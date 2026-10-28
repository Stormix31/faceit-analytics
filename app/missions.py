"""Система еженедельных миссий и очков.

Механика:
  - Каждую ISO-неделю у пользователя активен каталог миссий (победы, демо-анализы,
    сравнения, снимки прогресса). Выполнение миссии начисляет очки.
  - Очки копятся в месячном балансе (user.points_balance), аудит — в points_ledger.
  - В конце месяца баланс сбрасывается автоматически (лениво, при первом запросе
    нового месяца), топ-100 фиксируется в monthly_standings, топ-5 получает
    награду со статусом pending (активация по faceit_id — админским действием).

Анти-абьюз:
  1. Идемпотентность: событие (user, type, ref) засчитывается один раз
     (UniqueConstraint на уровне БД).
  2. Дневные капы событий по типу.
  3. Burst-детект побед: N побед за время короче N×25 мин → флаг, не идёт в зачёт.
  4. Недельный кап очков.
  5. Кулдаун сканирования матчей (10 мин).
  6. Сравнения: пара игроков нормализуется (A|B == B|A), дневной кап уникальных пар.
"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models import (
    User, MissionEvent, MissionProgress, PointsLedger, MonthlyStandings, MissionMeta,
)
from app.faceit_api import get_player_matches

# ==================== Периоды ====================

def week_key(dt: datetime) -> str:
    """ISO-неделя: 'YYYY-Www'."""
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def prev_month(mk: str) -> str:
    y, m = map(int, mk.split("-"))
    m -= 1
    if m == 0:
        m, y = 12, y - 1
    return f"{y}-{m:02d}"


def next_month(mk: str) -> str:
    y, m = map(int, mk.split("-"))
    m += 1
    if m == 13:
        m, y = 1, y + 1
    return f"{y}-{m:02d}"


# ==================== Каталог миссий ====================

# key, название, описание, тип события, цель, очки
MISSION_CATALOG = [
    ("win_10",      "Серия побед",          "Одержи 10 побед в матчах",              "win",           10, 100),
    ("win_20",      "Доминация",            "Одержи 20 побед в матчах",              "win",           20, 250),
    ("demo_1",      "Первый разбор",        "Проведи 1 AI-анализ демо",              "demo_analysis", 1,  50),
    ("demo_3",      "Исследователь",        "Проведи 3 AI-анализа демо",             "demo_analysis", 3,  120),
    ("compare_5",   "Разведчик",            "Сравни 5 профилей игроков",             "compare",       5,  60),
    ("snapshot_3",  "Контроль прогресса",   "Сделай 3 снимка своей статистики",      "snapshot",      3,  40),
]

# ==================== Параметры анти-абьюза ====================

DAILY_CAPS = {"win": 12, "demo_analysis": 5, "compare": 10, "snapshot": 3}
WEEKLY_POINT_CAP = 650          # максимум очков за неделю
SCAN_COOLDOWN_SECONDS = 600     # кулдаун сканирования матчей
WIN_BURST_MINUTES_PER_WIN = 25  # реальная игра длится дольше; 10 побед < 250 мин = подозрительно
WIN_BURST_THRESHOLD = 8         # от 8 побед включаем проверку размаха
REWARD_TOP_N = 5                # топ-5 месяца получают награду
LEADERBOARD_SIZE = 100


# ==================== Месячный цикл ====================

def _meta_get(db: Session, key: str):
    row = db.get(MissionMeta, key)
    return row.value if row else None


def _meta_set(db: Session, key: str, value: str):
    row = db.get(MissionMeta, key)
    if row:
        row.value = value
    else:
        db.add(MissionMeta(key=key, value=value))


def _close_month(db: Session, mk: str):
    """Закрывает месяц: архивирует топ-100, помечает топ-5 наградой, сбрасывает балансы."""
    users = (
        db.query(User)
        .filter(User.last_points_month == mk, User.points_balance > 0)
        .order_by(User.points_balance.desc())
        .all()
    )
    top = users[:LEADERBOARD_SIZE]
    for rank, u in enumerate(top, start=1):
        db.add(MonthlyStandings(
            month_key=mk, rank=rank, user_id=u.id, username=u.username,
            faceit_id=u.faceit_id, points=u.points_balance,
            reward_status="pending" if rank <= REWARD_TOP_N else "none",
            reward_note=(f"Faceit Premium → faceit_id={u.faceit_id or 'НЕ ПРИВЯЗАН'}"
                         if rank <= REWARD_TOP_N else None),
        ))
    # Сброс балансов всех участников месяца
    for u in users:
        old = u.points_balance
        db.add(PointsLedger(
            user_id=u.id, delta=-old, reason="month_reset", ref=f"month:{mk}",
            balance_after=0, month_key=next_month(mk),
        ))
        u.points_balance = 0
        u.last_points_month = None
    _meta_set(db, "last_closed_month", mk)


def ensure_current_month(db: Session, now: datetime | None = None):
    """Ленивое закрытие прошедших месяцев."""
    now = now or datetime.utcnow()
    cur = month_key(now)
    last_closed = _meta_get(db, "last_closed_month")
    if last_closed is None:
        # Первый запуск: считаем текущий месяц открытым, прошлых нет
        _meta_set(db, "last_closed_month", prev_month(cur))
        return
    guard = 0
    while last_closed < cur and guard < 24:
        last_closed = next_month(last_closed)
        _close_month(db, last_closed)
        guard += 1
    db.commit()


# ==================== Начисление очков ====================

def _weekly_points(db: Session, user: User, wk: str) -> int:
    rows = (
        db.query(MissionProgress)
        .filter(MissionProgress.user_id == user.id, MissionProgress.week_key == wk)
        .all()
    )
    return sum(r.points_awarded for r in rows)


def _award_points(db: Session, user: User, points: int, reason: str, ref: str,
                  now: datetime) -> int:
    """Начисляет очки с учётом недельного капа. Возвращает фактически начисленное."""
    wk = week_key(now)
    used = _weekly_points(db, user, wk)
    allowed = max(0, WEEKLY_POINT_CAP - used)
    actual = min(points, allowed)
    if actual <= 0:
        return 0
    user.points_balance = (user.points_balance or 0) + actual
    user.last_points_month = month_key(now)
    db.add(PointsLedger(
        user_id=user.id, delta=actual, reason=reason, ref=ref,
        balance_after=user.points_balance, month_key=month_key(now),
    ))
    return actual


# ==================== Запись событий (ядро) ====================

def record_event(db: Session, user: User, event_type: str, ref_id: str | None,
                 occurred_at: datetime | None = None, meta: dict | None = None) -> dict:
    """Записывает событие, обновляет прогресс миссий, начисляет очки.

    Возвращает {"status": "new"|"duplicate"|"flagged"|"capped", ...}
    """
    now = datetime.utcnow()
    ts = occurred_at or now
    ensure_current_month(db, now)

    # --- Идемпотентность ---
    if ref_id:
        existing = (
            db.query(MissionEvent)
            .filter(MissionEvent.user_id == user.id,
                    MissionEvent.event_type == event_type,
                    MissionEvent.ref_id == ref_id)
            .first()
        )
        if existing:
            return {"status": "duplicate", "event_id": existing.id}

    # --- Дневной кап ---
    day_start = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    day_count = (
        db.query(MissionEvent)
        .filter(MissionEvent.user_id == user.id,
                MissionEvent.event_type == event_type,
                MissionEvent.occurred_at >= day_start,
                MissionEvent.occurred_at < day_start + timedelta(days=1))
        .count()
    )
    cap = DAILY_CAPS.get(event_type)
    if cap is not None and day_count >= cap:
        ev = _insert_event(db, user, event_type, ref_id, ts, meta,
                           flagged=True, reason="daily_cap")
        return {"status": "capped", "event_id": ev.id}

    # --- Burst-детект для побед ---
    flagged, flag_reason = False, None
    if event_type == "win":
        recent = (
            db.query(MissionEvent)
            .filter(MissionEvent.user_id == user.id,
                    MissionEvent.event_type == "win",
                    MissionEvent.flagged.is_(False),
                    MissionEvent.occurred_at <= ts,
                    MissionEvent.occurred_at >= ts - timedelta(hours=6))
            .order_by(MissionEvent.occurred_at.desc())
            .limit(WIN_BURST_THRESHOLD)
            .all()
        )
        if len(recent) >= WIN_BURST_THRESHOLD:
            oldest = recent[-1].occurred_at
            span_min = (ts - oldest).total_seconds() / 60
            needed = len(recent) * WIN_BURST_MINUTES_PER_WIN
            if span_min < needed:
                flagged, flag_reason = True, "burst_pattern"

    ev = _insert_event(db, user, event_type, ref_id, ts, meta, flagged, flag_reason)

    if flagged:
        return {"status": "flagged", "event_id": ev.id, "reason": flag_reason}

    # --- Обновление прогресса миссий ---
    wk = week_key(ts)
    awarded_total = 0
    for mkey, _title, _desc, etype, target, points in MISSION_CATALOG:
        if etype != event_type:
            continue
        prog = (
            db.query(MissionProgress)
            .filter(MissionProgress.user_id == user.id,
                    MissionProgress.mission_key == mkey,
                    MissionProgress.week_key == wk)
            .first()
        )
        if prog is None:
            prog = MissionProgress(user_id=user.id, mission_key=mkey, week_key=wk,
                                   progress=0, target=target)
            db.add(prog)
        if prog.completed_at is not None or prog.progress >= target:
            continue
        prog.progress += 1
        if prog.progress >= target:
            prog.completed_at = now
            got = _award_points(db, user, points, "mission_completed",
                                ref=f"progress:{prog.id}", now=now)
            prog.points_awarded = got
            awarded_total += got

    db.commit()
    return {"status": "new", "event_id": ev.id, "points_awarded": awarded_total,
            "balance": user.points_balance}


def _insert_event(db: Session, user: User, event_type: str, ref_id, ts: datetime,
                  meta, flagged=False, reason=None) -> MissionEvent:
    ev = MissionEvent(
        user_id=user.id, event_type=event_type, ref_id=ref_id,
        occurred_at=ts, week_key=week_key(ts), month_key=month_key(ts),
        flagged=flagged, flag_reason=reason, meta_json=meta,
    )
    db.add(ev)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(MissionEvent)
            .filter(MissionEvent.user_id == user.id,
                    MissionEvent.event_type == event_type,
                    MissionEvent.ref_id == ref_id)
            .first()
        )
        if existing:
            existing.flagged = existing.flagged or flagged
            db.commit()
            return existing
        raise
    return ev


# ==================== Сканирование побед из истории матчей ====================

async def scan_wins(db: Session, user: User, limit: int = 30) -> dict:
    """Сканирует последние матчи привязанного профиля и засчитывает победы."""
    now = datetime.utcnow()
    if user.last_mission_scan_at and \
       (now - user.last_mission_scan_at).total_seconds() < SCAN_COOLDOWN_SECONDS:
        wait = SCAN_COOLDOWN_SECONDS - (now - user.last_mission_scan_at).total_seconds()
        return {"ok": False, "cooldown_seconds": int(wait)}
    if not user.faceit_id:
        return {"ok": False, "error": "Привяжите Faceit ID в настройках аккаунта"}

    matches = await get_player_matches(user.faceit_id, "cs2", limit=limit)
    stats = {"scanned": len(matches), "wins_found": 0, "new": 0,
             "duplicate": 0, "flagged": 0, "capped": 0, "points": 0}
    for m in matches:
        if m.get("result") != "won":
            continue
        stats["wins_found"] += 1
        ts = None
        raw_date = m.get("date")
        if raw_date:
            try:
                ts = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                ts = None
        res = record_event(db, user, "win", ref_id=str(m.get("match_id")),
                           occurred_at=ts, meta={"score": m.get("score"), "map": m.get("map")})
        stats[res["status"]] = stats.get(res["status"], 0) + 1
        stats["points"] += res.get("points_awarded", 0)
    user.last_mission_scan_at = now
    db.commit()
    stats["ok"] = True
    stats["balance"] = user.points_balance
    return stats


# ==================== Чтение состояния ====================

def get_missions_state(db: Session, user: User, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    ensure_current_month(db, now)
    wk = week_key(now)
    mkey = month_key(now)

    progs = {
        p.mission_key: p
        for p in db.query(MissionProgress)
        .filter(MissionProgress.user_id == user.id, MissionProgress.week_key == wk)
        .all()
    }
    missions = []
    for mkey_, title, desc, etype, target, points in MISSION_CATALOG:
        p = progs.get(mkey_)
        progress = p.progress if p else 0
        done = bool(p and p.completed_at is not None)
        missions.append({
            "key": mkey_, "title": title, "description": desc,
            "event_type": etype, "target": target, "points": points,
            "progress": min(progress, target), "completed": done,
            "awarded": (p.points_awarded if p else 0),
        })

    # Когда наступит следующий сброс (первое число следующего месяца)
    nxt = next_month(mkey)
    ny, nm = map(int, nxt.split("-"))
    reset_dt = datetime(ny, nm, 1)
    days_to_reset = max(0, (reset_dt - now).days)

    return {
        "week_key": wk,
        "month_key": mkey,
        "missions": missions,
        "points_balance": user.points_balance or 0,
        "weekly_points": _weekly_points(db, user, wk),
        "weekly_point_cap": WEEKLY_POINT_CAP,
        "days_to_reset": days_to_reset,
        "has_faceit_link": bool(user.faceit_id),
        "scan_cooldown_seconds": (
            max(0, SCAN_COOLDOWN_SECONDS - (now - user.last_mission_scan_at).total_seconds())
            if user.last_mission_scan_at else 0
        ),
    }


def get_leaderboard(db: Session, month: str | None = None,
                    now: datetime | None = None) -> dict:
    """Актуальный месяц — живой рейтинг по балансу; прошлые — из архива."""
    now = now or datetime.utcnow()
    ensure_current_month(db, now)
    mk = month or month_key(now)
    if mk == month_key(now):
        users = (
            db.query(User)
            .filter(User.points_balance > 0)
            .order_by(User.points_balance.desc())
            .limit(LEADERBOARD_SIZE)
            .all()
        )
        entries = [
            {"rank": i, "username": u.username, "faceit_id": u.faceit_id,
             "points": u.points_balance, "reward_status": "live"}
            for i, u in enumerate(users, start=1)
        ]
        archived = False
    else:
        rows = (
            db.query(MonthlyStandings)
            .filter(MonthlyStandings.month_key == mk)
            .order_by(MonthlyStandings.rank.asc())
            .all()
        )
        entries = [
            {"rank": r.rank, "username": r.username, "faceit_id": r.faceit_id,
             "points": r.points, "reward_status": r.reward_status}
            for r in rows
        ]
        archived = True
    return {"month": mk, "archived": archived, "entries": entries}


def get_rewards(db: Session, month: str | None = None,
                now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    mk = month or month_key(now)
    rows = (
        db.query(MonthlyStandings)
        .filter(MonthlyStandings.month_key == mk,
                MonthlyStandings.reward_status != "none")
        .order_by(MonthlyStandings.rank.asc())
        .all()
    )
    return {
        "month": mk,
        "reward": "Faceit Premium (1 мес.)",
        "items": [
            {"rank": r.rank, "username": r.username, "faceit_id": r.faceit_id,
             "points": r.points, "status": r.reward_status, "note": r.reward_note}
            for r in rows
        ],
    }


def activate_reward(db: Session, month: str, rank: int) -> dict:
    """Админское действие: подтверждает активацию награды (по faceit_id вручную)."""
    row = (
        db.query(MonthlyStandings)
        .filter(MonthlyStandings.month_key == month, MonthlyStandings.rank == rank)
        .first()
    )
    if row is None:
        return {"ok": False, "error": "Награда не найдена"}
    if row.reward_status == "activated":
        return {"ok": False, "error": "Уже активирована"}
    row.reward_status = "activated"
    row.reward_note = (row.reward_note or "") + " · активировано " + datetime.utcnow().isoformat()
    db.commit()
    return {"ok": True, "rank": rank, "faceit_id": row.faceit_id, "status": "activated"}
