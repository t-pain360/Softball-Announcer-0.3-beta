#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

command -v node >/dev/null 2>&1 || { echo "Node.js is required."; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "npm is required."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "Python 3 is required."; exit 1; }
command -v espeak-ng >/dev/null 2>&1 || command -v espeak >/dev/null 2>&1 || {
  echo "eSpeak NG is required by NeuTTS Air. Install it with: sudo apt install espeak-ng"
  exit 1
}

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

"$PYTHON" -m pip install --upgrade pip >/dev/null

# Current NeuTTS Air is published as the `neutts` Python package. The
# `neuttsair` module remains the API used by the NeuTTS Air examples.
if ! "$PYTHON" -c 'import fastapi, uvicorn, soundfile, neuttsair' >/dev/null 2>&1; then
  echo "Installing NeuTTS Air and local API dependencies..."
  "$PIP" install -r tts/requirements.txt
fi

if ! "$PYTHON" -c 'import fastapi, uvicorn, soundfile, neuttsair' >/dev/null 2>&1; then
  echo "ERROR: NeuTTS Air installation could not be verified."
  echo "Python: $PYTHON"
  echo "Try: $PYTHON -c 'import neuttsair; print(neuttsair.__file__)'"
  exit 1
fi

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
echo "   TTS: NeuTTS Air (local)"
echo "   Node: $(node --version)"
echo "   Python: $("$PYTHON" --version 2>&1)"
echo ""

npm run dev &
APP_PID=$!

wait "$APP_PID"
