"""Update to today's NHL (the Update tab): gather -> plan -> apply into the open roster -> report.

Gather: every club's roster and the season's calendar from NHL.com (overtime_core.nhlcom, cached), the owner's
data pack (EA ratings and draft history, plus a dated copy of the rosters and calendar for when NHL.com can't be
reached), and the owner's local NHL 27 pack when there is one (sources.nhl27_pack: ratings, player types and
contracts, which come before EA's list and the estimates). Plan: overtime_core.rosterupdate.plan (who stays, moves, is new, is released). Apply: rosterupdate.apply in one
bulk change of the RosterSession, so one Undo puts the whole roster back. An online roster first gets copies of the
default roster's custom team tables, where Seattle lives. The Update tab's Go then saves it (update_ctl.py); beta1's
Apply leaves that to the Save bar. The Update tab's switches turn parts off (run: nhl27, schedule, retire).
"""
import datetime
import gzip
import os
import re
import urllib.request
from dataclasses import dataclass, field

from overtime_core import art, calendar, clubdata, gamefiles, leaguecal, net, nhlcom, photos, ratings as R, reallines as RL, tdb
from overtime_core import rosterupdate as U, teams as T

from . import sources

LEAGUES_COPY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets', 'leaguecal.json')
STEPS = [('rosters', 'NHL.com rosters'), ('calendar', 'Calendar'), ('pack', 'Ratings and drafts'), ('plan', 'Plan'),
         ('apply', 'Apply'), ('verify', 'Verify')]
GATHER_STEPS = ('rosters', 'calendar', 'pack')
DEFAULT_SEASON = 2026


class UpdateError(RuntimeError):
    pass


@dataclass
class Gathered:
    season: int
    real: list
    games: list
    ratings: list = field(default_factory=list)
    drafts: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)  # step -> where it came from, as shown to the user
    active: list = None  # rosterupdate.still_playing(pack): old free agents it doesn't list retire; None keeps them
    nhl27: dict = None  # the owner's local NHL 27 pack (nhl27.py): ratings, player types, contracts; None: none
    lines: dict = None  # the data pack's real lines and captains for this season (reallines.part); None: none
    leagues: dict = None  # the other leagues' calendars ({'ahl': games, 'shl': games, ...}, leaguecal); None: none
    national: dict = None  # the data pack's IIHF squads ({'CAN': [player, ...]}, rosterupdate.rebuild_national)
    clubs: dict = None  # the data pack's club rosters on NHL 27's rows (clubdata.merged); None: NHL 27's own
    gone: list = None  # rosterupdate.gone_people(pack): who retired after last season (Kopitar), at any age
    unsigned: list = None  # rosterupdate.unsigned_last(pack): last season's NHL players no club signed (free agents)
    photos: list = None  # overtime_core.photos.links(pack): everyone the data pack has a photo link of; None: no pack


def gather_leagues(season, offline=False, fetch=None, log=lambda msg: None):
    """({'ahl': games, 'echl': games, 'liiga': games}, where): live (HockeyTech, liiga.fi; `fetch(url) -> bytes`), else
    the copy the app ships; ({}, '') without either."""
    live = {} if offline or fetch is None else leaguecal.fetch_season(season, fetch=fetch, log=log)
    copy = leaguecal.load_snapshot(LEAGUES_COPY, season)
    out = dict(copy, **live)
    if not out:
        return {}, ''
    where = 'live' if live and len(live) == len(out) else ('app copy' if not live else 'live + app copy')
    return out, where


def leagues_text(leagues, where):
    names = {'ahl': 'AHL', 'echl': 'ECHL', 'liiga': 'Liiga', 'shl': 'SHL', 'del': 'DEL', 'extraliga': 'Extraliga',
             'nl': 'National League', 'ohl': 'OHL', 'qmjhl': 'QMJHL', 'whl': 'WHL'}
    return ', '.join(f'{names[k]} {len(v):,}' for k, v in sorted(leagues.items())) + f' ({where})'


def _nhl27_text(nhl27):
    return f"NHL 27: {len(nhl27['players'])} players, {len(nhl27.get('contracts') or [])} contracts"


def fetch(url, timeout=60):
    """Bytes at `url` (the data pack on Legacy's file server)."""
    req = urllib.request.Request(url, headers={'User-Agent': nhlcom.USER_AGENT})
    with net.urlopen(req, timeout=timeout) as r:
        return r.read()


def _pack_rosters(pack, codes):
    teams = (pack or {}).get('nhl') or {}
    out = []
    for code in sorted(codes):
        body = teams.get(code) or (teams.get('ARI') if code == 'UTA' else None)
        if body:
            out += nhlcom.roster_players(body, team=code)
    return out


