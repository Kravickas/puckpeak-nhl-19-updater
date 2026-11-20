"""The game's calendar: a real NHL season written into a roster's schedule tables (idea from PS3 Legacy `schedule.py`).

Every schedule table has the fields round, day, month, index, home, away: one row per game, `month` 0 = January,
`day` 0 = the 1st (stock row 0 of nhlschedule is TOR-MTL on day 2 of month 9: the real 2018-19 opener, 3 Oct 2018),
`index` the row's own number, `home` / `away` team indexes. No year and no time of day. Rows are sorted by date.

    nhl32schedule        the calendar of a Franchise with the 32-team expansion (run X1: the league's regular season is
                         this table's games): places 0-31 (`SLOTS32`). Each place plays its row's games and keeps its
                         stock division, and the league layer's realignment lists Seattle (customteams 499) in Utah's
                         Pacific place 22 and Utah in place 31 (run v0100-s3b), so place 22 gets Seattle's games. Stock
                         1,312 rows (32 x 82), room 1,372: the real season's 1,344 games (32 x 84) fit (Franchise
                         played 84 per team, run X1; Play Now with this table at 84 plays, ws8-20261018/run1q).
    nhlschedule, nhlfutureschedule, favoriteteamschedule
                         the 31-team calendars (Season, Classic Franchise, Be a Pro; stock: three equal copies, 31 x 82):
                         teams 0-30. They get the real season with Seattle's games folded into games between its
                         opponents (`fold`), cut to 82 per team.

The 31-team tables keep the stock 82 games per team, 41 at home; the 32-team nhl32schedule has 84. The
Play Now crash once blamed on 80 games (0xc0000005, ws8-20261018/run1c..1p) came from the roster, not the calendar
(see docs/notes/nhl19-32teams-re.md). `GAMES` is their default.

All the tables are in the `rosters` and `rosterupdate` savegroups: the calendar travels in a custom roster save and
in the online roster.
"""
import datetime

from . import nhlcom

# NHL.com team code -> NHL 19 team index (exhibitionteams 0-30; 31 = the 32nd team of nhl32schedule)
SLOTS = {'ANA': 0, 'WPG': 1, 'BOS': 2, 'BUF': 3, 'CGY': 4, 'CAR': 5, 'CHI': 6, 'COL': 7, 'CBJ': 8, 'DAL': 9,
         'DET': 10, 'EDM': 11, 'FLA': 12, 'LAK': 13, 'MIN': 14, 'MTL': 15, 'NSH': 16, 'NJD': 17, 'NYI': 18, 'NYR': 19,
         'OTT': 20, 'PHI': 21, 'UTA': 22, 'PIT': 23, 'STL': 24, 'SJS': 25, 'TBL': 26, 'TOR': 27, 'VAN': 28, 'WSH': 29,
         'VGK': 30, 'SEA': 31}
CODES = {v: k for k, v in SLOTS.items()}
EXPANSION = 31
# nhl32schedule's places: Seattle and Utah trade places (see above). Be a Pro keeps 499 in place 31, listed in the
# Central, so there place 31 plays Utah's games (nhl19-32teams-re.md, run p3).
PLACE32 = {SLOTS['UTA']: EXPANSION, EXPANSION: SLOTS['UTA']}     # team index -> place, and back
SLOTS32 = {code: PLACE32.get(i, i) for code, i in SLOTS.items()}
CODES32 = {v: k for k, v in SLOTS32.items()}
GAMES = 82  # games per team of the 31-team tables (stock)
TABLE32 = 'nhl32schedule'
TABLES31 = ('nhlschedule', 'nhlfutureschedule', 'favoriteteamschedule')
FIELDS = ('round', 'day', 'month', 'index', 'home', 'away')
DAYS_IN = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


class CalendarError(ValueError):
    """The games cannot be made into the tables (the message says why)."""


def season_code(start_year):
    return f'{start_year}{start_year + 1}'


def season_games(client, start_year, codes=None, log=lambda msg: None):
    """[(date, home code, away code)] of every regular-season game of the season starting in `start_year`, one
    request per club (`client`: nhlcom.Client), each game once, sorted by date then NHL.com game id."""
    games = {}
    codes = sorted(codes or SLOTS)
    asked = nhlcom.each(lambda code: client.club_schedule(code, season_code(start_year)), codes)   # a few at once
    for body in asked:      # in club order, as one after another
        for g in nhlcom.schedule_games(body):
            games[g['id']] = (g['date'], g['home'], g['away'])
    out = [games[k] for k in sorted(games, key=lambda k: (games[k][0], k))]
    log(f'NHL.com {season_code(start_year)}: {len(out)} regular-season games')
    return out


def slot_games(games):
    """[(date, home, away)] with team indexes; a game of a team the game has no index for raises."""
    unknown = sorted({t for _d, h, a in games for t in (h, a) if t not in SLOTS})
    if unknown:
        raise CalendarError(f"no NHL 19 team for {', '.join(unknown)}")
    return [(d, SLOTS[h], SLOTS[a]) for d, h, a in games]


