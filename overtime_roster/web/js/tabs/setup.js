// Setup: where shadPS4 is and its checks, which roster you work on, this program (the Online card lives on Multiplayer). Legacy's
// SetupTab (RpcsCard, RosterCard, ProgramCard) in NHL 19's look. The picture packs moved to Game patch's Photos, logos
// pack card (v0.10.0); the slice keeps `downloads` for tools.
// Slice `setup`; calls setup_*, rosters_* (docs/ui/setup.md).
import { html, cls, useState, useEffect, useRef } from '../lib.js';
import { useSlice } from '../store.js';
import { call } from '../bridge.js';
import { Card, Button, PathText, Checkbox, Info, Modal, Segmented, Tag } from '../ui.js';
import { GameSettings, Controllers, Keyboard, GEAR_ICON, PAD_ICON, KEYS_ICON } from './emusettings.js';

export const tip = 'Find NHL 19 and pick the roster you work on. Everything else follows them.';

// a check's mark: good ✓, bad ✕, caution !, not checked yet …
const MARKS = {
  good: html`<path d="M3 8.4 6.4 11.6 13 4.6" fill="none" stroke="currentColor" stroke-width="2.4"/>`,
  bad: html`<path d="M4.2 4.2 11.8 11.8M11.8 4.2 4.2 11.8" fill="none" stroke="currentColor" stroke-width="2.4"/>`,
  caution: html`<path d="M8 2.8V9.4" stroke="currentColor" stroke-width="2.4"/><rect x="6.8" y="11.2" width="2.4" height="2.4" fill="currentColor"/>`,
  idle: html`<g fill="currentColor"><rect x="2.6" y="7" width="2.2" height="2.2"/><rect x="6.9" y="7" width="2.2" height="2.2"/><rect x="11.2" y="7" width="2.2" height="2.2"/></g>`,
};

function Mark({ tone }) {
  return html`<span class=${cls('su-mark', tone || 'idle')}><svg viewBox="0 0 16 16" aria-hidden="true">${MARKS[tone || 'idle']}</svg></span>`;
}

// --- Discord and Ko-fi: first in Setup, as in Legacy (0.50.2 / 0.50.4) -----------------------------------------------------
// Discord's mark (simple-icons, CC0), drawn here: the page loads nothing from the internet
const DISCORD_MARK = 'M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z';

function LinkRow() {
  return html`<div class="su-links">
    <button type="button" class="su-discord" title="gg.puckpeak.com" onClick=${() => call('open_discord')}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d=${DISCORD_MARK}/></svg>
      <span class="t">Join our Discord</span><span class="sub">Updates, patches, help · gg.puckpeak.com</span></button>
    <button type="button" class="su-kofi" title="ko-fi.com/iksperial" onClick=${() => call('open_kofi')}>
      <span class="cup" aria-hidden="true">☕</span>
      <span class="txt"><span class="t">Buy me a coffee</span><span class="sub">Support the development</span></span></button>
  </div>`;
}

// --- 1 Where is NHL 19? ---------------------------------------------------------------------------------------------------
const WHERE_INFO = [
  { head: 'What to pick', items: ['Press Find game and pick NHL 19\'s eboot.bin, or its PKG files to install the game.',
    'No shadPS4 on this PC? None needed: Overtime gets the build chosen under Boost performance by itself.',
    'Have shadPS4 already? Pick shadPS4QtLauncher.exe or shadPS4.exe and it is used (with QtLauncher, the version selected in it).',
    'The program finds the rest from there: NHL 19, the emulator and your roster saves.'] },
  { head: 'Installing from PKG', items: ['Pick the game PKG first, then the update 1.60 PKG. One at a time.',
    'The game goes into a new folder next to its PKG, the update into a new folder beside the game. Nothing is overwritten.',
    'It needs free space on that drive about the size of the PKG.',
    'The PKG tool is shadPS4Plus\'s pkg_extractor (GPL-2.0), downloaded from its GitHub page the first time: github.com/AzaharPlus/shadPS4Plus.'] },
  { head: 'Folders', items: ['Open it for the checks (below) and where shadPS4, NHL 19, shadPS4\'s data and your saves are.',
    'Change... picks one yourself (a portable shadPS4, another drive). The program never changes a folder you set.',
    'Auto lets the program find it again.',
    'Downloads and cache: the packs downloaded and the jerseys made on this PC (several GB with every pack). Change... moves '
      + 'them to a folder you pick, e.g. on the drive NHL 19 is on; Auto moves them back.'] },
  { head: 'The checks', items: ['shadPS4: found, and its version.', 'NHL 19: the game (CUSA11126 or CUSA11116) with update 1.60.',
    'ShadNet: you are signed in inside shadPS4.', 'Network: the Overtime server answers.',
    'Hold the mouse on a check to read all of it.'] },
];

