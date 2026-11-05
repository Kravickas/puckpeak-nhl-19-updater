"""Today's NHL in an NHL 19 roster: NHL.com rosters, EA ratings, the 2026-27 teams and the real calendar (idea from PS3
Legacy's update pipeline, `pipeline.py` / `builder.py`).

    gather_rosters(client, season)   NHL.com: every club's roster, flattened (nhlcom.roster_players)
    plan(db, real)                   who stays, moves, is new or leaves (nothing written)
    apply(db, schema, plan, ...)     do it, then Utah / Seattle, lines, ratings, calendar; returns a Report

Players. NHL.com players are matched to the roster's players by name and birth date (matching.py). A matched player on
another team (or a free agent, or in another league) moves: his roster row leaves its team and is put back at the end
of his new team's rows. The game keeps exhibitionrostertable sorted by team and by `key`: rows are written back in
that order, a new row gets the key after the row before it, and later keys move up only where there is no gap.
A real player with no match is made from a donor of the same position with a generic face: new bio, ratings,
equipment and exhibitionplayers records after the last ones (those tables are sorted by game_id / index).
Players of an NHL team who are on no real roster become free agents (bio team -1); NHL.com's rosters leave out injured
players, so the best of them stay while their team would not have 18 skaters and 2 goalies to dress.
Seattle's players go to customrostertable, team 499 (the expansion team, teams.py); Arizona's slot is Utah's.
exhibitionteams 399 (Seattle in Play Now and the online roster) gets the same players through their own
exhibitionplayers records (mirror_seattle).

All-Star teams (31-34) keep their rows (they point at players through their own exhibitionplayers records).
"""
import bisect
import collections
import itertools
import re
import unicodedata
from dataclasses import dataclass, field

from . import art, calendar, careerstats, equipment as EQ, estimate, leaguecal, lines, nhl27 as N, ratings as R, reallines, teams as T, vees
from .roster import ALTERNATE, CAPTAIN
from .matching import Matcher, Person

ROSTER, CUSTOM_ROSTER = 'exhibitionrostertable', 'customrostertable'
KEYS_PER_TEAM = 40  # a roster row's key is 40 * team + its place in the team, in every stock roster table
PLAYERS, BIOS, FREE = 'exhibitionplayers', 'exhibitionplayerbiotable', 'exhibitionfreeagents'
AI = {False: 'exhibitionskaterai', True: 'exhibitiongoalieai'}
EQUIPMENT = {False: 'exhibitionskaterequipment', True: 'exhibitiongoalieequipment'}
GOALIE = 4
POSITION = {'C': 0, 'L': 1, 'R': 2, 'D': 3, 'G': 4}
COUNTRY = {'CAN': 0, 'USA': 14, 'DNK': 66, 'FIN': 67, 'NOR': 68, 'SWE': 69, 'BLR': 70, 'EST': 71, 'KAZ': 72, 'LVA': 74,
           'LTU': 75, 'RUS': 76, 'UKR': 77, 'AUT': 78, 'BEL': 79, 'HRV': 81, 'CZE': 82, 'GBR': 83, 'FRA': 84, 'DEU': 85,
           'HUN': 86, 'ITA': 87, 'NLD': 89, 'POL': 91, 'ROU': 92, 'SVK': 95, 'SVN': 96, 'CHE': 97, 'JPN': 109}
HEIGHT_BASE, WEIGHT_BASE, YEAR_BASE = 54, 120, 1900
DEFAULT_SEASON = 2026
GENERIC_HEAD = 60000  # headid of the game's generic faces (60000 on; star players have their own)
NHL = tuple(range(31))
SLOT_FIELDS_SKIP = {'key', 'team', 'playerindex', 'jersey', 'playerstyle'}
DRESS_SKATERS, DRESS_GOALIES = 18, 2
TABLES = (ROSTER, CUSTOM_ROSTER, PLAYERS, BIOS, FREE, *AI.values(), *EQUIPMENT.values())
# Player ids (game_id / exhibitionplayers playerid): the regular players run up to ~20640; from 56500 on come the
# game's own special players (3-on-3, legends) and from 57000 the created players (custom* tables). New players take
# the free ids after the regular ones and must stay below the special ones: the game maps ids to players and two
# players on one id leave a hole it crashes on (default roster with 56818+ ids, run x2-20261016).
SPECIAL_IDS = 56500
# Portrait art ids (bio artid, 16 bits): the game draws nhl/ui/kettle_assets/playerportraits/p<artid>.gnf (ws8 run pk).
# The stock bios use up to 19947 and the stock portraits below 2**16 stop at 19645 (then p65535), so a new player
# takes his own from NEW_ARTIDS: his game id when no bio has it as artid (so the photo pack's name follows the game
# id), else the next free one. A donor's artid would be the donor's face.
NEW_ARTIDS = range(20000, art.PEOPLE_ARTIDS.start)
# the sorted player tables and their keys; new players are appended, then sort_players() puts them in place
SORTED = ((BIOS, 'game_id'), *((t, 'game_id') for t in AI.values()), *((t, 'game_id') for t in EQUIPMENT.values()),
          (PLAYERS, 'index'))
# teams whose rows point at players through records of their own (a player's main record is elsewhere): the
# All-Star teams and Seattle's Play Now copy
MIRROR = T.SEATTLE_PLAY_NOW
SHADOW_TEAMS = (31, 32, 33, 34, MIRROR)


class UpdateError(ValueError):
    pass


def target_of(code):
    """(roster table, team index) of an NHL.com club code."""
    code = 'UTA' if code in ('ARI', 'PHX') else code
    if code == 'SEA':
        return CUSTOM_ROSTER, T.SEATTLE
    if code not in calendar.SLOTS:
        raise UpdateError(f"no NHL 19 team for {code}")
    return ROSTER, calendar.SLOTS[code]


def gather_rosters(client, start_year, codes=None, log=lambda msg: None):
    """[real player] of every club (nhlcom.roster_players dicts, 'team' = club code), the season's roster or, before
    NHL.com has it, the current one."""
    from . import nhlcom
    out = []
    for code in sorted(codes or calendar.SLOTS):
        try:
            body = client.roster(code, calendar.season_code(start_year))
        except Exception:  # noqa: BLE001 - NHL.com answers 404 before the season's rosters exist
            body = client.roster(code, 'current')
        out += nhlcom.roster_players(body, team=code)
    log(f'NHL.com rosters: {len(out)} players on {len(codes or calendar.SLOTS)} clubs')
    return out


# --- the roster as it is ---------------------------------------------------------------------------
class State:
    """Who is where: roster rows of both roster tables, the free agents, each bio's main exhibitionplayers index."""

    def __init__(self, db):
        self.db = db
        players, bios = db[PLAYERS], db[BIOS]
        self.bio_row = {bios.get(i, 'game_id'): i for i in range(bios.count)}
        self.entry = {}  # playerindex -> (table, team)
        for name in (ROSTER, CUSTOM_ROSTER):
            if name in db:
                t = db[name]
                for i in range(t.count):
                    self.entry[t.get(i, 'playerindex')] = (name, t.get(i, 'team'))
        f = db[FREE]
        self.free = {f.get(i, 'playerindex') for i in range(f.count)}
        self.pis_of = {}  # game_id -> [playerindex]
        for i in range(players.count):
            if players.get(i, 'table') == 0:
                self.pis_of.setdefault(players.get(i, 'playerid'), []).append(players.get(i, 'index'))

    def main_pi(self, game_id):
        """The playerindex a bio plays under: the one on an NHL team or Seattle, else on the bio's team, else a free
        agent's, else one on any team but the All-Star teams and Seattle's Play Now copy. A national or event team's
        record can come first (Haula's Team Finland one before his Vegas one): planning with it moved that record
        and released the club's onto the free agent list while he played on."""
        pis = self.pis_of.get(game_id, [])
        if not pis:
            return None
        b = self.bio_row.get(game_id)
        team = self.db[BIOS].get(b, 'team') if b is not None else None

        def rank(pi):
            e = self.entry.get(pi)
            if e is None:
                return 2 if pi in self.free else 4
            if e[0] == ROSTER and e[1] in SHADOW_TEAMS:
                return 4
            if e == (CUSTOM_ROSTER, T.SEATTLE) or e[0] == ROSTER and e[1] in NHL:
                return 0
            return 1 if e[1] == team else 3
        best = min(pis, key=lambda pi: (rank(pi), pi))
        return best if rank(best) < 4 else min(pis)

    def bio(self, pi):
        players = self.db[PLAYERS]
        # exhibitionplayers is sorted by index
        i = bisect.bisect_left(_Column(players, 'index'), pi)
        if i < players.count and players.get(i, 'index') == pi and players.get(i, 'table') == 0:
            b = self.bio_row.get(players.get(i, 'playerid'))
            return self.db[BIOS].row(b) if b is not None else None
        return None


class _Column:
    def __init__(self, table, name):
        self.t, self.name = table, name

    def __len__(self):
        return self.t.count

    def __getitem__(self, i):
        return self.t.get(i, self.name)


def _birth(b):
    return f"{b['year'] + YEAR_BASE:04d}-{b['month'] + 1:02d}-{b['day'] + 1:02d}"


UNDRAFTED = 255  # bio draftyear of a player nobody drafted (shows as 2155)


def _clock_years(real, drafts, shift, draftyear=UNDRAFTED):
    """Bio birth date and draft year of a real player on the game's clock: `shift` years earlier, so the game's age
    (its league year 2018 - birth year) is the real one. The draft year comes from the data pack; without it the
    bio's own `draftyear` is moved too when it is still on the real calendar (more than 24 years after the shifted
    birth year: nobody is drafted that old), so a second run leaves it alone."""
    out = {}
    if real.get('birth'):
        y, m, d = (int(x) for x in real['birth'].split('-'))
        out.update(year=y - YEAR_BASE - shift, month=m - 1, day=d - 1)
    draft = (drafts or {}).get((_key(real.get('first')), _key(real.get('last'))))
    if draft:
        out['draftyear'] = draft[3] - YEAR_BASE - shift
    elif 'year' in out and draftyear != UNDRAFTED and draftyear - out['year'] > 24:
        out['draftyear'] = draftyear - shift
    return out


# --- the plan --------------------------------------------------------------------------------------
@dataclass
class Plan:
    placed: list = field(default_factory=list)   # (real, playerindex or None, (table, team), match level)
    moves: list = field(default_factory=list)    # (playerindex, name, from (table, team) or 'FA' / None, to)
    new: list = field(default_factory=list)      # (real, to)
    releases: list = field(default_factory=list)  # (playerindex, name, from (table, team))
    kept: list = field(default_factory=list)     # (playerindex, name, team): off NHL.com's roster, stays to dress 20
    stay: int = 0

    def summary(self):
        return {'players': len(self.placed), 'stay': self.stay, 'moves': len(self.moves), 'new': len(self.new),
                'releases': len(self.releases), 'kept': len(self.kept)}


KEEP_ROOM = 30  # an NHL club takes the players NHL.com leaves out while it holds fewer (Legacy NHL_KEEP_ROOM)
STAY_ROOM = 40  # who was there already stays while it holds fewer (Legacy MAX_PER_TEAM)
FARM_ROOM = 34  # an AHL club takes the deals nobody lists while it holds fewer (Legacy FARM_KEEP_ROOM)


def _absent_row(p, team, number=None):
    """The NHL.com row of a pack player (nhl27.py, or a data pack `nhl_last` row) on club `team`."""
    y, m, d = p['birth']
    height = p.get('height') or p.get('height_in')
    weight = p.get('weight') or p.get('weight_lb')
    return {'first': p['first'], 'last': p['last'], 'birth': f'{y:04d}-{m:02d}-{d:02d}',
            'position': {'LW': 'L', 'RW': 'R'}.get(p['pos'], p['pos']), 'shoots': p.get('hand') or p.get('shoots'),
            'height': height * 2.54 if height else None, 'weight': weight / 2.20462 if weight else None,
            'team': team, 'number': number, 'id': p.get('nhl_id'), 'birthplace': p.get('city') or p.get('birthplace')}


def with_absent(real, pack, data=None, real_lines=None, listed=(), lookup=None, log=lambda m: None, farms=None):
    """(NHL.com's rosters `real` + the NHL players its lists leave out, those extra rows, [(AHL club, player)] who go to
    a farm club instead: clubdata.merged). The lists drop injured reserve and some players they should have (the
    2026-10-16 lists had no Barzal, Larkin, Terry; the 2026-11-02 ones no Edvinsson), and the update released them with
    their 2018 bios. As Legacy's find_missing, contract_keeps and contract_strays:
    - who a league's feed lists (`listed`, clubdata.listed) plays there: NHL.com and the leagues win over a contract;
    - who the real lines name (`real_lines`, reallines.part) plays for that club unless his deal is two-way;
    - a deal or NHL 27's NHL row (`pack` NHL 27, `data` the data pack's nhl_last) goes where `lookup(nhl id)` says
      (nhlcom.landing_player, None when it can't say), if that is an NHL club; else to his organisation, or the NHL club
      NHL 27 has him at. An NHL club takes them while it holds fewer than KEEP_ROOM (STAY_ROOM when NHL 27 has him there
      already), a farm club (`farms`, clubdata.farm_clubs) while it holds fewer than FARM_ROOM: a two-way deal the farm
      club first, a one-way deal the NHL club first."""
    pkey = lambda p: (_team_key(p['last']), tuple(p['birth']))  # noqa: E731
    in_feed = lambda p: _team_key(p['first'] + p['last']) in listed or pkey(p) in listed  # noqa: E731
    last_year, by_id = {}, {}
    for p in (data or {}).get('nhl_last') or []:
        if p.get('birth'):
            last_year[pkey(p)] = p
            by_id[p.get('nhl_id')] = p
    players = {pkey(p): p for p in (pack or {}).get('players') or [] if p.get('birth')}
    deals = {pkey(d): d for d in (pack or {}).get('contracts') or [] if d.get('birth')}
    people = [Person(i, r['first'], r['last'], r.get('birth') or '') for i, r in enumerate(real)]
    matcher = Matcher(people)
    faces = {(_team_key(r['last']), r['first'][:1].casefold(), str(r.get('birth') or '')[:4]) for r in real}

    def missing(p):
        """Not on `real`: by the matcher, nor by last name, initial and birth year (NHL 27 has Benjamin Kindel born on
        another day than NHL.com's Ben Kindel)."""
        row = Person(0, p['first'], p['last'], '%04d-%02d-%02d' % tuple(p['birth']))
        face = (_team_key(p['last']), p['first'][:1].casefold(), str(p['birth'][0]))
        return matcher.match_all([row])[0].game is None and face not in faces
    size = collections.Counter(r['team'] for r in real)
    extra, farmed, ids = [], [], {r.get('id') for r in real}
    farm_size = collections.Counter({club: n for club, n in (farms or {}).values()})

    def add(row):
        extra.append(row)
        size[row['team']] += 1
        ids.add(row.get('id'))
    for code, entry in sorted((real_lines or {}).items()):
        for nhl_id in sorted({v for v in ((entry or {}).get('slots') or {}).values() if v}):
            if nhl_id in ids:
                continue
            p = by_id.get(nhl_id)
            if p is not None:
                if missing(p) and not in_feed(p) and not (deals.get(pkey(p)) or {}).get('two_way'):
                    add(_absent_row(p, code))
                continue
            found = lookup(nhl_id) if lookup else None
            if found and found.get('birth'):
                add(dict(found, team=code))
    for key in sorted(set(deals) | set(last_year), key=str):
        deal, last, row = deals.get(key), last_year.get(key), players.get(key)
        p = dict(row or deal or {}, **(last or {}))
        if p.get('pos') not in POSITION_27 + ('L', 'R') or (p.get('nhl_id') and p['nhl_id'] in ids) or not missing(p):
            continue
        if in_feed(p) or not listed and row is not None and row.get('league') != 'nhl':
            continue                                     # no feeds: NHL 27's leagues stand in for them
        if deal is None and (row is None or row.get('league') != 'nhl'):
            continue
        found = lookup(p['nhl_id']) if lookup and p.get('nhl_id') else None
        if found is not None:
            team = found['team'] if found.get('active') else None
        elif deal is not None:
            team = deal['org']
        else:
            team = row['team']
        number = (found or {}).get('number')
        room = STAY_ROOM if row is not None and row.get('team') == team else KEEP_ROOM
        open_here = (team == 'SEA' or team in calendar.SLOTS) and size[team] < room
        farm = (farms or {}).get(team, (None,))[0] if deal is not None else None
        if farm is not None and farm_size[farm] < FARM_ROOM and (deal.get('two_way') or not open_here):
            farmed.append((farm, dict(p, num=number, pos=_absent_row(p, team)['position'])))
            farm_size[farm] += 1
        elif open_here:
            add(_absent_row(p, team, number))
    if extra:
        log(f"{len(extra)} players NHL.com's rosters leave out kept: "
            + ', '.join(f"{r['first']} {r['last']}" for r in extra[:12]))
    if farmed:
        log(f'{len(farmed)} players under contract nobody lists go to their farm clubs')
    return list(real) + extra, extra, farmed


def short_teams(db):
    """The NHL clubs with fewer than 2 goalies or 18 skaters, as sentences: the game hangs the first game played with one
    (Legacy round 17: its line picker waits forever for a player of a kind)."""
    state, count = State(db), {}
    for pi, (table, team) in state.entry.items():
        if table == ROSTER and team in NHL:
            b = state.bio(pi)
            if b is not None:
                row = count.setdefault(team, [0, 0])
                row[b['position'] != GOALIE] += 1
    teams = {r['index']: r['teamname'] for r in db[T.TEAMS].rows()}
    return [f"{teams.get(team, team)} has {g} goalie{'s' if g != 1 else ''} and {s} skaters"
            for team, (g, s) in sorted(count.items()) if g < 2 or s < 18]


def free_and_on_a_club(db):
    """The names on the free agent list who also play for an NHL club under another of their records. The game shows
    them in both places, and an update leaves them out of its pool of free agents."""
    state, out = State(db), []
    for pi in sorted(state.free):
        b = state.bio(pi)
        if b is not None and any(state.entry.get(o, (None, None))[0] == ROSTER and state.entry[o][1] in NHL
                                 for o in state.pis_of.get(b['game_id'], [])):
            out.append(f"{b['firstname']} {b['lastname']}")
    return out


