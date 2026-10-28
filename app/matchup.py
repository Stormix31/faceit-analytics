"""Прогноз матча A vs B по статистике игроков.

Модель: взвешенная разность нормализованных метрик двух игроков,
пропущенная через сигмоиду → вероятность победы A. Детерминированна,
без внешних зависимостей и обучения — веса подобраны вручную по смыслу
метрик (KPR/ADR важнее MVP-счёта).

В проде модель можно заменить на обученную (логистическая регрессия /
градиентный бустинг) на истории реальных матчей — интерфейс тот же.
"""
import math
from app.faceit_api import get_player_stats


# Метрика: (ключ, вес, способ нормализации)
# Нормализация приводит метрику к ~0..1 для типичного диапазона лиги.
_FEATURES = [
    ("kpr",  0.30, lambda v: min(1.0, max(0.0, (v - 0.6) / 1.2))),   # KPR 0.6..1.8
    ("adr",  0.25, lambda v: min(1.0, max(0.0, (v - 40) / 70))),     # ADR 40..110
    ("kd",   0.20, lambda v: min(1.0, max(0.0, (v - 0.5) / 1.3))),   # K/D 0.5..1.8
    ("hs_pct", 0.15, lambda v: min(1.0, max(0.0, (v - 20) / 35))),   # HS% 20..55
    ("win_rate", 0.10, lambda v: min(1.0, max(0.0, v))),            # WR 0..1
]


def _skill(stats: dict) -> float:
    """Скалярный «скилл» игрока из его метрик (0..~1)."""
    total = 0.0
    for key, weight, norm in _FEATURES:
        try:
            v = float(stats.get(key, 0))
        except (TypeError, ValueError):
            continue
        total += weight * norm(v)
    return total


def predict_matchup(stats_a: dict, stats_b: dict) -> dict:
    """Вероятность победы A и разбивка по вкладу каждой метрики."""
    sa, sb = _skill(stats_a), _skill(stats_b)
    diff = sa - sb
    # Сигмоида с температурой: разница в 0.15 скилла ≈ ±12% вероятности
    p_a = 1.0 / (1.0 + math.exp(-diff * 9.0))

    # Разбивка вклада по метрикам (для UI: что именно решает исход)
    contributions = []
    for key, weight, norm in _FEATURES:
        va = float(stats_a.get(key, 0) or 0)
        vb = float(stats_b.get(key, 0) or 0)
        delta = weight * (norm(va) - norm(vb))
        contributions.append({
            "key": key,
            "a": va, "b": vb,
            "edge": round(delta, 4),          # >0 — преимущество A
            "favors": "a" if delta > 0.005 else ("b" if delta < -0.005 else "draw"),
        })
    contributions.sort(key=lambda c: abs(c["edge"]), reverse=True)

    if p_a >= 0.55:
        verdict = f"Игрок A фаворит ({p_a*100:.0f}%)"
    elif p_a <= 0.45:
        verdict = f"Игрок B фаворит ({(1-p_a)*100:.0f}%)"
    else:
        verdict = f"Ровный матч ({p_a*100:.0f}% : {(1-p_a)*100:.0f}%)"

    return {
        "prob_a": round(p_a, 4),
        "prob_b": round(1 - p_a, 4),
        "skill_a": round(sa, 4),
        "skill_b": round(sb, 4),
        "verdict": verdict,
        "decisive_metrics": [c["key"] for c in contributions[:3]],
        "contributions": contributions,
        "model": "logistic-v1",
    }


async def predict_matchup_by_ids(faceit_id_a: str, faceit_id_b: str,
                                 game: str = "cs2") -> dict:
    """Удобная обёртка: загружает статистику обоих и строит прогноз."""
    sa = await get_player_stats(faceit_id_a, game)
    sb = await get_player_stats(faceit_id_b, game)
    result = predict_matchup(sa, sb)
    result["player_a"] = {"id": faceit_id_a, "stats": sa}
    result["player_b"] = {"id": faceit_id_b, "stats": sb}
    return result
