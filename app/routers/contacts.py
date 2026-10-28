"""Роуты контактной формы."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ContactMessage
from app.security import rate_limiter, get_client_ip

router = APIRouter(prefix="/api/contact", tags=["contact"])


class ContactIn(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    email: EmailStr
    subject: str | None = Field(default=None, max_length=255)
    message: str = Field(min_length=10, max_length=5000)


@router.post("", status_code=201)
async def send_message(body: ContactIn, request: Request, db: Session = Depends(get_db)):
    ip = get_client_ip(request)
    if not rate_limiter.check(f"contact:{ip}", 5, 3600):
        raise HTTPException(429, "Слишком много сообщений. Попробуйте позже.")

    msg = ContactMessage(
        name=body.name,
        email=body.email,
        subject=body.subject,
        message=body.message,
    )
    db.add(msg)
    db.commit()
    return {"ok": True, "id": msg.id,
            "message": "Сообщение отправлено. Мы ответим на ваш email в течение 24 часов."}


@router.get("/info")
async def contact_info():
    """Публичные контактные данные сервиса."""
    return {
        "email": "support@faceitanalytics.ru",
        "telegram": "@faceitanalytics_support",
        "discord": "discord.gg/faceitanalytics",
        "working_hours": "Пн–Пт, 10:00–19:00 МСК",
        "address": "г. Москва, ул. Примерная, д. 1, офис 42",
    }
