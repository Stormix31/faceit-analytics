"""Безопасность: JWT, пароли, капча, rate limiting."""
import time
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Request, HTTPException
from app.config import get_settings

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ==================== Пароли ====================

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ==================== JWT ====================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Недействительный токен: {e}")


# ==================== Капча (простая математическая) ====================

class CaptchaStore:
    """В-памяти хранилище капч с TTL. Для продакшена — Redis."""
    _store: dict[str, tuple[str, float]] = {}  # token -> (answer, expiry)
    TTL = 300  # секунд

    @classmethod
    def generate(cls) -> dict:
        a = secrets.randbelow(20) + 1
        b = secrets.randbelow(20) + 1
        op = secrets.choice(["+", "-", "*"])
        if op == "+":
            answer = str(a + b)
            question = f"{a} + {b} = ?"
        elif op == "-":
            answer = str(abs(a - b))
            question = f"{max(a,b)} − {min(a,b)} = ?"
        else:
            answer = str(a * b)
            question = f"{a} × {b} = ?"

        token = secrets.token_urlsafe(24)
        cls._store[token] = (answer, time.time() + cls.TTL)
        # Очистка устаревших
        now = time.time()
        expired = [k for k, (_, exp) in cls._store.items() if exp < now]
        for k in expired:
            del cls._store[k]
        return {"token": token, "question": question}

    @classmethod
    def verify(cls, token: str, answer: str) -> bool:
        entry = cls._store.pop(token, None)
        if entry is None:
            return False
        stored_answer, expiry = entry
        if time.time() > expiry:
            return False
        return stored_answer == answer.strip()


captcha_store = CaptchaStore()


# ==================== Rate Limiting (анти-DDoS) ====================

class RateLimiter:
    """Простой sliding-window rate limiter по IP в памяти."""
    _hits: dict[str, list[float]] = {}

    @classmethod
    def check(cls, key: str, max_per_window: int, window_seconds: int) -> bool:
        now = time.time()
        hits = cls._hits.get(key, [])
        # Убираем старые
        hits = [t for t in hits if now - t < window_seconds]
        if len(hits) >= max_per_window:
            cls._hits[key] = hits
            return False
        hits.append(now)
        cls._hits[key] = hits
        return True

    @classmethod
    def count_recent(cls, key: str, window_seconds: int) -> int:
        now = time.time()
        hits = cls._hits.get(key, [])
        return sum(1 for t in hits if now - t < window_seconds)


rate_limiter = RateLimiter()


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