def plan(db, real, season=DEFAULT_SEASON, aliases=None):
    """What `apply` would do with the real rosters `real` (gather_rosters, with_absent). Birth dates match as they are or
    on the game's clock (teams.year_shift: what an earlier update for `season` stored). `aliases` {game_id: (first, last,
    real birth date or None)}: players the user renamed (the app's My edits) match under the name and birth date they had."""
    state = State(db)
    bios = db[BIOS]
    people = []
    for game_id, b in state.bio_row.items():
        if state.main_pi(game_id) is not None:
            r = bios.row(b)
            first, last, born = (aliases or {}).get(game_id) or (r['firstname'], r['lastname'], None)
            people.append(Person(game_id, first, last, born or _birth(r)))
    seen, unique = set(), []
    for p in real:  # a player traded while the clubs were fetched is on two lists: the first wins
        if p.get('id') is None or p['id'] not in seen:
            seen.add(p.get('id'))
            unique.append(p)
    real = unique
    reals = [Person(i, p['first'], p['last'], p.get('birth') or '') for i, p in enumerate(real)]
    out = Plan()
    placed = set()
    for p, m in zip(real, Matcher(people, shifts=range(T.year_shift(season) + 1)).match_all(reals)):
        to = target_of(p['team'])
        # same name and date, other kind of player: two people, and a goalie's ratings on a skater spoil both
        if m.game is None or (p.get('position') and (p['position'] == 'G')
                              != (bios.get(state.bio_row[m.game.key], 'position') == GOALIE)):
            out.new.append((p, to))
            out.placed.append((p, None, to, 'none'))
            continue
        pi = state.main_pi(m.game.key)
        placed.add(pi)
        out.placed.append((p, pi, to, m.level))
        now = state.entry.get(pi)
        if now == to:
            out.stay += 1
        else:
            out.moves.append((pi, f"{p['first']} {p['last']}", now if now else ('FA' if pi in state.free else None), to))
    leaving = {}
    for pi, (name, team) in state.entry.items():
        if pi in placed:
            continue
        if (name == ROSTER and team in NHL) or (name == CUSTOM_ROSTER and team == T.SEATTLE):
            leaving.setdefault((name, team), []).append(pi)
    # NHL.com leaves injured players out: keep the best leavers while a team could not dress 18 skaters and 2 goalies
    arriving = {}
    for p, pi, to, _level in out.placed:
        arriving.setdefault(to, []).append(POSITION.get(p.get('position'), 0) == GOALIE)
    for team, pis in sorted(leaving.items()):
        goalies = sum(arriving.get(team, []))
        skaters = len(arriving.get(team, [])) - goalies
        ranked = sorted(pis, key=lambda pi: (-_overall(db, state, pi), pi))
        for pi in ranked:
            b = state.bio(pi)
            name = f"{b['firstname']} {b['lastname']}" if b else f'player {pi}'
            goalie = bool(b and b['position'] == GOALIE)
            if goalie and goalies < DRESS_GOALIES or not goalie and skaters < DRESS_SKATERS:
                out.kept.append((pi, name, team))
                goalies, skaters = goalies + goalie, skaters + (not goalie)
            else:
                out.releases.append((pi, name, team))
    return out


def _overall(db, state, pi):
    b = state.bio(pi)
    if b is None:
        return 0
    t = db[AI[b['position'] == GOALIE]]
    i = bisect.bisect_left(_Column(t, 'game_id'), b['game_id'])
    return t.get(i, 'skill_overall') if i < t.count and t.get(i, 'game_id') == b['game_id'] else 0


# --- writing ---------------------------------------------------------------------------------------
def _records(t):
    n = t.record_length
    return [bytes(t.data[i * n:(i + 1) * n]) for i in range(t.count)]


def _write_records(t, recs):
    """Replace the table's records by `recs` (raw bytes); the rest of the room gets the free-record bytes."""
    from .tdb import FREE_BYTE
    if len(recs) > t.max_records:
        raise UpdateError(f"{t.name}: {len(recs)} records, room for {t.max_records}")
    n = t.record_length
    t.data[:len(recs) * n] = b''.join(recs)
    t.data[len(recs) * n:] = FREE_BYTE * (len(t.data) - len(recs) * n)
    t.count = len(recs)


def _rebuild_roster(t, remove, add):
    """Rows of roster table `t` without the playerindexes in `remove`, plus `add` [(team, values)] at the end of their
    team's rows; sorted by team, keyed like the stock tables: key = KEYS_PER_TEAM * team + the row's place in its
    team (Play Now's match load crashed, 0xc0000005 on SimThread, when a team's keys ran into the next team's
    range: ws8-20261018 run4c/4d). Returns {playerindex: row}."""
    recs = [(t.get(i, 'team'), i, rec) for i, rec in enumerate(_records(t)) if t.get(i, 'playerindex') not in remove]
    zero = bytes(t.record_length)
    added = [(team, None, (zero, values)) for team, values in add]
    rows = sorted(recs + added, key=lambda r: r[0])  # stable: a team's own rows first, in their order, then the new
    _write_records(t, [r[2] if r[1] is not None else r[2][0] for r in rows])
    where, place = {}, {}
    top = (1 << t.by_name['key'].depth) - 1
    for row, (team, old, rec) in enumerate(rows):
        if old is None:
            for name, value in rec[1].items():
                t.set(row, name, value)
        n = place[team] = place.get(team, -1) + 1
        key = KEYS_PER_TEAM * team + n
        if n >= KEYS_PER_TEAM or key > top:
            raise UpdateError(f"{t.name}: team {team} has more than {KEYS_PER_TEAM} rows")
        if t.get(row, 'key') != key:
            t.set(row, 'key', key)
        where[t.get(row, 'playerindex')] = row
    return where


def _rebuild_free(db, remove, add):
    t = db[FREE]
    pis = sorted(({t.get(i, 'playerindex') for i in range(t.count)} - set(remove)) | set(add))
    from .tdb import FREE_BYTE
    if len(pis) > t.max_records:
        raise UpdateError(f"{FREE}: {len(pis)} free agents, room for {t.max_records}")
    t.data[:] = FREE_BYTE * len(t.data)
    t.count = 0
    for pi in pis:
        t.append({'playerindex': pi})


def _unsign(bios, brow, b):
    """A released or retired player: no team and no contract (nhl27.NO_CONTRACT), as the stock free agents. Keeping
    the 2018 deal left 180 of 185 free agents with old contract dollars."""
    for f, v in dict(N.NO_CONTRACT, team=-1).items():
        if b[f] != v:
            bios.set(brow, f, v)


def _fit(table, name, text):
    size = table.by_name[name].depth // 8
    raw = (text or '').encode('utf-8')[:size - 1]
    return raw.decode('utf-8', 'ignore')


class _Maker:
    """New players from donors with a generic face."""

    def __init__(self, db):
        self.db = db
        bios = db[BIOS]
        self.ai_row = {g: {db[AI[g]].get(i, 'game_id'): i for i in range(db[AI[g]].count)} for g in (False, True)}
        self.eq_row = {g: {db[EQUIPMENT[g]].get(i, 'game_id'): i for i in range(db[EQUIPMENT[g]].count)}
                       for g in (False, True)}
        self.donors = []
        self.audio = {}
        for i in range(bios.count):
            b = bios.row(i)
            self.audio.setdefault(b['lastname'].lower(), b['audioid'])
            g = b['position'] == GOALIE
            if b['headid'] >= GENERIC_HEAD and b['game_id'] in self.ai_row[g] and b['game_id'] in self.eq_row[g]:
                self.donors.append((b['position'], b['height'], b['weight'], b['game_id'], i))
        players = db[PLAYERS]
        regular = [i for i in range(players.count) if players.get(i, 'table') == 0]
        self.used_ids = _used_ids(db)
        self.used_art = {bios.get(i, 'artid') for i in range(bios.count)}
        self.next_art = NEW_ARTIDS.start
        self.used_index = {players.get(i, 'index') for i in range(players.count)}
        if 'customplayers' in db:
            c = db['customplayers']
            self.used_index |= {c.get(i, 'index') for i in range(c.count)}
        self.next_game_id = 1 + max([players.get(i, 'playerid') for i in regular] +
                                    [g for g in self.used_ids if g < SPECIAL_IDS])
        self.next_index = 1 + max([players.get(i, 'index') for i in regular] +
                                  [i for i in self.used_index if i < SPECIAL_IDS])

    def _take(self, attr, used):
        n = getattr(self, attr)
        while n in used:
            n += 1
        if n >= SPECIAL_IDS:
            raise UpdateError(f'no free player id left below {SPECIAL_IDS}')
        used.add(n)
        setattr(self, attr, n + 1)
        return n

    def artid(self, gid):
        """A portrait art id for a new player: no bio's, no stock portrait's (NEW_ARTIDS), his game id if free."""
        if gid in NEW_ARTIDS and gid not in self.used_art:
            self.used_art.add(gid)
            return gid
        n = max(self.next_art, NEW_ARTIDS.start)
        while n in self.used_art:
            n += 1
        if n not in NEW_ARTIDS:
            raise UpdateError(f'no free portrait art id left below {NEW_ARTIDS.stop}')
        self.used_art.add(n)
        self.next_art = n + 1
        return n

    def donor(self, pos, height, weight):
        goalie = pos == GOALIE
        pool = [d for d in self.donors if (d[0] == GOALIE) == goalie]
        if not pool:
            raise UpdateError('no donor player with a generic face')
        return min(pool, key=lambda d: (d[0] != pos, abs(d[1] - height) + abs(d[2] - weight) / 10, d[3]))

    def make(self, real, team, proteam, number, drafts=None, shift=0):
        db = self.db
        bios, players = db[BIOS], db[PLAYERS]
        pos = POSITION.get(real.get('position'), 0)
        goalie = pos == GOALIE
        height = _height(real, None)
        weight = _weight(real, None)
        dpos, _h, _w, dgid, drow = self.donor(pos, height if height is not None else 18,
                                              weight if weight is not None else 75)
        gid, pi = self._take('next_game_id', self.used_ids), self._take('next_index', self.used_index)
        y, m, d = (int(x) for x in (real.get('birth') or '2000-01-01').split('-'))
        donor = bios.row(drow)
        # his own artid (the donor's is the donor's face: ws8 run pk, Leo Carlsson showed Blair Jones's p1349) and
        # no portrait flag: the patch sets it when the art layer serves p<artid> (art.portrait_flags)
        values = {'game_id': gid, 'artid': self.artid(gid), 'firstname': _fit(bios, 'firstname', real.get('first')),
                  'lastname': _fit(bios, 'lastname', real.get('last')), 'nickname': '',
                  'birthplace': _fit(bios, 'birthplace', real.get('birthplace')),
                  'year': y - YEAR_BASE - shift, 'month': m - 1, 'day': d - 1, 'position': pos,
                  'handedness': 1 if real.get('shoots') == 'R' else 0, 'jersey': number, 'team': team,
                  'proteam': proteam, 'hasportrait': 0, 'active': 1, 'contractstatus': 0,
                  'intlcountry': COUNTRY.get(real.get('country'), donor['intlcountry']),
                  'audioid': self.audio.get((real.get('last') or '').lower(), 0)}
        if height is not None:
            values['height'] = height
        if weight is not None:
            values['weight'] = weight
        for f in donor:
            if f.startswith(('nhl', 'progamesplayed')) and isinstance(donor[f], int):
                values[f] = 0
        draft = (drafts or {}).get((_key(real.get('first')), _key(real.get('last'))))
        if draft:
            values.update({'draftyear': draft[3] - YEAR_BASE - shift, 'draftround': draft[4], 'draftposition': draft[5],
                           'draftteam': T.draft_team(draft[6])})
        else:  # not the donor's draft: undrafted, as the stock roster marks them
            values.update({'draftyear': UNDRAFTED, 'draftround': 0, 'draftposition': 0, 'draftteam': -1})
        if proteam == -1 and team != T.SEATTLE:
            # not the donor's pro history either: a club player with no NHL deal has none, as NHL 19's own (pro debut and
            # waiver year -1 for 98 % of its junior and European players); NHL 27's own history comes on top (_pro_history)
            values.update(dict.fromkeys(N.PRO_YEARS, -1))
        bios.append(values, like=drow)
        ai, eq = db[AI[goalie]], db[EQUIPMENT[goalie]]
        ai.append({'game_id': gid}, like=self.ai_row[goalie][dgid])
        eq.append({'game_id': gid}, like=self.eq_row[goalie][dgid])
        kind = 'goalie' if goalie else 'skater'
        plain = {c: v for c, v in EQ.NEW_PLAYER[kind].items() if c != 'mask' or eq.get(eq.count - 1, 'masktype') == 0}
        EQ.write(db, eq.count - 1, plain, kind)  # not the donor's visor, tucks, tape or mask
        players.append({'table': 0, 'index': pi, 'playerid': gid})
        return pi, gid, ai.get(ai.count - 1, 'playerstyle'), dgid


def _used_ids(db):
    """Every player id any table holds (game_id, playerid fields)."""
    out = set()
    for t in db.tables:
        for f in t.fields:
            if f.name in ('game_id', 'playerid'):
                out.update(t.get(i, f.name) for i in range(t.count))
    return out


def sort_players(db):
    """Sort the player tables by their keys, as the game keeps them; returns the tables that moved."""
    return [name for name, key in SORTED if name in db and db[name].sort_by(key)]


def graft_custom(db, default_db):
    """Give a roster without the custom team tables (an online roster) copies of the default roster's."""
    import copy
    added = []
    for t in default_db.tables:
        if t.name.startswith('custom') and t.name not in db:
            db.add(copy.deepcopy(t))
            added.append(t.name)
    return added


def _key(name):
    from .matching import norm
    return norm(name or '')


def _height(real, current):
    cm = real.get('height')
    if not cm:
        return current
    return max(0, min(31, round(cm / 2.54) - HEIGHT_BASE))


def _weight(real, current):
    kg = real.get('weight')
    if not kg:
        return current
    return max(0, min(255, round(kg * 2.20462) - WEIGHT_BASE))


@dataclass
class Report:
    plan: dict
    teams: list
    lines: list
    ratings: int
    calendar: dict
    problems: list
    created: list
    skipped_lines: list
    signed: list = field(default_factory=list)
    retired: list = field(default_factory=list)  # (playerindex, name, age)
    nhl27: dict = field(default_factory=dict)  # what the NHL 27 pack gave: players rated, values, contracts
    real: dict = field(default_factory=dict)  # reallines.Result.as_dict(): real lines and captains; {} without
    called_up: list = field(default_factory=list)  # (playerindex, name, [table, farm club], [table, NHL club])

    def as_dict(self):
        return {'plan': self.plan, 'teams': len(self.teams), 'lines': self.lines, 'ratings': self.ratings,
                'calendar': self.calendar, 'problems': self.problems, 'created': self.created,
                'skipped_lines': self.skipped_lines, 'signed': self.signed, 'retired': self.retired,
                'nhl27': self.nhl27, 'real': self.real, 'called_up': self.called_up}


