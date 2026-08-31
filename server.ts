import express from 'express';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { createServer as createViteServer } from 'vite';

const app = express();
const port = Number(process.env.PORT ?? 3000);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
app.use(express.json({ limit: '1mb' }));

const NEUTTS_HOST = process.env.NEUTTS_HOST ?? '127.0.0.1';
const NEUTTS_PORT = Number(process.env.NEUTTS_PORT ?? 8011);
const NEUTTS_URL = `http://${NEUTTS_HOST}:${NEUTTS_PORT}`;
const NEUTTS_PYTHON = process.env.NEUTTS_PYTHON ?? 'python3';
const NEUTTS_TIMEOUT_MS = Number(process.env.NEUTTS_TIMEOUT_MS ?? 90000);
const NEUTTS_REFERENCE_DIR = process.env.NEUTTS_REFERENCE_DIR ?? path.join(process.cwd(), 'voices');

const personas = {
  classic: { id: 'classic', name: 'Classic PA', style: 'authoritative, warm, deliberate stadium public-address announcer', voice: 'classic' },
  hype: { id: 'hype', name: 'Hype Crew', style: 'high-energy modern ballpark MC, punchy and exciting', voice: 'hype' },
  radio: { id: 'radio', name: 'Golden Age Radio', style: 'crisp vintage baseball radio broadcaster, colorful but concise', voice: 'radio' },
  velvet: { id: 'velvet', name: 'Velvet PA', style: 'smooth, confident, polished stadium announcer with dramatic pauses', voice: 'velvet' },
} as const;

type Player = { id?: string; name: string; number: number; nickname?: string; lore?: string };
type Persona = (typeof personas)[keyof typeof personas];
type Cached = { text: string; audioBase64?: string; voice: string; audioType: 'neutts_wav' | 'browser_speech' };
const cache = new Map<string, Cached>();
let neuttsProcess: ReturnType<typeof spawn> | null = null;
let neuttsStart: Promise<void> | null = null;

const cacheKey = (p: Player, v: Persona) => JSON.stringify([p.id ?? '', p.name, p.number, p.nickname ?? '', p.lore ?? '', v.id]);

function limitText(text: unknown, maxChars = 700) {
  const clean = String(text ?? '').replace(/\s+/g, ' ').trim();
  if (clean.length <= maxChars) return clean;
  const clipped = clean.slice(0, maxChars);
  const boundary = Math.max(clipped.lastIndexOf('.'), clipped.lastIndexOf('!'), clipped.lastIndexOf('?'));
  return (boundary >= Math.floor(maxChars * 0.55) ? clipped.slice(0, boundary + 1) : clipped).trim();
}

function fallbackScript(p: Player, v: Persona) {
  const lore = limitText(p.lore, 180);
  const nickname = p.nickname?.trim() ? `, ${limitText(p.nickname, 80)}` : '';
  switch (v.id) {
    case 'hype': return limitText(`BALLPARK, MAKE SOME NOISE! Number ${p.number}, ${p.name}${nickname}!${lore ? ` ${lore}!` : ''} Let's go!`);
    case 'radio': return limitText(`Now stepping to the plate, number ${p.number}, ${p.name}${nickname}.${lore ? ` ${lore}.` : ''}`);
    case 'velvet': return limitText(`Ladies and gentlemen, please welcome number ${p.number}, ${p.name}${nickname}.${lore ? ` ${lore}.` : ''}`);
    default: return limitText(`Your attention please... Now batting... number ${p.number}, ${p.name}${nickname}.${lore ? ` ${lore}.` : ''}`);
  }
}

async function neuttsHealthy() {
  try { return (await fetch(`${NEUTTS_URL}/health`, { signal: AbortSignal.timeout(1500) })).ok; }
  catch { return false; }
}

async function startNeutts() {
  if (await neuttsHealthy()) return;
  if (neuttsStart) return neuttsStart;
  neuttsStart = new Promise<void>((resolve, reject) => {
    const script = path.join(__dirname, 'tts', 'neutts_service.py');
    neuttsProcess = spawn(NEUTTS_PYTHON, [script], { shell: false, env: { ...process.env, NEUTTS_HOST, NEUTTS_PORT: String(NEUTTS_PORT), NEUTTS_REFERENCE_DIR }, stdio: ['ignore', 'pipe', 'pipe'] });
    let startupError = '';
    neuttsProcess.stdout?.on('data', chunk => console.log(`[NeuTTS] ${chunk.toString().trim()}`));
    neuttsProcess.stderr?.on('data', chunk => { startupError = `${startupError}${chunk}`.slice(-4000); console.error(`[NeuTTS] ${chunk.toString().trim()}`); });
    neuttsProcess.once('error', err => reject(new Error(`Could not start NeuTTS Python service: ${err.message}`)));
    neuttsProcess.once('exit', code => { neuttsProcess = null; if (code !== 0) console.error(`NeuTTS exited with code ${code}: ${startupError.slice(-1000)}`); });
    const deadline = Date.now() + 60000;
    const poll = async () => {
      if (await neuttsHealthy()) return resolve();
      if (Date.now() >= deadline) return reject(new Error(`NeuTTS Air service did not become ready. ${startupError.slice(-1000)}`));
      setTimeout(poll, 500);
    };
    void poll();
  }).finally(() => { neuttsStart = null; });
  return neuttsStart;
}

