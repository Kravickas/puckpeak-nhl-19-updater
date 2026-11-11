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

// the Puck Peak logo, the tagline with the site, and the title line as the game's breadcrumb
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

export function Header({ meta, play }) {
  const [name, game, version] = meta.title || [meta.app_name, '', meta.version];
  return html`<header class="header">
    <${PlayButton} play=${play}/>
    <img class="logo" src="img/logo.png" alt="Puck Peak" draggable="false" onClick=${() => call('open_site')}/>
    <div class="tagline">${meta.tagline} · <a onClick=${() => call('open_site')}>${meta.site_label}</a></div>
    <div class="crumb"><b>${name}<i class="dashes"></i></b><span class="sep">|</span><span class="light">${game}</span>
      <span class="sep">|</span><span class="ver">version ${version}</span></div>
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

// progress, the status (its own slice, pushed first: it never waits for the others), the keys.
// status: {text, tone, busy, progress: 0..1 | < 0 (running, no end known) | null}; tip: shown when the status is empty
export function HelpBar({ status, tip, enter, detailsOpen, onDetails, onEnter }) {
  const s = status || {};
  const p = s.progress;
  const has = p != null;
  const indeterminate = has && p < 0;
  const value = has && !indeterminate ? p : 0;
  const text = s.text || tip || '';
  return html`<footer class="helpbar">
    <${ProgressBar} value=${value} active=${!!s.busy && !indeterminate} indeterminate=${indeterminate}/>
    <span class="pct">${has && !indeterminate ? Math.round(value * 100) + '%' : ''}</span>
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
