// Setup: where shadPS4 is and its checks, which roster you work on, this program (the Online card lives on Multiplayer). Legacy's
// SetupTab (RpcsCard, RosterCard, ProgramCard) in NHL 19's look. The picture packs moved to Game patch's Photos, logos
// pack card (v0.10.0); the slice keeps `downloads` for tools.
// Slice `setup`; calls setup_*, rosters_* (docs/ui/setup.md).
import { html, cls, useState, useEffect, useRef } from '../lib.js';
import { useSlice } from '../store.js';
import { call } from '../bridge.js';
import { Card, Button, PathText, Checkbox, Info, Modal, Segmented, Select, Switch, Tag } from '../ui.js';
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


// --- 1 Where is NHL 19? ---------------------------------------------------------------------------------------------------
const WHERE_INFO = [
  { head: 'What to pick', items: ['Press Find game and pick NHL 19\'s eboot.bin, or its PKG files to install the game.',
    'Nothing else to install: Overtime gets the renderer chosen under Boost performance by itself.',
    'Using your own renderer (shadPS4)? Folders, Renderer, Change... picks shadPS4QtLauncher.exe or shadPS4.exe.',
    'The program finds and handles the rest by itself: the renderer and your roster saves.'] },
  { head: 'Installing from PKG', items: ['Pick the game PKG first, then the update 1.60 PKG. One at a time.',
    'The game goes into a new folder next to its PKG, the update into a new folder beside the game. Nothing is overwritten.',
    'It needs free space on that drive about the size of the PKG.',
    'The PKG tool is shadPS4Plus\'s pkg_extractor (GPL-2.0), downloaded from its GitHub page the first time: github.com/AzaharPlus/shadPS4Plus.'] },
  { head: 'Folders', items: ['Open it for the checks (below) and where the renderer, NHL 19, the renderer\'s data and your saves are.',
    'Change... picks one yourself (your own shadPS4, another drive). The program never changes a folder you set.',
    'Auto lets the program find it again.',
    'Downloads and cache: the packs downloaded and the jerseys made on this PC (several GB with every pack). Change... moves '
      + 'them to a folder you pick, e.g. on the drive NHL 19 is on; Auto moves them back.'] },
  { head: 'The checks', items: ['Renderer: found, and its version.', 'NHL 19: the game (CUSA11126 or CUSA11116) with update 1.60.',
    'ShadNet: you are signed in to the online service.', 'Network: the Overtime server answers.',
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
      <div class="row su-pathrow">
        <div class="su-paths">
          ${(s.folders || []).filter((f) => f.key === 'game').map((f) => html`<div key=${f.key} class="su-path">
            <span class="su-pl">Game</span><${PathText} path=${f.path} unset="Not found"/></div>`)}
        </div>
        <${Button} kind=${s.emulator.path ? 'ghost' : 'primary'} disabled=${busy} onClick=${() => findGame(s.emulator.path)}
          title="Pick NHL 19's eboot.bin or its PKG">Find game...<//>
      </div>
      <${Folders} folders=${s.folders} checks=${s.checks} checking=${s.checking} busy=${busy}/>
      <div class=${cls('su-state', st.tone, 'su-checkrow')}>
        ${st.tone === 'good' ? html`<span class="su-chip" title="The checks are under Folders"><${Mark} tone="good"/>Ready to play</span>`
          : html`<span class="su-st">${st.text}</span>`}
        ${s.emulator.path && html`<${Button} small disabled=${busy} onClick=${() => call('setup_refresh')}>Check again<//>`}
      </div>
    </div>
  <//>`;
}

// --- Boost performance: the shadPS4 build the green Play NHL 19 button starts, Overtime Native v2 / v1 or Kravickas ----------
const BOOST_INFO = [
  { head: 'What it does', items: ['Picks the shadPS4 build that the green Play NHL 19 button starts.',
    "Overtime Native v2 (the default): v1 plus six speed changes: GPU readbacks without stalls, faster texture lookups, game threads at higher priority, a quieter log, shaders built in the background and draws recorded on a second thread. New, so tell us when something looks wrong.",
    "Overtime Native v1: Overtime's own build of shadPS4 for NHL 19, with less RAM reserved, lighter controller polling, steadier frames and the fix for the \"Out of order flip IRQ\" crash.",
    'Both Overtime Native builds come with Overtime releases.',
    "Kravickas: Kravickas's NHL 19 build, with his fix for the same crash: the newest one his GitHub publishes (branch NHL19-Build). Get newest gets it now.",
    'Play downloads the chosen build the first time, and again when a newer one is published.',
    'Saves, patch and ShadNet login stay the same with either build.'] },
  { head: 'Online', items: ['Multiplayer lobbies play on Overtime Native v2 for everyone, whichever build is chosen here.',
    'Open matchmaking pairs you with players on the same build.'] },
  { head: 'Source code (GPL-2.0)', items: ['Overtime Native v2: github.com/MatusRiedl/shadPS4, branch overtime-native-v2.',
    'Overtime Native v1: github.com/MatusRiedl/shadPS4, branch overtime-nightly.',
    'Kravickas: Source code, beside the build choice on the card.'] },
  { head: 'Your own shadPS4', items: ['It stays where it is, untouched.',
    'A portable shadPS4 with its own "user" folder keeps playing itself: the builds would not find its saves.'] },
  { head: 'Resolution', items: ["1080p is the game's own. 1440p renders at 2560x1440 (Kravickas's patch): sharper, needs a stronger GPU.", "720p renders at 1280x720 (Kravickas's patch): softer, for a weaker GPU.", '1440p also sets Additional DMem to 3500 MB; 720p and 1080p put your own value back.', 'Works with either build. Takes effect at the next start of NHL 19.'] },
  { head: 'Frame rate', items: ['60, 120 or Unlocked (the default): how fast NHL 19 runs (shadPS4\'s vblank).',
    'Online, players on different frame rates play together fine. NHL 19 uses a new choice from its next start.'] },
  { head: 'Also replays and cutscenes', items: ["On (the default): Kravickas's patch shows replays, celebrations, cutscenes and menus at your frame rate too.",
    "Off: they keep the game's own pace.",
    'Each player picks their own, online too. NHL 19 uses it from its next start.'] },
];
const RESOLUTIONS = [
  { value: 720, label: '720p', title: 'Renders at 1280x720 (Kravickas patch), for a weaker GPU' },
  { value: 1080, label: '1080p', title: "The game's own resolution" },
  { value: 1440, label: '1440p', title: 'Renders at 2560x1440 (Kravickas patch), needs a stronger GPU' },
];

const FRAMERATES = [
  { value: 60, label: '60 fps', title: "The console's frame rate" },
  { value: 120, label: '120 fps', title: 'Capped at 120: a late frame waits for the next tick' },
  { value: 9999, label: 'Unlocked', title: 'As fast as your PC runs it, each frame shown when it is done (the default)' },
];

function BoostCard({ s }) {
  const b = s.boost;
  const [view, setView] = useState(null);     // 'game' | 'pad' | 'keys': the open settings view
  const noEmu = !(s.emulator && s.emulator.path);
  const why = noEmu ? 'Find NHL 19 first' : undefined;
  const shut = () => setView(null);
  const BUILD_TITLES = { native2: 'Overtime Native v1 plus six speed changes (the default, and the lobby build)',
    nightly: "Overtime's own build of shadPS4 for NHL 19 (the default until v2)", kravickas: "Kravickas's NHL 19 build" };
  const builds = (b.builds || []).map((x) => ({ value: x.id, label: x.label, title: BUILD_TITLES[x.id] || x.label }));
  return html`<${Card} title="Boost performance" className="su-boost"
      aside=${html`<${Info} title="Boost performance" sections=${BOOST_INFO}/>`}>
    <div class="card-body">
      ${b.tone !== 'good' && html`<div class=${cls('su-state', b.tone)}>
        <span class="su-st">${b.text}</span>
      </div>`}
      <div class="su-state su-build">
        <span class="su-st">Build</span>
        <${Select} className="su-buildpick" options=${builds} value=${b.build} disabled=${!b.can} title=${BUILD_TITLES[b.build] || ''}
          onChange=${(v) => call('setup_build', v)}/>
        <span class="su-bacts"><span class="su-bal">Kravickas build:</span>
        <${Button} small kind="link" disabled=${!b.can_update}
          title=${b.updatable ? "Download Kravickas's newest build from his GitHub now" : 'For the Kravickas build. Overtime Native v1 and v2 come with Overtime releases: Play NHL 19 gets a new one by itself'}
          onClick=${() => call('setup_build_update')}>Get newest<//>
        ${(b.builds || []).filter((x) => x.updatable).map((x) => html`<${Button} small kind="link" title=${`The ${x.label} build's source code (GPL-2.0)`}
          onClick=${() => call('setup_boost_source', x.id)}>Source code ↗<//>`)}</span>
      </div>
      ${b.news && html`<div class="su-news" title=${b.upstream || ''}>${b.news}</div>`}
      <div class="su-state su-res">
        <span class="su-st">Resolution</span>
        <${Segmented} options=${RESOLUTIONS} value=${b.resolution || 1080} onChange=${(v) => call('setup_resolution', v)}/>
      </div>
      <div class="su-state su-res">
        <span class="su-st">Frame rate</span>
        <${Segmented} options=${FRAMERATES} value=${b.framerate} disabled=${noEmu}
          onChange=${(v) => call('setup_framerate', v)}/>
        <span class="su-every" title="On (the default): replays, celebrations, cutscenes and menus follow the frame rate too. Off: they keep the game's own pace.">
          <${Switch} on=${!!b.everywhere} onChange=${(on) => call('setup_everywhere', on)}>Also replays and cutscenes<//>
        </span>
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
      <div class="row">
        <${Checkbox} on=${p.check_on_start} onChange=${(v) => call('setup_check_updates', v)}>Check for updates at start<//>
        <span class="sp"></span>
        <span class=${cls('su-newest', p.state.tone)}>${p.state.tone === 'good' ? 'Up to date' : p.state.text}</span>
        <${Button} small disabled=${s.busy} onClick=${() => call('setup_check_updates_now')}>Check now<//>
      </div>
    </div>
  <//>`;
}

// --- 2 Which roster do you work on? -----------------------------------------------------------------------------------------
const ROSTER_INFO = [
  { head: 'Your rosters', items: ['Every roster is a save of NHL 19. The game lists up to 15 under Customize Rosters.',
    'Pick one: the roster update on the Patch tab, the team tabs and Save all use it.',
    'Start fresh opens the game roster or the Overtime default. Save it as a new roster to keep it.'] },
  { head: 'Good to know', items: ['Delete moves a roster to the Recycle Bin. You can take it back from there.',
    'The online roster comes from the Overtime server. It is replaced every time you sign in.',
    'Close NHL 19 before you save or delete a roster.'] },
];

function RosterRow({ r, busy }) {
  const open = () => { if (!r.open) call('rosters_open', r.id); };
  return html`<div class=${cls('su-row', r.open && 'sel', r.kind)} role="radio" aria-checked=${r.open} tabindex="0" title=${r.title}
      onClick=${open}
      onKeyDown=${(e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); open(); } }}>
    <span class="su-dot"></span>
    <div class="main">
      <div class="su-name"><span class="n">${r.name}</span>
        ${(r.chips.length ? r.chips : [{ text: / in the game/.test(r.meta) ? 'In game' : 'Save', tone: 'game' }]).map((c) => html`<span key=${c.text} class=${cls('chip', c.tone)}>${c.text}</span>`)}</div>
      <div class="su-meta">${r.meta.replace(/ · Saved in the game\./, '')}</div>
      ${r.problem && html`<div class="su-problem">${r.problem}</div>`}
    </div>
    ${r.acts && html`<div class="su-acts" onClick=${(e) => e.stopPropagation()}>
      ${r.acts.folder && html`<${Button} small onClick=${() => call('rosters_folder', r.id)}>Open folder<//>`}
      ${r.acts.delete && html`<${Button} small kind="danger-quiet" disabled=${busy || !r.can_delete} title=${r.delete_title}
        onClick=${() => call('rosters_delete', r.id)}><svg class="bin-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>Delete<//>`}
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
      ${s.running && html`<div class="small-note su-warn">NHL 19 is running. Close it before you save or delete a roster.</div>`}
      ${r.can_open && html`<div class=${cls('su-room', r.room_tone)}>
        <span class="su-count">${r.used} used</span><span class="su-room-text">${r.max - r.used} free of ${r.max} save slots</span>
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
      <${WhereCard} s=${s}/>
      <${BoostCard} s=${s}/>
      <${ProgramCard} s=${s}/>
    </div>
    <div class="col">
      <${RosterCard} s=${s}/>
    </div>
  </div>`;
}
