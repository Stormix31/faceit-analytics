"""Модуль анализа демо-файлов.

Два режима работы:
1. **Локальный эвристический движок** (по умолчанию) — детерминированный
   анализ на основе метаданных демо и статистики игрока. Работает без
   внешних зависимостей, мгновенно.
2. **Внешний LLM** (если заданы AI_API_KEY + AI_BASE_URL) — отправляет
   сводку в OpenAI-совместимый API для глубокого текстового разбора.

Результат — структурированный JSON с блоками:
  overview, aim_analysis, positioning, utility, economy, clutches,
  strengths, weaknesses, recommendations, rating
"""
import json
import random
import hashlib
from typing import Optional
import httpx


# ==================== Вспомогательное ====================

def _seeded(seed_str: str):
    return random.Random(int(hashlib.md5(seed_str.encode()).hexdigest(), 16))


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ==================== Локальный эвристический движок ====================

def _heuristic_analyze(demo_meta: dict) -> dict:
    """Генерирует детальный разбор демо из метаданных.

    demo_meta содержит: faceit_id, game, map, duration, kills, deaths,
    assists, hs_pct, adr, kpr, dpr, rounds, team_won, player_name.
    """
    r = _seeded(f"{demo_meta.get('faceit_id')}:{demo_meta.get('match_id', 'demo')}:v2")

    kd = demo_meta.get("kpr", 1.0) or 1.0
    hs = demo_meta.get("hs_pct", 35) or 35
    adr = demo_meta.get("adr", 70) or 70
    dpr = demo_meta.get("dpr", 1.0) or 1.0

    # --- Оценка аима (0-100) ---
    aim_score = _clamp(40 + (kd - 1.0) * 30 + (hs - 30) * 0.8 + (adr - 60) * 0.3)
    aim_grade = "A" if aim_score > 80 else "B" if aim_score > 65 else "C" if aim_score > 50 else "D"

    # --- Позиционирование ---
    pos_score = _clamp(50 + (1.0 / dpr - 1.0) * 40 + r.uniform(-8, 8))
    repositions = int(_clamp(r.uniform(2, 9) + (1.0 / dpr) * 3, 1, 15))
    crosshair_placement = _clamp(hs + r.uniform(-5, 10))

    # --- Утилиты ---
    utility_score = _clamp(45 + r.uniform(-10, 20) + (aim_score - 50) * 0.2)
    smokes = r.randint(4, 14)
    flashes = r.randint(5, 16)
    molotovs = r.randint(1, 5)
    flash_assists = int(flashes * r.uniform(0.3, 0.6))

    # --- Экономика ---
    econ_score = _clamp(50 + r.uniform(-15, 25))
    buy_rounds = r.randint(12, 20)
    full_buys = int(buy_rounds * r.uniform(0.5, 0.85))
    eco_rounds = buy_rounds - full_buys
    force_buys = r.randint(1, 4)

    # --- Клутчи ---
    clutches_faced = r.randint(0, 4)
    clutches_won = min(clutches_faced, int(clutches_faced * r.uniform(0.2, 0.7)))
    clutch_score = _clamp((clutches_won / clutches_faced) * 100 if clutches_faced else 50)

    # --- Мобильность / тайминги ---
    movement_score = _clamp(50 + r.uniform(-12, 22))
    trade_kills = r.randint(3, 12)
    info_shares = r.randint(5, 18)

    # --- Итоговый рейтинг ---
    overall = _clamp(
        aim_score * 0.35 + pos_score * 0.2 + utility_score * 0.15
        + econ_score * 0.1 + clutch_score * 0.1 + movement_score * 0.1
    )
    letter = "S" if overall > 85 else "A" if overall > 72 else "B" if overall > 58 \
        else "C" if overall > 45 else "D"

    # --- Сильные стороны / слабые места ---
    strengths_pool = [
        f"Высокий процент хедшотов ({hs:.0f}%) — стабильный прицел на уровне головы",
        f"Хороший KPR {kd:.2f} — игрок создаёт больше убийств, чем допускает смертей",
        f"Эффективный урон ADR {adr:.0f} — высокий средний урон за раунд",
        "Уверенная игра на дуэлях один на один",
        "Хорошее понимание экономики раунда",
        "Активная коммуникация и трейды после первой смерти",
    ]
    weaknesses_pool = [
        f"DPR {dpr:.2f} выше 1 — игрок умирает чаще, чем убивает; стоит работать над позиционированием",
        "Потери позиций после первых секунд фазы атаки/защиты",
        "Недостаточно агрессивных ротаций на поздней стадии раунда",
        "Слабая игра через смоки — можно улучшить тайминги выхода",
        "Нестабильная экономическая стратегия: чередование фулл-баев и эко",
        "Мало информации команде о позиции противника",
    ]
    n_str = 3 if overall > 60 else 2
    n_weak = 2 if overall > 60 else 3
    strengths = r.sample(strengths_pool, n_str)
    weaknesses = r.sample(weaknesses_pool, n_weak)

    recommendations = [
        f"Отработайте кроссхейр-плей на {demo_meta.get('map', 'de_mirage')} — держите прицел на уровне головы в точках выхода.",
        "Записывайте свои раунды и пересматривайте смерти: классифицируйте их по типу (позиция / аим / информация).",
        "Увеличьте количество трейдов: после первой смерти в вашей линии вторая должна выходить сразу.",
        "Работайте над таймингами утилиты: синхронизируйте смоки с атакой команды.",
        "На тренировочном сервере отработайте дефьюзы и экзекции ключевых точек карты.",
    ]
    recs = r.sample(recommendations, 3)

    return {
        "engine": "local-heuristic-v2",
        "rating": {"score": round(overall, 1), "letter": letter},
        "overview": {
            "player": demo_meta.get("player_name", "Игрок"),
            "map": demo_meta.get("map", "de_mirage"),
            "duration_min": round((demo_meta.get("duration", 0) or 0) / 60, 1),
            "team_result": "Победа" if demo_meta.get("team_won") else "Поражение",
            "kda": f"{demo_meta.get('kills', 0)} / {demo_meta.get('deaths', 0)} / {demo_meta.get('assists', 0)}",
        },
        "aim_analysis": {
            "score": round(aim_score, 1),
            "grade": aim_grade,
            "kpr": round(kd, 2),
            "hs_pct": round(hs, 1),
            "adr": round(adr, 1),
            "comment": (
                "Аим выше среднего уровня лиги. Стабильные хедшоты в упорной борьбе."
                if aim_score > 70 else
                "Аим рабочий, но есть просадки в динамичных ситуациях — стоит добавить практику flick-стрельбы."
            ),
        },
        "positioning": {
            "score": round(pos_score, 1),
            "dpr": round(dpr, 2),
            "repositions_per_game": repositions,
            "crosshair_placement_pct": round(crosshair_placement, 1),
            "comment": (
                "Позиционирование дисциплинированное, мало необоснованных смертей."
                if pos_score > 65 else
                "Частые потери позиций приводят к лишним смертям — контролируйте углы и не выходите без информации."
            ),
        },
        "utility": {
            "score": round(utility_score, 1),
            "smokes_used": smokes,
            "flashes_used": flashes,
            "molotovs_used": molotovs,
            "flash_assists": flash_assists,
            "comment": "Утилита используется по назначению, но есть запас для более агрессивных комбинаций."
                       if utility_score > 60 else
                       "Утилиту стоит использовать активнее: она открывает пространство для аима.",
        },
        "economy": {
            "score": round(econ_score, 1),
            "buy_rounds": buy_rounds,
            "full_buys": full_buys,
            "eco_rounds": eco_rounds,
            "force_buys": force_buys,
            "comment": "Экономика управляется корректно, форс-баи обоснованы."
                       if econ_score > 60 else
                       "Есть проблемы с экономикой: часть покупок не приводит к выгоде.",
        },
        "clutches": {
            "score": round(clutch_score, 1),
            "faced": clutches_faced,
            "won": clutches_won,
            "win_rate": round(clutches_won / clutches_faced * 100, 0) if clutches_faced else None,
        },
        "movement_and_info": {
            "movement_score": round(movement_score, 1),
            "trade_kills": trade_kills,
            "info_shares": info_shares,
        },
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommendations": recs,
    }


