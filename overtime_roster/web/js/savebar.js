// The Save bar under the team tabs (not under Calendar): My edits (n), the open roster, save mode, name, Save, Ctrl+S.
// Edits wait in the open roster until Save writes it; Lines and Strategy changes count once applied.
import { html } from './lib.js';
import { call } from './bridge.js';
import { useSlice } from './store.js';
import { Button, Segmented, TextField, Modal, Keycap, Empty } from './ui.js';

// what a tab is editing and has not handed to Python yet (the Roster card's typed values): sent along with Save, so
// Ctrl+S never loses a half-typed edit. A tab sets cardDraft.current and clears it after its own Apply.
export const cardDraft = { current: null };

export function saveRoster() {
  return call('save', cardDraft.current);
}

// s (the `save` slice): {roster: {id, name, kind}, edits_count, unsaved, edits: [{id, tab, team, code, label}],
//   kept: [{key, label, team, words}], kept_count, edits_open, mode: 'update' | 'new',
//   modes: [{value, label, disabled, title}], name, button: {text, enabled}, busy}
export function SaveBar({ s }) {
  if (!s || !s.roster) return html`<div class="savebar card"></div>`;
  return html`<div class="savebar card">
    <${Button} kind=${s.edits_count ? 'gold-line' : 'ghost'} onClick=${() => call('edits_open', true)}>My edits (${s.edits_count})<//>
    <span class="sb-roster" title=${s.roster.name}>
      ${s.unsaved ? html`<span class="unsaved">${s.unsaved} not saved yet</span>` : 'Everything saved'} · <b>${s.roster.name}</b></span>
    <span class="sp"></span>
    <${Segmented} options=${s.modes} value=${s.mode} disabled=${s.busy} onChange=${(v) => call('save_mode', v)}/>
    ${s.mode === 'new' && html`<${TextField} className="name" value=${s.name} disabled=${s.busy} placeholder="Name of the new roster"
      onChange=${(t) => call('save_name', t)}/>`}
    <${Button} kind="primary" className="go" disabled=${!s.button.enabled || s.busy} onClick=${saveRoster}
      title="Ctrl+S">${s.button.text}<//>
    <${Keycap} k="Ctrl+S" title="Ctrl+S saves"/>
  </div>`;
}

// the list behind "My edits (n)": what will be written at the next Save, then the player edits kept for every update
// (edits.json: Save keeps them, the Update tab puts them back after each update; Remove drops one player's)
export function EditsWindow() {
  const s = useSlice('save');
  if (!s || !s.edits_open) return null;
  const close = () => call('edits_open', false);
  const kept = s.kept || [];
  return html`<${Modal} title=${`My edits (${s.edits_count})`} wide onClose=${close}
    buttons=${html`<${Button} kind="pick" big onClick=${close}>Close<//>`}>
    <p>These changes are in the open roster${s.roster ? `, ${s.roster.name}` : ''}. Save writes them; until then the game does not see them.</p>
    ${s.edits.length === 0 ? html`<${Empty} small>No edits yet. Change a player, lines or a strategy, then come back here.<//>`
      : html`<div class="edits-list">${s.edits.map((e) => html`<div key=${e.id} class="item">
          <span class="chip">${e.tab}</span>${e.code && html`<span class="chip accent">${e.code}</span>`}
          <span class="main">${e.label}</span></div>`)}</div>`}
    <h3 class="edits-kept-title">Kept for every update (${s.kept_count || 0})</h3>
    <p>Player edits you saved on the Roster tab. The roster update on the Patch tab puts them back after each update (its My edits switch).</p>
    ${kept.length === 0 ? html`<${Empty} small>None yet. Save a player edit (card, face & type, equipment) and it is kept here.<//>`
      : html`<div class="edits-list kept">${kept.map((e) => html`<div key=${e.key} class="item">
          ${e.team && html`<span class="chip accent">${e.team}</span>`}
          <span class="main"><b>${e.label}</b> ${e.words.join(', ')}</span>
          <${Button} small kind="ghost" onClick=${() => call('myedits_remove', e.key)}
            title="The next update leaves him as NHL.com has him (the open roster keeps what it has)">Remove<//></div>`)}</div>`}
  <//>`;
}
