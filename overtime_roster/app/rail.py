"""The rail leader: one league and one team for the six team tabs (Roster, Lines, Strategy, Jerseys & gear, Calendar,
Front office). docs/ui/CONTRACT.md "The rail (leader and followers)".

The pick is the Controller's `league` and `team` (beta1's editor pick, which the old calls still move). A pick runs
the follower of the tab in view (`follow(rail id)`); the others catch up when they are shown (Shell.tab). Rail ids
are exhibitionteams indices, free agents -1 (labels.FREE_AGENTS), Seattle 399 (teams.SEATTLE_PLAY_NOW, also when the
roster holds Seattle only as the custom team 499). `map_id` turns a rail id into the id another table knows.
"""
from overtime_core import calendar, rosterupdate, teams as T

from . import labels as L
from .registry import Part
from .shell import TEAM_TABS

FA = L.FREE_AGENTS
AHL = 1                                     # labels.LEAGUES
SEATTLE = T.SEATTLE_PLAY_NOW                # the rail's Seattle
SEATTLE_TEAM = {'code': 'SEA', 'name': 'Seattle Kraken', 'colours': ['#001628', '#99D9D9', '#355464']}
COACHELLA = T.SEATTLE_AHL                   # customteams 498: Season and Franchise only (no Play Now row)
COACHELLA_TEAM = {'code': 'CV', 'name': 'Coachella Valley Firebirds', 'colours': ['#A6192E', '#FFB81C', '#000000']}
GREY = ['#45484C', '#838E96', '#1F2122']    # free agents, a team without colours
COLOURS = ('feprimarycolor', 'fesecondarycolor', 'fetertiarycolor')
TIP = 'Alt+Up / Alt+Down: the next team'
TEAMS = 'exhibitionteams'


def colour(value):
    return '#%06X' % (int(value or 0) & 0xFFFFFF)


LATER_TIP = 'This tab comes in the next update. Edit players on the Roster tab.'


def why_tip(c, later=False):
    """The Help bar's tip while a team tab shows its "why" card (the module's own tip is about the built tab)."""
    if c.session is None:
        return c.busy or 'Pick a roster in Setup first.'
    return LATER_TIP if later else f'Pick a team in the list. {TIP}.'


def why_view(c, kind, what, free_agents, later):
    """A team tab's centred "why" card ({id, team, view, title, why, tip, loading?}: lines.md, strategy.md,
    jerseys.md): no roster yet (or it is being read), free agents, no team, or `later` (the tab is not built yet).
    kind: the map_id the tab's tables need ('strategy', 'jerseys'), or None. Call it under the lock."""
    team = c.team
    view = c.rail.chip(team) if c.session is not None else None
    out = {'id': c.rail.map_id(kind, team) if kind else team, 'team': team, 'view': view,
           'title': f"{view['name']}: {what}" if view else what[:1].upper() + what[1:]}
    if c.session is None:
        return dict(out, why=c.busy or 'Pick a roster in Setup first.', loading=bool(c.busy), tip=why_tip(c))
    if team == FA:
        return dict(out, why=free_agents, tip=why_tip(c))
    if team is None:
        return dict(out, why='Pick a team in the list.', tip=why_tip(c))
    return dict(out, why=later, tip=why_tip(c, later=True))


