"""Модели базы данных Faceit Analytics."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class User(Base):
    """Пользователь сервиса."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(64), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- Подписка / платный контент ---
    subscription_tier = Column(String(32), default="free")  # free | pro
    subscription_expires = Column(DateTime, nullable=True)

    # --- Бесплатные демо-анализы ---
    free_demo_analyses_used = Column(Integer, default=0)

    # --- Привязанный профиль Faceit (опционально) ---
    faceit_id = Column(String(64), unique=True, nullable=True, index=True)

    # --- Система миссий / очки ---
    points_balance = Column(Integer, default=0)          # текущий баланс за месяц
    last_points_month = Column(String(7), nullable=True) # "YYYY-MM" последнего начисления/сброса
    last_mission_scan_at = Column(DateTime, nullable=True)  # для кулдауна сканирования

    demo_analyses = relationship("DemoAnalysis", back_populates="user")


class DemoAnalysis(Base):
    """Запись об анализе демо-файла."""
    __tablename__ = "demo_analyses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    # Метаданные демо
    game_name = Column(String(64), default="cs2")
    map_name = Column(String(64), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    file_size_mb = Column(Float, nullable=True)

    # Статус: pending -> processing -> completed | failed
    status = Column(String(16), default="pending")
    error_message = Column(Text, nullable=True)

    # Результат анализа (JSON с полной разбивкой)
    result_json = Column(JSON, nullable=True)
    summary_text = Column(Text, nullable=True)

    # Платёж
    was_paid = Column(Boolean, default=False)
    payment_ref = Column(String(64), nullable=True)

    user = relationship("User", back_populates="demo_analyses")


class ContactMessage(Base):
    """Сообщения из формы контактов."""
    __tablename__ = "contact_messages"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    email = Column(String(255), nullable=False)
    subject = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_read = Column(Boolean, default=False)


class LoginAttempt(Base):
    """Логи попыток входа — для анти-DDoS и капчи."""
    __tablename__ = "login_attempts"

    id = Column(Integer, primary_key=True, index=True)
    ip_address = Column(String(64), index=True)
    email = Column(String(255), nullable=True)
    success = Column(Boolean, default=False)
    attempted_at = Column(DateTime, default=datetime.utcnow)


class StatSnapshot(Base):
    """Снимок статистики игрока в определённый момент — основа трекера прогресса.

    Пользователь (или авто-хук после анализа демо) делает снапшот текущей
    статистики своего faceit_id; серия снапшотов даёт тренды во времени.
    """
    __tablename__ = "stat_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    faceit_id = Column(String(64), nullable=False, index=True)
    game_name = Column(String(32), default="cs2")
    taken_at = Column(DateTime, default=datetime.utcnow, index=True)
    # Инициатор: manual (кнопка) | demo (авто после анализа демо)
    source = Column(String(16), default="manual")

    # Ключевые метрики (числовые — удобно для трендов)
    win_rate = Column(Float, nullable=True)
    kd = Column(Float, nullable=True)
    kpr = Column(Float, nullable=True)
    dpr = Column(Float, nullable=True)
    hs_pct = Column(Float, nullable=True)
    adr = Column(Float, nullable=True)
    matches = Column(Integer, nullable=True)
    mvps = Column(Integer, nullable=True)

    # Полная сводка на момент снимка (для детального разбора)
    stats_json = Column(JSON, nullable=True)

    user = relationship("User", backref="stat_snapshots")


# ==================== Система миссий и очков ====================

class MissionEvent(Base):
    """Засчитанное событие игрока (победа / демо-анализ / сравнение и т.д.).

    Идемпотентность: уникальная пара (user_id, event_type, ref_id).
    Событие может быть помечено flagged анти-абьюзом — тогда оно не идёт в зачёт.
    """
    __tablename__ = "mission_events"
    __table_args__ = (
        UniqueConstraint("user_id", "event_type", "ref_id", name="uq_mission_event"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    event_type = Column(String(32), nullable=False, index=True)  # win | demo_analysis | compare | snapshot
    ref_id = Column(String(128), nullable=True, index=True)      # match_id / demo_id / "a|b"
    occurred_at = Column(DateTime, default=datetime.utcnow, index=True)
    week_key = Column(String(9), nullable=False, index=True)     # "YYYY-Www" ISO-неделя
    month_key = Column(String(7), nullable=False, index=True)    # "YYYY-MM"
    flagged = Column(Boolean, default=False)                     # помечено анти-абьюзом
    flag_reason = Column(String(128), nullable=True)
    meta_json = Column(JSON, nullable=True)


class MissionProgress(Base):
    """Прогресс пользователя по миссии за конкретную ISO-неделю."""
    __tablename__ = "mission_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "mission_key", "week_key", name="uq_mission_progress"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    mission_key = Column(String(48), nullable=False, index=True)  # e.g. "win_10"
    week_key = Column(String(9), nullable=False, index=True)      # "YYYY-Www"
    progress = Column(Integer, default=0)                          # текущее количество событий
    target = Column(Integer, default=0)                            # цель миссии
    completed_at = Column(DateTime, nullable=True)                 # когда выполнена
    points_awarded = Column(Integer, default=0)                    # сколько очков начислено


class PointsLedger(Base):
    """Аудит-леджер всех начислений/списаний очков (immutable)."""
    __tablename__ = "points_ledger"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    delta = Column(Integer, nullable=False)                        # +N или -N
    reason = Column(String(64), nullable=False)                    # mission_completed | month_reset | admin_adjust
    ref = Column(String(128), nullable=True)                       # ссылка на источник (progress id / event id)
    balance_after = Column(Integer, nullable=False)                # баланс после операции
    month_key = Column(String(7), nullable=False, index=True)     # "YYYY-MM"
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class MonthlyStandings(Base):
    """Архив месячного лидерборда (топ-100 с рангами)."""
    __tablename__ = "monthly_standings"
    __table_args__ = (
        UniqueConstraint("month_key", "rank", name="uq_monthly_rank"),
        UniqueConstraint("month_key", "user_id", name="uq_monthly_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    month_key = Column(String(7), nullable=False, index=True)     # "YYYY-MM"
    rank = Column(Integer, nullable=False)                         # 1..100
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    username = Column(String(64), nullable=False)
    faceit_id = Column(String(64), nullable=True)
    points = Column(Integer, nullable=False)
    reward_status = Column(String(16), default="none")            # none | pending | activated
    reward_note = Column(Text, nullable=True)


class MissionMeta(Base):
    """Метаданные системы: последний закрытый месяц, флаг инициализации."""
    __tablename__ = "mission_meta"

    key = Column(String(64), primary_key=True)
    value = Column(String(255), nullable=False)
