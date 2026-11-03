"""An open roster: the exhibition tables of a t3db database, with readable views, edits, undo and verify.

Edits go straight into the `tdb.Database` (which writes byte-exact); every change keeps the old bytes of each
record it touched, so Undo puts back exactly what was there. Facts about the fields: app/labels.py and
docs/notes/roster-format.md.
"""
import datetime
from dataclasses import dataclass, field

from overtime_core import lines, teams as T
from overtime_core.rosterupdate import CUSTOM_ROSTER
from overtime_core.roster import ALTERNATE, CAPTAIN, GOALIE_SLOTS, Roster

from . import labels as L

TEAMS, ROSTER, PLAYERS, BIOS = 'exhibitionteams', 'exhibitionrostertable', 'exhibitionplayers', 'exhibitionplayerbiotable'
SKATERS, GOALIES, FREE = 'exhibitionskaterai', 'exhibitiongoalieai', 'exhibitionfreeagents'
TABLES = (TEAMS, ROSTER, PLAYERS, BIOS, SKATERS, GOALIES, FREE)


class EditError(ValueError):
    """An edit the game would not accept; nothing was changed."""


@dataclass
class Change:
    label: str
    snaps: dict = field(default_factory=dict)  # (table, row) -> record bytes before the change
    details: list = field(default_factory=list)  # (what, old, new) as shown to the user
    kept: tuple = None  # the whole database before a bulk change (tdb.Database.keep)
    # where it was made, for My edits' chips and the rail's dot: the part that made it may set these; Save (save_ctl)
    # sets the rest when it first sees the change (the tab in view and the rail's team then)
    tab: str = None     # the tab's label ('Roster', 'Lines', ...)
    team: int = None    # the rail id of the team it belongs to (None: no one team, e.g. the update)


def clean(s):
    return ''.join(ch for ch in s if ch.isprintable()).strip()


