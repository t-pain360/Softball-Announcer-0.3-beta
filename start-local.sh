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
export PYTHONNOUSERSITE=1

"$PYTHON" -m pip install --upgrade pip >/dev/null

if ! "$PYTHON" -c 'import fastapi, uvicorn, soundfile, neuttsair' >/dev/null 2>&1; then
  echo "Installing the pinned NeuTTS Air runtime into .venv..."
  "$PYTHON" -m pip install --upgrade --force-reinstall -r tts/requirements.txt
fi

if ! "$PYTHON" -c 'import fastapi, uvicorn, soundfile, neuttsair; from torchao.dtypes.nf4tensor import NF4Tensor' >/dev/null 2>&1; then
  echo "ERROR: NeuTTS Air runtime verification failed."
  echo "Python: $PYTHON"
  "$PYTHON" -c 'import sys; print("sys.executable:", sys.executable); print("sys.path:"); print("\n".join(sys.path))'
  "$PYTHON" -m pip show neutts neucodec torch torchaudio torchao torchtune || true
  exit 1
fi

# Resolve an already-downloaded gated Q4 GGUF into a filesystem path. NeuTTS
# passes a filesystem path directly to llama.cpp, so once the model exists in
# the Hugging Face cache startup is completely local and does not re-authenticate.
export NEUTTS_BACKBONE="$($PYTHON - <<'PY'
from pathlib import Path
try:
    from huggingface_hub import try_to_load_from_cache
    repo = "neuphonic/neutts-air-q4-gguf"
    filename = "neutts-air-Q4_0.gguf"
    cached = try_to_load_from_cache(repo_id=repo, filename=filename)
    if cached and Path(cached).is_file():
        print(cached)
    else:
        print(repo)
except Exception:
    print("neuphonic/neutts-air-q4-gguf")
PY
)"

export NEUTTS_PYTHON="$PYTHON"
export NODE_ENV="${NODE_ENV:-development}"

echo ""
echo "🥎 Softball Announcer — Local Version"
echo "   No OpenAI or Gemini API key required."
echo "   TTS: NeuTTS Air (local)"
echo "   NeuTTS backbone: $NEUTTS_BACKBONE"
echo "   Node: $(node --version)"
echo "   Python: $("$PYTHON" --version 2>&1)"
echo ""

cleanup() {
  if [ -n "${APP_PID:-}" ] && kill -0 "$APP_PID" 2>/dev/null; then
    kill "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

npm run dev &
APP_PID=$!

wait "$APP_PID"
