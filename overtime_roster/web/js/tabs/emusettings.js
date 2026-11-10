// Game settings, Controllers and Keyboard (Setup > Boost performance): shadPS4's per-game settings and its input
// bindings for NHL 19. The Python side (emusettings.py, emuinput.py) reads and checks everything; these views only
// show it and send what changed.
import { html, cls, useState, useEffect, useRef } from '../lib.js';
import { call } from '../bridge.js';
import { Button, Checkbox, Modal, Select } from '../ui.js';

// --- icons (Overtime's own) ----------------------------------------------------------------------------------------
export const GEAR_ICON = html`<svg class="emu-ico" viewBox="0 0 20 20" aria-hidden="true"><path fill="none"
  stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" d="M8.6 2.5h2.8l.5 2.2 1.6.9 2.1-.8 1.4 2.4-1.7
  1.5v1.8l1.7 1.5-1.4 2.4-2.1-.8-1.6.9-.5 2.2H8.6l-.5-2.2-1.6-.9-2.1.8L3 12l1.7-1.5V8.7L3 7.2l1.4-2.4 2.1.8 1.6-.9z"/>
  <circle cx="10" cy="10" r="2.4" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>`;
export const PAD_ICON = html`<svg class="emu-ico" viewBox="0 0 24 20" aria-hidden="true"><path fill="none"
  stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" d="M7 4h10c2.6 0 4.4 1.9 5 5l.8 4.6c.4 2.4-2.3
  3.8-4 2L16 13.4H8L5.2 15.6c-1.7 1.8-4.4.4-4-2L2 9c.6-3.1 2.4-5 5-5z"/><path stroke="currentColor"
  stroke-width="1.6" stroke-linecap="round" d="M6.5 7.5v3M5 9h3"/><circle cx="16" cy="8" r="1" fill="currentColor"/>
  <circle cx="18" cy="10.2" r="1" fill="currentColor"/></svg>`;
export const KEYS_ICON = html`<svg class="emu-ico" viewBox="0 0 24 20" aria-hidden="true"><rect x="1.8" y="4" width="20.4"
  height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.6"/><path stroke="currentColor"
  stroke-width="1.6" stroke-linecap="round" d="M5.5 8h1M9.5 8h1M13.5 8h1M17.5 8h1M5.5 11h1M17.5 11h1M8.5 13h7"/>
  <path stroke="currentColor" stroke-width="1.6" stroke-linecap="round" d="M9.5 11h5"/></svg>`;

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const copy = (v) => JSON.parse(JSON.stringify(v));

function Note({ msg }) {
  if (!msg) return null;
  return html`<span class=${cls('emu-msg', msg.tone)} role=${msg.tone === 'bad' ? 'alert' : 'status'}>${msg.text}</span>`;
}

// --- Game settings ---------------------------------------------------------------------------------------------------
function shown(f, vals) {
  return !f.show_if || Object.entries(f.show_if).every(([id, v]) => vals[id] === v);
}

function Control({ f, value, onChange, onFocus }) {
  const off = !!f.lock;
  const scale = f.scale || 1;
  if (f.kind === 'check') {
    return html`<${Checkbox} on=${!!value} disabled=${off} onChange=${onChange}>${f.label}<//>`;
  }
  if (f.kind === 'select' || f.kind === 'device' || f.kind === 'gpu') {
    return html`<${Select} className="emu-select" value=${value} options=${f.options} disabled=${off}
      onChange=${onChange}/>`;
  }
  if (f.kind === 'slider') {
    const digits = f.digits || 0;
    return html`<span class="emu-slider">
      <input type="range" min=${f.min / scale} max=${f.max / scale} step=${digits ? 1 / 10 ** digits : 1}
        value=${value / scale} disabled=${off} onFocus=${onFocus} aria-label=${f.label}
        onInput=${(e) => onChange(Math.round(Number(e.target.value) * scale))}/>
      <b>${(value / scale).toFixed(digits)}${f.unit ? ` ${f.unit}` : ''}</b></span>`;
  }
  if (f.kind === 'number') {
    const digits = f.digits == null ? (f.real ? 1 : 0) : f.digits;
    return html`<input class="field emu-num" type="number" min=${f.min / scale} max=${f.max / scale}
      step=${f.step || (digits ? 1 / 10 ** digits : 1)} value=${f.real ? value : Math.round(value / scale * 10 ** digits) / 10 ** digits}
      disabled=${off} onFocus=${onFocus} aria-label=${f.label}
      onChange=${(e) => { const n = Number(e.target.value); if (e.target.value !== '' && !Number.isNaN(n)) onChange(f.real ? n : Math.round(n * scale)); }}/>`;
  }
  return html`<input class="field emu-text" value=${value} disabled=${off} spellcheck="false" onFocus=${onFocus}
    aria-label=${f.label} onInput=${(e) => onChange(e.target.value)}/>`;
}