// Find game: Windows' picker for the launcher, the emulator or the game; in a browser (no window to show it in)
// Python answers {type: true} and the path is typed
async function findGame(path) {
  const reply = await call('setup_pick_emulator', false);
  if (!reply || !reply.type) return;
  const typed = window.prompt('The full path of NHL 19\'s eboot.bin or PKG, shadPS4QtLauncher.exe or shadPS4.exe:', path || '');
  if (typed && typed.trim()) call('setup_set_emulator', typed.trim());
}

// Folders: each one found or set by hand (Change...), Auto finds it again. In a browser Python answers {type: true}
// and the path is typed
const FOLDER_ASK = {
  game: "The full path of NHL 19's folder (the one holding eboot.bin):",
  data: "The full path of shadPS4's data folder (\"user\" beside shadPS4.exe, or %APPDATA%\\shadPS4):",
  saves: 'The full path of the saves folder (...\\home\\1000\\savedata\\CUSA11126):',
  cache: 'The full path of a folder for the downloads and cache (its files move there):',
};
async function changeFolder(f) {
  if (f.key === 'emulator') return findGame(f.path);
  const reply = await call('setup_folder_pick', f.key);
  if (!reply || !reply.type) return;
  const typed = window.prompt(FOLDER_ASK[f.key], f.path || '');
  if (typed && typed.trim()) call('setup_folder_set', f.key, typed.trim());
}

// the checks (shadPS4, NHL 19, ShadNet, Network) and the folders, inside one dropdown, collapsed by default (owner
// 2026-11-11: "stupid proof"); its summary names the first check that is not good
function Folders({ folders, checks, checking, busy }) {
  folders = folders || [];
  checks = checks || [];
  const mine = folders.filter((f) => f.custom).length;
  const missing = folders.filter((f) => !f.ok).length;
  const off = checks.find((c) => c.tone === 'bad') || checks.find((c) => c.tone === 'caution');
  const sum = [off && `${off.label}: ${off.value}`, mine && `${mine} set by you`, missing && `${missing} not found`]
    .filter(Boolean).join(', ') || (checking ? 'checking...' : 'all found');
  return html`<details class="su-folders">
    <summary>Folders <span class=${cls('su-fsum', off && off.tone)}>${sum}</span></summary>
    ${checks.length > 0 && html`<div class=${cls('su-checks', checking && 'checking')}>
      ${checks.map((c) => html`<div key=${c.key} class=${cls('su-check', c.tone || 'idle')} title=${c.text}>
        <${Mark} tone=${c.tone}/>
        <span class="su-ct"><span class="su-cl">${c.label}</span><span class="su-cv">${c.value}</span></span>
      </div>`)}
    </div>`}
    <div class="su-fgrid">${folders.map((f) => html`<div key=${f.key}
      class=${cls('su-folder', !f.ok && 'bad')}>
      <span class="su-fl">${f.label}</span>
      <${PathText} path=${f.path} unset="Not found"/>
      <${Tag} tone=${f.custom ? 'info' : (f.ok ? '' : 'bad')}
        title=${f.custom ? 'You set this one. Checks never change it.' : 'Found by the program'}>${f.custom ? 'yours' : (f.ok ? 'found' : 'not found')}<//>
      <${Button} small disabled=${busy} onClick=${() => changeFolder(f)}
        title=${f.key === 'emulator' ? 'Pick shadPS4QtLauncher.exe or shadPS4.exe'
          : (f.key === 'cache' ? 'Pick a folder: the downloads and cache move there' : 'Pick this folder yourself')}>Change...<//>
      ${f.custom ? html`<${Button} small disabled=${busy} onClick=${() => call('setup_folder_auto', f.key)}
        title=${f.key === 'cache' ? 'Move them back to the program\'s own folder' : 'Let the program find it again'}>Auto<//>`
        : html`<span class="su-fauto"></span>`}
    </div>`)}</div>
  </details>`;
}

