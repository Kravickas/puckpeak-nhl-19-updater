// The small parts the tabs are built from: Legacy's components with Legacy's prop names, in NHL 19's look.
// Write labels normally ("Save as a new roster"): the CSS makes heads, buttons and tabs caps.
import { html, cls, useRef, useLayoutEffect, useState, useEffect, useMemo, createPortal } from './lib.js';

// kind: ghost (default) | primary | pick | danger | caution | gold (= featured) | gold-line | featured
export function Button({ kind = 'ghost', small, big, block, disabled, onClick, title, className, children }) {
  return html`<button type="button" title=${title}
    class=${cls('btn', kind, small && 'small', big && 'big', block && 'block', className)}
    disabled=${disabled} onClick=${onClick}>${children}</button>`;
}

// on / off. With children it is a row: the switch and its label, the label clickable too.
export function Toggle({ on, disabled, onChange, label, gold, children }) {
  const sw = html`<button type="button" role="switch" aria-checked=${!!on} aria-label=${label || (typeof children === 'string' ? children : undefined)}
    class=${cls('toggle', on && 'on', gold && 'gold')} disabled=${disabled}
    onClick=${(e) => { e.stopPropagation(); onChange(!on); }}></button>`;
  if (!children) return sw;
  return html`<div class=${cls('switch-row', disabled && 'disabled')} onClick=${() => !disabled && onChange(!on)}>
    ${sw}<span class="switch-label">${children}</span></div>`;
}
export const Switch = Toggle;

export function Checkbox({ on, disabled, onChange, title, children }) {
  return html`<div role="checkbox" aria-checked=${!!on} tabindex="0" title=${title}
    class=${cls('check', on && 'on', disabled && 'disabled')}
    onClick=${() => !disabled && onChange(!on)}
    onKeyDown=${(e) => { if (!disabled && (e.key === ' ' || e.key === 'Enter')) { e.preventDefault(); onChange(!on); } }}>
    <span class="box"><svg viewBox="0 0 12 12"><path d="M2 6.5 5 9.2 10.2 3" fill="none" stroke="#fff" stroke-width="2"/></svg></span>
    ${children}
  </div>`;
}

// a choice of a few, with a bar that slides to the one picked; options: [{value, label, icon?, disabled?, title?}]
export function Segmented({ options, value, disabled, onChange, className }) {
  const box = useRef(null);
  const [thumb, setThumb] = useState(null);
  // the picked button draws its own look (CSS: .seg button.on); the measured thumb only slides between picks, so a
  // measure that fails (a hidden tab, fonts still coming) never leaves the choice without its mark
  useLayoutEffect(() => {
    const measure = () => {
      const el = box.current && box.current.querySelector('button.on');
      setThumb(el && el.offsetWidth ? { x: el.offsetLeft - 2, w: el.offsetWidth } : null);
    };
    measure();
    const frame = requestAnimationFrame(measure);   // after the first paint: fonts and widths settled
    const watch = new ResizeObserver(measure);      // a tab shown again, the picked label growing
    watch.observe(box.current);
    const on = box.current.querySelector('button.on');
    if (on) watch.observe(on);
    return () => { cancelAnimationFrame(frame); watch.disconnect(); };
  }, [value, options.map((o) => o.label).join('|')]);
  return html`<div ref=${box} class=${cls('seg', disabled && 'disabled', thumb && 'has-thumb', className)}>
    ${thumb && html`<span class="thumb" style=${{ width: thumb.w + 'px', transform: `translateX(${thumb.x}px)` }}></span>`}
    ${options.map((o) => html`<button type="button" key=${o.value} class=${o.value === value ? 'on' : ''} title=${o.title}
        disabled=${disabled || o.disabled} onClick=${() => o.value !== value && onChange(o.value)}>${o.icon}${o.label}</button>`)}
  </div>`;
}

