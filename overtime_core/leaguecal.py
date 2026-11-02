"""The real 2026-27 calendars of the other leagues NHL 19 schedules (docs/notes/calendar.md): the AHL and Liiga by
their own places, and every league in LEAGUE_TABLES by club name: the ECHL from HockeyTech, the others from the data
pack's `schedules` (pack_games).

The tables have the NHL ones' layout (calendar.py: round, day, month 0-based, index, home, away); a team index is the
team's place in its league (exhibitionteams in `index` order).

    ahl32schedule   the AHL of a Franchise with the 32-team expansion: AHL places 0-30 plus 31 (customteams 498, the
                    expansion team's farm club, Seattle's Coachella Valley). Room 1,372: the real 1,152 games fit.
    ahlschedule     the 31-team AHL (Season-era Franchise): Coachella Valley's games folded into games between its
                    opponents (calendar.fold), 72 a team, room 1,331.
    finnishschedule Liiga, league 3, 15 places (the 2018 clubs). The 2026-27 league has 17: Jokerit and K-Espoo have
                    no place and their games are left out (56 a team, 420 games, room 480).

A real AHL club takes the place of its NHL parent's farm team in the game (exhibitionteams.ahlaffiliate of the NHL
club), so a parent's prospects play their real farm club's calendar whatever the game calls that team. Sources:
the AHL's HockeyTech LeagueStat feed and liiga.fi's API, live; an offline copy ships with the app (`load_snapshot`,
written by tools/build_leaguecal.py).
"""
import json
import urllib.request

from . import calendar
from .calendar import CalendarError

AHL32, AHL31, LIIGA = 'ahl32schedule', 'ahlschedule', 'finnishschedule'
# a calendar's key -> (exhibitionteams.league, its table). A club is found by its name in the roster being written
# (rosterupdate._calendar_places): the data pack's slots and league numbers are another game's. No source has
# Allsvenskan's, the ICE Hockey League's, the Champions League's or the Spengler Cup's: those keep the game's own.
LEAGUE_TABLES = {'shl': (2, 'swedishschedule'), 'del': (4, 'germanschedule'), 'extraliga': (5, 'czechschedule'),
                 'nl': (6, 'swissschedule'), 'ohl': (11, 'ohlschedule'), 'qmjhl': (12, 'qmjhlschedule'),
                 'whl': (13, 'whlschedule'), 'echl': (15, 'echlschedule')}
AHL_LEAGUE, LIIGA_LEAGUE = 1, 3
AHL_EXPANSION = 31          # place of customteams 498 in ahl32schedule
# HockeyTech club code -> NHL parent (calendar.SLOTS code), 2026-27 (theahl.com schedule release, 2026)
AHL_PARENT = {'ABB': 'VAN', 'BAK': 'EDM', 'BEL': 'OTT', 'CGY': 'CGY', 'CLT': 'FLA', 'CHI': 'CAR', 'CLE': 'CBJ',
              'CV': 'SEA', 'COL': 'COL', 'GR': 'DET', 'HAM': 'NYI', 'HFD': 'NYR', 'HSK': 'VGK', 'HER': 'WSH',
              'IA': 'MIN', 'LAV': 'MTL', 'LV': 'PHI', 'MB': 'WPG', 'MIL': 'NSH', 'ONT': 'LAK', 'PRO': 'BOS',
              'ROC': 'BUF', 'RFD': 'CHI', 'SD': 'ANA', 'SJ': 'SJS', 'SPR': 'STL', 'SYR': 'TBL', 'TEX': 'DAL',
              'TOR': 'TOR', 'TUC': 'UTA', 'UTC': 'NJD', 'WBS': 'PIT'}
