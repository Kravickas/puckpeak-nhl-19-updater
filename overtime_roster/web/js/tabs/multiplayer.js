// Multiplayer: play one friend. Three columns (owner's mockup, v0.70.9): 1 you and the pre-flight checks; 2 the lobby
// (host / join tiles, the public list; then the two players, Ready, the rules and the game steps); 3 your rating and the
// history. Everything on the tab is the `multiplayer` slice (the Advanced row is Setup's Online lines); the lobby's secret
// never reaches the page. docs/ui/multiplayer.md.
import { html, cls, useState } from '../lib.js';
import { useSlice } from '../store.js';
import { call } from '../bridge.js';
import { Button, Card, Modal, Segmented, Select, Tag, TextField, Toggle } from '../ui.js';
import { OnlineLines } from './setup.js';

export const tip = 'Make a lobby, give your friend the code, and both press Ready: the game starts by itself.';

const STATE_CHIP = {
  open: { tone: 'info', text: 'waiting for a friend' },
  full: { tone: 'info', text: 'full: press Ready' },
  launching: { tone: 'good', text: 'both ready' },
  matched: { tone: 'good', text: 'matched' },
};
const STAGE_TEXT = { lobby: 'game starting', setup: 'Game Setup', searching: 'searching', matched: 'matched' };
const GO_TEXT = { setup: 'Setup', patch: 'Game patch', update: 'Update' };
const GAME_TEXT = { title: 'NHL 19 release (title id)', data: 'game data', layers: 'Game patch switches', emu: 'shadPS4 build revision',
  timing: 'shadPS4 vblank / PS4 Pro mode' };

function copy(text) {
  try {
    if (navigator.clipboard) return navigator.clipboard.writeText(text);
  } catch (err) { /* the next line tries again */ }
  const area = document.createElement('textarea');
  area.value = text;
  document.body.appendChild(area);
  area.select();
  try { document.execCommand('copy'); } catch (err) { /* nothing more to try */ }
  area.remove();
  return null;
}

function Fact({ label, tone, sub, children, action }) {
  return html`<div class=${cls('mp-fact', tone)}>
    <span class="mp-fact-label caps">${label}</span>
    <span class="mp-fact-value">${children}${sub && html`<span class="mp-fact-sub">${sub}</span>`}</span>
    ${action}
  </div>`;
}

function Name({ you }) {
  const [edit, setEdit] = useState(false);
  if (edit || !you.name) {
    return html`<div class="mp-fact"><span class="mp-fact-label caps">Name</span>
      <${TextField} value=${you.name} placeholder="Your name" onChange=${(v) => call('mp_set_name', v)}
        onEnter=${() => setEdit(false)}/>
      ${you.name && html`<${Button} small kind="ghost" onClick=${() => setEdit(false)}>Done<//>`}</div>`;
  }
  return html`<${Fact} label="Name" action=${html`<${Button} small kind="ghost" onClick=${() => setEdit(true)}>Change<//>`}>
    ${you.name}<//>`;
}

const FROM = { log: "from the game's sign-in", typed: 'typed by you', shadnet: 'checked with ShadNet' };

// ShadNet sign-in: the app signs in to ShadNet with the player's own Online ID and password (that gives the account
// id at once, no NHL 19 run) and writes them into shadPS4, keeping a copy of the old file. "New account" makes one
// through the ShadNet site's sign-up and signs in with it.
function SignIn({ sn, onDone }) {
  const [make, setMake] = useState(false);
  const [npid, setNpid] = useState(sn.npid || '');
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [mail, setMail] = useState('');
  const [busy, setBusy] = useState(false);
  const id = npid.trim();
  const idOk = /^[A-Za-z0-9_-]{3,16}$/.test(id);
  const ok = make ? idOk && pw.length >= 6 && pw === pw2 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(mail.trim())
    : idOk && pw.length > 0;
  const go = async () => {
    if (!ok || busy) return;
    setBusy(true);
    try {
      const r = make ? await call('mp_shadnet_create', id, mail.trim(), pw) : await call('mp_shadnet_signin', id, pw);
      if (r && r.ok) { setPw(''); setPw2(''); onDone && onDone(); }
    } finally { setBusy(false); }
  };
  const enter = (e) => { if (e.key === 'Enter') go(); };
  const hint = make && pw2 && pw !== pw2 ? 'The passwords differ.' : make && pw && pw.length < 6 ? 'At least 6 characters.' : '';
  return html`<div class="mp-signin">
    <div class="mp-note">Each player needs their <b>own</b> ShadNet account. Never share one: two players on one account
      cannot play each other.</div>
    <div class="mp-row">
      <input class="field" placeholder="Online ID" value=${npid} spellcheck="false" autocomplete="username"
        aria-label="ShadNet Online ID" onInput=${(e) => setNpid(e.target.value)} onKeyDown=${enter}/>
      ${make && html`<input class="field" type="email" placeholder="E-mail" value=${mail} autocomplete="email"
        aria-label="E-mail" onInput=${(e) => setMail(e.target.value)} onKeyDown=${enter}/>`}
    </div>
    <div class="mp-row">
      <input class="field" type="password" placeholder="Password" value=${pw}
        autocomplete=${make ? 'new-password' : 'current-password'} aria-label="ShadNet password"
        onInput=${(e) => setPw(e.target.value)} onKeyDown=${enter}/>
      ${make && html`<input class="field" type="password" placeholder="Password again" value=${pw2}
        autocomplete="new-password" aria-label="Password again" onInput=${(e) => setPw2(e.target.value)} onKeyDown=${enter}/>`}
      <${Button} small disabled=${!ok || busy} onClick=${go}>${busy ? '...' : make ? 'Create' : 'Sign in'}<//>
    </div>
    ${hint && html`<div class="mp-note">${hint}</div>`}
    <div class="mp-note">${make
      ? html`Already have one? <a href="#" onClick=${(e) => { e.preventDefault(); setMake(false); }}>Sign in</a>.
          3 to 16 letters, digits, - or _. Free.`
      : html`No account yet? <a href="#" onClick=${(e) => { e.preventDefault(); setMake(true); setNpid(''); setPw(''); }}>Create one here</a>
          (free). Capitals count.`}
      <a href="#" class="mp-quiet" onClick=${(e) => { e.preventDefault(); call('mp_shadnet_register'); }}>ShadNet site</a></div>
  </div>`;
}

