// The page's copy of Python's state. Python sends whole slices ({meta, slices, log, events}); components read a
// slice with useSlice(name) and redraw when it changes.
import { useSyncExternalStore } from './lib.js';

const state = { meta: {}, slices: {}, log: [] };
const listeners = new Set();
const eventHandlers = new Map();
let version = 0;

function notify() {
  version += 1;
  listeners.forEach((fn) => fn());
}

// the newest message seq each slice came in (host.py: ready's answer and a push run at once, and a push sent after
// it can arrive before it: an older slice never replaces a newer one) and the log's
const seen = {};
let logSeq = 0;

export function receive(message) {
  if (!message || typeof message !== 'object') return;
  const seq = typeof message.seq === 'number' ? message.seq : null;
  if (message.meta) state.meta = message.meta;
  if (message.slices) {
    const fresh = {};
    Object.keys(message.slices).forEach((name) => {
      if (seq !== null && seen[name] > seq) return;
      fresh[name] = message.slices[name];
      if (seq !== null) seen[name] = seq;
    });
    state.slices = { ...state.slices, ...fresh };
  }
  if (message.log) {
    const lines = message.log.lines;
    if (!message.log.clear) state.log = state.log.concat(lines);
    else if (seq !== null && logSeq > seq) state.log = lines.concat(state.log);   // newer lines came first: they follow
    else state.log = lines.slice();
    if (seq !== null) logSeq = Math.max(logSeq, seq);
    if (state.log.length > 5000) state.log = state.log.slice(-5000);
  }
  notify();
  (message.events || []).forEach(([name, payload]) => (eventHandlers.get(name) || []).forEach((fn) => fn(payload)));
}

export function onEvent(name, fn) {
  if (!eventHandlers.has(name)) eventHandlers.set(name, []);
  eventHandlers.get(name).push(fn);
}

function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useSlice(name) {
  return useSyncExternalStore(subscribe, () => state.slices[name]);
}

export function useLog() {
  return useSyncExternalStore(subscribe, () => state.log);
}

export function useMeta() {
  return useSyncExternalStore(subscribe, () => state.meta);
}

window.OT = { receive, state };