# liiga.fi team name -> the game's Liiga place (league 3 in exhibitionteams order: Ässät 80 ... Sport 94)
LIIGA_SLOTS = {'Ässät': 0, 'HPK': 1, 'HIFK': 2, 'Ilves': 3, 'Jukurit': 4, 'JYP': 5, 'KalPa': 6, 'Kärpät': 7,
               'KooKoo': 8, 'Lukko': 9, 'Pelicans': 10, 'SaiPa': 11, 'Tappara': 12, 'TPS': 13, 'Sport': 14}
LIIGA_NO_PLACE = ('Jokerit', 'K-Espoo')
AHL_SEASONS = {2026: 94}    # HockeyTech season_id of each regular season (view=seasons)
AHL_KEY = '50c2cd9b5e18e390'    # theahl.com's public feed key
AHL_URL = ('https://lscluster.hockeytech.com/feed/index.php?feed=modulekit&view=schedule&key={key}&fmt=json'
           '&client_code=ahl&lang=en&season_id={sid}&team_id=&month=-1&location=home')
LIIGA_URL = 'https://liiga.fi/api/v2/games?tournament=runkosarja&season={season}'
ECHL_SEASONS = {2026: 78}   # as AHL_SEASONS
ECHL_KEY = '2c2b89ea7345cae8'   # echl.com's public feed key
ECHL_URL = ('https://lscluster.hockeytech.com/feed/index.php?feed=modulekit&view=schedule&key={key}&fmt=json'
            '&client_code=echl&lang=en&season_id={sid}&team_id=&month=-1&location=home')
AHL_CREDIT = 'Official statistics provided by American Hockey League'
USER_AGENT = 'OvertimeRoster (+https://ot.puckpeak.com)'


def _http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https bases)
        return r.read()


def ahl_games(body):
    """[(date, home code, away code)] of a HockeyTech schedule feed (modulekit, view=schedule), date order."""
    rows = (body.get('SiteKit') or {}).get('Schedule') or []
    games = [(g['date_played'], g['home_team_code'], g['visiting_team_code'], int(g['game_id'])) for g in rows]
    return [g[:3] for g in sorted(games, key=lambda g: (g[0], g[3]))]


def echl_games(body):
    """[(date, home name, away name)] of a HockeyTech schedule feed, date order."""
    rows = (body.get('SiteKit') or {}).get('Schedule') or []
    games = [(g['date_played'], g['home_team_name'], g['visiting_team_name'], int(g['game_id'])) for g in rows]
    return [g[:3] for g in sorted(games, key=lambda g: (g[0], g[3]))]


def liiga_games(body):
    """[(date, home name, away name)] of liiga.fi's games list (local date of the face-off), date order."""
    games = []
    for g in body or []:
        when = (g['homeTeam'].get('gameStartDateTime') or g['start'])[:10]
        games.append((when, g['homeTeam']['teamName'], g['awayTeam']['teamName'], g['id']))
    return [g[:3] for g in sorted(games, key=lambda g: (g[0], g[3]))]


def fetch_season(start_year, fetch=_http_get, log=lambda msg: None):
    """{'ahl': games, 'echl': games, 'liiga': games} of the season starting in `start_year`, live; a league that
    can't be read is left out (logged)."""
    out = {}
    if start_year in AHL_SEASONS:
        try:
            out['ahl'] = ahl_games(json.loads(fetch(AHL_URL.format(key=AHL_KEY, sid=AHL_SEASONS[start_year]))))
            log(f"AHL {start_year}-{(start_year + 1) % 100:02d}: {len(out['ahl'])} games (HockeyTech)")
        except (OSError, ValueError, KeyError, TypeError) as err:
            log(f'AHL calendar: {err}')
    if start_year in ECHL_SEASONS:
        try:
            out['echl'] = echl_games(json.loads(fetch(ECHL_URL.format(key=ECHL_KEY, sid=ECHL_SEASONS[start_year]))))
            log(f"ECHL {start_year}-{(start_year + 1) % 100:02d}: {len(out['echl'])} games (HockeyTech)")
        except (OSError, ValueError, KeyError, TypeError) as err:
            log(f'ECHL calendar: {err}')
    try:
        out['liiga'] = liiga_games(json.loads(fetch(LIIGA_URL.format(season=start_year + 1))))
        log(f"Liiga {start_year}-{(start_year + 1) % 100:02d}: {len(out['liiga'])} games (liiga.fi)")
    except (OSError, ValueError, KeyError, TypeError) as err:
        log(f'Liiga calendar: {err}')
    return {k: v for k, v in out.items() if v}


