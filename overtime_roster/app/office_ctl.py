"""Front office: the rail's organisation's contracts (NHL roster, farm club, prospects and rights), its cap space
over five seasons. docs/ui/office.md.

The tab sorts, shows one group or all, picks a player (his deal in words in the foot). Contract... (or a double
click) opens the contract window (beta3): cap hit, years left, one-way or two-way, checked and written by the Roster
card's own roster_card.check / RosterCtl._write, so it is one undoable change on the Save bar, the Roster card shows
it as his edit and My edits keeps it for every update. Players without a contract (rights) are not signed here yet.
office.py reads every organisation of the open roster at once (kept until the roster changes: another roster, an
edit, an Undo); an AHL club on the rail shows the organisation it plays for. The rail's numbers are each NHL club's
cap space this season.
"""
from overtime_core import nhl27 as N, rosterupdate as U, teams as T

from . import labels as L
from . import office, roster_card as RC
from .rail import why_tip
from .registry import Part
from .session import EditError

DATA_ERRORS = (KeyError, IndexError, TypeError, ValueError, AttributeError)


class OfficeCtl(Part):
    SLICES = {'office': 'view'}
    CALLS = {'office_sort': 'sort', 'office_group': 'group', 'office_pick': 'pick', 'office_contract': 'contract',
             'office_contract_apply': 'contract_apply', 'office_contract_close': 'contract_close'}
    TAB = 'office'
    rail_unit = 'cap space'

    def __init__(self, ctl):
        super().__init__(ctl)
        self.sort_by = {'key': 'cap', 'dir': -1}
        self.shown = 'all'          # the group switch: 'all' or one of office.GROUPS
        self.picked = None          # game_id of the picked player
        self.org = None             # the organisation the tab shows (its rail id)
        self._data = (None, None)   # ((session, edits, last change), office.read's result or None: unreadable)
        self._money = None          # (served, office.league_money rows)
        self.window = None          # the contract window: {key (game_id), typed, problems} or None

    # --- the open roster's organisations -------------------------------------------------------------------------
    def data(self):
        """office.read of the open roster, read again after any change to it; None when its bios cannot be read.
        Call it under the lock."""
        c = self.ctl
        s = c.session
        if s is None:
            return None
        last = s.history[-1] if s.history else None
        key, data = self._data
        if key is not None and key[0] is s and key[1] == len(s.history) and key[2] is last:
            return data
        clubs = [t['id'] for t in c.rail.listed(s, T.NHL_LEAGUE) if not t['extra']]
        try:
            data = office.read(s, clubs, c.upd_season, s.today)
        except DATA_ERRORS as err:
            c.host.log(f'Front office: the contracts could not be read ({err!r}).')
            data = None
        self._data = ((s, len(s.history), last), data)
        return data

    def money(self):
        """(served, five seasons of cap and lowest payroll): the league layer's when Game patch serves it."""
        if self._money is None:
            c = self.ctl
            served = office.league_served(c.game_dir, c.patch_status)
            self._money = (served, office.league_money(c.upd_season, served))
        return self._money

    # --- the rail's followers ------------------------------------------------------------------------------------
    def follow(self, team):
        """The rail's team: the pick stays while the organisation does (a club and its farm club)."""
        c = self.ctl
        with c.lock:
            data = self.data()
            org = office.org_of(data, team) if data else None
            if org != self.org:
                self.picked = None
            self.org = org
            self._money = None      # Game patch may have changed since the tab last showed
        c.changed('office')

    def roster_changed(self):
        self.picked = None
        self.window = None
        self.org = None
        self._data = (None, None)
        self._money = None

    def rail_number(self, team):
        """Each NHL club's cap space this season ('$9.8M'; caution under $2M, bad over the cap); None for others."""
        tid = team['id'] if isinstance(team, dict) else team
        data = self.data()
        org = data['orgs'].get(tid) if data else None
        if org is None:
            return None
        space = office.seasons(org['nhl'], self.money()[1][:1])[0]['space']
        return {'text': office.short(space), 'tone': '' if office.tone(space) == 'good' else office.tone(space),
                'tip': 'cap space'}

    # --- the slice -----------------------------------------------------------------------------------------------
    def chip(self, tid):
        """{id, code, name, colours, league ('NHL', 'AHL', ...)} of a team, or None."""
        s = self.ctl.session
        if s is None or tid is None:
            return None
        t = self.ctl.rail.team(s, tid)
        league = 'FA' if tid == L.FREE_AGENTS else L.LEAGUES.get(t['league'], '')
        return {'id': t['id'], 'code': t['code'], 'name': t['name'], 'colours': t['colours'], 'league': league}

    def where(self, r):
        """A prospect's team in the Where column: {team, text}, or None."""
        if r['where'] is None:
            return None
        team = self.chip(r['where'])
        return {'team': team, 'text': 'Free agents' if r['where'] == L.FREE_AGENTS else team['name']}

    def row(self, r, where):
        return {'key': r['key'], 'name': r['name'], 'pos': r['pos'], 'age': r['age'], 'ovr': r['ovr'],
                'cap': r['cap'], 'cap_text': office.money(r['cap']) if r['cap'] else 'No contract',
                'years': r['years'] or 0, 'type': office.contract_type(r),
                'ext': f"{r['ext'][0]} x {office.money(r['ext'][1])}" if r['ext'] else '', 'where': where,
                'rights': not r['cap'], 'sel': r['key'] == self.picked}

    def view(self):
        c = self.ctl
        with c.lock:
            s = c.session
            if s is None:
                why = c.busy or 'Pick a roster in Setup first.'
                return {'team': None, 'why': why, 'loading': bool(c.busy), 'tip': why_tip(c)}
            here = self.chip(c.team)
            data = self.data()
            if data is None:
                return {'team': here, 'why': office.UNREAD, 'tip': why_tip(c)}
            org = office.org_of(data, c.team)
            if org is None:
                t = c.rail.team(s, c.team) if c.team is not None else None
                league = L.LEAGUES.get(t['league'], '') if t else ''
                return {'team': here, 'why': office.why_text(t, league), 'tip': why_tip(c)}
            return self.organisation(data, org, here)

    def organisation(self, data, org, here):
        c = self.ctl
        o = data['orgs'][org]
        club = self.chip(org)
        farm = self.chip(o['farm']) if o['farm'] is not None else None
        nhl = [self.row(r, None) for r in o['nhl']]
        farm_rows = [self.row(r, {'team': farm, 'text': farm['name']} if farm else None) for r in o['farm_rows']]
        prospects = [self.row(r, self.where(r)) for r in o['prospects']]
        free_rows = [self.row(r, None) for r in data['free']]
        if farm_rows:
            farm_note = None
        elif farm:
            farm_note = 'No players of this organisation on the farm club.'
        elif org == office.SEATTLE:
            farm_note = f"Seattle's farm club, the {office.SEATTLE_FARM}, is a custom team; Front office does not list its players yet."
        else:
            farm_note = 'This organisation has no farm club in this roster.'
        key, direction = self.sort_by['key'], self.sort_by['dir']
        groups = [
            {'key': 'nhl', 'title': f"{club['name']}: NHL roster", 'rows': office.sort_rows(nhl, key, direction),
             'note': None if nhl else 'No players on the NHL roster.'},
            {'key': 'farm', 'title': f"Farm: {farm['name']}" if farm else 'Farm club',
             'rows': office.sort_rows(farm_rows, key, direction), 'note': farm_note},
            {'key': 'prospects', 'title': 'Prospects and rights', 'rows': office.sort_rows(prospects, key, direction),
             'note': None if prospects else 'No prospects or rights in this roster.'},
            {'key': 'free', 'title': 'Free agents: sign with ' + club['name'], 'rows': office.sort_rows(free_rows, key, direction),
             'note': None if free_rows else 'No free agents in this roster.'},
        ]
        served, money = self.money()
        years = office.seasons(o['nhl'], money)
        now = years[0]
        everyone = o['nhl'] + o['farm_rows'] + o['prospects'] + data['free']
        picked = next((r for r in everyone if r['key'] == self.picked), None)
        return {
            'team': club, 'why': None,
            'from_farm': f"Their farm club: {here['name']}" if c.team != org and here else None,
            'tiles': [
                {'label': f"Payroll {now['label']}", 'value': office.money(now['committed']), 'tone': ''},
                {'label': 'Salary cap', 'value': office.money(now['cap']), 'tone': ''},
                {'label': 'Cap space', 'value': office.money(now['space']),
                 'tone': 'bad' if now['space'] < 0 else 'good'},
                {'label': 'Lowest payroll', 'value': office.money(now['floor']), 'tone': '', 'minor': True},
                {'label': 'NHL · farm · prospects', 'value': f'{len(nhl)} · {len(farm_rows)} · {len(prospects)}',
                 'tone': '', 'minor': True},
            ],
            'seasons': [{'label': y['label'], 'committed': office.money(y['committed']), 'cap': office.money(y['cap']),
                         'space': office.money(y['space']),
                         'share': min(1, y['committed'] / y['cap']) if y['cap'] else 0,
                         'tone': office.tone(y['space']), 'signed': y['signed']} for y in years],
            'group': self.shown,
            'counts': {'nhl': len(nhl), 'farm': len(farm_rows), 'prospects': len(prospects), 'free': len(free_rows)},
            'groups': [g for g in groups if g['key'] != 'free'] if self.shown == 'all'
            else [g for g in groups if g['key'] == self.shown],
            'sort': dict(self.sort_by),
            'pick': {'key': picked['key'], 'name': picked['name'], 'pos': picked['pos'],
                     'deal': office.deal_text(picked)} if picked else None,
            'contract': {'available': bool(picked and (picked['cap'] or picked['where'] == L.FREE_AGENTS)),
                         'sign': bool(picked and not picked['cap'] and picked['where'] == L.FREE_AGENTS),
                         'note': office.CONTRACT if picked and picked['cap'] else
                         office.SIGN if picked and picked['where'] == L.FREE_AGENTS else
                         office.NO_DEAL if picked else office.PICK_FIRST},
            'window': self.window_view(o, years[0]),
            'note': office.NOTE if served else office.NOTE_STOCK,
        }

    # --- calls ---------------------------------------------------------------------------------------------------
    def sort(self, key):
        """The same column again turns the order round; a new one: name and position A to Z, the others high to low."""
        c = self.ctl
        if key not in office.SORTS:
            return
        with c.lock:
            if self.sort_by['key'] == key:
                self.sort_by = {'key': key, 'dir': -self.sort_by['dir']}
            else:
                self.sort_by = {'key': key, 'dir': office.first_dir(key)}
        c.changed('office')

    def group(self, group):
        c = self.ctl
        with c.lock:
            self.shown = group if group in office.GROUPS else 'all'
        c.changed('office')

    def pick(self, key):
        """A click on a player: his deal in words in the foot; the same player again (or null) lets go."""
        c = self.ctl
        try:
            key = None if key in (None, '') else int(key)
        except (TypeError, ValueError):
            key = None
        with c.lock:
            self.picked = None if key is None or key == self.picked else key
        c.changed('office')

    # --- the contract window (beta3) -----------------------------------------------------------------------------
    def _pi(self, key):
        """The playerindex of game_id `key` (his main card), or None. Under the lock."""
        s = self.ctl.session
        try:
            return U.State(s.db).main_pi(int(key))
        except (TypeError, ValueError, KeyError):
            return None

    def window_view(self, o, now):
        """The contract window of the organisation `o` (this season's money `now`), or None. Under the lock."""
        w = self.window
        if w is None:
            return None
        c = self.ctl
        s = c.session
        pi = self._pi(w['key'])
        sign = bool(w.get('sign'))
        row = next((r for g in ('nhl', 'farm_rows', 'prospects') for r in o[g] if r['key'] == w['key']), None)
        if sign:
            row = next((r for r in (self.data() or {}).get('free', []) if r['key'] == w['key']), None)
        if pi is None or row is None or not (row['cap'] or sign):
            return None
        if sign:     # a free agent's first deal here: the lowest salary for one season, one-way
            values = {'cap': N.LOWEST_2026 / 1e6, 'years': 1, 'twoway': False}
        else:
            v = RC.values(s, c.parts['roster'].clock(s), pi)
            values = {'cap': v['salary'], 'years': v['years'], 'twoway': bool(v['twoway'])}
        base = 0 if sign else values['cap']      # what his cap hit counts for now
        typed = w['typed'] or {}
        nhl = sign or any(r['key'] == w['key'] for r in o['nhl'])
        space_after = None
        try:
            cap = float(typed.get('cap', values['cap']))
            if nhl and cap != base:
                space_after = now['space'] - round((cap - base) * 1e6)
        except (TypeError, ValueError):
            pass
        return {'key': w['key'], 'name': row['name'], 'pos': row['pos'], 'age': row['age'], 'ovr': row['ovr'],
                'sign': sign, 'club': self.chip(o['club'])['name'] if sign else None, 'base': base,
                'values': values, 'typed': w['typed'], 'problems': list(w['problems']),
                'cap_min': office.CAP_MIN, 'cap_max': RC.CAP_MAX, 'years_max': RC.YEARS_MAX,
                'ext': f"Then {row['ext'][0]} x {office.money(row['ext'][1])} (an extension: not changed here)."
                if row['ext'] else None,
                'space': {'now': office.money(now['space']), 'dollars': now['space'], 'tone': office.tone(now['space']),
                          'after': office.money(space_after) if space_after is not None else None,
                          'after_tone': office.tone(space_after) if space_after is not None else None,
                          'counts': nhl},
                'note': office.SIGN if sign else office.CONTRACT}

    def contract(self, key=None):
        """Contract... (or a double click on a player): the contract window for him (default: the picked player).
        Players without a contract are refused with the reason."""
        c = self.ctl
        try:
            key = self.picked if key in (None, '') else int(key)
        except (TypeError, ValueError):
            key = None
        with c.lock:
            data = self.data() if c.session is not None else None
            org = office.org_of(data, c.team) if data else None       # as the tab shows it
            o = data['orgs'].get(org) if org is not None else None
            row = next((r for g in ('nhl', 'farm_rows', 'prospects') for r in o[g] if r['key'] == key),
                       None) if o and key is not None else None
            agent = next((r for r in data['free'] if r['key'] == key), None) if o and key is not None else None
            sign = bool(agent) and not (row and row['cap'])
            if sign and org == office.SEATTLE:
                why = 'Signing with Seattle comes later: its players are kept apart in the roster.'
            else:
                why = None if (row and row['cap']) or sign else office.NO_DEAL if row else office.PICK_FIRST
            if why is None:
                self.picked = key
                self.window = {'key': key, 'typed': None, 'problems': []}
                if sign:
                    self.window.update(sign=True, club=o['bio_team'])
        if why:
            c.say(why, 'info')
            return {'ok': False, 'error': why}
        c.changed('office')
        return {'ok': True}

    def contract_close(self):
        c = self.ctl
        with c.lock:
            self.window = None
        c.changed('office')
        return {'ok': True}

    def _sign(self, s, w, v):
        """Apply of a signing window (under the lock): {cap ($M), years (left), twoway}; every wrong value at once,
        else one change of the roster (rosterupdate.sign_player; one Undo takes the player back to the free agents)."""
        c = self.ctl
        problems = []
        try:
            cap = float(v.get('cap'))
        except (TypeError, ValueError):
            cap = None
        try:
            years = int(v.get('years'))
        except (TypeError, ValueError):
            years = None
        if cap is None or not office.CAP_MIN <= cap <= RC.CAP_MAX:
            problems.append({'key': 'cap', 'text': f'A cap hit runs {office.money(office.CAP_MIN * 1e6)} to '
                                                   f'{office.money(RC.CAP_MAX * 1e6)}.'})
        if years is None or not 1 <= years <= RC.YEARS_MAX:
            problems.append({'key': 'years', 'text': f'A contract runs 1 to {RC.YEARS_MAX} years.'})
        row = next((r for r in (self.data() or {}).get('free', []) if r['key'] == w['key']), None)
        if row is None:
            problems.append({'key': '', 'text': 'He is not a free agent any more.'})
        ch = None
        if not problems:
            dollars = round(cap * 1e6 / N.UNIT) * N.UNIT
            stored = years + (1 if RC.expansion(s) else 0)       # the extra season every NHL deal carries here
            label = f"{row['name']} signs with {s.team_abbr(w['club'])}"
            two = bool(v.get('twoway'))

            def work(db):
                U.sign_player(db, w['key'], w['club'], dollars, stored, two)
                return [(label, 'Free agent', f"{office.money(dollars)} x {years}{', two-way' if two else ''}")], None
            try:
                ch, _out = s.bulk(label, work)
            except U.UpdateError as err:
                problems.append({'key': '', 'text': str(err)})
        if problems:
            self.window = dict(w, typed=dict(v), problems=problems)
            c.say(problems[0]['text'], 'caution')
            c.changed('office')
            return {'ok': False, 'problems': problems}
        ch.tab, ch.team = 'Front office', w['club']
        self.window = None
        c.host.log(f'Front office: {ch.label}')
        c.say(f'{ch.label}. Save writes it.', 'good')
        c.changed('office', 'editor', 'lines', 'save', 'roster')
        return {'ok': True, 'changes': 1}

    def contract_apply(self, values):
        """The window's Apply: {cap ($M), years (left), twoway (bool)}. Every wrong value at once (the window shows
        them); else one change of the roster (the Roster card's writer), and the window closes."""
        c = self.ctl
        v = values if isinstance(values, dict) else {}
        with c.lock:
            s, w = c.session, self.window
            pi = self._pi(w['key']) if s is not None and w is not None else None
            if pi is None:
                self.window = None
                c.changed('office')
                return {'ok': False}
            if w.get('sign'):
                return self._sign(s, w, v)
            roster = c.parts['roster']
            clock = roster.clock(s)
            typed = {k: v[name] for name, k in (('cap', 'salary'), ('years', 'years'), ('twoway', 'twoway'))
                     if name in v}
            changes, problems = RC.check(s, clock, pi, typed)
            words = {'salary': 'cap', 'years': 'years', 'twoway': 'twoway'}
            problems = [{'key': words.get(p['key'], p['key']), 'text': p['text']} for p in problems]
            new = {k: n for k, _o, n in changes}
            if 'salary' in new and new['salary'] < office.CAP_MIN:
                problems.append({'key': 'cap', 'text': f'A contract needs a cap hit: {office.CAP_MIN} at least '
                                                      f'({office.money(office.CAP_MIN * 1e6)}).'})
            if 'years' in new and new['years'] < 1:
                problems.append({'key': 'years', 'text': f'A contract runs 1 to {RC.YEARS_MAX} years.'})
            if problems:
                self.window = dict(w, typed=dict(v), problems=problems)
                ch = None
            elif changes:
                try:
                    ch, _words = roster._write(s, clock, pi, changes)
                except EditError as err:
                    problems = [{'key': '', 'text': str(err)}]
                    self.window = dict(w, typed=dict(v), problems=problems)
                    ch = None
                else:
                    ch.tab = 'Front office'
                    self.window = None
            else:
                self.window = None
                ch = None
        if problems:
            c.say(problems[0]['text'], 'caution')
            c.changed('office')
            return {'ok': False, 'problems': problems}
        if ch is not None:
            c.host.log(f'Front office: {ch.label}')
            c.say(f'Contract changed: {ch.label}. Save writes it.', 'good')
            c.changed('office', 'editor', 'lines', 'save')
        else:
            c.changed('office')
        return {'ok': True, 'changes': len(changes)}