// --- 1 You and pre-flight: who you are, the checks, what the app does when the game starts, Advanced (Setup's Online) ---
function Mark({ tone }) {
  return html`<span class=${cls('mp-chk', tone)} aria-hidden="true">${tone === 'good'
    ? html`<svg width="12" height="12" viewBox="0 0 12 12"><path d="M2 6.4l2.6 2.6L10 3.5" fill="none" stroke="currentColor" stroke-width="2"/></svg>`
    : tone === 'bad'
      ? html`<svg width="12" height="12" viewBox="0 0 12 12"><path d="M3 3l6 6M9 3l-6 6" fill="none" stroke="currentColor" stroke-width="2"/></svg>`
      : '!'}</span>`;
}

// a small arrow pointing right; CSS turns it for open / closed
function Chevron() {
  return html`<svg class="mp-chev" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
    <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>`;
}

// the ShadNet account the server knows you by: a letter tile, the Online ID, the account number and where it came from
function Identity({ you }) {
  const [edit, setEdit] = useState(false);
  const sn = you.shadnet || {};
  const ok = !!you.ext && !edit;
  const name = sn.npid || you.name || (you.ext ? `#${you.ext}` : '');
  const sub = ok ? `ShadNet #${you.ext} · ${FROM[you.ext_from] || FROM.log}`
    : sn.npid ? 'Not signed in to ShadNet yet' : 'No ShadNet account yet';
  return html`<div class="mp-id">
    <div class="mp-id-head">
      <span class=${cls('mp-avatar', !ok && 'off')}>${(name.replace('#', '') || '?').charAt(0).toUpperCase()}</span>
      <div class="mp-id-main">
        <div class="mp-id-name">${name || 'Player'}</div>
        <div class=${cls('mp-id-sub', !ok && 'warn')}>${sub}</div>
      </div>
      ${ok ? html`<${Button} small onClick=${() => setEdit(true)}>Change<//>`
        : edit ? html`<${Button} small kind="ghost" onClick=${() => setEdit(false)}>Cancel<//>`
          : html`<${Button} small kind="ghost" onClick=${() => call('mp_refresh')}>Check again<//>`}
    </div>
    ${!ok && !edit && you.ext_why ? html`<div class="mp-note">${you.ext_why}</div>` : null}
    ${!ok && sn.ready ? html`<${SignIn} sn=${sn} onDone=${() => setEdit(false)}/>` : null}
  </div>`;
}

function Check({ c, action }) {
  return html`<div class=${cls('mp-check', c.tone)}>
    <${Mark} tone=${c.tone}/>
    <div class="mp-check-main"><div class="mp-check-label caps">${c.label}</div><div class="mp-check-value">${c.text}</div></div>
    ${action}
  </div>`;
}

// the controller's checks (roster, patch, server), one row each with what fixes it. No firewall row since 0.83.0:
// matches go through the Overtime relay, so the rule is optional (Advanced).
function checkRows(s, go) {
  return s.checks.map((c) => ({ ...c, action: c.go
    ? html`<${Button} small kind=${c.tone === 'bad' ? 'primary' : 'ghost'} onClick=${() => go && go(c.go)}>${GO_TEXT[c.go] || 'Open'}<//>`
    : html`<${Tag} tone=${c.tone}>${c.tone === 'good' ? (c.key === 'server' ? 'reachable' : 'ok') : 'check'}<//>` }));
}

function Option({ on, title, sub, onChange }) {
  return html`<div class="mp-opt">
    <${Toggle} on=${on} label=${title} onChange=${onChange}/>
    <div class="mp-opt-text"><div class="mp-opt-t">${title}</div><div class="mp-opt-d">${sub}</div></div>
  </div>`;
}

// the one-time question after the update: crash and early-end reports, yes or no (remembered either way)
function AskReports() {
  return html`<div class="mp-notice"><b>Send a report when NHL 19 crashes or a match ends early?</b>
    <div class="mp-row"><${Button} small kind="primary" onClick=${() => call('mp_set_reports', true)}>Yes<//>
      <${Button} small onClick=${() => call('mp_set_reports', false)}>No<//></div></div>`;
}

// the opt-in reports (crashreport.py): the automatic switch, and a report sent now after a confirmation. Rows of the
// Advanced grid (OnlineLines), laid out like the CPU line: label | what the button does | button, the switch under it.
function Reports({ r }) {
  const [ask, setAsk] = useState(false);
  const busy = !!r.busy;
  return html`
    <span class="field-label">Reports</span>
    <span class="su-fw"><span class="su-fwt">The game's log, now</span></span>
    <${Button} small disabled=${busy} onClick=${() => setAsk(true)}>${busy ? 'Sending...' : 'Send a report'}<//>
    <${Option} on=${r.on} title="Send reports by itself"
      sub="After a crash, or a match that ended early, send the game's log to the Overtime server. Off unless you turn it on."
      onChange=${(v) => call('mp_set_reports', v)}/>
    ${r.note && html`<span class="mp-note su-row-note">${r.note}</span>`}
    ${r.error && html`<span class="mp-note bad su-row-note" role="alert">${r.error}</span>`}
    ${ask && html`<${Modal} title="Send a report now?" onClose=${() => setAsk(false)}
      buttons=${html`<${Button} kind="ghost" onClick=${() => setAsk(false)}>Cancel<//>
        <${Button} kind="primary" onClick=${() => { setAsk(false); call('mp_send_report'); }}>Send<//>`}>
      <p class="mp-note">It sends the game's log (scrubbed, see What the Overtime server keeps below), this PC's app and
        emulator versions and CPU, and your ShadNet account number. Only the log and the details above go; nothing else.</p>
    <//>`}`;
}

