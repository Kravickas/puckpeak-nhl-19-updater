"""Roster: the rail's team's players (or the players found in every league) and the picked player's card.
docs/ui/roster.md.

The rail picks the team (Controller.team); this part keeps the search, the picked player, the typed values of the
players not on screen (roster_keep, a refused Apply) and each player's applied edits (roster_card.Edits: the card's
"Undo my edit" and the windows' "Take back" take back his own). The card's values, checks and writing are in
roster_card; the Face & type and Equipment windows are faces_ctl and gear_ctl, which add their edits here.
Save keeps the edits it writes in edits.json (myedits: My edits, put back after every update): `to_keep` under Save's
lock, `kept_saved` after a good save.
Beta1's player calls (search, pick_player, apply, undo, snap_editor) stay for the tests and tools.
"""
import copy

from overtime_core import faces as F, equipment as EQ

from . import labels as L, myedits, roster_card as RC
from .rail import COACHELLA, SEATTLE
from .registry import Part
from .session import EditError

SHOWN = 150     # the list shows the best 150 of a search
SEATTLE_CUSTOM = ("This roster keeps Seattle's players in the game's custom team only. Run the update on the Update "
                  'tab to edit them here.')
SEATTLE_COPY = {'text': 'Seattle copy', 'tip': 'His Season and Franchise card. Seattle in the Teams list holds his '
                                               'Play Now card.'}
COPY_NOTES = {
    'seattle': 'Seattle copy: his Season and Franchise card (the expansion Franchise lists him as a free agent). Edits '
               'here change Season and Franchise. Seattle in the Teams list holds his Play Now card.',
    'coachella': "Coachella Valley plays in Season and Franchise only: NHL 19's Play Now has no place for it. The "
                 'expansion Franchise starts it empty, its players as free agents.',
    'play_now': 'His Play Now card. His Season and Franchise card is on the free agent list (Seattle copy). Edits here '
                'change Play Now and that card alike.',
}
CONTRACT = {'enabled': False, 'title': 'Comes later: cap hit, years and clauses in one window.'}
LETTER_WORDS = {1: 'Captain', 2: 'Alternate'}
POS_ORDER = RC.POS_ORDER