def apply(db, schema, todo, rating_rows=None, games=None, start_year=None, drafts=None, per32=None, active=None,
          nhl27=None, log=lambda m: None, retire=True, real_lines=None, leagues=None, national=None, clubs=None,
          money=1.0, retired_list=None, unsigned=None):
    """Do the plan `todo`, then set up Utah and Seattle, retire old free agents nobody lists (`active`:
    still_playing(pack); None keeps them all, and so does `retire` False; `retired_list`: gone_people(pack), who
    retired after last season, at any age), put last season's unsigned NHL players on the free agent list (`unsigned`:
    unsigned_last(pack); add_unsigned), rebuild the lines of every team that changed, give everyone NHL 27's
    ratings, player type and biases (`nhl27`: the local NHL 27 pack, nhl27.py) and EA's ratings (`rating_rows`) to
    the players NHL 27 does not have, lay the real lines and captains on the NHL teams (`real_lines`: the data pack's
    `lines` part, reallines.part; None keeps the lines dealt), set the contracts (_contracts; only with `nhl27`), give every NHL goalie a
    career row (careerstats; NHL 27's seasons when the pack has them: Play Now crashes without one), write the
    calendar (`games`) and the other leagues' calendars (`leagues`, leaguecal; one that can't be made is left as it
    is and logged), the national teams (`national`: the data pack's IIHF squads, rebuild_national). `clubs`: the club
    leagues' rosters to use (clubdata.merged), else NHL 27's. `money`: the deals' dollars times this (money_scale:
    NHL 19's own cap over 2026-27's when the game plays the 2018 cap). Writes straight into `db` (the app keeps a copy of the tables to undo: TABLES + the team, strategy
    and schedule tables)."""
    if CUSTOM_ROSTER not in db or T.CUSTOM not in db:
        raise UpdateError('the roster has no custom team tables (an online roster): graft_custom() first')
    state = State(db)
    teams_before, names_before = _bio_teams(db), _team_names(db)
    draft_index = {}
    for row in drafts or []:
        draft_index.setdefault((_key(row[0]), _key(row[1])), row)
    teams_done = T.apply(db, schema)
    shift = T.year_shift(start_year)
    leaving = {pi for pi, _n, _t in todo.releases}
    moving = {pi for pi, _n, _f, _to in todo.moves}
    maker = _Maker(db)
    bios = db[BIOS]
    adds = {ROSTER: [], CUSTOM_ROSTER: []}
    created = []
    numbers = _numbers(db, state, todo)
    nhl_pis = {}  # NHL.com id -> exhibitionplayers index, for the real lines
    born_in = {}  # game_id -> NHL.com's birth country
    for p, pi, to, _level in todo.placed:
        table, team = to
        number = numbers[(to, pi if pi is not None else id(p))]
        proteam = team if table == ROSTER else -1
        if pi is None:
            pi, gid, style, donor = maker.make(p, team, proteam, number, draft_index, shift)
            if p.get('id') is not None:
                nhl_pis[p['id']] = pi
            state.bio_row[gid] = bios.count - 1
            born_in[gid] = p.get('country')
            created.append({'name': f"{p['first']} {p['last']}", 'team': p['team'], 'game_id': gid, 'donor': donor})
            adds[table].append((team, {'team': team, 'playerindex': pi, 'jersey': number, 'playerstyle': style}))
            continue
        if p.get('id') is not None:
            nhl_pis[p['id']] = pi
        b = state.bio(pi)
        brow = state.bio_row[b['game_id']]
        born_in[b['game_id']] = p.get('country')
        if pi in moving:
            style = _ai_value(db, b, 'playerstyle', 0)
            adds[table].append((team, {'team': team, 'playerindex': pi, 'jersey': number, 'playerstyle': style}))
        values = {'team': team, 'proteam': proteam, 'jersey': number,
                  'height': _height(p, b['height']),
                  'weight': _weight(p, b['weight']), 'handedness': 1 if p.get('shoots') == 'R' else
                  0 if p.get('shoots') == 'L' else b['handedness']}
        values.update(_clock_years(p, draft_index, shift, b['draftyear']))
        pos = POSITION.get(p.get('position'))
        if pos is not None and (pos == GOALIE) == (b['position'] == GOALIE):
            values['position'] = pos
        if b['contractstatus'] == -1:
            values['contractstatus'] = 0
        if not b['birthplace'].strip() and p.get('birthplace'):  # NHL 19 left 579 empty; a stock one stays (Legacy nhl_bio)
            values['birthplace'] = _fit(bios, 'birthplace', p['birthplace'])
        for f, v in values.items():
            if b[f] != v:
                bios.set(brow, f, v)
    if created:  # the new players were appended: put them in place, the bio rows move
        sort_players(db)
        state.bio_row = {bios.get(i, 'game_id'): i for i in range(bios.count)}
    placed_ids = {state.bio(pi)['game_id'] for _p, pi, _to, _l in todo.placed if pi is not None and state.bio(pi)}
    for pi, _name, _from in todo.releases:
        b = state.bio(pi)
        if b is not None and b['game_id'] not in placed_ids:  # a bio can have several records (All-Stars, 3-on-3)
            _unsign(bios, state.bio_row[b['game_id']], b)
    gone = leaving | moving
    for table in (ROSTER, CUSTOM_ROSTER):
        if table in db:
            _rebuild_roster(db[table], gone, adds[table])
    # a player on a club is no free agent under any of his records
    signed = {pi for gid in placed_ids for pi in state.pis_of.get(gid, ())}
    _rebuild_free(db, remove=moving | (signed & state.free), add=leaving - signed)
    # old free agents nobody lists retire; a club that can't dress its 20 without one still signs him first
    # with NHL 27's lists every free agent of 30 or more nobody lists goes; NHL 27's own free agents who retired
    # (retired_list: unsigned at 38, Petry) do not count as listed
    if nhl27 and nhl27.get('players'):
        active = list(active or []) + without_gone(nhl27['players'], retired_list, free_only=True)
    min_age = NHL27_RETIRE_AGE if nhl27 and nhl27.get('players') else FA_RETIRE_AGE
    retiring = (retirees(db, active, start_year or DEFAULT_SEASON, min_age, retired_list or ())
                if retire and active is not None else [])
    # numbers of the players who stay
    for table in (ROSTER, CUSTOM_ROSTER):
        if table not in db:
            continue
        t = db[table]
        for i in range(t.count):
            key = ((table, t.get(i, 'team')), t.get(i, 'playerindex'))
            if key in numbers and t.get(i, 'jersey') != numbers[key]:
                t.set(i, 'jersey', numbers[key])
    changed = {to for _pi, _n, _f, to in todo.moves} | {to for _p, to in todo.new}
    changed |= {f for _pi, _n, f, _to in todo.moves if isinstance(f, tuple)}
    changed |= {f for _pi, _n, f in todo.releases}
    signed = []
    club_listed = _club_listed(db, (nhl27 or {}).get('players'), (clubs or {}).get('players'), shift)
    # a club whose league is rebuilt below signs nobody before: the rebuild sets its roster and fills it to 2 goalies
    # and 18 skaters from its own 2018 players; a free agent signed before it was taken off again (the OHL's clubs
    # signed Georgiev, Sprong and Kunin when NHL.com called a junior up, then lost them to their league's rebuild)
    league_of = {r['index']: r['league'] for r in db[T.TEAMS].rows()} if T.TEAMS in db else {}
    pending = {AHL_LEAGUE, ALLSVENSKAN, *LEAGUE_PLAN} if nhl27 and nhl27.get('players') else set()

    last = {pi for pi, _n, _a in retiring}  # they retire once every club has signed: one may still need one of them
    former, called = {}, []  # the players each team let go in this update (it takes them back first); the call-ups
    for pi, _n, frm in todo.releases:
        former.setdefault(frm, set()).add(pi)
    # an NHL club calls its farm club's players up once the AHL is rebuilt (they are this season's then)
    waits = lambda table, team: table == ROSTER and (  # noqa: E731
        league_of.get(team) in pending or team in NHL and AHL_LEAGUE in pending)

    def sign(teams):
        out = []
        for table, team in sorted(teams):
            if not waits(table, team):
                out += _sign_free_agents(db, table, team, last, club_listed, former.get((table, team), ()), called)
        return out

    def done(league, teams_of):  # its clubs dress their 20 now, and every club the rebuild took players from
        pending.discard(league)
        return sign({(ROSTER, t) for t in teams_of} | {(tb, t) for tb, t in changed if league_of.get(t) == league
                                                        or league == AHL_LEAGUE and tb == ROSTER and t in NHL})
    signed += sign(changed)
    ahl, club_feed = {}, {}
    keeping = _listed_ids(db, (nhl27 or {}).get('players'), (clubs or {}).get('players'), active,
                          [p for squad in (national or {}).values() for p in squad], shift)
    if nhl27 and nhl27.get('players'):
        ahl = {'unused_dropped_first': drop_unused(db, keeping)}
        got, ahl_teams = rebuild_ahl(db, clubs or nhl27, shift, club_feed, keeping)
        ahl.update(got)
        ahl['ahl_renamed'] = len(rename_ahl(db, ahl_teams))
        # the renamed clubs' 2026 records and every NHL team's farm link, before the call-ups read them (_farm_of)
        teams_done += T.apply(db, schema)
        farms = {(CUSTOM_ROSTER, team) for team in ahl_teams if team in FARM_CLUBS}
        ahl_teams = {team for team in ahl_teams if team not in FARM_CLUBS}
        changed |= {(ROSTER, team) for team in ahl_teams} | farms
        signed += done(AHL_LEAGUE, ahl_teams) + sign(farms)  # Coachella Valley dresses its 20 too
    allsv = {}
    if nhl27 and nhl27.get('players'):  # HockeyAllsvenskan: NHL 27's clubs and players in the slots, renamed
        allsv, allsv_teams = rebuild_league(db, nhl27, shift, ALLSVENSKAN, 'allsvenskan',
                                            {k: v[0] for k, v in ALLSVENSKAN_MOVED.items()}, 'allsv', free_too=keeping)
        allsv['allsv_renamed'] = len(rename_allsvenskan(db, allsv_teams))
        changed |= {(ROSTER, team) for team in allsv_teams}
        signed += done(ALLSVENSKAN, allsv_teams)
    others = {}
    if nhl27 and nhl27.get('players'):  # every other club league, the clubs NHL 27 and NHL 19 share (LEAGUE_PLAN)
        frozen = {AHL_LEAGUE, ALLSVENSKAN}
        others['vees_slot'] = int(vees.wanted((clubs or nhl27).get('players')) and vees.make_room(db))
        for league, (tag, size) in LEAGUE_PLAN.items():
            got, teams_of = rebuild_league(db, clubs or nhl27, shift, league, tag, {}, tag, size, True, frozen, False,
                                           tag != 'europe', club_feed, keeping)
            frozen.add(league)
            others.update(got)
            changed |= {(ROSTER, team) for team in teams_of}
            signed += done(league, teams_of)
    retired = [r for r in retiring if r[0] not in {pi for pi, _n, _t in signed}]
    _retire(db, retired)
    unsigned_counts, unsigned_ids = add_unsigned(db, unsigned, shift, draft_index) if unsigned else ({}, set())
    squads, national_made = {}, {}
    if national:
        squads = {'unused_dropped': drop_unused(db, keeping)}
        got, national_teams = rebuild_national(db, national, shift, log, national_made,
                                               start_year or DEFAULT_SEASON)
        squads.update(got)
        changed |= {(ROSTER, team) for team in national_teams}
    done_lines, skipped = [], []
    for table, team in sorted(changed):
        try:
            lines.build(db, team, table=table)
            done_lines.append([table, team])
        except lines.NotEnoughPlayers as err:
            skipped.append(f"{table} team {team}: {err}")
    n_ratings, counts, models, rated, overall = 0, {}, {}, set(), {}
    full_found, list_found = [], []
    if nhl27 and nhl27.get('players'):
        models = {name: R.Model.fit(db[name]) for name in AI.values()}  # fitted before any rating changes
        found = full_found = _nhl27_matches(db, nhl27['players'], shift, 'team')
        clocked = _clock_nhl27(db, found, shift)
        todo27 = R.plan_nhl27(db, schema, found, nhl27['fields'], models)
        n_ratings = R.apply(db, todo27)
        rated = {bios.get(brow, 'game_id') for _p, brow, _l in found}
        overall = {bios.get(brow, 'game_id'): _row_overall(p, nhl27['fields']) for p, brow, _l in found}
        counts = {'rated': len(rated), 'values': n_ratings,
                  'styles': sum(1 for _t, _r, f, _o, _n in todo27 if f == 'playerstyle'),
                  'roster_styles': _sync_styles(db, todo27), 'pro_history': _pro_history(db, schema, found, shift),
                  'clocked': len(clocked)}
        counts.update(_real_gear(db, found))
        counts['gear_pack'] = _pack_gear(db, (clubs or {}).get('equipment'), shift)
    if rating_rows:
        ids = {bios.get(i, 'game_id') for i in range(bios.count)} - rated if rated else None
        found = list_found = R.match(db, rating_rows, game_ids=ids, shift=shift)
        n_ratings += R.apply(db, R.plan(db, found, models))
        rated |= {bios.get(brow, 'game_id') for _p, brow, _l in found}
    if club_feed and models:
        estimated, by_level = _estimate_clubs(db, club_feed, rated, models, start_year or DEFAULT_SEASON, shift,
                                              (clubs or {}).get('countries'))
        counts['rated_estimate'] = estimated
        overall.update(by_level)
    if national:
        if models:
            counts['rated_national'] = _estimate_national(db, national_made, rated, models, start_year or DEFAULT_SEASON)
        squads['national_filled'] = fill_national(db, born_in, overall, start_year or DEFAULT_SEASON, shift)
    real = reallines.apply(db, real_lines, nhl_pis, target_of, log=log) if real_lines else None
    if club_feed:
        counts.update(_club_finish(db, club_feed, (clubs or {}).get('club_lines'), log))
    if national:
        squads['national_captains'] = give_captains(db, overall)    # after the clubs' letters: they rank a team's
    renamed = {t for t, name in _team_names(db).items() if names_before.get(t) != name}
    counts.update(_fit_masks(db, teams_before, renamed))  # after every move, every new player and every rename
    counts['sticks'] = _fit_sticks(db, teams_before)
    on_clock =placed_ids | {c['game_id'] for c in created} | (clocked if nhl27 and nhl27.get('players') else set())
    on_clock |= {gid for info in club_feed.values() for gid, _f in info['made']} | set(national_made) | unsigned_ids
    on_clock |= _on_clock(db, full_found, shift)
    counts['ufa_years'] = _ufa_years(db, on_clock)
    if nhl27 is not None:
        state = State(db)
        free = {b['game_id'] for b in map(state.bio, state.free) if b}
        level = _levels(db, nhl27, full_found, list_found, rating_rows)
        orgs = {gid: org for info in club_feed.values() if info['tag'] == 'ahl' for gid, org in info['orgs'].items()}
        counts.update(_contracts(db, nhl27, start_year or DEFAULT_SEASON, shift, on_clock, level, free, money, orgs))
    counts.update(ahl)
    counts.update(unsigned_counts)
    counts.update(allsv)
    counts.update(others)
    counts.update(squads)
    mirror_seattle(db)
    expansion_active(db)
    if careerstats.SEASON in db:  # a roster save holds no stock career tables (only the default database does)
        careers = _goalie_careers(db, nhl27, T.year_shift(start_year or DEFAULT_SEASON))
        counts['goalie_careers'] = len(careerstats.fill(db, careers, T.year_shift(start_year or DEFAULT_SEASON)))
    cal = {}
    if games:
        cal = calendar.apply(db, schema, games, per32=per32)
    for key, part in sorted((leagues or {}).items()):
        try:
            if key in leaguecal.LEAGUE_TABLES:
                cal.update(leaguecal.apply_other(db, key, part, _calendar_places(db, key, part, log)))
                continue
            cal.update(leaguecal.apply(db, schema, {key: part}))
        except calendar.CalendarError as err:
            log(f'{key} calendar kept as it was: {err}')
    problems = check(db, schema, cal, start_year)
    log(f"update: {todo.summary()}, {len(created)} new, {len(retired)} retired, {n_ratings} rating values, "
        f"{len(problems)} problem(s)" + (f", NHL 27 {counts}" if counts else ''))
    summary = dict(todo.summary(), signed=len(signed), retired=len(retired))
    return Report(summary, teams_done, done_lines, n_ratings, cal, problems, created, skipped, signed, retired,
                  counts, real.as_dict() if real else {}, called)


def _clock_nhl27(db, found, shift):
    """Birth year (and a draft year still on the real calendar, _clock_years) of every bio NHL 27 matched (`found`:
    _nhl27_matches) put on the game's clock, as the placed ones: the free agents, AHL and European players kept EA's
    real years and the game showed 2018 ages (Barzal 21, Toews 30: ws5 run5). Only a bio still on NHL 27's real
    birth year moves, so a second run changes nothing. Returns the game_ids moved."""
    bios, out = db[BIOS], set()
    if not shift:
        return out
    for p, brow, _level in found:
        b = bios.row(brow)
        if b['game_id'] >= SPECIAL_IDS or b['year'] != p['birth'][0] - YEAR_BASE:
            continue
        values = {'year': b['year'] - shift}
        if b['draftyear'] != UNDRAFTED and b['draftyear'] - values['year'] > 24:
            values['draftyear'] = b['draftyear'] - shift
        for f, v in values.items():
            bios.set(brow, f, v)
        out.add(b['game_id'])
    return out


def _on_clock(db, found, shift):
    """The game_ids of the bios NHL 27 matched (`found`: _nhl27_matches) that sit on the game's clock, whoever put them
    there (the shipped default's are there before any update, and _clock_nhl27 moves only the others)."""
    bios = db[BIOS]
    return {bios.get(brow, 'game_id') for p, brow, _level in found
            if bios.get(brow, 'year') == p['birth'][0] - YEAR_BASE - shift}


UFA_AGE = 27  # NHL 19's own roster: yearufa = birth year + 27 for 97 % of its players (every junior, NHL 742 of 766)


def _ufa_years(db, gids):
    """yearufa = birth year + UFA_AGE on the bios in `gids` (the ones the update made or put on the game's clock): a
    made player kept his donor's and a moved birth year left the old one, so Franchise could send a 20-year-old to
    free agency (Legacy contracts.ufa_fit, the same rule on the PS3 game). Returns the bios changed."""
    bios = db[BIOS]
    f = bios.by_name.get('yearufa')
    if f is None:
        return 0
    low, high = f.low, f.low + (1 << f.depth) - 1
    n = 0
    for brow in range(bios.count):
        b = bios.row(brow)
        if b['game_id'] >= SPECIAL_IDS or b['game_id'] not in gids:
            continue
        want = min(max(b['year'] + UFA_AGE, low), high)
        if b['yearufa'] != want:
            bios.set(brow, 'yearufa', want)
            n += 1
    return n


def expansion_contracts(db):
    """Every NHL deal one season longer (contractlength + 1, at most 15): the expansion career starts in the 2018
    offseason, whose re-sign phase and July 1 end every deal in its last season; with + 1 the deals after that
    offseason are NHL 27's 2026-27 ones (Crosby, Malkin, Ovechkin stay: ws5 run5). Not for a career that starts in
    the preseason (Franchise without expansion), where every deal would run a season long. Returns the bios changed."""
    bios, n = db[BIOS], 0
    for brow in range(bios.count):
        b = bios.row(brow)
        # Seattle's players (customteams 499) have no proteam: theirs is a custom team
        if b['game_id'] >= SPECIAL_IDS or b['contractstatus'] != 0 or (b['proteam'] == -1 and b['team'] != T.SEATTLE) \
                or not (b['contractlength'] and b['contractdollars']):
            continue
        for f, v in {'contractlength': min(15, b['contractlength'] + 1), 'contractismultiyear': 1}.items():
            if b[f] != v:
                bios.set(brow, f, v)
        n += 1
    return n


def _club_code(b):
    """The NHL.com code of a bio's club, None when he is on none."""
    if b['team'] == T.SEATTLE:
        return 'SEA'
    return calendar.CODES.get(b['team']) if b['team'] in NHL else None


def _nhl27_matches(db, rows, shift, club):
    """R.match() of NHL 27 pack rows kept on name + birth date ('exact' / 'date'), or on the name alone when NHL 27
    has the player at the same club (row[`club`]: 'team' of a player, 'org' of a deal); NHL 27's birthdates have
    typos (day and month swapped, a month off: docs/notes/nhl27-data.md)."""
    bios = db[BIOS]
    return [(row, brow, level) for row, brow, level in R.match(db, rows, shift=shift)
            if level in ('exact', 'date') or (row.get(club) and row.get(club) == _club_code(bios.row(brow)))]


def _goalie_careers(db, pack, shift):
    """{game_id: NHL 27 career rows (pack 'career', careerstats.FIELDS)} of the pack's goalies the roster has."""
    if not pack or not pack.get('players'):
        return {}
    goalies = [p for p in pack['players'] if p.get('pos') == 'G' and p.get('career')]
    bios = db[BIOS]
    return {bios.get(brow, 'game_id'): row['career'] for row, brow, _l in _nhl27_matches(db, goalies, shift, 'team')}


def _pro_history(db, schema, found, shift):
    """NHL 27's pro history (pack 'pro', nhl27.PRO_FIELDS) on the bios of the players matched (`found`:
    _nhl27_matches), years moved back `shift` onto the game's clock, clamped to the roster's ranges. Without it the
    players the update brings in have no pro debut: the Franchise expansion draft counts them as first year pros
    (exempt), and teams were left with no one to take (docs/notes/nhl27-data.md). Returns the bios changed."""
    bios = db[BIOS]
    ranges = {f.name: (f.low, f.high) for f in schema.by_name(BIOS).fields.values() if not f.is_string}
    n = 0
    for row, brow, _level in found:
        if bios.get(brow, 'game_id') >= SPECIAL_IDS:
            continue
        changed = False
        for f, v in (row.get('pro') or {}).items():
            if f not in ranges:
                continue
            if f in N.PRO_YEARS and v != -1:
                v -= shift
            v = min(max(v, ranges[f][0]), ranges[f][1])
            if bios.get(brow, f) != v:
                bios.set(brow, f, v)
                changed = True
        n += changed
    return n


CHOICE_OF = {kind: {f: c for c, (f, _l, _n) in choices.items()} for kind, (_t, choices) in EQ.KINDS.items()}


def _real_gear(db, found):
    """NHL 27's gear (pack 'gear', nhl27.gear_of) on the equipment rows of the players matched (`found`:
    _nhl27_matches): sock tuck, pants, tape colours and a goalie's neck guard, through equipment.clean, so the update
    writes exactly what the Equipment window accepts; a value the game does not list is left out and counted. Returns
    {'gear': players changed, 'gear_values': values changed, 'gear_skipped': values left out}."""
    bios = db[BIOS]
    rows = {g: {db[EQUIPMENT[g]].get(i, 'game_id'): i for i in range(db[EQUIPMENT[g]].count)} for g in (False, True)}
    players = values = skipped = 0
    for row, brow, _level in found:
        gear = row.get('gear')
        gid = bios.get(brow, 'game_id')
        if not gear or gid >= SPECIAL_IDS:
            continue
        goalie = row.get('pos') == 'G'
        at = rows[goalie].get(gid)
        if at is None:
            continue
        kind = 'goalie' if goalie else 'skater'
        ok, problems = EQ.clean(db, {CHOICE_OF[kind][f]: v for f, v in gear.items() if f in CHOICE_OF[kind]}, kind)
        skipped += len(problems)
        n = EQ.write(db, at, ok, kind)
        players += bool(n)
        values += n
    return {'gear': players, 'gear_values': values, 'gear_skipped': skipped}


