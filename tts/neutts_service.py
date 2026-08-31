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
MIN_GENERATION_TOKENS = int(os.getenv("NEUTTS_MIN_GENERATION_TOKENS", "64"))

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
        if voice != "classic":
            fallback_wav, fallback_txt = paths_for_voice("classic")
            if fallback_wav.exists() and fallback_txt.exists():
                print(f"[NeuTTS] No reference for '{voice}'; using classic reference voice", flush=True)
                wav_path, txt_path = fallback_wav, fallback_txt
        if not wav_path.exists() or not txt_path.exists():
            raise FileNotFoundError(
                f"Missing NeuTTS reference for '{voice}'. Add {wav_path} and {txt_path}."
            )
    ref_text = txt_path.read_text(encoding="utf-8").strip()
    if not ref_text:
        raise ValueError(f"Reference transcript is empty: {txt_path}")
    codes = tts.encode_reference(str(wav_path))
    return codes, ref_text


def ggml_prompt(text: str, ref_codes, ref_text: str) -> str:
    return tts._ggml_prompt(ref_codes, ref_text, text)


def prompt_token_count(text: str, ref_codes, ref_text: str) -> int:
    prompt = ggml_prompt(text, ref_codes, ref_text)
    return len(tts.backbone.tokenize(prompt.encode("utf-8"), add_bos=True))


def fit_reference_to_context(ref_codes, ref_text: str):
    codes = list(ref_codes)
    if not codes:
        raise ValueError("NeuTTS reference audio produced no codec codes")

    original = len(codes)
    prompt_limit = MAX_CONTEXT_TOKENS - MIN_GENERATION_TOKENS
    while codes and prompt_token_count("", codes, ref_text) > prompt_limit:
        new_len = max(1, int(len(codes) * 0.80))
        if new_len == len(codes):
            new_len -= 1
        codes = codes[:new_len]

    empty_tokens = prompt_token_count("", codes, ref_text)
    if not codes or empty_tokens > prompt_limit:
        raise ValueError(
            f"NeuTTS reference requires {empty_tokens} prompt tokens; safe limit is {prompt_limit}. "
            "Use a shorter reference WAV and matching transcript."
        )

    print(
        f"[NeuTTS] Reference prompt={empty_tokens} tokens; safe limit={prompt_limit}"
        + (f"; trimmed codes {original}->{len(codes)}" if len(codes) != original else ""),
        flush=True,
    )
    return codes


def split_text_for_context(text: str, ref_codes, ref_text: str):
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    prompt_limit = MAX_CONTEXT_TOKENS - MIN_GENERATION_TOKENS
    words = text.split()
    chunks = []
    current = []

    for word in words:
        candidate = " ".join(current + [word])
        tokens = prompt_token_count(candidate, ref_codes, ref_text)
        if tokens <= prompt_limit:
            current.append(word)
        elif current:
            chunks.append(" ".join(current))
            current = [word]
            single_tokens = prompt_token_count(word, ref_codes, ref_text)
            if single_tokens > prompt_limit:
                raise ValueError(
                    f"A single announcement word requires {single_tokens} prompt tokens; safe limit is {prompt_limit}."
                )
        else:
            raise ValueError(
                f"A single announcement word requires {tokens} prompt tokens; safe limit is {prompt_limit}."
            )

    if current:
        chunks.append(" ".join(current))
    return chunks