def _pack_games(pack, season):
    if not pack or pack.get('season', season) != season:
        return []
    return [tuple(g[:3]) for g in pack.get('schedule') or [] if len(g) >= 3]


def _lookup(client):
    """NHL.com's page of a player (nhlcom.landing_player), None when it can't be read."""
    def read(nhl_id):
        try:
            return nhlcom.landing_player(client.player(nhl_id))
        except (nhlcom.NhlComError, OSError, ValueError):
            return None
    return read


def gather(client, season, pack_dir, fetch=None, offline=False, step=lambda key, state, text='': None,
           log=lambda msg: None, schedule=True):
    """Gathered for the season starting in `season`. NHL.com first; the data pack's copy when NHL.com can't be
    reached (or `offline`). Raises UpdateError when there are no rosters or no calendar at all (`schedule` False,
    the Calendar switch off: the calendar is still read when it can be, for the Calendar tab, but none stops
    nothing)."""
    pack = None
    step('pack', 'run')
    nhl27, where = sources.nhl27_pack(pack_dir)
    if nhl27:
        log(f'{_nhl27_text(nhl27)} ({where})')
    try:
        pack = R.load_pack(pack_dir, fetch=fetch, offline=offline, log=log)
        when = pack.get('generated', '')[:10]
        n = len(R.ea_rows(pack))
        step('pack', 'ok', f'{n} EA ratings, data pack {when}'.strip() + (f'; {_nhl27_text(nhl27)}' if nhl27 else ''))
    except R.PackError as err:
        if nhl27:
            step('pack', 'ok', f'{_nhl27_text(nhl27)} ({err}): no national teams, clubs from NHL 27')
        else:
            step('pack', 'skip', f'{err}: ratings stay as they are')
    out = Gathered(season, [], [], R.ea_rows(pack), (pack or {}).get('drafts') or [],
                   active=U.still_playing(pack, season) if pack else None, nhl27=nhl27, lines=RL.part(pack, season),
                   national=(pack or {}).get('iihf') or None, gone=U.gone_people(pack, season) if pack else None,
                   unsigned=U.unsigned_last(pack, season) if pack else None,
                   photos=photos.links(pack) if pack else None)
    out.sources['pack'] = (pack or {}).get('generated', '')[:10]
    if nhl27:
        out.sources['nhl27'] = where

    step('rosters', 'run')
    if not offline:
        try:
            out.real = U.gather_rosters(client, season, log=log)
            out.sources['rosters'] = 'NHL.com'
        except (nhlcom.NhlComError, OSError, ValueError) as err:
            log(f'NHL.com rosters: {err}')
    if not out.real:
        out.real = _pack_rosters(pack, calendar.SLOTS)
        out.sources['rosters'] = f"data pack {out.sources['pack']}" if out.real else ''
    if not out.real:
        step('rosters', 'fail', 'no connection to NHL.com and no data pack')
        raise UpdateError('No rosters: NHL.com could not be reached and there is no data pack.')
    out.real, _extra, farmed = U.with_absent(out.real, nhl27, pack, out.lines, clubdata.listed(pack),
                                             None if offline else _lookup(client), log, clubdata.farm_clubs(pack))
    out.clubs = clubdata.merged(pack, nhl27, farmed)
    step('rosters', 'ok', f"{len(out.real)} players, {len({p['team'] for p in out.real})} clubs "
                          f"({out.sources['rosters']})")

    step('calendar', 'run')
    if not offline:
        try:
            out.games = calendar.season_games(client, season, log=log)
            out.sources['calendar'] = 'NHL.com'
        except (nhlcom.NhlComError, OSError, ValueError) as err:
            log(f'NHL.com calendar: {err}')
    if not out.games:
        out.games = _pack_games(pack, season)
        out.sources['calendar'] = f"data pack {out.sources['pack']}" if out.games else ''
    if not out.games and not schedule:
        step('calendar', 'skip', 'no calendar (the Calendar switch is off)')
        return out
    if not out.games:
        step('calendar', 'fail', 'no calendar')
        raise UpdateError(f'No {season}-{(season + 1) % 100:02d} calendar: NHL.com could not be reached and the '
                          'data pack has none.')
    out.leagues, where = gather_leagues(season, offline or fetch is None, fetch=fetch, log=log)
    out.leagues = dict(out.leagues, **leaguecal.pack_games(pack, season))
    more = f'; {leagues_text(out.leagues, where)}' if out.leagues else ''
    if out.leagues:
        out.sources['leagues'] = where
    step('calendar', 'ok', f'{len(out.games)} games, {out.games[0][0]} to {out.games[-1][0]} '
                           f"({out.sources['calendar']}){more}")
    return out