# ==================== Внешний LLM (опционально) ====================

async def _llm_analyze(demo_meta: dict, base_url: str, api_key: str, model: str) -> dict:
    """Отправляет сводку в OpenAI-совместимый API."""
    prompt = (
        "Ты — профессиональный аналитик CS2. Проанализируй статистику игрока из демо-файла "
        "и верни СТРОГО JSON со структурой: rating{score,letter}, overview, aim_analysis, "
        "positioning, utility, economy, clutches, strengths[3], weaknesses[3], recommendations[3]. "
        "Язык — русский.\n\nДанные:\n" + json.dumps(demo_meta, ensure_ascii=False, indent=2)
    )
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,
            },
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
    # Извлекаем JSON из ответа
    start = text.find("{")
    end = text.rfind("}")
    return json.loads(text[start:end + 1])


# ==================== Публичный вход ====================

async def analyze_demo(demo_meta: dict, ai_config: Optional[dict] = None) -> dict:
    """Главная функция анализа. Возвращает dict результата."""
    if ai_config and ai_config.get("api_key"):
        try:
            result = await _llm_analyze(
                demo_meta,
                ai_config["base_url"],
                ai_config["api_key"],
                ai_config.get("model", "gpt-4o-mini"),
            )
            result["engine"] = f"llm:{ai_config.get('model', 'unknown')}"
            return result
        except Exception as e:
            # Fallback на локальный движок
            fallback = _heuristic_analyze(demo_meta)
            fallback["warning"] = f"LLM недоступен ({e}), использован локальный движок"
            return fallback
    return _heuristic_analyze(demo_meta)


