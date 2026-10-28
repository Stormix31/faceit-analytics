"""Faceit Analytics — точка входа приложения."""
import time
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from app.config import get_settings
from app.database import init_db
from app.security import rate_limiter, get_client_ip
from app.routers import auth, players, demos, contacts, progress, missions

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="Аналитический сервис для игроков Faceit: профили, статистика, "
                "AI-анализ демо, сравнение игроков.",
)

# --- CORS (для раздельного деплоя фронтенда) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # в проде — конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Глобальный rate limit (анти-DDoS) по IP ---
@app.middleware("http")
async def global_rate_limit(request: Request, call_next):
    ip = get_client_ip(request)
    path = request.url.path
    # Статика и капча не лимитируем жёстко
    if not path.startswith("/api/"):
        return await call_next(request)
    if not rate_limiter.check(f"global:{ip}", settings.RATE_LIMIT_PER_MINUTE, 60):
        return JSONResponse(
            status_code=429,
            content={"detail": "Превышен лимит запросов. Попробуйте через минуту."},
            headers={"Retry-After": "60"},
        )
    return await call_next(request)


# --- Запуск БД при старте ---
@app.on_event("startup")
async def on_startup():
    init_db()


# --- Роутеры ---
app.include_router(auth.router)
app.include_router(players.router)
app.include_router(demos.router)
app.include_router(contacts.router)
app.include_router(progress.router)
app.include_router(missions.router)


# --- Прочие API ---
@app.get("/api/health", tags=["meta"])
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.VERSION}


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse("static/index.html")


# --- Статика фронтенда ---
app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)