export function GameSettings({ onClose }) {
  const [data, setData] = useState(null);
  const [vals, setVals] = useState({});
  const [tab, setTab] = useState('General');
  const [tip, setTip] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const take = (d) => {
    if (!d || d.error) { setMsg({ text: (d && d.error) || 'The settings could not be read.', tone: 'bad' }); return; }
    setData(d);
    setVals(Object.fromEntries(d.fields.map((f) => [f.id, f.value])));
  };
  useEffect(() => { call('setup_emu_settings').then(take); }, []);
  const fields = data ? data.fields : [];
  const changed = Object.fromEntries(fields.filter((f) => !f.lock && !same(vals[f.id], f.value)).map((f) => [f.id, vals[f.id]]));
  const dirty = Object.keys(changed).length > 0;
  const apply = async (close) => {
    if (!dirty) { if (close) onClose(); return; }
    setBusy(true);
    const r = await call('setup_emu_settings_save', changed);
    setBusy(false);
    if (!r || r.error) { setMsg({ text: (r && r.error) || 'Not saved.', tone: 'bad' }); return; }
    if (close) { onClose(); return; }
    take(r);
    setMsg({ text: 'Saved. NHL 19 uses them from its next start.', tone: 'good' });
  };
  const restore = () => {
    setVals(Object.fromEntries(fields.map((f) => [f.id, f.lock ? vals[f.id] : f.default])));
    setMsg({ text: 'Defaults filled in: Save or Apply to keep them.', tone: '' });
  };
  const set = (id, v) => { setVals({ ...vals, [id]: v }); setMsg(null); };
  const tipField = tip && fields.find((f) => f.id === tip);
  const warnings = fields.filter((f) => f.warn && f.warn[vals[f.id]]).map((f) => f.warn[vals[f.id]]);
  const groups = [];
  for (const f of fields.filter((x) => x.tab === tab && shown(x, vals))) {
    let g = groups.find((x) => x.name === f.group);
    if (!g) groups.push(g = { name: f.group, fields: [] });
    g.fields.push(f);
  }
  const tabFields = fields.filter((f) => f.tab === tab);
  const locked = tabFields.length > 0 && tabFields.every((f) => f.lock);
  return html`<${Modal} title="Game settings" wide className="emu-modal emu-game" onClose=${onClose}
    foot=${html`<${Button} kind="ghost" className="emu-left" disabled=${!data || busy} onClick=${restore}>Restore defaults<//>
      <${Note} msg=${msg}/>
      <${Button} kind="ghost" onClick=${onClose}>Close<//>
      <${Button} kind="ghost" disabled=${!dirty || busy || !!(data && data.blocked)} onClick=${() => apply(false)}>Apply<//>
      <${Button} kind="primary" disabled=${busy || !!(data && data.blocked && dirty)} onClick=${() => apply(true)}>Save<//>`}>
    ${!data ? html`<p class="emu-wait">${msg ? '' : 'Reading the settings...'}</p>` : html`
      <div class="emu-tabs" role="tablist">
        ${data.tabs.map((t) => html`<button type="button" role="tab" aria-selected=${t === tab}
          class=${cls('emu-tab', t === tab && 'on')} onClick=${() => { setTab(t); setTip(null); }}>${t}</button>`)}
      </div>
      ${data.blocked && html`<div class="emu-banner">${data.blocked}</div>`}
      ${locked && html`<div class="emu-banner soft">${tabFields[0].lock}</div>`}
      <div class="emu-groups">
        ${groups.map((g) => html`<section class="emu-group">
          <h4>${g.name}</h4>
          ${g.fields.map((f) => html`<div class=${cls('emu-row', f.kind === 'check' && 'check', tip === f.id && 'tip')}
              onMouseEnter=${() => setTip(f.id)} onFocus=${() => setTip(f.id)}>
            ${f.kind !== 'check' && html`<label class="emu-label">${f.label}</label>`}
            <${Control} f=${f} value=${vals[f.id]} onChange=${(v) => set(f.id, v)} onFocus=${() => setTip(f.id)}/>
            <span class="emu-tags">
              ${f.lock && !locked && html`<span class="chip emu-lock" title=${f.lock}>Overtime</span>`}
            </span>
          </div>`)}
        </section>`)}
      </div>
      ${warnings.map((w) => html`<div class="emu-banner warn" key=${w}>${w}</div>`)}
      <div class="emu-help" aria-live="polite">
        ${tipField ? html`<b>${tipField.label}</b> ${tipField.help}${tipField.lock ? html` <i>${tipField.lock}</i>` : ''}`
          : 'Point at a setting to see what it does.'}
      </div>`}
  <//>`;
}

