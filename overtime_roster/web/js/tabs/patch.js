// Patch (0.97.0: the Update and Game patch tabs in one). Left: the patch (state, Patch / Unpatch / Play) and what one
// press puts in, in four groups, each with a switch of its own and a fold: Roster update (the update's switches, where
// it saves, Check first; js/tabs/update.js), Teams and league, Menus and server texts, Updated assets (an asset switch
// downloads its pack). One press of Patch runs the roster update first (when a roster is open and its group is on),
// then the patch. Right: the update's result when there is one, then what is in the game now (patched in, online:
// server, network switches, ShadNet; files; Check the game). Slices `patch`, `patch_files`, `patchall`, `update`,
// `update_list`; calls in docs/ui/patch.md.
import { html, cls, useState } from '../lib.js';
import { useSlice } from '../store.js';
import { call } from '../bridge.js';
import { Card, Button, Switch, Info, Tag, Modal, ProgressBar, Order } from '../ui.js';
import { GO_INFO, FromLine, Notice, Steps, Choices, SaveFields, Result, RunStrip, IDLE_RUN, ChangesModal } from './update.js';

export const tip = 'Press Patch: it updates the open roster, then patches the game. Unpatch puts every game file back.';

const TRASH = html`<svg viewBox="0 0 14 16" aria-hidden="true"><path fill="currentColor" d="M5 0h4l.6 1.5H13a1 1 0 0 1 0 2H1a1 1 0 0 1 0-2h3.4zM2 5h10l-.8 9.6A1.5 1.5 0 0 1 9.7 16H4.3a1.5 1.5 0 0 1-1.5-1.4zm3 2v7h1.4V7zm2.6 0v7H9V7z"/></svg>`;