def gather_files(season, pack_dir, rosters_path, schedule_path, log=lambda msg: None):
    """Gathered from recorded NHL.com JSON (`[player]` as nhlcom.roster_players gives, `[[date, home, away]]`) and
    the cached data pack's ratings and drafts when there is one (no network)."""
    import json
    with open(rosters_path, encoding='utf-8') as f:
        real = json.load(f)
    with open(schedule_path, encoding='utf-8') as f:
        games = [tuple(g) for g in json.load(f)]
    try:
        pack = R.load_pack(pack_dir, offline=True, log=log)
    except R.PackError:
        pack = {}
    nhl27, where = sources.nhl27_pack(pack_dir)
    found = {'rosters': rosters_path, 'calendar': schedule_path}
    if nhl27:
        found['nhl27'] = where
    leagues = leaguecal.load_snapshot(LEAGUES_COPY, season)
    if leagues:
        found['leagues'] = LEAGUES_COPY
    real_lines = RL.part(pack, season)
    real, _extra, farmed = U.with_absent(real, nhl27, pack, real_lines, clubdata.listed(pack), log=log,
                                         farms=clubdata.farm_clubs(pack))
    return Gathered(season, real, games, R.ea_rows(pack), pack.get('drafts') or [], found,
                    active=U.still_playing(pack, season) if pack else None, nhl27=nhl27, lines=real_lines,
                    leagues=dict(leagues, **leaguecal.pack_games(pack, season)) or None,
                    national=(pack or {}).get('iihf') or None, clubs=clubdata.merged(pack, nhl27, farmed),
                    gone=U.gone_people(pack, season) if pack else None,
                    unsigned=U.unsigned_last(pack, season) if pack else None,
                    photos=photos.links(pack) if pack else None)


def plan(db, gathered, aliases=None):
    return U.plan(db, gathered.real, season=gathered.season, aliases=aliases)


def _where(names, key):
    if key in (None, 'FA'):
        return 'Free agent'
    table, team = key
    return names(team, table)


def details(todo, report, names):
    """(what, old, new) lines for the Save tab's list of edits and the report."""
    out = []
    for _pi, name, frm, to in todo.moves:
        out.append((f'{name}: team', _where(names, frm), _where(names, to)))
    for real, to in todo.new:
        out.append((f"{real['first']} {real['last']}: new player", '-', _where(names, to)))
    for _pi, name, frm in todo.releases:
        out.append((f'{name}: team', _where(names, frm), 'Free agent'))
    for _pi, name, (table, team) in report.signed:
        out.append((f'{name}: signed', 'Free agent', names(team, table)))
    for _pi, name, (table, farm), (_t, team) in getattr(report, 'called_up', None) or []:
        out.append((f'{name}: called up so the team can dress 20', names(farm, table), names(team, table)))
    for _pi, name, age in report.retired:
        out.append((f'{name}: retired ({age})', 'Free agent', '-'))
    if report.teams:
        out.append(('Teams (Utah, Seattle, Coachella Valley)', '-', f'{len(report.teams)} value(s)'))
    for table, e in (report.calendar or {}).items():
        out.append((f'Calendar {table}', '-', f"{e['games']} games, {e['first']} to {e['last']}"))
    n27 = report.nhl27 or {}
    if n27.get('values'):
        out.append(('NHL 27 ratings and player types', '-',
                    f"{n27['rated']} player(s), {n27['values']} value(s), {n27.get('styles', 0)} type(s)"))
    if n27.get('gear_values'):
        out.append(('Real equipment (NHL 27)', '-', f"{n27['gear']} player(s), {n27['gear_values']} value(s)"))
    if n27.get('masks') or n27.get('goalie_colours'):
        out.append(('Goalies who changed teams: team mask, gear in team colours', '-',
                    f"{n27.get('masks', 0)} mask(s), {n27.get('goalie_colours', 0)} goalie(s) in team colours"))
    if n27.get('sticks'):
        out.append(('Skaters who came to an NHL team: stick in team colours', '-', f"{n27['sticks']} stick(s)"))
    if n27.get('unsigned_listed') or n27.get('unsigned_made'):
        out.append(("Last season's NHL players no club signed: free agents", '-',
                    f"{n27.get('unsigned_listed', 0)} put on the list, {n27.get('unsigned_made', 0)} new player(s)"))
    if report.ratings - n27.get('values', 0):
        out.append(('EA ratings', '-', f"{report.ratings - n27.get('values', 0)} value(s)"))
    if 'deals' in n27:
        out.append(('Contracts (NHL 27)', '-', f"{n27['deals']} club, {n27['minors']} minors"))
        out.append(('Contracts estimated', '-', f"{n27['estimated']} player(s)"))
        if n27.get('rights'):
            out.append(('NHL rights kept, no contract yet (unsigned picks)', '-', f"{n27['rights']} player(s)"))
        out.append(('2018 NHL contracts ended', '-', f"{n27['cleared']} player(s)"))
        if n27.get('money'):
            out.append(("Contracts in NHL 19's own money", '-',
                        f"x{n27['money']:.3f}: the 2026-27 salary cap is off in Game patch, so the game plays the "
                        f"2018-19 cap of $79.5M"))
    if 'expansion' in n27:
        out.append(('Contracts one season longer (expansion career)', '-', f"{n27['expansion']} deal(s)"))
    out.append(('Lines rebuilt', '-', f'{len(report.lines)} team(s)'))
    real = report.real or {}
    if real.get('lined') or real.get('lettered'):
        out.append(('Real lines and captains', '-', f"{len(real.get('full', []))} team(s) lined in full, "
                                                     f"{len(real.get('partly', {}))} in part, "
                                                     f"{len(real.get('lettered', []))} lettered"))
    for code, what in sorted((real.get('partly') or {}).items()):
        out.append((f'Real lines {code}', '-', ', '.join(what)))
    for code, why in sorted((real.get('refused') or {}).items()):
        out.append((f'Real lines {code}', '-', f'kept: {why[0]}'))
    return out