// --- Controllers -------------------------------------------------------------------------------------------------------
const hex = (rgb) => '#' + rgb.map((n) => n.toString(16).padStart(2, '0')).join('');
const rgbOf = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));

export function Controllers({ onClose }) {
  const [data, setData] = useState(null);
  const [m, setM] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const take = (d) => {
    if (!d || d.error) { setMsg({ text: (d && d.error) || 'The bindings could not be read.', tone: 'bad' }); return; }
    setData(d); setM(copy(d.model));
  };
  useEffect(() => { call('setup_emu_input', 'pad').then(take); }, []);
  const dirty = data && m && !same(m, data.model);
  const save = async (close) => {
    if (!dirty) { if (close) onClose(); return; }
    setBusy(true);
    const r = await call('setup_emu_input_save', 'pad', m);
    setBusy(false);
    if (!r || r.error) { setMsg({ text: (r && r.error) || 'Not saved.', tone: 'bad' }); return; }
    if (close) { onClose(); return; }
    take(r); setMsg({ text: 'Saved. In NHL 19, F8 reloads the bindings.', tone: 'good' });
  };
  const upd = (fn) => { const n = copy(m); fn(n); setM(n); setMsg(null); };
  const choices = data ? data.choices.map(([value, label]) => ({ value, label })) : [];
  const stickOpts = [{ value: 'left', label: 'Left stick' }, { value: 'right', label: 'Right stick' }];
  const zone = (side, i, label) => html`<label class="emu-zone">${label}
    <input type="range" min="1" max="127" value=${m.deadzone[side][i]} aria-label=${`${side} stick ${label}`}
      onInput=${(e) => upd((n) => { n.deadzone[side][i] = Number(e.target.value); })}/>
    <b>${m.deadzone[side][i]}</b></label>`;
  return html`<${Modal} title="Controllers" wide className="emu-modal" onClose=${onClose}
    foot=${html`<${Button} kind="ghost" className="emu-left" disabled=${!m || busy}
        onClick=${() => { setM(copy(data.defaults)); setMsg({ text: "shadPS4's defaults filled in: Save to keep them.", tone: '' }); }}>Restore defaults<//>
      <${Note} msg=${msg}/>
      <${Button} kind="ghost" onClick=${onClose}>Close<//>
      <${Button} kind="ghost" disabled=${!dirty || busy} onClick=${() => save(false)}>Apply<//>
      <${Button} kind="primary" disabled=${busy} onClick=${() => save(true)}>Save<//>`}>
    ${!m ? html`<p class="emu-wait">${msg ? '' : 'Reading the bindings...'}</p>` : html`
      <p class="emu-file">Any controller shadPS4 sees (DualShock 4, DualSense, Xbox). Each PS4 button takes the
        button you pick on your controller. File: <code>${data.path}</code></p>
      <div class="emu-cols">
        <section class="emu-group"><h4>Buttons</h4>
          <div class="emu-map">
            ${data.outputs.map(([o, label]) => html`<label class="emu-label">${label}</label>
              <${Select} className="emu-select" value=${m.buttons[o]} options=${choices}
                onChange=${(v) => upd((n) => { n.buttons[o] = v; })}/>`)}
          </div>
        </section>
        <div>
          <section class="emu-group"><h4>Sticks</h4>
            <div class="emu-map">
              <label class="emu-label">Left stick</label>
              <${Select} className="emu-select" value=${m.sticks.left} options=${stickOpts} onChange=${(v) => upd((n) => { n.sticks.left = v; })}/>
              <label class="emu-label">Right stick</label>
              <${Select} className="emu-select" value=${m.sticks.right} options=${stickOpts} onChange=${(v) => upd((n) => { n.sticks.right = v; })}/>
            </div>
          </section>
          <section class="emu-group"><h4>Deadzones</h4>
            <p class="emu-small">How far a stick moves before the game sees it (inner), and where it counts as all the
              way (outer). 1 to 127.</p>
            <div class="emu-zones"><span class="emu-label">Left stick</span>${zone('left', 0, 'Inner')}${zone('left', 1, 'Outer')}</div>
            <div class="emu-zones"><span class="emu-label">Right stick</span>${zone('right', 0, 'Inner')}${zone('right', 1, 'Outer')}</div>
          </section>
          <section class="emu-group"><h4>Lightbar</h4>
            <div class="emu-row check">
              <${Checkbox} on=${m.color.on} onChange=${(v) => upd((n) => { n.color.on = v; })}>Own lightbar colour<//>
              <input type="color" class="emu-color" value=${hex(m.color.rgb)} disabled=${!m.color.on} aria-label="Lightbar colour"
                onInput=${(e) => upd((n) => { n.color.rgb = rgbOf(e.target.value); })}/>
            </div>
          </section>
        </div>
      </div>`}
  <//>`;
}