def _pack_gear(db, players, shift):
    """Sock tuck, pant length and a goalie's neck guard of the data pack's `equipment` part (`players`: Legacy's
    real_equipment, a value left out is at the default) on the players matched by full name and birth date. Tape stays
    NHL 27's (_real_gear): the part has only black or white, NHL 19 a colour. Returns the players changed."""
    bios = db[BIOS]
    rows = {g: {db[EQUIPMENT[g]].get(i, 'game_id'): i for i in range(db[EQUIPMENT[g]].count)} for g in (False, True)}
    changed = 0
    for entry, brow, level in R.match(db, players or [], shift=shift):
        goalie, gid = entry.get('pos') == 'G', bios.get(brow, 'game_id')
        if level not in ('exact', 'date') or gid >= SPECIAL_IDS:
            continue
        at = rows[goalie].get(gid)
        if at is not None:
            values = {'neck': entry.get('neck', 0)} if goalie else {'sock_tuck': entry.get('sock', 0),
                                                                    'pant_length': entry.get('pants', 0)}
            changed += bool(EQ.write(db, at, EQ.clean(db, values, 'goalie' if goalie else 'skater')[0],
                                     'goalie' if goalie else 'skater'))
    return changed


PLAIN_MASK = 120  # NHL 19's plain white mask, the one its free agents wear most
GENERIC_MASKS = frozenset({120, 123, 124, 125})  # the stock's masks of no team
COYOTE = frozenset({22, 148})  # Arizona's two masks: never on Utah


def nhl_masks(team):
    """An NHL team's own masks in NHL 19's stock roster: slot n and n + 126 (Vegas 85 and 86). None for Utah (22 and 148
    are Arizona's coyote) and Seattle: their goalies wear the plain one."""
    if team == T.SLOTS['VGK']:
        return (85, 86)
    return (team, team + 126) if team in NHL and team != T.UTAH_SLOT else ()


def _bio_teams(db):
    """{game_id: bio team} of every player, taken before the update moves anyone (_fit_masks, _fit_sticks)."""
    bios = db[BIOS]
    return {bios.get(i, 'game_id'): bios.get(i, 'team') for i in range(bios.count)}


def _team_names(db):
    """{team index: teamname} of exhibitionteams, taken before the update renames a club's slot (_fit_masks)."""
    return {r['index']: r['teamname'] for r in db[T.TEAMS].rows()} if T.TEAMS in db else {}


def _fit_sticks(db, before):
    """A skater who came to an NHL team in this update (moved or made; `before`: _bio_teams at its start) and whose stick
    shows a colour the team does not wear gets the same brand's stick in a team colour (equipment.pick; Legacy's
    sticks.py); on a team of black, white and silver only (Los Angeles) that is the brand's plain stick, which fits every
    team. The players who stayed keep the game's own choice: NHL 19's roster has such sticks on its own teams too.
    Seattle's colours are its Play Now copy's. Returns the sticks changed; a second run changes nothing."""
    bios, eq = db[BIOS], db[EQUIPMENT[False]]
    rows = {eq.get(i, 'game_id'): i for i in range(eq.count)}
    hues, changed = {}, 0
    for i in range(bios.count):
        gid, team = bios.get(i, 'game_id'), bios.get(i, 'team')
        if gid not in rows or before.get(gid) == team or not (team in NHL or team == T.SEATTLE):
            continue
        if team not in hues:
            hues[team] = EQ.team_hues(db, T.SEATTLE_PLAY_NOW if team == T.SEATTLE else team)
        old = eq.get(rows[gid], 'stick')
        if old in EQ.STICK_COLOURS and not EQ.fits(old, hues[team]):
            new = EQ.pick(old, hues[team])
            if new != old:
                eq.set(rows[gid], 'stick', new)
                changed += 1
    return changed


def _fit_masks(db, before, renamed=()):
    """A goalie who changed teams in this update (`before`: _bio_teams at its start) or came in (a new player wears the
    plain mask, equipment.NEW_PLAYER) wears his new team's mask, and his pads and stick in the team's colours, as NHL 19
    does after a trade (keepcustomiftraded / keepcustomstickiftraded are 0 on every stock goalie; a 1 is kept). The mask,
    only of masktype 0: an NHL team's own the team's other goalies wear least (nhl_masks); a club's the mask its goalies
    wore before the update, the most worn (clubs share some: five Swiss clubs wear 119), else the plain one, which Utah,
    Seattle and Coachella Valley get too. A mask that already fits stays, a generic one only on a club without a mask of
    its own. Utah's goalies never keep a coyote, and a club slot the update renamed (`renamed`: Binghamton's playing as
    Abbotsford) has no mask of its own: its goalies lose the old club's (Binghamton's 160 and 81) for the plain one. The
    player's own edits come after (update_ctl replays them). Returns {'masks': masks changed, 'goalie_colours': goalies
    who lost their own colours}."""
    if EQUIPMENT[True] not in db or T.TEAMS not in db:
        return {}
    bios, eq = db[BIOS], db[EQUIPMENT[True]]
    league = {r['index']: r['league'] for r in db[T.TEAMS].rows() if r['index'] not in SHADOW_TEAMS}
    nhl_own = {m for t in NHL for m in nhl_masks(t)} | COYOTE
    worn = collections.defaultdict(collections.Counter)
    rows = {eq.get(i, 'game_id'): i for i in range(eq.count)}
    for gid, team in before.items():
        if gid in rows and league.get(team, 0) in CLUB_LEAGUES - {0}:
            mask = eq.get(rows[gid], 'maskid')
            if mask not in nhl_own and mask not in GENERIC_MASKS:
                worn[team][mask] += 1
    stale = {t: set(worn.pop(t, ())) for t in renamed}
    club = {t: [m for m, _n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))] for t, c in worn.items()}
    goalies = sorted((bios.get(i, 'game_id'), bios.get(i, 'team')) for i in range(bios.count)
                     if bios.get(i, 'position') == GOALIE and bios.get(i, 'game_id') in rows)
    wearing = collections.Counter((team, eq.get(rows[gid], 'maskid')) for gid, team in goalies)
    masks = colours = 0
    for gid, team in goalies:
        at, moved = rows[gid], before.get(gid) != team
        mask = eq.get(at, 'maskid')
        if team in NHL:
            fits, pick = mask in nhl_masks(team), nhl_masks(team)
        elif team in (T.SEATTLE, T.SEATTLE_AHL):
            fits, pick = mask in GENERIC_MASKS, ()
        elif league.get(team) in CLUB_LEAGUES - {0}:
            own = club.get(team, [])
            fits, pick = mask in own or not own and mask in GENERIC_MASKS, own[:1]
        else:  # a free agent, a national team, the All-Stars
            continue
        if moved:
            for show, keep in (('showcustomcolors', 'keepcustomiftraded'), ('showcustomstick', 'keepcustomstickiftraded')):
                if eq.get(at, show) and not eq.get(at, keep):
                    eq.set(at, show, 0)
                    colours += show == 'showcustomcolors'
        if not (moved or team == T.UTAH_SLOT and mask in COYOTE or mask in stale.get(team, ())) or fits \
                or eq.get(at, 'masktype') != 0:
            continue
        new = min(pick, key=lambda m: (wearing[(team, m)], pick.index(m))) if pick else PLAIN_MASK
        wearing[(team, mask)] -= 1
        wearing[(team, new)] += 1
        eq.set(at, 'maskid', new)
        masks += 1
    return {'masks': masks, 'goalie_colours': colours}


def _sync_styles(db, todo):
    """The roster rows' copy of playerstyle for the players whose AI record got another one (`todo`: the rating
    changes). Returns the rows changed."""
    gids = {db[t].get(row, 'game_id') for t, row, f, _o, _n in todo if f == 'playerstyle'}
    if not gids:
        return 0
    style = {}
    for name in AI.values():
        t = db[name]
        for i in range(t.count):
            if t.get(i, 'game_id') in gids:
                style[t.get(i, 'game_id')] = t.get(i, 'playerstyle')
    gid_of = {pi: gid for gid, pis in State(db).pis_of.items() if gid in gids for pi in pis}
    n = 0
    for name in (ROSTER, CUSTOM_ROSTER):
        if name not in db:
            continue
        t = db[name]
        for i in range(t.count):
            gid = gid_of.get(t.get(i, 'playerindex'))
            if gid is not None and t.get(i, 'playerstyle') != style[gid]:
                t.set(i, 'playerstyle', style[gid])
                n += 1
    return n


def _row_overall(p, fields):
    """NHL 27's overall of a pack row."""
    names = fields['goalie' if p.get('pos') == 'G' else 'skater']
    return p['v'][names.index('c_overall')] if 'c_overall' in names else 0


def _estimate_clubs(db, feed, rated, models, season, shift, countries):
    """Ratings by estimate.Estimator for the players the update made for a club (`feed`: _feed_facts) whom nobody rates
    (`rated`: game_ids). Returns (players written, {game_id: level}). A player found on his club keeps what he has."""
    bios = db[BIOS]
    state = State(db)
    dressed = []
    for table in (ROSTER, CUSTOM_ROSTER):
        for i in range(db[table].count if table in db else 0):
            r = db[table].row(i)
            if r[lines.DRESSED] and (r['team'] == T.SEATTLE if table == CUSTOM_ROSTER else r['team'] in NHL):
                b = state.bio(r['playerindex'])
                if b:
                    dressed.append((b['position'], b['game_id']))
    est = estimate.Estimator(db, dressed)
    rows = {name: {db[name].get(i, 'game_id'): i for i in range(db[name].count)} for name in AI.values()}
    written, by_level = 0, {}
    for info in feed.values():
        league = 'chl' if info['tag'] in ('ohl', 'qmjhl', 'whl') else info['tag']
        if league not in estimate.LEAGUE_GAP:
            continue
        home = (countries or {}).get(info['tag'])
        for gid, f in info['made']:
            brow = state.bio_row.get(gid)
            if gid in rated or brow is None:
                continue
            b = bios.row(brow)
            name = f"{f['first']} {f['last']}"
            level = est.target(league, b['position'], season - f['birth'][0], name, f.get('letter'), f.get('rookie'),
                               bool(home and f.get('country') and f['country'] != home))
            table = AI[b['position'] == GOALIE]
            row = rows[table].get(gid)
            if row is None:
                continue
            _rate(db, table, row, est.values(b['position'], level, name), models)
            written += 1
            by_level[gid] = round(level)
    return written, by_level


def _rate(db, table, row, values, models):
    """Attributes `values` on a player's row, and what the game's overall makes of them."""
    cur = db[table].row(row)
    new = dict(cur, **values)
    new.update(models[table].predict(new))
    for field, v in new.items():
        if cur[field] != v:
            db[table].set(row, field, v)


def _estimate_national(db, made, rated, models, season):
    """Ratings by estimate.national for the players the update made for a national team (`made` {game_id: (code, name,
    birth year)}) whom nobody rates (`rated`). Returns the players written."""
    bios, state = db[BIOS], State(db)
    rows = {name: {db[name].get(i, 'game_id'): i for i in range(db[name].count)} for name in AI.values()}
    written = 0
    for gid, (code, name, born) in made.items():
        brow = state.bio_row.get(gid)
        if gid in rated or brow is None:
            continue
        pos = bios.get(brow, 'position')
        table = AI[pos == GOALIE]
        if gid in rows[table]:
            _rate(db, table, rows[table][gid], estimate.national(pos, code, season - born, name), models)
            written += 1
    return written


def _levels(db, pack, full, listed, list_rows):
    """{game_id: a player's level on EA's overall scale}, what his starter deal goes by, on the scale NHL Legacy's update
    ranks him on: a full rating's overall through ratings.level_line (`full`: _nhl27_matches of `pack`), EA's overall
    for a player only its list rates (`listed`: R.match of `list_rows`), else the mean of his attributes; a level is
    moved onto the overall scale by ratings.level_offset."""
    bios, gap, out = db[BIOS], R.level_offset(list_rows), {}
    for goalie, table in AI.items():
        for row in db[table].rows():
            out[row['game_id']] = R.attribute_mean(row, goalie) + gap[goalie]
    for p, brow, _level in listed:
        if p.get('ovr'):
            out[bios.get(brow, 'game_id')] = p['ovr']
    if full:
        line = R.level_line(pack)
        for p, brow, _level in full:
            goalie = p.get('pos') == 'G'
            a, b = line[goalie]
            out[bios.get(brow, 'game_id')] = a + b * _row_overall(p, pack['fields']) + gap[goalie]
    return out


CAP_STOCK, CAP_2026 = 795, 1040  # the cap in $100,000: NHL 19's own (2018-19) and 2026-27's (overlay.CAP_STOCK / CAP_2026)


def money_scale(pack, served):
    """The factor for the deals' dollars: 1 when the game plays the 2026-27 cap (Game patch's league layer, `served`),
    else NHL 19's own cap over 2026-27's (the pack's money table, else CAP_2026): every deal keeps its share of the
    cap, so a team of 2026 deals fits the 2018 cap of $79.5M instead of being $25M over it (Legacy's contracts.GAME,
    71.4 / 104.0, for the PS3 game's cap). The lowest salary comes out right too: $850,000 x 0.764 = $650,000."""
    if served:
        return 1.0
    cap = ((pack or {}).get('money') or {}).get('cap') or CAP_2026
    return CAP_STOCK / cap


def _scaled(values, money):
    if money != 1:
        for f in ('contractdollars', 'extensiondollars'):
            if values.get(f):
                values[f] = max(1, min(16383, round(values[f] * money)))
    return values


def _rights_holder(code):
    """The NHL 19 team that can hold the rights of a player whose NHL.com organisation is `code`, else None (Seattle is
    a custom team; a code NHL 19 has no team for)."""
    try:
        table, team = target_of(code)
    except UpdateError:
        return None
    return team if table == ROSTER else None


def _contracts(db, pack, season, shift, on_clock, level=None, free=(), money=1.0, orgs=None):
    """Contracts after the update: a club player (an NHL team's or Seattle's) gets NHL 27's deal (nhl27.terms), else
    an estimate (nhl27.estimate on his age); a player in another league whom NHL 27 has under an NHL contract gets
    that deal and its organisation (`proteam`), a Seattle deal without one (Seattle is a custom team, and a deal with
    no `proteam` is no stock pattern: contractstatus -1); a club player whose NHL rights a club holds with no deal (the
    pack's `rights`: an unsigned pick) keeps them with no money, as NHL 19's own roster keeps its unsigned picks
    (`proteam` the club, contractstatus 0, $0 and no seasons; Legacy builder.starter_contracts gives such a player no
    starter deal either); anyone else on a club gets a starter deal (nhl27.starter by
    his level, `level` {game_id: value}: _levels), no NHL contract to the game (contractstatus -1, as its own unsigned
    players); a 2018 NHL deal (`proteam` set) of anyone else goes (nhl27.NO_CONTRACT). Free agents keep what they have.
    `on_clock`: the game_ids whose birth year the update put on the game's clock (shift years back). `free`: the
    game_ids on the free agent list, unsigned whatever club their bio names. `money`: money_scale. `orgs` {game_id:
    NHL.com code}: the NHL organisation an AHL club's own list names (the data pack's `leagues.ahl`, _feed_facts); an AHL
    player whom neither deals nor rights cover is that team's, on a two-way deal by his age (nhl27.estimate), as NHL 19's
    own AHL players under an NHL contract and Legacy clubs._rights (Stramel and Dexheimer at Iowa: Minnesota's). Returns
    counts per kind."""
    bios = db[BIOS]
    deal_of = {brow: d for d, brow, _level in _nhl27_matches(db, pack.get('contracts') or [], shift, 'org')}
    rights_of = {brow: r for r, brow, _level in _nhl27_matches(db, pack.get('rights') or [], shift, 'org')
                 if target_of(r['org'])[0] == ROSTER}   # Seattle is a custom team: it holds no rights
    league_of = {r['index']: r['league'] for r in db[T.TEAMS].rows() if r['index'] not in SHADOW_TEAMS}
    league_of.update({team: AHL_LEAGUE for team in FARM_CLUBS})  # Coachella Valley (customteams 498) plays in the AHL
    out = {'deals': 0, 'estimated': 0, 'minors': 0, 'rights': 0, 'organisation': 0, 'cleared': 0, 'starter': 0}
    for brow in range(bios.count):
        b = bios.row(brow)
        if b['game_id'] >= SPECIAL_IDS:
            continue
        deal = deal_of.get(brow)
        holder = _rights_holder((orgs or {}).get(b['game_id']))
        if b['team'] in NHL or b['team'] == T.SEATTLE:
            if deal:
                values, kind = N.terms(deal), 'deals'
            else:
                born = b['year'] + YEAR_BASE + (shift if b['game_id'] in on_clock else 0)
                values, kind = N.estimate(season - born), 'estimated'
            values['contractstatus'] = 0
        elif deal and b['team'] != -1 and target_of(deal['org'])[0] == ROSTER:
            values = dict(N.terms(deal), proteam=target_of(deal['org'])[1], contractstatus=0)
            kind = 'minors'
        elif deal and b['team'] != -1:
            values, kind = dict(N.terms(deal), proteam=-1, contractstatus=-1), 'minors'
        elif brow in rights_of and b['team'] != -1 and b['game_id'] not in free:
            values = dict(N.NO_CONTRACT, proteam=target_of(rights_of[brow]['org'])[1], contractstatus=0)
            kind = 'rights'
        elif holder is not None and league_of.get(b['team']) == AHL_LEAGUE and b['game_id'] not in free:
            born = b['year'] + YEAR_BASE + (shift if b['game_id'] in on_clock else 0)
            values = dict(N.estimate(season - born), contractis2way=1, proteam=holder, contractstatus=0)
            kind = 'organisation'
        elif league_of.get(b['team']) in CLUB_LEAGUES and b['game_id'] not in free:
            born = b['year'] + YEAR_BASE + (shift if b['game_id'] in on_clock else 0)
            row = N.STARTER_ROW.get(league_of[b['team']], 'other')
            values = dict(N.starter(row, (level or {}).get(b['game_id'], 0), season - born), proteam=-1,
                          contractstatus=-1)
            kind = 'starter'
        elif b['proteam'] != -1:
            values, kind = dict(N.NO_CONTRACT), 'cleared'
        else:
            continue
        changed = False
        for f, v in _scaled(values, money).items():
            if b[f] != v:
                bios.set(brow, f, v)
                changed = True
        out[kind] += changed
    return out


