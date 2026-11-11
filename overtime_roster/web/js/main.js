// The window: header, [L1] nine tabs [R1], the stage, the Help bar. Legacy's frame; each tab is its own module
// (js/tabs/<id>.js, loaded at start, drawn the first time it shows), so one tab's error never stops the others.
import { html, useState, useEffect, useRef, cls } from './lib.js';
import { useLobbyChimes } from './chime.js';
import { useSlice, useMeta, onEvent } from './store.js';
import { connect, call } from './bridge.js';
import { Backdrop, Header, TabBar, HelpBar, Details, Question } from './shell.js';
import { Rail } from './rail.js';
import { SaveBar, EditsWindow, saveRoster, cardDraft } from './savebar.js';

// Python moves to a tab itself (after a Patch with 32 teams, "Update it now" opens Update): the event 'goto' (tab id)
const goto = { pick: null };
onEvent('goto', (id) => goto.pick && goto.pick(id));

const R = window.React;

export const TABS = [
  { id: 'setup', label: 'Setup' },
  { id: 'update', label: 'Update' },
  { id: 'patch', label: 'Game patch' },
  { id: 'roster', label: 'Roster', team: true },
  { id: 'lines', label: 'Lines', team: true },
  { id: 'strategy', label: 'Strategy', team: true },
  { id: 'jerseys', label: 'Jerseys & gear', team: true },
  { id: 'calendar', label: 'Calendar', team: true, nosave: true },
  { id: 'office', label: 'Front office', team: true },
  { id: 'multiplayer', label: 'Multiplayer' },
];
const IDS = TABS.map((t) => t.id);
const TEAM = new Set(TABS.filter((t) => t.team).map((t) => t.id));
// beta1's tab names, so old links (?tab=...) and texts still land somewhere sensible
const OLD_NAMES = { source: 'setup', 'setup-play': 'setup', editor: 'roster', 'edit-roster': 'roster', gear: 'jerseys',
  'team-gear': 'jerseys', verify: 'update', save: 'update', 'game-patch': 'patch' };
const SHORT = 720;                 // window lines under which the compact layout is used
const params = new URLSearchParams(location.search);

// every tab module, imported once: {id: {mod} | {error}}
const loading = Promise.all(IDS.map((id) => import(`./tabs/${id}.js`)
  .then((mod) => [id, { mod }])
  .catch((error) => { console.error(`tab ${id} did not load:`, error); return [id, { error }]; })))
  .then((pairs) => Object.fromEntries(pairs));

// a tab that throws while drawing shows its error instead of taking the window down
class Boundary extends R.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error) { console.error(`${this.props.name}:`, error); }
  render() {
    if (this.state.error) return html`<pre class="tab-error">${this.props.name} stopped: ${String(this.state.error && this.state.error.stack || this.state.error)}</pre>`;
    return this.props.children;
  }
}

function TabPane({ id, entry, active, go }) {
  if (!entry) return null;
  if (entry.error) return html`<pre class="tab-error">The ${id} tab did not load: ${String(entry.error && entry.error.message || entry.error)}</pre>`;
  const Tab = entry.mod.default;
  return Tab ? html`<${Boundary} name=${id}><${Tab} active=${active} go=${go}/><//>` : null;
}

function useShort() {
  const [short, setShort] = useState(window.innerHeight < SHORT);
  useEffect(() => {
    const check = () => setShort(window.innerHeight < SHORT);
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);
  return short;
}

const typingIn = (el) => el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));

