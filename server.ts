import express from 'express';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { promises as fs } from 'node:fs';
import os from 'node:os';
import crypto from 'node:crypto';

const app = express();
const port = Number(process.env.PORT ?? 3000);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
app.use(express.json({ limit: '1mb' }));

const PIPER_BIN = process.env.PIPER_BIN ?? 'piper';
const PIPER_MODEL = process.env.PIPER_MODEL ?? '';
const PIPER_TIMEOUT_MS = Number(process.env.PIPER_TIMEOUT_MS ?? 30000);

const personas = {
  classic: { id: 'classic', name: 'Classic PA', style: 'authoritative, warm, deliberate stadium public-address announcer' },
  hype: { id: 'hype', name: 'Hype Crew', style: 'high-energy modern ballpark MC, punchy and exciting' },
  radio: { id: 'radio', name: 'Golden Age Radio', style: 'crisp vintage baseball radio broadcaster, colorful but concise' },
  velvet: { id: 'velvet', name: 'Velvet PA', style: 'smooth, confident, polished stadium announcer with dramatic pauses' },
} as const;

type Player = { id?: string; name: string; number: number; nickname?: string; lore?: string };
type Persona = (typeof personas)[keyof typeof personas];
type Cached = { text: string; audioBase64?: string; voice: string; audioType: 'piper_wav' | 'browser_speech' };
const cache = new Map<string, Cached>();

const cacheKey = (p: Player, v: Persona) => JSON.stringify([
  p.id ?? '', p.name, p.number, p.nickname ?? '', p.lore ?? '', v.id,
]);

function fallbackScript(p: Player, v: Persona) {
  const lore = String(p.lore ?? '').trim();
  const nickname = p.nickname?.trim() ? `, ${p.nickname.trim()}` : '';
  const cue = lore ? ` ${lore}.` : '';

  switch (v.id) {
    case 'hype':
      return `BALLPARK, MAKE SOME NOISE! Number ${p.number}, ${p.name}${nickname}!${lore ? ` ${lore}!` : ''} Let's go!`;
    case 'radio':
      return `Now stepping to the plate, number ${p.number}, ${p.name}${nickname}.${cue}`;
    case 'velvet':
      return `Ladies and gentlemen, please welcome number ${p.number}, ${p.name}${nickname}.${cue}`;
    default:
      return `Your attention please... Now batting... number ${p.number}, ${p.name}${nickname}.${cue}`;
  }
}

function runPiper(text: string, model: string): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const output = path.join(os.tmpdir(), `softball-${crypto.randomUUID()}.wav`);
    const args = ['--output_file', output];
    if (model) args.unshift('--model', model);

    const child = spawn(PIPER_BIN, args, { shell: false, stdio: ['pipe', 'ignore', 'pipe'] });
    let stderr = '';
    let settled = false;

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill('SIGKILL');
      reject(new Error(`Piper timed out after ${PIPER_TIMEOUT_MS}ms`));
    }, PIPER_TIMEOUT_MS);

    child.stderr.on('data', chunk => { stderr += chunk.toString(); });
    child.on('error', err => {
      clearTimeout(timer);
      if (!settled) {
        settled = true;
        reject(new Error(`Piper could not start: ${err.message}`));
      }
    });
    child.on('close', async code => {
      clearTimeout(timer);
      if (settled) return;
      settled = true;
      if (code !== 0) {
        reject(new Error(`Piper exited with code ${code}: ${stderr.slice(-800)}`));
        return;
      }
      try {
        const wav = await fs.readFile(output);
        await fs.rm(output, { force: true });
        resolve(wav);
      } catch (err) {
        reject(err);
      }
    });

    child.stdin.end(text.replace(/[\u0000-\u001f]/g, ' ').trim() + '\n');
  });
}

async function synthesize(text: string): Promise<{ audioBase64?: string; audioType: Cached['audioType']; voice: string }> {
  // Piper is the preferred open-source local TTS engine. If it is not installed,
  // the UI falls back to the browser's local SpeechSynthesis engine.
  if (!PIPER_MODEL) {
    return { audioType: 'browser_speech', voice: 'browser-local' };
  }

  try {
    const wav = await runPiper(text, PIPER_MODEL);
    return { audioBase64: wav.toString('base64'), audioType: 'piper_wav', voice: PIPER_MODEL };
  } catch (error) {
    console.warn('Local Piper TTS unavailable; using browser SpeechSynthesis fallback:', error instanceof Error ? error.message : error);
    return { audioType: 'browser_speech', voice: 'browser-local' };
  }
}

async function announcePlayer(player: Player, persona: Persona, generateAudio = true) {
  const key = cacheKey(player, persona);
  const existing = cache.get(key);
  if (existing && (!generateAudio || existing.audioBase64 || existing.audioType === 'browser_speech')) {
    return { ...existing, audioAvailable: Boolean(existing.audioBase64), cached: true };
  }

  const text = existing?.text ?? fallbackScript(player, persona);
  let result: Cached = {
    text,
    voice: 'browser-local',
    audioType: 'browser_speech',
  };

  if (generateAudio) {
    const speech = await synthesize(text);
    result = { text, voice: speech.voice, audioType: speech.audioType, audioBase64: speech.audioBase64 };
  }

  cache.set(key, result);
  return { ...result, audioAvailable: Boolean(result.audioBase64), cached: false };
}

app.get('/api/health', (_req, res) => {
  res.json({
    ok: true,
    localOnly: true,
    cloudAI: false,
    tts: PIPER_MODEL ? 'piper' : 'browser-speech-fallback',
    piperModelConfigured: Boolean(PIPER_MODEL),
  });
});

app.get('/api/personas', (_req, res) => res.json(Object.values(personas)));

app.post('/api/announce', async (req, res) => {
  try {
    const { player, personaId = 'classic', generateAudio = true } = req.body ?? {};
    if (!player?.name || !Number.isFinite(Number(player.number))) {
      return res.status(400).json({ error: 'Player name and jersey number are required.' });
    }
    const persona = personas[personaId as keyof typeof personas];
    if (!persona) return res.status(400).json({ error: 'Invalid persona.' });

    const result = await announcePlayer({ ...player, number: Number(player.number) }, persona, Boolean(generateAudio));
    return res.json(result);
  } catch (error) {
    console.error('Announcement failed:', error);
    return res.status(500).json({ error: error instanceof Error ? error.message : 'Announcement failed.' });
  }
});

app.post('/api/precache', async (req, res) => {
  const players = (Array.isArray(req.body?.players) ? req.body.players : []).slice(0, 15) as Player[];
  const persona = personas[(req.body?.personaId || 'classic') as keyof typeof personas];
  if (!persona) return res.status(400).json({ error: 'Invalid persona.' });

  let completed = 0;
  for (const player of players) {
    try {
      await announcePlayer(player, persona, true);
      completed++;
    } catch (error) {
      console.error('Precache failed:', error);
    }
  }
  return res.json({ completed, total: players.length, complete: completed === players.length });
});

const dist = path.join(__dirname, 'dist');
app.use(express.static(dist));
app.use((_req, res) => res.sendFile(path.join(dist, 'index.html')));

export default app;

if (process.env.NODE_ENV !== 'test') {
  app.listen(port, () => console.log(`Softball Announcer Local Version listening on http://localhost:${port}`));
}