// a card under NHL 19's hatched strip. n (or num): the step number; aside: right of the title; you write the
// body yourself (<div class="card-body">) or use Panel.
export function Card({ n, num, title, aside, grow, featured, className, style, children }) {
  const step = n != null ? n : num;
  return html`<section class=${cls('card', grow && 'grow', featured && 'featured', className)} style=${style}>
    <header class="card-head">
      ${step != null && html`<span class="num">${step}</span>`}
      ${featured && html`<${Featured}/>`}
      <span class="title">${title}</span>
      ${aside && html`<span class="aside">${aside}</span>`}
    </header>
    ${children}
  </section>`;
}

// a Card with its body (fill: stretches; scroll: scrolls) and an optional foot (buttons)
export function Panel({ n, num, title, aside, grow, featured, fill, scroll, foot, className, bodyClass, style, children }) {
  return html`<${Card} n=${n} num=${num} title=${title} aside=${aside} grow=${grow} featured=${featured} className=${className} style=${style}>
    <div class=${cls('card-body', fill && 'fill', scroll && 'scroll', bodyClass)}>${children}</div>
    ${foot && html`<div class="card-foot">${foot}</div>`}
  <//>`;
}

// a labelled field: the label above (caps), the control, a hint under it
export function Field({ label, hint, className, children }) {
  return html`<div class=${cls('labelled', className)}>
    ${label && html`<span class="field-label">${label}</span>`}
    ${children}
    ${hint && html`<span class="hint">${hint}</span>`}
  </div>`;
}

// NHL 19's FEATURED tag (Legacy's gold): on Patch, Go and featured rows
export function Featured({ children = 'Featured' }) {
  return html`<span class="featured-tag">${children}</span>`;
}

// a PS4 button glyph: L1, R1 (caps); ✕ ○ D (circles)
export function Keycap({ k, onClick, title }) {
  return html`<span class=${cls('keycap', String(k).length === 1 && 'round')} title=${title} onClick=${onClick}>${k}</span>`;
}

// tone: good | bad | caution | info | accent | (none: grey)
export function Tag({ tone, title, children }) {
  return html`<span class=${cls('chip', tone)} title=${title}>${children}</span>`;
}

// the order the program is used in, shown on Update and Game patch (v0.60.1): Update makes the roster, Game patch
// puts the game files, club logos and kits of that roster in, then NHL 19 must be set to the roster in Rosters > Active Rosters
export function Order({ here, go }) {
  const step = (id, n, text) => here === id
    ? html`<span class="order-step here" aria-current="step"><b>${n}</b>${text}</span>`
    : html`<button type="button" class="order-step" onClick=${() => go(id)}><b>${n}</b>${text}</button>`;
  return html`<div class="order" role="note" aria-label="The order: Update, then Game patch, then the Active Roster in the game">
    ${step('update', 1, 'Update')}<span class="order-arrow" aria-hidden="true">›</span>
    ${step('patch', 2, 'Game patch')}<span class="order-arrow" aria-hidden="true">›</span>
    <span class="order-step last"><b>3</b>In NHL 19: Rosters > Active Rosters, pick the new roster</span>
  </div>`;
}

// a tab with nothing to show yet (no roster, a team it cannot show, the roster still being read): one centred block.
// mark: a node over the text (a team chip); busy: a small spinner; children: buttons under the text
export function Why({ mark, text, busy, className, children }) {
  return html`<div class=${cls('why-wrap', className)}><section class="card why">
    ${mark}
    <p>${text}</p>
    ${busy && html`<span class="spin" role="progressbar" aria-label="Reading"></span>`}
    ${children && html`<div class="why-acts">${children}</div>`}
  </section></div>`;
}

export function Empty({ small, children }) {
  return html`<div class=${cls('empty', small && 'small')}>${children}</div>`;
}

// a path shortened in the middle by the layout itself: the end (file name) always shows
export function PathText({ path, unset }) {
  if (!path) return html`<div class="field path unset">${unset}</div>`;
  const cut = Math.max(path.lastIndexOf('\\'), path.lastIndexOf('/'));
  const head = cut > 0 ? path.slice(0, cut + 1) : '';
  const tail = cut > 0 ? path.slice(cut + 1) : path;
  return html`<div class="field path" title=${path}><span class="head">${head}</span><span class="tail">${tail}</span></div>`;
}