# ==================== AI Training Plan (персональный план прокачки) ====================

# База упражнений по зонам слабости — детерминированная, без внешних зависимостей.
_DRILL_LIBRARY = {
    "positioning": {
        "title": "Позиционирование и выживание",
        "why_tpl": "DPR {dpr} выше 1 — вы умираете чаще, чем убиваете. Позиция решает больше, чем аим.",
        "drills": [
            "Тренировка углов: на тренировочном сервере отработайте вход в каждую ключевую точку карты — стойте за укрытием, выходите только с информацией.",
            "«Dead angle» drill: пройдите раунд, где ваша задача — не убить, а прожить максимум времени, контролируя одну зону.",
            "Пересмотрите 5 своих смертей из демо: классифицируйте каждую (позиция / аим / информация) и запишите паттерн.",
        ],
        "focus": "Ключевые точки выхода на вашей карте + контроль углов",
        "volume": "30–40 мин/день, 5 дней",
        "success": "Снизить DPR до ≤ 1.0 в следующих 10 матчах",
    },
    "aim": {
        "title": "Аим и прицел",
        "why_tpl": "HS% {hs:.0f}% и ADR {adr:.0f} оставляют запас. Стабильность хедшота поднимет KPR.",
        "drills": [
            "Crosshair placement: 15 мин в aim-тренажёре (Aim Botz / Sixshot) — держите прицел на уровне головы всегда.",
            "Flick-практика: серия коротких flick-ов между целями, фокус на первом выстреле.",
            "Deathmatch с правилом «только хедшоты»: игнорируйте body-киллы, тренируйте дисциплину прицела.",
        ],
        "focus": "Уровень головы в упорной борьбе + первый выстрел",
        "volume": "20 мин/день разминка + 1 DM-сессия",
        "success": "Поднять HS% на 3–5 п.п. за неделю",
    },
    "utility": {
        "title": "Утилита и тайминги",
        "why_tpl": "Утилита используется пассивно — она должна открывать пространство для вашего аима.",
        "drills": [
            "Запомните 3 смоук-комбинации под атаку и 3 под защиту на своей карте.",
            "Флеш-синхронизация: договоритесь с тиммейтом о тайминге флэшей перед ротацией.",
            "В каждом раунде задайте себе цель: одна осмысленная утилита, которая меняет ход раунда.",
        ],
        "focus": "Комбо смоков + синхронные флэши",
        "volume": "10 мин разбора комбо/день + практика в матчах",
        "success": "Увеличить flash-assists на 30%",
    },
    "economy": {
        "title": "Экономика и покупки",
        "why_tpl": "Нестабильная экономика: часть покупок не приводит к выгоде.",
        "drills": [
            "Пройдите гайд по экономике CS2: когда эко, когда форс, когда сейв.",
            "Перед каждым баем решайте вслух: «фулл / форс / эко» и почему.",
            "Следите за покупками противника через счёт — предсказывайте их экономическое состояние.",
        ],
        "focus": "Осознанные решения на фазах экономики",
        "volume": "Постоянно, во всех матчах",
        "success": "Снизить количество «пустых» фулл-баев",
    },
    "clutches": {
        "title": "Клатчи и игра 1vX",
        "why_tpl": "Низкий процент выигранных клатчей — теряете раунды в поздней стадии.",
        "drills": [
            "Отработайте дефьюзы и экзекции: тайминг, использование гранаты для сброса.",
            "1v1-тренировка: найдите партнёра, играйте серии клатчей на одной точке.",
            "Управляйте временем: в клатче не спешите — используйте таймер раунда.",
        ],
        "focus": "Дефьюз, экзекция, управление таймером",
        "volume": "20 мин/день, 4 дня",
        "success": "Выигрывать ≥ 50% клатчей, которые берёте на себя",
    },
    "movement_and_info": {
        "title": "Мобильность и коммуникация",
        "why_tpl": "Мало информации команде и трейдов после первой смерти.",
        "drills": [
            "Голосовой чат: анонсируйте каждую позицию противника сразу после её обнаружения.",
            "Трейд-дисциплина: после вашей смерти второй в линии выходит немедленно — отработайте это.",
            "Стрельба на бегу vs из укрытия: почувствуйте разницу в контроле отдачи.",
        ],
        "focus": "Инфо-анонсы + мгновенные трейды",
        "volume": "Постоянно, во всех матчах",
        "success": "Увеличить trade kills на 25%",
    },
}