async function synthesize(text: string, persona: Persona) {
  try {
    await startNeutts();
    const response = await fetch(`${NEUTTS_URL}/synthesize`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: limitText(text), voice: persona.voice }), signal: AbortSignal.timeout(NEUTTS_TIMEOUT_MS) });
    const data = await response.json() as { audioBase64?: string; voice?: string; error?: string };
    if (!response.ok || !data.audioBase64) throw new Error(data.error || `NeuTTS returned HTTP ${response.status}`);
    return { audioBase64: data.audioBase64, audioType: 'neutts_wav' as const, voice: data.voice ?? persona.voice };
  } catch (error) {
    console.warn('NeuTTS Air unavailable; using browser SpeechSynthesis fallback:', error instanceof Error ? error.message : error);
    return { audioType: 'browser_speech' as const, voice: 'browser-local' };
  }
}

async function announcePlayer(player: Player, persona: Persona, generateAudio = true) {
  const key = cacheKey(player, persona);
  const existing = cache.get(key);
  if (existing && (!generateAudio || existing.audioBase64 || existing.audioType === 'browser_speech')) return { ...existing, audioAvailable: Boolean(existing.audioBase64), cached: true };
  const text = existing?.text ?? fallbackScript(player, persona);
  let result: Cached = { text, voice: 'browser-local', audioType: 'browser_speech' };
  if (generateAudio) { const speech = await synthesize(text, persona); result = { text, voice: speech.voice, audioType: speech.audioType, audioBase64: speech.audioBase64 }; }
  cache.set(key, result);
  return { ...result, audioAvailable: Boolean(result.audioBase64), cached: false };
}

app.get('/api/health', async (_req, res) => {
  const ready = await neuttsHealthy();
  res.json({ ok: true, localOnly: true, cloudAI: false, tts: ready ? 'neutts-air' : 'browser-speech-fallback', neuttsReady: ready });
});
app.get('/api/personas', (_req, res) => res.json(Object.values(personas)));

app.post('/api/announce', async (req, res) => {
  try {
    const { player, personaId = 'classic', generateAudio = true } = req.body ?? {};
    if (!player?.name || !Number.isFinite(Number(player.number))) return res.status(400).json({ error: 'Player name and jersey number are required.' });
    const persona = personas[personaId as keyof typeof personas];
    if (!persona) return res.status(400).json({ error: 'Invalid persona.' });
    const safePlayer = { ...player, name: limitText(player.name, 100), nickname: limitText(player.nickname, 80), lore: limitText(player.lore, 180), number: Number(player.number) };
    return res.json(await announcePlayer(safePlayer, persona, Boolean(generateAudio)));
  } catch (error) { return res.status(500).json({ error: error instanceof Error ? error.message : 'Announcement failed.' }); }
});

app.post('/api/precache', async (req, res) => {
  const players = (Array.isArray(req.body?.players) ? req.body.players : []).slice(0, 15) as Player[];
  const persona = personas[(req.body?.personaId || 'classic') as keyof typeof personas];
  if (!persona) return res.status(400).json({ error: 'Invalid persona.' });
  let completed = 0;
  for (const player of players) { try { await announcePlayer({ ...player, name: limitText(player.name, 100), nickname: limitText(player.nickname, 80), lore: limitText(player.lore, 180) }, persona, true); completed++; } catch (error) { console.error('Precache failed:', error); } }
  return res.json({ completed, total: players.length, complete: completed === players.length });
});

async function startServer() {
  if (process.env.NODE_ENV === 'production') {
    const dist = path.join(process.cwd(), 'dist');
    app.use(express.static(dist));
    app.use((_req, res) => res.sendFile(path.join(dist, 'index.html')));
    app.listen(port, () => console.log(`Softball Announcer Local Version listening on http://localhost:${port}`));
    return;
  }

  const vite = await createViteServer({ server: { middlewareMode: true }, appType: 'spa' });
  app.use(vite.middlewares);
  app.listen(port, () => console.log(`Softball Announcer Local Version dev server listening on http://localhost:${port}`));
}

if (process.env.NODE_ENV !== 'test') void startServer();
export default app;
