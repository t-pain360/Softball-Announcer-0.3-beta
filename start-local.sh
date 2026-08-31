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

# Prevent a previous NeuTTS process from occupying port 8011 with an older
# copy of neutts_service.py. This is safe for this checkout because the match
# is the absolute path to this project's service file.
if command -v pkill >/dev/null 2>&1; then
  pkill -f "$ROOT/tts/neutts_service.py" 2>/dev/null || true
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

# NeuTTS Air is a voice-cloning model and requires a reference WAV plus its
# transcript. Seed the upstream Jo reference on first run so a fresh local
# checkout works immediately. Once downloaded, synthesis itself is local.
VOICE_DIR="$ROOT/voices"
mkdir -p "$VOICE_DIR"
if [ ! -s "$VOICE_DIR/jo.wav" ] || [ ! -s "$VOICE_DIR/jo.txt" ]; then
  echo "Installing the default NeuTTS reference voice (one-time)..."
  "$PYTHON" - <<'PY'
from pathlib import Path
from urllib.request import urlopen

root = Path("voices")
root.mkdir(exist_ok=True)
files = {
    "jo.wav": "https://raw.githubusercontent.com/neuphonic/neutts/main/samples/jo.wav",
    "jo.txt": "https://raw.githubusercontent.com/neuphonic/neutts/main/samples/jo.txt",
}
for name, url in files.items():
    target = root / name
    if target.is_file() and target.stat().st_size > 0:
        continue
    print(f"  downloading {name}...")
    with urlopen(url, timeout=60) as response:
        target.write_bytes(response.read())
PY
fi

# Keep the existing UI voice name "classic", but use the seeded Jo reference
# until the user supplies a dedicated announcer recording as classic.wav/txt.
if [ ! -s "$VOICE_DIR/classic.wav" ] || [ ! -s "$VOICE_DIR/classic.txt" ]; then
  cp "$VOICE_DIR/jo.wav" "$VOICE_DIR/classic.wav"
  cp "$VOICE_DIR/jo.txt" "$VOICE_DIR/classic.txt"
fi

export NEUTTS_PYTHON="$PYTHON"
export NEUTTS_MAX_CONTEXT_TOKENS="2048"
export NEUTTS_MIN_GENERATION_TOKENS="64"
export NODE_ENV="${NODE_ENV:-development}"

echo ""
echo "🥎 Softball Announcer — Local Version"
echo "   No OpenAI or Gemini API key required."
echo "   TTS: NeuTTS Air (local)"
echo "   NeuTTS context: ${NEUTTS_MAX_CONTEXT_TOKENS} tokens"
echo "   NeuTTS generation reserve: ${NEUTTS_MIN_GENERATION_TOKENS} tokens"
echo "   NeuTTS backbone: $NEUTTS_BACKBONE"
echo "   NeuTTS reference: $VOICE_DIR/classic.wav"
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