def apply_options(db, gathered, nhl27=True, retire=True, lines=True, served=True):
    """rosterupdate.apply's ratings, drafts, NHL 27 pack, retirement list and real lines for the Update tab's
    switches: NHL 27 off leaves every rating, player type, draft and contract as it is; Retirements off retires
    nobody; Real lines off deals the lines by rating. `served`: Game patch serves the 2026-27 salary cap
    (office.league_served); without it the deals are written in NHL 19's own money (rosterupdate.money_scale)."""
    pack = gathered.nhl27 if nhl27 else None
    return {'money': U.money_scale(pack, served),
            'rating_rows': gathered.ratings if nhl27 else None, 'drafts': gathered.drafts if nhl27 else None,
            'nhl27': pack, 'active': gathered.active, 'retire': retire,
            'retired_list': getattr(gathered, 'gone', None), 'unsigned': getattr(gathered, 'unsigned', None),
            'real_lines': getattr(gathered, 'lines', None) if lines else None,
            'national': getattr(gathered, 'national', None), 'clubs': getattr(gathered, 'clubs', None) if nhl27 else None}


def retirees(db, gathered, nhl27=True):
    """How many free agents the update would retire, counted on the roster as it is now (rosterupdate.apply counts
    again after its moves); None when nothing says who still plays."""
    pack = gathered.nhl27 if nhl27 else None
    active, gone = gathered.active, getattr(gathered, 'gone', None)
    if pack and pack.get('players'):
        active = list(active or []) + U.without_gone(pack['players'], gone, free_only=True)
    if active is None:
        return None
    age = U.NHL27_RETIRE_AGE if pack and pack.get('players') else U.FA_RETIRE_AGE
    return len(U.retirees(db, active, gathered.season, age, gone or ()))


