#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

command -v node >/dev/null 2>&1 || { echo "Node.js is required."; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "npm is required."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "Python 3 is required."; exit 1; }
command -v git >/dev/null 2>&1 || { echo "Git is required to install NeuTTS Air."; exit 1; }

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
NEUTTS_SRC="$ROOT/.local/neutts-air"

"$PYTHON" -m pip install --upgrade pip >/dev/null

# NeuTTS Air is currently distributed from its source repository rather than
# as a PyPI package named "neutts-air". Clone it locally and install its
# published Python dependencies into this app's venv.
if [ ! -f "$NEUTTS_SRC/neuttsair/neutts.py" ]; then
  echo "Installing NeuTTS Air source..."
  mkdir -p "$ROOT/.local"
  rm -rf "$NEUTTS_SRC"
  git clone --depth 1 https://github.com/Tavus-Engineering/neutts-air.git "$NEUTTS_SRC"
fi

if ! "$PYTHON" -c 'import fastapi, uvicorn, soundfile, neuttsair' >/dev/null 2>&1; then
  echo "Installing NeuTTS Air dependencies..."
  "$PIP" install -r "$NEUTTS_SRC/requirements.txt"
  "$PIP" install -e "$NEUTTS_SRC"
  "$PIP" install fastapi 'uvicorn[standard]' soundfile llama-cpp-python 'onnxruntime>=1.18,<2'
fi

if ! "$PYTHON" -c 'import fastapi, uvicorn, soundfile, neuttsair' >/dev/null 2>&1; then
  echo "ERROR: NeuTTS Air installation could not be verified."
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
