// Lobby chimes (owner 2026-11-07): very soft, short tones made with Web Audio (no sound files). One when your lobby
// opens (you made or joined it), another when somebody enters, a third when you leave or the lobby closes. They play
// on any tab: App watches the `multiplayer` slice with useLobbyChimes.
import { useEffect, useRef } from './lib.js';

const VOLUME = 0.045;        // low: a hint, not an alert
let audio = null;

function ctx() {
  try {
    if (!audio) audio = new (window.AudioContext || window.webkitAudioContext)();
    if (audio.state === 'suspended') audio.resume();
    return audio;
  } catch (_e) {
    return null;
  }
}

// notes: [[frequency Hz, start s, length s], ...]
function play(notes, type = 'sine') {
  const ac = ctx();
  if (!ac) return;
  const t0 = ac.currentTime + 0.02;
  notes.forEach(([freq, at, len]) => {
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0, t0 + at);
    gain.gain.linearRampToValueAtTime(VOLUME, t0 + at + 0.02);           // soft attack
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + at + len);       // and a gentle fade
    osc.connect(gain).connect(ac.destination);
    osc.start(t0 + at);
    osc.stop(t0 + at + len + 0.05);
  });
}

export const CHIMES = {
  open: () => play([[659.25, 0, 0.5], [880, 0.12, 0.7]]),                              // E5 then A5, rising
  enter: () => play([[523.25, 0, 0.45], [659.25, 0.1, 0.45], [783.99, 0.2, 0.8]], 'triangle'),  // C E G
  leave: () => play([[587.33, 0, 0.5], [392, 0.16, 0.8]]),                             // D5 down to G4
};

// what changed between two looks at the lobby: 'open' | 'enter' | 'leave' | null. `before` undefined: the first look
// (a lobby already open when the page loads makes no sound)
export function lobbyChange(before, after) {
  if (before === undefined) return null;
  const was = before ? (before.players || []).length : 0;
  const now = after ? (after.players || []).length : 0;
  if (!before && after) return 'open';
  if (before && !after) return 'leave';
  if (before && after && before.code !== after.code) return 'open';
  if (now > was) return 'enter';
  return null;
}

export function useLobbyChimes(mp) {
  const last = useRef(undefined);
  const lobby = mp ? mp.lobby || null : undefined;
  useEffect(() => {
    if (lobby === undefined) return;          // the slice has not come yet
    const change = lobbyChange(last.current, lobby);
    last.current = lobby;
    if (change) CHIMES[change]();
  }, [lobby]);
}
