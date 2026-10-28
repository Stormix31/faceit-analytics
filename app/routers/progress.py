"""Роуты трекера прогресса: снапшоты статистики и тренды во времени."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import User, StatSnapshot
from app.routers.auth import current_user
from app.faceit_api import get_player_stats

router = APIRouter(prefix="/api/progress", tags=["progress"])

# Метрики для трендов: (ключ снапшота, подпись, выше_лучше)
TREND_METRICS = [
    ("win_rate", "Win Rate %", True),
    ("kd", "K/D", True),
    ("hs_pct", "Headshot %", True),
    ("adr", "ADR", True),
    ("kpr", "KPR", True),
    ("dpr", "DPR", False),  # ниже лучше
]


class SnapshotIn(BaseModel):
    faceit_id: str | None = None   # если не задан — берём привязанный user.faceit_id
    game: str = "cs2"


@router.get("/status")
async def progress_status(user: User = Depends(current_user)):
    """Есть ли у пользователя привязанный профиль / снапшоты."""
    return {
        "linked_faceit_id": user.faceit_id,
        "snapshots_count": len(user.stat_snapshots),
    }


@router.post("/snapshot", status_code=201)
async def take_snapshot(body: SnapshotIn, user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    """Делает снимок текущей статистики игрока."""
    faceit_id = (body.faceit_id or user.faceit_id or "").strip()
    if not faceit_id:
        raise HTTPException(400, "Укажите faceit_id или привяжите профиль в настройках входа")

    stats = await get_player_stats(faceit_id, body.game)
    snap = StatSnapshot(
        user_id=user.id,
        faceit_id=faceit_id,
        game_name=body.game,
        source="manual",
        win_rate=stats.get("win_rate"),
        kd=stats.get("kd"),
        kpr=stats.get("kpr"),
        dpr=stats.get("dpr"),
        hs_pct=stats.get("hs_pct"),
        adr=stats.get("adr"),
        matches=stats.get("matches"),
        mvps=stats.get("mvps"),
        stats_json=stats,
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    # Авто-хук: снимок засчитывается в миссии
    try:
        from app import missions as M
        M.record_event(db, user, "snapshot", ref_id=f"snap:{snap.id}",
                       occurred_at=snap.taken_at)
    except Exception:
        pass
    return _snapshot_dict(snap, prev=None)


@router.get("/history")
async def history(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Серия снапшотов с дельтами к предыдущему (новые — в конце)."""
    snaps = sorted(user.stat_snapshots, key=lambda s: s.taken_at or s.id)
    out = []
    prev = None
    for s in snaps:
        out.append(_snapshot_dict(s, prev))
        prev = s
    return out


def _snapshot_dict(s: StatSnapshot, prev: StatSnapshot | None) -> dict:
    d = {
        "id": s.id,
        "taken_at": s.taken_at.isoformat() if s.taken_at else None,
        "game": s.game_name,
        "source": s.source,
        "win_rate": s.win_rate,
        "kd": s.kd,
        "kpr": s.kpr,
        "dpr": s.dpr,
        "hs_pct": s.hs_pct,
        "adr": s.adr,
        "matches": s.matches,
        "mvps": s.mvps,
    }
    # Дельты к предыдущему снапшоту
    if prev is not None:
        d["delta"] = {
            "win_rate": _round3(s.win_rate, prev.win_rate),
            "kd": _round3(s.kd, prev.kd),
            "hs_pct": _round3(s.hs_pct, prev.hs_pct),
            "adr": _round3(s.adr, prev.adr),
            "matches": (s.matches or 0) - (prev.matches or 0),
        }
    return d


def _round3(cur, old):
    if cur is None or old is None:
        return None
    return round(cur - old, 3)


@router.get("/trends")
async def trends(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Данные для графиков: оси X (даты) + серии по каждой метрике.

    Вторая наложенная серия — рейтинги из AI-анализов демо (если есть).
    """
    snaps = sorted(user.stat_snapshots, key=lambda s: s.taken_at or s.id)
    labels = [
        (s.taken_at.strftime("%d.%m %H:%M") if s.taken_at else f"#{s.id}")
        for s in snaps
    ]
    series = {}
    for key, _label, _better in TREND_METRICS:
        series[key] = [getattr(s, key) for s in snaps]

    # Рейтинги демо как отдельная серия (0-100)
    from app.models import DemoAnalysis
    demos = (
        db.query(DemoAnalysis)
        .filter(DemoAnalysis.user_id == user.id, DemoAnalysis.status == "completed")
        .order_by(DemoAnalysis.uploaded_at.asc())
        .all()
    )
    demo_labels = [d.uploaded_at.strftime("%d.%m %H:%M") if d.uploaded_at else "" for d in demos]
    demo_ratings = [((d.result_json or {}).get("rating") or {}).get("score") for d in demos]

    return {
        "labels": labels,
        "series": series,
        "metrics": [{"key": k, "label": l, "higher_is_better": h} for k, l, h in TREND_METRICS],
        "demo_ratings": {"labels": demo_labels, "values": demo_ratings},
        "count": len(snaps),
    }
