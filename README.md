# 🥎 Softball Announcer — Local Version

A fully local softball/baseball public-address announcer for game-day use. Player data, announcement generation, and speech stay on the local machine. **No OpenAI API key, Gemini key, cloud TTS service, or Vercel deployment is required.**

> **Status:** 0.3 local beta — active development.

## What changed from 0.3 Beta

The local version removes the cloud AI dependency:

- Removed the OpenAI Node SDK.
- Removed `OPENAI_API_KEY` and cloud model configuration.
- Announcement scripts are generated deterministically from local templates.
- **Piper TTS** is the preferred open-source local speech engine.
- If Piper is not configured, the browser's local `SpeechSynthesis` API is used as a fallback.
- Audio and scripts are cached only in the running server's memory.
- Vercel configuration has been removed because Piper requires a local runtime/model.

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
│ In-memory cache               │
│ Piper process launcher        │
└──────────────┬───────────────┘
               │ local process
               ▼
┌──────────────────────────────┐
│        Piper TTS              │
│      Open-source / local      │
│         WAV output            │
└──────────────────────────────┘

Fallback:
Browser SpeechSynthesis → local OS/browser voice
```

There are **no outbound AI requests** in the application code.

## 🎙️ Announcer Personas

| Persona | Local style |
|---|---|
| **Classic PA** | Authoritative, warm, deliberate stadium PA |
| **Hype Crew** | High-energy, modern ballpark MC |
| **Golden Age Radio** | Crisp vintage baseball-radio style |
| **Velvet PA** | Smooth, confident, polished with dramatic pauses |

Personas currently control the local announcement template and browser-speech pacing. Piper uses the configured local model.

## 🔊 Piper TTS

[Piper](https://github.com/rhasspy/piper) is the preferred TTS engine for this version. Piper runs locally and produces speech without sending the announcement to a cloud speech provider.

### Install Piper

The easiest Python-based installation is:

```bash
python3 -m pip install piper-tts
```

Verify it is available:

```bash
piper --help
```

Download a Piper voice/model using the Piper tooling appropriate to your installation. Store the model somewhere on the local machine, for example:

```text
/home/timw1982/Softball/models/en_US-lessac-medium.onnx
```

Then configure the model path in `.env`:

```env
PIPER_MODEL=/home/timw1982/Softball/models/en_US-lessac-medium.onnx
```

If `piper` is not on your `PATH`, set its executable explicitly:

```env
PIPER_BIN=/home/timw1982/.local/bin/piper
```

Optional timeout:

```env
PIPER_TIMEOUT_MS=30000
```

### No model? No problem

If `PIPER_MODEL` is not configured, the app still works. It returns the locally generated announcement text and the browser uses `SpeechSynthesis` to speak it.

## 🚀 Local Development

### Requirements

- Node.js 18+ recommended
- npm
- Python 3 if using Piper
- Piper and a compatible local voice model for open-source TTS

### Install

```bash
npm install
```

### Configure Piper

Create `.env` in the project root:

```env
PIPER_MODEL=/absolute/path/to/your/voice.onnx
```

Optional:

```env
PORT=3000
PIPER_BIN=piper
PIPER_TIMEOUT_MS=30000
```

**There is no `OPENAI_API_KEY` setting.**

### Start

```bash
npm run dev
```

Open:

```text
http://localhost:3000
```

### Production-style local run

```bash
npm run build
npm start
```

The production server serves the Vite `dist` directory.

## 📡 Local API

### `GET /api/health`

Returns local-runtime information:

```json
{
  "ok": true,
  "localOnly": true,
  "cloudAI": false,
  "tts": "piper",
  "piperModelConfigured": true
}
```

### `GET /api/personas`

Returns the four local announcer personas.

### `POST /api/announce`

Generates a local announcement and, when Piper is configured, local WAV audio.

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

A Piper response contains Base64-encoded WAV audio:

```json
{
  "text": "Your attention please... Now batting... number 14, Jordan Smith, J-Smooth.",
  "audioBase64": "...",
  "audioType": "piper_wav",
  "voice": "/path/to/voice.onnx",
  "audioAvailable": true
}
```

When Piper is unavailable:

```json
{
  "text": "...",
  "audioType": "browser_speech",
  "voice": "browser-local",
  "audioAvailable": false
}
```

The browser then speaks the returned text locally.

### `POST /api/precache`

Pre-generates local announcements for up to 15 players. Piper audio is cached in memory for rapid replay during a game.

## 🧠 Local Announcement Rules

The local generator intentionally avoids an LLM so it cannot invent player statistics or game facts.

Announcements:

- Include the player's name and jersey number.
- May include the supplied nickname.
- May include the supplied hype/lore cue.
- Are short and PA-friendly.
- Do not invent statistics, positions, achievements, scores, innings, or game situations.

## 🔐 Privacy & Security

This version is designed for local/offline operation.

- No AI API keys are required.
- No OpenAI credentials are stored or transmitted.
- No Gemini credentials are stored or transmitted.
- Player information stays on the local machine unless you deliberately expose the server yourself.
- Piper speech generation happens as a local child process.
- The cache exists only in server memory and disappears when the server stops.

For a game-day computer, bind the application to localhost if remote access is not required.

## ⚡ Game-Day Workflow

1. Install Node and Piper.
2. Download a Piper voice model.
3. Set `PIPER_MODEL` in `.env`.
4. Run `npm install`.
5. Run `npm run dev`.
6. Open `http://localhost:3000`.
7. Enter the lineup.
8. Select an announcer persona.
9. Press **PRE-CACHE LINEUP** before the game.
10. Announce each batter from the booth.

