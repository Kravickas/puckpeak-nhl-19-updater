"""NHL 27's players, ratings and contracts for NHL 19 rosters (idea and pack layout from PS3 Legacy
`tools/providers/nhl27_players.py` and `nhl27_contracts.py`).

Source: NHL 27's (PS5) roster database, `gamemodes/database/t3db/nhl_game.db` with its `nhl_game-meta.xml`, and the
league kernel's money table (`gamemodes/league/resource_kernel/legacybrkfeatureskernel.brk`), pulled out of the
owner's own dump by re/scripts/nhl27_extract.py (only read, into the gitignored re/dumps/). tools/build_datapack.py
turns them into the local pack `packs/nhl27.json.gz`: numbers, names, birthdates and teams only. Nothing of it ships
with Overtime.

NHL 27's database is EA's t3db with NHL 19's table and field names, read with tdb / schema (values as stored +
rangelow: `team` / `proteam` are team indexes, -1 for none; `playerclassid` is -1 for a real player). Five tables
join on game_id:

    exhibitionplayerbiotable  names, birthdate (years from 1900, months and days from 0), position, hand, height,
                              weight, team, the NHL organisation (`proteam`) and the contract
    exhibitionskaterai        a skater's c_* ratings, playerstyle and the three biases
    exhibitiongoalieai        a goalie's c_* ratings and playerstyle
    exhibitionteams           the team (`index` = bio team): name and league; NHL clubs 0-31 in calendar.SLOTS order
    stockcareerseasongoaliestats  a goalie's seasons (NHL 19's fields + team; year = season end year - 1900, league
                              0 NHL, 1 AHL)

The pack (format 1):

    {'format': 1, 'generated': 'YYYY-MM-DD', 'source': {file: sha256},
     'fields': {'skater': [field name, ...], 'goalie': [...]},
     'players': [{'first', 'last', 'birth': [y, m, d], 'pos': 'C'|'LW'|'RW'|'D'|'G', 'hand': 'L'|'R',
                  'height': inches, 'weight': pounds, 'team': club code / NHL 27 team name / None (free agent),
                  'league': LEAGUES name or None, 'v': [the value of each field of his kind, in that order],
                  'career': [[careerstats.FIELDS values], ...] (goalies with NHL / AHL seasons only, by year),
                  'pro': {PRO_FIELDS name: NHL 27's value} (pro history, raw years),
                  'gear': {GEAR_SKATER / GEAR_GOALIE field: NHL 27's value} (only the values that are his, see gear_of)}],
     'contracts': [{'first', 'last', 'birth', 'pos', 'org': club code, 'cap': dollars, 'years', 'two_way',
                    'ext': [seasons, dollars, two_way] (an extension from next season, when there is one)}],
     'rights': [{'first', 'last', 'birth', 'pos', 'org': club code}] (NHL rights without a deal: unsigned picks; a pack
               made before 2026-11-03 has none, and then a club player keeps no rights),
     'money': {'floor': $100,000, 'cap': $100,000, 'rows': [floor rise, cap rise, lowest salary, highest
               entry-level salary: 12 values in $1,000 each, one per league year from 2026-27]}}

What the update writes (rosterupdate.apply with `nhl27=`; the numbers behind each choice: docs/notes/nhl27-data.md):
the c_* ratings both games have except c_overall (another scale in NHL 27) and c_potential, playerstyle only within
the player's class (NHL 19 and NHL 27 number the types alike: forwards 5-10, defence 1-4, goalies 0-2), the three
biases, each clamped to NHL 19's range; then the skill_* summary values follow (ratings.Model). Contracts: the cap
hit, seasons, two-way and extension of NHL 27's deal, in $5,000 units as in NHL 19.
"""
import gzip
import hashlib
import json
import os
import struct

from . import calendar, careerstats, durable, tdb
from .matching import Matcher, Person
from .schema import parse_schema

FORMAT = 1
PACK_NAME = 'nhl27.json.gz'
DB_PATH = 'gamemodes/database/t3db/nhl_game.db'
META_PATH = 'gamemodes/database/t3db/nhl_game-meta.xml'
MONEY_PATH = 'gamemodes/league/resource_kernel/legacybrkfeatureskernel.brk'
BIOS, SKATERS, GOALIES, TEAMS = ('exhibitionplayerbiotable', 'exhibitionskaterai', 'exhibitiongoalieai',
                                 'exhibitionteams')