// one switch in a group: a patch layer, or an asset with its download state (the state line when it says something,
// else what it is). Its tag (In the game / Patch to add) is a dot before the title, the words on hover; Delete is a bin.
function Row({ r, busy }) {
  const asset = r.kind === 'asset';
  const line = asset ? (r.quiet || !r.text ? r.sub : r.text) : (r.why || r.sub);
  const blocked = asset ? r.disabled && !busy && !r.on : r.disabled;
  return html`<div class=${cls('gp-layer', r.on && 'on', blocked && 'off')} data-key=${r.key}>
    <div class="gp-layer-main">
      <div class="gp-layer-title" title=${r.tag ? `${r.title}: ${r.tag.text}` : r.title}>
        ${r.tag && html`<span class=${cls('gp-dot', r.tag.tone)} role="img" aria-label=${r.tag.text}></span>`}<span>${r.title}</span></div>
      <div class=${cls('gp-layer-sub', r.tone)} title=${line}>${line}</div>
      ${r.progress != null && html`<${ProgressBar} value=${r.progress} active/>`}
    </div>
    ${r.can_update && html`<${Button} small onClick=${() => call('setup_pack_download', r.name)}>Update<//>`}
    ${r.can_remove && html`<button type="button" class="gp-bin" title="Delete it from this PC" aria-label=${`Delete ${r.title} from this PC`}
      onClick=${() => call('setup_pack_remove', r.name)}>${TRASH}</button>`}
    <${Info} title=${r.info.title} text=${r.why && !asset ? `${r.info.text} ${r.why}` : r.info.text}/>
    <${Switch} on=${r.on} disabled=${asset ? r.disabled : busy || r.disabled} label=${r.title}
      onChange=${(on) => call('patch_option', r.key, on)}/>
  </div>`;
}

const FOLDER = html`<svg class="gp-folder" viewBox="0 0 16 13" aria-hidden="true"><path fill="currentColor"
  d="M0 1.5A1.5 1.5 0 0 1 1.5 0h4l1.6 1.8h7.4A1.5 1.5 0 0 1 16 3.3v8.2a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 0 11.5z"/></svg>`;

// a group's head: its fold, what is on, its own switch; `extra` sits before the switch
function GroupHead({ title, count, sub, open, onOpen, sw, extra, icon }) {
  return html`<div class="gp-group-head">
    <button type="button" class="gp-group-fold" aria-expanded=${open ? 'true' : 'false'} onClick=${() => onOpen(!open)}
        title=${open ? 'Fold' : 'Show each switch'}>
      <span class="gp-chev" aria-hidden="true"></span>
      <span class="gp-group-text">
        <span class="gp-group-title">${icon}${title}${count && html`<span class="gp-group-count">${count}</span>`}</span>
        <span class="gp-group-sub" title=${sub}>${sub}</span>
      </span>
    </button>
    ${extra}
    ${sw}
  </div>`;
}

// a patch group (on: its main switches; off: all of them); open, its switches in two columns
function Group({ g, busy, open, onOpen }) {
  const mixed = !g.on && g.count > 0;
  const st = g.store;
  const extra = st && html`
    ${(st.size || st.total) && html`<span class="gp-store">${st.size ? `${st.size} on this PC` : 'None on this PC'}${st.total ? `, ${st.total} for all` : ''}</span>`}
    ${st.wait && html`<span class="gp-wait" title=${st.wait} aria-label=${st.wait} tabindex="0">!</span>`}
    ${st.can_remove && html`<${Button} small className="gp-store-drop" onClick=${() => call('setup_packs_drop')}
      title="Take every downloaded asset off this PC">Delete...<//>`}`;
  return html`<section class=${cls('gp-group', g.on && 'on', mixed && 'mixed', open && 'open')} data-key=${g.key}>
    <${GroupHead} title=${g.title} count=${`${g.count} of ${g.rows.length} on`} sub=${g.sub} open=${open} onOpen=${onOpen}
      icon=${g.key === 'assets' && FOLDER} extra=${extra}
      sw=${html`<${Switch} on=${g.on} disabled=${g.disabled} label=${g.title} onChange=${(on) => call('patch_group', g.key, on)}/>`}/>
    ${open && html`<div class="gp-group-rows">${g.rows.map((r) => html`<${Row} key=${r.key} r=${r} busy=${busy}/>`)}</div>`}
  </section>`;
}

// the Roster update group: its own switch (off: Patch patches only); open, the update's switches, its choices and where
// it saves
function RosterGroup({ u, pa, open, onOpen, go }) {
  const ready = u && u.ready;
  const on = ready ? u.switches.filter((w) => w.on).length : 0;
  const sub = !ready ? 'Open a roster in Setup: Patch then updates it with today\'s NHL rosters first.'
    : !pa.update_on ? `Off: Patch leaves ${u.from.name} as it is.`
    : pa.skips ? `${u.from.name} is updated already: the next press patches only.`
    : `${u.from.name} gets today's NHL rosters and is saved, then the patch goes in.`;
  return html`<section class=${cls('gp-group', 'gp-roster', ready && pa.update_on && 'on', open && 'open')} data-key="roster">
    <${GroupHead} title="Roster update" count=${ready && `${on} of ${u.switches.length} on`} sub=${sub} open=${open} onOpen=${onOpen}
      extra=${html`<${Info} title="The roster update" sections=${GO_INFO}/>`}
      sw=${html`<${Switch} on=${pa.update_on} disabled=${pa.phase != null} label="Roster update"
        onChange=${(v) => call('patch_update_on', v)}/>`}/>
    ${open && html`<div class="gp-roster-body">
      ${!ready ? html`<div class="up-none">
          <span>No roster is open.</span>
          <${Button} small kind="primary" onClick=${() => go('setup')}>Go to Setup<//>
        </div>`
        : html`
          <${FromLine} f=${u.from} go=${go}/>
          ${u.active && html`<${Notice} p=${u.active} tone="bad"/>`}
          ${u.patch && html`<${Notice} p=${u.patch}/>`}
          <${Steps} s=${u}/>
          <${Choices} s=${u}/>
          <${SaveFields} s=${u}/>`}
    </div>`}
  </section>`;
}

// Skip the first-run setup: only for a save folder with no profile yet (starter.py)
function StarterRow({ st, busy }) {
  return html`<div class=${cls('gp-layer', 'gp-starter', st.on && 'on')} data-key="starter">
    <div class="gp-layer-main">
      <div class="gp-layer-title"><span>Skip the first-run setup</span></div>
      <div class="gp-layer-sub">NHL 19 has no profile for player 1 yet: Patch writes a new one, so the game starts at the main menu.</div>
    </div>
    <${Info} title="Skip the first-run setup" text="Writes a new profile save (Profile0) for player 1 with the first-run setup marked done and the updated roster as the active one. It shows only while there is no profile, and never writes over one. Untested on a first boot yet: leave it off if you are not sure."/>
    <${Switch} on=${st.on} disabled=${busy} label="Skip the first-run setup" onChange=${(v) => call('patch_starter', v)}/>
  </div>`;
}

const FOLDS = 'overtime.patch.open';
function readFolds() {
  try { return JSON.parse(localStorage.getItem(FOLDS) || '{}') || {}; } catch (e) { return {}; }
}

