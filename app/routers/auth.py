"""Роуты авторизации и аккаунта."""
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field

from app.database import get_db
from app.models import User, LoginAttempt
from app.security import (
    hash_password, verify_password, create_access_token, decode_access_token,
    captcha_store, rate_limiter, get_client_ip,
)
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/api/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ==================== Схемы ====================

class RegisterIn(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    captcha_token: str | None = None
    captcha_answer: str | None = None


class CaptchaOut(BaseModel):
    token: str
    question: str


class MeOut(BaseModel):
    id: int
    email: str
    username: str
    subscription_tier: str
    faceit_id: str | None
    free_demo_analyses_used: int
    is_admin: bool


# ==================== Капча ====================

@router.get("/captcha", response_model=CaptchaOut)
async def get_captcha(request: Request):
    """Выдаёт новую математическую капчу."""
    ip = get_client_ip(request)
    if not rate_limiter.check(f"cap:{ip}", 10, 60):
        raise HTTPException(429, "Слишком много запросов капчи")
    return captcha_store.generate()


def _check_login_captcha(request: Request, body: LoginIn):
    """Принудительно проверяет капчу при включённом режиме или после N неудачных попыток."""
    ip = get_client_ip(request)
    recent_failures = rate_limiter.count_recent(f"loginfail:{ip}", 900)
    need_captcha = settings.CAPTCHA_ENABLED or recent_failures >= settings.CAPTCHA_TRIGGER_THRESHOLD
    if need_captcha:
        if not (body.captcha_token and body.captcha_answer):
            raise HTTPException(400, detail="CAPTCHA_REQUIRED")
        if not captcha_store.verify(body.captcha_token, body.captcha_answer):
            raise HTTPException(400, detail="Неверный ответ на капчу")


# ==================== Регистрация ====================

@router.post("/register", status_code=201)
async def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    ip = get_client_ip(request)
    if not rate_limiter.check(f"reg:{ip}", 5, 3600):
        raise HTTPException(429, "Слишком много регистраций с этого IP")

    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, "Email уже зарегистрирован")
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(409, "Имя пользователя занято")

    user = User(
        email=body.email,
        username=body.username,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id), "username": user.username})
    return {"access_token": token, "token_type": "bearer", "user": _me_dict(user)}


# ==================== Логин ====================

@router.post("/login")
async def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = get_client_ip(request)
    # Rate limit на логин: 5 попыток в 15 минут с одного IP
    if not rate_limiter.check(f"login:{ip}", settings.RATE_LIMIT_LOGIN_PER_15MIN, 900):
        raise HTTPException(429, "Слишком много попыток входа. Попробуйте через 15 минут.")

    _check_login_captcha(request, body)

    user = db.query(User).filter(User.email == body.email).first()
    ok = user is not None and verify_password(body.password, user.hashed_password)

    db.add(LoginAttempt(ip_address=ip, email=body.email, success=ok))
    db.commit()

    if not ok:
        rate_limiter._hits.setdefault(f"loginfail:{ip}", []).append(time.time())
        raise HTTPException(401, "Неверный email или пароль")
    if not user.is_active:
        raise HTTPException(403, "Аккаунт деактивирован")

    token = create_access_token({"sub": str(user.id), "username": user.username})
    return {"access_token": token, "token_type": "bearer", "user": _me_dict(user)}


# ==================== Текущий пользователь ====================

def current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_access_token(token)
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(401, "Пользователь не найден")
    return user


def _me_dict(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "username": u.username,
        "subscription_tier": u.subscription_tier,
        "faceit_id": u.faceit_id,
        "free_demo_analyses_used": u.free_demo_analyses_used,
        "is_admin": u.is_admin,
    }


@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(current_user)):
    return _me_dict(user)


# ==================== Привязка Faceit ID ====================

class FaceitLinkIn(BaseModel):
    faceit_id: str = Field(min_length=8, max_length=64)


@router.post("/link-faceit")
async def link_faceit(body: FaceitLinkIn, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    other = db.query(User).filter(User.faceit_id == body.faceit_id, User.id != user.id).first()
    if other:
        raise HTTPException(409, "Этот Faceit ID уже привязан к другому аккаунту")
    user.faceit_id = body.faceit_id
    db.commit()
    return {"ok": True, "faceit_id": user.faceit_id}