POSITIONS = ('C', 'LW', 'RW', 'D', 'G')
HANDS = ('L', 'R')
GOALIE = 4
HEIGHT_BASE, WEIGHT_BASE, YEAR_BASE = 54, 120, 1900
UNIT = 5000  # contractdollars / extensiondollars: $5,000 units in both games
# NHL 27's leagues (exhibitionteams.league) whose players go into the pack, as Legacy's pack names them. Left out:
# 16 Palm Springs, 17 World of CHEL, 18 mascots, 19 EASHL drop-in, 20 Spengler Cup guests, 21 NHL alumni, 22 all-time
# teams, 23 the Threes circuit, 26 women's worlds, 27 PWHL, 35 Hockey Ultimate Team.
LEAGUES = {0: 'nhl', 1: 'ahl', 2: 'shl', 3: 'liiga', 4: 'del', 5: 'extraliga', 6: 'nl', 7: 'icehl', 8: 'allsvenskan',
           9: 'europe', 10: 'national', 11: 'ohl', 12: 'qmjhl', 13: 'whl', 15: 'echl', 24: 'national_juniors',
           25: 'national_worlds'}
NHL_CLUBS = 32  # exhibitionteams 0-31 (32-35: the All-Star teams)
EXTRA_SKATER = ('playerstyle', 'off_defbias', 'pass_carrybias', 'shoot_passbias')
EXTRA_GOALIE = ('playerstyle',)
# not written: c_overall sits on another scale in NHL 27 (+22 +- 18 against NHL 19's for the same player), c_potential
# is no rating in either game; skatingstyle changed meaning (0-7 in NHL 27, -1..254 in NHL 19) and is not in the pack
NOT_WRITTEN = {'c_overall', 'c_potential'}
STYLE_CLASS = {'F': range(5, 11), 'D': range(1, 5), 'G': range(0, 3)}
# the money table in legacybrkfeatureskernel.brk: u16 floor and cap in $100,000 at 37, then 4 rows of 12 u16 in
# $1,000 at 41, the layout of NHL 19's capdefs.brk (overlay.CAP_AT / ROWS_AT)
MONEY_AT = 37
# 2026-27 under the CBA: lowest salary and highest entry-level salary (the money rows' year 0; overlay.ROWS_2026)
LOWEST_2026, ELC_MAX_2026 = 850_000, 975_000  # as Legacy's default deal (contracts.default_terms)
ELC_AGE = 23  # younger than this at the season's start: a player with no deal gets 3 seasons at the ELC maximum
CONTRACT_FIELDS = ('contractdollars', 'contractlength', 'contractis2way', 'contractismultiyear', 'extensionlength',
                   'extensiondollars', 'extensionis2way')
# the equipment numbers NHL 19 and NHL 27 share (sock tuck, pants, tape colours, the goalie's neck guard); models, visor and
# tape style are numbered otherwise and stay out (docs/notes/equipment-real.md)
SKATER_GEAR, GOALIE_GEAR = 'exhibitionskaterequipment', 'exhibitiongoalieequipment'
GEAR_SKATER = ('skatesocktuck', 'pantstypecode', 'stickbladetapecolor', 'stickshafttapecolor')
GEAR_GOALIE = ('neckprotector',)
DEFAULT_TAPE = 0xDFDDD7   # the colour of a default row's tape

NO_CONTRACT = dict({f: 0 for f in CONTRACT_FIELDS}, proteam=-1, contractstatus=-1)
STARTER = {'ahl': (75_000, 125_000, 200_000, 300_000), 'nl': (250_000, 400_000, 600_000, 900_000),
           'shl': (150_000, 225_000, 325_000, 450_000), 'liiga': (100_000, 150_000, 250_000, 350_000),
           'chl': (10_000, 10_000, 15_000, 20_000), 'other': (50_000, 75_000, 100_000, 150_000)}
STARTER_ROW = {1: 'ahl', 2: 'shl', 3: 'liiga', 4: 'shl', 5: 'liiga', 6: 'nl', 11: 'chl', 12: 'chl', 13: 'chl'}  # by league
STARTER_AGE = 27


class Nhl27Error(ValueError):
    pass


# --- reading NHL 27 ------------------------------------------------------------------------------
def read_db(raw, meta_xml):
    """NHL 27's nhl_game.db as a tdb.Database (CRCs checked)."""
    return tdb.Database.parse(raw, parse_schema(meta_xml))


