"""Lines: the rail's team's lines, power play, penalty kill, overtime, shootout, NHL Threes and letters.
docs/ui/lines.md.

Like Legacy's Lines tab, the tab works on a draft of the team's lines: the player's changes to the team's
exhibitionrostertable rows (the 87 places, who dresses, the letters), kept per player and field over the roster's own
values. Changes wait per team until Apply (the draft of a team the rail leaves is kept); Apply writes the draft into
the roster as one change (My edits, the rail's dot); "Take back my lines" drops the draft and, while the team's
applied lines are not saved yet, takes them back (applied.py). The place rules are overtime_core.lines' own: `place`
runs on the draft and `deal` deals it ("Deal all lines again" is beta1's Auto lines). Beta1's names (set_slot,
set_captain, lines_section, auto_group, auto_lines, snap_lines) stay and work on the draft.
"""
from overtime_core import lines
from overtime_core.roster import ALTERNATE, CAPTAIN, ES_SLOTS, GOALIE, GOALIE_SLOTS

from . import labels as L
from .applied import Applied
from .rail import SEATTLE, TIP, why_view
from .registry import Part
from .session import EditError

ROSTER, DRESSED = lines.ROSTER, lines.DRESSED
FIELDS = ('team', 'playerindex', DRESSED, 'captain') + lines.SLOTS     # what the draft holds of a roster row
TAB = 'Lines'                                                          # session.Change.tab (shell.TAB_LABELS)
EVEN, LETTERS = 'Even strength', 'Letters'
PAGES = tuple(L.LINE_SECTIONS) + (LETTERS,)
POS_ORDER = {'C': 0, 'LW': 1, 'RW': 2, 'D': 3, 'G': 4}
LETTER = {0: '', CAPTAIN: 'C', ALTERNATE: 'A'}
NEED_GOALIES, NEED_SKATERS = 2, 18          # lines.deal: 20 dress, two of them goalies

# the unit titles players read (labels.LINE_GROUPS has the short ones: L1, D1, PP4-1, ...) and a place in a sentence
UNIT_TITLES = {
    'Forwards': 'Forward line {n}', 'Defense': 'Defence pair {n}', 'Goalies': 'Goalies',
    '5 on 4': 'Unit {n}: 5 on 4', '4 on 3': 'Unit {n}: 4 on 3', '4 on 5': 'Unit {n}: 4 on 5',
    '3 on 5': 'Unit {n}: 3 on 5', '4 on 4': 'Unit {n}: 4 on 4', '3 on 3': 'Unit {n}: 3 on 3',
    'Shooters': 'Shooters', 'Extra attackers': 'Extra attackers', 'NHL Threes': 'NHL Threes',
}
WORDS = {'LW': 'left wing', 'C': 'centre', 'RW': 'right wing', 'LD': 'left defence', 'RD': 'right defence',
         'Starter': 'starting goalie', 'Backup': 'backup goalie', 'W': 'wing', 'D': 'defence', 'G1': 'goalie 1',
         'G2': 'goalie 2', 'S1': 'shooter 1', 'S2': 'shooter 2'}
SLOT_LABELS = {'G1': 'Goalie 1', 'G2': 'Goalie 2', 'S1': 'Shooter 1', 'S2': 'Shooter 2'}
PAGE_NOTES = {
    'Even strength': 'Who dresses and who plays together at five on five. A player you bring in takes every place '
                     'of the one he replaces.',
    'Power play': 'The units the game sends out with one or two men more.',
    'Penalty kill': 'The units the game sends out a man or two short.',
    'Overtime': 'Four on four and three on three in overtime.',
    'Shootout': 'The shooters in the order they shoot, and the extra attackers for a pulled goalie.',
    'Threes': 'The team in NHL Threes. These players need not dress.',
}
LETTERS_RULE = ('Pick C, A or none for each player. A new C takes the C from the old one; NHL teams wear one C and '
                'two A, but more letters are allowed.')
APPLIED = 'Applied. Save the roster to keep these lines in it.'
FREE_AGENTS = 'Free agents have no lines. Pick a team in the list.'
NO_LINES = 'This team has no lines in the roster. Pick another team in the list.'
SEATTLE_CUSTOM = ("This roster keeps Seattle's players in the game's custom team only. Run the update on the Update "
                  'tab to change their lines here.')
