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
};

const cache = new Map<string, { text: string; audioBase64?: string; voice: string }>();

function key(player: any, persona: any) {
  return JSON.stringify([player.id ?? '', player.name ?? '', player.number ?? '', player.nickname ?? '', player.lore ?? '', persona.id, persona.voice]);
}

function fallbackScript(player: any, persona: any) {
  const lore = String(player.lore ?? '').trim();
  const nickname = player.nickname ? `, ${player.nickname}` : '';
  if (persona.id === 'hype') return `BALLPARK, MAKE SOME NOISE! Number ${player.number}, ${player.name}${nickname}${lore ? `. ${lore}!` : '!'} Let's go!`;
  if (persona.id === 'radio') return `Now stepping to the plate, number ${player.number}, ${player.name}${nickname}${lore ? `. ${lore}.` : '.'}`;
  if (persona.id === 'velvet') return `Ladies and gentlemen, please welcome number ${player.number}, ${player.name}${nickname}${lore ? `. ${lore}.` : '.'}`;
  return `Your attention please... Now batting... number ${player.number}, ${player.name}${nickname}${lore ? `. ${lore}.` : '.'}`;
}

async function writeScript(player: any, persona: any) {
  if (!openai) return fallbackScript(player, persona);
  try {
    const response = await openai.responses.create({
      model: process.env.OPENAI_TEXT_MODEL || 'gpt-5.6-luna',
      input: `Write a short softball/baseball PA announcement. Persona: ${persona.name}. Style: ${persona.style}. Player: ${player.name}, #${player.number}. Nickname: ${player.nickname || 'none'}. Hype cue: ${player.lore || 'none'}. Use 1-2 sentences. Include name and number. Do not invent stats, game situation, position, achievements, or facts. Output only the spoken announcement.`,
    });
    return response.output_text?.trim() || fallbackScript(player, persona);
  } catch {
    return fallbackScript(player, persona);
  }
}

app.get('/api/health', (_req, res) => res.json({ ok: true, openaiConfigured: Boolean(openai) }));
app.get('/api/personas', (_req, res) => res.json(Object.values(personas)));

app.post('/api/announce', async (req, res) => {
  const { player, personaId = 'classic', generateAudio = true } = req.body ?? {};
  if (!player?.name || !personaId || !personas[personaId as keyof typeof personas]) return res.status(400).json({ error: 'Player name and valid persona are required.' });
  const persona = personas[personaId as keyof typeof personas];
  const cacheKey = key(player, persona);
  const existing = cache.get(cacheKey);
  if (existing && (!generateAudio || existing.audioBase64)) return res.json({ ...existing, cached: true });

  const text = existing?.text || await writeScript(player, persona);
  let audioBase64: string | undefined;
  if (generateAudio && openai) {
    try {
      const speech = await openai.audio.speech.create({ model: process.env.OPENAI_TTS_MODEL || 'gpt-4o-mini-tts', voice: persona.voice as any, input: text, response_format: 'mp3' });
      audioBase64 = Buffer.from(await speech.arrayBuffer()).toString('base64');
    } catch (error) {
      console.error('TTS failed:', error);
    }
  }
  const result = { text, audioBase64, voice: persona.voice };
  cache.set(cacheKey, result);
  res.json({ ...result, cached: false, audioAvailable: Boolean(audioBase64) });
});

app.post('/api/precache', async (req, res) => {
  const players = Array.isArray(req.body?.players) ? req.body.players : [];
  const personaId = req.body?.personaId || 'classic';
  const persona = personas[personaId as keyof typeof personas];
  if (!persona) return res.status(400).json({ error: 'Invalid persona.' });
  let completed = 0;
  for (const player of players.slice(0, 15)) {
    await (async () => { try { await fetch(`http://127.0.0.1:${port}/api/announce`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ player, personaId, generateAudio: true }) }); completed++; } catch {} })();
  }
  res.json({ completed, total: Math.min(players.length, 15) });
});

const dist = path.join(__dirname, 'dist');
app.use(express.static(dist));
app.get('*', (_req, res) => res.sendFile(path.join(dist, 'index.html')));

app.listen(port, () => console.log(`Softball Announcer 0.3 beta listening on http://localhost:${port}`));