def style_class(pos):
    """'F', 'D' or 'G' of a position (pack letters or NHL 19's numbers 0-4)."""
    if pos in ('G', GOALIE):
        return 'G'
    return 'D' if pos in ('D', 3) else 'F'


def fields_of(table, extra):
    """The pack's fields of an AI table: every c_* value by name, then `extra` (those the table has)."""
    names = [f.name for f in table.fields]
    return sorted(n for n in names if n.startswith('c_')) + [n for n in extra if n in names]


def keep(bio, team):
    """A real man of a league the pack carries (or a free agent): no legend, mascot, woman, made-up player or special
    team."""
    if bio.get('islegend') or bio.get('ismascot') or bio.get('gender') or bio.get('playerclassid', -1) != -1:
        return False
    if not bio['year'] or not bio['firstname'].strip() or not bio['lastname'].strip() or bio['position'] >= len(POSITIONS):
        return False
    if bio['team'] == -1:
        return True  # a free agent
    return team is not None and team['league'] in LEAGUES


def _team_name(team):
    if team['league'] == 0 and 0 <= team['index'] < NHL_CLUBS:
        return calendar.CODES[team['index']]
    return team['teamname'].strip()


def _birth(b):
    return [YEAR_BASE + b['year'], b['month'] + 1, b['day'] + 1]


# a player's pro history in the bio (raw years: season end year - 1900, -1 for none); the expansion draft exempts first
# and second year pros (no `yearprodebut` counts as none) and uses `expansiondraftstatus` (0 exempt, 1 no-move clause,
# 3 exposed in NHL 27)
PRO_FIELDS = ('yearprodebut', 'yearfirstsigned', 'yearwaivereligible', 'progamesplayedcareer', 'nhlgamesplayedcareer',
              'rookie', 'expansiondraftstatus')
PRO_YEARS = ('yearprodebut', 'yearfirstsigned', 'yearwaivereligible')


def careers_of(db):
    """{game_id: [[careerstats.FIELDS values]]} of NHL 27's goalie seasons in the NHL and AHL (leagues 0 and 1), by
    year; NHL 27's own years (season end year - 1900)."""
    if careerstats.SEASON not in db:
        return {}
    out = {}
    for r in db[careerstats.SEASON].rows():
        if r['league'] in (0, 1):
            out.setdefault(r['game_id'], []).append([r[f] for f in careerstats.FIELDS])
    for rows in out.values():
        rows.sort()
    return out


def gear_of(row, kind, default_stick):
    """{field: value} of one NHL 27 equipment row that are really his. A value other than the default row's is real
    wherever it stands; a default one (tuck 0, pants 0, the default tape) only on a row whose stick is not the default
    (a curated row), because a default row says nothing. A goalie's neck guard counts only when it is on."""
    if kind == 'goalie':
        return {f: row[f] for f in GEAR_GOALIE if row.get(f)}
    curated = row['stick'] != default_stick
    out = {}
    for f in GEAR_SKATER:
        default = DEFAULT_TAPE if f.endswith('tapecolor') else 0
        if row[f] != default or curated:
            out[f] = row[f]
    return out


def gear_part(db):
    """({'skater': {game_id: gear}, 'goalie': {...}}) of NHL 27's equipment tables; empty when it has none."""
    out = {'skater': {}, 'goalie': {}}
    if SKATER_GEAR not in db or GOALIE_GEAR not in db:
        return out
    sticks = {}
    for r in db[SKATER_GEAR].rows():
        sticks[r['stick']] = sticks.get(r['stick'], 0) + 1
    default_stick = max(sticks, key=lambda k: (sticks[k], -k)) if sticks else None   # the default row's stick
    for kind, table in (('skater', SKATER_GEAR), ('goalie', GOALIE_GEAR)):
        for r in db[table].rows():
            g = gear_of(r, kind, default_stick)
            if g:
                out[kind][r['game_id']] = g
    return out