export function ProgressBar({ value, active, indeterminate }) {
  return html`<div class=${cls('progress', active && 'active', indeterminate && 'indeterminate')}
    role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow=${Math.round((value || 0) * 100)}>
    <div class="fill" style=${{ transform: `scaleX(${Math.max(0, Math.min(1, value || 0))})` }}></div>
    <div class="sweep"></div>
  </div>`;
}

// an input the player types in: Python's value is shown unless the player is typing
export function TextField({ value, disabled, onChange, delay = 250, className, placeholder, onEnter }) {
  const [text, setText] = useState(value || '');
  const typing = useRef(false);
  const timer = useRef(null);
  useEffect(() => { if (!typing.current) setText(value || ''); }, [value]);
  useEffect(() => () => clearTimeout(timer.current), []);
  return html`<input class=${cls('field', className)} value=${text} disabled=${disabled} placeholder=${placeholder}
    spellcheck="false"
    onFocus=${() => { typing.current = true; }}
    onBlur=${() => { typing.current = false; clearTimeout(timer.current); if (text !== (value || '')) onChange(text); }}
    onKeyDown=${(e) => { if (e.key === 'Enter') { clearTimeout(timer.current); onChange(text); onEnter && onEnter(); } }}
    onInput=${(e) => { const t = e.target.value; setText(t); clearTimeout(timer.current);
      timer.current = setTimeout(() => onChange(t), delay); }}/>`;
}

// a select over [{value, label, disabled?}]; onChange gets the option's value (numbers stay numbers)
export function Select({ value, options, disabled, onChange, className, title }) {
  return html`<select class=${cls('field', className)} value=${String(value)} disabled=${disabled} title=${title}
    onChange=${(e) => { const o = options[e.target.selectedIndex]; if (o) onChange(o.value); }}>
    ${options.map((o) => html`<option key=${o.value} value=${String(o.value)} disabled=${o.disabled}>${o.label}</option>`)}
  </select>`;
}

const INFO_EDGE = 12;

// where the "?"'s text goes: under the "?" when it fits there, else over it, else beside it (when two columns fit),
// else over the "?" as near it as the window lets it be
export function infoSpot(dot, pop) {
  const r = dot.getBoundingClientRect();
  const vw = window.innerWidth, vh = window.innerHeight, edge = INFO_EDGE;
  const h = pop ? pop.offsetHeight : 0;
  const full = Math.min(1000, vw - 2 * edge);
  const near = Math.max(edge, Math.min(vh - edge - h, r.top + r.height / 2 - h / 2));
  const right = vw - r.right - 10 - edge, left = r.left - 10 - edge;
  let spot;
  if (r.bottom + 8 + h <= vh - edge) spot = { top: r.bottom + 8 };
  else if (r.top - 8 - h >= edge) spot = { top: r.top - 8 - h };
  else if (Math.max(right, left) >= 820) {
    const width = Math.min(1000, Math.max(right, left));
    spot = { left: right >= left ? r.right + 10 : r.left - 10 - width, top: near, width };
  } else spot = { top: near };
  const place = { left: Math.max(edge, Math.min(r.left - 16, vw - full - edge)), width: full, ...spot,
                  maxHeight: vh - 2 * edge };
  for (const k of ['left', 'top', 'width']) place[k] = Math.round(place[k]);
  return place;
}

