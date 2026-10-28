"""Конфигурация приложения Faceit Analytics."""
import os
from functools import lru_cache


class Settings:
    # --- Общее ---
    APP_NAME: str = "Faceit Analytics"
    VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # --- БД ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite:///./faceit_analytics.db"
    )

    # --- JWT / безопасность ---
    SECRET_KEY: str = os.getenv(
        "SECRET_KEY",
        "change-me-in-production-use-a-long-random-string-min-32-chars"
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

    # --- Faceit API ---
    FACEIT_API_KEY: str = os.getenv("FACEIT_API_KEY", "")
    FACEIT_BASE_URL: str = "https://api.faceit.com"
    # Сколько секунд кэшировать ответ Faceit API
    FACEIT_CACHE_TTL: int = int(os.getenv("FACEIT_CACHE_TTL", "300"))

    # --- AI-анализ демо ---
    # Токен для внешнего LLM/API анализа (опционально). Если пусто —
    # используется локальный эвристический движок.
    AI_API_KEY: str = os.getenv("AI_API_KEY", "")
    AI_BASE_URL: str = os.getenv("AI_BASE_URL", "")
    AI_MODEL: str = os.getenv("AI_MODEL", "local-heuristic")

    # --- Платная модель анализа демо ---
    DEMO_ANALYSIS_PRICE: float = float(os.getenv("DEMO_ANALYSIS_PRICE", "99.0"))
    # Сколько бесплатных анализов демо доступно каждому пользователю
    FREE_DEMO_ANALYSES: int = 1

    # --- Анти-DDoS / Rate limiting ---
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    RATE_LIMIT_LOGIN_PER_15MIN: int = int(os.getenv("RATE_LIMIT_LOGIN_PER_15MIN", "5"))
    CAPTCHA_ENABLED: bool = os.getenv("CAPTCHA_ENABLED", "true").lower() == "true"
    # Порог запросов после которого включается капча на вход
    CAPTCHA_TRIGGER_THRESHOLD: int = int(os.getenv("CAPTCHA_TRIGGER_THRESHOLD", "3"))

    @property
    def faceit_api_configured(self) -> bool:
        return bool(self.FACEIT_API_KEY)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
