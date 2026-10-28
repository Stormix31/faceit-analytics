"""Детект аномалий в статистике игрока (в духе CSWatch watchlist).

Флагит подозрительно высокие значения, которые редко встречаются у
честных игроков: аномально высокий HS%, K/D вне реалистичного диапазона,
высокий ADR при низком количестве матчей и т.п. Это эвристики на порогах —
не обвинение, а «стоит посмотреть внимательнее».
"""

# (ключ, порог, направление, подпись)
_RULES = [
    ("hs_pct", 65.0, "above", "Очень высокий процент хедшотов (>65%)"),
    ("kd",     3.0,  "above", "K/D выше 3.0 — редкое значение для лиги"),
    ("adr",    120.0,"above", "ADR выше 120 — аномально высокий урон за раунд"),
    ("kpr",    2.8,  "above", "KPR выше 2.8"),
    ("win_rate", 0.78, "above", "Win Rate выше 78% — подозрительно стабильно"),
]


def detect_anomalies(stats: dict) -> dict:
    """Проверяет статистику по набору правил. Возвращает список флагов."""
    flags = []
    for key, threshold, direction, label in _RULES:
        try:
            v = float(stats.get(key))
        except (TypeError, ValueError):
            continue
        if direction == "above" and v > threshold:
            severity = "high" if v > threshold * 1.3 else "medium"
            flags.append({
                "key": key,
                "value": v,
                "threshold": threshold,
                "severity": severity,
                "label": label,
            })
        elif direction == "below" and v < threshold:
            flags.append({
                "key": key,
                "value": v,
                "threshold": threshold,
                "severity": "medium",
                "label": label,
            })

    # Дополнительное правило: мало матчей + отличные цифры = слабый сигнал
    matches = stats.get("matches") or 0
    if 0 < matches < 50 and (stats.get("kd", 0) or 0) > 2.0:
        flags.append({
            "key": "low_sample",
            "value": matches,
            "threshold": 50,
            "severity": "low",
            "label": "Мало сыгранных матчей (<50) при высоком K/D — малая выборка",
        })

    has_high = any(f["severity"] == "high" for f in flags)
    # suspicious: есть high-флаг ИЛИ 3+ флага средней важности (совпадение по нескольким метрикам)
    status = "suspicious" if (has_high or len(flags) >= 3) else ("watch" if flags else "clean")
    return {
        "status": status,
        "flags_count": len(flags),
        "flags": flags,
        "note": "Автоматическая эвристика. Флаги — повод присмотреться, не вердикт.",
    }