// a "?" that explains more while the pointer is on it (or the keyboard is); a click keeps it open, Escape or a click
// elsewhere closes it. sections: [{head, items: [text]}]; text: one paragraph instead. Short texts get a narrow box.
export function Info({ title, sections = [], text, label = 'More about this', narrow }) {
  const dot = useRef(null);
  const pop = useRef(null);
  const timer = useRef(null);
  const [hover, setHover] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [place, setPlace] = useState(null);
  const [, setSize] = useState(0);
  const open = hover || pinned;
  const small = narrow || sections.length <= 1;
  const show = () => { clearTimeout(timer.current); setHover(true); };
  const hide = () => { clearTimeout(timer.current); timer.current = setTimeout(() => setHover(false), 180); };
  const close = () => { clearTimeout(timer.current); setHover(false); setPinned(false); };
  useLayoutEffect(() => {
    if (!open) { if (place) setPlace(null); return; }
    let next = infoSpot(dot.current, pop.current);
    if (small) next = { ...next, width: Math.min(next.width, 420) };
    if (!place || Object.keys(next).some((k) => next[k] !== place[k])) setPlace(next);
  });
  useEffect(() => {
    if (!open) return undefined;
    const again = () => setSize((n) => n + 1);
    window.addEventListener('resize', again);
    return () => window.removeEventListener('resize', again);
  }, [open]);
  useEffect(() => {
    if (!open) return undefined;
    const key = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
    const away = (e) => { if (!dot.current.contains(e.target) && !(pop.current && pop.current.contains(e.target))) close(); };
    window.addEventListener('keydown', key, true);
    window.addEventListener('mousedown', away, true);
    return () => { window.removeEventListener('keydown', key, true); window.removeEventListener('mousedown', away, true); };
  }, [open]);
  useEffect(() => () => clearTimeout(timer.current), []);
  const width = place ? place.width : Math.min(small ? 420 : 1000, window.innerWidth - 2 * INFO_EDGE);
  const box = open && html`<div ref=${pop} role="tooltip"
      class=${cls('info-pop', !small && (width >= 900 ? 'three' : width >= 600 && 'two'))}
      style=${place || { width, left: 0, top: 0, visibility: 'hidden' }}
      onMouseEnter=${show} onMouseLeave=${hide}>
    <div class="i-title">${title}</div>
    ${text && html`<p>${text}</p>`}
    ${sections.length > 0 && html`<div class="i-parts">${sections.map((s) => html`<div key=${s.head} class="i-part">
      ${s.head && html`<div class="i-head">${s.head}</div>`}
      <ul>${s.items.map((t, k) => html`<li key=${k}>${t}</li>`)}</ul>
    </div>`)}</div>`}
  </div>`;
  return html`<button type="button" ref=${dot} class=${cls('info-dot', open && 'open')} aria-label=${label}
      aria-expanded=${open} onMouseEnter=${show} onMouseLeave=${hide} onFocus=${show} onBlur=${hide}
      onClick=${(e) => { e.stopPropagation(); pinned ? close() : setPinned(true); }}>?</button>
    ${box && createPortal(box, document.body)}`;
}

// a dialog: the window dims and blurs behind it (the Help bar stays readable). buttons (or foot): the row at the
// bottom; Escape and a click beside it call onClose. tone 'bad' paints the title red. It always goes into the
// window's root (#app), so a dialog opened from a tab covers the whole window.
export function Modal({ title, wide, full, tone, onClose, buttons, foot, className, children }) {
  useEffect(() => {
    const key = (e) => { if (e.key === 'Escape' && onClose) { e.stopPropagation(); onClose(); } };
    window.addEventListener('keydown', key, true);
    return () => window.removeEventListener('keydown', key, true);
  }, [onClose]);
  const row = buttons || foot;
  const page = html`<div class=${cls('modal-back', full && 'full')} onMouseDown=${(e) => { if (e.target === e.currentTarget && onClose) onClose(); }}>
    <div class=${cls('modal', wide && 'wide', full && 'full', tone, className)} role="dialog" aria-modal="true">
      <div class="m-head">${title}</div>
      <div class="m-body">${children}</div>
      ${row && html`<div class="m-buttons">${row}</div>`}
    </div>
  </div>`;
  const root = document.getElementById('app');
  return root ? createPortal(page, root) : page;
}

// --- tables -----------------------------------------------------------------------------------------------------------
// columns: [{key, label, width = '1fr' (a grid track), align: 'r' | 'm', num (tabular digits), bold,
//            sort: false | (row) => value (default: row[key]), cell: (row) => content (default: row[key]), title}]
export function sortValue(row, col) {
  if (typeof col.sort === 'function') return col.sort(row);
  const v = row[col.key];
  return typeof v === 'string' ? v.toLowerCase() : v;
}

