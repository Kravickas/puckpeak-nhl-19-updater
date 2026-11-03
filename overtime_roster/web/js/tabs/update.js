// Update: Legacy's Update tab in NHL 19's look. The From bar (the open roster), "What should be updated?" (the
// switches), the result of the last Go or Check first, and the Save card with Go. One Go checks NHL.com, plans,
// changes the roster, checks it, backs up, saves and writes the list of changes; the steps show in the Save card and
// the Help bar. Slices `update`, `update_list`; calls in docs/ui/update.md.
import { html, cls } from '../lib.js';
import { useSlice } from '../store.js';
import { call } from '../bridge.js';
import { Card, Button, Switch, Segmented, Select, TextField, Field, Info, Tag, Modal, Why } from '../ui.js';

export const tip = 'Pick what to update and how to save it, then press Go.';

const GO_INFO = [
  { head: 'One Go does it all', items: [
    'Checks NHL.com for today\'s rosters (or reads the offline copy).',
    'Plans the changes and makes them in the open roster.',
    'Checks that the roster opens in NHL 19.',
    'Backs up the save it writes over, then saves.',
    'Writes a list of every change.',
  ] },
  { head: 'Not sure?', items: ['Press Check first: it shows what would change and saves nothing.'] },
];

function FromBar({ f, go }) {
  return html`<div class="card up-from">
    <span class="caps up-from-label">From</span>
    <span class="up-from-name">${f.name}</span>
    ${f.tag && html`<${Tag} tone=${f.tag.tone || null}>${f.tag.text}<//>`}
    ${f.date && html`<span class="up-from-date">Saved ${f.date}</span>`}
    ${f.note && html`<span class="up-from-note">${f.note}</span>`}
    <span class="sp"></span>
    <${Button} small onClick=${() => go('setup')}>Change it in Setup<//>
  </div>`;
}

// the game patch is missing, broken or from an older Overtime: say so over the switches, with the way to Game patch
function PatchBar({ p, go }) {
  return html`<div class=${cls('card up-patch', p.tone)} role="status">
    <span class="up-patch-text">${p.text}</span>
    <span class="sp"></span>
    <${Button} small kind="primary" onClick=${() => go('patch')}>Go to Game patch<//>
  </div>`;
}

// one row of "What should be updated?": title, one line, its options, the "?", the switch
function Step({ w, busy, children }) {
  return html`<div class=${cls('up-step', w.on && 'on', w.locked && 'locked')} data-key=${w.key}>
    <div class="up-step-main">
      <div class="up-step-title">${w.title}${w.always && html`<span class="up-always">Always on</span>`}</div>
      <div class="up-step-sub">${w.sub}</div>
      ${children}
    </div>
    <${Info} title=${w.info.title} text=${w.info.text}/>
    <${Switch} on=${w.on} disabled=${busy || w.locked} label=${w.title} onChange=${(on) => call('update_option', w.key, on)}/>
  </div>`;
}

// two columns: what comes from NHL.com and NHL 27, then My edits, on the left; the calendar, retirements and the
// data source on the right
function StepsCard({ s }) {
  const by = Object.fromEntries(s.switches.map((w) => [w.key, w]));
  const cal = by.calendar;
  return html`<${Card} n="1" title="What should be updated?" grow className="up-steps-card"
      aside=${html`<span class="up-aside">Turn a part off to keep it as it is.</span><${Info} title="What Go does" sections=${GO_INFO}/>`}>
    <div class="card-body up-steps-body">
      <div class="up-steps">
        <${Step} w=${by.rosters} busy=${s.busy}/>
        <${Step} w=${by.nhl27} busy=${s.busy}/>
        <${Step} w=${by.drafts} busy=${s.busy}/>
        <${Step} w=${by.myedits} busy=${s.busy}/>
        <${Step} w=${cal} busy=${s.busy}>
          <div class="up-opts">
            <${Segmented} className="up-season" options=${s.seasons} value=${s.season} disabled=${s.busy || !cal.on}
              onChange=${(v) => call('update_option', 'season', v)}/>
            <${Segmented} className="up-per32" value=${s.per32} disabled=${s.busy || !cal.on}
              options=${[{ value: 84, label: '84 games', title: 'The real NHL since 2025-26' }, { value: 82, label: '82 games', title: 'The length NHL 19 was made for' }]}
              onChange=${(v) => call('update_option', 'per32', v)}/>
          </div>
        <//>
        <${Step} w=${by.retire} busy=${s.busy}/>
        <div class="up-step on data" data-key="data">
          <div class="up-step-main">
            <div class="up-step-title">Data</div>
            <div class="up-step-sub">Where the rosters and the calendar come from.</div>
            <div class="up-opts">
              <${Segmented} className="up-data" value=${s.offline} disabled=${s.busy}
                options=${[{ value: false, label: 'NHL.com' }, { value: true, label: s.offline_date ? `Offline copy (${s.offline_date})` : 'Offline copy' }]}
                onChange=${(v) => call('update_option', 'offline', v)}/>
            </div>
          </div>
          <${Info} title="Data" text="NHL.com has today's rosters. The offline copy comes with Overtime Roster: use it when NHL.com does not answer."/>
        </div>
      </div>
    </div>
  <//>`;
}

