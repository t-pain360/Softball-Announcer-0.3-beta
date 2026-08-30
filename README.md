# 🥎 Softball Announcer 0.3 Beta

A lightweight, browser-based softball/baseball public-address announcer that turns player information into short stadium announcements and optional generated speech.

**Repository:** https://github.com/t-pain360/Softball-Announcer-0.3-beta

> **Status:** 0.3 beta — active development. APIs and UI behavior may change.

## ✨ What It Does

Softball Announcer is designed for dugouts, scorekeepers, team DJs, and anyone who wants a more energetic ballpark presentation without needing a dedicated PA operator.

Give the app a player and an announcer persona and it can:

- Generate a short PA-style announcement.
- Include the player's name and jersey number.
- Add an optional nickname or hype/lore cue.
- Generate spoken audio through the configured OpenAI models.
- Cache generated announcements in server memory for fast replay.
- Pre-cache up to 15 players for a selected announcer persona.
- Fall back to deterministic local announcement text when OpenAI script generation is unavailable.
- Run locally with a simple Node/TypeScript server or deploy through Vercel.

## 🎙️ Announcer Personas

| Persona | Voice | Style |
|---|---|---|
| **Classic PA** | `onyx` | Authoritative, warm, deliberate stadium PA |
| **Hype Crew** | `alloy` | High-energy, modern ballpark MC |
| **Golden Age Radio** | `echo` | Crisp vintage baseball-radio style |
| **Velvet PA** | `shimmer` | Smooth, confident, polished with dramatic pauses |

The persona definitions live in the server and control both the writing style and selected speech voice.

## 🧱 Architecture

```text
┌──────────────────────────────┐
│        Browser / React       │
│   Player + Persona Controls  │
└──────────────┬───────────────┘
               │ HTTP / JSON
               ▼
┌──────────────────────────────┐
│      Express + TypeScript    │
│          server.ts           │
├──────────────────────────────┤
│  Player validation            │
│  Persona selection            │
│  Announcement cache           │
│  Script generation            │
│  Speech generation            │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│          OpenAI API           │
│                              │
│  Responses API → PA script   │
│  Audio Speech API → MP3      │
└──────────────────────────────┘
```

The current beta keeps the OpenAI client on the server. The browser does **not** need to contain the API key. The server reads `OPENAI_API_KEY` from the environment and initializes the OpenAI SDK only when a key is present.

## 🔐 API Key & Security

Set the OpenAI API key as a **server-side environment variable**:

```env
OPENAI_API_KEY=your_api_key_here
```

Optional model overrides:

```env
OPENAI_TEXT_MODEL=gpt-4o-mini
OPENAI_TTS_MODEL=gpt-4o-mini-tts
```

Never commit `.env` or an API key to GitHub.

The `/api/health` endpoint intentionally reports only whether OpenAI is configured; it does not return the key itself.

For a public production deployment, add authentication, rate limiting, request-size controls, and abuse protection before exposing the announcement endpoints broadly.

## 🔊 Audio Pipeline

The normal announcement pipeline is:

1. The client sends player data and a persona ID to `POST /api/announce`.
2. The server validates the player and persona.
3. The server checks its in-memory cache.
4. If no cached script exists, OpenAI generates a short spoken announcement.
5. The server sends that text to the configured OpenAI speech model.
6. The returned MP3 is converted to Base64.
7. The server caches the result and returns the script/audio to the client.

If text generation fails, the server uses a local deterministic fallback script. If speech generation is unavailable, the request reports the speech-generation error rather than silently pretending audio was produced.

## 🧠 Announcement Rules

The generated prompt is intentionally constrained so announcements:

- Stay short — normally 1–2 sentences.
- Include the player's name and jersey number.
- Do not invent statistics.
- Do not invent game situations.
- Do not invent positions or achievements.
- Use only the supplied nickname and hype/lore information.
- Return only spoken announcement text.

## ⚡ Caching

Announcements are cached in server memory using player/persona information as the cache key.

The cache can avoid regenerating the same script/audio repeatedly during a game. It is intentionally an in-memory cache, so it is cleared when the server instance restarts.

For multi-instance production deployments, consider moving the cache to a shared store such as Redis or another persistent caching service.

## 📡 API

### `GET /api/health`

Returns basic server health and whether an OpenAI key is configured.

