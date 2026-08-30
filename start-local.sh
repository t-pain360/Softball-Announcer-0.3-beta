#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

command -v node >/dev/null 2>&1 || { echo "Node.js is required."; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "npm is required."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "Python 3 is required."; exit 1; }

if [ ! -d node_modules ]; then
  echo "Installing Node dependencies..."
  npm install
fi

if [ ! -d .venv ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv .venv
fi

PYTHON="$ROOT/.venv/bin/python"
PIP="$ROOT/.venv/bin/pip"

if ! "$PYTHON" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
  echo "Installing NeuTTS Python dependencies..."
  "$PIP" install -r tts/requirements.txt
fi

# Allow the Node server to manage the NeuTTS process itself. This avoids
# requiring users to start a second terminal/service.
export NEUTTS_PYTHON="$PYTHON"
export NODE_ENV="${NODE_ENV:-development}"

cleanup() {
  if [ -n "${APP_PID:-}" ] && kill -0 "$APP_PID" 2>/dev/null; then
    kill "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo ""
echo "🥎 Softball Announcer — Local Version"
echo "   No OpenAI or Gemini API key required."
echo "   Node: $(node --version)"
echo "   Python: $("$PYTHON" --version 2>&1)"
echo ""

npm run dev &
APP_PID=$!

wait "$APP_PID"