function WhereCard({ s }) {
  const st = s.state;
  const busy = s.busy;
  return html`<${Card} n="1" title="Where is NHL 19?" className="su-where"
      aside=${html`<${Info} title="Where is NHL 19?" sections=${WHERE_INFO}/>`}>
    <div class="card-body">
      <div class="row">
        <${PathText} path=${s.emulator.path} unset="Not picked yet"/>
        <${Button} kind=${s.emulator.path ? 'ghost' : 'primary'} disabled=${busy} onClick=${() => findGame(s.emulator.path)}
          title="Pick NHL 19's eboot.bin or its PKG, or your shadPS4 (shadPS4QtLauncher.exe or shadPS4.exe)">Find game...<//>
      </div>
      <${Folders} folders=${s.folders} checks=${s.checks} checking=${s.checking} busy=${busy}/>
      <div class=${cls('su-state', st.tone)}>
        <span class="su-st">${st.text}</span>
        ${s.emulator.path && html`<${Button} small disabled=${busy} onClick=${() => call('setup_refresh')}>Check again<//>`}
      </div>
    </div>
  <//>`;
}

// --- Boost performance: the shadPS4 build the green Play NHL 19 button starts, Nightly or Kravickas -------------------------
const BOOST_INFO = [
  { head: 'What it does', items: ['Picks the shadPS4 build that the green Play NHL 19 button starts. The lit one is in use.',
    "Nightly (the default): upstream shadPS4's newest official build. Kravickas: Overtime's smooth build on Kravickas's NHL 19 fixes.",
    'Play downloads the chosen build the first time, and again when a newer one is published. Update gets it now.',
    'Saves, patch and ShadNet login stay the same with either build.'] },
  { head: 'Online', items: ['Multiplayer lobbies start the lobby build by themselves, whichever one is chosen here.',
    'Open matchmaking pairs you with players on the same build.'] },
  { head: 'Your own shadPS4', items: ['It stays where it is, untouched.',
    'A portable shadPS4 with its own "user" folder keeps playing itself: the builds would not find its saves.'] },
  { head: 'Resolution', items: ["1080p is the game's own. 1440p renders at 2560x1440 (Kravickas's patch): sharper, needs a stronger GPU.", "720p renders at 1280x720 (Kravickas's patch): softer, for a weaker GPU.", '1440p also sets Additional DMem to 3500 MB; 720p and 1080p put your own value back.', 'Works with either build. Takes effect at the next start of NHL 19.'] },
  { head: 'Replays at 60 fps', items: ["Kravickas's patch, on for everyone: replays, celebrations and cutscenes run at 60 instead of 30."] },
];
const RESOLUTIONS = [
  { value: 720, label: '720p', title: 'Renders at 1280x720 (Kravickas patch), for a weaker GPU' },
  { value: 1080, label: '1080p', title: "The game's own resolution" },
  { value: 1440, label: '1440p', title: 'Renders at 2560x1440 (Kravickas patch), needs a stronger GPU' },
];