SHORT = 'This team has too few players for lines ({}). A team needs 2 goalies and 18 skaters.'
NO_TEAM = 'Pick a team in the list first.'
WHY_TIP = f'Pick a team in the list to change its lines. {TIP}.'


def _words(group, title, label):
    if group == 'Shooters':
        return f'shooter {label}'
    if group == 'Extra attackers':
        return f'extra attacker {label}'
    if group == 'Goalies':
        return WORDS[label]
    if group == 'NHL Threes':
        return f'{WORDS[label]} in NHL Threes'
    return f'{WORDS[label]} on {title[:1].lower()}{title[1:]}'


def _pages():
    """{page: [(unit title, [(slot, label, the place in words)])]} and {slot: (label, words, unit title, page)}."""
    pages, places = {}, {}
    for section, group, units in L.LINE_GROUPS:
        for n, (_short, slots) in enumerate(units, 1):
            title = UNIT_TITLES[group].format(n=n)
            row = [(slot, SLOT_LABELS.get(label, label), _words(group, title, label)) for slot, label in slots]
            pages.setdefault(section, []).append((title, row))
            for slot, label, words in row:
                places[slot] = (label, words, title, section)
    return pages, places


PAGE_UNITS, PLACES = _pages()


def moved_slots(base, st):
    """The places whose holder the draft `st` changes from `base`."""
    was, now = base.holders(), st.holders()
    return [slot for slot in lines.SLOTS if was.get(slot, []) != now.get(slot, [])]


def cap(text):
    return text[:1].upper() + text[1:]


def first(holders):
    return holders[0] if holders else None


class Rows:
    """A team's exhibitionrostertable rows as plain values (FIELDS), with the get / row / count overtime_core.lines
    reads and the setter it writes through: the roster's own (Rows.of), or the draft over them (LinesCtl.draft)."""

    def __init__(self, vals):
        self.vals = vals
        self.count = len(vals)

    @classmethod
    def of(cls, s, team):
        rows = s.rows[ROSTER]
        return cls([{f: rows[i].get(f, 0) for f in FIELDS} for i in s.team_entries.get(team, [])])

    def get(self, k, field):
        return self.vals[k][field]

    def row(self, k):
        return dict(self.vals[k])

    def set(self, _table, k, field, value):
        self.vals[k][field] = value

    def at(self):
        """{player: row}"""
        return {v['playerindex']: k for k, v in enumerate(self.vals)}

    def holders(self):
        """{slot: [player, ...]}"""
        out = {}
        for v in self.vals:
            for slot in lines.SLOTS:
                if v[slot]:
                    out.setdefault(slot, []).append(v['playerindex'])
        return out


