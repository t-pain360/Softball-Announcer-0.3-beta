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
MAX_CONTEXT_TOKENS = int(os.getenv("NEUTTS_MAX_CONTEXT_TOKENS", "2048"))
# Keep a conservative amount of room below llama.cpp's hard context limit.
PROMPT_BUDGET = int(os.getenv("NEUTTS_PROMPT_BUDGET", "1500"))

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
    codes = tts.encode_reference(str(wav_path))
    return fit_reference_to_context(codes, ref_text), ref_text


def prompt_token_count(text: str, ref_codes, ref_text: str) -> int:
    prompt = tts._ggml_prompt(ref_codes, ref_text, text)
    return len(tts.backbone.tokenize(prompt.encode("utf-8"), add_bos=True))


def fit_reference_to_context(ref_codes, ref_text: str):
    """Ensure the reference itself leaves usable context for new text.

    NeuTTS Air's 2048-token window includes the reference audio codes and
    reference transcript. A long reference can therefore overflow the model
    before the requested announcement is even added. We progressively shorten
    the reference codes until an empty synthesis prompt is safely below the
    configured prompt budget.
    """
    codes = list(ref_codes)
    if not codes:
        raise ValueError("NeuTTS reference audio produced no codec codes")

    # The reference audio is used only as a speaker/style prompt. Keeping the
    # beginning of a clean reference is preferable to allowing it to consume
    # the entire context window. The model documentation recommends only a few
    # seconds for cloning, so this also protects against accidentally supplied
    # long recordings.
    original = len(codes)
    while codes and prompt_token_count("", codes, ref_text) > PROMPT_BUDGET:
        new_len = max(1, int(len(codes) * 0.75))
        if new_len == len(codes):
            new_len -= 1
        codes = codes[:new_len]

    if not codes or prompt_token_count("", codes, ref_text) > PROMPT_BUDGET:
        raise ValueError(
            "NeuTTS reference is too large for the 2048-token context window. "
            "Use a shorter reference WAV (about 3 seconds) and matching transcript."
        )

    if len(codes) != original:
        print(
            f"[NeuTTS] Trimmed reference codec prompt from {original} to {len(codes)} codes "
            f"to fit context (empty prompt={prompt_token_count('', codes, ref_text)} tokens)",
            flush=True,
        )
    else:
        print(
            f"[NeuTTS] Reference prompt={prompt_token_count('', codes, ref_text)} tokens",
            flush=True,
        )
    return codes


def split_text_for_context(text: str, ref_codes, ref_text: str):
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    words = text.split()
    chunks = []

    def fits(candidate: str) -> bool:
        return prompt_token_count(candidate, ref_codes, ref_text) <= PROMPT_BUDGET

    current = []
    for word in words:
        candidate = " ".join(current + [word])
        if current and not fits(candidate):
            chunks.append(" ".join(current))
            current = [word]
        elif fits(candidate):
            current.append(word)
        else:
            # A single word can occasionally be pathological after phonemization.
            # Split it into smaller pieces rather than sending an oversized prompt.
            placed = False
            for size in range(max(1, len(word) // 2), 0, -1):
                piece = word[:size]
                if fits(piece):
                    chunks.append(piece)
                    remainder = word[size:]
                    current = [remainder] if remainder else []
                    placed = True
                    break
            if not placed:
                raise ValueError("Announcement text cannot fit in NeuTTS context")

    if current:
        chunks.append(" ".join(current))
    return chunks


def synthesize_chunks(text, ref_codes, ref_text):
    chunks = split_text_for_context(text, ref_codes, ref_text)
    print(
        f"[NeuTTS] Exact-token chunking: {len(chunks)} chunk(s), prompt budget={PROMPT_BUDGET}",
        flush=True,
    )
    audio_chunks = []
    for index, chunk in enumerate(chunks, 1):
        tokens = prompt_token_count(chunk, ref_codes, ref_text)
        print(
            f"[NeuTTS] Chunk {index}/{len(chunks)}: {len(chunk)} chars, {tokens} prompt tokens",
            flush=True,
        )
        if tokens >= MAX_CONTEXT_TOKENS:
            raise ValueError(f"Prompt is {tokens} tokens; maximum is {MAX_CONTEXT_TOKENS}")

        try:
            audio_chunks.append(np.asarray(tts.infer(chunk, ref_codes, ref_text), dtype=np.float32))
        except Exception as exc:
            message = str(exc)
            match = re.search(r"Requested tokens \((\d+)\) exceed context window of (\d+)", message)
            if not match:
                raise

            requested = int(match.group(1))
            limit = int(match.group(2))
            print(
                f"[NeuTTS] llama.cpp rejected prompt ({requested}>{limit}); retrying with a shorter chunk",
                flush=True,
            )

            # This is a final safety net for tokenizer-version differences. If
            # the preflight count disagrees with llama.cpp, split the text in
            # half and retry each half with the same reference.
            if len(chunk.split()) <= 1:
                raise ValueError(
                    f"NeuTTS reference/text prompt is too large ({requested} tokens). "
                    "Use a shorter reference WAV."
                ) from exc

            parts = chunk.split()
            midpoint = max(1, len(parts) // 2)
            left = " ".join(parts[:midpoint])
            right = " ".join(parts[midpoint:])
            for retry in (left, right):
                audio_chunks.append(
                    np.asarray(tts.infer(retry, ref_codes, ref_text), dtype=np.float32)
                )

    return audio_chunks, len(chunks)


@app.get("/health")
def health():
    return {
        "ok": True,
        "engine": "neutts-air",
        "backbone": BACKBONE,
        "language": LANGUAGE,
        "contextTokens": MAX_CONTEXT_TOKENS,
        "promptBudget": PROMPT_BUDGET,
        "build": "reference-aware-context-v3",
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