AHL_LEAGUE = 1  # exhibitionteams.league of the AHL clubs (nhl27.LEAGUES)
AHL_SIZE = (20, FARM_ROOM)  # players per AHL club after rebuild_ahl, at least AHL_GOALIES of them goalies
AHL_GOALIES = 2
AHL_SKATERS = 18  # lines.build dresses 18 skaters and 2 goalies
AHL_SHAPE = {'F': 12, 'D': 7}  # the skaters a short club is filled towards first
# NHL 19's 2018 AHL clubs that NHL 27 has under another name: the slot takes that club's players and its name
# (rename_ahl); town, abbreviation, division, colours, arena and the parent's farm link follow (teams.AHL_2026). The
# logo and jerseys are the art pack's. NHL 27's Coachella Valley Firebirds are Seattle's (customteams 498,
# teams.SEATTLE_AHL): no slot, their players go into customrostertable (FARM_CLUBS).
AHL_MOVED = {'Binghamton Devils': 'Abbotsford Canucks', 'Bridgeport Sound Tigers': 'Hamilton Hammers',
             'San Antonio Rampage': 'Henderson Silver Knights', 'Stockton Heat': 'Calgary Wranglers'}
FARM_CLUBS = {T.SEATTLE_AHL: 'Coachella Valley Firebirds'}  # AHL clubs of custom teams: {customteams index: club}
EXPANSION_TEAMS = (T.SEATTLE, T.SEATTLE_AHL)  # empty in the expansion start roster (empty_expansion)


def _team_key(name):
    return re.sub('[^a-z]', '', unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower())


def _fuzzy_clubs(teams, free, names):
    """{slot: NHL 27 club key} for the slots (`teams` {index: row}) in `free` (slot indices no club matched by name)
    taking the club left in `names` {key: name} that has their city in its name, else their nickname (its last word),
    when exactly one has: the same franchise under a new name or town (Frolunda Indians / Frolunda HC, Mississauga
    Steelheads / Brampton Steelheads). Two slots never take one club."""
    out, left = {}, set(names)
    for how in ('cityname', 'nickname'):
        for s in sorted(free):
            if s in out:
                continue
            word = _team_key(teams[s][how].split()[-1] if how == 'nickname' and teams[s][how].split()
                             else teams[s][how])
            if len(word) < 4:
                continue
            hit = [k for k in sorted(left) if word in k]
            if len(hit) == 1:
                out[s] = hit[0]
                left.discard(hit[0])
    return out


def _calendar_places(db, key, games, log=lambda m: None):
    """{club name of `games`: place in the league's table} on this roster. A club takes the slot of its name, else of
    its town or nickname (_fuzzy_clubs); a slot left over plays the real calendar of a club left over. Clubs without
    a slot are logged, and their games are left out (leaguecal.other_rows)."""
    league = leaguecal.LEAGUE_TABLES[key][0]
    rows = sorted((r for r in db[T.TEAMS].rows() if r['league'] == league), key=lambda r: r['index'])
    place = {r['index']: i for i, r in enumerate(rows)}
    teams = {r['index']: r for r in rows}
    names = {_team_key(c): c for _d, h, a in games for c in (h, a)}
    slot_of = {}
    for s, r in teams.items():
        for name in (r['teamname'], r['nickname']):
            if _team_key(name) in names and _team_key(name) not in slot_of.values():
                slot_of[s] = _team_key(name)
                break
    left = {k: v for k, v in names.items() if k not in set(slot_of.values())}
    found = _fuzzy_clubs(teams, set(teams) - set(slot_of), left)
    slot_of.update(found)
    played = collections.Counter(_team_key(c) for _d, h, a in games for c in (h, a))
    left = sorted((k for k in left if k not in set(found.values())), key=lambda k: (-played[k], k))
    for s in sorted(set(teams) - set(slot_of)):
        if left:
            slot_of[s] = left.pop(0)
    if left:
        log(f"{key} calendar: no place for {', '.join(names[k] for k in left)}")
    return {names[k]: place[s] for s, k in slot_of.items()}


# NHL 27's clubs that can take over a slot: the pack gives a club no town, and a name does not say which word is one.
CLUB_TOWNS = {'Savannah Ghost Pirates': ('Savannah', 'SAV'), 'Bloomington Bison': ('Bloomington', 'BLM'),
              'Greensboro Gargoyles': ('Greensboro', 'GSO'), 'Tahoe Knight Monsters': ('Tahoe', 'TAH'),
              'Olimpija Ljubljana': ('Ljubljana', 'LJU'), 'HYDRO Fehervar AV 19': ('Fehervar', 'AVS'),
              'EC iDM Warmepumpen VSV': ('Villach', 'VSV'), 'HC Falkensteiner Pustertal Wolfe': ('Pustertal', 'PUS'),
              'Hockey Club Milano': ('Milano', 'MIL')}


def _rename_club(teams, slot, name, whole=False, towns=None):
    """Name slot `slot` (a teams row index) after the club `name`: teamname and nickname. The city is the club's town
    (`towns` {name: (town, abbreviation)}, then CLUB_TOWNS); without one, the first of a two-word name ending with the
    nickname's last word (Brampton Steelheads: Brampton), else the slot's stays. `whole`: another club, not the slot's
    under a new name: its abbreviation too, when known."""
    row = next(i for i in range(teams.count) if teams.get(i, 'index') == slot)
    words, last = name.split(), (teams.get(row, 'nickname') or '').split()
    city = words[0] if len(words) == 2 and last and _team_key(words[-1]) == _team_key(last[-1]) else None
    town, abbr = (towns or {}).get(name) or CLUB_TOWNS.get(name) or (city, None)
    city, abbr = town, abbr if whole else None
    for field, value in (('teamname', name), ('nickname', name), ('cityname', city), ('abbrname', abbr)):
        if value:
            teams.set(row, field, _fit(teams, field, value))


def _group(pos):
    return 'G' if pos in ('G', GOALIE) else 'D' if pos in ('D', 3) else 'F'


def _real_of(p):
    """A pack player (nhl27.py) as the NHL.com rows _Maker.make takes."""
    y, m, d = p['birth']
    return {'first': p['first'], 'last': p['last'], 'birth': f'{y:04d}-{m:02d}-{d:02d}',
            'position': {'LW': 'L', 'RW': 'R'}.get(p['pos'], p['pos']), 'shoots': p.get('hand'),
            'height': p['height'] * 2.54 if p.get('height') else None,
            'weight': p['weight'] / 2.20462 if p.get('weight') else None}


def rebuild_league(db, pack, shift, league=AHL_LEAGUE, tag='ahl', moved=None, prefix='ahl', size=AHL_SIZE,
                   fuzzy=False, frozen=(), free_agents=True, take_over=False, feed=None, free_too=(), custom=None):
    """The clubs' rosters of one league from NHL 27's (`pack`, nhl27.py; the AHL by default, HockeyAllsvenskan in
    ALLSVENSKAN: `league` is exhibitionteams.league, `tag` the pack's league key, `moved` {2018 name: NHL 27 name},
    `prefix` the counts' names, `size` the (least, most) players a club has; `fuzzy`: a slot no club matches by name
    takes the club of its town or nickname (_fuzzy_clubs) and is renamed after it; `frozen`: the leagues whose
    rosters are final (their players stay); `free_agents` False: a short club is not filled from the unsigned
    players; `take_over`: a slot still without a club becomes a club still without a slot, the biggest first, its
    name, city and abbreviation (_rename_club), and a slot's club the pack's game has no room for gives way to a
    club it has; `feed`: a dict _feed_facts fills in; `free_too`: game ids of the bios another list names, the data
    pack's (_listed_ids): one who leaves his club becomes a free agent as those NHL 27 has, so last season's NHL
    players NHL 27 lacks (Aube-Kubel, Legare) are not lost); `custom` {customteams index: club name}: clubs of the
    league that play as a custom team, their rows in customrostertable (the AHL's Coachella Valley, Seattle's farm in
    customteams 498: before, its 25 players were placed nowhere and the team stayed empty). `pack` is the data pack's clubs where it has the league
    (clubdata.merged), so a club's list decides and NHL 27 only rates. The AHL: each slot gets
    its NHL 27 club's players (by name, or AHL_MOVED), less those on an NHL club or Seattle; an existing bio moves
    off his other club or the free agent list, anyone else is created (_Maker). A club left short of AHL_SIZE or of
    AHL_GOALIES goalies is filled from NHL 27's ECHL players of its NHL organisation, then NHL 27's unsigned players
    (its own, then the free agent list's), then its own 2018 players; one over AHL_SIZE loses its lowest rated
    players without an NHL deal first. The 2018 players who leave and play nowhere else are unsigned (_unsign), as
    the released NHL players: with their 2018 deals cleared (_contracts) they were the Franchise's free agents
    (Perron, Gagne, Masin signed on July 1, ws5 run4). Contracts and NHL organisations follow in _contracts, ratings
    and pro history in apply. Returns ({counts}, {teams whose rows changed})."""
    teams = {r['index']: r for r in db[T.TEAMS].rows() if r['league'] == league}
    frozen_slots = {r['index'] for r in db[T.TEAMS].rows() if r['league'] in frozen}
    moved = {_team_key(k): _team_key(v) for k, v in (AHL_MOVED if moved is None else moved).items()}
    by_club, echl, unsigned = {}, {}, []
    pkey = lambda p: (p['first'], p['last'], tuple(p['birth']))  # noqa: E731
    org = {pkey(c): c['org'] for c in pack.get('contracts') or []}
    for p in pack.get('players') or []:
        if not p.get('birth') or p.get('pos') not in POSITION_27:
            continue
        if p.get('league') == tag and p.get('team'):
            by_club.setdefault(_team_key(p['team']), []).append(p)
        elif tag == 'ahl' and p.get('league') == 'echl' and pkey(p) in org:
            echl.setdefault(org[pkey(p)], []).append(p)
        elif p.get('league') is None and free_agents:
            unsigned.append(p)
    source = {s: moved.get(_team_key(r['teamname']), _team_key(r['teamname'])) for s, r in teams.items()}
    custom = {s: _team_key(name) for s, name in (custom or {}).items()}
    source.update(custom)
    source = {s: k for s, k in source.items() if k in by_club}
    where = lambda s: (CUSTOM_ROSTER, s) if s in custom else (ROSTER, s)  # noqa: E731
    renamed = {}
    if fuzzy:
        names = {_team_key(p['team']): p['team'] for ps in by_club.values() for p in ps}
        found = _fuzzy_clubs(teams, set(teams) - set(source),
                             {k: v for k, v in names.items() if k not in set(source.values())})
        source.update(found)
        renamed = {s: names[k] for s, k in found.items() if _team_key(teams[s]['teamname']) != k}
    whole = set()
    if take_over:
        last = {_team_key(n) for n in pack.get('spare') or ()}
        spare = sorted((k for k in by_club if k not in set(source.values()) and len(by_club[k]) >= size[0]),
                       key=lambda k: (k in last, -len(by_club[k]), k))
        free = sorted(set(teams) - set(source))
        # a slot's 2018 club the pack's game has no room for gives way to one it has (Jukurit to Kiekko-Espoo)
        held = sorted(s for s, k in source.items() if k in last)[:max(0, sum(k not in last for k in spare) - len(free))]
        for s, k in zip(free + held, spare):
            source[s], renamed[s] = k, by_club[k][0]['team']
            whole.add(s)
    if not source:
        return {}, set()
    rows = [p for k in source.values() for p in by_club[k]] + [p for ps in echl.values() for p in ps] + unsigned
    brow_of = {id(row): brow for row, brow, level in R.match(db, rows, shift=shift) if level in ('exact', 'date')}
    state, bios = State(db), db[BIOS]
    gid_at = {brow: gid for gid, brow in state.bio_row.items()}

    clubs = {r['index'] for r in db[T.TEAMS].rows() if r['league'] in CLUB_LEAGUES and r['index'] not in SHADOW_TEAMS}

    def club_entry(pi):
        e = state.entry.get(pi)
        return e if e is not None and e[0] == ROSTER and e[1] in clubs else None
    taken = set()  # on an NHL club, or a custom team (Seattle and its AHL club): placed by NHL.com, or not ours
    for gid, pis in state.pis_of.items():
        if any(state.entry.get(pi, ('', -1))[0] == CUSTOM_ROSTER and state.entry[pi][1] not in custom
               or state.entry.get(pi, ('', -1))[0] == ROSTER
               and (state.entry[pi][1] in NHL or state.entry[pi][1] in frozen_slots) for pi in pis):
            taken.add(gid)
    used = set()

    def item(p):
        brow = brow_of.get(id(p))
        gid = gid_at.get(brow) if brow is not None else None
        if gid is not None and (gid in taken or gid in used) or ('new', pkey(p)) in used:
            return None
        fields = pack['fields']['goalie' if p['pos'] == 'G' else 'skater']
        ovr = p['v'][fields.index('c_overall')] if 'c_overall' in fields else 0
        return {'p': p, 'gid': gid, 'pos': _group(p['pos']), 'ovr': ovr, 'deal': pkey(p) in org}

    def take(it):
        used.add(it['gid'] if it['gid'] is not None else ('new', pkey(it['p'])))
        return it
    plan = {}
    for s in sorted(source):
        club = [it for it in map(item, by_club[source[s]]) if it]
        club = [take(it) for it in club]
        plan[s] = club
    # the slots' own players, read before any player is made (exhibitionplayers is sorted until then: State.bio)
    on_slot = {s: [(pi, b) for pi, e in state.entry.items() if e == where(s) for b in [state.bio(pi)] if b]
               for s in set(teams) | set(custom)}
    counts = {f'{prefix}_teams': len(plan), f'{prefix}_filled': 0, f'{prefix}_trimmed': 0, f'{prefix}_kept_2018': 0}
    for s, club in sorted(plan.items()):
        affiliate = None
        orgs = [org[pkey(it['p'])] for it in club if pkey(it['p']) in org]
        if orgs:
            affiliate = max(set(orgs), key=lambda o: (orgs.count(o), o))
        own = {b['game_id'] for _pi, b in on_slot[s]}
        pools = [sorted(echl.get(affiliate, []), key=lambda p: p['last']),
                 [p for p in unsigned if gid_at.get(brow_of.get(id(p))) in own],
                 [p for p in unsigned if any(pi in state.free for pi in state.pis_of.get(gid_at.get(
                     brow_of.get(id(p))), []))]]

        def fill(want):
            for pool in pools:
                cands = [it for it in map(item, pool) if it and (want is None or it['pos'] == want)]
                if cands:
                    return take(max(cands, key=lambda it: (it['ovr'], it['p']['last'])))
            stale = [b for _pi, b in on_slot[s] if b['game_id'] not in used and b['game_id'] not in taken
                     and b['position'] <= GOALIE and (want is None or _group(b['position']) == want)]
            if stale:
                b = max(stale, key=lambda b: (_ai_value(db, b, 'c_overall', 0), -b['game_id']))
                counts[f'{prefix}_kept_2018'] += 1
                return take({'p': None, 'gid': b['game_id'], 'pos': _group(b['position']), 'ovr': 0, 'deal': False})
            return None
        while sum(it['pos'] == 'G' for it in club) < AHL_GOALIES and (it := fill('G')):
            club.append(it)
            counts[f'{prefix}_filled'] += 1
        while len(club) < size[0] or sum(it['pos'] != 'G' for it in club) < AHL_SKATERS:
            have = {g: sum(it['pos'] == g for it in club) for g in 'FD'}
            want = next((g for g in 'FD' if have[g] < AHL_SHAPE[g]), None)
            if want is None and len(club) >= size[0]:  # enough players, too few skaters
                want = 'F'
            it = fill(want) or fill(None)
            if not it:
                break
            club.append(it)
            counts[f'{prefix}_filled'] += 1
        while len(club) > size[1]:
            goalies = sum(it['pos'] == 'G' for it in club)
            skaters = len(club) - goalies
            out = min((it for it in club if it['pos'] == 'G' and goalies > AHL_GOALIES + 1
                       or it['pos'] != 'G' and skaters > AHL_SKATERS),
                      key=lambda it: (it['deal'], it['ovr'], it['p']['last'] if it['p'] else ''))
            club.remove(out)
            used.discard(out['gid'] if out['gid'] is not None else ('new', pkey(out['p'])))
            counts[f'{prefix}_trimmed'] += 1
    # write: rows off their old clubs and the free agent list, new rows on the slots
    maker = _Maker(db)
    remove, adds, free_out, changed = set(), [], set(), set(plan)
    kept_gids = set()
    created = moved_n = 0
    for s, club in sorted(plan.items()):
        here = {b['game_id']: pi for pi, b in on_slot[s]}
        numbers = set()
        for it in club:
            if it['gid'] is not None and it['gid'] in here:
                numbers.add(bios.get(state.bio_row[it['gid']], 'jersey'))
        for it in club:
            gid = it['gid']
            if gid is not None and gid in here:  # stays on his club
                kept_gids.add(gid)
                it['pi'] = here[gid]
                continue
            if gid is None:
                number = next(k for k in range(2, 99) if k not in numbers)
                numbers.add(number)
                pi, gid, style, _donor = maker.make(_real_of(it['p']), s, -1, number, None, shift)
                brow = bios.count - 1
                for f, v in dict(N.NO_CONTRACT, contractstatus=-1).items():
                    bios.set(brow, f, v)
                state.bio_row[gid] = brow
                it['gid'], it['made'] = gid, True
                created += 1
            else:
                pis = state.pis_of.get(gid, [])
                pi = next((p for p in pis if club_entry(p)), None) or next((p for p in pis if p in state.free),
                                                                            None) or state.main_pi(gid)
                if pi is None:
                    continue
                if state.entry.get(pi):
                    remove.add(pi)
                    changed.add(state.entry[pi][1]) if state.entry[pi][0] == ROSTER else None
                free_out |= {p for p in pis if p in state.free}
                brow = state.bio_row[gid]
                own = bios.get(brow, 'jersey')
                number = own if 1 <= own <= 99 and own not in numbers else next(k for k in range(2, 99)
                                                                                 if k not in numbers)
                numbers.add(number)
                # a minor league club's player without an NHL deal: contractstatus -1, as the stock roster
                # (_sign_free_agents); NHL 27's deal and its organisation come in _contracts
                values = {'team': s, 'jersey': number} if it['deal'] else dict(N.NO_CONTRACT, team=s, jersey=number,
                                                                               contractstatus=-1)
                for f, v in values.items():
                    if bios.get(brow, f) != v:
                        bios.set(brow, f, v)
                style = _ai_value(db, bios.row(brow), 'playerstyle', 0)
                moved_n += 1
            kept_gids.add(gid)
            it['pi'] = pi
            adds.append((s, {'team': s, 'playerindex': pi, 'jersey': number, 'playerstyle': style}))
    # who NHL 27 or another list (`free_too`) has anywhere: a 2018 player who leaves his club for good is a free agent
    # if so, else he goes as the old free agents nobody lists (_retire)
    listed = {gid_at[brow] for _p, brow, _l in _nhl27_matches(db, pack['players'], shift, 'team') if brow in gid_at}
    listed |= set(free_too)
    cleared, free_in = 0, set()
    for s in plan:
        for pi, b in on_slot[s]:
            if b['game_id'] in kept_gids:
                continue
            remove.add(pi)
            others = [p for p in state.pis_of.get(b['game_id'], []) if p != pi and p not in remove and club_entry(p)]
            if not others and b['game_id'] not in taken:
                _unsign(bios, state.bio_row[b['game_id']], b)
                cleared += 1
                if b['game_id'] in listed:
                    free_in.add(pi)
    _rebuild_roster(db[ROSTER], remove, [a for a in adds if a[0] not in custom])
    if custom:
        _rebuild_roster(db[CUSTOM_ROSTER], remove, [a for a in adds if a[0] in custom])
    if free_out or free_in:
        _rebuild_free(db, remove=free_out, add=free_in)
    if created:
        sort_players(db)
    for s, name in sorted(renamed.items()):
        _rename_club(db[T.TEAMS], s, name, s in whole, pack.get('towns'))
    if feed is not None:
        _feed_facts(db, plan, feed, tag, custom)
    counts.update({f'{prefix}_renamed': len(renamed), f'{prefix}_players': sum(len(c) for c in plan.values()), f'{prefix}_created': created,
                   f'{prefix}_moved': moved_n, f'{prefix}_cleared': cleared, f'{prefix}_to_free_agents': len(free_in)})
    return counts, changed