class RosterSession:
    def __init__(self, db, source_name='roster', today=None):
        missing = [t for t in TABLES if t not in db]
        if missing:
            raise ValueError('not a roster: no ' + ', '.join(missing))
        self.db = db
        self.source_name = source_name
        self.today = today or datetime.date.today()
        self.rows = {t: db[t].rows() for t in TABLES}
        self.history = []  # Change list, oldest first (Undo takes the newest)
        self._index()

    # --- indexes ---------------------------------------------------------------------------------
    def _index(self):
        r = self.rows
        self.player_row = {p['index']: i for i, p in enumerate(r[PLAYERS])}
        self.bio_row = {b['game_id']: i for i, b in enumerate(r[BIOS])}
        self.skater_row = {s['game_id']: i for i, s in enumerate(r[SKATERS])}
        self.goalie_row = {g['game_id']: i for i, g in enumerate(r[GOALIES])}
        self.entry_row = {}
        self.team_entries = {}
        for i, e in enumerate(r[ROSTER]):
            self.entry_row[e['playerindex']] = i
            self.team_entries.setdefault(e['team'], []).append(i)
        self.team_row = {t['index']: i for i, t in enumerate(r[TEAMS])}
        self.free_agents = [f['playerindex'] for f in r[FREE]]

    # --- reading ----------------------------------------------------------------------------------
    def bio(self, pi):
        """(bio row index, bio dict) of exhibitionplayers index `pi`, or (None, None)."""
        prow = self.player_row.get(pi)
        if prow is None:
            return None, None
        p = self.rows[PLAYERS][prow]
        if p['table'] != 0:
            return None, None
        b = self.bio_row.get(p['playerid'])
        return (b, self.rows[BIOS][b]) if b is not None else (None, None)

    def ai(self, bio):
        """(table name, row index, dict) of a player's ratings, or (None, None, None)."""
        if bio is None:
            return None, None, None
        if bio['position'] == L.GOALIE:
            i = self.goalie_row.get(bio['game_id'])
            return (GOALIES, i, self.rows[GOALIES][i]) if i is not None else (None, None, None)
        i = self.skater_row.get(bio['game_id'])
        return (SKATERS, i, self.rows[SKATERS][i]) if i is not None else (None, None, None)

    def entry(self, pi):
        i = self.entry_row.get(pi)
        return (i, self.rows[ROSTER][i]) if i is not None else (None, None)

    def team_name(self, team):
        i = self.team_row.get(team)
        if i is None:
            return 'Free agents' if team == L.FREE_AGENTS else f'Team {team}'
        t = self.rows[TEAMS][i]
        return clean(t.get('nickname') or t.get('teamname') or f'Team {team}').rstrip('®™ ')  # Ducks(R)

    def team_abbr(self, team):
        i = self.team_row.get(team)
        return clean(self.rows[TEAMS][i].get('abbrname', '')) if i is not None else ('FA' if team == L.FREE_AGENTS else '')

    def leagues(self):
        """[(league id, label, number of teams with players)], NHL first, then the free agents."""
        counts = {}
        for team in self.team_entries:
            i = self.team_row.get(team)
            if i is not None:
                lg = self.rows[TEAMS][i]['league']
                counts[lg] = counts.get(lg, 0) + 1
        out = [(lg, L.LEAGUES.get(lg, f'League {lg}'), n) for lg, n in sorted(counts.items())]
        if self.free_agents:
            out.append((L.FREE_AGENTS, 'Free agents', 1))
        return out

    def teams(self, league):
        if league == L.FREE_AGENTS:
            return [{'id': L.FREE_AGENTS, 'name': 'Free agents', 'abbr': 'FA', 'count': len(self.free_agents)}]
        out = []
        for t in self.rows[TEAMS]:
            if t['league'] == league and t['index'] in self.team_entries:
                out.append({'id': t['index'], 'name': self.team_name(t['index']), 'abbr': self.team_abbr(t['index']),
                            'count': len(self.team_entries[t['index']])})
        return out

    def players_of(self, team):
        if team == L.FREE_AGENTS:
            return list(self.free_agents)
        if team == T.SEATTLE_AHL and CUSTOM_ROSTER in self.db:     # Coachella Valley: the custom roster only
            t = self.db[CUSTOM_ROSTER]
            return [t.get(i, 'playerindex') for i in range(t.count) if t.get(i, 'team') == team]
        return [self.rows[ROSTER][i]['playerindex'] for i in self.team_entries.get(team, [])]

    def birth(self, b):
        try:
            return datetime.date(b['year'] + L.YEAR_BASE, b['month'] + 1, b['day'] + 1)
        except ValueError:
            return None

    def age(self, b):
        d = self.birth(b)
        if d is None:
            return ''
        t = self.today
        return t.year - d.year - ((t.month, t.day) < (d.month, d.day))

    def name(self, b):
        return f"{b['firstname']} {b['lastname']}".strip()

    def summary(self, pi):
        _, b = self.bio(pi)
        _, e = self.entry(pi)
        if b is None:
            return {'id': pi, 'pos': '?', 'num': '', 'name': f'(player {pi}: no bio)', 'age': '', 'ovr': '',
                    'shoots': '', 'nat': '', 'cap': '', 'team': ''}
        _, _, ai = self.ai(b)
        team = e['team'] if e else b['team']
        return {
            'id': pi, 'pos': L.POSITIONS[b['position']] if b['position'] < 5 else str(b['position']),
            'num': e['jersey'] if e else b['jersey'], 'name': self.name(b), 'age': self.age(b),
            'ovr': ai.get('skill_overall', ai.get('c_overall', '')) if ai else '', 'shoots': L.HANDS[b['handedness']],
            'nat': L.country(b['intlcountry']), 'cap': L.CAPTAIN_NAMES.get(e['captain'], '') if e else '',
            'team': self.team_abbr(team) if team is not None and team >= 0 else 'FA',
        }

    def search(self, text, limit=200):
        q = clean(text).lower()
        if not q:
            return []
        out = []
        for pi in list(self.entry_row) + self.free_agents:
            _, b = self.bio(pi)
            if b and q in self.name(b).lower():
                out.append(pi)
                if len(out) >= limit:
                    break
        return out

    def card(self, pi):
        """Everything the player card shows and edits."""
        brow, b = self.bio(pi)
        if b is None:
            return None
        erow, e = self.entry(pi)
        table, _, ai = self.ai(b)
        goalie = b['position'] == L.GOALIE
        groups = L.GOALIE_GROUPS if goalie else L.SKATER_GROUPS
        summary = L.GOALIE_SUMMARY if goalie else L.SKATER_SUMMARY
        fields = self.db[table].by_name if table else {}
        rating_groups = [{'title': title, 'items': [{'key': f, 'label': lab} for f, lab in items if f in fields]}
                         for title, items in groups]
        birth = self.birth(b)
        inches = b['height'] + L.HEIGHT_BASE
        lbs = b['weight'] + L.WEIGHT_BASE
        team = e['team'] if e else b['team']
        slots = sorted(k for k, v in e.items() if v and k in set(L.all_slots())) if e else []
        return {
            'key': f'{pi}:{len(self.history)}', 'id': pi, 'game_id': b['game_id'], 'goalie': goalie,
            'title': self.name(b), 'team': self.team_name(team) if team is not None and team >= 0 else 'Free agent',
            'rostered': e is not None,
            'note': f"{L.POSITIONS[b['position']]} · #{e['jersey'] if e else b['jersey']} · {L.country(b['intlcountry'])}"
                    f" · {inches // 12}'{inches % 12}\" {lbs} lbs · game id {b['game_id']}",
            'values': {
                'first': b['firstname'], 'last': b['lastname'], 'num': e['jersey'] if e else b['jersey'],
                'pos': L.POSITIONS[b['position']], 'shoots': L.HANDS[b['handedness']],
                'birth': birth.isoformat() if birth else '', 'height': round(inches * 2.54),
                'weight': round(lbs / 2.20462), 'country': b['intlcountry'],
                'salary': round(b['contractdollars'] * L.CONTRACT_UNIT / 1e6, 3), 'years': b['contractlength'],
                'captain': e['captain'] if e else 0,
                'ratings': {it['key']: ai[it['key']] for g in rating_groups for it in g['items']} if ai else {},
            },
            'rating_groups': rating_groups,
            'summary': [{'label': lab, 'value': ai[f]} for f, lab in summary if ai and f in ai],
            'positions': [p for p in L.POSITIONS if (p == 'G') == goalie],
            'slots': slots,
            'imperial': f"{inches // 12}'{inches % 12}\" · {lbs} lbs",
        }

    # --- writing ----------------------------------------------------------------------------------
    def _snap(self, ch, table, row):
        key = (table, row)
        if key not in ch.snaps:
            t = self.db[table]
            n = t.record_length
            ch.snaps[key] = bytes(t.data[row * n:(row + 1) * n])

    def _set(self, ch, table, row, name, value, what=None):
        cur = self.rows[table][row][name]
        if cur == value:
            return False
        self._snap(ch, table, row)
        try:
            self.db[table].set(row, name, value)
        except ValueError as err:
            raise EditError(str(err)) from None
        self.rows[table][row][name] = self.db[table].get(row, name)
        if what:
            ch.details.append((what, cur, value))
        return True

    def _commit(self, ch):
        if ch.snaps:
            self.history.append(ch)
        return ch

    def drop(self, changes):
        """Take `changes` (all in the history) back out of the roster and its history, newest first, when no other
        change after the first of them touched one of their records or re-made the database (`kept`). Returns False
        and does nothing otherwise. Lines' and Strategy's Take back (app/applied.py)."""
        at = [k for k, ch in enumerate(self.history) if any(ch is c for c in changes)]
        if not at or len(at) != len(changes):
            return False
        records = {key for ch in changes for key in ch.snaps}
        for ch in self.history[at[0]:]:
            if not any(ch is c for c in changes) and (ch.kept is not None or records & set(ch.snaps)):
                return False
        for k in reversed(at):
            self._rollback(self.history.pop(k))
        return True

    def _rollback(self, ch):
        if ch.kept is not None:
            self.db.put_back(ch.kept)
            self.rows = {t: self.db[t].rows() for t in TABLES}
        for (table, row), raw in ch.snaps.items():
            t = self.db[table]
            n = t.record_length
            t.data[row * n:(row + 1) * n] = raw
            if table in self.rows:
                self.rows[table][row] = t.row(row)
        self._index()

    def edit(self, label, work):
        """Run `work(setter)`; `setter(table, row, field, value, what=None)` may change a field of any table and keeps
        the old bytes of each record first, so one Undo takes all of it back. Returns (Change, work's result)."""
        ch = Change(label)

        def setter(table, row, name, value, what=None):
            t = self.db[table]
            cur = t.get(row, name)
            if cur == value:
                return False
            self._snap(ch, table, row)
            t.set(row, name, value)
            if table in self.rows:
                self.rows[table][row][name] = t.get(row, name)
            if what:
                ch.details.append((what, cur, value))
            return True
        try:
            out = work(setter)
        except (EditError, ValueError, TypeError, KeyError) as err:
            self._rollback(ch)
            raise EditError(str(err)) from None
        if any(table in self.rows for table, _row in ch.snaps):
            self._index()
        return self._commit(ch), out

    def bulk(self, label, work):
        """Run `work(db)`, which may change anything (records added, removed or re-sorted, tables added). The whole
        database is kept first, so one Undo puts it back. `work` returns (details, result). Returns (Change, result);
        on an error nothing is changed."""
        ch = Change(label, kept=self.db.keep())
        try:
            details, out = work(self.db)
        except BaseException:
            self._rollback(ch)
            raise
        ch.details = list(details)
        self.rows = {t: self.db[t].rows() for t in TABLES}
        self._index()
        self.history.append(ch)
        return ch, out

    def fold(self, ch, into):
        """Make change `ch` (the newest, or one with nothing changed) part of the bulk change `into` before it: one
        Undo takes both back (`into` keeps the whole database from before them). Update's My edits."""
        if into.kept is None:
            raise ValueError('only a bulk change takes in another')
        if self.history and self.history[-1] is ch and ch is not into:
            self.history.pop()
        into.details.extend(ch.details)

    def apply(self, pi, values):
        """Write a player card's values (only the keys present). Returns the Change; raises EditError (and
        changes nothing) when a value is not allowed."""
        brow, b = self.bio(pi)
        if b is None:
            raise EditError('This player has no bio record.')
        erow, e = self.entry(pi)
        who = self.name(b)
        ch = Change(f'Edit {who}')
        try:
            self._apply(ch, pi, brow, b, erow, e, values)
        except (EditError, ValueError, TypeError) as err:
            self._rollback(ch)
            raise EditError(str(err)) from None
        return self._commit(ch)

    def _apply(self, ch, pi, brow, b, erow, e, v):
        who = self.name(b)
        if 'first' in v:
            self._set(ch, BIOS, brow, 'firstname', clean(str(v['first'])), f'{who}: first name')
        if 'last' in v:
            last = clean(str(v['last']))
            if not last:
                raise EditError('The last name cannot be empty.')
            self._set(ch, BIOS, brow, 'lastname', last, f'{who}: last name')
        if 'num' in v:
            num = _int(v['num'], 'Number')
            if not 1 <= num <= 99:
                raise EditError('Numbers go from 1 to 99.')
            if e is not None:   # a teammate may wear it too: the game shows both (Verify warns)
                self._set(ch, ROSTER, erow, 'jersey', num, f'{who}: number')
            self._set(ch, BIOS, brow, 'jersey', num, None if e is not None else f'{who}: number')
        if 'pos' in v:
            pos = L.POSITIONS.index(v['pos']) if v['pos'] in L.POSITIONS else -1
            if pos < 0:
                raise EditError(f"Unknown position {v['pos']!r}.")
            if (pos == L.GOALIE) != (b['position'] == L.GOALIE):
                raise EditError('A skater cannot become a goalie (or the other way): the game keeps their ratings '
                                'in different tables.')
            self._set(ch, BIOS, brow, 'position', pos, f'{who}: position')
        if 'shoots' in v:
            if v['shoots'] not in L.HANDS:
                raise EditError('Shoots must be L or R.')
            self._set(ch, BIOS, brow, 'handedness', L.HANDS.index(v['shoots']), f'{who}: shoots')
        if v.get('birth'):
            try:
                d = datetime.date.fromisoformat(str(v['birth']).strip())
            except ValueError:
                raise EditError('Birth date: use YYYY-MM-DD.') from None
            if not 1900 <= d.year <= 2155:
                raise EditError('Birth year out of range.')
            old = self.birth(b)
            if old != d:
                self._set(ch, BIOS, brow, 'year', d.year - L.YEAR_BASE)
                self._set(ch, BIOS, brow, 'month', d.month - 1)
                self._set(ch, BIOS, brow, 'day', d.day - 1)
                ch.details.append((f'{who}: born', old.isoformat() if old else '', d.isoformat()))
        if 'height' in v:
            cm = _int(v['height'], 'Height')
            inches = round(cm / 2.54)
            if not L.HEIGHT_BASE <= inches <= L.HEIGHT_BASE + 31:
                raise EditError(f'Height must be {round(L.HEIGHT_BASE * 2.54)}-{round((L.HEIGHT_BASE + 31) * 2.54)} cm.')
            if round((b['height'] + L.HEIGHT_BASE) * 2.54) != cm:
                self._set(ch, BIOS, brow, 'height', inches - L.HEIGHT_BASE, f'{who}: height (in)')
        if 'weight' in v:
            kg = _int(v['weight'], 'Weight')
            lbs = round(kg * 2.20462)
            if not L.WEIGHT_BASE <= lbs <= L.WEIGHT_BASE + 255:
                raise EditError('Weight must be 55-170 kg.')
            if round((b['weight'] + L.WEIGHT_BASE) / 2.20462) != kg:
                self._set(ch, BIOS, brow, 'weight', lbs - L.WEIGHT_BASE, f'{who}: weight (lbs)')
        if 'country' in v:
            self._set(ch, BIOS, brow, 'intlcountry', _int(v['country'], 'Country'), f'{who}: country')
        if 'salary' in v:
            try:
                units = round(float(v['salary']) * 1e6 / L.CONTRACT_UNIT)
            except (TypeError, ValueError):
                raise EditError('Salary: a number of millions, e.g. 1.5') from None
            self._set(ch, BIOS, brow, 'contractdollars', units, f'{who}: salary (x $5,000)')
        if 'years' in v:
            self._set(ch, BIOS, brow, 'contractlength', _int(v['years'], 'Contract years'), f'{who}: contract years')
        if 'captain' in v and e is not None:
            self._captain(ch, erow, e, _int(v['captain'], 'Captain'))
        ratings = v.get('ratings') or {}
        if ratings:
            table, arow, ai = self.ai(self.rows[BIOS][brow])
            if ai is None:
                raise EditError('This player has no ratings record.')
            for f, val in ratings.items():
                if f not in ai:
                    raise EditError(f'Unknown rating {f}.')
                n = _int(val, L.rating_label(f))
                meta = self.db[table].by_name[f]
                hi = (1 << meta.depth) - 1 + meta.low
                if not meta.low <= n <= min(hi, 99):
                    raise EditError(f'{L.rating_label(f)}: {meta.low}-{min(hi, 99)}.')
                self._set(ch, table, arow, f, n, f'{who}: {L.rating_label(f)}')

    def _captain(self, ch, erow, e, value):
        if value not in (0, CAPTAIN, ALTERNATE):
            raise EditError('Captain must be none, C or A.')
        if value == e['captain']:
            return
        mates = [i for i in self.team_entries.get(e['team'], []) if i != erow]
        if value == CAPTAIN:
            for i in mates:
                if self.rows[ROSTER][i]['captain'] == CAPTAIN:
                    self._set(ch, ROSTER, i, 'captain', 0)
        # more than three letters is allowed: the game plays them (Verify warns)
        _, b = self.bio(e['playerindex'])
        old = L.CAPTAIN_NAMES.get(e['captain'], '') or 'none'
        self._set(ch, ROSTER, erow, 'captain', value)
        ch.details.append((f'{self.name(b)}: captain', old, L.CAPTAIN_NAMES[value] or 'none'))

    def set_captain(self, pi, value):
        erow, e = self.entry(pi)
        if e is None:
            raise EditError('Free agents cannot wear a letter.')
        _, b = self.bio(pi)
        ch = Change(f'Captain {self.name(b) if b else pi}')
        try:
            self._captain(ch, erow, e, int(value))
        except EditError:
            self._rollback(ch)
            raise
        return self._commit(ch)

    def slot_holders(self, team):
        """{slot: [playerindex, ...]} for one team."""
        out = {}
        slots = L.all_slots()
        for i in self.team_entries.get(team, []):
            e = self.rows[ROSTER][i]
            for s in slots:
                if e.get(s):
                    out.setdefault(s, []).append(e['playerindex'])
        return out

    def set_slot(self, team, slot, pi):
        """Put player `pi` (or nobody, None) in a line slot of `team` (lines.place: whoever held it leaves it, a
        player already in the slot's group swaps with him, a scratch coming in takes over the places of the one he
        replaces)."""
        if slot not in L.all_slots():
            raise EditError(f'Unknown line slot {slot}.')
        if pi is not None:
            erow, e = self.entry(pi)
            if e is None or e['team'] != team:
                raise EditError('That player is not on this team.')
            _, b = self.bio(pi)
            goalie = b is not None and b['position'] == L.GOALIE
            if slot in GOALIE_SLOTS and not goalie:      # the game crashes on it (docs/notes/roster-checks.md)
                raise EditError('Only goalies go in a goalie slot.')
            if slot not in GOALIE_SLOTS and goalie:
                raise EditError('Goalies only go in the goalie slots.')
        ch, moved = self.edit(f'{self.team_abbr(team)} {slot}',
                              lambda setter: lines.place(self.db, team, slot, pi, setter=setter))

        def name(p):
            b = self.bio(p)[1] if p is not None else None
            return self.name(b) if b else 'nobody'
        for s, old, new in moved:
            ch.details.append((f'{self.team_abbr(team)} line {s}', name(old), name(new)))
        return ch

    def deal_groups(self, team, groups):
        """Re-deal the named groups of units of `team` (lines.deal_groups) as one undoable change."""
        what = ', '.join(groups).lower()
        ch, dealt = self.edit(f'{self.team_abbr(team)}: auto {what}',
                              lambda setter: lines.deal_groups(self.db, team, groups, setter=setter))
        if ch.snaps:
            ch.details.append((f'{self.team_abbr(team)} {what}', 'as before', f'dealt by ratings ({len(dealt)} slots)'))
        return ch

    def lineup_problems(self, team):
        return lines.check_lineup(self.db, team)

    def dressed(self, team):
        """{playerindex: dressed} of a team's roster rows."""
        return {self.rows[ROSTER][i]['playerindex']: bool(self.rows[ROSTER][i]['rosterstatus'])
                for i in self.team_entries.get(team, [])}

    def undo(self):
        """Take back the newest change. Returns it, or None when there is nothing to undo."""
        if not self.history:
            return None
        ch = self.history.pop()
        self._rollback(ch)
        return ch

    @property
    def changes(self):
        return list(self.history)

    def change_lines(self):
        return [(what, old, new) for ch in self.history for what, old, new in ch.details]

    def verify(self, strict=False):
        """The roster rules. A player's roster is not strict: the default roster's patterns are warnings
        (overtime_core.roster.PATTERN_RULES); building the default roster asks for strict."""
        return Roster.from_database(self.db).verify(strict=strict)


def _int(value, what):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise EditError(f'{what}: a whole number, please.') from None
