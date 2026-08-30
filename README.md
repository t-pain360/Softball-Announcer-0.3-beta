# 🥎 Softball Announcer — Local Version

A fully local softball/baseball public-address announcer for game-day use. Player data, announcement generation, and speech stay on the local machine. **No OpenAI API key, Gemini key, cloud TTS service, or Vercel deployment is required.**

> **Status:** 0.3 local beta — NeuTTS Air edition.

## What changed from the Piper local version

The local edition now uses **NeuTTS Air** for open-source, on-device speech synthesis. NeuTTS Air supports local voice cloning from a short reference WAV plus transcript, GGUF backbones, and local inference. citeturn0search2turn0search0

- Removed Piper configuration and process execution.
- Added a local Python NeuTTS Air service under `tts/`.
- Node/Express automatically starts the Python TTS service when the first announcement needs audio.
- Four personas map to four local voice-reference pairs.
- Announcement scripts remain deterministic local templates; no LLM is required.
- Browser SpeechSynthesis remains a fallback if NeuTTS Air or a reference voice is unavailable.
- Audio is WAV and is cached only in server memory.
- No OpenAI/Gemini credentials are used.

## Architecture

```text
┌──────────────────────────────┐
│        Browser / React       │
│   Lineup + Persona Controls  │
└──────────────┬───────────────┘
               │ HTTP / JSON
               ▼
┌──────────────────────────────┐
│      Local Express Server    │
│          server.ts           │
├──────────────────────────────┤
│ Local announcement templates │
│ Persona selection             │
│ In-memory audio cache         │
│ NeuTTS service launcher       │
└──────────────┬───────────────┘
               │ localhost HTTP
               ▼
┌──────────────────────────────┐
│     Python / NeuTTS Air      │
│       local TTS service      │
├──────────────────────────────┤
│ GGUF backbone                │
│ Local reference voice        │
│ Local NeuCodec                │
└──────────────┬───────────────┘
               ▼
          WAV audio

Fallback:
Browser SpeechSynthesis → local OS/browser voice
```

NeuTTS Air's upstream documentation recommends GGUF backbones, pre-encoded references, and an ONNX codec decoder when minimizing on-device latency. citeturn0search2

## 🎙️ Announcer Personas

| Persona | Voice reference |
|---|---|
| **Classic PA** | `voices/classic.wav` + `classic.txt` |
| **Hype Crew** | `voices/hype.wav` + `hype.txt` |
| **Golden Age Radio** | `voices/radio.wav` + `radio.txt` |
| **Velvet PA** | `voices/velvet.wav` + `velvet.txt` |

These are reference recordings, not four separately trained models. NeuTTS Air clones the characteristics of the supplied reference during inference. The upstream project recommends clean continuous speech, mono WAV, 16–44 kHz, and roughly 3–15 seconds for references. citeturn0search3

Use only recordings you own or have permission to clone.

## 🔊 NeuTTS Air Setup

NeuTTS Air requires Python 3.11+ and eSpeak NG. GGUF inference uses `llama-cpp-python`; the upstream project also supports an ONNX decoder. citeturn0search2

### 1. Install eSpeak NG

On Ubuntu/Debian:

```bash
sudo apt install espeak-ng
```

