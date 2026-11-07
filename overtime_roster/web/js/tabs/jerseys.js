// The Jerseys & gear tab: Legacy's Jerseys & ice slot and layout (tiles with a picture at the left) for NHL 19's team
// gear: the gear colours, the team colours, another team's gear to copy, the sticks. Python keeps a draft per team;
// Apply hands it to My edits. Slice `jerseys`, calls in docs/ui/jerseys.md.
import { html, cls, Fragment } from '../lib.js';
import { useSlice } from '../store.js';
import { call } from '../bridge.js';
import { Button, Select, Why as UiWhy } from '../ui.js';
import { Code } from '../rail.js';

export const tip = 'Pick a new colour for a gear colour, or use the team colours, then Apply.';

const bg = (h) => ({ background: `#${h}` });
const poss = (name) => (name.endsWith('s') ? `${name}'` : `${name}'s`);
const recolour = (from, to) => call('gear_recolour', { [from]: to });

// a team the tab cannot show, or its gear still being read (Legacy's Why)
function Why({ s }) {
  return html`<${UiWhy} className="jg-why" mark=${s.view && html`<${Code} team=${s.view}/>`} text=${s.why} busy=${s.loading}/>`;
}

// --- the tiles' pictures: drawn in the colours they show ----------------------------------------------------------------
const helmetPaths = (a, b) => html`
  <path d="M10 52C8 27 26 10 50 10c22 0 38 14 38 32v10H76l-4 7H52l-4-7z" fill=${`#${a}`} class="jg-edge"/>
  <path d="M28 15c14-6 32-6 44 1l-4 7c-11-6-25-6-36-1z" fill=${`#${b}`}/>
  <circle cx="40" cy="44" r="8" fill=${`#${b}`}/>
  <path d="M74 30l18 4v7H76z" fill="rgba(255,255,255,.35)"/>`;

function Helmet({ c = [] }) {
  const [a = '303640', b = 'E6E6E6'] = c;
  return html`<svg viewBox="0 0 96 72" class="jg-art" aria-hidden="true">${helmetPaths(a, b)}</svg>`;
}

// another team's helmet passing its look to this team's
function Copies({ c = [] }) {
  const [a = '303640', b = 'E6E6E6'] = c;
  return html`<svg viewBox="0 0 96 72" class="jg-art" aria-hidden="true">
    <g transform="translate(0 4) scale(.55)" opacity=".55">${helmetPaths('8A93A3', 'D8DCE3')}</g>
    <path d="M44 22h10v-5l9 8-9 8v-5H44z" fill="rgba(255,255,255,.55)"/>
    <g transform="translate(40 28) scale(.58)">${helmetPaths(a, b)}</g>
  </svg>`;
}

function Jersey({ c = [] }) {
  const [a = '303640', b = 'E6E6E6', d = '000000'] = c;
  return html`<svg viewBox="0 0 64 64" class="jg-art" aria-hidden="true">
    <path d="M22 6 8 12 2 26l10 4 2-6v36h36V24l2 6 10-4-6-14-14-6c-2 4-6 6-10 6s-8-2-10-6z" fill=${`#${a}`} class="jg-edge"/>
    <path d="M14 44h36v5H14z" fill=${`#${b}`}/><path d="M14 51h36v3H14z" fill=${`#${d}`}/>
    <path d="M2 26l10 4 1-3-10-4z" fill=${`#${b}`}/><path d="M62 26l-10 4-1-3 10-4z" fill=${`#${b}`}/>
  </svg>`;
}

function Stick({ c = [] }) {
  const [a = '303640', b = 'E6E6E6'] = c;
  return html`<svg viewBox="0 0 96 72" class="jg-art" aria-hidden="true">
    <path d="M72 4l8 3-44 53-8-3z" fill=${`#${a}`} class="jg-edge"/>
    <path d="M28 57l8 3-4 7H8c-3 0-3-4 0-5z" fill=${`#${b}`}/>
    <path d="M14 62h12l-1 3H13z" fill="rgba(255,255,255,.5)"/>
  </svg>`;
}

const Arrow = () => html`<svg viewBox="0 0 12 10" class="jg-arrow" aria-hidden="true"><path d="M0 4h8V1l4 4-4 4V6H0z" fill="currentColor"/></svg>`;

function Tile({ pic, title, aside, className, children }) {
  return html`<div class=${cls('jg-tile', className)}>
    <div class="jg-pic">${pic}</div>
    <div class="jg-main">
      <div class="jg-tile-head"><span class="jg-tile-title subhead">${title}</span>
        ${aside && html`<span class="faint jg-aside">${aside}</span>`}</div>
      ${children}
    </div>
  </div>`;
}

// --- gear colours: each colour of the team's gear, what it becomes, where it is ------------------------------------------
function Palette({ s }) {
  const team = s.colours.now;
  return html`<${Fragment}><div class="jg-prow jg-phead">
      <span class="th">Now</span><span></span><span class="th">New</span><span class="th">Where</span>
      <span class="th">Team colours</span><span></span>
    </div>
    <div class="jg-palette">${s.palette.map((r) => html`<div key=${r.from} class=${cls('jg-prow', r.changed && 'changed')}
        title=${`#${r.from}${r.changed ? ` to #${r.to}` : ''}: ${r.pieces.join(', ')} (${r.zones} zones)`}>
      <span class="jg-sw" style=${bg(r.from)}></span>
      <${Arrow}/>
      <label class="jg-sw jg-pick" style=${bg(r.to)} title=${`#${r.to}: pick any colour`}>
        <input type="color" value=${`#${r.to.toLowerCase()}`} aria-label=${`New colour for #${r.from}`}
          onChange=${(e) => recolour(r.from, e.target.value.slice(1).toUpperCase())}/></label>
      <span class="jg-where faint">${r.pieces.join(', ')}</span>
      <span class="jg-quick">${team.map((c) => html`<button type="button" key=${c} class=${cls('jg-qsw', r.to === c && 'on')}
          style=${bg(c)} title=${`Use the team colour #${c}`} onClick=${() => recolour(r.from, c)}></button>`)}</span>
      ${r.changed ? html`<${Button} small className="jg-back" onClick=${() => recolour(r.from, r.from)}
          title=${`Back to #${r.from}`}>Back<//>` : html`<span></span>`}
    </div>`)}</div><//>`;
}

function Pieces({ s }) {
  return html`<div class="jg-pieces">${s.pieces.map((p) => html`<div key=${p.name} class="jg-piece">
      <span class="jg-pname">${p.name}</span>
      <span class="jg-bar">${p.colours.map((c) => html`<i key=${c.hex} style=${{ flex: c.n, background: `#${c.hex}` }}
        title=${`#${c.hex}: ${c.n} zones`}></i>`)}</span>
    </div>`)}</div>`;
}

function Colours({ s }) {
  const c = s.colours;
  const chips = (list) => list.map((h) => html`<span key=${h} class="jg-chip" title=${`#${h}`}><i style=${bg(h)}></i></span>`);
  return html`<${Fragment}><div class="jg-crows">
      <div class="jg-crow"><span class="jg-clabel">Now</span>${chips(c.now)}</div>
      <div class="jg-crow"><span class="jg-clabel">NHL 19's own</span>${c.game ? chips(c.game) : html`<span class="faint">None</span>`}</div>
    </div>
    <div class="jg-actions">
      <${Button} disabled=${!c.can_propose} onClick=${() => call('gear_propose')}
        title="Gear colours that wear NHL 19's old team colours change to the colours now">Use the team colours<//>
      <span class="small-note faint">${c.note}</span>
    </div><//>`;
}

function Copy({ s }) {
  const c = s.copy;
  const options = [{ value: '', label: 'This team\'s own gear' }, ...c.options];
  return html`<div class="jg-actions">
    <${Select} className="jg-select" value=${c.from ?? ''} options=${options} title="Copy the gear of"
      disabled=${c.from == null && !c.options.some((o) => !o.disabled)}
      onChange=${(v) => call('gear_copy', v === '' ? null : v)}/>
    ${c.error ? html`<span class="note bad jg-error" title=${c.error}>${c.error}</span>`
      : html`<span class="small-note faint jg-cnote" title=${c.note}>${c.note}</span>`}
  </div>`;
}

function Sticks({ s }) {
  const k = s.sticks;
  return html`<${Fragment}>${k.count ? html`<div class="list scroll jg-sticks">${k.rows.map((r) => html`<div key=${r.name}
        class=${cls('jg-stick', k.fitted && 'fitted')}>
        <b>${r.name}</b><span class="jg-old" title=${r.old}>${r.old}</span><${Arrow}/><span class="jg-new" title=${r.new}>${r.new}</span>
      </div>`)}</div>`
      : html`<p class="jg-none">Every stick matches the team colours.</p>`}
    <div class="jg-actions">
      <${Button} disabled=${!k.count} onClick=${() => call('gear_sticks', false)}
        title="Each changes to a stick of the same brand in the team colours">${k.fitted ? 'Keep these sticks' : 'Fit this team\'s sticks'}<//>
      <${Button} disabled=${!k.nhl_count} onClick=${() => call('gear_sticks', true)}
        title=${`${k.nhl_count} sticks on ${k.nhl_teams} NHL teams`}>Every NHL team...<//>
      <span class="small-note faint jg-snote">${k.fitted ? `${k.count} ${k.count === 1 ? 'stick changes' : 'sticks change'} when you press Apply.`
        : k.count ? 'Each becomes a stick of its brand in the team colours.'
          : k.nhl_count ? `${k.nhl_count} sticks on ${k.nhl_teams} NHL teams do not match their team colours.` : ''}</span>
    </div><//>`;
}

export default function Jerseys() {
  const s = useSlice('jerseys');
  if (!s) return null;
  if (s.why) return html`<${Why} s=${s}/>`;
  const helmet = (s.pieces.find((p) => p.name === 'Helmet') || { colours: [] }).colours.map((c) => c.hex);
  return html`<section class="card grow jg-tab">
    <header class="card-head jg-head">
      ${s.view && html`<${Code} team=${s.view} small/>`}
      <span class="title">${s.title}</span>
      ${s.touched && html`<span class="aside"><span class="pill">Not applied</span></span>`}
    </header>
    <div class="card-body scroll jg-body">
      <p class=${cls('small-note jg-note', s.note_tone)}>${s.note}</p>
      <div class="jg-grid">
        <div class="jg-left">
          <${Tile} className="jg-gear" pic=${html`<${Helmet} c=${helmet}/>`} title="Gear colours"
            aside=${`${s.rows} pieces · ${s.palette.length} colours${s.copy.from_name ? ` · ${poss(s.copy.from_name)}` : ''}`}>
            <${Palette} s=${s}/><${Pieces} s=${s}/>
          <//>
        </div>
        <div class="jg-right">
        <${Tile} className="jg-colours" pic=${html`<${Jersey} c=${s.colours.now}/>`} title="Team colours">
          <${Colours} s=${s}/>
        <//>
        <${Tile} className="jg-copy" pic=${html`<${Copies} c=${helmet}/>`} title="Copy another team's gear">
          <${Copy} s=${s}/>
        <//>
        <${Tile} className="jg-stick-tile" pic=${html`<${Stick} c=${s.colours.now}/>`} title="Sticks"
          aside=${s.sticks.count ? `${s.sticks.count} not in the team colours` : ''}>
          <${Sticks} s=${s}/>
        <//>
        </div>
      </div>
    </div>
    <div class="card-foot jg-foot">
      <${Button} kind="primary" disabled=${!s.can_apply} onClick=${() => call('jerseys_apply')}>Apply<//>
      <${Button} disabled=${!s.can_undo} onClick=${() => call('jerseys_undo')}
        title="Drop your changes and put back the gear the roster had">Take back my gear<//>
      <span class="small-note faint jg-foot-note">${s.mine ? 'This team wears your gear. Save the roster to keep it.'
        : 'Changes wait here until you press Apply. Jerseys come from the game; the updated jerseys go in with Game patch.'}</span>
    </div>
  </section>`;
}
