"""Strategy: the rail's team's team and line strategies. docs/ui/strategy.md.

Like Legacy's Strategy tab, the tab works on a draft: the player's changes to the team's strategies row, kept per rail
team over the roster's own values. Changes wait per team until Apply (the draft of a team the rail leaves is kept);
Apply writes the draft into the roster as one change (My edits, the rail's dot); Game defaults puts NHL 19's own values
for the team (the game's default roster) into the draft; "Take back my strategies" drops the draft and, while the
team's applied strategies are not saved yet, takes them back (applied.py). The strategies table knows Seattle (399 on
the rail) as the custom team 499 (Rail.map_id('strategy')): the slice's `id` is the table's, the draft is the rail's.

Beta1's names stay: strategy_team moves the rail (the rail leads), strategy_set and strategy_reset work on the draft,
snap_strategy shows the draft's values while the team has one.
"""
from overtime_core import strategy as S, teams as T

from .applied import Applied
from .rail import FA, SEATTLE, TIP, why_view
from .registry import Part
from .session import EditError

TAB = 'Strategy'                                                       # session.Change.tab (shell.TAB_LABELS)
HIDDEN = ('team_bias2', *(f'forward{n}_bias2' for n in range(1, 5)))   # varied by the game, not on its menu
LABELS = {S.TRAP: 'Neutral zone or forecheck'}                         # its words: NZ ... FC
TITLES = {'Team': 'Team strategies'}
NOTE = 'The strategies this team takes into every game. Change any of them, then Apply.'
APPLIED = 'Applied. Save the roster to keep these strategies in it.'
FREE_AGENTS = 'Free agents have no strategies. Pick a team in the list.'
NO_ROW = 'This team has no strategies in the roster. Pick another team in the list.'
SEATTLE_NONE = 'This roster has no strategies for Seattle yet. Run the roster update on the Patch tab first.'
NO_GAME_ROW = "NHL 19's own roster has no strategies for this team."
SAME_AS_GAME = "These are the game's own strategies already."
NO_TEAM = 'Pick a team in the list first.'
WHY_TIP = f'Pick a team in the list to change its strategies. {TIP}.'


def _layout():
    """[(section title, [row])] of strategy.describe() in the words the tab shows, and {field: row}."""
    sections, rows = [], {}
    for sec in S.describe():
        title = TITLES.get(sec['title'], sec['title'])
        out = []
        for f in sec['fields']:
            row = dict(f, label=LABELS.get(f['field'], f['label']), section=title, hidden=f['field'] in HIDDEN)
            out.append(row)
            rows[f['field']] = row
        sections.append((title, out))
    return sections, rows


SECTIONS, ROWS = _layout()
SHARED = {f for f, r in ROWS.items() if sum(1 for o in ROWS.values() if o['label'] == r['label']) > 1}
TEAM_SECTION = SECTIONS[0][0]


def where(field):
    """A value's name in a sentence: 'Carry or Dump on forward line 2' when the name alone is not clear."""
    r = ROWS.get(field)
    if r is None:
        return S.label(field)
    if field in SHARED and r['section'] != TEAM_SECTION:
        return f"{r['label']} on {r['section'].lower()}"
    return r['label']


def words(field, value):
    r = ROWS.get(field)
    if r is not None and r['kind'] == 'choice' and isinstance(value, int) and 0 <= value < len(r['options']):
        return r['options'][value]
    return str(value)


def bad(field, value):
    """The value is not one the game uses (shown fields only: the others hold what their bits hold)."""
    return field in ROWS and not (isinstance(value, int) and 0 <= value <= ROWS[field]['top'])


