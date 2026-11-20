// The frame around the tabs: NHL 19's page, the header, the tab row, the Help bar, the Details drawer, questions.
import { html, cls, useRef, useLayoutEffect, useState, useEffect } from './lib.js';
import { ProgressBar, Button, Modal, Keycap } from './ui.js';
import { call } from './bridge.js';
import { useLog } from './store.js';

// NHL 19's menu page: the dark blue-black, a red-orange glow at the left, diagonal stripes and streaks
export function Backdrop() {
  return html`<div class="backdrop" aria-hidden="true">
    <div class="dots"></div>
    <div class="stripes"></div>
    <div class="stripes low"></div>
    <div class="streak s1"></div><div class="streak s2"></div><div class="streak s3"></div>
  </div>`;
}

// the OVERTIME wordmark | "brought to you by" the Puck Peak logo (owner 2026-11-13, mockup B in
// docs/ui/mockups/branding.html), then the game line and the version
// The green Play NHL 19 button, top right on every tab (owner 2026-11-11): grey until a game is found; it starts the
// build chosen on Setup's Boost performance card. play: {can, text, why, progress} (shell.app)
function PlayButton({ play }) {
  const p = play || { can: false, text: 'Play NHL 19', why: 'Find NHL 19 first: press Find game in Setup.' };
  const part = typeof p.progress === 'number' ? Math.max(0, Math.min(1, p.progress)) : null;
  return html`<button type="button" class=${cls('playnow', p.can && 'ready', part !== null && 'getting')}
      disabled=${!p.can} title=${p.why || ''} onClick=${() => call('setup_play')}>
    ${part !== null && html`<span class="fill" style=${{ width: `${part * 100}%` }}></span>`}
    <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5v11l9.5-5.5z" fill="currentColor"/></svg>
    <span class="label">${p.text}</span>
  </button>`;
}

// The Puck Peak apps, top left, mirroring Play (owner 2026-11-13, docs/ui/mockups/apps-promo.html): Blueline (NHL
// Legacy), Overtime in the middle (this app: lit in its own orange, "You are here"), Faceoff (NHL 27), the other two
// quiet until pointed at (owner 2026-11-13, docs/ui/app-dock-kit/DESIGN.md). Each opens its page; a card tells what it is.
const APPS = [
  { id: 'blueline', name: 'Blueline', tone: 'blue', title: 'Blueline · NHL Legacy on PC',
    text: 'NHL Legacy Updated and Online with a few clicks. 32 teams, lobbies, edit everything.' },
  { id: 'overtime', name: 'Overtime', tone: 'here', title: 'Overtime · NHL 19 on PC',
    text: 'NHL 19 Updated and Online with a few clicks. 32 teams, lobbies, edit everything.' },
  { id: 'faceoff', name: 'Faceoff', tone: 'red', title: 'Faceoff · NHL 27 on PC',
    text: 'Play NHL 27 on PC with steady pacing and more to come.' },
];

function AppDock() {
  return html`<div class="appdock">
    ${APPS.map((a) => html`<button type="button" key=${a.id} class=${cls('dk', a.tone)} aria-disabled=${a.tone === 'here'}
        onClick=${a.tone === 'here' ? null : () => call('open_app', a.id)}>
      <img src=${`img/app-${a.id}.png`} alt="" draggable="false"/><b>${a.name}</b>
      <span class="tip" role="tooltip"><strong>${a.title}</strong><span>${a.text}</span></span>
    </button>`)}
  </div>`;
}

export function Header({ meta, play }) {
  const [name, game, version] = meta.title || [meta.app_name, '', meta.version];
  return html`<header class="header">
    <${AppDock}/>
    <${PlayButton} play=${play}/>
    <div class="brand">
      <div class="wordmark">${name}</div>
      <div class="vsep"></div>
      <div class="by" title=${meta.site_label} onClick=${() => call('open_site')}>Brought to you by
        <img class="logo" src="img/logo.png" alt="Puck Peak" draggable="false"/></div>
    </div>
    <div><div class="crumb"><span class="light">${game}</span>
      <span class="sep">|</span><span class="ver">version ${version}</span></div></div>
  </header>`;
}

// [L1] the nine tabs [R1]; the active one red-orange over a sliding bar
export function TabBar({ tabs, tab, onTab }) {
  const box = useRef(null);
  const [thumb, setThumb] = useState(null);
  useLayoutEffect(() => {
    const measure = () => {
      const el = box.current && box.current.querySelector('button.on');
      if (el) setThumb({ x: el.offsetLeft, w: el.offsetWidth });
    };
    measure();
    const watch = new ResizeObserver(measure);     // fonts arriving, the window resized
    watch.observe(box.current);
    return () => watch.disconnect();
  }, [tab]);
  const index = tabs.findIndex((t) => t.id === tab);
  const step = (d) => onTab(tabs[(index + d + tabs.length) % tabs.length].id);
  return html`<nav class="tabs">
    <${Keycap} k="L1" title="Ctrl+Page Up" onClick=${() => step(-1)}/>
    <div class="tabset" ref=${box} role="tablist">
      ${thumb && html`<span class="thumb" style=${{ width: thumb.w + 'px', transform: `translateX(${thumb.x}px)` }}></span>`}
      ${tabs.map((t, k) => html`<button type="button" key=${t.id} role="tab" aria-selected=${t.id === tab}
          class=${cls(t.id === tab && 'on', `tab-${t.id}`)} title=${`Ctrl+${k + 1}`} onClick=${() => onTab(t.id)}>${t.label}</button>`)}
    </div>
    <${Keycap} k="R1" title="Ctrl+Page Down" onClick=${() => step(1)}/>
  </nav>`;
}

