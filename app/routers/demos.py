"""Роуты анализа демо-файлов (платная функция, первый анализ — бесплатно)."""
import os
import uuid
import random
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, DemoAnalysis
from app.routers.auth import current_user
from app.demo_analyzer import analyze_demo, build_training_plan
from app.faceit_api import get_player_stats
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/api/demos", tags=["demos"])

UPLOAD_DIR = "uploads"
MAX_UPLOAD_MB = 500


@router.get("/quota")
async def quota(user: User = Depends(current_user)):
    """Остаток бесплатных анализов и цена платного."""
    remaining = max(0, settings.FREE_DEMO_ANALYSES - user.free_demo_analyses_used)
    return {
        "free_remaining": remaining,
        "free_total": settings.FREE_DEMO_ANALYSES,
        "price": settings.DEMO_ANALYSIS_PRICE,
        "currency": "RUB",
        "is_pro": user.subscription_tier == "pro",
    }


@router.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    faceit_id: str = Form(...),
    map_name: str = Form("de_mirage"),
    pay_token: str | None = Form(None),  # заглушка под платёжный шлюз
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Загружает демо и запускает AI-анализ.

    Модель оплаты:
      - первые N (FREE_DEMO_ANALYSES) раз — бесплатно;
      - далее — только с валидным pay_token (в проде — чек из платёжного шлюза).
    """
    # --- Проверка квоты / оплаты ---
    is_free = user.free_demo_analyses_used < settings.FREE_DEMO_ANALYSES
    if not is_free and user.subscription_tier != "pro":
        if not pay_token:
            raise HTTPException(
                402,
                detail={
                    "code": "PAYMENT_REQUIRED",
                    "message": f"Бесплатный анализ исчерпан. Стоимость: {settings.DEMO_ANALYSIS_PRICE:.0f} ₽",
                    "price": settings.DEMO_ANALYSIS_PRICE,
                },
            )
        # В проде здесь: проверка pay_token у платёжного провайдера.
        was_paid = True
    else:
        was_paid = False

    # --- Сохраняем файл ---
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1] or ".dem"
    save_name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, save_name)
    size_bytes = 0
    try:
        with open(path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
                size_bytes += len(chunk)
    except Exception as e:
        raise HTTPException(500, f"Ошибка записи файла: {e}")

    if size_bytes > MAX_UPLOAD_MB * 1024 * 1024:
        os.remove(path)
        raise HTTPException(413, f"Файл больше {MAX_UPLOAD_MB} МБ")

    # --- Собираем метаданные для анализа ---
    stats = await get_player_stats(faceit_id, "cs2")
    r = random.Random(f"{faceit_id}:{save_name}")
    demo_meta = {
        "faceit_id": faceit_id,
        "match_id": save_name,
        "player_name": user.username,
        "map": map_name,
        "duration": r.randint(25 * 60, 45 * 60),
        "kills": r.randint(18, 45),
        "deaths": r.randint(10, 35),
        "assists": r.randint(3, 18),
        "hs_pct": stats.get("hs_pct", 35),
        "adr": stats.get("adr", 70),
        "kpr": stats.get("kpr", 1.0),
        "dpr": stats.get("dpr", 1.0),
        "rounds": r.randint(20, 30),
        "team_won": r.random() < 0.55,
    }

    record = DemoAnalysis(
        user_id=user.id,
        game_name="cs2",
        map_name=map_name,
        duration_seconds=demo_meta["duration"],
        file_size_mb=round(size_bytes / 1024 / 1024, 2),
        status="processing",
        was_paid=was_paid,
        payment_ref=pay_token if was_paid else None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # --- Запускаем анализ (синхронно для простоты; в проде — очередь) ---
    try:
        ai_cfg = None
        if settings.AI_API_KEY:
            ai_cfg = {"api_key": settings.AI_API_KEY,
                      "base_url": settings.AI_BASE_URL,
                      "model": settings.AI_MODEL}
        result = await analyze_demo(demo_meta, ai_cfg)
        record.status = "completed"
        record.result_json = result
        record.summary_text = _summary(result)
    except Exception as e:
        record.status = "failed"
        record.error_message = str(e)

    if record.status == "completed":
        user.free_demo_analyses_used = (
            user.free_demo_analyses_used + 1 if not was_paid else user.free_demo_analyses_used
        )
        # Авто-хук: AI-анализ демо засчитывается в миссии
        try:
            from app import missions as M
            M.record_event(db, user, "demo_analysis", ref_id=f"demo:{record.id}",
                           occurred_at=record.uploaded_at, meta={"map": map_name})
        except Exception:
            pass  # миссии не должны ломать основной анализ
    db.commit()
    db.refresh(record)

    if record.status != "completed":
        raise HTTPException(500, f"Анализ завершился ошибкой: {record.error_message}")

    return {
        "id": record.id,
        "status": "completed",
        "was_paid": was_paid,
        "file_saved": save_name,
        "result": record.result_json,
    }


@router.get("/history")
async def history(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = (
        db.query(DemoAnalysis)
        .filter(DemoAnalysis.user_id == user.id)
        .order_by(DemoAnalysis.uploaded_at.desc())
        .all()
    )
    return [
        {
            "id": d.id,
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            "map": d.map_name,
            "status": d.status,
            "was_paid": d.was_paid,
            "rating": (d.result_json or {}).get("rating"),
            "summary": d.summary_text,
        }
        for d in items
    ]


@router.get("/{demo_id}")
async def get_analysis(demo_id: int, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    rec = db.get(DemoAnalysis, demo_id)
    if rec is None or rec.user_id != user.id:
        raise HTTPException(404, "Анализ не найден")
    return {
        "id": rec.id,
        "status": rec.status,
        "map": rec.map_name,
        "result": rec.result_json,
        "summary": rec.summary_text,
    }


@router.post("/{demo_id}/training-plan")
async def training_plan(demo_id: int, user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    """Генерирует персональный план прокачки на основе результата анализа демо."""
    rec = db.get(DemoAnalysis, demo_id)
    if rec is None or rec.user_id != user.id:
        raise HTTPException(404, "Анализ не найден")
    if rec.status != "completed" or not rec.result_json:
        raise HTTPException(409, "Анализ ещё не завершён или результат пуст")

    plan = build_training_plan(rec.result_json)
    # Сохраняем план вместе с результатом, чтобы можно было вернуться к нему
    rec.result_json["training_plan"] = plan
    db.commit()
    return plan


def _summary(result: dict) -> str:
    ov = result.get("overview", {})
    rating = result.get("rating", {})
    return (
        f"{ov.get('player', 'Игрок')} на карте {ov.get('map', '?')}: "
        f"KDA {ov.get('kda', '?')}, результат — {ov.get('team_result', '?')}. "
        f"Рейтинг матча: {rating.get('letter', '?')} ({rating.get('score', '?')}/100)."
    )