// --- Keyboard ------------------------------------------------------------------------------------------------------------
const PUNCT = { '`': 'grave', '~': 'tilde', '!': 'exclamation', '@': 'at', '#': 'hash', $: 'dollar', '%': 'percent',
  '^': 'caret', '&': 'ampersand', '*': 'asterisk', '(': 'lparen', ')': 'rparen', '-': 'minus', _: 'underscore',
  '=': 'equals', '+': 'plus', '[': 'lbracket', ']': 'rbracket', '{': 'lbrace', '}': 'rbrace', '\\': 'backslash',
  '|': 'pipe', ';': 'semicolon', ':': 'colon', "'": 'apostrophe', '"': 'quote', ',': 'comma', '<': 'less',
  '.': 'period', '>': 'greater', '/': 'slash', '?': 'question' };
const PAD_KEYS = { NumpadDecimal: 'kpperiod', NumpadComma: 'kpcomma', NumpadDivide: 'kpslash', NumpadMultiply: 'kpasterisk',
  NumpadSubtract: 'kpminus', NumpadAdd: 'kpplus', NumpadEqual: 'kpequals', NumpadEnter: 'kpenter' };
const SIDES = { ShiftLeft: 'lshift', ShiftRight: 'rshift', ControlLeft: 'lctrl', ControlRight: 'rctrl', AltLeft: 'lalt',
  AltRight: 'ralt', MetaLeft: 'lwin', MetaRight: 'rwin' };