def load_snapshot(path, start_year):
    """The offline copy {'ahl': games, 'echl': games, 'liiga': games} for `start_year`; {} without one."""
    try:
        with open(path, encoding='utf-8') as f:
            snap = json.load(f)
    except (OSError, ValueError):
        return {}
    if snap.get('season') != start_year:
        return {}
    return {k: [tuple(g[:3]) for g in snap.get(k) or []] for k in ('ahl', 'echl', 'liiga') if snap.get(k)}


def pack_games(pack, start_year):
    """{key: [(date, home name, away name)]} of the data pack's `schedules` for LEAGUE_TABLES' leagues. The pack gives
    a club as its team slot, or as its name when it has no slot: a slot is turned into its name. {} for another
    season."""
    if not pack or pack.get('season') != start_year:
        return {}
    name = {t['slot']: t['full'] for league in (pack.get('leagues') or {}).values() for t in league.get('teams') or []
            if t.get('slot') is not None}
    out = {}
    for key, games in (pack.get('schedules') or {}).items():
        if key in LEAGUE_TABLES:
            rows = [(g[0], name.get(g[1], g[1]), name.get(g[2], g[2])) for g in games]
            if not any(isinstance(c, int) for _d, h, a in rows for c in (h, a)):
                out[key] = rows
    return out


def snapshot(start_year, leagues, generated):
    """The offline copy's content (load_snapshot reads it)."""
    return dict({'format': 1, 'season': start_year, 'generated': generated, 'credit': AHL_CREDIT},
                **{k: [list(g) for g in v] for k, v in sorted(leagues.items())})


def _league(db, league):
    t = db['exhibitionteams']
    return sorted((t.row(i) for i in range(t.count) if t.get(i, 'league') == league), key=lambda r: r['index'])


def ahl_slots(db):
    """{NHL code: AHL place} from the roster's own farm links (exhibitionteams.ahlaffiliate of NHL clubs 0-30);
    'SEA' -> AHL_EXPANSION."""
    if 'exhibitionteams' not in db:
        raise CalendarError('this roster has no team table (exhibitionteams)')
    places = {r['index']: i for i, r in enumerate(_league(db, AHL_LEAGUE))}
    t = db['exhibitionteams']
    farm = {t.get(i, 'index'): t.get(i, 'ahlaffiliate') for i in range(t.count)}
    out = {}
    for code, slot in calendar.SLOTS.items():
        if slot == calendar.EXPANSION:
            continue
        if farm.get(slot) not in places:
            raise CalendarError(f'{code} has no AHL farm team in this roster')
        out[code] = places[farm[slot]]
    if len(set(out.values())) != len(out) or len(places) != len(out):
        raise CalendarError('the NHL clubs and the AHL teams do not pair up one to one in this roster')
    out['SEA'] = AHL_EXPANSION
    return out


def _even(played, fold_team=None):
    """`played` [(date, home, away)] (place numbers) with `fold_team`'s games folded away, every team on the same
    number of games (the fewest any team has, made even; calendar.trim), date order."""
    if fold_team is not None:
        played = calendar.fold(played, team=fold_team)
    counts = calendar.per_team(played)
    if len(set(counts.values())) > 1:
        per = min(counts.values()) // 2 * 2
        played = calendar.trim(played, per)
    return sorted(played, key=lambda g: g[0])


