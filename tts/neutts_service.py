import base64
import os
import re
from pathlib import Path
from functools import lru_cache

import numpy as np
import soundfile as sf
from fastapi import FastAPI
from pydantic import BaseModel
from neuttsair.neutts import NeuTTSAir

HOST = os.getenv("NEUTTS_HOST", "127.0.0.1")
PORT = int(os.getenv("NEUTTS_PORT", "8011"))
REFERENCE_DIR = Path(os.getenv("NEUTTS_REFERENCE_DIR", "voices"))
BACKBONE = os.getenv("NEUTTS_BACKBONE", "neuphonic/neutts-air-q4-gguf")
CODEC = os.getenv("NEUTTS_CODEC", "neuphonic/neucodec")
LANGUAGE = os.getenv("NEUTTS_LANGUAGE", "en-us")
BACKBONE_DEVICE = os.getenv("NEUTTS_BACKBONE_DEVICE", "cpu")
CODEC_DEVICE = os.getenv("NEUTTS_CODEC_DEVICE", "cpu")
# NeuTTS Air has a 2048-token context window INCLUDING the reference prompt.
# Keep chunks conservative. If a particular sentence still exceeds the model
# limit, synthesize_chunks() recursively splits it again on the exact error.
MAX_SYNTH_CHARS = int(os.getenv("NEUTTS_MAX_SYNTH_CHARS", "500"))

if BACKBONE == "neuphonic/neutts-air-q4-gguf":
    try:
        from huggingface_hub import try_to_load_from_cache
        cached = try_to_load_from_cache(repo_id=BACKBONE, filename="neutts-air-Q4_0.gguf")
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
    language=LANGUAGE,
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


def split_text(text: str, max_chars: int = MAX_SYNTH_CHARS):
    """Split text conservatively before calling NeuTTS Air."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate

        # A single sentence can itself be very long.
        while len(current) > max_chars:
            cut = current.rfind(" ", 0, max_chars + 1)
            if cut < max_chars // 2:
                cut = max_chars
            chunks.append(current[:cut].strip())
            current = current[cut:].strip()
    if current:
        chunks.append(current)
    return chunks


def synthesize_chunks(text, ref_codes, ref_text):
    """Synthesize with a retry that halves any chunk rejected by the model."""
    chunks = split_text(text)
    audio_chunks = []

    def synthesize_one(chunk, depth=0):
        print(f"[NeuTTS] Synthesizing chunk ({len(chunk)} chars)", flush=True)
        try:
            return [np.asarray(tts.infer(chunk, ref_codes, ref_text), dtype=np.float32)]
        except Exception as exc:
            message = str(exc)
            context_error = "exceed context window" in message.lower() or "requested tokens" in message.lower()
            if not context_error or len(chunk) <= 80 or depth >= 8:
                raise
            # The model's 2048-token limit includes the reference prompt, so
            # halve rejected chunks rather than guessing a token/character ratio.
            cut = len(chunk) // 2
            split_at = chunk.rfind(" ", 0, cut + 1)
            if split_at < 40:
                split_at = cut
            left = chunk[:split_at].strip()
            right = chunk[split_at:].strip()
            print(f"[NeuTTS] Context limit hit; splitting {len(chunk)} -> {len(left)} + {len(right)} chars", flush=True)
            return synthesize_one(left, depth + 1) + synthesize_one(right, depth + 1)

    for chunk in chunks:
        audio_chunks.extend(synthesize_one(chunk))
    return audio_chunks, len(chunks)


@app.get("/health")
def health():
    return {
        "ok": True,
        "engine": "neutts-air",
        "backbone": BACKBONE,
        "language": LANGUAGE,
        "maxSynthChars": MAX_SYNTH_CHARS,
    }


@app.post("/synthesize")
def synthesize(request: SynthesisRequest):
    text = request.text.strip()
    if not text:
        return {"error": "text is required"}
    try:
        ref_codes, ref_text = reference_codes(request.voice)
        audio_chunks, initial_chunks = synthesize_chunks(text, ref_codes, ref_text)
        wav = np.concatenate(audio_chunks) if len(audio_chunks) > 1 else audio_chunks[0]
        output = Path("/tmp") / f"softball-neutts-{os.getpid()}.wav"
        sf.write(output, wav, 24000)
        audio = base64.b64encode(output.read_bytes()).decode("ascii")
        output.unlink(missing_ok=True)
        return {
            "audioBase64": audio,
            "voice": request.voice,
            "sampleRate": 24000,
            "chunks": len(audio_chunks),
            "initialChunks": initial_chunks,
        }
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