class LinesCtl(Part):
    SLICES = {'lines': 'view'}
    CALLS = {'lines_section': 'lines_section', 'lines_slot': 'lines_slot', 'set_slot': 'set_slot',
             'set_captain': 'set_captain', 'auto_group': 'auto_group', 'auto_lines': 'auto_lines',
             'lines_apply': 'lines_apply', 'lines_undo': 'lines_undo'}
    TAB = 'lines'
    rail_unit = 'dressed'

    def __init__(self, ctl):
        super().__init__(ctl)
        self.held = {}          # rail team -> {(player, field): value}: the player's changes, not applied yet
        self.picked = None      # the place picked (Escape, a pick of the page or the team lets go of it)
        self.notes = {}         # rail team -> the note after Apply
        self.applied = Applied(ctl, TAB)
        self.noted = []         # [(change, team, {slot: new holder}, {player: letter})]: what Save keeps (My edits)

    # --- the rail's hooks --------------------------------------------------------------------------------------------
    def follow(self, team):
        self.picked = None
        self.ctl.changed('lines')

    def roster_changed(self):
        self.held, self.notes, self.picked = {}, {}, None
        self.applied.reset()
        self.noted = []

    def kept_of(self, ids):
        """[(team, {slot: holder}, {player: letter})] of the applied lines Save writes (changes `ids`), oldest first.
        Under the lock."""
        history = self.ctl.session.history
        self.noted = [n for n in self.noted if any(n[0] is h for h in history)]
        return [n[1:] for n in self.noted if id(n[0]) in ids]

    def dirty(self, team):
        return self.touched(team)

    def drafts(self):
        c = self.ctl
        with c.lock:
            codes = [self.code(t) for t in list(self.held) if self.touched(t)]
        return f"Lines not applied yet: {', '.join(codes)}." if codes else ''

    def rail_number(self, team):
        """How many players the team dresses (the draft's while it is changed); None (the rail's player count) for
        free agents and a team with no rows of its own (Seattle in the custom team only). Called under the lock."""
        s = self.ctl.session
        tid = team.get('id') if isinstance(team, dict) else team
        if s is None or tid == L.FREE_AGENTS or not s.team_entries.get(tid):
            return None
        if tid in self.held:
            n = sum(1 for v in self.draft(s, tid).vals if v[DRESSED])
        else:
            rows = s.rows[ROSTER]
            n = sum(1 for i in s.team_entries.get(tid, []) if rows[i][DRESSED])
        return {'text': str(n), 'tip': 'dressed'}

    # --- the team's lines ---------------------------------------------------------------------------------------------
    def code(self, team):
        chip = self.ctl.rail.chip(team)
        return chip['code'] if chip else str(team)

    @staticmethod
    def goalie(s, pi):
        _, b = s.bio(pi)
        return b is not None and b['position'] == GOALIE

    def why(self, s, team):
        """Why the tab cannot show this team's lines, or ''."""
        if team is None:
            return 'Pick a team in the list.'
        if team == L.FREE_AGENTS:
            return FREE_AGENTS
        entries = s.team_entries.get(team, [])
        if not entries:
            return SEATTLE_CUSTOM if team == SEATTLE else NO_LINES
        rows = s.rows[ROSTER]
        goalies = sum(1 for i in entries if self.goalie(s, rows[i]['playerindex']))
        skaters = len(entries) - goalies
        if goalies < NEED_GOALIES or skaters < NEED_SKATERS:
            return SHORT.format(f"{goalies} goalie{'s' if goalies != 1 else ''}, "
                                f"{skaters} skater{'s' if skaters != 1 else ''}")
        return ''

    def draft(self, s, team):
        """The team's rows with the player's changes on them."""
        st = Rows.of(s, team)
        held = self.held.get(team)
        if held:
            at = st.at()
            for (pi, f), v in held.items():
                if pi in at:
                    st.vals[at[pi]][f] = v
        return st

    def hold(self, s, team, st):
        """Keep what the draft `st` changes of the roster's rows (nothing: no draft)."""
        base = Rows.of(s, team)
        held = {(b['playerindex'], f): v[f] for b, v in zip(base.vals, st.vals) for f in FIELDS if v[f] != b[f]}
        if held:
            self.held[team] = held
        else:
            self.held.pop(team, None)

    def touched(self, team):
        """The team's draft differs from the roster."""
        s, held = self.ctl.session, self.held.get(team)
        if s is None or not held:
            return False
        rows = s.rows[ROSTER]
        for (pi, f), v in held.items():
            i = s.entry_row.get(pi)
            if i is not None and rows[i]['team'] == team and rows[i].get(f, 0) != v:
                return True
        return False

    @staticmethod
    def problems(holders):
        """The lineup's places that are not held by exactly one player, in words (shown; Apply still goes: the game
        plays an empty or shared place)."""
        out = []
        for slot in ES_SLOTS:
            n = len(holders.get(slot, []))
            if n == 0:
                out.append(f'{cap(PLACES[slot][1])} is empty.')
            elif n > 1:
                out.append(f'{cap(PLACES[slot][1])} has {n} players. Click it and pick the one who plays there.')
        return out

    @staticmethod
    def fits(pick, p, dressed, holders):
        """(whether the player can take the place picked, why not)."""
        if not pick:
            return False, ''
        if p['id'] in holders.get(pick, []):
            return False, 'He plays here now.'
        goalie = p['pos'] == 'G'
        if pick in GOALIE_SLOTS and not goalie:
            return False, 'Only goalies play in this place.'
        if pick not in GOALIE_SLOTS and goalie:
            return False, 'Goalies play only in goal.'
        if lines.GROUP_OF[pick] != lines.THREES and pick not in ES_SLOTS and not dressed:
            return False, 'Scratched: give him a place on the Even strength page first.'
        return True, ''

    # --- the slice ---------------------------------------------------------------------------------------------------
    def view(self):
        c = self.ctl
        with c.lock:
            s, team = c.session, c.team
            if s is None:       # no roster yet, or it is being read
                return why_view(c, None, 'lines', FREE_AGENTS, '')
            chip = c.rail.chip(team)
            head = {'id': team, 'view': chip, 'title': f"{chip['name']}: lines" if chip else 'Lines'}
            why = self.why(s, team)
            if why:
                return dict(head, why=why, tip=WHY_TIP)
            return dict(head, why=None, **self.page(s, team))

    def page(self, s, team):
        c = self.ctl
        page = c.lines_page if c.lines_page in PAGES else EVEN
        pick = self.picked if page != LETTERS and self.picked in PLACES else None
        base, st = Rows.of(s, team), self.draft(s, team)
        was, now = base.holders(), st.holders()
        people = {v['playerindex']: s.summary(v['playerindex']) for v in st.vals}

        def card(pi):
            p = people.get(pi)
            return {k: p[k] for k in ('id', 'name', 'pos', 'shoots', 'ovr', 'num')} if p else None
        units, places = [], {}
        for title, row in PAGE_UNITS.get(page, []):
            units.append({'title': title, 'slots': [
                {'slot': slot, 'label': label, 'full': words, 'player': card(first(now.get(slot))),
                 'picked': slot == pick, 'changed': now.get(slot, []) != was.get(slot, [])}
                for slot, label, words in row]})
            for slot, label, _words in row:
                for pi in now.get(slot, []):
                    places.setdefault(pi, []).append(f'{title} · {label}')
        letters = {v['playerindex']: v['captain'] for v in base.vals}
        players = []
        for v in st.vals:
            pi = v['playerindex']
            p = people[pi]
            dressed = bool(v[DRESSED])
            fits, why = self.fits(pick, p, dressed, now)
            players.append({'id': pi, 'name': p['name'], 'pos': p['pos'], 'shoots': p['shoots'], 'ovr': p['ovr'],
                            'num': p['num'], 'dressed': dressed, 'letter': LETTER.get(v['captain'], ''),
                            'where': ', '.join(places.get(pi, [])), 'places': places.get(pi, []),
                            'fits': fits, 'why': why, 'here': bool(pick) and pi in now.get(pick, []),
                            'letter_changed': v['captain'] != letters.get(pi)})
        players.sort(key=lambda p: (not p['dressed'], POS_ORDER.get(p['pos'], 5),
                                    -(p['ovr'] if isinstance(p['ovr'], int) else 0), p['name']))
        problems = self.problems(now)
        touched = self.touched(team)
        mine = bool(self.applied.mine(team))
        return {
            'page': page, 'pages': [{'id': p, 'label': p} for p in PAGES],
            'note': APPLIED if mine and self.notes.get(team) else LETTERS_RULE if page == LETTERS else PAGE_NOTES[page],
            'note_tone': 'good' if mine and self.notes.get(team) else '',
            'letters_rule': LETTERS_RULE, 'units': units,
            'players': [p for p in players if p['pos'] != 'G'] if page == LETTERS else players,
            'picked': pick, 'picked_label': PLACES[pick][1] if pick else '', 'can_empty': bool(pick and now.get(pick)),
            'dressed': sum(1 for p in players if p['dressed']), 'problems': problems,
            'touched': touched, 'can_apply': touched, 'mine': mine, 'can_undo': mine or touched,
            'can_auto': page != LETTERS,
            'auto_label': 'Deal all lines again' if page == EVEN else f'Deal the {page.lower()} again',
        }

    # --- calls -------------------------------------------------------------------------------------------------------
    def refuse(self, text, tone='caution'):
        self.ctl.say(text, tone)
        return {'error': text}

    def ready(self):
        """(session, team) when the tab shows the rail's team's lines, else None. Under the lock."""
        c = self.ctl
        if c.session is None or self.why(c.session, c.team):
            return None
        return c.session, c.team

    def lines_section(self, name):
        c = self.ctl
        with c.lock:
            if name not in PAGES:
                return {'error': 'There is no such page.'}
            c.lines_page = name
            self.picked = None
        c.changed('lines')
        return {'ok': True}

    def lines_slot(self, slot):
        """Pick a place (the same again lets go of it)."""
        c = self.ctl
        with c.lock:
            if slot not in PLACES or self.ready() is None or c.lines_page == LETTERS:
                return {'error': 'There is no such place here.'}
            self.picked = None if self.picked == slot else slot
        c.changed('lines')
        return {'ok': True}

    def set_slot(self, slot, ident=None):
        """Put a player (None: nobody) in a place of the draft: slot None is the place picked."""
        c = self.ctl
        with c.lock:
            ready = self.ready()
            if ready is None:
                return self.refuse(NO_TEAM)
            s, team = ready
            slot = slot or self.picked
            if slot not in PLACES:
                return self.refuse('Click a place first, then the player for it.')
            try:
                pi = None if ident in (None, '', -1, '-1') else int(ident)
            except (TypeError, ValueError):
                return self.refuse('That player is not on this team.')
            st = self.draft(s, team)
            if pi is not None:
                if pi not in st.at():
                    return self.refuse('That player is not on this team.')
                goalie = self.goalie(s, pi)
                if slot in GOALIE_SLOTS and not goalie:     # the game crashes on it (docs/notes/roster-checks.md)
                    return self.refuse('Only goalies play in that place.')
                if slot not in GOALIE_SLOTS and goalie:
                    return self.refuse('Goalies play only in goal.')
            try:
                lines.place({ROSTER: st}, team, slot, pi, setter=st.set)
            except lines.NotDressed:
                return self.refuse(f"{s.summary(pi)['name']} is scratched. Give him a place on the Even strength "
                                   'page first.')
            self.hold(s, team, st)
            self.picked = None
            self.notes.pop(team, None)
        c.changed('lines', 'rail')
        return {'ok': True}

    def set_captain(self, ident, value):
        """A player's letter in the draft: 0 none, 1 C, 2 A. A new C takes the C from the old one."""
        c = self.ctl
        with c.lock:
            ready = self.ready()
            if ready is None:
                return self.refuse(NO_TEAM)
            s, team = ready
            try:
                pi, value = int(ident), int(value)
            except (TypeError, ValueError):
                return self.refuse('Pick C, A or none.')
            if value not in LETTER:
                return self.refuse('Pick C, A or none.')
            st = self.draft(s, team)
            k = st.at().get(pi)
            if k is None:
                return self.refuse('That player is not on this team.')
            others = [j for j, v in enumerate(st.vals) if j != k and v['captain'] in (CAPTAIN, ALTERNATE)]
            kept = [j for j in others if st.vals[j]['captain'] != CAPTAIN] if value == CAPTAIN else others
            for j in others:
                if j not in kept:
                    st.vals[j]['captain'] = 0
            st.vals[k]['captain'] = value
            self.hold(s, team, st)
            self.notes.pop(team, None)
        c.changed('lines', 'rail')
        return {'ok': True}

    def auto_group(self, section=None):
        """Deal a page again by ratings, into the draft. Even strength deals every place of the team (after a
        question): the best 20 dress."""
        c = self.ctl
        with c.lock:
            ready = self.ready()
            if ready is None:
                return self.refuse(NO_TEAM)
            s, team = ready
            page = section or c.lines_page
            if page not in L.LINE_SECTIONS:
                return self.refuse('Pick a page with places first.')
            name = c.rail.chip(team)['name']
        if page != EVEN:
            return self.deal(team, page)
        ident = c.shell.ask('Deal all lines again?', [
            f'Every place on every page of {name} is dealt again by ratings, and the best 20 players dress.',
            'Nothing is written until you press Apply.'],
            [('Deal them again', 'deal', 'primary'), ('Cancel', 'cancel', 'plain')],
            {'deal': lambda: self.deal(team, EVEN) if c.team == team else None})     # the rail moved: nothing
        return {'ok': True, 'asked': ident}

    def auto_lines(self):
        """Beta1's Auto lines: every place of the rail's team dealt again by ratings (into the draft, no question)."""
        return self.deal(self.ctl.team, EVEN)

    def deal(self, team, page):
        """lines.build (Even strength) or lines.deal_groups (another page, from the players who dress), on the
        draft of `team`."""
        c = self.ctl
        with c.lock:
            s = c.session
            if s is None or self.why(s, team):
                return self.refuse(NO_TEAM)
            st = self.draft(s, team)
            at = st.at()
            everyone = lines.players_of(s.db, team)
            try:
                if page == EVEN:
                    dealt = lines.deal(everyone)
                else:
                    dealt = lines.deal([p for p in everyone if p.index in at and st.vals[at[p.index]][DRESSED]])
            except lines.NotEnoughPlayers:
                return self.refuse('Too few players dress for this page. Fill the Even strength page first.')
            want = set(lines.SLOTS) if page == EVEN else {
                slot for group in L.LINE_SECTIONS[page] for slot in lines.GROUPS[group]}
            holds = {}
            for slot, p in dealt.items():
                if slot in want:
                    holds.setdefault(p.index, set()).add(slot)
            old = [dict(v) for v in st.vals]
            for v in st.vals:
                mine = holds.get(v['playerindex'], set())
                for slot in want:
                    v[slot] = int(slot in mine)
                if page == EVEN:
                    v[DRESSED] = int(bool(mine))
            moved = old != st.vals
            self.hold(s, team, st)
            self.picked = None
            self.notes.pop(team, None)
        what = 'Every line' if page == EVEN else f'The {page.lower()}'
        c.say(f'{what} is dealt again by ratings. Check it, then Apply.' if moved
              else 'Dealt again by ratings: nothing changed.', 'info')
        c.changed('lines', 'rail')
        return {'ok': True}

    def describe(self, s, team, base, st):
        """(My edits' label, the Details' lines) of what the draft changes."""
        code = self.code(team)
        was, now = base.holders(), st.holders()
        moved = [slot for slot in lines.SLOTS if was.get(slot, []) != now.get(slot, [])]
        lettered = [(b['playerindex'], b['captain'], v['captain'])
                    for b, v in zip(base.vals, st.vals) if b['captain'] != v['captain']]

        def name(pi):
            return s.summary(pi)['name'] if pi is not None else 'nobody'
        details = [(f'{code} {PLACES[slot][1]}', name(first(was.get(slot))), name(first(now.get(slot))))
                   for slot in moved]
        details += [(f'{name(pi)}: letter', LETTER.get(old) or 'none', LETTER.get(new) or 'none')
                    for pi, old, new in lettered]
        if len(moved) == 1 and not lettered:
            who, words = first(now.get(moved[0])), PLACES[moved[0]][1]
            return (f'{name(who)} to {words}' if who is not None else f'{cap(words)} left empty'), details
        parts = []
        if moved:
            parts.append(f"{len(moved)} place{'s' if len(moved) != 1 else ''}")
        if lettered:
            parts.append(f"{len(lettered)} letter{'s' if len(lettered) != 1 else ''}")
        return (f"{' and '.join(parts)} changed" if parts else 'Who dresses changed'), details

    def lines_apply(self):
        """Write the team's draft into the roster as one change (My edits)."""
        c = self.ctl
        with c.lock:
            ready = self.ready()
            if ready is None:
                return self.refuse(NO_TEAM)
            s, team = ready
            if not self.touched(team):
                return self.refuse('Nothing to apply: change a place or a letter first.', 'info')
            base, st = Rows.of(s, team), self.draft(s, team)
            label, details = self.describe(s, team, base, st)
            rows = list(s.team_entries.get(team, []))       # Rows.of's order
            values = {}

            def work(setter):
                for i, b, v in zip(rows, base.vals, st.vals):
                    for f in FIELDS:
                        if v[f] != b[f]:
                            setter(ROSTER, i, f, v[f])
                            values[(b['playerindex'], f)] = (b[f], v[f])
            try:
                ch, _ = s.edit(label, work)
            except EditError as err:
                return self.refuse(str(err), 'bad')
            ch.tab, ch.team = TAB, team
            ch.details += details
            self.applied.note(ch, values)
            now = st.holders()
            self.noted.append((ch, team, {slot: first(now[slot]) for slot in moved_slots(base, st) if now.get(slot)},
                               {b['playerindex']: v['captain'] for b, v in zip(base.vals, st.vals)
                                if b['captain'] != v['captain']}))
            self.held.pop(team, None)
            self.picked = None
            self.notes[team] = APPLIED
            c.issues = None
            code, name = self.code(team), c.rail.chip(team)['name']
        c.host.log(f'{code} lines: {label}.')
        for what, old, new in details:
            c.host.log(f'  {what}: {old} -> {new}')
        c.say(f'{name}: lines applied. Save the roster to keep them.', 'good')
        c.changed('lines', 'rail', 'save', 'editor')
        return {'ok': True}

    def lines_undo(self):
        """Take back my lines: the draft goes, and the team's applied lines that are not saved yet are taken back."""
        c = self.ctl
        with c.lock:
            ready = self.ready()
            if ready is None:
                return self.refuse(NO_TEAM)
            s, team = ready
            touched = self.touched(team)
            self.held.pop(team, None)
            self.picked = None
            self.notes.pop(team, None)
            code, name = self.code(team), c.rail.chip(team)['name']

            def restore(setter, values):
                rows = s.rows[ROSTER]
                for (pi, f), (old, new) in values.items():
                    i = s.entry_row.get(pi)
                    if i is not None and rows[i]['team'] == team and rows[i].get(f) == new:
                        setter(ROSTER, i, f, old)
            try:
                back = self.applied.take_back(team, f'{name}: lines taken back', restore)
            except EditError as err:
                return self.refuse(str(err), 'bad')
            if back is not None:
                c.issues = None
        if back is None and not touched:
            c.say('Nothing to take back on this team.', 'info')
            return {'ok': False}
        if back is not None:
            c.host.log(f'{code} lines: taken back.')
            c.say("Your lines are taken back. The team plays the roster's lines again.", 'info')
        else:
            c.say('Your changes are dropped.', 'info')
        c.changed('lines', 'rail', 'save', 'editor')
        return {'ok': True}

    # --- beta1's snapshot --------------------------------------------------------------------------------------------
    def snap_lines(self):
        """Beta1's lines snapshot (the draft's lines while the team has one)."""
        c = self.ctl
        with c.lock:
            s = c.session
            if s is None or c.team is None or c.team == L.FREE_AGENTS:
                return {'ready': False}
            st = self.draft(s, c.team)
            holders = st.holders()
            dressed = {v['playerindex']: bool(v[DRESSED]) for v in st.vals}
            page = c.lines_page
            mine = {}  # playerindex -> places on this page ("PP1 LW")
            groups = []
            for section, title, units in L.LINE_GROUPS:
                if section == page:
                    for lab, slots in units:
                        for sl, sl_lab in slots:
                            for p in holders.get(sl, []):
                                mine.setdefault(p, []).append(f'{lab} {sl_lab}')
                groups.append({'section': section, 'title': title, 'units': [
                    {'label': lab, 'slots': [{'slot': sl, 'label': sl_lab, 'holders': holders.get(sl, []),
                                              'goalie': sl in GOALIE_SLOTS,
                                              'required': sl in ES_SLOTS}
                                             for sl, sl_lab in slots]} for lab, slots in units]})
            players = []
            for p in s.players_of(c.team):
                sm = s.summary(p)
                players.append({'id': p, 'label': f"{sm['pos']} #{sm['num']} {sm['name']}", 'pos': sm['pos'],
                                'goalie': sm['pos'] == 'G', 'ovr': sm['ovr'], 'cap': sm['cap'], 'name': sm['name'],
                                'num': sm['num'], 'dressed': dressed.get(p, False),
                                'where': ', '.join(mine.get(p, []))})
            return {'ready': True, 'team': c.team, 'team_name': s.team_name(c.team), 'players': players,
                    'groups': groups, 'page': page, 'pages': list(PAGES),
                    'problems': lines.check_lineup({ROSTER: st}, c.team)}