function Result({ r }) {
  const buttons = [];
  if (r.kind !== 'bad' || r.can_undo) buttons.push(html`<${Button} small key="list" className="up-list-btn" onClick=${() => call('update_list', true)}>List of changes<//>`);
  if (r.can_offline) buttons.push(html`<${Button} small key="off" onClick=${() => call('update_option', 'offline', true)}>Use the offline copy<//>`);
  if (r.kind === 'bad' || r.log) buttons.push(html`<${Button} small key="log" onClick=${() => call('open_error_log')}>Open the error log<//>`);
  if (r.can_undo) buttons.push(html`<${Button} small key="undo" title="Take the whole update back" onClick=${() => call('update_result', 'undo')}>Undo the update<//>`);
  if (r.folder) buttons.push(html`<${Button} small key="dir" onClick=${() => call('open_path', r.folder)}>Open folder<//>`);
  if (r.can_play) buttons.push(html`<${Button} small kind="primary" key="play" onClick=${() => call('setup_play')}>Play<//>`);
  return html`<section class=${cls('card up-result', r.kind)} role="status">
    <div class="up-r-head">
      <span class="up-r-title caps">${r.title}</span>
      ${r.issues.length > 0 && html`<${Tag} tone="caution">${r.issues.length} to know<//>`}
      <span class="sp"></span>
      <div class="up-r-buttons">${buttons}</div>
      <button type="button" class="up-close" aria-label="Close" title="Close" onClick=${() => call('update_result', 'close')}>✕</button>
    </div>
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

// Go's steps: faint before a run, lit while it runs (the Help bar says the same), red where it stopped
function RunStrip({ run, idle }) {
  return html`<ol class=${cls('up-run', idle && 'idle')}>
    ${run.steps.map((st, i) => html`<li key=${st.key}
        class=${cls(!idle && i < run.at && 'done', !idle && i === run.at && (run.failed ? 'fail' : 'now'))}>
      <span class="up-run-n">${i + 1}</span><span class="up-run-label">${st.label}</span>
    </li>`)}
  </ol>`;
}

const IDLE_RUN = { at: -1, steps: [['check', 'NHL.com'], ['plan', 'Plan'], ['apply', 'Change'], ['verify', 'Check'],
  ['backup', 'Back up'], ['save', 'Save'], ['report', 'Report']].map(([key, label]) => ({ key, label })) };

function SaveCard({ s }) {
  const sv = s.save;
  const busy = s.busy;
  return html`<${Card} n="2" title="Save" featured className="up-save" aside=${sv.mode === 'online' ? null : html`<span>${sv.used} of ${sv.max} saves used</span>`}>
    <div class="card-body up-save-body">
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
        <div class="up-go-wrap">
          <${Button} className="up-check" disabled=${!s.check.enabled} onClick=${() => call('update_check')}
            title="Shows what would change. Nothing is saved.">Check first<//>
          <${Button} kind="featured" big className="up-go" disabled=${!s.go.enabled} title=${sv.block || 'Update and save (Enter)'}
            onClick=${() => call('update_go')}>${s.go.text}<//>
        </div>
      </div>
      <div class="up-save-foot">
        <${RunStrip} run=${s.run || IDLE_RUN} idle=${!s.run}/>
        <span class=${cls('small-note up-note', (sv.why || sv.note.tone === 'caution') && 'caution')}>
          ${sv.why ? `${sv.why} ` : ''}${sv.note.text}
        </span>
      </div>
    </div>
  <//>`;
}

export default function Update({ go }) {
  const s = useSlice('update');
  if (!s) return null;
  if (!s.ready) {
    return html`<div class="up">
      <${Why} className="up-none" text="Pick the roster to update first. Setup also shows the program where shadPS4 is.">
        <${Button} kind="primary" onClick=${() => go('setup')}>Go to Setup<//>
      <//>
    </div>`;
  }
  return html`<div class=${cls('up', s.result && 'has-result')}>
    <${FromBar} f=${s.from} go=${go}/>
    ${s.patch && html`<${PatchBar} p=${s.patch} go=${go}/>`}
    ${s.active && html`<div class="card up-patch bad" role="status"><span class="up-patch-text">${s.active.text}</span></div>`}
    <${StepsCard} s=${s}/>
    ${s.result && html`<${Result} r=${s.result}/>`}
    <${SaveCard} s=${s}/>
  </div>`;
}

// the list of changes (from the result's button): who moves, who is new, who leaves
export function Modals() {
  const l = useSlice('update_list');
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