function Advanced({ setup, reports }) {
  const [open, setOpen] = useState(false);
  return html`<div class=${cls('mp-adv', open && 'open')}>
    <button type="button" class="mp-adv-head" aria-expanded=${open} onClick=${() => setOpen(!open)}>
      <span class="mp-adv-main"><span class="mp-lbl caps">Advanced</span><span class="mp-adv-d">Server address, CPU check, reports, firewall (optional), what the server keeps</span></span>
      <${Chevron}/>
    </button>
    ${open && html`<div class="mp-adv-body"><${OnlineLines} s=${setup}><${Reports} r=${reports}/><//><${Privacy}/></div>`}
  </div>`;
}

function You({ s, setup, go }) {
  const lobbyOpen = !!s.lobby;
  const rows = checkRows(s, go);
  const fix = rows.filter((c) => c.tone === 'bad').length;
  const hud = s.you.hud;
  return html`<${Card} n=${1} title="You and pre-flight" className="mp-card-fill">
    <div class="mp-body mp-fill">
      ${!s.you.shadnet?.npid && !s.you.ext && html`<${Name} you=${s.you}/>`}
      <${Identity} you=${s.you}/>
      ${s.reports && !s.reports.asked && html`<${AskReports}/>`}
      ${fix > 0 && html`<div class="mp-notice bad"><b>${fix} ${fix === 1 ? 'thing' : 'things'} to fix</b>
        <span>before a lobby can start the game.</span></div>`}
      <div class="mp-checks">${rows.map((c) => html`<${Check} key=${c.key} c=${c} action=${c.action}/>`)}</div>
      ${s.error && html`<div class="mp-note bad" role="alert">${s.error}</div>`}
      ${s.error && !lobbyOpen && html`<div class="mp-row"><${Button} small onClick=${() => call('mp_refresh')}>Check again<//></div>`}
      <div class="mp-hl"></div>
      <div class="mp-lbl caps">When the game starts</div>
      <${Option} on=${s.you.press} title="App skips the title screen" sub="Presses ✕ for you, twice."
        onChange=${(v) => call('mp_set_press', v)}/>
      ${hud && html`<${Option} on=${hud.on} title="Chat and results in game"
        sub=${hud.available ? 'Toasts and the result card, only over the game window.' : 'Windows only.'}
        onChange=${(v) => call('mp_set_hud', v)}/>`}
      ${hud && hud.link !== undefined && html`<${Option} on=${hud.link} title="Connection in the corner"
        sub=${hud.available ? 'Ping and packet loss, top right of the game window, while a match runs.' : 'Windows only.'}
        onChange=${(v) => call('mp_set_link', v)}/>`}
      <div class="mp-spacer"></div>
      ${setup && setup.online && html`<${Advanced} setup=${setup} reports=${s.reports || {}}/>`}
    </div>
  </${Card}>`;
}

// --- 2 Lobby, none open yet: a host tile and a join tile, the public list, how a match comes about ---------------------
const HOWTO = [
  ['Create or join', 'One lobby, two players.'],
  ['Both press Ready', 'The host sets the match rules first.'],
  ['The app starts NHL 19', 'It searches for your friend by itself.'],
];

function HowTo() {
  return html`<div class="mp-howto">${HOWTO.map(([t, d], i) => html`<div class="mp-howto-step" key=${i}>
    <span class="mp-ftag">${i + 1}</span><div><b>${t}</b><div class="mp-howto-d">${d}</div></div></div>`)}</div>`;
}

function Pick({ s, go }) {
  const [code, setCode] = useState('');
  const [pub, setPub] = useState(true);   // public by default (owner, 2026-11-06)
  const idle = !s.busy;
  const patch = s.checks.find((c) => c.key === 'patch');
  const join = () => { if (code) call('mp_join', code); };
  return html`<div class="mp-body mp-fill mp-pick">
    ${patch && patch.tone === 'bad' && html`<div class="mp-notice caution">
      <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true" class="mp-warn"><path d="M10 2l9 16H1z" fill="none" stroke="currentColor" stroke-width="2"/>
        <path d="M10 8v5M10 15v1" stroke="currentColor" stroke-width="2"/></svg>
      <span class="sp"><b>${patch.go === 'setup' ? 'Find NHL 19 in Setup first.' : 'Patch the game first.'}</b>${' '}Patch: ${patch.text},
        so a lobby cannot start NHL 19.</span>
      ${patch.go && html`<${Button} small kind="caution" onClick=${() => go && go(patch.go)}>Open ${GO_TEXT[patch.go] || 'it'}<//>`}
    </div>`}
    <div class="mp-tiles">
      <div class="mp-tile host">
        <div class="mp-tile-t caps">Host a lobby</div>
        <div class="mp-tile-d">You get a short code to send to a friend, or your lobby shows in the public list.</div>
        <${Toggle} on=${pub} onChange=${setPub}>Show it in the public list<//>
        <${Button} kind="gold" big block disabled=${!idle} onClick=${() => call('mp_create', pub)}>Create lobby<//>
      </div>
      <div class="mp-tile join">
        <div class="mp-tile-t caps">Join a friend</div>
        <div class="mp-tile-d">Type the code your friend sent you.</div>
        <input class="field mp-code-in" placeholder="CODE" value=${code} maxlength="12" spellcheck="false" aria-label="Lobby code"
          onInput=${(e) => setCode(e.target.value.toUpperCase())} onKeyDown=${(e) => { if (e.key === 'Enter') join(); }}/>
        <${Button} big block kind=${code ? 'primary' : 'plain'} disabled=${!idle || !code} onClick=${join}>Join with a code<//>
      </div>
    </div>
    <div class="mp-public">
      <div class="mp-row"><span class="mp-lbl caps">Public lobbies</span><span class="sp"></span>
        <${Button} small kind="ghost" disabled=${!idle} onClick=${() => call('mp_refresh')}>Refresh<//></div>
      ${s.lobbies.length
        ? html`<div class="mp-list">${s.lobbies.map((l) => html`<div class="mp-lobby-row" key=${l.code}>
            <span class="who">${l.host}</span><span class="age">${l.age}</span>
            <${Button} small disabled=${!idle} onClick=${() => call('mp_join', l.code)}>Join<//></div>`)}</div>`
        : html`<div class="mp-public-empty"><div><div class="mp-public-t">No public lobbies right now</div>
            <div class="mp-public-d">Make one, or ask a friend for a code.</div></div></div>`}
    </div>
    <${HowTo}/>
  </div>`;
}

function Player({ p, launching }) {
  const roster = p.roster === 'ok' ? html`<${Tag} tone="good">roster ok<//>`
    : p.roster === 'mismatch' ? html`<${Tag} tone="bad">roster differs<//>` : null;
  // live 2026-11-08: installs that differ (title id, game data, data patch layers) may desync; the server only warns
  const game = p.game && p.game.length
    ? html`<span title=${'Not the same as the other game: ' + p.game.map((k) => GAME_TEXT[k] || k).join(', ')
        + '. This may end the match early. Compare Setup on both PCs.'}><${Tag} tone="caution">game differs<//></span>` : null;
  return html`<div class=${cls('mp-player', p.ready && 'ready')}>
    <span class="mp-player-name">${p.name}${p.you && html`<span class="you caps">you</span>`}</span>
    <div class="mp-marks">
      ${launching
        ? html`<${Tag} tone="info">${STAGE_TEXT[p.stage] || p.stage}<//>`
        : html`<${Tag} tone=${p.ready ? 'good' : 'caution'}>${p.ready ? 'ready' : 'not ready'}<//>`}
      ${roster}
      ${game}
    </div>
  </div>`;
}

const HOTKEY_HINT = 'Ctrl+Shift+F1 to F6 sends a phrase while you play';

// lobby chat: the last lines, a box, and the quick phrases; the same lines show over the game when the HUD is on
function Chat({ chat, hud }) {
  const [text, setText] = useState('');
  const send = (t) => { const v = t.trim(); if (v) call('mp_say', v); };
  const sendBox = () => { send(text); setText(''); };
  const phrases = (hud && hud.phrases) || [];
  return html`<div class="mp-chat">
    <div class="caps mp-sub">Chat</div>
    <div class="mp-chat-log" role="log" aria-live="polite">
      ${chat.length ? chat.map((c) => html`<div key=${c.n} class=${cls('mp-chat-line', c.mine && 'mine')}>
          <b>${c.mine ? 'You' : c.name}</b><span>${c.text}</span></div>`)
        : html`<div class="mp-chat-empty">Say hi. Lines are not saved: they go when the lobby closes.</div>`}
    </div>
    <div class="mp-chat-in">
      <input class="field" placeholder="Message" maxlength="140" value=${text} spellcheck="false"
        onInput=${(e) => setText(e.target.value)} onKeyDown=${(e) => { if (e.key === 'Enter') sendBox(); }}/>
      <${Button} small disabled=${!text.trim()} onClick=${sendBox}>Send<//>
    </div>
    ${phrases.length > 0 && html`<div class="mp-chat-quick">${phrases.map((p, i) => html`<button key=${i} type="button"
        class="mp-chat-chip" title=${`Ctrl+Shift+F${i + 1}`} onClick=${() => send(p)}>${p}</button>`)}</div>`}
    ${hud && hud.on && hud.available && html`<div class="mp-note">${HOTKEY_HINT}.</div>`}
  </div>`;
}

function Lobby({ s }) {
  const l = s.lobby;
  const launching = l.state === 'launching' || l.state === 'matched';
  const chip = STATE_CHIP[l.state] || { tone: 'info', text: l.state };
  const differ = l.waiting && /ROSTERCRC/.test(l.waiting);
  return html`<${Card} n=${2} title=${launching ? `Lobby ${l.code}` : 'Lobby'} className="mp-stage"
      aside=${html`<${Tag} tone=${chip.tone}>${chip.text}<//>${l.waiting && html` <${Tag} tone="caution">${l.waiting}<//>`}`}>
    <div class="mp-body">
      ${!launching && html`<div class="mp-code"><span class="mp-code-big">${l.code}</span>
        <${Button} small onClick=${() => copy(l.code)}>Copy<//><span class="sp"></span></div>`}
      <div class="mp-players">
        ${l.players.map((p) => html`<${Player} key=${p.name + p.you} p=${p} launching=${launching}/>`)}
        ${l.players.length < 2 && html`<div class="mp-player empty">Waiting for a friend</div>`}
      </div>
      ${differ && html`<div class="mp-note warn">You and ${l.partner || 'your friend'} are not on the same roster: press Update
        on both PCs, then launch again.</div>`}
      ${!launching && html`<div class="mp-row">
        ${l.state === 'open' && html`<${Button} kind="gold" big disabled>Waiting for a friend<//>`}
        ${l.state === 'full' && !l.me_ready && html`<${Button} kind="gold" big disabled=${!!s.busy}
          onClick=${() => call('mp_ready', true)}>${s.prep ? 'Getting ready...' : 'Ready'}<//>`}
        ${l.state === 'full' && l.me_ready && html`<${Button} kind="gold" big disabled>Waiting for ${l.partner}<//>
          <${Button} small kind="ghost" onClick=${() => call('mp_ready', false)}>Not ready<//>`}
        <span class="sp"></span>
        <${Button} small kind="ghost" onClick=${() => call('mp_leave')}>Leave<//>
      </div>`}
      ${s.prep && html`<div class="mp-note">${s.prep}</div>`}
      ${!launching && l.state === 'open' && html`<div class="mp-note">Give your friend the code. Both press Ready, then the game starts by itself.</div>`}
      ${launching && html`<div class="mp-row"><span class="sp"></span><${Button} small kind="ghost" onClick=${() => call('mp_leave')}>Leave<//></div>`}
      ${l.players.length > 1 && l.chat && html`<${Chat} chat=${l.chat} hud=${s.you.hud}/>`}
    </div>
  </${Card}>`;
}

// the match rules: the host picks them before Ready, the partner sees them; both games then play these
const ROSTER_OPTIONS = [
  { value: 'server', label: 'Server roster' },
  { value: 'host', label: "Host's own roster" },
];

// whose roster the match plays on: the server's online roster, or the host's own (its app uploads it at Ready and the
// guest's game downloads it, as a shared roster in the PS3 legacy app)
// one compact tile among the rules; its note (host's own roster) goes under the grid
function RosterRule({ roster }) {
  const own = roster.mode === 'host';
  const picked = ROSTER_OPTIONS.find((o) => o.value === roster.mode);
  return html`<label class=${cls('mp-rule', own && 'changed')}>
    <span class="mp-rule-label caps">Roster</span>
    ${roster.edit
      ? html`<${Select} value=${roster.mode} options=${ROSTER_OPTIONS} onChange=${(v) => call('mp_roster_mode', v)}/>`
      : html`<span class="mp-rule-value">${picked ? picked.label : roster.mode}</span>`}
  </label>`;
}

function RosterNote({ roster, host, hostName }) {
  if (roster.mode !== 'host') return null;
  return host
    ? html`<div class="mp-note">Your open roster (with your edits and lines; none open: the one Patch put on your game) is sent
        when you press Ready. Both games download it.</div>`
    : html`<div class="mp-note">${hostName || 'The host'} plays their own roster.
        ${roster.uploaded ? 'Your game downloads it when you press PLAY.' : 'It is sent when they press Ready.'}</div>`;
}

// the game the lobby plays: Online Versus, Shootout or Threes (the host picks; the others grey out the rules they have not)
const MODE_OPTIONS = [
  { value: 'versus', label: 'VERSUS' },
  { value: 'shootout', label: 'SHOOTOUT' },
  { value: 'threes', label: 'THREES' },
];

function ModePick({ mode, pick }) {
  return html`<div class="mp-rule mp-mode-pick">
    <span class="mp-rule-label caps">Game</span>
    <${Segmented} options=${MODE_OPTIONS} value=${mode} disabled=${!pick.edit} onChange=${(v) => call('mp_set_mode', v)}/>
  </div>`;
}

function Rules({ rules, host, hostName, roster, mode, modePick }) {
  const edit = rules.can_edit;
  return html`<${Card} n=${3} title="Match rules"
      aside=${html`<${Tag} tone=${rules.is_default ? 'info' : 'accent'}>${rules.summary}<//>`}>
    <div class="mp-body mp-rules-body">
      ${modePick && html`<${ModePick} mode=${mode} pick=${modePick}/>`}
      ${mode === 'shootout' && html`<div class="mp-note">Shootout: 1 against 1 penalty shots; the greyed rules do not apply. Counts in the same rating.</div>`}
      ${mode === 'threes' && html`<div class="mp-note">Threes: 3 on 3 with its own rules, so every rule is greyed. Counts in the same rating.</div>`}
      <div class="mp-rules">${roster && html`<${RosterRule} roster=${roster}/>`}${rules.rows.map((r) => {
        const picked = r.options.find((o) => o.value === r.value);
        return html`<label key=${r.key} class=${cls('mp-rule', r.value !== r.default && 'changed', r.off && 'off')}
            title=${r.off ? 'Does not apply to ' + (mode === 'threes' ? 'Threes' : 'Shootout') : null}>
          <span class="mp-rule-label caps">${r.label}</span>
          ${edit && !r.off
            ? html`<${Select} value=${r.value} options=${r.options} onChange=${(v) => call('mp_set_rule', r.key, v)}/>`
            : html`<span class="mp-rule-value">${picked ? picked.label : r.value}</span>`}
        </label>`;
      })}</div>
      ${roster && html`<${RosterNote} roster=${roster} host=${host} hostName=${hostName}/>`}
      ${edit && html`<div class="mp-row"><span class="mp-note">Changing a rule clears Ready for both of you.</span><span class="sp"></span>
        <${Button} small kind="ghost" disabled=${rules.is_default} onClick=${() => call('mp_reset_rules')}>Reset to default<//></div>`}
      ${!host && html`<div class="mp-note">${hostName || 'The host'} picks the rules. Both games play them.</div>`}
      ${host && !edit && html`<div class="mp-note">The game is starting: the rules are fixed now.</div>`}
    </div>
  </${Card}>`;
}

function Game({ game }) {
  const failed = game.phase === 'failed';
  return html`<${Card} n=${4} title="Game" aside=${game.steps.length ? 'About 2 minutes' : null}>
    <div class="mp-body">
      ${game.steps.length > 0 && html`<div class="mp-steps">${game.steps.map((st, i) => html`<div key=${i}
          class=${cls('mp-step', st.state)}><span class="n">${st.state === 'done' ? '✓' : i + 1}</span>${st.text}
          <span class="sp"></span>${st.state === 'now' && html`<${Tag} tone="accent">now<//>`}</div>`)}</div>`}
      ${failed && html`<div class="mp-steps"><div class="mp-step fail"><span class="n">!</span>${game.note}</div></div>`}
      ${!failed && game.note && html`<div class="mp-note">${game.note}</div>`}
      ${game.manual && !failed && html`<div class="mp-manual">Not moving? Press <b>✕</b> on the title screen (twice if the
        first only wakes the window). The game then goes to Online ${game.game || 'Versus'} by itself.</div>`}
      ${game.again && html`<div class="mp-row"><${Button} small onClick=${() => call('mp_launch_now')}>Start the game again<//></div>`}
    </div>
  </${Card}>`;
}

// --- History: recent matches and the players table; a click on a player opens the pop-up; "Enter result" the form ------
const STATUS_TONE = { good: 'good', bad: 'bad', caution: 'caution', info: 'info' };

function Side({ p }) {
  return html`<span class=${cls('mp-side', p.won && 'won', p.you && 'you')}>
    <span class="mp-side-name">${p.name}</span>${p.team && html`<span class="mp-team">${p.team}</span>`}</span>`;
}

const signed = (n) => (n > 0 ? '+' : '') + n;

function MatchRow({ m }) {
  const [a, b] = m.players;
  const shown = a.score != null && b.score != null;
  const score = shown ? `${a.score}–${b.score}` : (a.score != null ? `${a.score}–${b.score}?` : '–');
  // three parts (mockup): the first player with the match's state, the score, the second player with the buttons
  return html`<div class=${cls('mp-match', m.status)}>
    <div class="mp-match-a">
      <${Side} p=${a}/>
      <div class="mp-match-sub">
        <${Tag} tone=${STATUS_TONE[m.tone] || 'info'}>${m.text}<//>
        <span class="mp-ago">${m.ago}${m.mode === 'shootout' ? ' · Shootout' : m.mode === 'threes' ? ' · Threes' : ''}${m.rules && m.rules !== 'Default rules' ? ` · ${m.rules}` : ''}</span>
        ${m.delta != null && html`<span class=${cls('mp-delta', m.delta > 0 && 'plus', m.delta < 0 && 'minus')}>${signed(m.delta)}</span>`}
      </div>
    </div>
    <span class=${cls('mp-score', m.status !== 'confirmed' && 'tentative')}>${score}</span>
    <div class="mp-match-b">
      <${Side} p=${b}/>
      <div class="mp-match-sub">
        ${m.mine && m.status === 'confirmed' && html`<${Button} small onClick=${() => call('mp_review_open', m.id)}>Review<//>`}
        ${m.entry && html`<${Button} small kind=${m.entry.again ? 'ghost' : 'primary'} onClick=${() => call('mp_result_open', m.id)}>
          ${m.entry.again ? 'Change my result' : 'Enter result'}<//>`}
      </div>
    </div>
  </div>`;
}

function PlayerRow({ p }) {
  return html`<button type="button" class=${cls('mp-prow', p.you && 'you')} onClick=${() => call('mp_history_player', p.pid)}>
    <span class="mp-prow-name">${p.name}${p.you && html`<span class="you caps">you</span>`}</span>
    <span class="mp-prow-tier">${p.rank != null ? p.tier : p.rating != null ? 'Placing' : ''}</span>
    <span class="mp-prow-n mp-rk">${p.rank != null ? '#' + p.rank : p.rating != null ? '\u2026' : ''}</span>
    <span class="mp-prow-n mp-rt" title=${p.tier || ''}>${p.rating != null ? p.rating : ''}</span>
    <span class="mp-prow-n">${p.w}</span><span class="mp-prow-n">${p.l}</span><span class="mp-prow-n">${p.played}</span>
    <span class=${cls('mp-prow-n', p.diff > 0 && 'plus', p.diff < 0 && 'minus')}>${p.diff > 0 ? '+' : ''}${p.diff}</span>
  </button>`;
}

// ranked players by rank, then those still placing by rating; the rest (an older server) as sent
const byRating = (a, b) => (a.rank != null ? a.rank : 1e6) - (b.rank != null ? b.rank : 1e6) || (b.rating || 0) - (a.rating || 0);

// 3 Your rating: the number big, then the tier (or the placing games), the last change, the record, a bar to the next
// tier (or to the rank), the record per game (Versus / Shootout / Threes)
function RatingCard({ r }) {
  const placed = 5 - r.placing;
  const bar = r.ranked ? (r.next ? r.next.progress || 0 : 1) : placed / 5;
  const streak = Math.abs(r.streak) >= 2 ? `${Math.abs(r.streak)} ${r.streak > 0 ? 'wins' : 'losses'} in a row` : '';
  const extra = [...(r.modes || []).map((m) => `${m.name} ${m.record}`), streak].filter(Boolean);
  return html`<${Card} n=${3} title="Your rating"
      aside=${html`<${Toggle} on=${!r.hidden} onChange=${(on) => call('mp_set_hidden', !on)}>Show me on the web board<//>`}>
    <div class="mp-body mp-rating">
      <div class="mp-rating-n">${r.rating}</div>
      <div class="mp-rating-side">
        <div class="mp-rating-top">
          <${Tag} tone=${r.ranked ? 'good' : 'info'}>${r.ranked ? r.tier : `Placing ${placed}/5`}<//>
          ${r.change != null && html`<span class=${cls('mp-delta', r.change > 0 && 'plus', r.change < 0 && 'minus')}>${signed(r.change)} last game</span>`}
          <span class="mp-rating-rec">Record ${r.record}</span>
        </div>
        <div class="mp-progress" title=${r.ranked && r.next ? `${r.next.to_go} to ${r.next.name}` : null}>
          <span style=${{ width: `${Math.round(Math.min(1, Math.max(0, bar)) * 100)}%` }}></span></div>
        <div class="mp-rating-note">${r.ranked
          ? `#${r.rank} of ${r.of}${r.next ? ` · ${r.next.to_go} to ${r.next.name} (${r.next.at})` : ''}`
          : `${r.placing} more rated ${r.placing === 1 ? 'game' : 'games'} to get your rank`}</div>
        ${extra.length > 0 && html`<div class="mp-rating-note">${extra.join(' · ')}</div>`}
      </div>
    </div>
  <//>`;
}

// My games: how I played, over every game that has the game's own numbers, then each game with its box score.
function MyGames({ g }) {
  const o = g.overall;
  return html`<div class="mp-games">
    <div class="mp-tally"><span class="mp-tally-n">${g.w}–${g.l}</span>
      <span class="mp-note">${g.played} confirmed ${g.played === 1 ? 'game' : 'games'}, goals ${g.gf}–${g.ga}</span></div>
    ${o
      ? html`<div class="caps mp-sub">Per Versus game over ${o.games} ${o.games === 1 ? 'game' : 'games'} with the game's numbers</div>
        <div class="mp-avg">${o.avg.map((a) => html`<div class="mp-avg-cell" key=${a.key} title=${`Total ${a.total}`}>
          <span class="mp-avg-v">${a.value}</span><span class="mp-note">${a.label}</span></div>`)}</div>
        ${o.rates.length > 0 && html`<div class="mp-rates">${o.rates.map((r) => html`<span key=${r.label}><b>${r.value}</b> <span class="mp-note">${r.label}</span></span>`)}</div>`}`
      : !g.shootout && html`<div class="mp-empty">No numbers yet. They come from the game's own match report after an online game;
        a result typed in the app has no numbers.</div>`}
    ${g.shootout && html`<div class="caps mp-sub">Shootout over ${g.shootout.games} ${g.shootout.games === 1 ? 'game' : 'games'}</div>
      <div class="mp-note">${g.shootout.line}</div>
      ${g.shootout.rates.length > 0 && html`<div class="mp-rates">${g.shootout.rates.map((r) => html`<span key=${r.label}><b>${r.value}</b> <span class="mp-note">${r.label}</span></span>`)}</div>`}`}
    <div class="caps mp-sub">My games</div>
    <div class="mp-recent">${g.games.map((m) => html`<details class=${cls('mp-game', m.result)} key=${m.id}>
      <summary class=${cls('mp-recent-row', m.result)}>
        <span class="mp-res">${m.result || '–'}</span>
        <span class="mp-recent-main">${m.for != null && m.status === 'confirmed'
          ? html`${m.team || '?'} ${m.for}–${m.against} ${m.opp_team || '?'}<span class="mp-note"> against ${m.opponent}</span>`
          : html`Against ${m.opponent}`}</span>
        <span class="mp-ago">${m.status === 'confirmed' ? '' : m.status + ' · '}${m.ago}${m.mode === 'shootout' ? ' · Shootout' : m.mode === 'threes' ? ' · Threes' : ''}</span></summary>
      ${m.box.length
        ? html`<div class="mp-box"><div class="mp-box-row head caps"><span></span><span>Me</span><span>Them</span></div>
            ${m.box.map((r) => html`<div class="mp-box-row" key=${r.label}><span>${r.label}</span><b>${r.me}</b><span>${r.them}</span></div>`)}</div>`
        : html`<div class="mp-note mp-box-none">No numbers for this game.</div>`}
    </details>`)}</div>
  </div>`;
}

function History({ h }) {
  const [view, setView] = useState('matches');
  const [sort, setSort] = useState('rating');
  const empty = h.loaded && !h.matches.length;
  const players = sort === 'rating' && h.players.some((p) => p.rating != null) ? [...h.players].sort(byRating) : h.players;
  return html`<${Card} title="History" className="mp-card-fill"
      aside=${html`<${Button} small kind="ghost" onClick=${() => call('mp_history_refresh')}>Refresh<//>`}>
    <div class="mp-body mp-fill mp-hist">
      ${h.banner && html`<div class="mp-notice info" role="status"><span class="sp"><b>Match review ready:</b> ${h.banner.text}</span>
        <${Button} small kind="primary" onClick=${() => call('mp_review_open', h.banner.match)}>View<//></div>`}
      <${Segmented} value=${view} onChange=${setView}
        options=${[{ value: 'matches', label: 'Recent matches' }, ...(h.games ? [{ value: 'games', label: 'My games' }] : []),
          { value: 'players', label: 'Leaderboard' }]}/>
      ${h.error && html`<div class="mp-note warn" role="alert">${h.error}</div>`}
      <div class="mp-hist-scroll">
        ${!h.loaded && !h.error && html`<div class="mp-empty">Loading the history...</div>`}
        ${view === 'matches' && empty && html`<div class="mp-empty">No matches yet. Every game two players start from a lobby shows up here;
          after it, both enter the result and it counts.</div>`}
        ${view === 'games' && h.games && html`<${MyGames} g=${h.games}/>`}
        ${view === 'matches' && h.matches.length > 0 && html`<div class="mp-matches">${h.matches.map((m) => html`<${MatchRow} key=${m.id} m=${m}/>`)}</div>`}
        ${view === 'players' && h.players.some((p) => p.rating != null) && html`<${Segmented} value=${sort} onChange=${setSort}
          options=${[{ value: 'rating', label: 'By rating' }, { value: 'wins', label: 'By wins' }]}/>`}
        ${view === 'players' && html`${h.players.length
          ? html`<div class="mp-players-table">
              <div class="mp-prow head caps"><span class="mp-prow-name">Player</span><span class="mp-prow-tier">Tier</span><span class="mp-prow-n mp-rk">Rank</span>
                <span class="mp-prow-n mp-rt">Rating</span><span class="mp-prow-n">W</span>
                <span class="mp-prow-n">L</span><span class="mp-prow-n">GP</span><span class="mp-prow-n">+/-</span></div>
              ${players.map((p) => html`<${PlayerRow} key=${p.pid} p=${p}/>`)}</div>`
          : h.loaded && html`<div class="mp-empty">Nobody has a confirmed match yet.</div>`}`}
        ${view === 'players' && h.ladder.length > 0 && html`<div class="caps mp-sub">Ranks (a rank shows after 5 rated games)</div>
          <div class="mp-ladder">${h.ladder.map((t) => html`<div key=${t.name} class=${cls('mp-ladder-row', t.you && 'you')}>
            <b>${t.name}</b><span class="mp-note">${t.min ? t.min + '+' : 'under 1000'}</span><span class="mp-note mp-ladder-b">${t.blurb}</span></div>`)}</div>`}
      </div>
    </div>
  </${Card}>`;
}

// draft for the owner to approve (v0.10.0); the web board's footer says the same (overtime_server/http/web/board.html)
function Privacy() {
  return html`<details class="mp-privacy">
    <summary class="caps"><${Chevron}/>What the Overtime server keeps</summary>
    <ul class="mp-note">
      <li>The name you enter here and your ShadNet account number. Other players never see the number, only your name.</li>
      <li>Every match two players start from a lobby: both names, the teams, the scores, the match rules and when it was
        played. Matches are kept so the history and the ratings add up; the server's operator can remove one.</li>
      <li>Other Overtime players see your name, results and rating in their History. The public web board shows the same;
        with "Show me on the web board" off it shows you as "Hidden player" (your place and rating stay, so the others'
        numbers still add up).</li>
      <li>Lobby chat lasts only as long as the lobby and is never written down.</li>
      <li>Reports, only when you turn them on (or send one by hand): the game's log (the first 3,000 lines and the last
        20,000, with your folder path, user and computer names, Online ID, IP and e-mail addresses taken out), the app and emulator
        versions, the emulator's file hash, your CPU and its maker, the Cross-CPU check, the game's online version, your
        ShadNet account number and the match id. Never a password. Kept for 30 days.</li>
      <li>A CPU check result, only when you send it: what your CPU's two estimate instructions return, its name and maker,
        and the app and emulator details a report holds (no game log, no account number). Kept for 30 days.</li>
    </ul>
  </details>`;
}

function Record({ rows, empty, label }) {
  if (!rows.length) return html`<div class="mp-empty">${empty}</div>`;
  return html`<div class="mp-rec">${rows.map((r) => html`<div class="mp-rec-row" key=${r.pid || r.team}>
    <span class="mp-rec-name">${r.name || r.team}</span><span class="mp-rec-wl">${r.w}\u2013${r.l}</span></div>`)}</div>`;
}

function PlayerWindow({ d }) {
  const close = () => call('mp_history_close');
  return html`<${Modal} wide title=${d.name + (d.you ? ' (you)' : '')} onClose=${close}
      buttons=${html`<${Button} kind="primary" onClick=${close}>Close<//>`}>
    <div class="mp-detail">
      <div class="mp-tally"><span class="mp-tally-n">${d.w}\u2013${d.l}</span>
        <span class="mp-note">${d.played} confirmed ${d.played === 1 ? 'game' : 'games'}, goals ${d.gf}\u2013${d.ga}</span></div>
      <div class="mp-detail-cols">
        <div><div class="caps mp-sub">Played against</div><${Record} rows=${d.opponents} empty="Nobody yet."/></div>
        <div><div class="caps mp-sub">Teams played with</div><${Record} rows=${d.teams} empty="No teams yet."/></div>
        <div><div class="caps mp-sub">Teams played against</div><${Record} rows=${d.against} empty="No teams yet."/></div>
      </div>
      <div class="caps mp-sub">Latest matches</div>
      <div class="mp-recent">${d.recent.map((m) => html`<div class=${cls('mp-recent-row', m.result)} key=${m.id}>
        <span class="mp-res">${m.result || '\u2013'}</span>
        <span class="mp-recent-main">${m.for != null && m.status === 'confirmed'
          ? html`${m.team || '?'} ${m.for}\u2013${m.against} ${m.opp_team || '?'}<span class="mp-note"> against ${m.opponent}</span>`
          : html`Against ${m.opponent}`}</span>
        <span class="mp-ago">${m.status === 'confirmed' ? '' : m.status + ' \u00b7 '}${m.ago}</span></div>`)}</div>
    </div>
  <//>`;
}

function ReviewWindow({ r }) {
  const close = () => call('mp_review_close');
  const n = r.rating;
  return html`<${Modal} wide title=${r.headline} onClose=${close}
      buttons=${html`<${Button} kind="primary" onClick=${close}>Close<//>`}>
    <div class="mp-review">
      <div class="mp-tally"><span class=${cls('mp-tally-n', r.won ? 'plus' : 'minus')}>${r.for}\u2013${r.against}</span>
        <span class="mp-note">${r.team || '?'} against ${r.opp_team || '?'} \u00b7 ${n.before} \u2192 ${n.after} (${signed(n.delta)}) \u00b7 ${n.chance}% chance to win</span></div>
      ${r.tags.length > 0 && html`<div class="mp-tags">${r.tags.map((t) => html`<${Tag} key=${t} tone="info">${t}<//>`)}</div>`}
      <div class="caps mp-sub">How it went</div>
      <ul class="mp-facts">${r.facts.map((f, i) => html`<li key=${i}>${f}</li>`)}</ul>
      <div class="caps mp-sub">What to work on</div>
      ${r.tips.length
        ? html`<ul class="mp-facts">${r.tips.map((t, i) => html`<li key=${i}>${t}</li>`)}</ul>`
        : html`<div class="mp-empty">${r.has_stats ? 'Nothing stood out in the numbers of this game.'
          : 'Detailed tips need the game\u2019s own match report (shots, penalties, faceoffs). This server has not received one for this match.'}</div>`}
    </div>
  <//>`;
}

function ResultWindow({ f }) {
  const [team, setTeam] = useState(f.team);
  const [mine, setMine] = useState(f.score_for == null ? '' : String(f.score_for));
  const [theirs, setTheirs] = useState(f.score_against == null ? '' : String(f.score_against));
  const close = () => call('mp_result_close');
  const send = () => call('mp_result', f.match, team, mine === '' ? null : Number(mine), theirs === '' ? null : Number(theirs));
  const teams = [{ value: '', label: 'Pick your team' }, ...f.teams.map((t) => ({ value: t, label: t }))];
  if (team && !f.teams.includes(team)) teams.push({ value: team, label: team });
  const num = (value, set, label) => html`<input class="field mp-num" inputmode="numeric" maxlength="2" value=${value} aria-label=${label}
    onInput=${(e) => set(e.target.value.replace(/\D/g, ''))} onKeyDown=${(e) => { if (e.key === 'Enter') send(); }}/>`;
  return html`<${Modal} title=${'Result against ' + f.opponent} onClose=${close}
      buttons=${html`<${Button} kind="ghost" onClick=${close}>Cancel<//><${Button} kind="primary" onClick=${send}>Send result<//>`}>
    <div class="mp-form">
      <label class="mp-form-row"><span class="caps">Your team</span>
        <${Select} value=${team} options=${teams} onChange=${setTeam}/></label>
      <div class="mp-form-row"><span class="caps">Final score (overtime and shootout count)</span>
        <div class="mp-score-in">${num(mine, setMine, 'Your goals')}<span>\u2013</span>${num(theirs, setTheirs, 'Their goals')}
          <span class="mp-note">you \u2013 ${f.opponent}</span></div></div>
      ${f.error && html`<div class="mp-note bad" role="alert">${f.error}</div>`}
      <div class="mp-note">The result counts once ${f.opponent} enters the same score from their side.</div>
    </div>
  <//>`;
}

export function Modals() {
  const s = useSlice('multiplayer');
  const h = s && s.history;
  if (!h) return null;
  return html`${h.detail && html`<${PlayerWindow} d=${h.detail}/>`}${h.form && html`<${ResultWindow} key=${h.form.match} f=${h.form}/>`}
    ${h.review && html`<${ReviewWindow} key=${h.review.match} r=${h.review}/>`}`;
}

export default function Multiplayer({ go }) {
  const s = useSlice('multiplayer');
  const setup = useSlice('setup');       // the Advanced row (server address, firewall) and the firewall check are Setup's
  if (!s) return null;
  const h = s.history && s.history.supported ? s.history : null;
  return html`<div class=${cls('mp', !h && 'no-side')}>
    <div class="mp-col mp-col-you"><${You} s=${s} setup=${setup} go=${go}/></div>
    <div class="mp-col mp-col-lobby">
      ${s.lobby
        ? html`<${Lobby} s=${s}/>`
        : html`<${Card} n=${2} title="Lobby" aside="Play one friend at a time" className="mp-card-fill mp-stage">
            ${s.you.ext ? html`<${Pick} s=${s} go=${go}/>`
              : html`<div class="mp-body mp-fill"><div class="mp-empty">Sign in to ShadNet first (left): a lobby is tied to your game's own sign-in.</div>
                  <div class="mp-spacer"></div><${HowTo}/></div>`}
          </${Card}>`}
      ${s.lobby && s.lobby.rules && html`<${Rules} rules=${s.lobby.rules} host=${s.lobby.host} hostName=${s.lobby.host_name}
          roster=${s.lobby.roster_mode} mode=${s.lobby.mode} modePick=${s.lobby.mode_pick}/>`}
      ${s.game && html`<${Game} game=${s.game}/>`}
    </div>
    ${h && html`<div class="mp-col mp-col-side">
      ${h.rating && html`<${RatingCard} r=${h.rating}/>`}
      <${History} h=${h}/>
    </div>`}
  </div>`;
}