// the one press: Patch runs the update's steps first (when it runs); a stopped update offers Patch without it
function OnePress({ u, pa }) {
  if (!pa || !(pa.phase === 'update' || pa.stopped)) return null;
  const run = u && u.run;
  return html`<div class=${cls('gp-run', pa.stopped && 'stopped')}>
    <span class="caps gp-run-label">Roster update</span>
    <${RunStrip} run=${run || IDLE_RUN} idle=${!run}/>
    ${pa.stopped && html`<span class="sp"></span><${Button} small kind="gold-line" className="gp-anyway"
      title="The update stopped (its result says why). This patches the game without it."
      onClick=${() => call('patch_anyway')}>Patch the game anyway<//>`}
  </div>`;
}

function PatchCard({ s, u, pa, busy, go }) {
  const b = s.buttons;
  const [open, setOpen] = useState(readFolds);
  const fold = (key, on) => {
    const next = on ? { [key]: true } : {};      // one group open at a time: the card needs no scroll
    setOpen(next);
    try { localStorage.setItem(FOLDS, JSON.stringify(next)); } catch (e) { /* a private window: not kept */ }
  };
  const btn = (pa && pa.button) || { enabled: b.patch.enabled, title: '' };
  return html`<${Card} n="1" title="Overtime game patch" grow featured className="gp-main"
      aside=${html`<${Tag} tone=${s.patched ? (s.state.tone === 'bad' ? 'bad' : 'good') : null}>${s.patched ? 'Patched' : 'Not patched'}<//>
        <${Button} small className="gp-refresh" disabled=${!b.refresh.enabled} onClick=${() => call('patch_refresh')}
          title="Looks at the game and shadPS4 again">Check again<//>`}>
    <div class="card-body gp-top">
      <div class=${cls('gp-state', s.state.tone)} role="status"><span class="gp-mark"></span><span>${s.state.text}</span></div>
      <${Order} here="patch" go=${go}/>
      <div class="gp-buttons">
        <${Button} kind="featured" big className="gp-patch" disabled=${!btn.enabled || busy} title=${btn.title}
          onClick=${() => call('patch_all')}>${b.patch.text}<//>
        <${Info} title="What the game patch does" sections=${patchInfo(s)} label="What the game patch does"/>
        <${Button} kind="gold-line" className="gp-unpatch" disabled=${!b.unpatch.enabled} onClick=${() => call('setup_unpatch')}>Unpatch<//>
        <span class="sp"></span>
        <${Button} className="gp-play" disabled=${!b.play.enabled} onClick=${() => call('setup_play')}>
          <svg class="gp-play-icon" viewBox="0 0 10 12" aria-hidden="true"><path d="M0 0 10 6 0 12z" fill="currentColor"/></svg>Play<//>
      </div>
      <${OnePress} u=${u} pa=${pa}/>
    </div>
    <div class="card-body gp-layers">
      <div class="gp-layers-head">
        <span class="field-label">What Patch puts in</span>
        <span class="small-note gp-hint">${s.hint}</span>
      </div>
      ${pa && html`<${RosterGroup} u=${u} pa=${pa} open=${!!open.roster} onOpen=${(on) => fold('roster', on)} go=${go}/>`}
      ${s.groups.map((g) => html`<${Group} key=${g.key} g=${g} busy=${s.busy} open=${!!open[g.key]}
        onOpen=${(on) => fold(g.key, on)}/>`)}
      ${pa && pa.starter.show && html`<${StarterRow} st=${pa.starter} busy=${busy}/>`}
      ${s.coming && html`<div class="gp-layer coming">
        <div class="gp-layer-main">
          <div class="gp-layer-title"><span>${s.coming.title}</span><${Tag} tone="info">Coming<//></div>
          <div class="gp-layer-sub">${s.coming.sub}</div>
        </div>
        <${Info} title=${s.coming.title} text=${s.coming.sub}/>
      </div>`}
    </div>
  <//>`;
}