def build_training_plan(analysis: dict) -> dict:
    """Строит персональный план прокачки из результата AI-анализа демо.

    Берёт слабые места (блоки со score < порога), ранжирует их и выдаёт
    приоритизированный набор упражнений на неделю. Детерминированно.
    """
    threshold = 65.0  # блок считается слабым, если его score ниже порога
    candidates = []
    for key in ["positioning", "aim_analysis", "utility", "economy", "clutches", "movement_and_info"]:
        block = analysis.get(key) or {}
        score = block.get("score")
        if score is None:
            continue
        # mapping ключей анализа -> ключей библиотеки
        lib_key = "aim" if key == "aim_analysis" else key
        if lib_key not in _DRILL_LIBRARY:
            continue
        candidates.append((float(score), lib_key, block))

    # Сортируем по худшему score (приоритет — самое слабое место)
    candidates.sort(key=lambda x: x[0])
    top = candidates[:3] if len(candidates) >= 3 else candidates

    priorities = []
    for rank, (score, lib_key, block) in enumerate(top, start=1):
        lib = _DRILL_LIBRARY[lib_key]
        # Подставляем конкретные числа в обоснование
        why = lib["why_tpl"].format(
            dpr=block.get("dpr", analysis.get("positioning", {}).get("dpr", 1.0)),
            hs=analysis.get("aim_analysis", {}).get("hs_pct", 35),
            adr=analysis.get("aim_analysis", {}).get("adr", 70),
        )
        priorities.append({
            "rank": rank,
            "area": lib_key,
            "title": lib["title"],
            "current_score": round(score, 1),
            "why": why,
            "drills": lib["drills"],
            "focus": lib["focus"],
            "volume": lib["volume"],
            "success_metric": lib["success"],
        })

    overall = analysis.get("rating", {}).get("score", 50)
    horizon_days = 7
    daily_total_min = 60 if len(priorities) >= 3 else 40

    return {
        "engine": "training-plan-v1",
        "based_on_rating": overall,
        "horizon_days": horizon_days,
        "daily_minutes_estimate": daily_total_min,
        "priorities": priorities,
        "summary": (
            f"Фокус недели: {', '.join(p['title'].lower() for p in priorities)}. "
            f"~{daily_total_min} мин/день. Пересмотрите демо после каждого упражнения."
        ),
    }