def _feed_facts(db, plan, feed, tag, custom=()):
    """What a club's own list says, over NHL 27's row (`plan`: rebuild_league's, {slot: [item]}): height, weight, hand,
    position and number. A goalie stays one and a plain 'forward' the forward he is (a defenceman moves up); listed
    numbers win a clash, the others keep theirs or take the lowest free one. `feed` {slot: {'club': name, 'letters':
    {exhibitionplayers index: 'C' | 'A'}, 'tag': league, 'made': [(game_id, entry)], 'orgs': {game_id: NHL.com code}}}
    is filled in for _club_finish, _estimate_clubs and _contracts, who run after the ratings. A forward the update made
    and whose list says only 'F' takes C, LW and RW in turn."""
    bios = db[BIOS]
    brow_of = {bios.get(i, 'game_id'): i for i in range(bios.count)}
    # a club's rows: exhibitionrostertable's, or customrostertable's for Coachella Valley (rebuild_league `custom`)
    rows = {(t.get(i, 'team'), t.get(i, 'playerindex')): (t, i)
            for t in [db[n] for n in (ROSTER, CUSTOM_ROSTER) if n in db] for i in range(t.count)}
    entry = lambda it: (it['p'] or {}).get('feed') or {}  # noqa: E731
    forwards = itertools.cycle((0, 1, 2))
    for s, club in plan.items():
        listed = [it for it in club if entry(it)]
        if not listed:
            continue
        feed[s] = {'club': listed[0]['p']['team'], 'letters': {}, 'tag': tag, 'made': [],
                   'orgs': {it['gid']: entry(it)['org'] for it in listed if entry(it).get('org')},
                   'table': CUSTOM_ROSTER if s in custom else ROSTER}
        taken = set()
        for it in sorted(club, key=lambda it: (not entry(it).get('num'), -it['ovr'])):
            f, brow, (roster, row) = entry(it), brow_of.get(it['gid']), rows.get((s, it.get('pi')), (None, None))
            if brow is None or row is None:
                continue
            number = min(f.get('num') or roster.get(row, 'jersey'), 99)
            if not number or number in taken:
                number = next(k for k in range(2, 99) if k not in taken)
            taken.add(number)
            values = {'jersey': number}
            p = it['p'] or {}
            inches = f.get('height_in') or (f.get('height_cm') and round(f['height_cm'] / 2.54)) or p.get('height')
            pounds = f.get('weight_lb') or (f.get('weight_kg') and round(f['weight_kg'] * 2.20462)) or p.get('weight')
            hand = f.get('shoots') if f.get('shoots') in ('L', 'R') else p.get('hand')
            if inches:
                values['height'] = max(0, min(31, round(inches) - HEIGHT_BASE))
            if pounds:
                values['weight'] = max(0, min(255, round(pounds) - WEIGHT_BASE))
            if hand in ('L', 'R'):
                values['handedness'] = int(hand == 'R')
            now = bios.get(brow, 'position')
            pos = (0 if now == POSITION['D'] else now) if f.get('pos') == 'F' else POSITION.get(f.get('pos'))
            if it.get('made'):
                feed[s]['made'].append((it['gid'], f))
                if f.get('pos') == 'F':
                    pos = next(forwards)
            if pos is not None and GOALIE not in (now, pos):
                values['position'] = pos
            for name, v in values.items():
                if bios.get(brow, name) != v:
                    bios.set(brow, name, v)
            if roster.get(row, 'jersey') != number:
                roster.set(row, 'jersey', number)
            if f.get('letter'):
                feed[s]['letters'][it['pi']] = f['letter']


def _club_finish(db, feed, club_lines, log=lambda m: None):
    """The clubs of `feed` (_feed_facts) their real lines (`club_lines`, clubdata.club_lines: found on the club by the
    full name, else by the last name and initial when only one player has them; the same rule as the NHL's, reallines.
    line_up) and their letters. Returns {'club_lined': n, 'club_refused': {club name: [why]}}."""
    state = State(db)
    lined, refused = 0, {}
    for s, info in sorted(feed.items()):
        table = info.get('table', ROSTER)
        roster = db[table]
        wanted = (club_lines or {}).get(info['club'])
        if wanted:
            full, short = {}, {}
            for i in range(roster.count):
                b = state.bio(roster.get(i, 'playerindex')) if roster.get(i, 'team') == s else None
                if b:
                    first, last = _key(b['firstname']), _key(b['lastname'])
                    full.setdefault(first + last, []).append(roster.get(i, 'playerindex'))
                    short.setdefault((last, first[:1]), []).append(roster.get(i, 'playerindex'))
            key = {}
            for slot, who in wanted.items():
                first, last = _key(who[0]), _key(who[1])
                found = full.get(first + last) or short.get((last, first[:1])) or []
                if len(found) == 1:
                    key[slot] = found[0]
            problems = reallines.line_up(db, table, s, key, {pi: pi for pi in key.values()})
            if problems:
                refused[info['club']] = problems
                log(f"real lines {info['club']}: kept the lines it had ({problems[0]})")
            else:
                lined += 1
        reallines.club_letters(db, table, s, info['letters'])
    return {'club_lined': lined, 'club_refused': refused}


def rebuild_ahl(db, pack, shift, feed=None, free_too=()):
    """The AHL clubs' rosters from NHL 27's or the data pack's (rebuild_league's defaults), Coachella Valley's in
    customteams 498 (FARM_CLUBS)."""
    return rebuild_league(db, pack, shift, feed=feed, free_too=free_too,
                          custom=FARM_CLUBS if CUSTOM_ROSTER in db else None)


def rename_ahl(db, only=None):
    """Name the slots whose 2018 club NHL 27 has under another name (AHL_MOVED) after that club: teamname and nickname
    (`only`: just the slots that got its players). The rest of the club's record and the farm links follow in
    teams.apply. A slot already renamed is left alone. Returns the slots renamed."""
    teams = db[T.TEAMS]
    moved = {_team_key(k): v for k, v in AHL_MOVED.items()}
    out = []
    for i in range(teams.count):
        if teams.get(i, 'league') != AHL_LEAGUE or only is not None and teams.get(i, 'index') not in only:
            continue
        name = moved.get(_team_key(teams.get(i, 'teamname')))
        if name is None:
            continue
        for field in ('teamname', 'nickname'):
            teams.set(i, field, _fit(teams, field, name))
        out.append(teams.get(i, 'index'))
    return out


ALLSVENSKAN = 8   # exhibitionteams.league of HockeyAllsvenskan (swedish2ndschedule, 14 clubs, 52 games)
# NHL 19's 2018 Allsvenskan slots NHL 27 has other clubs for (promoted, relegated or folded since): the slot becomes
# that club (name, abbreviation); its logo and jerseys come with the art pack by the new name. The 8 clubs NHL 27
# still has (AIK, Almtuna, BIK Karlskoga, Leksands, MODO, IK Oskarshamn, Sodertalje, Vik Vasteras) keep their slot.
# {2018 name: (NHL 27 name, city, abbreviation)}
ALLSVENSKAN_MOVED = {
    'IF Bjorkloven': ('Ostersunds IK', 'Ostersund', 'OST'),
    'Karlskrona Hockey': ('Kalmar HC', 'Kalmar', 'KAL'),
    'IK Pantern': ('Nybro Vikings IF', 'Nybro', 'NYB'),
    'Tingsryds AIF': ('Vimmerby Hockey', 'Vimmerby', 'VIM'),
    'Vasterviks IK': ('Visby/Roma HK', 'Visby', 'VIS'),
    'HC Vita Hasten': ('Mora IK', 'Mora', 'MORA'),
}


def rename_allsvenskan(db, only=None):
    """Name the slots NHL 27 has other clubs for (ALLSVENSKAN_MOVED) after them: teamname, nickname, city and
    abbreviation (`only`: just those slots, the ones that got NHL 27's players). A slot already renamed is left
    alone. Returns the slots renamed."""
    teams = db[T.TEAMS]
    moved = {_team_key(k): v for k, v in ALLSVENSKAN_MOVED.items()}
    out = []
    for i in range(teams.count):
        if teams.get(i, 'league') != ALLSVENSKAN or only is not None and teams.get(i, 'index') not in only:
            continue
        new = moved.get(_team_key(teams.get(i, 'teamname')))
        if new is None:
            continue
        name, city, abbr = new
        for field, value in (('teamname', name), ('nickname', name), ('cityname', city), ('abbrname', abbr)):
            teams.set(i, field, _fit(teams, field, value))
        out.append(teams.get(i, 'index'))
    return out


POSITION_27 = ('C', 'LW', 'RW', 'D', 'G')
# The club leagues rebuilt from NHL 27 after the AHL and HockeyAllsvenskan: exhibitionteams.league -> (the pack's league
# key, (least, most) players a club has; NHL 19's own clubs go to 38). A slot the source has no club for becomes one
# the league has no slot for (take_over; not the Europe teams, a few clubs only); else it keeps its 2018 roster (its
# players NHL 27 still lists get its ratings). Clubs over the league's slots are not added.
LEAGUE_PLAN = {2: ('shl', (20, 38)), 3: ('liiga', (20, 38)), 4: ('del', (20, 38)), 5: ('extraliga', (20, 38)),
               6: ('nl', (20, 38)), 7: ('icehl', (20, 38)), 9: ('europe', (20, 38)), 11: ('ohl', (20, 38)),
               12: ('qmjhl', (20, 38)), 13: ('whl', (20, 38)), 15: ('echl', (20, 38))}


FA_RETIRE_AGE = 35  # Legacy builder.FA_RETIRE_AGE
# NHL 27's players cover every league NHL 19's free agents come from (NHL, AHL, ECHL, CHL, the European leagues,
# national teams): a 2018 free agent none of its lists, NHL.com or the data pack has is retired, or plays where no
# free agent comes from (KHL). From 30 on he retires; a younger one stays a free agent (Sprong, Mete, Gurianov play in
# the KHL and can still be signed), as Legacy does for a roster that starts from the game's own (stock_retire_age)
NHL27_RETIRE_AGE = 30
# a player of last season's NHL whom no club signed retires at this age, whatever lists him (Kopitar, Toews, Quick;
# Legacy builder.UNSIGNED_RETIRE_AGE, owner 2026-10-28)
UNSIGNED_RETIRE_AGE = 38
# exhibitionteams.league of the clubs (NHL 19 numbers the leagues as NHL 27 does, nhl27.LEAGUES): NHL, AHL, the
# European leagues, CHL, ECHL; not 10 (national teams), 14 (Top Prospects) or 16 on (event teams: Threes, alumni...)
CLUB_LEAGUES = frozenset(range(10)) | {11, 12, 13, 15}


def _birth_text(v):
    if isinstance(v, (list, tuple)) and len(v) == 3:
        return f'{v[0]:04d}-{v[1]:02d}-{v[2]:02d}'
    return v if isinstance(v, str) else ''


def retire_free_agents(db, active, season=DEFAULT_SEASON, min_age=FA_RETIRE_AGE, gone=()):
    """Free agents `min_age` or older whom `active` does not list (the data pack's NHL players of last season, the
    club leagues' and national squads' players, NHL 27's players) retire: off the free agent list, like the ~780
    players the stock roster has on no team and no list (Vanek, Grabner...). Those `gone` names (gone_people) retire
    at any age unless `active` lists them. Returns [(playerindex, name, age)]."""
    out = retirees(db, active, season, min_age, gone)
    _retire(db, out)
    return out


def retirees(db, active, season=DEFAULT_SEASON, min_age=FA_RETIRE_AGE, gone=()):
    """The free agents retire_free_agents() would retire, nothing changed. Their age counts on the real calendar: a
    bio the update did not place keeps EA's real birth year. A free agent with another record on a club stays; one on
    an All-Star, national or event team (2018's) does not count."""
    state, on_club = State(db), _club_test(db)
    fas = []
    for pi in sorted(state.free):
        b = state.bio(pi)
        if b is not None and not on_club(state, b['game_id']):
            fas.append((pi, b))
    people = [Person(pi, b['firstname'], b['lastname'], _birth(b)) for pi, b in fas]

    def matched(rows):
        reals = [Person(i, p.get('first') or '', p.get('last') or '', _birth_text(p.get('birth')))
                 for i, p in enumerate(rows)]
        matcher = Matcher(people, shifts=range(T.year_shift(season) + 1))
        return {m.game.key for m in matcher.match_all(reals) if m.game is not None}
    playing, retired = matched(active), matched(gone) if gone else set()
    out = []
    for pi, b in fas:
        age = season - YEAR_BASE - b['year']
        if pi not in playing and (age >= min_age or pi in retired):
            out.append((pi, f"{b['firstname']} {b['lastname']}", age))
    return out


def _club_test(db):
    """on_club(state, game_id): has the bio a record on a club (not an All-Star, national or event team of 2018's)."""
    league = {r['index']: r['league'] for r in db[T.TEAMS].rows()} if T.TEAMS in db else {}

    def club(entry):
        table, team = entry
        return table != ROSTER or (not 31 <= team <= 34 and league.get(team, 0) in CLUB_LEAGUES)
    return lambda state, gid: any(club(state.entry[o]) for o in state.pis_of.get(gid, []) if o in state.entry)


def _retire(db, rows):
    if not rows:
        return
    state, bios = State(db), db[BIOS]
    for pi, _name, _age in rows:
        b = state.bio(pi)
        if b is not None:
            _unsign(bios, state.bio_row[b['game_id']], b)
    _rebuild_free(db, remove=[pi for pi, _n, _a in rows], add=())


def _person_key(p):
    """Name and birth year: NHL 27 and NHL.com may differ on the day (Benjamin / Ben Kindel)."""
    return _team_key(p.get('first') or ''), _team_key(p.get('last') or ''), _birth_text(p.get('birth'))[:4]


def gone_people(pack, season=DEFAULT_SEASON):
    """Who retired although he played last season (Legacy builder.retired_people): the data pack's `retired` list
    (announced: Kopitar), and last season's NHL players (`nhl_last`) no club has signed (no team) who are
    UNSIGNED_RETIRE_AGE or older this season (born `season` - 38 or earlier: Toews, Quick; at 37 he stays a free
    agent). A club league or national squad that lists him still wins (still_playing, retirees)."""
    pack = pack or {}
    out = {_person_key(p): p for p in pack.get('retired') or [] if p.get('birth')}
    for p in pack.get('nhl_last') or []:
        if p.get('birth') and not p.get('team') and p['birth'][0] <= season - UNSIGNED_RETIRE_AGE:
            out.setdefault(_person_key(p), p)
    return [out[k] for k in sorted(out)]


def without_gone(players, gone, free_only=False):
    """`players` but those `gone` (gone_people) names; `free_only`: only the ones on no team (NHL 27's free agents:
    Petry; NHL 27 on a club wins)."""
    keys = {_person_key(p) for p in gone or ()}
    return [p for p in players or () if _person_key(p) not in keys or free_only and p.get('team')]


UNSIGNED_NUMBER = 19  # the number NHL 19 gives most of its free agents (52 of the stock's 90)


def unsigned_last(pack, season=DEFAULT_SEASON):
    """Last season's NHL players (`nhl_last`) no club has signed (no team), but those who retired (gone_people)."""
    pack = pack or {}
    return without_gone([p for p in pack.get('nhl_last') or [] if p.get('birth') and p.get('pos') and not p.get('team')],
                        gone_people(pack, season))


def add_unsigned(db, rows, shift, drafts=None):
    """Last season's unsigned NHL players (`rows`: unsigned_last) are free agents, as Legacy's builder.add_unsigned:
    one the roster has on no club and off every list goes onto the free agent list; one it lacks is made (_Maker: a
    generic donor of his position and build, NHL 27's or EA's ratings come after in apply), with no deal, NHL 19's usual
    free agent number. One on a club stays there (NHL 27 has him in Europe); a national team record does not count.
    A free agent's bio still on EA's real birth year goes onto the game's clock (_clock_nhl27). Before, the 2018 bios of
    Aube-Kubel and Légaré were on no team and off the list, and Hunter Shepard was not in the game. Returns ({counts},
    game ids made or put on the clock)."""
    state, bios, on_club = State(db), db[BIOS], _club_test(db)
    found = {id(r): (r, brow, level) for r, brow, level in R.match(db, rows, shift=shift)}
    listed, made, clock, maker = [], set(), [], None
    for p in rows:
        hit = found.get(id(p))
        if hit is not None:
            gid = bios.get(hit[1], 'game_id')
            pis = state.pis_of.get(gid, [])
            if pis and bios.get(hit[1], 'team') == -1 and not on_club(state, gid):
                clock.append(hit)
                if not any(pi in state.free for pi in pis):
                    listed.append(min(pis, key=lambda pi: (pi in state.entry, pi)))
            continue
        maker = maker or _Maker(db)
        real = dict(_absent_row(p, -1), country=p.get('country'))
        pi, gid, _style, _donor = maker.make(real, -1, -1, UNSIGNED_NUMBER, drafts, shift)
        for f, v in dict(N.NO_CONTRACT, contractstatus=-1).items():
            bios.set(bios.count - 1, f, v)
        listed.append(pi)
        made.add(gid)
    clocked = _clock_nhl27(db, clock, shift)
    if made:
        sort_players(db)
    if listed:
        _rebuild_free(db, remove=(), add=listed)
    return {'unsigned_listed': len(listed) - len(made), 'unsigned_made': len(made)}, made | clocked