function BoostCard({ s }) {
  const b = s.boost;
  const [view, setView] = useState(null);     // 'game' | 'pad' | 'keys': the open settings view
  const noEmu = !(s.emulator && s.emulator.path);
  const why = noEmu ? 'Find NHL 19 first' : undefined;
  const shut = () => setView(null);
  const builds = (b.builds || []).map((x) => ({ value: x.id, label: x.label,
    title: x.id === 'nightly' ? "Upstream shadPS4's newest official build" : "Overtime's smooth build on Kravickas's NHL 19 fixes" }));
  return html`<${Card} title="Boost performance" className="su-boost"
      aside=${html`<${Info} title="Boost performance" sections=${BOOST_INFO}/>`}>
    <div class="card-body">
      <div class=${cls('su-state', b.tone)}>
        <span class="su-st">${b.text}</span>
      </div>
      <div class="su-state su-build">
        <span class="su-st">Build</span>
        <${Segmented} options=${builds} value=${b.build} disabled=${!b.can} onChange=${(v) => call('setup_build', v)}/>
        <${Button} small disabled=${!b.can_update} title="Download the chosen build now" onClick=${() => call('setup_build_update')}>Update<//>
        <${Button} small kind="ghost" title="The chosen build's source code (GPL-2.0)" onClick=${() => call('setup_boost_source')}>Source code<//>
      </div>
      ${b.news && html`<div class="su-news" title=${b.upstream || ''}>${b.news}</div>`}
      <div class="su-state su-res">
        <span class="su-st">Resolution</span>
        <${Segmented} options=${RESOLUTIONS} value=${b.resolution || 1080} onChange=${(v) => call('setup_resolution', v)}/>
      </div>
      <div class="su-state su-emu">
        <span class="su-st">Settings</span>
        <${Button} small disabled=${noEmu} title=${why || "shadPS4's settings for NHL 19"} onClick=${() => setView('game')}>
          ${GEAR_ICON}Game settings<//>
        <${Button} small disabled=${noEmu} title=${why || 'Controller bindings'} onClick=${() => setView('pad')}>
          ${PAD_ICON}Controllers<//>
        <${Button} small disabled=${noEmu} title=${why || 'Keyboard and mouse bindings'} onClick=${() => setView('keys')}>
          ${KEYS_ICON}Keyboard<//>
      </div>
    </div>
    ${view === 'game' && html`<${GameSettings} onClose=${shut}/>`}
    ${view === 'pad' && html`<${Controllers} onClose=${shut}/>`}
    ${view === 'keys' && html`<${Keyboard} onClose=${shut}/>`}
  <//>`;
}

// --- Online: shown only on the Multiplayer tab (it needs the `setup` slice, see multiplayer.js) ---------------------------------------------------------------------------------------------------------------
// the server address: sent on Enter or when the field is left; Escape puts the saved one back
function ServerField({ value, disabled, bad }) {
  const [text, setText] = useState(value);
  const typing = useRef(false);
  useEffect(() => { if (!typing.current) setText(value); }, [value]);
  const send = () => { if (text.trim() !== value) call('setup_set_server', text.trim()); };
  return html`<input class=${cls('field', 'su-server', bad && 'bad')} value=${text} disabled=${disabled} spellcheck="false"
    aria-label="Server address" placeholder=${value}
    onFocus=${() => { typing.current = true; }}
    onBlur=${() => { typing.current = false; send(); }}
    onInput=${(e) => setText(e.target.value)}
    onKeyDown=${(e) => {
      if (e.key === 'Enter') { e.preventDefault(); send(); }
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setText(value); }
    }}/>`;
}