// rows sorted by sort = {key, dir: 1 | -1}; empty values last either way; ties keep their order
export function sortRows(rows, columns, sort) {
  const col = sort && columns.find((c) => c.key === sort.key);
  if (!col || col.sort === false) return rows;
  const dir = sort.dir || 1;
  return rows.map((r, i) => [r, i]).sort(([a, i], [b, j]) => {
    const x = sortValue(a, col), y = sortValue(b, col);
    const xe = x == null || x === '', ye = y == null || y === '';
    if (xe || ye) return xe === ye ? i - j : xe ? 1 : -1;
    return (x < y ? -1 : x > y ? 1 : 0) * dir || i - j;
  }).map(([r]) => r);
}

function useSort(sort, onSort, columns) {
  const [own, setOwn] = useState(sort || null);
  const now = onSort ? sort : own;
  const pick = (key) => {
    const col = columns.find((c) => c.key === key);
    if (!col || col.sort === false) return;
    const next = now && now.key === key ? { key, dir: -(now.dir || 1) } : { key, dir: col.num ? -1 : 1 };
    onSort ? onSort(next) : setOwn(next);
  };
  return [now, pick];
}

// a sortable table; sel: the picked row's key; onPick(row); Up / Down move the pick while the table has focus.
// Without onSort the table sorts by itself (sort is then the first order).
export function Table({ columns, rows, rowKey = 'id', sel, onPick, sort, onSort, dim, className, empty = 'Nothing here.' }) {
  const [now, pick] = useSort(sort, onSort, columns);
  const shown = useMemo(() => sortRows(rows, columns, now), [rows, columns, now]);
  const body = useRef(null);
  const grid = columns.map((c) => c.width || '1fr').join(' ');
  useEffect(() => {
    const el = body.current && body.current.querySelector('.tbl-row.sel');
    if (el) el.scrollIntoView({ block: 'nearest' });
  }, [sel]);
  const key = (e) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const at = shown.findIndex((r) => r[rowKey] === sel);
    const next = shown[Math.max(0, Math.min(shown.length - 1, at + (e.key === 'ArrowDown' ? 1 : -1)))];
    if (next && onPick) onPick(next);
  };
  const align = (c) => cls(c.align, c.num && 'n', c.bold && 'b');
  return html`<div class=${cls('tbl', className)} style=${{ '--cols': grid }}>
    <div class="tbl-head" role="row">
      ${columns.map((c) => html`<div key=${c.key} role="columnheader" title=${c.title}
          class=${cls('th', align(c), c.sort !== false && 'sortable', now && now.key === c.key && 'on')}
          onClick=${() => pick(c.key)}>${c.label}${now && now.key === c.key && html`<i class="arrow">${now.dir < 0 ? '▼' : '▲'}</i>`}</div>`)}
    </div>
    <div class="tbl-body" ref=${body} tabindex="0" role="rowgroup" onKeyDown=${key}>
      ${shown.length === 0 && html`<${Empty} small>${empty}<//>`}
      ${shown.map((r) => html`<div key=${r[rowKey]} role="row"
          class=${cls('tbl-row', r[rowKey] === sel && 'sel', dim && dim(r) && 'dim')}
          onClick=${() => onPick && onPick(r)}>
        ${columns.map((c) => html`<div key=${c.key} class=${cls('c', align(c))}>${c.cell ? c.cell(r) : r[c.key]}</div>`)}
      </div>`)}
    </div>
  </div>`;
}

// money in millions as the game shows it: $5.125M; $750K under a million
export function money(millions) {
  if (millions == null || Number.isNaN(millions)) return '';
  const m = Number(millions);
  if (Math.abs(m) < 1) return `$${Math.round(m * 1000)}K`;
  return `$${m.toFixed(3).replace(/\.?0+$/, '')}M`;
}
