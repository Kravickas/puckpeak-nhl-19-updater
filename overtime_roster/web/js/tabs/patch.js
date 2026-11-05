// Game patch: Legacy's Game patch tab in NHL 19's look. Left: the patch (state, Patch / Unpatch / Play, one switch
// per layer with its "?"). Right: the Photos, logos pack (v0.10.0) and what is in the game now (layers, files, Quick check, a full copy). What the game
// patch does is the "?" beside the Patch button. Slices `patch`, `patch_files`; calls in docs/ui/patch.md.
import { html, cls, useState } from '../lib.js';
import { useSlice } from '../store.js';
import { call } from '../bridge.js';
import { Card, Button, Switch, Info, Tag, Modal, TextField, Field, ProgressBar, Order } from '../ui.js';

export const tip = 'Patch the game once. Unpatch puts every game file back.';

function Layer({ l, busy }) {
  return html`<div class=${cls('gp-layer', l.on && 'on', l.disabled && 'off')} data-key=${l.key}>
    <div class="gp-layer-main">
      <div class="gp-layer-title"><span>${l.title}</span>${l.tag && html`<${Tag} tone=${l.tag.tone}>${l.tag.text}<//>`}</div>
      <div class="gp-layer-sub">${l.why || l.sub}</div>
    </div>
    <${Info} title=${l.info.title} text=${l.why ? `${l.info.text} ${l.why}` : l.info.text}/>
    <${Switch} on=${l.on} disabled=${busy || l.disabled} label=${l.title} onChange=${(on) => call('patch_option', l.key, on)}/>
  </div>`;
}

function PatchCard({ s, go }) {
  const b = s.buttons;
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
      ${s.layers.map((l) => html`<${Layer} key=${l.key} l=${l} busy=${s.busy}/>`)}
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

// the Photos, logos pack (v0.10.0): the four picture packs as one download, off until it is here
function PackCard({ s }) {
  const p = s.pack;
  const loading = p.state === 'downloading';
  return html`<${Card} n="2" title=${p.title} className="gp-pack" aside=${p.size && html`<span class="gp-pack-size">${p.size}</span>`}>
    <div class=${cls('card-body gp-pack-body', p.tone)}>
      <div class="gp-pack-sub">${p.sub}</div>
      <div class="gp-pack-state" role="status">${p.text}</div>
      ${loading && html`<${ProgressBar} value=${p.progress} active/>`}
      <div class="gp-pack-buttons">
        ${p.state !== 'here' && html`<${Button} small kind="primary" className="gp-pack-get" disabled=${!p.can_download}
          onClick=${() => call('setup_packs_get')}>${loading ? 'Downloading...' : p.download_text}<//>`}
        ${p.can_remove && html`<${Button} small className="gp-pack-drop" onClick=${() => call('setup_packs_drop')}>Delete...<//>`}
      </div>
    </div>
  <//>`;
}

// the packs with a switch of their own (Legacy's): on downloads the pack, off keeps it on this PC; Patch puts it in or out
function ExtraRow({ r }) {
  return html`<div class=${cls('gp-layer gp-extra', r.on && 'on', r.disabled && 'off')} data-key=${r.key}>
    <div class="gp-layer-main">
      <div class="gp-layer-title"><span>${r.title}</span>${r.tag && html`<${Tag} tone=${r.tag.tone}>${r.tag.text}<//>`}</div>
      <div class=${cls('gp-layer-sub', r.tone)}>${r.text}</div>
      ${r.progress !== null && html`<${ProgressBar} value=${r.progress} active/>`}
    </div>
    ${r.can_update && html`<${Button} small onClick=${() => call('setup_pack_download', r.name)}>Update<//>`}
    ${r.can_remove && html`<${Button} small className="gp-extra-drop" onClick=${() => call('setup_pack_remove', r.name)}>Delete...<//>`}
    <${Info} title=${r.title} text=${r.sub}/>
    <${Switch} on=${r.on} disabled=${r.disabled} label=${r.title} onChange=${(on) => call('setup_pack_switch', r.key, on)}/>
  </div>`;
}

function ExtraCard({ s }) {
  const x = s.extras;
  return html`<${Card} n="3" title=${x.title} className="gp-extras">
    <div class="card-body gp-layers">
      <div class="small-note gp-extras-sub">${x.sub}</div>
      ${x.rows.map((r) => html`<${ExtraRow} key=${r.key} r=${r}/>`)}
    </div>
  <//>`;
}

function NowCard({ s }) {
  const g = s.game;
  const [to, setTo] = useState('');
  return html`<${Card} n="4" title="In the game now" className="gp-now"
      aside=${g.problems.length ? html`<${Tag} tone="bad">${g.problems.length} ${g.problems.length === 1 ? 'problem' : 'problems'}<//>` : null}>
    <div class="card-body gp-now-body">
      ${s.patched ? html`<dl class="gp-facts">
        <div><dt>Patched</dt><dd>${g.applied_at}</dd></div>
        <div><dt>Layers</dt><dd class="gp-chips">${g.layers.length ? g.layers.map((x) => html`<${Tag} key=${x.key}>${x.text}<//>`)
          : html`<span class="faint">None: the Overtime server only.</span>`}</dd></div>
        <div><dt>Files</dt><dd class="gp-files-line">
          <span class=${g.files.bad ? 'bad-text' : 'good-text'}>${g.files.count} files${g.files.bad ? `, ${g.files.bad} not right` : ', all as written'}</span>
          <${Button} small className="gp-files-btn" onClick=${() => call('patch_files', true)}>List them<//>
        </dd></div>
      </dl>` : html`<p class="gp-clean">No patch files. NHL 19 runs as it came.</p>`}
      ${g.problems.length > 0 && html`<ul class="gp-problems">${g.problems.map((t, k) => html`<li key=${k}>${t}</li>`)}</ul>`}
      <div class="gp-tool">
        <div class="gp-tool-row">
          <span class="field-label">Clean game</span>
          <span class="sp"></span>
          <${Button} small className="gp-verify" disabled=${s.busy} onClick=${() => call('setup_verify', false)}>Quick check<//>
          <${Button} small disabled=${s.busy} onClick=${() => call('setup_verify', true)} title=${g.size ? `Every file: ${g.size}, a few minutes` : 'Every file: a few minutes'}>Check every file (slow)<//>
        </div>
        ${g.verify && html`<div class=${cls('small-note gp-verify-text', g.verify.tone === 'bad' ? 'bad-text' : 'good-text')}>${g.verify.text}</div>`}
      </div>
      <div class="gp-tool">
        <${Field} label="Full copy of the clean game" hint=${g.copy ? g.copy.text : `${g.size ? `About ${g.size}: a` : 'A'} spare to put back if the game folder breaks.`}>
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
    <div class="col"><${PackCard} s=${s}/><${ExtraCard} s=${s}/><${NowCard} s=${s}/></div>
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