def number(value):
    """A whole number the page sent (3, 3.0 or '3'), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def problems(values):
    return [f"{where(f)} holds {values[f]}, but the game's values go from 0 to {ROWS[f]['top']}."
            for f in S.FIELDS if f in values and bad(f, values[f])]


def describe(base, draft):
    """My edits' label of what the draft changes: 'Forecheck: 2-3', 'Carry or Dump on forward line 2: 6',
    '3 strategies changed'."""
    moved = [f for f in draft if draft[f] != base.get(f)]
    if len(moved) == 1 and moved[0] in ROWS:
        return f'{where(moved[0])}: {words(moved[0], draft[moved[0]])}'
    return f"{len(moved)} strateg{'ies' if len(moved) != 1 else 'y'} changed"


class StrategyCtl(Part):
    SLICES = {'strategy': 'view'}
    CALLS = {'strategy_set': 'strategy_set', 'strategy_reset': 'strategy_reset', 'strategy_apply': 'strategy_apply',
             'strategy_undo': 'strategy_undo', 'strategy_show_hidden': 'strategy_show_hidden',
             'strategy_team': 'strategy_team'}
    TAB = 'strategy'

    def __init__(self, ctl):
        super().__init__(ctl)
        self.held = {}          # rail team -> {field: value}: the player's changes, not applied yet
        self.notes = {}         # rail team -> the note after Apply
        self.applied = Applied(ctl, TAB)
        self._stock = None      # (the GameData read, {table id: NHL 19's own values})

    # --- the rail's hooks --------------------------------------------------------------------------------------------
    def follow(self, team):
        c = self.ctl
        with c.lock:
            mapped = c.rail.map_id('strategy', team)
            if mapped is not None and mapped != FA:
                c.strat_team = mapped       # beta1's snapshot reads it
        c.changed('strategy')

    def roster_changed(self):
        self.held, self.notes = {}, {}
        self.applied.reset()

    def dirty(self, team):
        return self.touched(team)

    def drafts(self):
        c = self.ctl
        with c.lock:
            codes = [self.code(t) for t in list(self.held) if self.touched(t)]
        return f"Strategies not applied yet: {', '.join(codes)}." if codes else ''

    # --- the team's values -------------------------------------------------------------------------------------------
    def code(self, team):
        chip = self.ctl.rail.chip(team)
        return chip['code'] if chip else str(team)

    @staticmethod
    def rail_of(tid):
        """The rail id of a strategies table id (499 is the rail's Seattle)."""
        return SEATTLE if tid == T.SEATTLE else tid

    def table_id(self, team):
        return self.ctl.rail.map_id('strategy', team)

    def now(self, s, team):
        """{field: value} of every field of the team's row in the open roster, or None (no row)."""
        if team is None or team == FA:
            return None
        return S.read(s.db, self.table_id(team), every=True)

    def draft(self, s, team):
        """The team's values with the player's changes on them, or None."""
        now = self.now(s, team)
        if now is None:
            return None
        return dict(now, **{f: v for f, v in self.held.get(team, {}).items() if f in now})

    def hold(self, s, team, values):
        """Keep what `values` changes of the roster's (nothing: no draft)."""
        now = self.now(s, team) or {}
        held = {f: v for f, v in values.items() if f in now and now[f] != v}
        if held:
            self.held[team] = held
        else:
            self.held.pop(team, None)

    def touched(self, team):
        """The team's draft differs from the roster."""
        s, held = self.ctl.session, self.held.get(team)
        if s is None or not held:
            return False
        now = self.now(s, team) or {}
        return any(f in now and now[f] != v for f, v in held.items())

    def stock(self, tid):
        """NHL 19's own values (every field) for a strategies table id, or None: the game's default roster, read once
        (strategy.locate's order: a custom team's own table first)."""
        c = self.ctl
        if self._stock is None or self._stock[0] is not c.game:
            found = {}
            try:
                db = c.game.default_db()
                for name in (S.CUSTOM, S.STRATEGIES):
                    if name not in db:
                        continue
                    t = db[name]
                    fields = [f.name for f in t.fields if f.name != S.KEY]
                    for i in range(t.count):
                        key = t.get(i, S.KEY)
                        if name == S.STRATEGIES or key >= S.FIRST_CUSTOM:
                            found.setdefault(key, {f: t.get(i, f) for f in fields})
            except (OSError, ValueError, KeyError, IndexError) as err:
                c.host.log(f"Strategy: NHL 19's own strategies could not be read ({err}).")
            self._stock = (c.game, found)
        return self._stock[1].get(tid)

    def why(self, s, team):
        """Why the tab cannot show this team's strategies, or ''."""
        if team is None:
            return 'Pick a team in the list.'
        if team == FA:
            return FREE_AGENTS
        if self.now(s, team) is None:
            return SEATTLE_NONE if team == SEATTLE else NO_ROW
        return ''

    def ready(self):
        """(session, rail team, table id) when the tab shows the rail's team's strategies, else None. Under the lock."""
        c = self.ctl
        if c.session is None or self.why(c.session, c.team):
            return None
        return c.session, c.team, self.table_id(c.team)

    # --- the slice ---------------------------------------------------------------------------------------------------
    def view(self):
        c = self.ctl
        with c.lock:
            s, team = c.session, c.team
            if s is None:       # no roster yet, or it is being read
                return why_view(c, 'strategy', 'strategies', FREE_AGENTS, '')
            chip = c.rail.chip(team)
            head = {'id': self.table_id(team), 'team': team, 'view': chip,
                    'title': f"{chip['name']}: strategies" if chip else 'Strategies'}
            why = self.why(s, team)
            if why:
                return dict(head, why=why, tip=WHY_TIP)
            return dict(head, why=None, **self.page(s, team))

    def page(self, s, team):
        c = self.ctl
        base, st = self.now(s, team), self.draft(s, team)
        show = bool(c.prefs.get('strategy_hidden'))
        sections = []
        for title, rows in SECTIONS:
            out = []
            for r in rows:
                f = r['field']
                v = st[f]
                if r['hidden'] and not show and not bad(f, v):
                    continue
                row = {'field': f, 'kind': r['kind'], 'label': r['label'], 'value': v, 'top': r['top'],
                       'changed': v != base[f], 'hidden': r['hidden'], 'bad': bad(f, v)}
                if r['kind'] == 'choice':
                    row['options'] = [{'value': k, 'label': w} for k, w in enumerate(r['options'])]
                else:
                    row['left'], row['right'] = r['words']
                out.append(row)
            sections.append({'title': title, 'rows': out})
        probs = problems(st)
        touched = self.touched(team)
        mine = bool(self.applied.mine(team))
        note = mine and self.notes.get(team)
        own = self.stock(self.table_id(team))
        same = own is not None and all(st.get(f) == v for f, v in own.items())
        return {
            'note': APPLIED if note else NOTE, 'note_tone': 'good' if note else '',
            'sections': sections, 'show_hidden': show, 'hidden_count': len(HIDDEN),
            'problems': probs, 'touched': touched, 'can_apply': touched and not probs,
            'mine': mine, 'can_undo': mine or touched,
            'can_defaults': own is not None and not same,
            'defaults_why': NO_GAME_ROW if own is None else SAME_AS_GAME if same else '',
        }

    # --- calls -------------------------------------------------------------------------------------------------------
    def refuse(self, text, tone='caution'):
        self.ctl.say(text, tone)
        return {'error': text}

    def strategy_team(self, team):
        """Beta1's own team list (a strategies table id): the rail moves to that team (499: the rail's Seattle)."""
        c = self.ctl
        try:
            tid = int(team)
        except (TypeError, ValueError):
            return self.refuse(NO_TEAM)
        with c.lock:
            c.strat_team = tid
        c.rail.pick_team(self.rail_of(tid))
        c.changed('strategy')
        return {'ok': True}

    def strategy_set(self, field, value):
        """Put a value in the team's draft."""
        c = self.ctl
        with c.lock:
            if c.session is None:
                return self.refuse('Pick a roster in Setup first.')
            ready = self.ready()
            if ready is None:
                return self.refuse(NO_TEAM)
            s, team, _tid = ready
            r = ROWS.get(field)
            if r is None:
                return self.refuse('There is no such strategy.')
            v = number(value)
            if v is None or bad(field, v):
                return self.refuse(f"Pick a value from 0 to {r['top']}.")
            st = self.draft(s, team)
            if st[field] == v:
                return {'ok': True}
            st[field] = v
            self.hold(s, team, st)
            self.notes.pop(team, None)
        c.changed('strategy', 'rail')
        return {'ok': True}

    def strategy_reset(self):
        """Game defaults: NHL 19's own values for the team into the draft."""
        c = self.ctl
        with c.lock:
            if c.session is None:
                return self.refuse('Pick a roster in Setup first.')
            ready = self.ready()
            if ready is None:
                return self.refuse(NO_TEAM)
            s, team, tid = ready
            own = self.stock(tid)
            if own is None:
                return self.refuse(NO_GAME_ROW)
            st = self.draft(s, team)
            if all(st.get(f) == v for f, v in own.items()):
                c.say(SAME_AS_GAME, 'info')
                return {'ok': False}
            st.update({f: v for f, v in own.items() if f in st})
            self.hold(s, team, st)
            self.notes.pop(team, None)
            touched = self.touched(team)
        c.say("The game's own strategies are in. Check them, then Apply." if touched
              else "Back to the roster's strategies.", 'info')
        c.changed('strategy', 'rail')
        return {'ok': True}

    def strategy_apply(self):
        """Write the team's draft into the roster as one change (My edits)."""
        c = self.ctl
        with c.lock:
            ready = self.ready()
            if ready is None:
                return self.refuse(NO_TEAM)
            s, team, tid = ready
            if not self.touched(team):
                return self.refuse('Nothing to apply: change a strategy first.', 'info')
            base, st = self.now(s, team), self.draft(s, team)
            probs = problems(st)
            if probs:
                return self.refuse(f'{probs[0]} Pick a value, then Apply.')
            changed = {f: v for f, v in st.items() if v != base[f]}
            label = describe(base, changed)
            code, name = self.code(team), c.rail.chip(team)['name']
            details = [(f'{code} strategy: {where(f)}', words(f, base[f]), words(f, v))
                       for f, v in changed.items() if f in ROWS]
            others = sum(1 for f in changed if f not in ROWS)     # only Game defaults changes those
            if others:
                details.append((f"{code} strategy: {others} value{'s' if others != 1 else ''} the menu does not show",
                                "the roster's", "the game's own"))
            try:
                ch, _n = s.edit(label, lambda setter: S.write(s.db, tid, changed, setter=setter))
            except (EditError, KeyError) as err:
                return self.refuse(str(err), 'bad')
            ch.tab, ch.team = TAB, team
            ch.details += details
            self.applied.note(ch, {f: (base[f], v) for f, v in changed.items()})
            self.held.pop(team, None)
            self.notes[team] = APPLIED
            c.issues = None
        c.host.log(f'{code} strategies: {label}.')
        for what, old, new in details:
            c.host.log(f'  {what}: {old} -> {new}')
        c.say(f'{name}: strategies applied. Save the roster to keep them.', 'good')
        c.changed('strategy', 'rail', 'save', 'editor')
        return {'ok': True}

    def strategy_undo(self):
        """Take back my strategies: the draft goes, and the team's applied strategies that are not saved yet are taken
        back."""
        c = self.ctl
        with c.lock:
            ready = self.ready()
            if ready is None:
                return self.refuse(NO_TEAM)
            s, team, tid = ready
            touched = self.touched(team)
            self.held.pop(team, None)
            self.notes.pop(team, None)
            code, name = self.code(team), c.rail.chip(team)['name']

            def restore(setter, values):
                found = S.locate(s.db, tid)
                if found is None:
                    return
                t, row = found
                for f, (old, new) in values.items():
                    if t.get(row, f) == new:
                        setter(t.name, row, f, old)
            try:
                back = self.applied.take_back(team, f'{name}: strategies taken back', restore)
            except EditError as err:
                return self.refuse(str(err), 'bad')
            if back is not None:
                c.issues = None
        if back is None and not touched:
            c.say('Nothing to take back on this team.', 'info')
            return {'ok': False}
        if back is not None:
            c.host.log(f'{code} strategies: taken back.')
            c.say("Your strategies are taken back. The team plays the roster's strategies again.", 'info')
        else:
            c.say('Your changes are dropped.', 'info')
        c.changed('strategy', 'rail', 'save', 'editor')
        return {'ok': True}

    def strategy_show_hidden(self, on):
        """Show or hide the values the game's menu does not show (a preference)."""
        c = self.ctl
        with c.lock:
            c.remember(strategy_hidden=bool(on))
        c.changed('strategy')
        return {'ok': True}

    # --- beta1's strategies ------------------------------------------------------------------------------------------
    def _strategy_teams(self):
        c = self.ctl
        s = c.session
        out = [{'id': t, 'abbr': c._code(t), 'name': s.team_name(t)} for t in range(31)]
        if S.locate(s.db, T.SEATTLE) is not None:
            out.append({'id': T.SEATTLE, 'abbr': 'SEA', 'name': 'Seattle (custom team)'})
        return out

    def snap_strategy(self):
        """Beta1's strategies snapshot (the draft's values while the team has one)."""
        c = self.ctl
        with c.lock:
            s = c.session
            if s is None:
                return {'ready': False}
            team = c.strat_team
            rail = self.rail_of(team)
            values = self.draft(s, rail) if self.table_id(rail) == team else None
            if values is None:
                values = S.read(s.db, team, every=True)
            return {'ready': True, 'teams': self._strategy_teams(), 'team': team, 'abbr': c._code(team),
                    'name': s.team_name(team) if team < S.FIRST_CUSTOM else 'Seattle (custom team)',
                    'sections': S.describe(), 'values': {f: values[f] for f in S.FIELDS} if values else None,
                    'verified': S.VERIFIED, 'busy': bool(c.busy)}