class Rail(Part):
    SLICES = {'rail': 'view'}
    CALLS = {'rail_league': 'pick_league', 'rail_team': 'pick_team', 'rail_step': 'step',
             'league': 'pick_league', 'team': 'pick_team'}       # beta1's pickers move the rail too

    def __init__(self, ctl):
        super().__init__(ctl)
        self.picks = {}             # league -> the team last picked in it
        self._seattle = (None, 0)   # ((session, edits), players of the custom Seattle)

    # --- the open roster's teams -------------------------------------------------------------------------------------
    def team(self, s, tid, count=None):
        """{id, code, name, colours, league, extra, count} of one rail team."""
        if tid == FA:
            return {'id': FA, 'code': 'FA', 'name': 'Free agents', 'colours': GREY, 'league': FA, 'extra': False,
                    'count': len(s.free_agents) if count is None else count}
        i = s.team_row.get(tid)
        row = s.rows[TEAMS][i] if i is not None else {}
        if tid == SEATTLE:
            return {'id': tid, **SEATTLE_TEAM, 'league': T.NHL_LEAGUE, 'extra': False, 'count': count}
        if tid == COACHELLA and i is None:
            out = {'id': tid, **COACHELLA_TEAM, 'league': AHL, 'extra': False, 'count': count}
            try:                            # the custom team's own colours (teams.py writes them)
                j = rosterupdate._seattle_row(s.db, COACHELLA)
                if j is not None:
                    out['colours'] = [colour(s.db[T.CUSTOM].get(j, k)) for k in COLOURS]
            except (KeyError, IndexError, TypeError, ValueError):
                pass
            return out
        name = s.team_name(tid)
        city = str(row.get('cityname') or '').strip()
        if city.startswith('$'):            # "$SEATTLE": the game spells the city itself
            name = f'{city[1:].title()} {name}'
        return {'id': tid, 'code': s.team_abbr(tid) or str(tid), 'name': name,
                'colours': [colour(row.get(k)) for k in COLOURS] if row else GREY,
                'league': row.get('league', FA), 'extra': 'All-Stars' in name, 'count': count}

    def chip(self, tid):
        """{id, code, name, colours} for a team chip (None for no team)."""
        s = self.ctl.session
        if s is None or tid is None:
            return None
        t = self.team(s, tid)
        return {k: t[k] for k in ('id', 'code', 'name', 'colours')}

    def seattle_players(self, s):
        """Players of the custom Seattle (499) when the roster has it ready but no Play Now copy (399) listed."""
        key = (s, len(s.history))
        if self._seattle[0] != key:
            n = 0
            try:
                if rosterupdate.seattle_ready(s.db):
                    t = s.db[rosterupdate.CUSTOM_ROSTER]
                    n = sum(1 for i in range(t.count) if t.get(i, 'team') == T.SEATTLE)
            except (KeyError, IndexError, TypeError, ValueError):   # a roster without the custom tables
                n = 0
            self._seattle = (key, n)
        return self._seattle[1]

    def listed(self, s, league):
        """The league's rail teams: the clubs by name, then the All-Stars teams."""
        out = [self.team(s, t['id'], t['count']) for t in s.teams(league)]
        if league == T.NHL_LEAGUE and all(t['id'] != SEATTLE for t in out):
            n = self.seattle_players(s)
            if n:
                out.append(self.team(s, SEATTLE, n))
        if league == AHL and COACHELLA not in s.team_row:
            try:
                t = s.db[rosterupdate.CUSTOM_ROSTER]
                n = sum(1 for i in range(t.count) if t.get(i, 'team') == COACHELLA)
            except (AttributeError, KeyError, IndexError, TypeError, ValueError):  # no custom tables
                n = 0
            if n:
                out.append(self.team(s, COACHELLA, n))
        out.sort(key=lambda t: (t['extra'], t['name']))
        return out

    def league_of(self, s, tid):
        if tid == FA:
            return FA
        if tid == SEATTLE:
            return T.NHL_LEAGUE
        if tid == COACHELLA and tid not in s.team_row:
            return AHL
        i = s.team_row.get(tid)
        return s.rows[TEAMS][i]['league'] if i is not None else None

    def first(self, s, league):
        rows = self.listed(s, league)
        return next((t['id'] for t in rows if not t['extra']), rows[0]['id'] if rows else None)

    def farm_of(self, s, tid):
        """An NHL club's AHL club (its 'ahlaffiliate'), or None."""
        i = s.team_row.get(tid)
        aff = s.rows[TEAMS][i].get('ahlaffiliate') if i is not None else None
        j = s.team_row.get(aff) if aff is not None and aff != tid else None
        return aff if j is not None and s.rows[TEAMS][j]['league'] == AHL else None

    def map_id(self, kind, rail_id):
        """A rail id as another table knows it: 'strategy' and 'jerseys' (Seattle 399 -> 499), 'calendar' (the
        32-team calendar's slot, None for a team without NHL games), 'farm' (an NHL club -> its AHL club), 'org' (an
        AHL club -> its NHL club)."""
        s = self.ctl.session
        if rail_id is None:
            return None
        if kind in ('strategy', 'jerseys'):
            return T.SEATTLE if rail_id == SEATTLE else rail_id
        if kind == 'calendar':
            if rail_id == SEATTLE:
                return calendar.SLOTS32['SEA']
            nhl = s is not None and self.league_of(s, rail_id) == T.NHL_LEAGUE
            return calendar.PLACE32.get(rail_id, rail_id) if nhl and 0 <= rail_id <= 30 else None
        if s is None:
            return None
        if kind == 'farm':
            return self.farm_of(s, rail_id)
        if kind == 'org':
            if rail_id == COACHELLA and rail_id not in s.team_row:
                return SEATTLE
            return next((t['id'] for t in s.teams(T.NHL_LEAGUE) if self.farm_of(s, t['id']) == rail_id), None)
        raise ValueError(f'no rail id map {kind!r}')

    # --- the slice ---------------------------------------------------------------------------------------------------
    def follower(self):
        """The part of the team tab in view, else None."""
        c = self.ctl
        return c.tab_parts.get(c.tab_name) if c.tab_name in TEAM_TABS else None

    def view(self):
        c = self.ctl
        with c.lock:
            s = c.session
            part = self.follower()
            out = {'leagues': [], 'league': c.league, 'team': c.team, 'loaded': False, 'status': '',
                   'unit': getattr(part, 'rail_unit', 'players'), 'tip': TIP, 'extra_label': 'All-Stars', 'rows': []}
            if s is None:
                return dict(out, status=c.busy or 'Pick a roster in Setup first.')
            farms = {}
            if c.league == AHL:
                farms = {self.farm_of(s, t['id']): t['code'] for t in self.listed(s, T.NHL_LEAGUE)}
                farms.setdefault(COACHELLA, SEATTLE_TEAM['code'])
            edited = c.parts['save'].teams()
            rows = []
            for t in self.listed(s, c.league):
                number = part.rail_number(t) if part else None
                dirty = t['id'] in edited or any(p.dirty(t['id']) for p in c.tab_parts.values())
                rows.append({'id': t['id'], 'code': t['code'], 'name': t['name'], 'colours': t['colours'],
                             'league': t['league'], 'sel': t['id'] == c.team, 'extra': t['extra'],
                             'farm': farms.get(t['id'], ''), 'dirty': dirty,
                             'number': number or {'text': str(t['count'] or 0), 'tip': 'players'}})
            return dict(out, loaded=True, rows=rows,
                        leagues=[{'value': lg, 'label': label} for lg, label, _n in s.leagues()])

    # --- picks -------------------------------------------------------------------------------------------------------
    def pick_league(self, league):
        c = self.ctl
        with c.lock:
            if not c.session:
                return
            league = int(league)
            self.picks[c.league] = c.team
            c.league = league
            known = {t['id'] for t in self.listed(c.session, league)}
            keep = self.picks.get(league)
            c.team = keep if keep in known else self.first(c.session, league)
            c.query = ''
        self.moved()

    def pick_team(self, team):
        """Pick a team (another league's too: the rail turns to it)."""
        c = self.ctl
        with c.lock:
            old_league, old_team = c.league, c.team
            c.team = int(team)
            c.query = ''
            if c.session is not None:
                league = self.league_of(c.session, c.team)
                if league is not None and league != old_league:
                    self.picks[old_league] = old_team
                    c.league = league
        self.moved()

    def step(self, by):
        """The next (+1) or the one before (-1) team of the league; it stops at the ends."""
        c = self.ctl
        with c.lock:
            if not c.session:
                return
            ids = [t['id'] for t in self.listed(c.session, c.league)]
            if not ids:
                return
            at = ids.index(c.team) if c.team in ids else -1
            to = min(len(ids) - 1, max(0, at + (1 if int(by) > 0 else -1)))
            if ids[to] == c.team:
                return
            c.team = ids[to]
            c.query = ''
        self.moved()

    def moved(self):
        """The rail's team changed: the tab in view follows it; beta1's slices that showed the pick change too."""
        part = self.follower()
        if part is not None:
            part.follow(self.ctl.team)
        self.ctl.changed('rail', 'editor', 'lines')

    def shown(self, tab):
        """Another tab shows (Shell.tab): a team tab catches up with the rail; the numbers' word may change."""
        part = self.follower()
        if part is not None and self.ctl.session is not None:
            part.follow(self.ctl.team)
        self.ctl.changed('rail')

    def roster_changed(self):
        """Another roster is open: the rail starts on its first league's first club; every part hears of it (under the
        lock: they reset the Controller's shared state)."""
        c = self.ctl
        with c.lock:
            self.picks = {}
            s = c.session
            if s is not None:
                leagues = s.leagues()
                c.league = leagues[0][0] if leagues else T.NHL_LEAGUE
                c.team = self.first(s, c.league)
            for part in c.parts.values():
                if part is not self and hasattr(part, 'roster_changed'):
                    part.roster_changed()
        self.moved()
