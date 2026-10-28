"""Роуты системы миссий и очков."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.routers.auth import current_user
from app import missions as M

router = APIRouter(prefix="/api/missions", tags=["missions"])


@router.get("")
async def my_missions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Состояние миссий текущего пользователя на эту неделю + баланс очков."""
    return M.get_missions_state(db, user)


@router.post("/scan-wins")
async def scan_wins(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Сканирует историю матчей привязанного профиля и засчитывает победы."""
    result = await M.scan_wins(db, user)
    if not result.get("ok"):
        raise HTTPException(409, detail=result)
    return result


# ==================== Хуки событий из других модулей ====================

@router.post("/events/demo/{demo_id}")
async def event_demo(demo_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Засчитывает AI-анализ демо как событие миссии."""
    from app.models import DemoAnalysis
    rec = db.get(DemoAnalysis, demo_id)
    if rec is None or rec.user_id != user.id or rec.status != "completed":
        raise HTTPException(404, "Анализ не найден или не завершён")
    res = M.record_event(db, user, "demo_analysis", ref_id=f"demo:{rec.id}",
                         occurred_at=rec.uploaded_at, meta={"map": rec.map_name})
    return res


@router.post("/events/compare")
async def event_compare(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Засчитывает сравнение профилей. Пара нормализуется для дедупликации."""
    a = (body.get("player_a") or "").strip().lower()
    b = (body.get("player_b") or "").strip().lower()
    if not a or not b or a == b:
        raise HTTPException(400, "Нужны два разных faceit_id")
    pair = "|".join(sorted([a, b]))  # A|B == B|A
    res = M.record_event(db, user, "compare", ref_id=f"cmp:{pair}",
                         meta={"a": a, "b": b})
    return res


@router.post("/events/snapshot/{snapshot_id}")
async def event_snapshot(snapshot_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Засчитывает снимок статистики как событие миссии."""
    from app.models import StatSnapshot
    snap = db.get(StatSnapshot, snapshot_id)
    if snap is None or snap.user_id != user.id:
        raise HTTPException(404, "Снимок не найден")
    res = M.record_event(db, user, "snapshot", ref_id=f"snap:{snap.id}",
                         occurred_at=snap.taken_at)
    return res


# ==================== Лидерборд и награды ====================

@router.get("/leaderboard")
async def leaderboard(month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
                      db: Session = Depends(get_db)):
    """Лидерборд: текущий месяц — живой рейтинг, прошлые — архив топ-100."""
    return M.get_leaderboard(db, month)


@router.get("/rewards")
async def rewards(month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
                  db: Session = Depends(get_db)):
    """Очередь наград месяца (топ-5) со статусами активации."""
    return M.get_rewards(db, month)


@router.post("/rewards/activate")
async def activate_reward(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Активация награды топ-5. В проде — только админ; здесь открыта для теста.

    Body: {"month": "YYYY-MM", "rank": 1..5}
    Награда активируется по faceit_id получателя вручную оператором FACEIT —
    сервис фиксирует факт активации.
    """
    if not user.is_admin:
        raise HTTPException(403, "Только администратор может активировать награды")
    mk = body.get("month")
    rank = body.get("rank")
    if not mk or not isinstance(rank, int) or not (1 <= rank <= M.REWARD_TOP_N):
        raise HTTPException(400, "Нужны month='YYYY-MM' и rank=1..5")
    result = M.activate_reward(db, mk, rank)
    if not result.get("ok"):
        raise HTTPException(409, detail=result)
    return result