// the Online lines (server address, CPU check, firewall): Multiplayer shows them in its Advanced row. One grid of
// label | content | button, so every button sits in the same column at the same width; `children` adds rows to it.
export function OnlineLines({ s, className, children }) {
  const o = s.online;
  const fw = o.firewall;
  return html`
    <div class=${cls(className, 'su-lines')}>
      <span class="field-label">Server</span>
      <${ServerField} value=${o.server} disabled=${s.busy} bad=${!!o.error}/>
      <${Button} small disabled=${s.busy || o.is_default} title=${`Back to ${o.server_default}`}
        onClick=${() => call('setup_set_server', '')}>Default<//>
      <span class=${cls('su-hint', o.error && 'bad')}>${o.error || 'Leave it as it is unless your league runs its own server.'}</span>
      ${o.cpu && html`<${CpuLine} c=${o.cpu}/>`}
      ${children}
      <span class="field-label">Firewall</span>
      <span class=${cls('su-fw', fw.tone, !fw.can_fix && 'wide')}><${Mark} tone=${fw.tone}/><span class="su-fwt">${fw.text}</span></span>
      ${fw.can_fix && html`<${Button} small disabled=${s.busy} title="Windows asks you to allow it (optional)"
        onClick=${() => call('setup_firewall')}>Allow...<//>`}
      ${fw.hint && html`<span class="su-hint">${fw.hint}</span>`}
    </div>`;
}

// Check my CPU (cpucheck.py): does this CPU's estimate math match one proven to play in step? Sending asks first.
function CpuLine({ c }) {
  const [ask, setAsk] = useState(false);
  const hint = c.error || c.note;
  return html`
    <span class="field-label">CPU</span>
    <span class="su-fw su-cpu-name" title=${c.full_name || ''}><span class="su-fwt">${c.name || 'This PC'}</span></span>
    <${Button} small disabled=${!c.can_check} title="Runs Overtime's CPU check program (downloaded the first time)"
      onClick=${() => call('setup_cpu_check')}>${c.busy ? 'Checking...' : 'Check my CPU'}<//>
    <span class=${cls('su-fw', 'su-cpu-st', c.tone, !(c.can_send || c.sending) && 'wide')} title=${c.title || ''}>
      <${Mark} tone=${c.tone}/><span class="su-fwt">${c.text}</span></span>
    ${(c.can_send || c.sending) && html`<${Button} small disabled=${!c.can_send}
      onClick=${() => setAsk(true)}>${c.sending ? 'Sending...' : 'Send result...'}<//>`}
    ${hint && html`<span class=${cls('su-hint', c.error && 'bad')} role=${c.error ? 'alert' : null}>${hint}</span>`}
    ${ask && html`<${Modal} title="Send the CPU check result?" onClose=${() => setAsk(false)}
      buttons=${html`<${Button} kind="ghost" onClick=${() => setAsk(false)}>Cancel<//>
        <${Button} kind="primary" onClick=${() => { setAsk(false); call('setup_cpu_send'); }}>Send<//>`}>
      <p class="mp-note">It sends the check's result file (what this CPU's two estimate instructions return, about
        200 KB), the CPU's name and maker, and this PC's app and emulator versions and settings (the emulator's file
        hash, AMD math, the Cross-CPU check, the game's online version) to the Overtime server. No game log and no
        account go.</p>
    <//>`}`;
}

// --- This program ---------------------------------------------------------------------------------------------------------
function ProgramCard({ s }) {
  const p = s.program;
  return html`<${Card} title="This program" aside=${`version ${p.version}`} className="su-program">
    <div class="card-body">
      <div class=${cls('su-newer', p.state.tone)}>
        <${Mark} tone=${p.state.tone}/><span class="sp">${p.state.text}</span>
        ${p.newer && html`<${Button} small kind="primary" disabled=${s.busy} onClick=${() => call('setup_check_updates_now')}>Update...<//>`}
      </div>
      <div class="row">
        <${Checkbox} on=${p.check_on_start} onChange=${(v) => call('setup_check_updates', v)}>Check for updates at start<//>
        <span class="sp"></span>
        <${Button} small disabled=${s.busy} onClick=${() => call('setup_check_updates_now')}>Check now<//>
      </div>
    </div>
  <//>`;
}

// --- 2 Which roster do you work on? -----------------------------------------------------------------------------------------
const ROSTER_INFO = [
  { head: 'Your rosters', items: ['Every roster is a save of NHL 19. The game lists up to 15 under Customize Rosters.',
    'Pick one: the Update tab, the team tabs and Save all use it.',
    'Start fresh opens the game roster or the Overtime default. Save it as a new roster to keep it.'] },
  { head: 'Good to know', items: ['Delete moves a roster to the Recycle Bin. You can take it back from there.',
    'The online roster comes from the Overtime server. It is replaced every time you sign in.',
    'Close shadPS4 before you save or delete a roster.'] },
];

function RosterRow({ r, busy }) {
  const open = () => { if (!r.open) call('rosters_open', r.id); };
  return html`<div class=${cls('su-row', r.open && 'sel', r.kind)} role="radio" aria-checked=${r.open} tabindex="0" title=${r.title}
      onClick=${open}
      onKeyDown=${(e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); open(); } }}>
    <span class="su-dot"></span>
    <div class="main">
      <div class="su-name"><span class="n">${r.name}</span>
        ${r.chips.map((c) => html`<span key=${c.text} class=${cls('chip', c.tone)}>${c.text}</span>`)}</div>
      <div class="su-meta">${r.meta}</div>
      ${r.problem && html`<div class="su-problem">${r.problem}</div>`}
    </div>
    ${r.acts && html`<div class="su-acts" onClick=${(e) => e.stopPropagation()}>
      ${r.acts.folder && html`<${Button} small onClick=${() => call('rosters_folder', r.id)}>Open folder<//>`}
      ${r.acts.delete && html`<${Button} small kind="danger" disabled=${busy || !r.can_delete} title=${r.delete_title}
        onClick=${() => call('rosters_delete', r.id)}>Delete...<//>`}
    </div>`}
  </div>`;
}

function RosterCard({ s }) {
  const r = s.rosters;
  const list = useRef(null);
  useEffect(() => {
    const el = list.current && list.current.querySelector('.su-row.sel');
    if (el) el.scrollIntoView({ block: 'nearest' });
  }, [r.open, r.rows.length]);
  return html`<${Card} n="2" title="Which roster do you work on?" grow className="su-rosters"
      aside=${html`<${Info} title="Which roster do you work on?" sections=${ROSTER_INFO}/>`}>
    <div class="card-body fill">
      ${s.running && html`<div class="small-note su-warn">shadPS4 is running. Close it before you save or delete a roster.</div>`}
      ${r.can_open && html`<div class=${cls('su-room', r.room_tone)}>
        <span class="su-count">${r.used} of ${r.max}</span><span class="su-room-text">${r.room_text}</span>
      </div>`}
      <div class="su-fresh"><span class="su-fl">Start fresh:</span>
        ${r.starts.map((x) => html`<${Button} small key=${x.id} kind=${x.open ? 'pick' : 'ghost'} title=${x.note}
          disabled=${s.busy || !r.can_open} onClick=${() => call('rosters_open', x.id)}>${x.name}<//>`)}
      </div>
      ${r.rows.length ? html`<div class="scroll" ref=${list}><div class="list su-list" role="radiogroup" aria-label="Your rosters">
          ${r.rows.map((x) => html`<${RosterRow} key=${x.id} r=${x} busy=${s.busy}/>`)}
        </div></div>` : html`<div class="empty">${r.empty}</div>`}
    </div>
  <//>`;
}

export default function Setup() {
  const s = useSlice('setup');
  if (!s) return null;
  return html`<div class=${cls('columns', 'su', s.first && 'su-first')}>
    <div class="col">
      <${LinkRow}/>
      <${WhereCard} s=${s}/>
      <${BoostCard} s=${s}/>
      <${ProgramCard} s=${s}/>
    </div>
    <div class="col">
      <${RosterCard} s=${s}/>
    </div>
  </div>`;
}