def run(session, game, gathered, todo, per32=None, names=None, log=lambda msg: None, nhl27=True, schedule=True,
        retire=True, expansion=False, lines=False, portraits=None, served=True):
    """Apply `todo` to the session's roster in one bulk change (one Undo takes it all back). Returns the Report.
    The Update tab's switches: `nhl27` False keeps ratings, types, drafts and contracts; `schedule` False keeps the
    calendar; `retire` False retires nobody; `lines` True lays the data pack's real lines and captains on the NHL
    teams (the Update tab's switch, patch.updated_default). `expansion`: when the update set the contracts (NHL 27 on, its pack
    there: rosterupdate._contracts writes every NHL deal plain), give every NHL deal the expansion career's extra
    season after it (rosterupdate.expansion_contracts), so the roster reads like the default and the online roster.
    patch.updated_default adds it itself. `portraits` (patch.served_portraits): the photos the patch serves, for the
    bios to show them: a saved roster's flags are not the served default's. `served` False: the game plays NHL 19's
    own salary cap (the league layer off), so the deals are written in its money (apply_options)."""
    schema = game.schema()
    names = names or (lambda team, table: str(team))

    def work(db):
        if U.CUSTOM_ROSTER not in db or T.CUSTOM not in db:
            added = U.graft_custom(db, game.default_db())
            log(f"Online roster: copied {', '.join(added)} from the game's default roster.")
        opts = apply_options(db, gathered, nhl27, retire, lines, served)
        rep = U.apply(db, schema, todo, games=gathered.games if schedule else None, start_year=gathered.season,
                      per32=per32, log=log, leagues=gathered.leagues if schedule else None, **opts)
        if opts['nhl27'] is not None and opts['money'] != 1:
            rep.nhl27['money'] = opts['money']
            log(f"contracts in NHL 19's own money (2018-19 cap): x{opts['money']:.3f}")
        if expansion and opts['nhl27'] is not None:
            rep.nhl27['expansion'] = longer = U.expansion_contracts(db)
            log(f'expansion career contracts: {longer} NHL deals one season longer')
        if portraits and portraits[0]:
            found = art.player_portraits(db, portraits[1], T.year_shift(gathered.season))
            stock = tdb.Database.parse(gamefiles.default_database(game.game_dir)[0], schema)
            art.portrait_flags(db, stock, portraits[0])
            rep.nhl27['portraits'] = found
            log(f'player photos: {found} from the people pack')
        return details(todo, rep, names), rep
    _ch, rep = session.bulk(f"Update to today's NHL ({gathered.season}-{(gathered.season + 1) % 100:02d})", work)
    return rep


def heads_up(db):
    """(short teams, free agents also on a club) for the result; a heads-up never stops an update."""
    try:
        return U.short_teams(db), U.free_and_on_a_club(db)
    except (KeyError, IndexError, TypeError, ValueError):
        return [], []


def team_count(db):
    """How many NHL teams the roster opens with in NHL 19: 32 with Seattle ready (rosterupdate.seattle_ready), else
    31."""
    try:
        return 32 if U.seattle_ready(db) else 31
    except (KeyError, IndexError, TypeError, ValueError):
        return 31


_DATES = {}     # data pack path -> (mtime, date)


def offline_date(pack_dir):
    """The date of the offline copy (the cached data pack: its `generated` date, else the day it was downloaded),
    '' when there is none. Read once per download: the first bytes are enough when the date comes first."""
    path = os.path.join(pack_dir, 'datapack.json.gz')
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ''
    hit = _DATES.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    date = ''
    try:
        with gzip.open(path, 'rt', encoding='utf-8', errors='replace') as f:
            m = re.search(r'"generated"\s*:\s*"(\d{4}-\d{2}-\d{2})', f.read(65536))
        date = m.group(1) if m else ''
    except (OSError, EOFError, ValueError):
        pass
    date = date or datetime.date.fromtimestamp(mtime).isoformat()
    _DATES[path] = (mtime, date)
    return date


def calendar_view(db, schema, team=None, real=None, start_year=DEFAULT_SEASON):
    """What the Calendar tab shows: per-team game counts of the 32-team calendar, a team's games, and whether the
    roster's calendar is the real one (`real`: gathered games, when there are some)."""
    out = {'ready': False}
    name = 'nhl32schedule'
    if name not in db:
        return out
    games = []
    for month, day, home, away in calendar.read(db[name]):
        try:
            games.append((calendar.season_date(month, day, start_year), home, away))
        except ValueError:
            games.append((None, home, away))
    per = {}
    for _d, h, a in games:
        per.setdefault(h, [0, 0])[0] += 1
        per.setdefault(a, [0, 0])[1] += 1
    dates = [d for d, _h, _a in games if d]
    out.update(ready=True, table=name, games=len(games),
               first=min(dates).isoformat() if dates else None, last=max(dates).isoformat() if dates else None,
               teams=[{'id': t, 'code': calendar.CODES32.get(t, str(t)), 'home': h, 'away': a}
                      for t, (h, a) in sorted(per.items())])
    if team is not None:
        out['team'] = team
        out['schedule'] = [{'date': d.isoformat() if d else '?', 'home': h == team,
                            'opponent': calendar.CODES32.get(a if h == team else h, '?')}
                           for d, h, a in games if team in (h, a)]
    if real:
        want = sorted((d, calendar.SLOTS32.get(h, -1), calendar.SLOTS32.get(a, -1)) for d, h, a in real)
        have = sorted((d.isoformat() if d else '', h, a) for d, h, a in games)
        missing = len(set(want) - set(have))
        extra = len(set(have) - set(want))
        out['sync'] = {'real': len(want), 'missing': missing, 'extra': extra, 'same': missing == extra == 0}
    return out