Pre-caching is recommended because it gives the local machine time to generate the WAV files before they are needed.

## 🛠️ Tech Stack

- React
- TypeScript
- Vite
- Express
- Piper TTS
- Browser SpeechSynthesis fallback
- Lucide React

There is intentionally **no OpenAI SDK or other cloud AI SDK** in this local version.

## 📁 Project Structure

```text
.
├── .github/          # GitHub configuration/workflows
├── api/               # Legacy deployment files from the upstream project
├── src/               # React application
├── index.html         # Vite entry point
├── server.ts          # Local Express API + Piper integration
├── package.json       # Local dependencies/scripts
└── tsconfig.json      # TypeScript configuration
```

## 🧪 Troubleshooting

### `OPENAI_API_KEY is not configured`

That message belongs to the cloud 0.3 beta. The local branch does not require or use OpenAI. Make sure you are running the `local-version` branch.

### Piper is unavailable

Check:

```bash
which piper
piper --help
```

Then check:

```bash
echo "$PIPER_MODEL"
ls -lh "$PIPER_MODEL"
```

If the model is not configured, the application will use browser-local SpeechSynthesis instead.

### `dist/index.html` does not exist

Build the frontend before starting in production mode:

```bash
npm run build
npm start
```

For development, use:

```bash
npm run dev
```

## 🗺️ Roadmap

- Add downloadable/managed Piper voice setup.
- Add multiple Piper voice profiles per persona.
- Add adjustable pitch and speaking rate.
- Add offline lineup save/load.
- Add keyboard shortcuts for game-day operation.
- Add local audio effects and walk-up music.
- Add a local mixer for PA volume and ducking.
- Package the application as a desktop app for Windows/Linux.
- Add a fully offline installer containing Node, Piper, and selected voice models.

## 📄 License

No license file is currently specified in the upstream repository. Until a license is added, assume the project is **all rights reserved**.

## 🥎 Local Edition

**Softball Announcer — Local Version** is intended to be a dependable game-day PA tool that keeps the entire announcement pipeline on the operator's computer: local player data → local announcement logic → local Piper speech → local speakers.
