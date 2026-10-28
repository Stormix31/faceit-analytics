@echo off
REM Faceit Analytics - quick start (Windows)
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Install it from https://www.python.org/downloads/
  echo         and tick "Add Python to PATH" during setup. Then run this again.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo Creating virtual environment .venv ...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo Installing dependencies (first run only, ~1 min) ...
pip install -q -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed. Check your internet connection and try again.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   Faceit Analytics is starting...
echo   Open in browser:  http://localhost:8000
echo   API docs:         http://localhost:8000/docs
echo   Stop server:      Ctrl+C
echo ============================================================
echo.
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
