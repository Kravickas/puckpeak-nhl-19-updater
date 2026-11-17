// The roster update's parts, drawn in the Patch tab's Roster update group (0.97.0: Update and Game patch are one
// Patch tab; this file is no tab of its own). The From line (the open roster), the switches, the season and data
// choices, where it saves, the result of the last run and its steps. One press of Patch runs the update first: it
// checks NHL.com, plans, changes the roster, checks it, backs up, saves and writes the list of changes. Slices
// `update`, `update_list`; calls in docs/ui/patch.md.
import { html, cls } from '../lib.js';
import { call } from '../bridge.js';
import { Button, Switch, Segmented, Select, TextField, Field, Info, Tag, Modal } from '../ui.js';

export const GO_INFO = [
  { head: 'The roster update', items: [
    'Checks NHL.com for today\'s rosters (or reads the offline copy).',
    'Plans the changes and makes them in the open roster.',
    'Checks that the roster opens in NHL 19.',
    'Backs up the save it writes over, then saves.',
    'Writes a list of every change.',
    'Then the patch goes in.',
  ] },
  { head: 'Not sure?', items: ['Press Check first: it shows what would change and saves nothing.'] },
];

export function FromLine({ f, go }) {
  return html`<div class="up-from">
    <span class="caps up-from-label">From</span>
    <span class="up-from-name">${f.name}</span>
    ${f.tag && html`<${Tag} tone=${f.tag.tone || null}>${f.tag.text}<//>`}
    ${f.date && html`<span class="up-from-date">Saved ${f.date}</span>`}
    ${f.note && html`<span class="up-from-note">${f.note}</span>`}
    <span class="sp"></span>
    <${Button} small onClick=${() => go('setup')}>Change it in Setup<//>
  </div>`;
}

// the game patch is missing or broken, the cap switch changed, or the roster is not the active one: one line
export function Notice({ p, tone }) {
  return html`<div class=${cls('up-patch', tone || p.tone)} role="status"><span class="up-patch-text">${p.text}</span></div>`;
}

// one switch tile: title, two lines at most (all of it in the "?"), the switch
export function Step({ w, busy }) {
  return html`<div class=${cls('up-step', w.on && 'on', w.locked && 'locked')} data-key=${w.key}>
    <div class="up-step-main">
      <div class="up-step-title">${w.title}${w.always && html`<span class="up-always">Always on</span>`}</div>
      <div class="up-step-sub" title=${w.sub}>${w.sub}</div>
    </div>
    <${Info} title=${w.info.title} text=${w.info.text}/>
    <${Switch} on=${w.on} disabled=${busy || w.locked} label=${w.title} onChange=${(on) => call('update_option', w.key, on)}/>
  </div>`;
}

// the tiles' order: the rosters and what rides on them, the ratings, then the season
const ORDER = ['rosters', 'lines', 'myedits', 'retire', 'nhl27', 'drafts', 'calendar'];

export function Steps({ s }) {
  const by = Object.fromEntries(s.switches.map((w) => [w.key, w]));
  const keys = ORDER.filter((k) => by[k]).concat(s.switches.map((w) => w.key).filter((k) => !ORDER.includes(k)));
  return html`<div class="up-steps">${keys.map((k) => html`<${Step} key=${k} w=${by[k]} busy=${s.busy}/>`)}</div>`;
}

// the calendar's season and length, where the data comes from
export function Choices({ s }) {
  const cal = s.switches.find((w) => w.key === 'calendar') || { on: false };
  return html`<div class="up-bar">
    <div class=${cls('up-opt', !cal.on && 'off')}>
      <span class="caps up-opt-label">Season</span>
      <${Segmented} className="up-season" options=${s.seasons} value=${s.season} disabled=${s.busy || !cal.on}
        onChange=${(v) => call('update_option', 'season', v)}/>
      <${Segmented} className="up-per32" value=${s.per32} disabled=${s.busy || !cal.on}
        options=${[{ value: 84, label: '84 games', title: 'The real NHL since 2025-26' }, { value: 82, label: '82 games', title: 'The length NHL 19 was made for' }]}
        onChange=${(v) => call('update_option', 'per32', v)}/>
    </div>
    <span class="sp"></span>
    <div class="up-opt">
      <span class="caps up-opt-label">Data</span>
      <${Segmented} className="up-data" value=${s.offline} disabled=${s.busy}
        options=${[{ value: false, label: 'NHL.com' }, { value: true, label: s.offline_date ? `Offline copy (${s.offline_date})` : 'Offline copy' }]}
        onChange=${(v) => call('update_option', 'offline', v)}/>
      <${Info} title="Data" text="NHL.com has today's rosters. The offline copy comes with Overtime Roster: use it when NHL.com does not answer."/>
    </div>
  </div>`;
}

// where the update saves (Save to, its name or slot), Check first, and the note under them
export function SaveFields({ s }) {
  const sv = s.save;
  const busy = s.busy;
  return html`<div class="up-save">
    <div class="up-save-row">
      <${Field} label="Save to" className="up-mode-field">
        <${Segmented} className="up-modes" options=${sv.modes} value=${sv.mode} disabled=${busy}
          onChange=${(v) => call('update_save_mode', v)}/>
      <//>
      ${sv.mode === 'update' && html`<${Field} label="Roster" className="up-name-field"><div class="field up-target" title=${sv.target}>${sv.target}</div><//>`}
      ${(sv.mode === 'new' || sv.mode === 'folder') && html`<${Field} label="Name" className="up-name-field">
        <${TextField} value=${sv.name} placeholder=${sv.name_default} disabled=${busy} onChange=${(t) => call('update_name', t)}/>
      <//>`}
      ${sv.mode === 'folder' && html`<${Field} label="Slot on the other PC" className="up-slot-field">
        <${Select} value=${sv.folder_slot || ''} disabled=${busy} onChange=${(v) => call('update_folder_slot', v)}
          options=${[{ value: '', label: 'Automatic' }].concat(sv.folder_slots)}/>
      <//>`}
      ${sv.mode === 'online' && html`<${Field} label="File" className="up-name-field"><div class="field up-target">roster_h2h.db</div><//>`}
      ${sv.slots && html`<${Field} label="Write over" className="up-slot-field">
        <${Select} value=${sv.slot || ''} disabled=${busy} onChange=${(v) => v && call('update_slot', v)}
          options=${[{ value: '', label: 'Pick a save...' }].concat(sv.slots)}/>
      <//>`}
      <span class="sp"></span>
      ${sv.mode !== 'online' && html`<span class="up-used small-note">${sv.used} of ${sv.max} saves used</span>`}
      <${Button} small className="up-check" disabled=${!s.check.enabled} onClick=${() => call('update_check')}
        title="Shows what would change. Nothing is saved.">Check first<//>
    </div>
    <span class=${cls('small-note up-note', (sv.why || sv.note.tone === 'caution') && 'caution')}>
      ${sv.why ? `${sv.why} ` : ''}${sv.note.text}
    </span>
  </div>`;
}

export function Result({ r }) {
  const buttons = [];
  if (r.kind !== 'bad' || r.can_undo) buttons.push(html`<${Button} small key="list" className="up-list-btn" onClick=${() => call('update_list', true)}>List of changes<//>`);
  if (r.can_offline) buttons.push(html`<${Button} small key="off" onClick=${() => call('update_option', 'offline', true)}>Use the offline copy<//>`);
  if (r.kind === 'bad' || r.log) buttons.push(html`<${Button} small key="log" onClick=${() => call('open_error_log')}>Open the error log<//>`);
  if (r.can_undo) buttons.push(html`<${Button} small key="undo" title="Take the whole update back" onClick=${() => call('update_result', 'undo')}>Undo the update<//>`);
  if (r.folder) buttons.push(html`<${Button} small key="dir" onClick=${() => call('open_path', r.folder)}>Open folder<//>`);
  return html`<section class=${cls('card up-result', r.kind)} role="status">
    <div class="up-r-head">
      <span class="up-r-title caps">${r.title}</span>
      ${r.issues.length > 0 && html`<${Tag} tone="caution">${r.issues.length} to know<//>`}
      <span class="sp"></span>
      <button type="button" class="up-close" aria-label="Close" title="Close" onClick=${() => call('update_result', 'close')}>✕</button>
    </div>
    <div class="up-r-buttons">${buttons}</div>
    <div class="up-r-body">
      <ul class="up-r-lines">
        ${r.lines.map((l, k) => html`<li key=${`${l.part}${k}`} class=${l.tone === 'bad' ? 'bad' : undefined}><b>${l.part}</b><span>${l.text}</span></li>`)}
        ${r.issues.map((t, k) => html`<li key=${`i${k}`} class="issue"><b>To know</b><span>${t}</span></li>`)}
      </ul>
      ${r.items.length > 0 && html`<dl class="up-r-items">
        ${r.items.map(([k, v]) => html`<div key=${k}><dt>${k}</dt><dd title=${v}>${v}</dd></div>`)}
      </dl>`}
    </div>
  </section>`;
}

// the update's steps: faint before a run, lit while it runs (the Help bar says the same), red where it stopped
export function RunStrip({ run, idle }) {
  return html`<ol class=${cls('up-run', idle && 'idle')}>
    ${run.steps.map((st, i) => html`<li key=${st.key}
        class=${cls(!idle && i < run.at && 'done', !idle && i === run.at && (run.failed ? 'fail' : 'now'))}>
      <span class="up-run-n">${i + 1}</span><span class="up-run-label">${st.label}</span>
    </li>`)}
  </ol>`;
}

export const IDLE_RUN = { at: -1, steps: [['check', 'NHL.com'], ['plan', 'Plan'], ['apply', 'Change'], ['verify', 'Check'],
  ['backup', 'Back up'], ['save', 'Save'], ['report', 'Report']].map(([key, label]) => ({ key, label })) };

// the list of changes (from the result's button): who moves, who is new, who leaves
export function ChangesModal({ l }) {
  if (!l || !l.open) return null;
  const close = () => call('update_list', false);
  const part = (title, rows, line) => html`<section class="up-l-part">
    <div class="up-l-head caps">${title}<span class="up-l-count">${rows.length}</span></div>
    <ul class="up-l-rows">${rows.map((r, k) => html`<li key=${k}>${line(r)}</li>`)}</ul>
  </section>`;
  return html`<${Modal} wide title=${l.title} className="up-changes" onClose=${close}
      buttons=${[l.report && html`<${Button} big key="full" onClick=${() => call('open_path', l.report)}
          title="Every change, in your browser">Open the full list<//>`,
        html`<${Button} kind="pick" big key="close" onClick=${close}>Close<//>`]}>
    <p class="up-l-sum">${l.summary.moves} players move, ${l.summary.new} are new and ${l.summary.releases} leave. ${l.summary.teams} teams change.</p>
    <div class="up-list">
      ${part('Moves', l.moves, (m) => html`<span class="up-l-name">${m.name}</span><span class="up-l-pos">${m.pos}</span>
        <span class="up-l-way">${m.from} → <b>${m.to}</b></span>`)}
      ${part('New', l.new, (m) => html`<span class="up-l-name">${m.name}</span><span class="up-l-pos">${m.pos}</span>
        <span class="up-l-way">→ <b>${m.to}</b></span>`)}
      ${part('Leaving', l.releases, (m) => html`<span class="up-l-name">${m.name}</span><span class="up-l-pos">${m.pos}</span>
        <span class="up-l-way">${m.from} →  FA</span>`)}
    </div>
  <//>`;
}
