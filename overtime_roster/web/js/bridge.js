// Talking to Python: pywebview's js_api in the app window; in browser mode (the URL carries ?token=) a POST per
// call and a server-sent event stream for the pushes. With a fixture (window.__FIXTURE__ put into the page, or
// ?fixture=<file.json> next to index.html) the page draws that state and its calls do nothing: for pictures.
import { receive } from './store.js';

export const params = new URLSearchParams(location.search);
const token = params.get('token');
let api = null;
export let mode = 'window';
export const offline = params.has('fixture') || !!window.__FIXTURE__;

function pywebviewReady() {
  return new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.ready) return resolve();
    window.addEventListener('pywebviewready', () => resolve(), { once: true });
  });
}

// The window library sets itself up once per page load, and forgets what was asked before. A page reloaded while the one
// before it was still loading gets it twice: the first question is never answered, so it is asked again.
function firstData() {
  return new Promise((resolve, reject) => {
    const ask = () => { api = window.pywebview.api; api.ready().then(answered, reject); };
    const answered = (reply) => { window.removeEventListener('pywebviewready', ask); resolve(reply); };
    window.addEventListener('pywebviewready', ask);
    ask();
  });
}

function httpApi() {
  return new Proxy({}, {
    get: (_, name) => (...args) => fetch(`/api/${name}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Overtime-Token': token },
      body: JSON.stringify({ args }),
    }).then((r) => r.json()),
  });
}

function listen() {
  return new Promise((resolve) => {
    const es = new EventSource(`/api/events?token=${encodeURIComponent(token)}`);
    es.onmessage = (e) => { try { receive(JSON.parse(e.data)); } catch (err) { console.error(err); } };
    es.onopen = () => resolve();
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) receive({ slices: { status: { text: 'Lost the connection to Overtime Roster. Is it still running?', tone: 'bad' } } });
      resolve();
    };
  });
}

async function fixture() {
  if (window.__FIXTURE__) return window.__FIXTURE__;
  const reply = await fetch(params.get('fixture'));
  return reply.json();
}

export async function connect() {
  if (offline) {
    mode = 'fixture';
    const state = await fixture();
    api = { ready: () => state };
  } else if (token) {
    mode = 'browser';
    api = httpApi();
    await listen();               // subscribe first: nothing pushed after ready() is missed
  } else {
    await pywebviewReady();
    receive(await firstData());
    return;
  }
  receive(await api.ready());
}

// a call Python has but has not built yet: the Help bar says so (Python's status line), nothing to log
const NOT_BUILT = 'not built yet';

export function call(name, ...args) {
  const fn = api && api[name];
  if (!fn) {
    if (api && mode !== 'fixture') console.error('unknown call', name);
    return Promise.resolve(null);
  }
  return Promise.resolve(fn(...args))
    .then((reply) => {
      if (reply && reply.error && reply.error !== NOT_BUILT) console.error(name, reply.error);
      return reply;
    })
    .catch((err) => { console.error(name, err); return null; });
}