def ahl_rows(games, slots, teams=32):
    """The AHL `games` (ahl_games) as rows of the `teams`-team table (32: all; 31: Coachella Valley folded)."""
    unknown = sorted({c for _d, h, a in games for c in (h, a) if c not in AHL_PARENT})
    if unknown:
        raise CalendarError(f"no NHL parent known for AHL club(s) {', '.join(unknown)}")
    played = [(d, slots[AHL_PARENT[h]], slots[AHL_PARENT[a]]) for d, h, a in games]
    if teams == 31:
        return _even(played, AHL_EXPANSION)
    if teams != 32:
        raise CalendarError(f'no {teams}-team AHL calendar')
    return _even(played)


def liiga_rows(games):
    """Liiga `games` (liiga_games) as finnishschedule rows: clubs without a place left out."""
    unknown = sorted({c for _d, h, a in games for c in (h, a) if c not in LIIGA_SLOTS and c not in LIIGA_NO_PLACE})
    if unknown:
        raise CalendarError(f"no Liiga place for {', '.join(unknown)}")
    return _even([(d, LIIGA_SLOTS[h], LIIGA_SLOTS[a]) for d, h, a in games if h in LIIGA_SLOTS and a in LIIGA_SLOTS])


def other_rows(games, places):
    """`games` [(date, home, away)] as rows of a league's table: `places` {club name: place}; a club without a place
    is left out with its games."""
    return _even([(d, places[h], places[a]) for d, h, a in games if h in places and a in places])


def apply_other(db, key, games, places):
    """Write the calendar of LEAGUE_TABLES[key]. Every place must play: raises CalendarError otherwise, before
    anything is written. Returns what `apply` returns."""
    league, name = LEAGUE_TABLES[key]
    if name not in db:
        raise CalendarError(f'this roster has no {name}')
    teams = len(_league(db, league))
    rows = other_rows(games, places)
    if len({c for _d, h, a in rows for c in (h, a)}) != teams:
        raise CalendarError(f'{name}: not every one of the {teams} teams has games')
    t = db[name]
    if len(rows) > t.max_records:
        raise CalendarError(f'{len(rows)} games do not fit in {name} ({t.max_records})')
    calendar.fill(t, rows)
    counts = calendar.per_team(rows)
    return {name: {'games': len(rows), 'per_team': (min(counts.values()), max(counts.values())),
                   'first': rows[0][0], 'last': rows[-1][0], 'teams': teams}}


def apply(db, schema, leagues):
    """Write `leagues` ({'ahl': games, 'liiga': games}, either may be missing) into their tables. Everything is made
    and checked for room before anything is written. Returns {table: {'games', 'per_team', 'first', 'last',
    'teams'}} (calendar.check reads it)."""
    plan = {}
    if leagues.get('ahl'):
        slots = ahl_slots(db)
        plan[AHL32] = (ahl_rows(leagues['ahl'], slots, 32), 32)
        plan[AHL31] = (ahl_rows(leagues['ahl'], slots, 31), 31)
    if leagues.get('liiga'):
        if len(_league(db, LIIGA_LEAGUE)) != len(LIIGA_SLOTS):
            raise CalendarError(f'this roster\'s Liiga does not have {len(LIIGA_SLOTS)} teams')
        plan[LIIGA] = (liiga_rows(leagues['liiga']), len(LIIGA_SLOTS))
    for name, (rows, _n) in plan.items():
        if name not in db:
            raise CalendarError(f'this roster has no {name}')
        t = db[name]
        if len(rows) > t.max_records:
            raise CalendarError(f'{len(rows)} games do not fit in {name} ({t.max_records})')
    out = {}
    for name, (rows, n) in plan.items():
        calendar.fill(db[name], rows)
        counts = calendar.per_team(rows)
        out[name] = {'games': len(rows), 'per_team': (min(counts.values()), max(counts.values())),
                     'first': rows[0][0], 'last': rows[-1][0], 'teams': n}
    return out
