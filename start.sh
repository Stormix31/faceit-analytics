#!/usr/bin/env bash
# Faceit Analytics — быстрый запуск (Linux/macOS)
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "→ Создаю виртуальное окружение .venv …"
  python3 -m venv .venv
fi
source .venv/bin/activate

echo "→ Устанавливаю зависимости …"
pip install -q -r requirements.txt

# Опционально: подхватим .env, если есть
if [ -f ".env" ]; then
  set -a; source .env; set +a
  echo "→ Подключён .env"
fi

echo ""
echo "✅ Запускаю Faceit Analytics → http://localhost:8000"
echo "   API-документация:            http://localhost:8000/docs"
echo "   Стоп: Ctrl+C"
echo ""
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