def infer_with_context_budget(chunk, ref_codes, ref_text):
    """Generate with an exact prompt+generation budget and a fresh llama.cpp context."""
    prompt = ggml_prompt(chunk, ref_codes, ref_text)
    prompt_tokens = len(tts.backbone.tokenize(prompt.encode("utf-8"), add_bos=True))
    remaining = MAX_CONTEXT_TOKENS - prompt_tokens

    if prompt_tokens > MAX_CONTEXT_TOKENS:
        raise ValueError(
            f"NeuTTS prompt is {prompt_tokens} tokens, exceeding the {MAX_CONTEXT_TOKENS}-token context."
        )
    if remaining < MIN_GENERATION_TOKENS:
        raise ValueError(
            f"NeuTTS prompt is {prompt_tokens} tokens, leaving only {remaining} tokens for generation; "
            f"minimum is {MIN_GENERATION_TOKENS}."
        )

    print(
        f"[NeuTTS] Exact llama.cpp request: prompt={prompt_tokens}, "
        f"max_tokens={remaining}, total={prompt_tokens + remaining}/{MAX_CONTEXT_TOKENS}",
        flush=True,
    )

    # NeuTTS itself resets llama.cpp before every non-streaming inference.
    # Without this, repeated /synthesize requests can inherit stale KV-cache state
    # and produce empty output (which upstream code then indexes as choices[0]).
    tts.backbone.reset()
    output = tts.backbone(
        prompt,
        max_tokens=remaining,
        temperature=1.0,
        top_k=50,
        stop=["<|SPEECH_GENERATION_END|>"],
        seed=tts._call_seed(),
    )

    choices = output.get("choices") if isinstance(output, dict) else None
    if not choices:
        raise RuntimeError(
            f"llama.cpp returned no choices for a {prompt_tokens}-token prompt "
            f"with max_tokens={remaining}. Raw response keys: "
            f"{list(output.keys()) if isinstance(output, dict) else type(output).__name__}"
        )

    output_str = choices[0].get("text", "")
    if not output_str:
        raise RuntimeError("llama.cpp returned an empty speech-token response")

    # NeuTTS upstream raises a useful error when no speech tokens are present.
    speech_token_count = len(re.findall(r"<\\|speech_(\\d+)\\|>", output_str))
    if speech_token_count == 0:
        raise RuntimeError("NeuTTS generated no valid speech tokens")

    wav = tts._decode(output_str)
    if tts.watermarker is not None:
        wav = tts.watermarker.apply_watermark(wav, sample_rate=24000)
    return np.asarray(wav, dtype=np.float32)


def synthesize_chunks(text, ref_codes, ref_text):
    chunks = split_text_for_context(text, ref_codes, ref_text)
    print(f"[NeuTTS] Exact-token chunking: {len(chunks)} chunk(s)", flush=True)
    audio_chunks = []

    for index, chunk in enumerate(chunks, 1):
        try:
            audio_chunks.append(infer_with_context_budget(chunk, ref_codes, ref_text))
        except Exception as exc:
            message = str(exc)
            match = re.search(r"Requested tokens \((\d+)\) exceed context window of (\d+)", message)
            if not match:
                raise

            requested = int(match.group(1))
            limit = int(match.group(2))
            print(
                f"[NeuTTS] llama.cpp rejected request {requested}>{limit}; splitting chunk {index} and retrying",
                flush=True,
            )

            parts = chunk.split()
            if len(parts) <= 1:
                raise ValueError(
                    f"NeuTTS prompt still exceeds the {limit}-token context with a single word. "
                    "Use a shorter reference WAV."
                ) from exc

            midpoint = max(1, len(parts) // 2)
            for retry in (" ".join(parts[:midpoint]), " ".join(parts[midpoint:])):
                audio_chunks.append(infer_with_context_budget(retry, ref_codes, ref_text))

    return audio_chunks, len(chunks)


@app.get("/health")
def health():
    return {
        "ok": True,
        "engine": "neutts-air",
        "backbone": BACKBONE,
        "language": LANGUAGE,
        "contextTokens": MAX_CONTEXT_TOKENS,
        "minimumGenerationTokens": MIN_GENERATION_TOKENS,
        "build": "direct-llama-context-budget-v6-reset-guard",
    }


@app.post("/synthesize")
def synthesize(request: SynthesisRequest):
    text = request.text.strip()
    if not text:
        return {"error": "text is required"}
    try:
        ref_codes, ref_text = reference_codes(request.voice)
        ref_codes = fit_reference_to_context(ref_codes, ref_text)
        audio_chunks, chunk_count = synthesize_chunks(text, ref_codes, ref_text)
        if not audio_chunks:
            raise ValueError("NeuTTS produced no audio chunks")
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
