import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

type Player = { id: string; name: string; number: number; nickname?: string; lore?: string };
type Persona = { id: string; name: string; style: string };
const blank = (i: number): Player => ({ id: crypto.randomUUID(), name: '', number: i + 1, nickname: '', lore: '' });

function speakLocally(text: string, personaId: string) {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = personaId === 'hype' ? 1.08 : personaId === 'radio' ? 0.92 : personaId === 'velvet' ? 0.88 : 0.98;
  utterance.pitch = personaId === 'hype' ? 1.05 : personaId === 'radio' ? 0.92 : 1;
  window.speechSynthesis.speak(utterance);
}

function App() {
  const [team, setTeam] = useState('Home Team');
  const [players, setPlayers] = useState<Player[]>(Array.from({ length: 9 }, (_, i) => blank(i)));
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [personaId, setPersonaId] = useState('classic');
  const [selected, setSelected] = useState(0);
  const [announcement, setAnnouncement] = useState('');
  const [audio, setAudio] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [audioError, setAudioError] = useState('');

  useEffect(() => { fetch('/api/personas').then(r => r.json()).then(setPersonas).catch(() => {}); }, []);
  const active = players[selected];
  const validPlayers = useMemo(() => players.filter(p => p.name.trim()), [players]);
  const update = (index: number, patch: Partial<Player>) => setPlayers(prev => prev.map((p, i) => i === index ? { ...p, ...patch } : p));
  const move = (index: number, direction: -1 | 1) => setPlayers(prev => { const next = index + direction; if (next < 0 || next >= prev.length) return prev; const copy = [...prev]; [copy[index], copy[next]] = [copy[next], copy[index]]; return copy; });

  const announce = async (player = active) => {
    if (!player?.name.trim()) return;
    setBusy(true); setAudio(null); setAudioError('');
    try {
      const r = await fetch('/api/announce', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ player, personaId, generateAudio: true }) });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || 'Announcement failed');
      setAnnouncement(data.text || '');
      if (data.audioBase64 && data.audioType === 'piper_wav') {
        const audioUrl = `data:audio/wav;base64,${data.audioBase64}`;
        setAudio(audioUrl);
        const playerAudio = new Audio(audioUrl);
        playerAudio.preload = 'auto';
        await playerAudio.play();
      } else {
        speakLocally(data.text || '', personaId);
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Announcement failed';
      setAudioError(message);
      if (announcement) return;
      setAnnouncement(message);
    } finally { setBusy(false); }
  };

  const precache = async () => { setBusy(true); try { await fetch('/api/precache', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ players: validPlayers, personaId }) }); } finally { setBusy(false); } };
  const add = () => players.length < 15 && setPlayers(p => [...p, blank(p.length)]);
  const remove = (i: number) => { if (players.length <= 1) return; setPlayers(p => p.filter((_, n) => n !== i)); setSelected(s => Math.min(s, players.length - 2)); };

  return <div className="app">
    <header><div><span className="eyebrow">LOCAL BALLPARK PA SYSTEM</span><h1>ANNOUNCER <b>BOOTH</b></h1><p>{team || 'Home Team'} · {validPlayers.length} players ready</p></div><button className="ghost" onClick={precache} disabled={busy}>PRE-CACHE LINEUP</button></header>
    <main>
      <section className="hero"><div><span className="eyebrow">NOW ANNOUNCING</span><div className="bigNumber">#{active?.number ?? '--'}</div><h2>{active?.name || 'Select a batter'}</h2><p>{active?.nickname ? `“${active.nickname}”` : 'Build your lineup, then send a batter to the PA.'}</p></div><button className="announce" onClick={() => announce()} disabled={busy || !active?.name}> {busy ? 'GENERATING…' : '▶ ANNOUNCE BATTER'}</button></section>
      <div className="grid">
        <section className="panel lineup"><div className="panelHead"><h3>LINEUP</h3><div><input value={team} onChange={e => setTeam(e.target.value)} aria-label="Team name"/><button onClick={add} disabled={players.length >= 15}>+ PLAYER</button></div></div>
          <div className="slots">{players.map((p, i) => <div className={`slot ${i === selected ? 'selected' : ''}`} key={p.id} onClick={() => setSelected(i)}><span className="order">{i + 1}</span><input value={p.name} onChange={e => update(i,{name:e.target.value})} placeholder="Player name" onClick={e=>e.stopPropagation()}/><input className="num" type="number" min="0" max="99" value={p.number} onChange={e=>update(i,{number:Number(e.target.value)})} onClick={e=>e.stopPropagation()}/><button onClick={e=>{e.stopPropagation();move(i,-1)}} disabled={i===0}>↑</button><button onClick={e=>{e.stopPropagation();move(i,1)}} disabled={i===players.length-1}>↓</button><button className="delete" onClick={e=>{e.stopPropagation();remove(i)}}>×</button></div>)}</div></section>
        <section className="panel"><div className="panelHead"><h3>PLAYER PROFILE</h3></div><label>Nickname<input value={active?.nickname || ''} onChange={e=>update(selected,{nickname:e.target.value})} placeholder="The nickname the crowd knows"/></label><label>Hype cue / lore<textarea value={active?.lore || ''} onChange={e=>update(selected,{lore:e.target.value})} placeholder="A safe, factual cue for the announcer…"/></label><div className="personas"><span className="label">ANNOUNCER PERSONA</span>{personas.map(p=><button key={p.id} className={personaId===p.id?'persona active':'persona'} onClick={()=>setPersonaId(p.id)}><b>{p.name}</b><small>{p.style}</small></button>)}</div></section>
      </div>
      <section className="panel output"><div className="panelHead"><h3>PA OUTPUT</h3>{audio && <audio controls src={audio}/>}</div><div className="script">{announcement || 'Your local announcement will appear here.'}</div>{audioError && <p role="alert">Audio: {audioError}</p>}</section>
    </main><footer>LOCAL VERSION · NO CLOUD AI · PIPER TTS · BUILT FOR THE BALLPARK</footer>
  </div>;
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
