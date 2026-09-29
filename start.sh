#!/usr/bin/env bash
# One-command start for macOS / Linux: sets up everything on first run, then opens the app.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
PY="$(command -v python3.13 || command -v python3.12 || command -v python3 || true)"
[ -n "$PY" ] || { echo "[WebPilot] Python 3.12+ not found: https://www.python.org/downloads/"; exit 1; }

if [ ! -x .venv/bin/python ]; then
  echo "[WebPilot] First run: creating the Python environment..."
  "$PY" -m venv .venv
  echo "[WebPilot] Installing dependencies (1-2 minutes)..."
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
fi
[ -f .env ] || cp .env.example .env

# Browser: Playwright's Chromium, or an installed Google Chrome if the download fails.
if [ ! -f .venv/.chromium-ok ] && ! grep -q '^BROWSER_CHANNEL=' .env; then
  echo "[WebPilot] Installing the Chromium browser..."
  if .venv/bin/python -m playwright install chromium >/dev/null 2>&1; then
    touch .venv/.chromium-ok
  else
    echo "[WebPilot] Chromium download failed, using Google Chrome instead."
    echo "BROWSER_CHANNEL=chrome" >> .env
  fi
fi

echo
echo "[WebPilot] Starting on http://localhost:$PORT"
echo "[WebPilot] Optional: paste a free Gemini key in .env (GEMINI_API_KEY=...) to give it any task on any site."
echo "[WebPilot] Press Ctrl+C to stop."
echo
[ -n "${NO_BROWSER:-}" ] || ( sleep 4; (command -v open >/dev/null && open "http://localhost:$PORT") || (command -v xdg-open >/dev/null && xdg-open "http://localhost:$PORT") || true ) &
exec .venv/bin/python -m uvicorn app.main:app --port "$PORT"