def players_part(db):
    """(fields, players) of the pack (see the module's docstring), sorted by league, team, name, birth."""
    skaters, goalies = db[SKATERS], db[GOALIES]
    fields = {'skater': fields_of(skaters, EXTRA_SKATER), 'goalie': fields_of(goalies, EXTRA_GOALIE)}
    ai = {False: {r['game_id']: r for r in skaters.rows()}, True: {r['game_id']: r for r in goalies.rows()}}
    team_of = {t['index']: t for t in db[TEAMS].rows()}
    careers = careers_of(db)
    gear = gear_part(db)
    players = []
    for bio in db[BIOS].rows():
        team = team_of.get(bio['team']) if bio['team'] != -1 else None
        if not keep(bio, team):
            continue
        goalie = bio['position'] == GOALIE
        row = ai[goalie].get(bio['game_id'])
        if row is None:
            continue
        players.append({'first': bio['firstname'].strip(), 'last': bio['lastname'].strip(), 'birth': _birth(bio),
                        'pos': POSITIONS[bio['position']], 'hand': HANDS[bio['handedness']],
                        'height': HEIGHT_BASE + bio['height'], 'weight': WEIGHT_BASE + bio['weight'],
                        'team': _team_name(team) if team else None,
                        'league': LEAGUES[team['league']] if team else None,
                        'v': [row[f] for f in fields['goalie' if goalie else 'skater']],
                        'pro': {f: bio[f] for f in PRO_FIELDS if f in bio}})
        if goalie and careers.get(bio['game_id']):
            players[-1]['career'] = careers[bio['game_id']]
        if gear['goalie' if goalie else 'skater'].get(bio['game_id']):
            players[-1]['gear'] = gear['goalie' if goalie else 'skater'][bio['game_id']]
    # one name and birthdate on several records is a template of EA's (six free agents 'Jordan NHL', born 1 Jan
    # 2000, one per position, every rating 66), not a person: a real player has one record
    seen = {}
    for p in players:
        key = (p['first'], p['last'], tuple(p['birth']))
        seen[key] = seen.get(key, 0) + 1
    players = [p for p in players if seen[(p['first'], p['last'], tuple(p['birth']))] == 1]
    order = {k: n for n, k in enumerate(LEAGUES.values())}
    players.sort(key=lambda p: (order.get(p['league'], len(order)), p['team'] or '', p['last'], p['first'],
                                p['birth'], p['pos']))
    return fields, players


def contracts_part(db):
    """[deal] of every player NHL 27 has on an NHL contract with money, sorted by club and name."""
    out = []
    for b in db[BIOS].rows():
        org, cap, years = b['proteam'], b['contractdollars'], b['contractlength']
        first, last = b['firstname'].strip(), b['lastname'].strip()
        if not (0 <= org < NHL_CLUBS and cap and years and first and last and b['position'] < len(POSITIONS)):
            continue
        if b.get('islegend') or b.get('gender') or b.get('playerclassid', -1) != -1:
            continue
        deal = {'first': first, 'last': last, 'birth': _birth(b), 'pos': POSITIONS[b['position']],
                'org': calendar.CODES[org], 'cap': cap * UNIT, 'years': years, 'two_way': b['contractis2way']}
        if b['extensionlength'] and b['extensiondollars']:
            deal['ext'] = [b['extensionlength'], b['extensiondollars'] * UNIT, b['extensionis2way']]
        out.append(deal)
    out.sort(key=lambda d: (d['org'], d['last'], d['first'], d['birth']))
    return out


def rights_part(db):
    """[right] of every player whose NHL rights a club holds with no deal (an unsigned pick in junior, college, Europe or
    the AHL), sorted by club and name: {'first', 'last', 'birth', 'pos', 'org': club code}. NHL 27 keeps 303 such players
    (contractstatus 0, no money), as NHL 19's own roster keeps its unsigned picks; a player on the club itself is left out."""
    out = []
    for b in db[BIOS].rows():
        org = b['proteam']
        first, last = b['firstname'].strip(), b['lastname'].strip()
        if not (0 <= org < NHL_CLUBS and first and last and b['position'] < len(POSITIONS)) or b['team'] == org:
            continue
        if (b['contractdollars'] and b['contractlength']) or b.get('islegend') or b.get('gender') \
                or b.get('playerclassid', -1) != -1:
            continue
        out.append({'first': first, 'last': last, 'birth': _birth(b), 'pos': POSITIONS[b['position']],
                    'org': calendar.CODES[org]})
    out.sort(key=lambda r: (r['org'], r['last'], r['first'], r['birth']))
    return out


