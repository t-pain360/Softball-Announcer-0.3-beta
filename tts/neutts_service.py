import base64
import os
from pathlib import Path
from functools import lru_cache

import soundfile as sf
from fastapi import FastAPI
from pydantic import BaseModel
from neuttsair.neutts import NeuTTSAir

HOST = os.getenv("NEUTTS_HOST", "127.0.0.1")
PORT = int(os.getenv("NEUTTS_PORT", "8011"))
REFERENCE_DIR = Path(os.getenv("NEUTTS_REFERENCE_DIR", "voices"))
BACKBONE = os.getenv("NEUTTS_BACKBONE", "neuphonic/neutts-air-q4-gguf")
CODEC = os.getenv("NEUTTS_CODEC", "neuphonic/neucodec")
BACKBONE_DEVICE = os.getenv("NEUTTS_BACKBONE_DEVICE", "cpu")
CODEC_DEVICE = os.getenv("NEUTTS_CODEC_DEVICE", "cpu")

# If the gated Q4 model has already been downloaded, use the local GGUF file
# directly. NeuTTS/llama.cpp supports a filesystem path and this prevents a
# startup health check from triggering another Hugging Face request.
if BACKBONE == "neuphonic/neutts-air-q4-gguf":
    try:
        from huggingface_hub import try_to_load_from_cache
        cached = try_to_load_from_cache(
            repo_id=BACKBONE,
            filename="neutts-air-Q4_0.gguf",
        )
        if cached and Path(cached).is_file():
            BACKBONE = cached
            print(f"Using cached local NeuTTS Air GGUF: {BACKBONE}", flush=True)
    except Exception as exc:
        print(f"NeuTTS cache lookup skipped: {exc}", flush=True)

app = FastAPI(title="Softball Announcer NeuTTS Air", docs_url=None, redoc_url=None)

print(f"Loading NeuTTS Air backbone: {BACKBONE}", flush=True)
tts = NeuTTSAir(
    backbone_repo=BACKBONE,
    backbone_device=BACKBONE_DEVICE,
    codec_repo=CODEC,
    codec_device=CODEC_DEVICE,
)

class SynthesisRequest(BaseModel):
    text: str
    voice: str = "classic"


def paths_for_voice(voice: str):
    safe = "".join(c for c in voice if c.isalnum() or c in "-_ ").strip().replace(" ", "-")
    return REFERENCE_DIR / f"{safe}.wav", REFERENCE_DIR / f"{safe}.txt"


@lru_cache(maxsize=16)
def reference_codes(voice: str):
    wav_path, txt_path = paths_for_voice(voice)
    if not wav_path.exists() or not txt_path.exists():
        raise FileNotFoundError(
            f"Missing NeuTTS reference for '{voice}'. Add {wav_path} and {txt_path}."
        )
    ref_text = txt_path.read_text(encoding="utf-8").strip()
    if not ref_text:
        raise ValueError(f"Reference transcript is empty: {txt_path}")
    return tts.encode_reference(str(wav_path)), ref_text


@app.get("/health")
def health():
    return {"ok": True, "engine": "neutts-air", "backbone": BACKBONE}


@app.post("/synthesize")
def synthesize(request: SynthesisRequest):
    text = request.text.strip()
    if not text:
        return {"error": "text is required"}
    try:
        ref_codes, ref_text = reference_codes(request.voice)
        wav = tts.infer(text, ref_codes, ref_text)
        output = Path("/tmp") / f"softball-neutts-{os.getpid()}.wav"
        sf.write(output, wav, 24000)
        audio = base64.b64encode(output.read_bytes()).decode("ascii")
        output.unlink(missing_ok=True)
        return {"audioBase64": audio, "voice": request.voice, "sampleRate": 24000}
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
