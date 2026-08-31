import 'dotenv/config';
import express from 'express';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import OpenAI from 'openai';

const app = express();
const port = Number(process.env.PORT ?? 3000);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const openai = process.env.OPENAI_API_KEY ? new OpenAI({ apiKey: process.env.OPENAI_API_KEY }) : null;
app.use(express.json({ limit: '1mb' }));

const personas = {
  classic: { id: 'classic', name: 'Classic PA', voice: 'onyx', style: 'authoritative, warm, deliberate stadium public-address announcer' },
  hype: { id: 'hype', name: 'Hype Crew', voice: 'alloy', style: 'high-energy modern ballpark MC, punchy and exciting' },
  radio: { id: 'radio', name: 'Golden Age Radio', voice: 'echo', style: 'crisp vintage baseball radio broadcaster, colorful but concise' },
  velvet: { id: 'velvet', name: 'Velvet PA', voice: 'shimmer', style: 'smooth, confident, polished stadium announcer with dramatic pauses' },
} as const;

type Player = { id?: string; name: string; number: number; nickname?: string; lore?: string };
type Persona = (typeof personas)[keyof typeof personas];
type Cached = { text: string; audioBase64?: string; voice: string };
const cache = new Map<string, Cached>();
const key = (p: Player, v: Persona) => JSON.stringify([p.id ?? '', p.name, p.number, p.nickname ?? '', p.lore ?? '', v.id, v.voice]);

function limitText(text: unknown, maxChars = 700) {
  const clean = String(text ?? '').replace(/\s+/g, ' ').trim();
  if (clean.length <= maxChars) return clean;
  const clipped = clean.slice(0, maxChars);
  const boundary = Math.max(clipped.lastIndexOf('.'), clipped.lastIndexOf('!'), clipped.lastIndexOf('?'));
  return (boundary >= Math.floor(maxChars * 0.55) ? clipped.slice(0, boundary + 1) : clipped).trim();
}

function fallbackScript(p: Player, v: Persona) {
  const lore = limitText(p.lore, 180);
  const nick = p.nickname ? `, ${limitText(p.nickname, 80)}` : '';
  if (v.id === 'hype') return limitText(`BALLPARK, MAKE SOME NOISE! Number ${p.number}, ${p.name}${nick}${lore ? `. ${lore}!` : '!'} Let's go!`);
  if (v.id === 'radio') return limitText(`Now stepping to the plate, number ${p.number}, ${p.name}${nick}${lore ? `. ${lore}.` : '.'}`);
  if (v.id === 'velvet') return limitText(`Ladies and gentlemen, please welcome number ${p.number}, ${p.name}${nick}${lore ? `. ${lore}.` : '.'}`);
  return limitText(`Your attention please... Now batting... number ${p.number}, ${p.name}${nick}${lore ? `. ${lore}.` : '.'}`);
}

// Hard application-level ceiling: generated announcements are intentionally tiny.
// 700 characters is far below 2048 tokens even for unusually token-heavy input.
async function writeScript(p: Player, v: Persona) {
  if (!openai) return fallbackScript(p, v);
  const name = limitText(p.name, 100);
  const nickname = limitText(p.nickname, 80) || 'none';
  const lore = limitText(p.lore, 180) || 'none';
  try {
    const r = await openai.responses.create({
      model: process.env.OPENAI_TEXT_MODEL || 'gpt-4o-mini',
      max_output_tokens: 120,
      input: `Write ONE very short softball/baseball PA announcement. Persona: ${v.name}. Style: ${v.style}. Player: ${name}, #${p.number}. Nickname: ${nickname}. Hype cue: ${lore}. Maximum 2 sentences and 300 characters. Include name and number. Do not invent stats, game situation, position, achievements, or facts. Output only the spoken announcement.`
    });
    return limitText(r.output_text?.trim() || fallbackScript(p, v));
  } catch (e) {
    console.error('Script generation failed', e);
    return fallbackScript(p, v);
  }
}

async function makeSpeech(text: string, v: Persona) {
  if (!openai) throw new Error('OPENAI_API_KEY is not configured on the server.');
  const safeText = limitText(text);
  const speech = await openai.audio.speech.create({
    model: process.env.OPENAI_TTS_MODEL || 'gpt-4o-mini-tts',
    voice: v.voice,
    input: safeText,
    response_format: 'mp3'
  });
  return Buffer.from(await speech.arrayBuffer()).toString('base64');
}

async function announcePlayer(p: Player, v: Persona, generateAudio = true): Promise<Cached & { audioAvailable: boolean }> {
  const k = key(p, v);
  const existing = cache.get(k);
  if (existing && (!generateAudio || existing.audioBase64)) return { ...existing, audioAvailable: Boolean(existing.audioBase64) };
  const text = existing?.text || await writeScript(p, v);
  let audioBase64 = existing?.audioBase64;
  if (generateAudio && !audioBase64) audioBase64 = await makeSpeech(text, v);
  const result = { text: limitText(text), audioBase64, voice: v.voice, audioAvailable: Boolean(audioBase64) };
  cache.set(k, result);
  return result;
}

app.get('/api/health', (_req, res) => res.json({ ok: true, openaiConfigured: Boolean(openai) }));
app.get('/api/personas', (_req, res) => res.json(Object.values(personas)));

app.post('/api/announce', async (req, res) => {
  try {
    const { player, personaId = 'classic', generateAudio = true } = req.body ?? {};
    if (!player?.name || !personas[personaId as keyof typeof personas]) return res.status(400).json({ error: 'Player name and valid persona are required.' });
    const persona = personas[personaId as keyof typeof personas];
    const result = await announcePlayer(player, persona, Boolean(generateAudio));
    res.json({ ...result, cached: false });
  } catch (e) {
    console.error('Announcement failed', e);
    const message = e instanceof Error ? e.message : 'Announcement failed.';
    res.status(502).json({ error: message });
  }
});

app.post('/api/precache', async (req, res) => {
  const players = (Array.isArray(req.body?.players) ? req.body.players : []).slice(0, 15) as Player[];
  const persona = personas[(req.body?.personaId || 'classic') as keyof typeof personas];
  if (!persona) return res.status(400).json({ error: 'Invalid persona.' });
  let completed = 0;
  for (const p of players) {
    try { await announcePlayer(p, persona, true); completed++; }
    catch (e) { console.error('Precache failed', e); }
  }
  res.json({ completed, total: players.length, complete: completed === players.length });
});

const dist = path.join(__dirname, 'dist');
app.use(express.static(dist));
app.use((_req, res) => res.sendFile(path.join(dist, 'index.html')));

export default app;
if (process.env.VERCEL !== '1') app.listen(port, () => console.log(`Softball Announcer 0.3 beta listening on http://localhost:${port}`));