Example:

```json
{
  "ok": true,
  "openaiConfigured": true
}
```

### `GET /api/personas`

Returns the available announcer personas.

### `POST /api/announce`

Generate an announcement and optional audio.

Example request:

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

Example response shape:

```json
{
  "text": "Your attention please... Now batting... number 14, Jordan Smith, J-Smooth!",
  "audioBase64": "...",
  "voice": "onyx",
  "audioAvailable": true
}
```

### `POST /api/precache`

Pre-generates announcements for a lineup. The current server limits the request to 15 players.

```json
{
  "players": [
    { "name": "Jordan Smith", "number": 14 },
    { "name": "Taylor Jones", "number": 7 }
  ],
  "personaId": "classic"
}
```

## 🛠️ Tech Stack

- **React** — browser UI
- **TypeScript** — application/server language
- **Vite** — frontend build tooling
- **Express** — HTTP API/server
- **OpenAI Node SDK** — text and speech generation
- **Lucide React** — UI icons
- **Vercel** — supported deployment target

The repository is configured as an ES module project and provides `dev`, `build`, and `start` scripts through `package.json`.

## 🚀 Local Development

### Requirements

- Node.js 18+ recommended
- npm
- An OpenAI API key for generated speech

### Install

```bash
npm install
```

### Configure environment

Create `.env` in the project root:

```env
OPENAI_API_KEY=your_api_key_here
```

Optional:

```env
PORT=3000
OPENAI_TEXT_MODEL=gpt-4o-mini
OPENAI_TTS_MODEL=gpt-4o-mini-tts
```

### Start development server

```bash
npm run dev
```

Then open:

```text
http://localhost:3000
```

### Production build

```bash
npm run build
npm start
```

The build runs TypeScript validation followed by the Vite production build.

## ☁️ Vercel Deployment

The repository includes `vercel.json` and routes `/api/*` requests to `/api/index.ts` while serving the Vite `dist` output.

Configure the following environment variable in the Vercel project:

```text
OPENAI_API_KEY
```

Optional model variables:

```text
OPENAI_TEXT_MODEL
OPENAI_TTS_MODEL
```

Then deploy the repository through Vercel or your preferred CI/CD workflow.

> **Deployment note:** The repository currently contains both a traditional Express server entry point and Vercel API routing configuration. Verify the Vercel API entry point and production build locally before treating a deployment as production-ready.

## 📁 Project Structure

```text
.
├── .github/              # GitHub configuration/workflows
├── api/                  # Vercel API entry point(s)
├── src/                  # React application source
├── index.html            # Vite HTML entry
├── server.ts             # Express API + server entry
├── package.json          # Dependencies and scripts
├── tsconfig.json         # TypeScript configuration
└── vercel.json           # Vercel deployment configuration
```

## 🧪 Development Checklist

Before a game-day deployment:

- [ ] `npm install` completes successfully.
- [ ] `npm run build` passes.
- [ ] `OPENAI_API_KEY` is configured server-side.
- [ ] `/api/health` reports the expected configuration state.
- [ ] Each announcer persona produces usable audio.
- [ ] Player names and numbers are correct.
- [ ] Pre-cache completes for the intended lineup.
- [ ] Audio playback works through the venue's speakers.
- [ ] API rate limits and authentication are configured for public deployments.

## 🗺️ Roadmap Ideas

- Fully open-source/local TTS option such as Piper.
- Optional local LLM for completely offline script generation.
- Persistent/shared audio cache.
- Team and lineup import/export.
- Better audio mixing with walk-up music and PA effects.
- Adjustable speech speed, pitch, and stadium reverb.
- Game-day operator mode with keyboard shortcuts.
- Authentication and team-level access control.
- PWA/offline support for field use.

## 🤝 Contributing

Issues, suggestions, and pull requests are welcome. When submitting a change, include enough detail to reproduce the behavior and, where practical, test the affected API or UI flow locally.

## 📄 License

No license file is currently specified in the repository. Until a license is added, assume the project is **all rights reserved** and do not redistribute it as open-source software without permission from the copyright holder.

## 🥎 About

**Softball Announcer 0.3 Beta** is a game-day PA assistant for softball and baseball that combines player-specific announcements, announcer personas, generated speech, and lineup pre-caching in a simple web application.