def still_playing(pack, season=DEFAULT_SEASON):
    """The players the data pack `pack` lists anywhere this season: NHL last season (but those gone_people retired),
    club leagues, national squads."""
    pack = pack or {}
    out = without_gone(pack.get('nhl_last'), gone_people(pack, season))
    for league in (pack.get('leagues') or {}).values():
        for team in league.get('teams') or []:
            out += team.get('players') or []
    for squad in (pack.get('iihf') or {}).values():
        out += squad or []
    return out


def empty_expansion(db):
    """Seattle's players become free agents and the expansion team starts empty, as in the stock default roster:
    Franchise fills team 499 in its expansion draft, and with Seattle's rows already in the default roster the game
    crashed on the Creation Zone's save (run x4-20261016/run1: it read a team-499 player its league did not have; with
    the rows gone, run2 saved and started the Franchise). Its AHL club Coachella Valley (customteams 498, in the
    32-team AHL only with the expansion) starts empty the same way. Returns the playerindexes released."""
    state = State(db)
    gone = sorted(pi for pi, e in state.entry.items() if e[0] == CUSTOM_ROSTER and e[1] in EXPANSION_TEAMS)
    bios = db[BIOS]
    for pi in gone:
        b = state.bio(pi)
        if b is not None:
            _unsign(bios, state.bio_row[b['game_id']], b)
    if gone:
        _rebuild_roster(db[CUSTOM_ROSTER], set(gone), [])
        _rebuild_free(db, remove=(), add=gone)
    expansion_active(db)
    return gone


def expansion_free_agents(db):
    """Seattle's players also on the free agent list, still on team 499 with their deals. The expansion career takes
    its free agent pool from the default roster (nhl_game.db) and its teams from expansion_draft.db, where team 499 is
    empty (overlay.mode_roster_files): without this, the 25 were in no pool there (ws8 s2). Season and Classic
    Franchise do not list a free agent who is on a roster (ws8 s3). Coachella Valley's players too (empty_expansion).
    Returns the playerindexes added."""
    state = State(db)
    add = sorted(pi for pi, e in state.entry.items()
                 if e[0] == CUSTOM_ROSTER and e[1] in EXPANSION_TEAMS and pi not in state.free)
    if add:
        _rebuild_free(db, remove=(), add=add)
    return add


def _seattle_has_players(db, team=T.SEATTLE):
    t = db[CUSTOM_ROSTER]
    return any(t.get(i, 'team') == team for i in range(t.count))


def _seattle_row(db, team=T.SEATTLE):
    t = db[T.CUSTOM]
    return next((i for i in range(t.count) if t.get(i, 'index') == team), None)


def expansion_active(db):
    """customteams 499's `active` = whether Seattle has players. With the 32-team switch (xmlpatch.expansion32)
    Season's team list asks the team-ratings service without a mode context, and that service leaves out a custom
    team that is not active: Seattle got no ratings entry and New Season crashed (ws8 run7a; active, run7b played).
    The default roster's empty expansion team stays inactive, as in the stock roster. Coachella Valley (498) follows
    the same rule (not played yet with players). Returns Seattle's value."""
    out = None
    for team in EXPANSION_TEAMS:
        value, row = int(_seattle_has_players(db, team)), _seattle_row(db, team)
        if row is None:
            continue
        t = db[T.CUSTOM]
        if t.get(row, 'active') != value:
            t.set(row, 'active', value)
        out = value if out is None else out
    return out


def seattle_ready(db):
    """Whether the roster takes the 32-team switch (xmlpatch.expansion32): Seattle has players and customteams 499
    is active. The stock roster, the older default rosters (empty_expansion) and custom rosters saved before
    expansion_active are not: New Season crashes with the switch on (ws8 run7a)."""
    return _seattle_has_players(db) and db[T.CUSTOM].get(_seattle_row(db), 'active') == 1


def _mirror_rows(db):
    """[row] of exhibitionrostertable's team 399, in order."""
    t = db[ROSTER]
    return [t.row(i) for i in range(t.count) if t.get(i, 'team') == MIRROR]


def mirror_seattle(db):
    """Seattle for Play Now and the online roster: exhibitionteams 399 (teams.SEATTLE_PLAY_NOW) gets customrostertable's
    team 499 rows (numbers, lines, captains), each player through an exhibitionplayers record of its own, as the
    All-Star teams have theirs; a player keeps his record from an earlier run, so a second run changes nothing. Play
    Now lists exhibition teams only, and the online roster (`rosterupdate` savegroup) has no custom team tables. With
    team 499 empty (the default roster after empty_expansion) team 399 keeps its rows. Returns the number of
    players on team 399."""
    if CUSTOM_ROSTER not in db:
        return 0
    custom, roster, players = db[CUSTOM_ROSTER], db[ROSTER], db[PLAYERS]
    src = [custom.row(i) for i in range(custom.count) if custom.get(i, 'team') == T.SEATTLE]
    old_rows = _mirror_rows(db)
    if not src:
        return len(old_rows)
    gid = _record_ids(db)
    want = [(gid.get(r['playerindex']), _slot_values(r)) for r in src]
    if any(g is None for g, _v in want):
        raise UpdateError("Seattle's roster points at a player without a regular exhibitionplayers record")
    old = [r['playerindex'] for r in old_rows]
    elsewhere = {roster.get(i, 'playerindex') for i in range(roster.count) if roster.get(i, 'team') != MIRROR}
    elsewhere |= {custom.get(i, 'playerindex') for i in range(custom.count)}
    elsewhere |= {db[FREE].get(i, 'playerindex') for i in range(db[FREE].count)}
    own = {gid[pi]: pi for pi in old if pi not in elsewhere and pi in gid}  # records only team 399 uses
    if [(gid.get(r['playerindex']), _slot_values(r)) for r in old_rows] == want and set(old) == set(own.values()):
        return len(want)
    keep = {g for g, _v in want}
    drop = {pi for g, pi in own.items() if g not in keep}
    used = {players.get(i, 'index') for i in range(players.count)}
    if 'customplayers' in db:
        used |= {db['customplayers'].get(i, 'index') for i in range(db['customplayers'].count)}
    nxt = 1 + max(i for i in used - drop if i < SPECIAL_IDS)
    adds = []
    for g, values in want:
        pi = own.get(g)
        if pi is None:
            while nxt in used:
                nxt += 1
            if nxt >= SPECIAL_IDS:
                raise UpdateError(f'no free player index left below {SPECIAL_IDS}')
            pi, nxt = nxt, nxt + 1
            used.add(pi)
            players.append({'table': 0, 'index': pi, 'playerid': g})
        adds.append((MIRROR, dict(values, team=MIRROR, playerindex=pi)))
    for i in reversed(range(players.count)):
        if players.get(i, 'index') in drop and players.get(i, 'table') == 0:
            players.delete(i)
    players.sort_by('index')
    _rebuild_roster(roster, set(old), adds)
    return len(adds)


NATIONAL = 10   # exhibitionteams.league of the national teams
# the data pack's IIHF code -> NHL 19's national team (its spelling). Russia has no IIHF squad: fill_national
NATIONAL_TEAMS = {'AUT': 'Austria', 'BLR': 'Belarus', 'CAN': 'Canada', 'CZE': 'Czech Republic', 'DNK': 'Denmark',
                  'FIN': 'Finland', 'FRA': 'France', 'DEU': 'Germany', 'GBR': 'Great Britain', 'ITA': 'Italy',
                  'JPN': 'Japan', 'KAZ': 'Kazakstan', 'LVA': 'Latvia', 'NOR': 'Norway', 'POL': 'Poland',
                  'SVK': 'Slovakia', 'SWE': 'Sweden', 'CHE': 'Switzerland', 'UKR': 'Ukraine', 'USA': 'USA'}
RUSSIA = 'Russia'
NATIONAL_ROOM, NATIONAL_LEAST = 26, {'G': 3, 'D': 7, 'F': 13}
NATIONAL_AGE = 38   # the oldest a club player is called up


def _national_code(key):
    return 'RUS' if key == _team_key(RUSSIA) else next((c for c, n in NATIONAL_TEAMS.items() if _team_key(n) == key), None)


def _national_slots(db):
    """{national team's name key: team index}."""
    return {_team_key(r['nickname']): r['index'] for r in db[T.TEAMS].rows() if r['league'] == NATIONAL}


def _set_squad(db, maker, state, slot, picks, made=None):
    """National team `slot` is `picks` [(game_id, number or None)]. A player keeps the record he has on the team, or
    the one just made for him (`made` {game_id: record}), else he gets a new one: a national team's records are its
    own, as the All-Stars'. An old record goes unless it is the bio's last one. Returns the players."""
    roster, players, bios = db[ROSTER], db[PLAYERS], db[BIOS]
    old = [roster.get(i, 'playerindex') for i in range(roster.count) if roster.get(i, 'team') == slot]
    gid_of = _record_ids(db)
    own = {gid_of[pi]: pi for pi in old if pi in gid_of} | (made or {})
    numbers, adds = set(), []
    for gid, number in picks:
        brow = state.bio_row[gid]
        n = number if number and 1 <= number <= 99 and number not in numbers else bios.get(brow, 'jersey')
        if not 1 <= n <= 99 or n in numbers:
            n = next(k for k in range(2, 99) if k not in numbers)
        numbers.add(n)
        pi = own.get(gid)
        if pi is None:
            pi = maker._take('next_index', maker.used_index)
            players.append({'table': 0, 'index': pi, 'playerid': gid})
            state.pis_of.setdefault(gid, []).append(pi)
        style = _ai_value(db, bios.row(brow), 'playerstyle', 0)
        adds.append((slot, {'team': slot, 'playerindex': pi, 'jersey': n, 'playerstyle': style}))
    keep = {values['playerindex'] for _t, values in adds}
    drop = set()
    for pi in old:
        pis = state.pis_of.get(gid_of.get(pi), [])
        if pi not in keep and len(pis) > 1:
            drop.add(pi)
            pis.remove(pi)
    _rebuild_roster(roster, set(old), adds)
    for i in reversed(range(players.count)):
        if players.get(i, 'index') in drop and players.get(i, 'table') == 0:
            players.delete(i)
    return len(adds)


def _listed_ids(db, nhl27_rows, club_rows, active, squad_rows, shift):
    """The bios any list names (name + birth date): drop_unused leaves them, they may be placed yet."""
    rows = [dict(p) for p in (*(nhl27_rows or ()), *(club_rows or ()), *(squad_rows or ())) if p.get('birth')]
    rows += [p for p in active or () if isinstance(p, dict) and p.get('birth') and isinstance(p['birth'], (list, tuple))
             and 'last' in p and 'pos' in p]
    bios = db[BIOS]
    return {bios.get(brow, 'game_id') for _r, brow, _l in R.match(db, rows, shift=shift)}


def _club_listed(db, nhl27_rows, club_rows, shift):
    """The game ids of the bios a club's list names (NHL 27's or the data pack's rows with a league and a team, not
    their free agents): _sign_free_agents leaves them for their league's rebuild."""
    on_team = lambda rows: [p for p in rows or () if p.get('league') and p.get('team')]  # noqa: E731
    return _listed_ids(db, on_team(nhl27_rows), on_team(club_rows), None, (), shift)


def drop_unused(db, keeping=()):
    """Take out the players nothing uses, for room: the player tables are full long before a whole game of new players
    is in (exhibitionskaterai holds 11,078). A bio goes when he is no custom or special player, on no roster and no
    free agent list, no list names him (`keeping`), and no other table holds his id (career stats, awards, visors,
    resort extras: those stay). Returns the bios dropped."""
    state, bios, players = State(db), db[BIOS], db[PLAYERS]
    own = {BIOS, PLAYERS, *AI.values(), *EQUIPMENT.values()}
    held = set()
    for t in db.tables:
        if t.name not in own:
            for f in t.fields:
                if f.name in ('game_id', 'playerid', 'playerartid', 'heroplayerid', 'villainplayerid'):
                    held.update(t.get(i, f.name) for i in range(t.count))
    held.update(players.get(i, 'playerid') for i in range(players.count) if players.get(i, 'table') != 0)
    gone = set()
    for i in range(bios.count):
        gid = bios.get(i, 'game_id')
        if (gid >= SPECIAL_IDS or gid in held or gid in keeping or bios.get(i, 'team') != -1
                or any(p in state.entry or p in state.free for p in state.pis_of.get(gid, ()))):
            continue
        gone.add(gid)
    for t in (bios, players, *(db[n] for n in (*AI.values(), *EQUIPMENT.values()))):
        name = 'playerid' if t is players else 'game_id'
        for i in reversed(range(t.count)):
            if t.get(i, name) in gone and (t is not players or t.get(i, 'table') == 0):
                t.delete(i)
    return len(gone)


def rebuild_national(db, squads, shift, log=lambda m: None, unrated=None, season=DEFAULT_SEASON):
    """The national teams from the data pack's IIHF squads ({code: [player]}: NATIONAL_TEAMS). A player the roster has
    (name + birth date) plays through a record of the team's own, anyone else is created, on the national team alone,
    without a contract: `unrated` {game_id: (code, name, birth year)} gets those. Belarus last played in 2021: whoever is
    past NATIONAL_AGE now is off its list. Returns ({counts}, {teams changed})."""
    slots = _national_slots(db)
    wanted = {c: [p for p in s if c != 'BLR' or p['birth'][0] >= season - NATIONAL_AGE + 1] for c, s in squads.items()
              if s and _team_key(NATIONAL_TEAMS.get(c)) in slots}
    log(f"national teams without a squad: {', '.join(sorted(set(NATIONAL_TEAMS) - set(wanted))) or 'none'}")
    rows = [p for squad in wanted.values() for p in squad]
    brow_of = {id(row): brow for row, brow, level in R.match(db, rows, shift=shift) if level in ('exact', 'date')}
    state, maker, bios = State(db), _Maker(db), db[BIOS]
    gid_at = {brow: gid for gid, brow in state.bio_row.items()}
    created, changed, found, forwards = {}, set(), 0, 0
    for code, squad in sorted(wanted.items()):
        slot, picks, made = slots[_team_key(NATIONAL_TEAMS[code])], [], {}
        for p in squad:
            gid = gid_at.get(brow_of.get(id(p)))
            who = (p['first'], p['last'], tuple(p['birth']))
            gid = created.get(who) if gid is None else gid
            if gid is None:
                y, m, d = p['birth']
                real = {'first': p['first'], 'last': p['last'], 'birth': f'{y:04d}-{m:02d}-{d:02d}',
                        'position': 'CLR'[forwards % 3] if p['pos'] == 'F' else p['pos'], 'shoots': p.get('shoots'),
                        'height': p.get('height_cm'), 'weight': p.get('weight_kg'), 'country': code}
                forwards += p['pos'] == 'F'
                pi, gid, _style, _donor = maker.make(real, slot, -1, p.get('num') or 2, None, shift)
                if unrated is not None:
                    unrated[gid] = (code, f"{p['first']} {p['last']}", y)
                brow = bios.count - 1
                for f, v in dict(N.NO_CONTRACT, contractstatus=-1).items():
                    bios.set(brow, f, v)
                state.bio_row[gid] = brow
                state.pis_of.setdefault(gid, []).append(pi)
                created[who], made[gid] = gid, pi
            else:
                found += 1
            if gid not in {g for g, _n in picks}:
                picks.append((gid, p.get('num')))
        _set_squad(db, maker, state, slot, picks, made)
        changed.add(slot)
    db[PLAYERS].sort_by('index')
    sort_players(db)
    return {'national_teams': len(changed), 'national_found': found, 'national_created': len(created)}, changed


def fill_national(db, born_in, quality=None, season=DEFAULT_SEASON, shift=0):
    """Legacy's national teams: after the squad, the country's NHL players (the roster and NHL.com agree on it: `born_in`
    {game_id: birth country}), best first, up to NATIONAL_ROOM: one takes a place while every position can still reach
    NATIONAL_LEAST, and the place of his position's weakest once the team is full. A position still short takes the
    country's players elsewhere, the best NHL players left take what remains. Russia has no squad and is made the same
    way. A team that could not dress stays as it is. By `quality` {game_id: overall}, else the roster's. Lines are dealt
    again, by the update's ratings. Returns the teams changed."""
    slots, bios, state, maker = _national_slots(db), db[BIOS], State(db), _Maker(db)
    leagues = {r['index']: r['league'] for r in db[T.TEAMS].rows() if r['index'] not in SHADOW_TEAMS}
    on, nhl, elsewhere = {slot: [] for slot in slots.values()}, {}, {}
    for table in (ROSTER, CUSTOM_ROSTER):
        for i in range(db[table].count if table in db else 0):
            r = db[table].row(i)
            b = state.bio(r['playerindex'])
            if b is None or b['game_id'] >= SPECIAL_IDS:
                continue
            if (r['team'] == T.SEATTLE if table == CUSTOM_ROSTER else r['team'] in NHL):
                nhl[b['game_id']] = b
            elif table == CUSTOM_ROSTER:  # Coachella Valley, an AHL club
                elsewhere[b['game_id']] = b
            elif r['team'] in on:
                on[r['team']].append((b['game_id'], r['jersey']))
            elif leagues.get(r['team']) in CLUB_LEAGUES:
                elsewhere[b['game_id']] = b
    for pi in state.free:
        b = state.bio(pi)
        if b is not None and b['game_id'] < SPECIAL_IDS:
            elsewhere[b['game_id']] = b
    for gid in nhl:
        elsewhere.pop(gid, None)
    group = lambda gid: _group(bios.get(state.bio_row[gid], 'position'))    # noqa: E731
    rating = lambda gid: (quality or {}).get(gid) or _ai_value(db, bios.row(state.bio_row[gid]), 'skill_overall', 0)    # noqa: E731
    rank = lambda gid: (-rating(gid), gid)      # noqa: E731
    done = {}
    for key, slot in slots.items():
        code = _national_code(key)
        if code not in COUNTRY:
            continue
        members = [] if code == 'RUS' else list(on[slot])   # no squad: its stock one is years old

        def room_for(g):
            count = collections.Counter(group(gid) for gid, _n in members)
            short = sum(max(0, need - count[h]) for h, need in NATIONAL_LEAST.items() if h != g)
            return len(members) < NATIONAL_ROOM and (count[g] < NATIONAL_LEAST[g] or NATIONAL_ROOM - len(members) > short)
        have = {gid for gid, _n in members}
        called = sorted((gid for gid, b in nhl.items() if gid not in have and b['intlcountry'] == COUNTRY[code]
                         and born_in.get(gid) == code), key=rank)
        for gid in called:
            same = [m for m in members if group(m[0]) == group(gid)]
            if room_for(group(gid)):
                members.append((gid, None))
            elif len(members) >= NATIONAL_ROOM and same:
                weakest = min(same, key=lambda m: rating(m[0]))
                if rating(gid) > rating(weakest[0]):
                    members.remove(weakest)
                    members.append((gid, None))
        have = {gid for gid, _n in members}
        for gid in sorted((gid for gid, b in elsewhere.items() if gid not in have and b['intlcountry'] == COUNTRY[code]
                           and season - (b['year'] + YEAR_BASE + shift) <= NATIONAL_AGE), key=rank):
            if len(members) < NATIONAL_ROOM and sum(group(m[0]) == group(gid) for m in members) < NATIONAL_LEAST[group(gid)]:
                members.append((gid, None))
        have = {gid for gid, _n in members}
        for gid in called:
            if len(members) < NATIONAL_ROOM and gid not in have:
                members.append((gid, None))
        count = collections.Counter(group(gid) for gid, _n in members)
        if count['G'] < DRESS_GOALIES or count['D'] < 6 or count['D'] + count['F'] < 18:
            continue
        done[slot] = {gid for gid, _n in members} != {gid for gid, _n in on[slot]}
        if done[slot]:
            _set_squad(db, maker, state, slot, members)
    db[PLAYERS].sort_by('index')
    for slot in done:
        lines.build(db, slot)
    return sum(done.values())