def per_team(games):
    count = {}
    for _d, h, a in games:
        count[h] = count.get(h, 0) + 1
        count[a] = count.get(a, 0) + 1
    return count


def trim(games, per):
    """`games` [(date, home, away)] with some left out so that every team plays exactly `per` (even), `per` / 2 at
    home and `per` / 2 away (a flow over home -> away pairs; deterministic). The games cut are the ones nearest the
    middle of the season (pairs and games), so the first and last weeks stay as they are."""
    if per % 2:
        raise CalendarError(f"{per} games: the calendar needs an even number of games per team")
    home, away = {}, {}
    for _d, h, a in games:
        home[h] = home.get(h, 0) + 1
        away[a] = away.get(a, 0) + 1
    teams = set(home) | set(away)
    home_cut = {t: home.get(t, 0) - per // 2 for t in teams}
    away_cut = {t: away.get(t, 0) - per // 2 for t in teams}
    if any(v < 0 for v in home_cut.values()) or any(v < 0 for v in away_cut.values()):
        raise CalendarError(f"a team has fewer than {per // 2} home or away games")
    dates = [datetime.date.fromisoformat(d) for d, _h, _a in games]
    middle = min(dates) + (max(dates) - min(dates)) / 2
    pairs = {}
    for i, (_d, h, a) in enumerate(games):
        pairs.setdefault((h, a), []).append(i)
    for idx in pairs.values():  # nearest the middle of the season first
        idx.sort(key=lambda i: (abs((dates[i] - middle).days), i))
    near = {pair: abs((dates[idx[0]] - middle).days) for pair, idx in pairs.items()}
    cap = {}

    def edge(u, v, c):
        cap.setdefault(u, {})[v] = cap.get(u, {}).get(v, 0) + c
        cap.setdefault(v, {}).setdefault(u, 0)
    for t in sorted(home_cut):
        edge('s', ('h', t), home_cut[t])
        edge(('a', t), 't', away_cut[t])
    for (h, a), idx in sorted(pairs.items()):
        edge(('h', h), ('a', a), len(idx))
    wanted = sum(home_cut.values())

    def push(u, seen):
        if u == 't':
            return True
        seen.add(u)
        for v in sorted(cap[u], key=lambda v: (near.get((u[1], v[1]), 0) if u[0] == 'h' and v != 's' else 0, repr(v))):
            if cap[u][v] > 0 and v not in seen and push(v, seen):
                cap[u][v] -= 1
                cap[v][u] += 1
                return True
        return False
    done = 0
    while done < wanted and push('s', set()):
        done += 1
    if done < wanted or sum(away_cut.values()) != wanted:
        raise CalendarError(f"{per} games for every team cannot be made without changing who plays whom")
    flow = {(h, a): len(idx) - cap[('h', h)][('a', a)] for (h, a), idx in pairs.items()}
    cut = set()
    for pair, idx in pairs.items():
        cut.update(idx[:flow[pair]])
    return [g for i, g in enumerate(games) if i not in cut]


def fold(games, team=EXPANSION):
    """`games` [(date, home, away)] without `team`: each of its home games (vs x) is paired with one of its away
    games (at y, y != x) and becomes y hosting x, on a game day neither plays and that gives neither three games on
    three days in a row (the NHL's schedule never does): the pair with the nearest days, on one of those days or within
    a week of one. Every other team keeps its number of home and away games. Deterministic."""
    rest = [g for g in games if team not in (g[1], g[2])]
    homes = [g for g in games if g[1] == team]
    aways = [g for g in games if g[2] == team]
    if len(homes) != len(aways):
        raise CalendarError(f"team {team} has {len(homes)} home and {len(aways)} away games: they cannot be paired")
    busy = {}
    for d, h, a in rest:
        busy.setdefault(d, set()).update((h, a))
    day = datetime.date.fromisoformat
    days = sorted(busy)
    one = datetime.timedelta(1)

    def plays(t, d):
        return t in busy.get(d.isoformat(), ())

    def three_in_a_row(t, d):
        d = day(d)
        return any(all(plays(t, d + k * one) for k in range(s, s + 3) if k) for s in (-2, -1, 0))
    used, out = set(), []
    for d1, _t, x in homes:
        best = None
        for j, (d2, y, _t2) in enumerate(aways):
            if j in used or y == x:
                continue
            for d in days:
                off = min(abs((day(d) - day(d1)).days), abs((day(d) - day(d2)).days))
                if off <= 7 and not busy[d] & {x, y} and not three_in_a_row(x, d) and not three_in_a_row(y, d):
                    key = (abs((day(d2) - day(d1)).days) + off, d, j)
                    if best is None or key < best[0]:
                        best = (key, j, d, y)
        if best is None:
            raise CalendarError(f"team {team}'s games cannot be folded into games between its opponents")
        _key, j, d, y = best
        used.add(j)
        busy.setdefault(d, set()).update((x, y))
        out.append((d, y, x))
    return sorted(rest + out, key=lambda g: g[0])


def rows_for(games, teams=32, per=None):
    """[(date, home, away)] sorted by date for a `teams`-team table (32: all games, in `SLOTS32` places; 31: Seattle's
    folded into games between its opponents), cut to `per` games per team (None: all of them for 32 teams, `GAMES`
    for 31)."""
    played = slot_games(games)
    if teams == 31:
        played = fold(played)
        per = GAMES if per is None else per
    elif teams != 32:
        raise CalendarError(f"no {teams}-team calendar")
    if per is not None and set(per_team(played).values()) != {per}:
        played = trim(played, per)
    if teams == 32:
        played = [(d, PLACE32.get(h, h), PLACE32.get(a, a)) for d, h, a in played]
    return sorted(played, key=lambda g: g[0])  # stable: a day's games keep NHL.com's order


def _table(db, schema, name):
    return db[schema.by_name(name).short]


def fill(table, rows):
    """Replace every row of `table` by `rows` [(date, home, away)]."""
    if len(rows) > table.max_records:
        raise CalendarError(f"{len(rows)} games do not fit in {table.name} ({table.max_records})")
    table.clear()
    for i, (date, home, away) in enumerate(rows):
        d = datetime.date.fromisoformat(date)
        table.append({'round': 0, 'day': d.day - 1, 'month': d.month - 1, 'index': i, 'home': home, 'away': away})


def apply(db, schema, games, per32=None, per31=None):
    """Write the season `games` ([(date, home code, away code)], as `season_games` gives them) into the four schedule
    tables of `db`. `per32` / `per31` games per team (None: all real games / `GAMES`).
    Returns {table name: {'games', 'per_team', 'first', 'last'}}."""
    def fits(name, rows):  # everything checked before anything is written
        if len(rows) > _table(db, schema, name).max_records:
            raise CalendarError(f"{len(rows)} games do not fit in {name} ({_table(db, schema, name).max_records})")
        return rows
    plan = {TABLE32: fits(TABLE32, rows_for(games, 32, per32))}
    rows31 = rows_for(games, 31, per31)
    plan.update({name: fits(name, rows31) for name in TABLES31})
    out = {}
    for name, rows in plan.items():
        fill(_table(db, schema, name), rows)
        counts = per_team(rows)
        out[name] = {'games': len(rows), 'per_team': (min(counts.values()), max(counts.values())),
                     'first': rows[0][0], 'last': rows[-1][0]}
    return out


def read(table):
    """[(month, day, home, away)] of a schedule table, the game's own numbers."""
    return [(table.get(i, 'month'), table.get(i, 'day'), table.get(i, 'home'), table.get(i, 'away'))
            for i in range(table.count)]


def season_date(month, day, start_year):
    """The real date of a row (months from July on are in `start_year`, the rest in the next year)."""
    return datetime.date(start_year if month >= 6 else start_year + 1, month + 1, day + 1)


def check(db, schema, expected, start_year=None):
    """Problems of the calendar in `db` that `apply` wrote (`expected`: its return value): row counts, plain game rows
    numbered in order, valid dates from September to June, dates in order, nobody twice a day or against itself,
    teams in range, the same number of games for everyone, as many home as away games, and the three 31-team tables
    equal."""
    problems = []
    for name, exp in expected.items():
        t = _table(db, schema, name)
        teams = exp.get('teams') or (32 if name == TABLE32 else 31)   # 'teams': the other leagues (leaguecal)
        if t.count != exp['games']:
            problems.append(f"{name}: {t.count} games, expected {exp['games']}")
        last, busy, games, home = None, set(), {}, {}
        for i in range(t.count):
            r = t.row(i)
            if r['round'] or r['index'] != i:
                problems.append(f"{name} row {i}: not a plain game row ({r})")
            m, d = r['month'], r['day']
            if not (m < 12 and d < DAYS_IN[m]) or not (m >= 8 or m <= 5):
                problems.append(f"{name} row {i}: date {m + 1}/{d + 1}")
                continue
            key = (m if m >= 6 else m + 12, d)  # the season runs September -> June
            if last is not None and key < last:
                problems.append(f"{name} row {i}: out of date order")
            last = key
            if start_year is not None:
                try:
                    season_date(m, d, start_year)
                except ValueError:
                    problems.append(f"{name} row {i}: no such day {m + 1}/{d + 1}")
            h, a = r['home'], r['away']
            if h == a or not (0 <= h < teams and 0 <= a < teams):
                problems.append(f"{name} row {i}: teams {h} - {a}")
            for team in (h, a):
                if (key, team) in busy:
                    problems.append(f"{name} row {i}: team {team} plays twice on {m + 1}/{d + 1}")
                busy.add((key, team))
                games[team] = games.get(team, 0) + 1
            home[h] = home.get(h, 0) + 1
        if len(games) != teams or len(set(games.values())) > 1:
            problems.append(f"{name}: games per team {sorted(set(games.values()))} over {len(games)} teams")
        lopsided = [t for t, n in games.items() if 2 * home.get(t, 0) != n]
        if lopsided:
            problems.append(f"{name}: home and away games differ for teams {sorted(lopsided)}")
    views = [read(_table(db, schema, n)) for n in TABLES31 if n in expected]
    if any(v != views[0] for v in views[1:]):
        problems.append("the 31-team schedule tables are not equal")
    return problems
