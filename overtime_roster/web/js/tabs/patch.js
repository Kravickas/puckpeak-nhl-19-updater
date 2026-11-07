// Game patch: Legacy's Game patch tab in NHL 19's look. Left: the patch (state, Patch / Unpatch / Play) and its
// switches in three groups, each with a switch of its own and a fold (v0.70.0: Teams and league, Menus and server
// texts, Updated assets; an asset switch downloads its pack). Right: what is in the game now (layers, files, Quick
// check, a full copy). What the game patch does is the "?" beside the Patch button. Slices `patch`, `patch_files`;
// calls in docs/ui/patch.md.
import { html, cls, useState } from '../lib.js';
import { useSlice } from '../store.js';
import { call } from '../bridge.js';
import { Card, Button, Switch, Info, Tag, Modal, TextField, Field, ProgressBar, Order } from '../ui.js';

export const tip = 'Patch the game once. Unpatch puts every game file back.';

const TRASH = html`<svg viewBox="0 0 14 16" aria-hidden="true"><path fill="currentColor" d="M5 0h4l.6 1.5H13a1 1 0 0 1 0 2H1a1 1 0 0 1 0-2h3.4zM2 5h10l-.8 9.6A1.5 1.5 0 0 1 9.7 16H4.3a1.5 1.5 0 0 1-1.5-1.4zm3 2v7h1.4V7zm2.6 0v7H9V7z"/></svg>`;

// one switch in a group: a patch layer, or an asset with its download state (the state line when it says something,
// else what it is). v0.70.0: its tag (In the game / Patch to add) is a dot before the title, the words on hover, so
// the title is not cut; Delete is a bin.
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