def money(raw):
    """{'floor', 'cap', 'rows'} of the league kernel's money table (MONEY_AT), after checking it reads as one."""
    if len(raw) < MONEY_AT + 4 + 96:
        raise Nhl27Error('the money table is missing (file too short)')
    floor, cap = struct.unpack_from('<2H', raw, MONEY_AT)
    rows = [list(struct.unpack_from('<12H', raw, MONEY_AT + 4 + 24 * k)) for k in range(4)]
    lowest, elc = rows[2], rows[3]
    if not (0 < floor < cap and rows[0][0] == rows[1][0] == 0 and lowest == sorted(lowest)
            and all(e > lo for e, lo in zip(elc, lowest))):
        raise Nhl27Error('the money table does not read as one (floor, cap, rows)')
    return {'floor': floor, 'cap': cap, 'rows': rows}


def build(db, money_raw=None, source=None, generated=''):
    """The pack (see the module's docstring) from NHL 27's database and money table."""
    fields, players = players_part(db)
    pack = {'format': FORMAT, 'generated': generated, 'source': dict(source or {}), 'fields': fields,
            'players': players, 'contracts': contracts_part(db), 'rights': rights_part(db)}
    if money_raw is not None:
        pack['money'] = money(money_raw)
    return pack


def write_pack(pack, path):
    """gzip JSON, the same bytes for the same pack (no time in the gzip header)."""
    raw = json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path + '.part', 'wb') as f:
        f.write(gzip.compress(raw, mtime=0))
    durable.replace(path + '.part', path)
    return hashlib.sha256(raw).hexdigest()


def usable(pack):
    return (isinstance(pack, dict) and pack.get('format') == FORMAT and isinstance(pack.get('players'), list)
            and isinstance(pack.get('fields'), dict))


def load(path):
    """The pack at `path`, or None when it is missing or not one this version reads."""
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            pack = json.load(f)
    except (OSError, ValueError):
        return None
    return pack if usable(pack) else None


def report(pack, log=print):
    """Printed checks: players per league and position, each field's range, the deals, the money rows."""
    from collections import Counter
    players = pack['players']
    log(f"nhl27: {len(players)} players, {len(pack['fields']['skater'])} skater and "
        f"{len(pack['fields']['goalie'])} goalie fields")
    for league, n in Counter(p['league'] or 'free agent' for p in players).most_common():
        log(f'   {league}: {n}')
    log(f"   gear: {sum('gear' in p for p in players)} players carry real equipment")
    log('   positions: ' + ', '.join(f'{k} {n}' for k, n in sorted(Counter(p['pos'] for p in players).items())))
    for kind in ('skater', 'goalie'):
        names = pack['fields'][kind]
        vals = [p['v'] for p in players if (p['pos'] == 'G') == (kind == 'goalie')]
        if vals:
            spans = [f'{n} {min(v[i] for v in vals)}-{max(v[i] for v in vals)}' for i, n in enumerate(names)]
            log(f'   {kind}: ' + ', '.join(spans))
    deals = pack.get('contracts') or []
    if deals:
        caps = sorted(d['cap'] for d in deals)
        log(f"   contracts: {len(deals)} NHL deals, ${caps[0] / 1e6:.3f}M - ${caps[-1] / 1e6:.3f}M, "
            f"{sum(1 for d in deals if d.get('ext'))} with an extension, {len({d['org'] for d in deals})} clubs")
    rights = pack.get('rights') or []
    if rights:
        log(f"   rights: {len(rights)} players' NHL rights without a deal, {len({r['org'] for r in rights})} clubs")
    m = pack.get('money')
    if m:
        log(f"   money: floor ${m['floor'] / 10:.1f}M, cap ${m['cap'] / 10:.1f}M, rows {m['rows']}")


# --- matching -----------------------------------------------------------------------------------
def _person(key, p):
    y, m, d = (list(p.get('birth') or []) + [0, 0, 0])[:3]
    return Person(key, p.get('first') or '', p.get('last') or '', f'{y:04d}-{m:02d}-{d:02d}' if y else '')


