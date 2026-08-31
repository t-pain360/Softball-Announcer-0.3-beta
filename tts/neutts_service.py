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
# Budget against NeuTTS's actual tokenizer instead of guessing from characters.
# 2048 is the complete model context, including the reference prompt.
MAX_CONTEXT_TOKENS = int(os.getenv("NEUTTS_MAX_CONTEXT_TOKENS", "2048"))
# Leave headroom for the generated speech tokens.  NeuTTS's own implementation
# passes max_length=2048, so the input prompt itself must remain below this.
PROMPT_TOKEN_HEADROOM = int(os.getenv("NEUTTS_PROMPT_TOKEN_HEADROOM", "256"))

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


def prompt_token_count(text: str, ref_codes, ref_text: str) -> int:
    """Count the exact GGUF prompt tokens NeuTTS will send to llama.cpp."""
    prompt = tts._ggml_prompt(ref_codes, ref_text, text)
    return len(tts.backbone.tokenize(prompt.encode("utf-8"), add_bos=True))


def split_text_for_context(text: str, ref_codes, ref_text: str):
    """Split using the model tokenizer, not character count.

    NeuTTS Air has a 2048-token context window INCLUDING reference text and
    reference speech codes. A character limit cannot guarantee safety because
    phonemization/tokenization varies substantially. We therefore binary-search
    the largest word-aligned chunk whose *actual NeuTTS prompt* fits below a
    conservative token budget.
    """
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    # Keep substantial room for speech generation. This is deliberately
    # conservative; it trades a few extra chunks for reliability.
    budget = max(256, MAX_CONTEXT_TOKENS - PROMPT_TOKEN_HEADROOM)
    words = text.split()
    chunks = []
    current = []

    def fits(candidate: str) -> bool:
        return prompt_token_count(candidate, ref_codes, ref_text) <= budget

    for word in words:
        candidate = " ".join(current + [word])
        if not current:
            # An individual pathological token still has to be sent somehow.
            if fits(candidate):
                current = [word]
            else:
                # Fall back to progressively smaller pieces of the word.
                for size in range(max(1, len(word) // 2), 0, -1):
                    piece = word[:size]
                    if fits(piece):
                        chunks.append(piece)
                        remainder = word[size:]
                        current = [remainder] if remainder else []
                        break
                else:
                    raise ValueError("NeuTTS reference prompt leaves no usable context for synthesis text")
            continue

        if fits(candidate):
            current.append(word)
        else:
            chunks.append(" ".join(current))
            current = [word]

    if current:
        chunks.append(" ".join(current))

    # Prefer sentence boundaries when possible by merging adjacent small
    # chunks only when the exact tokenizer budget still allows it.
    merged = []
    for chunk in chunks:
        if merged:
            candidate = f"{merged[-1]} {chunk}"
            if fits(candidate):
                merged[-1] = candidate
                continue
        merged.append(chunk)
    return merged


def synthesize_chunks(text, ref_codes, ref_text):
    chunks = split_text_for_context(text, ref_codes, ref_text)
    print(
        f"[NeuTTS] Exact-token chunking: {len(chunks)} chunk(s), "
        f"budget={MAX_CONTEXT_TOKENS - PROMPT_TOKEN_HEADROOM} tokens",
        flush=True,
    )
    audio_chunks = []
    for index, chunk in enumerate(chunks, 1):
        tokens = prompt_token_count(chunk, ref_codes, ref_text)
        print(f"[NeuTTS] Chunk {index}/{len(chunks)}: {len(chunk)} chars, {tokens} prompt tokens", flush=True)
        # This assertion prevents the old failure from reaching llama.cpp.
        if tokens >= MAX_CONTEXT_TOKENS:
            raise ValueError(
                f"Internal context-budget error: chunk has {tokens} prompt tokens "
                f"but maximum is {MAX_CONTEXT_TOKENS}"
            )
        audio_chunks.append(np.asarray(tts.infer(chunk, ref_codes, ref_text), dtype=np.float32))
    return audio_chunks, len(chunks)


@app.get("/health")
def health():
    return {
        "ok": True,
        "engine": "neutts-air",
        "backbone": BACKBONE,
        "language": LANGUAGE,
        "contextTokens": MAX_CONTEXT_TOKENS,
        "promptTokenHeadroom": PROMPT_TOKEN_HEADROOM,
        "build": "exact-token-chunking-v2",
    }


@app.post("/synthesize")
def synthesize(request: SynthesisRequest):
    text = request.text.strip()
    if not text:
        return {"error": "text is required"}
    try:
        ref_codes, ref_text = reference_codes(request.voice)
        audio_chunks, chunk_count = synthesize_chunks(text, ref_codes, ref_text)
        wav = np.concatenate(audio_chunks) if len(audio_chunks) > 1 else audio_chunks[0]
        output = Path("/tmp") / f"softball-neutts-{os.getpid()}.wav"
        sf.write(output, wav, 24000)
        audio = base64.b64encode(output.read_bytes()).decode("ascii")
        output.unlink(missing_ok=True)
        return {
            "audioBase64": audio,
            "voice": request.voice,
            "sampleRate": 24000,
            "chunks": chunk_count,
            "engine": "neutts-air",
        }
    except Exception as exc:
        print(f"[NeuTTS] synthesis error: {exc}", flush=True)
        return {"error": str(exc), "engine": "neutts-air"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