// a group: its fold, what is on, its own switch (on: its main switches; off: all of them); open, its switches in two
// columns
function Group({ g, busy, open, onOpen }) {
  const mixed = !g.on && g.count > 0;
  const st = g.store;
  return html`<section class=${cls('gp-group', g.on && 'on', mixed && 'mixed', open && 'open')} data-key=${g.key}>
    <div class="gp-group-head">
      <button type="button" class="gp-group-fold" aria-expanded=${open ? 'true' : 'false'} onClick=${() => onOpen(!open)}
          title=${open ? 'Fold' : 'Show each switch'}>
        <span class="gp-chev" aria-hidden="true"></span>
        <span class="gp-group-text">
          <span class="gp-group-title">${g.key === 'assets' && FOLDER}${g.title}
            <span class="gp-group-count">${g.count} of ${g.rows.length} on</span></span>
          <span class="gp-group-sub">${g.sub}</span>
        </span>
      </button>
      ${st && st.size && html`<span class="gp-store">${st.size} on this PC</span>`}
      ${st && st.can_remove && html`<${Button} small className="gp-store-drop" onClick=${() => call('setup_packs_drop')}
        title="Take every downloaded asset off this PC">Delete...<//>`}
      <${Switch} on=${g.on} disabled=${g.disabled} label=${g.title} onChange=${(on) => call('patch_group', g.key, on)}/>
    </div>
    ${open && html`<div class="gp-group-rows">${g.rows.map((r) => html`<${Row} key=${r.key} r=${r} busy=${busy}/>`)}</div>`}
  </section>`;
}

const FOLDS = 'overtime.patch.open';
function readFolds() {
  try { return JSON.parse(localStorage.getItem(FOLDS) || '{}') || {}; } catch (e) { return {}; }
}

function PatchCard({ s, go }) {
  const b = s.buttons;
  const [open, setOpen] = useState(readFolds);
  const fold = (key, on) => {
    const next = on ? { [key]: true } : {};      // one group open at a time: the card needs no scroll
    setOpen(next);
    try { localStorage.setItem(FOLDS, JSON.stringify(next)); } catch (e) { /* a private window: not kept */ }
  };
  return html`<${Card} n="1" title="Overtime game patch" grow featured className="gp-main"
      aside=${html`<${Tag} tone=${s.patched ? (s.state.tone === 'bad' ? 'bad' : 'good') : null}>${s.patched ? 'Patched' : 'Not patched'}<//>
        <${Button} small className="gp-refresh" disabled=${!b.refresh.enabled} onClick=${() => call('patch_refresh')}
          title="Looks at the game and shadPS4 again">Check again<//>`}>
    <div class="card-body gp-top">
      <div class=${cls('gp-state', s.state.tone)} role="status"><span class="gp-mark"></span><span>${s.state.text}</span></div>
      <${Order} here="patch" go=${go}/>
      <div class="gp-buttons">
        <${Button} kind="featured" big className="gp-patch" disabled=${!b.patch.enabled} onClick=${() => call('setup_patch')}>${b.patch.text}<//>
        <${Info} title="What the game patch does" sections=${patchInfo(s)} label="What the game patch does"/>
        <${Button} kind="gold-line" className="gp-unpatch" disabled=${!b.unpatch.enabled} onClick=${() => call('setup_unpatch')}>Unpatch<//>
        <span class="sp"></span>
        <${Button} className="gp-play" disabled=${!b.play.enabled} onClick=${() => call('setup_play')}>
          <svg class="gp-play-icon" viewBox="0 0 10 12" aria-hidden="true"><path d="M0 0 10 6 0 12z" fill="currentColor"/></svg>Play<//>
      </div>
    </div>
    <div class="card-body gp-layers">
      <div class="gp-layers-head">
        <span class="field-label">What the patch puts in</span>
        <span class="small-note gp-hint">${s.hint}</span>
      </div>
      ${s.groups.map((g) => html`<${Group} key=${g.key} g=${g} busy=${s.busy} open=${!!open[g.key]}
        onOpen=${(on) => fold(g.key, on)}/>`)}
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

function NowCard({ s }) {
  const g = s.game;
  const [to, setTo] = useState('');
  return html`<${Card} n="2" title="What's in your game now" className="gp-now"
      aside=${g.problems.length ? html`<${Tag} tone="bad">${g.problems.length} ${g.problems.length === 1 ? 'problem' : 'problems'}<//>` : null}>
    <div class="card-body gp-now-body">
      ${s.patched ? html`<dl class="gp-facts">
        <div><dt>Patched</dt><dd>${g.applied_at}</dd></div>
        <div><dt>Patched in</dt><dd class="gp-chips">${g.layers.length ? g.layers.map((x) => html`<${Tag} key=${x.key}>${x.text}<//>`)
          : html`<span class="faint">None: the Overtime server only.</span>`}</dd></div>
        <div><dt>Files</dt><dd class="gp-files-line">
          <span class=${g.files.bad ? 'bad-text' : 'good-text'}>${g.files.count} files changed${g.files.bad ? `, ${g.files.bad} not right` : ', all intact'}</span>
          <${Button} small className="gp-files-btn" onClick=${() => call('patch_files', true)}>List them<//>
        </dd></div>
      </dl>` : html`<p class="gp-clean">No patch files. NHL 19 runs as it came.</p>`}
      ${g.problems.length > 0 && html`<ul class="gp-problems">${g.problems.map((t, k) => html`<li key=${k}>${t}</li>`)}</ul>`}
      <div class="gp-tool">
        <div class="gp-tool-row">
          <span class="field-label">Check for damage</span>
          <span class="sp"></span>
          <${Button} small className="gp-verify" disabled=${s.busy} onClick=${() => call('setup_verify', false)}>Quick check<//>
          <${Button} small disabled=${s.busy} onClick=${() => call('setup_verify', true)} title=${g.size ? `Every file: ${g.size}, a few minutes` : 'Every file: a few minutes'}>Check every file (slow)<//>
        </div>
        ${g.verify && html`<div class=${cls('small-note gp-verify-text', g.verify.tone === 'bad' ? 'bad-text' : 'good-text')}>${g.verify.text}</div>`}
      </div>
      <div class="gp-tool">
        <${Field} label="Backup copy of the game" hint=${g.copy ? g.copy.text : `${g.size ? `About ${g.size}: a` : 'A'} spare to put back if the game folder breaks.`}>
          <div class="row">
            <${TextField} value=${to} placeholder="D:\\Games\\NHL 19 copy" disabled=${s.busy} onChange=${setTo}
              onEnter=${() => call('setup_copy', to)}/>
            <${Button} disabled=${s.busy} onClick=${() => call('setup_copy', to)}>Copy<//>
          </div>
        <//>
      </div>
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
  return html`<div class="columns gp">
    <div class="col"><${PatchCard} s=${s} go=${go}/></div>
    <div class="col"><${NowCard} s=${s}/></div>
  </div>`;
}

// the patch files (from "List them"): each file the patch serves, and whether it is as the patch wrote it
export function Modals() {
  const f = useSlice('patch_files');
  if (!f || !f.open) return null;
  const close = () => call('patch_files', false);
  return html`<${Modal} wide title="The patch files" className="gp-files-modal" onClose=${close}
      buttons=${html`<${Button} kind="pick" big onClick=${close}>Close<//>`}>
    <p class="gp-files-where">shadPS4 serves them from <b>${f.overlay}</b>. The game folder itself is only read.</p>
    <ul class="gp-files">${f.list.map((x) => html`<li key=${x.path} class=${x.state === 'as written' ? '' : 'bad'}>
      <span class="gp-file-path">${x.path}</span><span class="gp-file-state">${x.state}</span>
    </li>`)}</ul>
  <//>`;
}