const MODS = { Shift: 'shift', Control: 'ctrl', Alt: 'alt', Meta: 'win' };
const NAMED = { Escape: 'escape', PrintScreen: 'printscreen', ScrollLock: 'scrolllock', Pause: 'pausebreak',
  Backspace: 'backspace', Delete: 'delete', Insert: 'insert', Home: 'home', End: 'end', PageUp: 'pgup',
  PageDown: 'pgdown', Tab: 'tab', CapsLock: 'capslock', Enter: 'enter', ' ': 'space', ArrowUp: 'up',
  ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right' };
const MOUSE_BUTTONS = ['leftbutton', 'middlebutton', 'rightbutton', 'sidebuttonback', 'sidebuttonforward'];

// shadPS4's name for a pressed key (it reads SDL keycodes: the character the layout gives, so e.key first)
export function keyName(e) {
  const c = e.code || '';
  if (/^Numpad\d$/.test(c)) return 'kp' + c.slice(6);
  if (PAD_KEYS[c]) return PAD_KEYS[c];
  if (SIDES[c]) return SIDES[c];
  if (MODS[e.key]) return (e.location === 2 ? 'r' : 'l') + MODS[e.key];
  if (NAMED[e.key]) return NAMED[e.key];
  if (/^F([1-9]|1[0-2])$/.test(e.key)) return e.key.toLowerCase();
  if (e.key && e.key.length === 1) {
    const k = e.key.toLowerCase();
    if (/^[a-z0-9]$/.test(k)) return k;
    if (PUNCT[k]) return PUNCT[k];
  }
  if (/^Key[A-Z]$/.test(c)) return c.slice(3).toLowerCase();
  if (/^Digit\d$/.test(c)) return c.slice(5);
  return null;
}

const PRETTY = { lshift: 'Left Shift', rshift: 'Right Shift', lctrl: 'Left Ctrl', rctrl: 'Right Ctrl', lalt: 'Left Alt',
  ralt: 'Right Alt', lwin: 'Left Win', rwin: 'Right Win', lmeta: 'Left Meta', rmeta: 'Right Meta', space: 'Space',
  enter: 'Enter', escape: 'Esc', backspace: 'Backspace', tab: 'Tab', up: '↑', down: '↓', left: '←', right: '→',
  pgup: 'Page Up', pgdown: 'Page Down', leftbutton: 'Left click', rightbutton: 'Right click',
  middlebutton: 'Middle click', sidebuttonback: 'Mouse back', sidebuttonforward: 'Mouse forward',
  mousewheelup: 'Wheel up', mousewheeldown: 'Wheel down', mousewheelleft: 'Wheel left', mousewheelright: 'Wheel right',
  capslock: 'Caps Lock', printscreen: 'Print Screen', scrolllock: 'Scroll Lock', pausebreak: 'Pause' };
const PUNCT_BACK = Object.fromEntries(Object.entries(PUNCT).map(([ch, n]) => [n, ch]));
export function pretty(combo) {
  return combo.split(',').map((t) => {
    if (PRETTY[t]) return PRETTY[t];
    if (/^kp\d$/.test(t)) return 'Num ' + t.slice(2);
    if (t.startsWith('kp')) return 'Num ' + ({ kpperiod: '.', kpcomma: ',', kpslash: '/', kpasterisk: '*', kpminus: '-',
      kpplus: '+', kpequals: '=', kpenter: 'Enter' }[t] || t.slice(2));
    if (PUNCT_BACK[t]) return PUNCT_BACK[t];
    return t.length === 1 || /^f\d+$/.test(t) ? t.toUpperCase() : t.charAt(0).toUpperCase() + t.slice(1);
  }).join(' + ');
}

export function Keyboard({ onClose }) {
  const [data, setData] = useState(null);
  const [m, setM] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [grab, setGrab] = useState(null);     // {o, i}: the slot waiting for a key
  const held = useRef([]);
  const doneAt = useRef(0);                   // the click (or menu) that ends a capture must not start or clear one
  const settled = () => Date.now() - doneAt.current > 400;
  const take = (d) => {
    if (!d || d.error) { setMsg({ text: (d && d.error) || 'The bindings could not be read.', tone: 'bad' }); return; }
    setData(d); setM(copy(d.model));
  };
  useEffect(() => { call('setup_emu_input', 'keys').then(take); }, []);
  const dirty = data && m && !same(m, data.model);
  const put = (o, i, combo) => {
    const n = copy(m);
    n.bindings[o] = n.bindings[o] || [];
    const list = n.bindings[o];
    if (combo) {
      for (const [other, combos] of Object.entries(n.bindings)) {   // one key, one job: taken from where it was
        const at = combos.indexOf(combo);
        if (at < 0 || (other === o && at === i)) continue;
        combos.splice(at, 1);
        if (other === o && at < i) i -= 1;
      }
      if (i < list.length) list[i] = combo; else list.push(combo);
    } else if (i < list.length) list.splice(i, 1);
    setM(n);
  };
  useEffect(() => {
    if (!grab) return undefined;
    held.current = [];
    let done = false;
    const finish = (combo) => {
      if (done) return;
      done = true;
      doneAt.current = Date.now();
      if (combo && grab.o.startsWith('axis_') && combo.split(',').some((t) => t.startsWith('mousewheel'))) {
        setMsg({ text: 'The mouse wheel cannot move a stick.', tone: 'bad' });
      } else if (combo) { put(grab.o, grab.i, combo); setMsg(null); }
      setGrab(null);
    };
    const down = (e) => {
      e.preventDefault(); e.stopPropagation();
      if (e.repeat) return;
      if (e.key === 'Escape' && !held.current.length) { finish(null); return; }
      const name = keyName(e);
      const add = (n) => { if (n && !held.current.includes(n) && held.current.length < 3) held.current.push(n); };
      for (const [on, mod] of [[e.ctrlKey, 'ctrl'], [e.shiftKey, 'shift'], [e.altKey, 'alt']]) {
        // a modifier held from before the capture (or sent without its own keydown) still counts
        if (on && !held.current.some((h) => h.slice(1) === mod) && (name || '').slice(1) !== mod) add('l' + mod);
      }
      add(name);
    };
    const up = (e) => {
      e.preventDefault(); e.stopPropagation();
      if (held.current.length) finish(held.current.join(','));
    };
    const mouse = (e) => {
      if (!e.target.closest || !e.target.closest('.emu-grab')) { finish(null); return; }   // a click elsewhere cancels
      e.preventDefault(); e.stopPropagation();
      const b = MOUSE_BUTTONS[e.button];
      if (b) finish([...held.current, b].slice(0, 3).join(','));
    };
    const wheel = (e) => {
      if (!e.target.closest || !e.target.closest('.emu-grab')) return;
      e.preventDefault();
      const w = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? (e.deltaX < 0 ? 'mousewheelleft' : 'mousewheelright')
        : (e.deltaY < 0 ? 'mousewheelup' : 'mousewheeldown');
      finish([...held.current, w].slice(0, 3).join(','));
    };
    const menu = (e) => { if (e.target.closest && e.target.closest('.emu-grab')) e.preventDefault(); };
    window.addEventListener('keydown', down, true);
    window.addEventListener('keyup', up, true);
    window.addEventListener('mousedown', mouse, true);
    window.addEventListener('wheel', wheel, { capture: true, passive: false });
    window.addEventListener('contextmenu', menu, true);
    return () => {
      window.removeEventListener('keydown', down, true);
      window.removeEventListener('keyup', up, true);
      window.removeEventListener('mousedown', mouse, true);
      window.removeEventListener('wheel', wheel, { capture: true });
      window.removeEventListener('contextmenu', menu, true);
    };
  }, [grab]);
  const save = async (close) => {
    if (!dirty) { if (close) onClose(); return; }
    setBusy(true);
    const r = await call('setup_emu_input_save', 'keys', m);
    setBusy(false);
    if (!r || r.error) { setMsg({ text: (r && r.error) || 'Not saved.', tone: 'bad' }); return; }
    if (close) { onClose(); return; }
    take(r); setMsg({ text: 'Saved. In NHL 19, F8 reloads the bindings.', tone: 'good' });
  };
  const close = () => (grab ? setGrab(null) : onClose());
  const slots = data ? data.slots : 3;
  const mouse = m && m.mouse;
  const params = data ? data.mouse_params : [];
  const paramLabels = { deadzone: 'Deadzone offset', speed: 'Speed', offset: 'Speed offset' };
  return html`<${Modal} title="Keyboard" wide className="emu-modal" onClose=${close}
    foot=${html`<${Button} kind="ghost" className="emu-left" disabled=${!m || busy || !!grab}
        onClick=${() => { const n = copy(data.defaults); n.bindings = { ...Object.fromEntries(data.outputs.map(([o]) => [o, []])), ...n.bindings };
          setM(n); setMsg({ text: "shadPS4's defaults filled in: Save to keep them.", tone: '' }); }}>Restore defaults<//>
      <${Note} msg=${msg}/>
      <${Button} kind="ghost" onClick=${close}>Close<//>
      <${Button} kind="ghost" disabled=${!dirty || busy || !!grab} onClick=${() => save(false)}>Apply<//>
      <${Button} kind="primary" disabled=${busy || !!grab} onClick=${() => save(true)}>Save<//>`}>
    ${!m ? html`<p class="emu-wait">${msg ? '' : 'Reading the bindings...'}</p>` : html`
      <p class="emu-file">Click a slot, then press a key, a combination (up to 3 keys) or a mouse button. Right-click a
        slot to clear it. Overtime presses the letter or digit on Cross to start online matches, so keep one there.
        File: <code>${data.path}</code></p>
      <div class="emu-cols">
        <section class="emu-group"><h4>Buttons and sticks</h4>
          <div class="emu-keys">
            ${data.outputs.map(([o, label]) => {
              const list = m.bindings[o] || [];
              return html`<div class="emu-krow" key=${o}><span class="emu-label">${label}</span><div class="emu-kslots">
                ${Array.from({ length: Math.max(slots, list.length) }, (_, i) => {
                  const on = grab && grab.o === o && grab.i === i;
                  const combo = list[i];
                  return html`<button type="button" class=${cls('emu-slot', combo && 'set', on && 'emu-grab')}
                    title=${combo ? `${pretty(combo)} (right-click clears)` : 'Click, then press a key'}
                    disabled=${!!grab && !on}
                    onClick=${() => { if (!grab && settled()) setGrab({ o, i }); }}
                    onContextMenu=${(e) => { e.preventDefault(); if (!grab && combo && settled()) { put(o, i, null); setMsg(null); } }}>
                    ${on ? 'Press a key...' : combo ? pretty(combo) : ''}</button>`;
                })}</div></div>`;
            })}
          </div>
        </section>
        <div>
          <section class="emu-group"><h4>Mouse as a stick</h4>
            <div class="emu-map">
              <label class="emu-label">Mouse moves</label>
              <${Select} className="emu-select" value=${mouse.stick}
                options=${[{ value: 'none', label: 'Nothing' }, { value: 'left', label: 'The left stick' }, { value: 'right', label: 'The right stick' }]}
                onChange=${(v) => { const n = copy(m); n.mouse.stick = v; setM(n); }}/>
              ${mouse.stick !== 'none' && params.map(([key, lo, hi], i) => html`<label class="emu-label">${paramLabels[key]}</label>
                <span class="emu-slider"><input type="range" min=${lo} max=${hi} step=${key === 'speed' ? 0.1 : 0.005}
                  value=${mouse.params[i]} aria-label=${paramLabels[key]}
                  onInput=${(e) => { const n = copy(m); n.mouse.params[i] = Number(e.target.value); setM(n); }}/>
                  <b>${Number(mouse.params[i]).toFixed(key === 'speed' ? 1 : 3)}</b></span>`)}
            </div>
            <p class="emu-small">F7 in the game switches it on and off.</p>
          </section>
          <section class="emu-group"><h4>Emulator keys</h4>
            <div class="emu-hotkeys">
              ${data.hotkeys.map(([label, combo]) => html`<span>${label}</span><kbd>${pretty(combo.replace(/ \+ /g, ','))}</kbd>`)}
            </div>
            <p class="emu-small">Set in shadPS4's global.ini.</p>
          </section>
        </div>
      </div>`}
  <//>`;
}