def give_captains(db, quality=None):
    """A national team without letters: the C goes to the dressed skater who captains his own club, else one who wears an
    A there, else the best (`quality` {game_id: overall}, else the roster's), the two A's follow in the same order. The
    squads come with no letters, and _rebuild_roster's new rows have none. Returns the teams given them."""
    roster, state = db[ROSTER], State(db)
    slots = set(_national_slots(db).values())
    by_team, worn = {}, {}
    for i in range(roster.count):
        r = roster.row(i)
        if r['team'] in slots:
            by_team.setdefault(r['team'], []).append(i)
        elif r['captain']:
            b = state.bio(r['playerindex'])
            if b:
                worn[b['game_id']] = min(worn.get(b['game_id'], 9), 1 if r['captain'] == CAPTAIN else 2)
    n = 0
    for rows in by_team.values():
        if any(roster.get(i, 'captain') for i in rows):
            continue
        ranked = []
        for i in rows:
            b = state.bio(roster.get(i, 'playerindex'))
            if b and b['position'] != GOALIE and roster.get(i, 'rosterstatus'):
                gid = b['game_id']
                level = (quality or {}).get(gid) or _ai_value(db, b, 'skill_overall', 0)
                ranked.append((worn.get(gid, 9), -level, gid, i))
        for (_w, _o, _g, i), letter in zip(sorted(ranked), (CAPTAIN, ALTERNATE, ALTERNATE)):
            roster.set(i, 'captain', letter)
        n += bool(ranked)
    return n


def _record_ids(db):
    """{exhibitionplayers index: bio game_id} of the regular records (table 0)."""
    p = db[PLAYERS]
    return {p.get(i, 'index'): p.get(i, 'playerid') for i in range(p.count) if p.get(i, 'table') == 0}


def _slot_values(row):
    """A roster row without its place (key, team, player record): number, lines, captaincy, style, dressed."""
    return {k: v for k, v in row.items() if k not in ('key', 'team', 'playerindex')}


def _mirror_problems(db):
    """Team 399 holds team 499's players with the same rows, through records of its own, when team 499 has any."""
    custom = db[CUSTOM_ROSTER]
    src = [custom.row(i) for i in range(custom.count) if custom.get(i, 'team') == T.SEATTLE]
    if not src:
        return []
    gid = _record_ids(db)
    mirror = _mirror_rows(db)
    if [(gid.get(r['playerindex']), _slot_values(r)) for r in mirror] != [(gid.get(r['playerindex']), _slot_values(r))
                                                                         for r in src]:
        return [f"Play Now Seattle (team {MIRROR}): {len(mirror)} rows do not mirror team {T.SEATTLE}'s {len(src)}"]
    if {r['playerindex'] for r in mirror} & {r['playerindex'] for r in src}:
        return [f"Play Now Seattle (team {MIRROR}) shares exhibitionplayers records with team {T.SEATTLE}"]
    return []


JUNIOR_LEAGUES = frozenset({11, 12, 13})  # OHL, QMJHL, WHL
JUNIOR_AGE = 20  # the free agents a junior club may sign to dress its 20 are this young (Legacy clubs.JUNIOR_AGE)


def _farm_of(db, team):
    """The AHL club NHL club `team` keeps its farm players at (exhibitionteams.ahlaffiliate), or None."""
    if T.TEAMS not in db:
        return None
    rows = {r['index']: r for r in db[T.TEAMS].rows()}
    farm = (rows.get(team) or {}).get('ahlaffiliate')
    return farm if farm in rows and farm != team and rows[farm]['league'] == AHL_LEAGUE else None


def _sign_free_agents(db, table, team, last=(), listed=(), former=(), called=None):
    """A team that lost players to the NHL signs the free agents it needs to dress 2 goalies, 6 defencemen and 12
    forwards; the playerindexes in `last` (retiring) only when no other free agent fits; never one whom a club list
    names (`listed`: game ids, _club_listed), whose league's rebuild would take him away again (Legacy
    clubs._fill_lineup: a junior club signed Korenar, Ryfors and Toivola after the AHL's rebuild, lost them to the
    European leagues' and signed again, six times at Peterborough). An NHL club (and Seattle) takes the best. Any other
    club takes the ones nearest its own level (the median overall of who it has) and one better than its best only when
    no other is left. A junior club takes players of JUNIOR_AGE or younger; an older one only while it cannot dress 2
    goalies and 18 skaters (lines.deal plays a spare of the other position), the youngest first. Before, an ECHL club
    short of forwards signed Adam Henrique, Brandon Saad and Evander Kane, the best free agents, and the OHL's clubs
    ex-NHL players of 30 (Legacy: an AHL club signed Jonathan Toews).
    An NHL club first takes back a player it let go in this update (`former`: his playerindexes, a free agent now; a
    second run lets the one it brought in go again and takes him back, so it changes nothing), then calls up the best of
    its farm club (_farm_of) while the farm club keeps 2 goalies and 18 skaters, never one under another club's deal;
    then a free agent (Legacy builder.call_ups: the owner's Ottawa could not dress after NHL.com made a defenceman a
    winger). The call-ups go into `called` [(playerindex, name, [table, farm], [table, team])]. Returns the signed
    [(playerindex, name, team)]."""
    have = lines.players_of(db, table=table, team=team)
    need = {'G': 2 - sum(p.pos == GOALIE for p in have), 'D': 6 - sum(p.pos == 3 for p in have),
            'F': 12 - sum(p.pos in (0, 1, 2) for p in have)}
    if not have or max(need.values()) <= 0:
        return []
    state = State(db)
    league = next((r['league'] for r in db[T.TEAMS].rows() if r['index'] == team), None) if T.TEAMS in db else None
    nhl_like = team in NHL and table == ROSTER or team == T.SEATTLE
    own = sorted(_overall(db, state, p.index) for p in have)
    top, level = own[-1], own[len(own) // 2]
    dress = {'G': sum(p.pos == GOALIE for p in have), 'S': sum(p.pos != GOALIE for p in have)}
    kind_of = lambda b: 'G' if b['position'] == GOALIE else 'D' if b['position'] == 3 else 'F'  # noqa: E731
    pool = []
    for pi in state.free:
        b = state.bio(pi)
        if b is None or b['position'] > GOALIE or any(o in state.entry for o in state.pis_of.get(b['game_id'], [])) \
                or b['game_id'] in listed:
            continue  # also on a team under another of his records, or a club's list has him
        q = _overall(db, state, pi)
        age = DEFAULT_SEASON - YEAR_BASE - b['year']
        old = league in JUNIOR_LEAGUES and age > JUNIOR_AGE
        fit = (0 if pi in former else 2, -q) if nhl_like else (old, age if old else 0, q > top, abs(q - level), -q)
        pool.append((pi in last, fit, pi, kind_of(b), b, old, None))
    farm = _farm_of(db, team) if table == ROSTER and team in NHL else None
    farm_dress = {}
    if farm is not None:
        on_farm = lines.players_of(db, table=ROSTER, team=farm)
        farm_dress = {'G': sum(p.pos == GOALIE for p in on_farm), 'S': sum(p.pos != GOALIE for p in on_farm)}
        for p in on_farm:
            b = state.bio(p.index)
            if b is not None and b['position'] <= GOALIE and p.index not in last and b['proteam'] in (team, -1):
                pool.append((False, (1, -_overall(db, state, p.index)), p.index, kind_of(b), b, False, farm))
    pool.sort(key=lambda x: x[:3])
    used = {p.index for p in have}
    numbers = {db[table].get(i, 'jersey') for i in range(db[table].count) if db[table].get(i, 'team') == team}
    adds, out, ups = [], [], set()
    bios = db[BIOS]
    for _last, _fit, pi, kind, b, old, frm in pool:
        group = 'G' if kind == 'G' else 'S'
        if need[kind] <= 0 or pi in used or old and dress[group] >= (2 if group == 'G' else 18):
            continue
        if frm is not None and farm_dress[group] <= (2 if group == 'G' else 18):
            continue  # the farm club keeps a line-up it can dress
        need[kind] -= 1
        dress[group] += 1
        n = b['jersey'] if 1 <= b['jersey'] <= 99 and b['jersey'] not in numbers else             next(k for k in range(2, 99) if k not in numbers)
        numbers.add(n)
        adds.append((team, {'team': team, 'playerindex': pi, 'jersey': n,
                            'playerstyle': _ai_value(db, b, 'playerstyle', 0)}))
        brow = state.bio_row[b['game_id']]
        # as the stock roster: an NHL club's player has a deal and his proteam (_contracts may put NHL 27's deal in);
        # a minor league club's player without an NHL deal has contractstatus -1. Status 0 with no deal and no
        # proteam is no stock pattern (run ws5 run1: SimThread crash on the Creation Zone save with 25 of them)
        if frm is not None and b['contractstatus'] == 0 and b['contractdollars'] > 0:  # called up on his own deal
            values = {'team': team, 'proteam': team, 'jersey': n}
        elif table == ROSTER and team in NHL:
            values = dict(N.estimate(99), team=team, proteam=team, jersey=n, contractstatus=0)
        else:
            values = {'team': team, 'jersey': n, 'contractstatus': -1}
        for f, v in values.items():
            if b[f] != v:
                bios.set(brow, f, v)
        name = f"{b['firstname']} {b['lastname']}"
        if frm is None:
            out.append((pi, name, [table, team]))
            continue
        farm_dress[group] -= 1
        ups.add(pi)
        if called is not None:
            called.append((pi, name, [table, frm], [table, team]))
    if adds:
        _rebuild_roster(db[table], ups, adds)
        _rebuild_free(db, remove=[pi for pi, _n, _t in out], add=[])
    return out


SIGN_ROWS_WARN = 30  # the default roster's longest NHL club has 29 rows: past this the game's compliance step has more to do


def sign_player(db, game_id, team, dollars, years, two_way=False):
    """The free agent `game_id` signs with NHL club `team` (0-30): one deal of `dollars` x `years` (the stored length,
    the +1 expansion season already in it), one-way or two-way. His club row goes in the ROSTER table (a spare until
    Edit Lines puts him in a line), his bio gets the deal, `proteam` and `team` = the club, `contractstatus` 0 (the
    pattern of every stock NHL club player, see _sign_free_agents), and he leaves the free agent list. Returns
    (name, playerindex, rows on the club now); raises UpdateError (nothing changed) when he cannot sign."""
    if team not in NHL:
        raise UpdateError('Players sign with the 31 NHL clubs listed; Seattle and the minor league clubs come later.')
    state = State(db)
    pis = state.pis_of.get(game_id, [])
    row = state.bio_row.get(game_id)
    if row is None or not pis:
        raise UpdateError('That player is not in this roster.')
    pi = next((p for p in pis if p in state.free), None)
    if pi is None or any(p in state.entry for p in pis):
        raise UpdateError('He is not a free agent: only players on the free agent list can sign.')
    bios, roster = db[BIOS], db[ROSTER]
    b = state.bio(pi)
    rows_now = [i for i in range(roster.count) if roster.get(i, 'team') == team]
    if len(rows_now) >= KEYS_PER_TEAM:
        raise UpdateError(f'That club has {len(rows_now)} players on its roster rows: no room for another.')
    units = N.units(dollars)
    if not 1 <= years <= 15 or units > 16383:
        raise UpdateError('A contract runs 1 to 15 seasons and fits in $81.9M.')
    numbers = {roster.get(i, 'jersey') for i in rows_now}
    n = b['jersey'] if 1 <= b['jersey'] <= 99 and b['jersey'] not in numbers else         next((k for k in range(2, 99) if k not in numbers), None)
    if n is None:
        raise UpdateError('That club has every jersey number taken.')
    deal = N.terms({'cap': units * N.UNIT, 'years': years, 'two_way': bool(two_way)})
    deal['contractlength'] = years
    values = dict(deal, team=team, proteam=team, jersey=n, contractstatus=0)
    for f, v in values.items():
        if bios.get(row, f) != v:
            bios.set(row, f, v)
    _rebuild_roster(roster, set(), [(team, {'team': team, 'playerindex': pi, 'jersey': n,
                                            'playerstyle': _ai_value(db, b, 'playerstyle', 0)})])
    _rebuild_free(db, remove=[pi], add=[])
    return f"{b['firstname']} {b['lastname']}", pi, len(rows_now) + 1


def _ai_value(db, b, name, default):
    t = db[AI[b['position'] == GOALIE]]
    i = bisect.bisect_left(_Column(t, 'game_id'), b['game_id'])
    return t.get(i, name) if i < t.count and t.get(i, 'game_id') == b['game_id'] else default


def _numbers(db, state, todo):
    """{(team, playerindex or id(real)): number}: NHL.com's number where the team has it free, else the player's
    own, else the first free one."""
    out = {}
    by_team = {}
    for p, pi, to, _l in todo.placed:
        by_team.setdefault(to, []).append((p, pi))
    for pi, _n, team in todo.kept:
        by_team.setdefault(team, []).append((None, pi))
    for team, members in by_team.items():
        used = set()
        wants = []
        for p, pi in members:
            real = p.get('number') if p else None
            b = state.bio(pi) if pi is not None else None
            own = b['jersey'] if b else None
            wants.append((p, pi, real if isinstance(real, int) and 1 <= real <= 99 else None, own))
        for p, pi, real, _own in wants:  # NHL.com's numbers first
            if real is not None and real not in used:
                used.add(real)
                out[(team, pi if pi is not None else id(p))] = real
        for p, pi, _real, own in wants:
            key = (team, pi if pi is not None else id(p))
            if key in out:
                continue
            n = own if own and 1 <= own <= 99 and own not in used else next(k for k in range(2, 99) if k not in used)
            used.add(n)
            out[key] = n
    return out


def check(db, schema, cal=None, start_year=None):
    """Problems of an updated roster: the verify rules, unit groups of the NHL teams and Seattle, the teams, the
    calendar."""
    from .roster import Roster
    problems = [str(i) for i in Roster.from_database(db).verify() if i.level == 'error']
    for team in NHL:
        problems += [f"team {team}: {p}" for p in lines.check_groups(db, team)]
    if CUSTOM_ROSTER in db:
        t = db[CUSTOM_ROSTER]
        if any(t.get(i, 'team') == T.SEATTLE for i in range(t.count)):
            problems += [f"Seattle: {p}" for p in lines.check_groups(db, T.SEATTLE, CUSTOM_ROSTER)]
            problems += _custom_lines(db)
            problems += _mirror_problems(db)
        if _seattle_has_players(db, T.SEATTLE_AHL):
            problems += [f"Coachella Valley: {p}" for p in lines.check_groups(db, T.SEATTLE_AHL, CUSTOM_ROSTER)]
        problems += T.check(db, schema)
        for team, name in ((T.SEATTLE, 'Seattle'), (T.SEATTLE_AHL, 'Coachella Valley')):
            row = _seattle_row(db, team) if T.CUSTOM in db else None
            if row is not None and db[T.CUSTOM].get(row, 'active') != int(_seattle_has_players(db, team)):
                problems.append(f'{name} (customteams {team}): active should be 1 exactly when it has players')
    if careerstats.SEASON in db:
        problems += careerstats.check(db)
    problems += key_problems(db)
    if cal:
        problems += calendar.check(db, schema, cal, start_year)
    return problems


def key_problems(db):
    """Roster rows whose key is not KEYS_PER_TEAM * team + their place in the team (the stock layout)."""
    out = []
    for table in (ROSTER, CUSTOM_ROSTER):
        if table not in db:
            continue
        t, place, bad = db[table], {}, set()
        for i in range(t.count):
            team = t.get(i, 'team')
            n = place[team] = place.get(team, -1) + 1
            if t.get(i, 'key') != KEYS_PER_TEAM * team + n:
                bad.add(team)
        out += [f"{table}: team {team}'s keys are not {KEYS_PER_TEAM} * team + n" for team in sorted(bad)]
    return out


def repair_keys(db):
    """Set every roster key to the stock layout in place (rows keep their order); returns the number of keys changed.
    Raises ValueError when it cannot: a team's rows are not together, or a team has more than KEYS_PER_TEAM rows."""
    changed = 0
    for table in (ROSTER, CUSTOM_ROSTER):
        if table not in db:
            continue
        t, place, seen, last = db[table], {}, set(), None
        for i in range(t.count):
            team = t.get(i, 'team')
            if team != last:
                if team in seen:
                    raise ValueError(f"{table}: team {team}'s players are not together")
                seen.add(team)
                last = team
            n = place[team] = place.get(team, -1) + 1
            if n >= KEYS_PER_TEAM:
                raise ValueError(f'team {team} has more than {KEYS_PER_TEAM} players; the game holds {KEYS_PER_TEAM}')
            key = KEYS_PER_TEAM * team + n
            if t.get(i, 'key') != key:
                t.set(i, 'key', key)
                changed += 1
    return changed


def _custom_lines(db):
    """roster.verify's line rules for Seattle's rows of customrostertable (verify reads exhibitionrostertable only)."""
    from .roster import ES_SLOTS
    t = db[CUSTOM_ROSTER]
    rows = [t.row(i) for i in range(t.count) if t.get(i, 'team') == T.SEATTLE]
    out = []
    for s in ES_SLOTS:
        n = sum(1 for r in rows if r[s])
        if n != 1:
            out.append(f"Seattle: line slot {s} is filled {n} times")
    for s in lines.SLOTS:
        if s not in ES_SLOTS and sum(1 for r in rows if r[s]) > 1:
            out.append(f"Seattle: slot {s} is filled more than once")
    jerseys = [r['jersey'] for r in rows]
    if len(set(jerseys)) != len(jerseys):
        out.append("Seattle: two players wear the same number")
    return out