### 2. Create a Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r tts/requirements.txt
```

### 3. Configure the local service

Optional `.env` values:

```env
NEUTTS_PYTHON=.venv/bin/python
NEUTTS_HOST=127.0.0.1
NEUTTS_PORT=8011
NEUTTS_BACKBONE=neuphonic/neutts-air-q4-gguf
NEUTTS_CODEC=neuphonic/neucodec
NEUTTS_BACKBONE_DEVICE=cpu
NEUTTS_CODEC_DEVICE=cpu
```

The first run downloads the model assets from the configured model repositories. NeuTTS Air documents GGUF backbones as the efficient local option. citeturn0search2

### 4. Add voice references

Create:

```text
voices/
├── classic.wav
├── classic.txt
├── hype.wav
├── hype.txt
├── radio.wav
├── radio.txt
├── velvet.wav
└── velvet.txt
```

Each `.txt` file must contain the exact words spoken in its corresponding WAV reference.

The first synthesis for a voice encodes and caches its reference. Subsequent announcements reuse the encoded reference within the Python service.

### 5. Start the app

```bash
npm install
npm run dev
```

The Node server automatically starts the NeuTTS Python service when audio is requested.

Open:

```text
http://localhost:3000
```

## 🧠 Local Announcement Generation

This version deliberately does **not** require a local LLM. Scripts are deterministic templates, which is preferable for a game-day PA because it prevents invented statistics or game facts.

Announcements:

- Include the player's name and jersey number.
- May include the supplied nickname.
- May include the supplied hype/lore cue.
- Are short and PA-friendly.
- Do not invent statistics, positions, achievements, scores, innings, or game situations.

NeuTTS Air is responsible only for turning that trusted local text into speech.

## 📡 Local API

### `GET /api/health`

Returns local runtime state:

```json
{
  "ok": true,
  "localOnly": true,
  "cloudAI": false,
  "tts": "neutts-air",
  "neuttsReady": true
}
```

### `GET /api/personas`

Returns the four local announcer personas.

### `POST /api/announce`

Generates local announcement text and, when NeuTTS Air is ready, local WAV audio.

```json
{
  "player": {
    "id": "player-14",
    "name": "Jordan Smith",
    "number": 14,
    "nickname": "J-Smooth",
    "lore": "the lightning-fast shortstop"
  },
  "personaId": "classic",
  "generateAudio": true
}
```

A NeuTTS response contains Base64-encoded WAV audio:

```json
{
  "text": "Your attention please... Now batting... number 14, Jordan Smith, J-Smooth.",
  "audioBase64": "...",
  "audioType": "neutts_wav",
  "voice": "classic",
  "audioAvailable": true
}
```

### `POST /api/precache`

Pre-generates local announcements for up to 15 players. Generated WAV audio is cached in memory for rapid replay.

## 🔐 Privacy

This edition is designed for local/offline operation.

- No OpenAI credentials.
- No Gemini credentials.
- No cloud TTS calls.
- Player data stays on the local machine unless you deliberately expose the server.
- Voice reference recordings remain local.
- NeuTTS Air inference runs locally.
- The server cache disappears when the application stops.

NeuTTS Air adds a Perth perceptual-threshold watermark to generated audio according to its upstream documentation. citeturn0search2

## ⚡ Game-Day Workflow

1. Install Node.js and Python 3.11+.
2. Install eSpeak NG.
3. Create the Python virtual environment.
4. Install `tts/requirements.txt`.
5. Add your authorized voice references.
6. Run `npm install`.
7. Run `npm run dev`.
8. Enter the lineup.
9. Select a persona.
10. Press **PRE-CACHE LINEUP** before the game.
11. Announce batters from the booth.

Pre-caching is recommended because NeuTTS Air is a neural model and generating the audio before it is needed reduces game-time latency.

## 🛠️ Tech Stack

- React
- TypeScript
- Vite
- Express
- Python 3.11+
- NeuTTS Air
- NeuCodec
- llama-cpp-python for GGUF inference
- FastAPI/Uvicorn local TTS service
- Browser SpeechSynthesis fallback

NeuTTS Air's official examples use `NeuTTSAir`, a reference WAV/transcript pair, and write 24 kHz WAV output. citeturn0search2

## 📁 Project Structure

```text
.
├── src/                    # React application
├── tts/
│   ├── neutts_service.py  # Local NeuTTS Air HTTP service
│   └── requirements.txt    # Python dependencies
├── voices/
│   └── README.md           # Voice-reference instructions
├── index.html
├── server.ts               # Express API + local TTS launcher
├── package.json
└── tsconfig.json
```

## 🧪 Troubleshooting

### `OPENAI_API_KEY is not configured`

That message belongs to the cloud 0.3 beta. The `local-version` branch does not use OpenAI. Make sure you are running the local branch and not the upstream cloud version.

### NeuTTS service does not start

Check Python:

```bash
.venv/bin/python --version
```

Check dependencies:

```bash
.venv/bin/python -c "from neuttsair.neutts import NeuTTSAir; print('NeuTTS import OK')"
```

Check eSpeak NG:

```bash
espeak-ng --version
```

### A persona says its reference is missing

Add both files:

```text
voices/classic.wav
voices/classic.txt
```

and make sure the transcript exactly matches the recording.

### NeuTTS Air is too slow

Use the GGUF backbone and pre-encode references. The upstream project specifically recommends GGUF, pre-encoded references, and an ONNX codec decoder for lower latency. citeturn0search2

If your machine has a supported GPU, configure the appropriate acceleration for `llama-cpp-python` and the NeuTTS backend.

### `dist/index.html` does not exist

For development:

```bash
npm run dev
```

For production-style local execution:

```bash
npm run build
npm start
```

## 🗺️ Roadmap

- Add a voice-reference recorder inside the app.
- Add voice preview/testing.
- Add per-persona speed controls.
- Add offline lineup save/load.
- Add keyboard shortcuts for game-day operation.
- Add local walk-up music and PA effects.
- Add local audio mixing/ducking.
- Package as a Windows/Linux desktop app.
- Provide a one-command offline installer.

## 📄 License

No license file is currently specified in the upstream repository. Until a license is added, assume the project is **all rights reserved**.

## 🥎 Local Edition

**Softball Announcer — NeuTTS Air Local Version** keeps the entire announcement pipeline on the operator's computer: local player data → local announcement templates → local NeuTTS Air voice cloning → local WAV audio → local speakers.