def match_people(reals, players, shift=0):
    """[(real, NHL 27 player, level)] for the `reals` (dicts with 'first', 'last', 'birth' [y, m, d] or
    'YYYY-MM-DD', 'position' or 'pos') that find an NHL 27 player of their kind (a goalie only a goalie), by name and
    birth date (matching.py). `shift`: years the NHL 27 side may be behind (0: both on the real calendar)."""
    out = []
    for goalie in (True, False):
        side = [(i, p) for i, p in enumerate(players) if (p['pos'] == 'G') == goalie]
        matcher = Matcher([_person(i, p) for i, p in side], shifts=range(shift + 1))
        mine = [r for r in reals if ((r.get('position') or r.get('pos')) == 'G') == goalie]
        people = []
        for i, r in enumerate(mine):
            birth = r.get('birth')
            if isinstance(birth, str):
                people.append(Person(i, r.get('first') or '', r.get('last') or '', birth))
            else:
                people.append(_person(i, r))
        for r, m in zip(mine, matcher.match_all(people)):
            if m.game is not None:
                out.append((r, players[m.game.key], m.level))
    return out


def match_rate(reals, players):
    """D1: how many real players (NHL.com rosters) NHL 27 has, on name + birth date ('exact' or 'date' level).
    {'total', 'matched', 'rate', 'levels', 'misses': ['First Last (TEAM, born)']}."""
    found = match_people(reals, players)
    levels = {}
    for _r, _p, level in found:
        levels[level] = levels.get(level, 0) + 1
    hit = {id(r) for r, _p, level in found if level in ('exact', 'date')}
    misses = sorted(f"{r.get('first')} {r.get('last')} ({r.get('team')}, {r.get('birth')})"
                    for r in reals if id(r) not in hit)
    total = len(reals)
    matched = total - len(misses)
    return {'total': total, 'matched': matched, 'rate': matched / total if total else 0.0, 'levels': levels,
            'misses': misses}


# --- what the update writes -----------------------------------------------------------------------
def values_of(player, fields):
    """{field: NHL 27 value} of a pack player (`fields`: the pack's 'fields')."""
    names = fields['goalie' if player['pos'] == 'G' else 'skater']
    return dict(zip(names, player['v']))


def ai_values(player, fields, cur, ranges, pos):
    """{field: new value} of an NHL 19 AI record `cur` (dict) for NHL 27's `player`: the fields both have but
    NOT_WRITTEN, clamped to `ranges` ({field: (low, high)}); playerstyle only when it is of the class of NHL 19
    position `pos` (0-4)."""
    out = {}
    for name, v in values_of(player, fields).items():
        if name in NOT_WRITTEN or name not in cur or name not in ranges:
            continue
        if not isinstance(v, int) or isinstance(v, bool):
            continue
        if name == 'playerstyle' and v not in STYLE_CLASS[style_class(pos)]:
            continue
        low, high = ranges[name]
        out[name] = max(low, min(high, v))
    return out


def units(dollars):
    return max(1, round(dollars / UNIT))


def terms(deal):
    """NHL 19 bio contract values of an NHL 27 deal."""
    years, cap, two = deal.get('ext') or (0, 0, 0)
    return {'contractdollars': min(16383, units(deal['cap'])), 'contractlength': max(1, min(15, deal['years'])),
            'contractis2way': int(bool(deal['two_way'])), 'contractismultiyear': int(deal['years'] >= 2),
            'extensionlength': min(15, years), 'extensiondollars': min(16383, units(cap)) if years else 0,
            'extensionis2way': int(bool(two)) if years else 0}


def starter(row, overall, age):
    """The deal of a club player with none and no NHL team's rights (Legacy's starter deal, the owner's choice of
    2026-10-22): real dollars a season by his league's STARTER row and his overall, one-way, one season from STARTER_AGE
    on, else two."""
    band = 0 if overall < 70 else 1 if overall < 75 else 2 if overall < 80 else 3
    years = 1 if age >= STARTER_AGE else 2
    return {'contractdollars': units(STARTER[row][band]), 'contractlength': years, 'contractis2way': 0,
            'contractismultiyear': int(years >= 2), 'extensionlength': 0, 'extensiondollars': 0, 'extensionis2way': 0}


def estimate(age):
    """The deal of a club player NHL 27 has none for: three seasons at the entry-level maximum for a young player
    (younger than ELC_AGE), else one season at the lowest salary (Legacy contracts.default_terms)."""
    years, dollars = (3, ELC_MAX_2026) if age < ELC_AGE else (1, LOWEST_2026)
    return {'contractdollars': units(dollars), 'contractlength': years, 'contractis2way': 0,
            'contractismultiyear': int(years >= 2), 'extensionlength': 0, 'extensiondollars': 0, 'extensionis2way': 0}