function App() {
  const meta = useMeta();
  const app = useSlice('app');
  const status = useSlice('status');
  const rail = useSlice('rail');
  const save = useSlice('save');
  const question = useSlice('question');
  const update = useSlice('update');
  useLobbyChimes(useSlice('multiplayer'));
  const short = useShort();
  const asked = OLD_NAMES[params.get('tab')] || params.get('tab');
  const [tab, setTab] = useState(IDS.includes(asked) ? asked : null);
  const own = useSlice(tab || 'app');
  const [seen, setSeen] = useState(() => new Set(tab ? [tab] : []));
  const [dir, setDir] = useState('');
  const [mods, setMods] = useState({});
  const [details, setDetails] = useState(params.get('details') === '1');
  const state = useRef({});

  useEffect(() => { loading.then(setMods); }, []);
  // no tab asked for: Setup (Python's app.start)
  useEffect(() => { if (!tab && app && app.start) pickTab(app.start); }, [app && app.start]);
  useEffect(() => { if (tab) call('tab', tab); }, [tab]);

  goto.pick = pickTab;
  function pickTab(id) {
    if (!IDS.includes(id) || id === state.current.tab) return;
    const from = IDS.indexOf(state.current.tab), to = IDS.indexOf(id);
    setDir(from < 0 ? '' : to > from ? 'from-right' : 'from-left');
    setTab(id);
    setSeen((s) => (s.has(id) ? s : new Set([...s, id])));
  }

  const go = update && update.go;
  const enter = tab === 'update' && go && go.enabled ? go.text : null;
  // Ctrl+S does what the Save button does: only while it is on (or the Roster card has typed values to apply)
  const canSave = !!(save && save.button && save.button.enabled && !save.busy);
  state.current = { tab, enter, details, canSave };

  useEffect(() => {
    const key = (e) => {
      const { tab: now, enter: canGo } = state.current;
      const typing = typingIn(e.target);
      const dialog = document.querySelector('.modal-back');
      const mod = mods[now] && mods[now].mod;
      if (e.key === 'F5' || (e.ctrlKey && e.key.toLowerCase() === 'r')) { e.preventDefault(); return; }
      if (dialog) return;                                       // a dialog keeps its own keys (Escape closes it)
      if (mod && mod.onKey && mod.onKey(e)) { e.preventDefault(); return; }
      const step = (d) => pickTab(IDS[(IDS.indexOf(now) + d + IDS.length) % IDS.length]);
      if (e.ctrlKey && (e.key === 'PageUp' || e.key === 'PageDown')) { e.preventDefault(); step(e.key === 'PageUp' ? -1 : 1); return; }
      if (e.ctrlKey && !e.altKey && /^[0-9]$/.test(e.key)) { e.preventDefault(); pickTab(IDS[(Number(e.key) + 9) % 10]); return; }
      if (e.ctrlKey && e.key.toLowerCase() === 's') {
        e.preventDefault();
        if (TEAM.has(now) && now !== 'calendar' && (state.current.canSave || cardDraft.current)) saveRoster();
        return;
      }
      if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown') && TEAM.has(now)) {
        e.preventDefault(); call('rail_step', e.key === 'ArrowUp' ? -1 : 1); return;
      }
      if (e.key === 'Escape' && state.current.details) { setDetails(false); return; }
      if (typing || e.ctrlKey || e.altKey || e.metaKey) return;
      const k = e.key.toLowerCase();
      if (k === 'd') { setDetails((v) => !v); return; }
      if (k === 'q' || k === 'e') { step(k === 'q' ? -1 : 1); return; }
      if (e.key === 'Enter' && canGo && !(e.target.closest && e.target.closest('button, a, [role=option], [tabindex]'))) {
        e.preventDefault(); call('update_go');
      }
    };
    const menu = (e) => { if (!typingIn(e.target)) e.preventDefault(); };
    window.addEventListener('keydown', key);
    window.addEventListener('contextmenu', menu);
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('contextmenu', menu); };
  }, [mods]);

  const info = TABS.find((t) => t.id === tab);
  const mod = tab && mods[tab] && mods[tab].mod;
  const tip = (own && own.tip) || (mod && mod.tip);   // a tab's slice may say a tip for its state (Update: no roster)
  const teamTab = TEAM.has(tab);
  const nosave = info && info.nosave;

  return html`<div id="app" class=${cls('app', short && 'compact', params.has('still') && 'still')}>
    <${Backdrop}/>
    <${Header} meta=${meta} play=${app && app.play}/>
    <${TabBar} tabs=${TABS} tab=${tab} onTab=${pickTab}/>
    <main class="stage">
      ${TABS.filter((t) => !t.team && seen.has(t.id)).map((t) => html`<section key=${t.id}
          class=${cls('pane', `tab-${t.id}`, 'enter')} hidden=${tab !== t.id}>
        <${TabPane} id=${t.id} entry=${mods[t.id]} active=${tab === t.id} go=${pickTab}/>
      </section>`)}
      <section class=${cls('pane', 'teamstage', nosave && 'nosave')} hidden=${!teamTab}>
        <${Rail} s=${rail}/>
        <div class="tpanes">
          ${TABS.filter((t) => t.team && seen.has(t.id)).map((t) => html`<div key=${t.id}
              class=${cls('tpane', `tab-${t.id}`, tab === t.id && dir)} hidden=${tab !== t.id}>
            <${TabPane} id=${t.id} entry=${mods[t.id]} active=${tab === t.id} go=${pickTab}/>
          </div>`)}
        </div>
        ${!nosave && html`<${SaveBar} s=${save}/>`}
      </section>
    </main>
    <${Details} open=${details} onClose=${() => setDetails(false)}/>
    <${HelpBar} status=${status} tip=${tip} enter=${enter} detailsOpen=${details}
      onDetails=${() => setDetails((v) => !v)} onEnter=${() => call('update_go')}/>
    ${IDS.map((id) => mods[id] && mods[id].mod && mods[id].mod.Modals
      && html`<${Boundary} key=${id} name=${id}><${mods[id].mod.Modals}/><//>`)}
    <${EditsWindow}/>
    <${Question} dialog=${question} onAnswer=${(id, answer) => call('answer', id, answer)}/>
  </div>`;
}

window.ReactDOM.createRoot(document.getElementById('root')).render(html`<${App}/>`);
connect().then(() => setTimeout(() => window.__otOk && window.__otOk(), 0),
  (err) => window.__otFail && window.__otFail(`The app did not answer: ${err && err.message || err}`));
