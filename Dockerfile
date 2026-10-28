# Faceit Analytics — production Docker image
FROM python:3.12-slim AS base

# Не root — безопасность
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Системные зависимости (для bcrypt)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Python-зависимости (отдельный слой — кэшируется)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY app/ ./app/
COPY static/ ./static/

# Каталоги для загруженных демо и БД
RUN mkdir -p uploads data && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