// The support strip under the tab row, on every tab (0.98.0, owner: as Faceoff 0.30.0): Buy me a coffee first, Discord
// second. Discord's mark (simple-icons, CC0) is drawn here: the page loads nothing from the internet.
export const DISCORD_MARK = 'M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z';

export function SupportStrip() {
  return html`<aside class="support" aria-label="Support Overtime">
    <span class="sup-heart" aria-hidden="true">♥</span>
    <span class="sup-text"><span class="sup-long">Support the development, updates and maintenance.</span><span
      class="sup-short">Support the development.</span></span>
    <button type="button" class="kofi" title="ko-fi.com/iksperial" onClick=${() => call('open_kofi')}>
      <span class="cup" aria-hidden="true">☕</span><span class="t">Buy me a coffee</span></button>
    <button type="button" class="discord" title="gg.puckpeak.com" onClick=${() => call('open_discord')}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d=${DISCORD_MARK}/></svg><span class="t">Join our Discord</span></button>
  </aside>`;
}

// progress, the status (its own slice, pushed first: it never waits for the others), the keys.
// status: {text, tone, busy, progress: 0..1 | < 0 (running, no end known) | null, amount: a short count beside the % (Patch:
// "Patched 10.34 GB", counted as it writes) or none}; tip: shown when the status is empty
export function HelpBar({ status, tip, enter, detailsOpen, onDetails, onEnter }) {
  const s = status || {};
  const p = s.progress;
  const has = p != null;
  const indeterminate = has && p < 0;
  const value = has && !indeterminate ? p : 0;
  const text = s.text || tip || '';
  return html`<footer class="helpbar">
    ${(s.busy || (has && value < 1)) && html`<${ProgressBar} value=${value} active=${!!s.busy && !indeterminate} indeterminate=${indeterminate}/>`}
    ${(s.busy || (has && value < 1)) && html`<span class="pct">${has && !indeterminate ? Math.round(value * 100) + '%' : ''}</span>`}
    ${!s.busy && s.tone === 'good' && html`<span class="done-tick">✓</span>`}
    ${s.amount && html`<span class="amount">[${s.amount}]</span>`}
    <span class=${cls('status', s.text ? s.tone : 'tip')} title=${text}>${text}</span>
    <span class="keys">
      ${enter && html`<span class="key" title="✕ or Enter" onClick=${onEnter}><${Keycap} k="✕"/><span class="or">/</span><${Keycap} k="Enter"/>${enter}</span>`}
      ${detailsOpen && html`<span class="key" title="Esc" onClick=${onDetails}><${Keycap} k="○"/>Back</span>`}
      <span class="key" title="D" onClick=${onDetails}><${Keycap} k="D"/>${detailsOpen ? 'Hide details' : 'Details'}</span>
    </span>
  </footer>`;
}

// everything the program said (the log), over the bottom of the window
export function Details({ open, onClose }) {
  const lines = useLog();
  const box = useRef(null);
  const follow = useRef(true);
  useEffect(() => {
    const el = box.current;
    if (el && open && follow.current) el.scrollTop = el.scrollHeight;
  }, [lines, open]);
  return html`<div class=${cls('details', open && 'open')} aria-hidden=${!open}>
    <div class="d-head">Details<span class="sp"></span>
      <${Button} small onClick=${() => call('open_error_log')}>Error log<//>
      <${Button} small onClick=${onClose}>Close<//></div>
    <pre ref=${box} onScroll=${(e) => { const el = e.target; follow.current = el.scrollTop + el.clientHeight >= el.scrollHeight - 8; }}
      >${lines.join('\n')}</pre>
  </div>`;
}

// a question from Python (Delete, unsaved edits, Go over edits...): {id, title, lines, buttons: [{label, answer, style}]}
// style: primary (the white pick) | danger | plain (also what Escape answers)
export function Question({ dialog, onAnswer }) {
  if (!dialog) return null;
  const cancel = dialog.buttons.find((b) => b.style === 'plain') || (dialog.buttons.length === 1 ? dialog.buttons[0] : null);
  const kinds = { primary: 'pick', danger: 'danger', plain: 'ghost' };
  return html`<${Modal} title=${dialog.title} tone=${dialog.tone} onClose=${cancel ? () => onAnswer(dialog.id, cancel.answer) : null}
    buttons=${dialog.buttons.map((b, k) => html`<${Button} key=${k} kind=${kinds[b.style] || 'ghost'} big
      onClick=${() => onAnswer(dialog.id, b.answer)}>${b.label}<//>`)}>
    ${dialog.lines.map((line, k) => html`<p key=${k}>${line}</p>`)}
  <//>`;
}
