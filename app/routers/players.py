"""Роуты профилей Faceit: профиль, статистика, матчи, оружие, прогноз, аномалии, сравнение."""
from fastapi import APIRouter, Query
from app.faceit_api import (
    get_player, get_player_stats, get_player_matches, get_player_weapons, is_demo_mode,
)
from app.matchup import predict_matchup_by_ids
from app.anomaly import detect_anomalies

router = APIRouter(prefix="/api/players", tags=["players"])


@router.get("/status")
async def api_status():
    """Статус подключения к Faceit API."""
    return {
        "demo_mode": is_demo_mode(),
        "note": ("Faceit API key не задан — данные синтетические (демо-режим)."
                 if is_demo_mode() else "Подключено к реальному Faceit API."),
    }


@router.get("/{faceit_id}")
async def player_profile(faceit_id: str):
    """Профиль игрока Faceit."""
    return await get_player(faceit_id)


@router.get("/{faceit_id}/stats")
async def player_stats(faceit_id: str, game: str = Query("cs2")):
    """Сводная статистика игрока по игре."""
    return await get_player_stats(faceit_id, game)


@router.get("/{faceit_id}/matches")
async def player_matches(
    faceit_id: str,
    game: str = Query("cs2"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Последние матчи игрока."""
    items = await get_player_matches(faceit_id, game, limit, offset)
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/{faceit_id}/weapons")
async def player_weapons(faceit_id: str, game: str = Query("cs2")):
    """Статистика по оружию: K/D и HS% по каждой пушке."""
    return await get_player_weapons(faceit_id, game)


@router.get("/{faceit_id}/anomaly")
async def player_anomaly(faceit_id: str, game: str = Query("cs2")):
    """Детект аномалий в статистике (флаги подозрительных значений)."""
    stats = await get_player_stats(faceit_id, game)
    result = detect_anomalies(stats)
    result["faceit_id"] = faceit_id
    return result


# ==================== Прогноз матча A vs B ====================

@router.post("/predict")
async def predict_match(body: dict):
    """Прогноз матча двух игроков по их статистике.

    Body: {"player_a": "<faceit_id>", "player_b": "<faceit_id>", "game": "cs2"}
    """
    a_id = (body.get("player_a") or "").strip()
    b_id = (body.get("player_b") or "").strip()
    game = body.get("game", "cs2")
    if not a_id or not b_id:
        return {"error": "Нужны оба faceit_id"}
    if a_id == b_id:
        return {"error": "Нельзя прогнозировать матч игрока с самим собой"}
    return await predict_matchup_by_ids(a_id, b_id, game)


# ==================== Сравнение двух профилей ====================

COMPARE_KEYS = [
    ("matches", "Матчей сыграно", ",.0f", False),
    ("win_rate", "Win Rate", ".1%", True),
    ("kd", "K/D", ".2f", True),
    ("kpr", "KPR", ".2f", True),
    ("dpr", "DPR", ".2f", False),  # меньше = лучше
    ("hs_pct", "Headshot %", ".1f", True),
    ("adr", "ADR", ".1f", True),
    ("mvps", "MVP за игру", ",.0f", True),
    ("first_kills_pct", "First Kill %", ".1%", True),
    ("clutch_won", "Выиграно клатчей", ",.0f", True),
]


@router.post("/compare")
async def compare_profiles(body: dict):
    """Сравнивает двух игроков по ключевым метрикам.

    Body: {"player_a": "<faceit_id>", "player_b": "<faceit_id>", "game": "cs2"}
    Возвращает таблицу метрик + вердикт по каждой строке.
    """
    a_id = (body.get("player_a") or "").strip()
    b_id = (body.get("player_b") or "").strip()
    game = body.get("game", "cs2")
    if not a_id or not b_id:
        return {"error": "Нужны оба faceit_id"}
    if a_id == b_id:
        return {"error": "Нельзя сравнивать игрока с самим собой"}

    pa, pb = await get_player(a_id), await get_player(b_id)
    sa, sb = await get_player_stats(a_id, game), await get_player_stats(b_id, game)

    rows = []
    a_points = b_points = 0
    for key, label, fmt, higher_is_better in COMPARE_KEYS:
        va, vb = sa.get(key, 0), sb.get(key, 0)
        try:
            va_f, vb_f = float(va), float(vb)
        except (TypeError, ValueError):
            continue
        if va_f == vb_f:
            winner = None
        elif (va_f > vb_f) == higher_is_better:
            winner = "a"
            a_points += 1
        else:
            winner = "b"
            b_points += 1
        rows.append({
            "key": key, "label": label,
            "a": va_f, "b": vb_f,
            "display_a": _fmt(va_f, fmt), "display_b": _fmt(vb_f, fmt),
            "winner": winner,
        })

    verdict = "Ровный матч по статистике" if a_points == b_points else (
        f"{pa['name']} выглядит сильнее по {max(a_points, b_points)} из {a_points + b_points} метрик"
    )
    return {
        "player_a": {"id": a_id, "name": pa["name"], "country": pa.get("country_code"),
                     "rank_tier": sa.get("rank_tier")},
        "player_b": {"id": b_id, "name": pb["name"], "country": pb.get("country_code"),
                     "rank_tier": sb.get("rank_tier")},
        "game": game,
        "rows": rows,
        "points": {"a": a_points, "b": b_points},
        "verdict": verdict,
    }


def _fmt(v: float, fmt: str) -> str:
    """Форматирует значение по спецификации format() (без фигурных скобок)."""
    try:
        return format(v, fmt)
    except Exception:
        return str(v)