// "What's in your game now": is it patched, can it play online (server, network switches, ShadNet), are the files
// right. No backup copy (owner 2026-11-07: the patch never changes the game's own files).
function NowCard({ s }) {
  const g = s.game;
  const o = g.online || {};
  const net = o.network === true ? ['good', 'Network switches on']
    : o.network === false ? ['caution', 'Network switches off: Play turns them on'] : ['idle', 'shadPS4 not set up'];
  const sn = o.shadnet ? ['good', `ShadNet: ${o.shadnet}`] : ['bad', 'No ShadNet sign-in: Multiplayer tab'];
  const bad = g.files.bad > 0 || g.problems.length > 0;
  return html`<${Card} n="2" title="What's in your game now" className="gp-now"
      aside=${g.problems.length ? html`<${Tag} tone="bad">${g.problems.length} ${g.problems.length === 1 ? 'problem' : 'problems'}<//>` : null}>
    <div class="card-body gp-now-body">
      <div class=${cls('gp-now-state', !s.patched ? 'caution' : bad ? 'bad' : 'good')}>
        <span class=${cls('gp-dot', !s.patched ? 'caution' : bad ? 'bad' : 'good')}></span>
        <span>${!s.patched ? 'Not patched: NHL 19 runs as it came.'
          : bad ? 'Patched, but something is not right (below).' : `Patched${g.applied_at ? ` ${g.applied_at}` : ''}, all intact.`}</span>
      </div>
      <dl class="gp-facts">
        ${s.patched && html`<div><dt>Patched in</dt><dd class="gp-chips">${g.layers.length ? g.layers.map((x) => html`<${Tag} key=${x.key}>${x.text}<//>`)
          : html`<span class="faint">The Overtime server only.</span>`}</dd></div>`}
        <div><dt>Online</dt><dd class="gp-online">
          ${o.server && html`<span class="gp-on-item" title="The server the patch points NHL 19 at">${o.server}</span>`}
          <span class=${cls('gp-on-item', net[0])} title="shadPS4's Set Network Connected and Enable shadNet, for NHL 19"><span class=${cls('gp-dot', net[0])}></span>${net[1]}</span>
          <span class=${cls('gp-on-item', sn[0])} title="The ShadNet account NHL 19 signs in with"><span class=${cls('gp-dot', sn[0])}></span>${sn[1]}</span>
          ${o.cross && html`<span class=${cls('gp-on-item', o.cross.tone)} title=${o.cross.title}><span class=${cls('gp-dot', o.cross.tone)}></span>${o.cross.text}</span>`}
        </dd></div>
        ${s.patched && html`<div><dt>Files</dt><dd class="gp-files-line">
          <span class=${g.files.bad ? 'bad-text' : 'good-text'}>${g.files.count} Overtime files${g.files.bad ? `, ${g.files.bad} not right` : ', all as written'}</span>
          <${Button} small className="gp-files-btn" onClick=${() => call('patch_files', true)}>List them<//>
        </dd></div>`}
      </dl>
      ${g.problems.length > 0 && html`<ul class="gp-problems">${g.problems.map((t, k) => html`<li key=${k}>${t}</li>`)}</ul>`}
      <div class="gp-tool gp-tool-row">
        <span class="small-note">Compares NHL 19's own files with how they were before the first patch.</span>
        <span class="sp"></span>
        <${Button} small className="gp-verify" disabled=${s.busy} onClick=${() => call('setup_verify', false)}>Check the game<//>
      </div>
      ${g.verify && html`<div class=${cls('small-note gp-verify-text', g.verify.tone === 'bad' ? 'bad-text' : 'good-text')}>${g.verify.text}</div>`}
    </div>
  <//>`;
}

// what the patch does: the "?" beside the Patch button (the text is patch_ctl.ABOUT and NAMES)
function patchInfo(s) {
  const names = s.names.map((x) => `${x.what}: ${x.from} → ${x.to}`);
  return names.length ? [...s.about, { head: 'The names it changes', items: names }] : s.about;
}

export default function Patch({ go }) {
  const s = useSlice('patch');
  const u = useSlice('update');
  const pa = useSlice('patchall');
  const status = useSlice('status');
  if (!s) return null;
  if (!s.ready) {
    return html`<div class="columns gp">
      <div class="col">
        <${Card} n="1" title="Overtime game patch" grow
            aside=${html`<${Info} title="What the game patch does" sections=${patchInfo(s)} label="What the game patch does"/>`}>
          <div class="card-body fill gp-empty">
            <p>NHL 19 is not set up yet. Show the program where shadPS4 is: it finds the game from there.</p>
            <${Button} kind="primary" onClick=${() => go('setup')}>Go to Setup<//>
          </div>
        <//>
      </div>
    </div>`;
  }
  const result = u && u.ready && u.result;
  return html`<div class="columns gp">
    <div class="col"><${PatchCard} s=${s} u=${u} pa=${pa} busy=${!!(status && status.busy) || s.busy} go=${go}/></div>
    <div class=${cls('col', 'gp-side', result && 'has-result')}>
      ${result && html`<${Result} r=${result}/>`}
      <${NowCard} s=${s}/>
    </div>
  </div>`;
}

// the patch files (from "List them") and the update's list of changes (from its result)
export function Modals() {
  const f = useSlice('patch_files');
  const l = useSlice('update_list');
  const close = () => call('patch_files', false);
  return html`<div class="gp-modals">
    ${f && f.open && html`<${Modal} wide title="The patch files" className="gp-files-modal" onClose=${close}
        buttons=${html`<${Button} kind="pick" big onClick=${close}>Close<//>`}>
      <p class="gp-files-where">shadPS4 serves them from <b>${f.overlay}</b>. The game folder itself is only read.</p>
      <ul class="gp-files">${f.list.map((x) => html`<li key=${x.path} class=${x.state === 'as written' ? '' : 'bad'}>
        <span class="gp-file-path">${x.path}</span><span class="gp-file-state">${x.state}</span>
      </li>`)}</ul>
    <//>`}
    <${ChangesModal} l=${l}/>
  </div>`;
}