class RosterCtl(Part):
    SLICES = {'roster': 'view', 'roster_card': 'card_view'}
    CALLS = {'roster_search': 'search', 'roster_player': 'player', 'roster_apply': 'apply',
             'roster_undo': 'roster_undo', 'roster_keep': 'keep',
             'search': 'search', 'player': 'pick_player', 'apply': 'apply', 'undo': 'undo'}
    TAB = 'roster'

    def __init__(self, ctl):
        super().__init__(ctl)
        self._kept = None           # edits.json (myedits), read when first needed
        self._fresh()

    def _fresh(self):
        self.edits = RC.Edits()     # each player's applied edits
        self.saved_items = []       # the edits Save kept in edits.json since this roster was opened
        self.typed = {}             # {pi: values} typed, not applied (roster_keep, a refused Apply)
        self.problems = {}          # {pi: [{key, text}]} of his last refused Apply
        self.version = 0            # the card's key: Python filled it again (the page resets its typed values)
        self.seen = None            # the rail team the list last followed
        self._names = (None, {})    # (session, {pi: plain name}) for the search
        self._clock = (None, None)  # (session, roster_card.Clock)

    # --- the rail's follower -----------------------------------------------------------------------------------------
    def follow(self, team):
        """The rail picked a team (the rail cleared the search): the list shows it and its first player is picked.
        The same team again (the tab shown again) keeps the pick."""
        c = self.ctl
        with c.lock:
            if c.session is not None and (team != self.seen or c.player is None):
                self.seen = team
                rows = self.team_rows(c.session, team)
                c.player = rows[0] if rows else None
        c.changed('roster', 'roster_card')

    def hide(self):
        c = self.ctl
        with c.lock:
            c.parts['faces'].open = None
            c.parts['gear'].open = None
        c.changed('roster_face', 'roster_gear')

    def roster_changed(self):
        c = self.ctl
        c.player = None
        c.card_error = ''
        self._fresh()

    def dirty(self, team):
        """Typed or picked for a player of this rail team, not applied yet (the card, the two windows)."""
        c = self.ctl
        s = c.session
        if s is None:
            return False
        held = set(self.typed) | set(c.parts['faces'].picks) | set(c.parts['gear'].picks)
        return any(RC.rail_team(s, pi) == team for pi in held)

    def drafts(self):
        c = self.ctl
        with c.lock:
            s = c.session
            if s is None:
                return ''
            items = ([f'the card of {self.who(s, pi)}' for pi in self.typed]
                     + [f'Face & type of {self.who(s, pi)}' for pi in c.parts['faces'].picks]
                     + [f'Equipment of {self.who(s, pi)}' for pi in c.parts['gear'].picks])
        return f"Roster, not applied yet: {', '.join(items)}." if items else ''

    # --- helpers the windows share ----------------------------------------------------------------------------------
    @staticmethod
    def who(s, pi):
        _, b = s.bio(pi)
        return s.name(b) if b else 'a player'

    def clock(self, s):
        """The roster's Clock, made again after a change of the whole roster (an update moves its birth dates)."""
        key = (s, sum(1 for ch in s.history if ch.kept is not None), self.ctl.upd_season)
        if self._clock[0] != key:
            self._clock = (key, RC.Clock(s, RC.roster_shift(s.db, self.ctl.upd_season)))
        return self._clock[1]

    def names(self, s):
        """{pi: plain name} for roster_card.find, kept while the roster's history stays the same."""
        key = (s, len(s.history), id(s.history[-1]) if s.history else None)
        if self._names[0] != key:
            self._names = (key, {})
        return self._names[1]

    def unsaved(self):
        """ids of the changes Save has not written yet (not taken back). Under the lock."""
        return {id(ch) for ch, undone in self.ctl.parts['save'].pending() if not undone}

    def mine(self, pi, what=None):
        self.edits.prune(self.ctl.session.history)
        return self.edits.of(pi, self.unsaved(), what)

    def note(self, ch, pi, what, short, keys, ident=None, kept=None):
        """A change the tab (the card or a window) applied for player pi: My edits' chips and his own history.
        `ident`: who he was before it (myedits.identity; default: who he is now); `kept`: what edits.json keeps of it
        (default `keys`: the card's fields; a window's choices and face parts)."""
        s = self.ctl.session
        ch.tab, ch.team = 'Roster', RC.rail_team(s, pi)
        self.edits.add(ch, pi, what, short, keys, ident or myedits.identity(s, self.clock(s), pi), kept)
        self.version += 1

    # --- My edits kept for every update (edits.json) ----------------------------------------------------------------
    def kept(self):
        """edits.json as the app knows it (myedits.load the first time)."""
        if self._kept is None:
            self._kept = myedits.load()
        return self._kept

    def to_keep(self, written):
        """(edits.json as it is after a save of `written`, the edits it keeps): the edits Save writes are kept with his
        values now, saved ones taken back since are dropped. Nothing is written here. Under the lock."""
        s = self.ctl.session
        ids = {id(ch) for ch in written}
        self.edits.prune(s.history)
        live = [it for it in self.edits.items if id(it['ch']) in ids]
        gone = [it for it in self.saved_items if id(it['ch']) not in ids]
        kept_before = {id(it['ch']) for it in self.saved_items}
        data = copy.deepcopy(self.kept())
        clock = self.clock(s)
        myedits.forget(data, s, clock, gone)
        # only the edits not kept yet: one kept before keeps its value (an update since may have refused it)
        myedits.record(data, s, clock, [it for it in live if id(it['ch']) not in kept_before])
        for team, slots, letters in self.ctl.parts['lines'].kept_of(ids):
            myedits.record_lines(data, s, clock, team, slots, letters)
        return data, live

    def kept_saved(self, data, live):
        """The save went well: edits.json is `data` now (to_keep). Under the lock."""
        self._kept, self.saved_items = data, list(live)
        try:
            myedits.save(data)
        except OSError as err:
            self.ctl.host.log(f'My edits could not be kept: {err}')

    def kept_remove(self, key):
        """My edits' Remove: that player's kept edit goes (the roster keeps what it has). Returns his name or ''.
        Under the lock."""
        e = (self.kept()['lines'].get(key[len(myedits.LINES):]) if key.startswith(myedits.LINES)
             else self.kept()['players'].get(key))
        if e is None:
            return ''
        data = copy.deepcopy(self.kept())
        myedits.remove(data, key)
        myedits.save(data)
        self._kept = data
        return e.get('label') or e['id']['last']

    def take_back(self, pi, what=None):
        """Take back his applied edits (of one kind, or all of them: only the newest), newest first. Returns (taken,
        the label of a newer change in the way or ''). Under the lock."""
        s = self.ctl.session
        todo = self.mine(pi, what)
        if what is None:
            todo = todo[-1:]
        taken = 0
        for it in reversed(todo):
            blocked = RC.take_back(s, it['ch'])
            if blocked:
                return taken, blocked
            taken += 1
        self.edits.prune(s.history)
        self.version += 1
        return taken, ''

    # --- the list ----------------------------------------------------------------------------------------------------
    @staticmethod
    def ovr_of(s, pi):
        _, b = s.bio(pi)
        _, _, ai = s.ai(b)
        return (ai.get('skill_overall', ai.get('c_overall', 0)) or 0) if ai else 0

    def team_rows(self, s, team):
        """His team's players: C, LW, RW, D, G, then the best first."""
        pis = s.players_of(team) if team is not None else []
        return sorted(pis, key=lambda pi: (self._pos(s, pi), -self.ovr_of(s, pi), self.who(s, pi)))

    @staticmethod
    def _pos(s, pi):
        _, b = s.bio(pi)
        return b['position'] if b else 9

    def found(self, s, query):
        """Every league's players whose name holds the typed words: the best first, then by name, then the league
        order (a club's own card before its copies)."""
        order = {lg: k for k, (lg, _l, _n) in enumerate(s.leagues())}

        def league(pi):
            t = RC.rail_team(s, pi)
            i = s.team_row.get(t)
            return order.get(s.rows['exhibitionteams'][i]['league'], 98) if i is not None else 99
        pis = RC.find(s, query, self.names(s))
        return sorted(pis, key=lambda pi: (-self.ovr_of(s, pi), self.who(s, pi), league(pi), pi))

    def row(self, s, pi, searching, unsaved, sea):
        c = self.ctl
        sm = s.summary(pi)
        _, b = s.bio(pi)
        _, _, ai = s.ai(b)
        dollars = (b or {}).get('contractdollars') or 0
        goalie = bool(b) and b['position'] == L.GOALIE
        style = F.type_name(ai.get(F.STYLE), goalie) if ai else None
        words = list(dict.fromkeys(w for it in self.edits.of(pi, unsaved) for w in it['short']))
        team = RC.rail_team(s, pi)
        return {'id': pi, 'pos': sm['pos'], 'num': sm['num'], 'name': sm['name'], 'cap': sm['cap'],
                'age': self.clock(s).age(b) if b else '', 'shoots': sm['shoots'], 'nat': sm['nat'],
                'type': style[0] if style else '', 'ovr': sm['ovr'],
                'salary': dollars * L.CONTRACT_UNIT / 1e6 if dollars else 0,
                'team': c.rail.chip(team) if searching else None,
                'note': f"Edited: {', '.join(words)}" if words else '', 'tag': 'edited' if words else '',
                'copy': dict(SEATTLE_COPY) if RC.copy_kind(s, pi, sea) == 'seattle' else None}

    def view(self):
        c = self.ctl
        with c.lock:
            s = c.session
            if s is None:
                return {'loaded': False, 'busy': bool(c.busy)}
            query = c.query
            searching = bool(query.strip())
            pis = self.found(s, query) if searching else self.team_rows(s, c.team)
            team = c.rail.chip(c.team)
            if searching:
                title = f'{len(pis)} found for "{query.strip()}"'
                count = f'the best {SHOWN} shown' if len(pis) > SHOWN else 'every league'
                empty = 'Nobody by that name. Check the spelling, or type part of the last name.'
            else:
                title = team['name'] if team else 'Pick a team'
                count = f'{len(pis)} players' if len(pis) != 1 else '1 player'
                empty = 'No players on this team.' if team else 'Pick a team in the list.'
                if c.team == SEATTLE and not pis:   # the rail counts the custom team's players (Rail.listed)
                    empty = SEATTLE_CUSTOM
            note = ''
            if not searching and c.team == L.FREE_AGENTS:
                note = 'Free agents. Edit one here. Signing him to a team comes later.'
            elif not searching and c.team == SEATTLE:
                note = 'Seattle is added by Overtime. Most Kraken have a generic head: give them a face in Face & type.'
            elif not searching and c.team == COACHELLA:
                note = COPY_NOTES['coachella']
            unsaved, sea = self.unsaved(), RC.seattle_rows(s)
            return {
                'loaded': True, 'busy': bool(c.busy), 'team': team, 'query': query, 'searching': searching,
                'title': title, 'count': count, 'rows': [self.row(s, p, searching, unsaved, sea) for p in pis[:SHOWN]],
                'selected': c.player, 'empty': empty, 'note': note,
            }

    # --- the card ----------------------------------------------------------------------------------------------------
    def card_view(self):
        c = self.ctl
        with c.lock:
            s = c.session
            if s is None or c.player is None:
                return None
            pi = c.player
            _, b = s.bio(pi)
            if b is None:
                return None
            clock = self.clock(s)
            _, e = s.entry(pi)
            _, _, ai = s.ai(b)
            goalie = b['position'] == L.GOALIE
            team = RC.rail_team(s, pi)
            free = team == L.FREE_AGENTS
            values = RC.values(s, clock, pi)
            style = ai.get(F.STYLE) if ai else None
            name = F.type_name(style, goalie)
            summary = L.GOALIE_SUMMARY if goalie else L.SKATER_SUMMARY
            kind = RC.copy_kind(s, pi)
            chip = c.rail.chip(team) if not free else None
            copy_note = COPY_NOTES.get(kind, '')
            if kind == 'copy' and chip:
                copy_note = f"The game keeps his {chip['name']} card apart from his club's. Edits here change only " \
                            'this one.'
            mine = self.mine(pi)
            last = mine[-1] if mine else None
            countries = sorted(([k, v] for k, v in L.COUNTRIES.items()), key=lambda kv: kv[1])
            if not any(n == values['country'] for n, _v in countries):
                countries.insert(0, [values['country'], L.country(values['country'])])
            face = F.read(b)
            generic = face['head'] >= F.GENERIC
            gear, gear_note = self.gear_lines(s, b)
            note = [values['pos'], f"#{values['num']}", LETTER_WORDS.get(values['captain'], '')]
            return {
                'key': f'{pi}:{self.version}:{len(s.history)}', 'id': pi,
                'kind': 'goalie' if goalie else 'skater', 'goalie': goalie,
                'title': s.name(b), 'note': ' · '.join(w for w in note if w),
                'team': chip, 'free_agent': free, 'copy_note': copy_note,
                'ovr': self.ovr_of(s, pi), 'age': clock.age(b),
                'type': {'value': style, 'label': F.type_label(style, goalie) if name else 'None',
                         'short': name[0] if name else ''},
                'summary': [{'label': label, 'value': ai[f]} for f, label in summary if ai and f in ai],
                'values': values,
                'typed': self.typed.get(pi),
                'problems': self.problems.get(pi, []),
                'edited': list(dict.fromkeys(k for it in mine for k in it['keys'])),
                'rating_groups': [{'title': g['title'], 'items': g['items']} for g in RC.rating_groups(s, b)],
                'choices': {'positions': ['G'] if goalie else list(L.SKATER_POSITIONS), 'countries': countries,
                            'letters': [[0, 'None'], [1, 'C'], [2, 'A']]},
                'locked': {'captain': 'A free agent has no letter.' if free else ''},
                'face': {'text': f"Generic head {face['head']}" if generic else f"His own face (head {face['head']})",
                         'colours': f"Skin {face['skin']} · eyes {face['eyes']}", 'generic': generic,
                         'hint': 'The game draws a stand-in face. Give him a real one in Face & type.' if generic
                         else ''},
                'gear': gear, 'gear_note': gear_note,
                'waiting': [w for w, part in (('Face & type', 'faces'), ('Equipment', 'gear'))
                            if pi in c.parts[part].picks],
                'can_undo': last is not None,
                'undo_label': f"Take back: {', '.join(last['short'])}" if last else 'Nothing to take back',
                'contract': dict(CONTRACT), 'made_up': False, 'busy': bool(c.busy),
            }

    @staticmethod
    def gear_lines(s, b):
        """([{label, value}] of his first four models, a note when he has no equipment record)."""
        kind = EQ.kind_of(b['position'])
        try:
            row = EQ.row_of(s.db, b['game_id'], kind)
        except KeyError:
            row = None
        if row is None:
            return [], 'He has no equipment record.'
        values = EQ.read(s.db, row, kind)
        out = []
        for k, (_f, label, names) in EQ.KINDS[kind][1].items():
            if names is None:
                continue
            out.append({'label': label, 'value': dict(EQ.options(kind, k, values[k])).get(values[k], str(values[k]))})
            if len(out) == 4:
                break
        return out, ''

    # --- the calls ---------------------------------------------------------------------------------------------------
    def search(self, text):
        """Every league by name ('' = the team again); the first hit is picked when the pick is not in the list."""
        c = self.ctl
        with c.lock:
            c.query = str(text or '')
            s = c.session
            if s is not None:
                pis = self.found(s, c.query)[:SHOWN] if c.query.strip() else self.team_rows(s, c.team)
                if pis and c.player not in pis:
                    c.player = pis[0]
        c.changed('roster', 'roster_card')

    def pick_player(self, ident, typed=None):
        c = self.ctl
        if typed and c.player is not None:
            reply = self.apply(typed)
            if reply and reply.get('error'):
                return reply
        with c.lock:
            c.player = int(ident)
            c.card_error = ''
        c.changed('editor')
        return None

    def player(self, ident, draft=None):
        """roster_player(id, draft {id, values} | null): the draft is the old player's typed card, applied first."""
        c = self.ctl
        try:
            ident = int(ident)
        except (TypeError, ValueError):
            return {'ok': False}
        typed = draft.get('values') if isinstance(draft, dict) and draft.get('id') == c.player \
            and ident != c.player else None
        reply = self.pick_player(ident, typed)
        return {'ok': False, 'problems': reply.get('problems', [])} if reply else {'ok': True}

    def keep(self, ident, values=None):
        """roster_keep(id, values | null): typed values of a player not on screen, kept when they differ from his card
        or are wrong; null forgets them."""
        c = self.ctl
        with c.lock:
            s = c.session
            try:
                pi = int(ident)
            except (TypeError, ValueError):
                return {'ok': False}
            if s is None or s.bio(pi)[1] is None:
                return {'ok': False}
            changes, problems = RC.check(s, self.clock(s), pi, values) if isinstance(values, dict) else ([], [])
            if changes or problems:
                self.typed[pi] = values
            else:
                self.typed.pop(pi, None)
                self.problems.pop(pi, None)
            kept = pi in self.typed
        c.changed('roster_card', 'rail')
        return {'ok': True, 'kept': kept}

    def apply(self, values):
        """Check every field, then apply them as one change. {ok, changes} or {ok: false, problems, error}."""
        c = self.ctl
        with c.lock:
            s = c.session
            if not s or c.player is None:
                return {'ok': False, 'problems': [], 'error': 'No player is open.'}
            pi = c.player
            clock = self.clock(s)
            changes, problems = RC.check(s, clock, pi, values or {})
            if not problems and changes:
                try:
                    ch, words = self._write(s, clock, pi, changes)
                except EditError as err:
                    problems = [{'key': '', 'text': str(err)}]
            if problems:
                self.typed[pi] = values
                self.problems[pi] = problems
                self.version += 1
                c.card_error = text = f'{self.who(s, pi)}: {problems[0]["text"]}'
            else:
                self.typed.pop(pi, None)
                self.problems.pop(pi, None)
                c.card_error = ''
                c.issues = None
                if not changes:
                    self.version += 1
        if problems:
            c.say(text, 'bad')
            c.changed('roster_card', 'rail')
            return {'ok': False, 'problems': problems, 'error': text}
        if changes:
            for what, old, new in ch.details:
                c.host.log(f'  {what}: {old} -> {new}')
            c.say(f'{ch.label}. Not saved yet: press Save when you are done.', 'good')
        else:
            c.say('Nothing changed: the card already has these values.', 'info')
        c.changed('editor', 'lines', 'save')
        return {'ok': True, 'changes': len(changes)}

    def _write(self, s, clock, pi, changes):
        """One change of the roster for checked card values. Returns (Change, words). Under the lock."""
        before, ovr = self.who(s, pi), self.ovr_of(s, pi)
        ident = myedits.identity(s, clock, pi)
        rated = any(k.startswith('ratings.') for k, _o, _n in changes)
        _, b = s.bio(pi)
        table, _r, _ai = s.ai(b)
        model = self.ctl.editors._model(s, table) if rated and table else None
        ch, lost = s.edit(f'Edit {before}', lambda setter: RC.write(s, clock, pi, changes, setter, model))
        who = self.who(s, pi)
        words = RC.change_words(changes)
        now = self.ovr_of(s, pi)
        if now != ovr:
            words.append(f'overall {ovr} to {now}')
        ch.label = f"{who}: {', '.join(words)}" + (f' ({lost} loses the C)' if lost else '')
        for k, old, new in changes:
            if k.startswith('ratings.'):
                ch.details.append((f'{who}: {L.rating_label(k[len("ratings."):]).lower()}', old, new))
            else:
                ch.details.append((f'{who}: {RC.WORDS[k]}', RC.shown(k, old), RC.shown(k, new)))
        self.note(ch, pi, 'card', RC.change_short(changes), [k for k, _o, _n in changes], ident)
        return ch, words

    def undo(self):
        """Beta1's Undo: the roster's newest change (My edits has it now)."""
        c = self.ctl
        with c.lock:
            if not c.session:
                return
            ch = c.session.undo()
            c.issues = None
            self.edits.prune(c.session.history)
            self.version += 1
        if ch:
            c.host.log(f'Undo: {ch.label}')
            c.say(f'Undone: {ch.label}', 'info')
            if ch.kept is not None:
                with c.lock:
                    c.upd_report = None
                    c.upd_steps['apply'] = {'state': 'idle', 'text': ''}
                    c.upd_steps['verify'] = {'state': 'idle', 'text': ''}
        c.changed('editor', 'lines', 'save', 'update', 'strategy', 'calendar')

    def roster_undo(self, what='applied'):
        """'typed': forgets the picked player's typed values; 'applied': takes back his newest applied edit."""
        c = self.ctl
        with c.lock:
            s = c.session
            if s is None or c.player is None:
                c.say('Pick a player first.', 'caution')
                return {'ok': False}
            pi = c.player
            who = self.who(s, pi)
            if what == 'typed':
                self.typed.pop(pi, None)
                self.problems.pop(pi, None)
                c.card_error = ''
                self.version += 1
                text, tone, ok = f"What you typed on {who}'s card is gone. Nothing was applied.", 'info', True
            else:
                mine = self.mine(pi)
                if not mine:
                    text, tone, ok = f'Nothing to take back for {who}.', 'caution', False
                else:
                    taken, blocked = self.take_back(pi)
                    short = ', '.join(mine[-1]['short'])
                    if blocked:
                        text, tone, ok = f'{who}: take back "{blocked}" first (My edits). It changed him later.', \
                            'caution', False
                    else:
                        text, tone, ok = f"Taken back: {who}'s {short}.", 'good', True
                        c.issues = None
        c.say(text, tone)
        c.changed('editor', 'lines', 'save', 'roster_face', 'roster_gear')
        return {'ok': ok}

    def snap_editor(self):
        c = self.ctl
        with c.lock:
            s = c.session
            if s is None:
                return {'loaded': False, 'busy': bool(c.busy), 'text': c.busy or 'Pick a roster in Setup first.'}
            searching = bool(c.query.strip())
            pis = s.search(c.query) if searching else (s.players_of(c.team) if c.team is not None else [])
            rows = [s.summary(p) for p in pis]
            card = s.card(c.player) if c.player is not None else None
            return {
                'loaded': True, 'busy': bool(c.busy), 'roster': s.source_name,
                'leagues': [{'id': lg, 'label': lab, 'count': n} for lg, lab, n in s.leagues()],
                'league': c.league, 'teams': s.teams(c.league), 'team': c.team,
                'team_name': s.team_name(c.team) if c.team is not None else '',
                'rows': rows, 'selected': c.player, 'query': c.query, 'searching': searching,
                'card': card, 'card_error': c.card_error,
                'countries': sorted(([k, v] for k, v in L.COUNTRIES.items()), key=lambda kv: kv[1]),
                'edits': len(s.change_lines()), 'can_undo': bool(s.history),
                'undo_label': s.history[-1].label if s.history else '',
            }
