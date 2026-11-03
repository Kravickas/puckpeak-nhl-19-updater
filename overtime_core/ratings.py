"""Real ratings for NHL 19 players: EA's published attributes, written into exhibitionskaterai / exhibitiongoalieai,
then the game's summary values (skill_*) worked out again. Idea from PS3 Legacy `builder.apply_ea_ratings`.

NHL 27's own values come first when the owner's local NHL 27 pack is there (nhl27.py, plan_nhl27: every c_*
rating both games have, playerstyle and the biases); EA's list then rates the players NHL 27 does not have.

Source: the owner's Legacy data pack (`ratings_list`, `ea_ratings` in format 1: EA NHL 27, [{'name', 'team',
'position', 'birth', 'ovr', 'attrs'}]), downloaded at run time from Legacy's file server and cached; nothing of it
ships with Overtime. The GitHub release asset went away with Legacy 0.32.0 (format 2): that URL answers 404.

skill_overall and the other skill_* values are, for each playerstyle, a straight line of the c_* attributes (the game's
default roster: 95-100 % exact after rounding). `Model` fits those lines on the roster being edited, so the game's own
formula is neither needed nor copied. c_overall is no such line (its use is unknown): left as it is. Attributes EA
does not publish (skaters' backskating and aggressiveness, goalies' consistency and paddle-down) keep their value.
"""
import gzip
import json
import os

from .matching import Matcher, Person

DEFAULT_PACK_URL = 'https://puckpeak.com/legacy-roster/datapack.json.gz'
PACK_URL = os.environ.get('OVERTIME_PACK_URL', DEFAULT_PACK_URL)
PACK_FORMAT = 2  # format 2 (Legacy 0.32.0) renamed ea_ratings to ratings_list; format 1 still reads
PLAYERS, BIOS = 'exhibitionplayers', 'exhibitionplayerbiotable'
SKATERS, GOALIES = 'exhibitionskaterai', 'exhibitiongoalieai'
GOALIE = 4
TOP = 99

SKATER_ATTRS = {
    'Acceleration': 'c_acceleration', 'Agility': 'c_agility', 'Balance': 'c_balance', 'Endurance': 'c_endurance',
    'Speed': 'c_speed', 'Slap Shot Accuracy': 'c_slapaccuracy', 'Slap Shot Power': 'c_slapshotpower',
    'Wrist Shot Accuracy': 'c_wristaccuracy', 'Wrist Shot Power': 'c_wristshotpower', 'Deking': 'c_deking',
    'Hand-Eye': 'c_handeye', 'Passing': 'c_passing', 'Puck Control': 'c_puckcontrol', 'Body Checking': 'c_bodychecking',
    'Strength': 'c_strength', 'Aggressiveness': 'c_aggression', 'Durability': 'c_durability',
    'Fighting Skill': 'c_fightingskill', 'Defensive Awareness': 'c_defawareness', 'Faceoffs': 'c_faceoffs',
    'Shot Blocking': 'c_shotblocking', 'Stick Checking': 'c_stickchecking', 'Discipline': 'c_discipline',
    'Offensive Awareness': 'c_offawareness', 'Poise': 'c_poise',
}
GOALIE_ATTRS = {
    'Glove Side High': 'c_gsh', 'Glove Side Low': 'c_gsl', 'Stick Side High': 'c_ssh', 'Stick Side Low': 'c_ssl',
    'Five Hole': 'c_5hole', 'Angles': 'c_positioning', 'Breakaway': 'c_breakaway', 'Rebound Control': 'c_reboundcontrol',
    'Shot Recover': 'c_shotrecover', 'Vision': 'c_vision', 'Speed': 'c_speed', 'Agility': 'c_agility',
    'Endurance': 'c_endurance', 'Durability': 'c_durability', 'Poke Check': 'c_pokecheck', 'Passing': 'c_passing',
    'Puck Playing Frequency': 'c_puckplayfrequency', 'Aggressiveness': 'c_aggression', 'Poise': 'c_poise',
}
NOT_INPUTS = {'c_overall', 'c_potential', 'c_fighting'}


class PackError(RuntimeError):
    pass


# --- the data pack -----------------------------------------------------------------------------
def usable(pack):
    return isinstance(pack, dict) and isinstance(pack.get('format'), int) and 1 <= pack['format'] <= PACK_FORMAT


def ea_rows(pack):
    """EA's rating rows of a data pack: `ratings_list` (format 2), `ea_ratings` (format 1); [] without."""
    return list((pack or {}).get('ratings_list') or (pack or {}).get('ea_ratings') or [])


def load_pack(cache_dir, fetch=None, offline=False, log=lambda msg: None):
    """The data pack: downloaded (`fetch(url) -> bytes`) and cached in `cache_dir`, else the cached copy."""
    path = os.path.join(cache_dir, 'datapack.json.gz')
    if fetch is not None and not offline:
        try:
            raw = fetch(PACK_URL)
            pack = json.loads(gzip.decompress(raw))
            if usable(pack):
                os.makedirs(cache_dir, exist_ok=True)
                with open(path + '.part', 'wb') as f:
                    f.write(raw)
                os.replace(path + '.part', path)
                log(f"data pack {pack.get('generated', '')}: downloaded")
                return pack
            log('the published data pack needs a newer Overtime')
        except Exception as err:  # offline, no release: the cached copy
            log(f'data pack: no download ({err})')
    if os.path.exists(path):
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            pack = json.load(f)
        if usable(pack):
            log(f"data pack {pack.get('generated', '')}: cached copy")
            return pack
    raise PackError('no data pack (no connection and no cached copy)')


# --- the summary values ------------------------------------------------------------------------
def _solve(a, b):
    """x with a x = b (Gauss-Jordan, partial pivoting); `a` gets a small ridge so a constant column is harmless."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for i in range(n):
        m[i][i] += 1e-6
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        piv = m[c][c]
        if abs(piv) < 1e-12:
            continue
        inv = 1.0 / piv
        m[c] = [v * inv for v in m[c]]
        for r in range(n):
            if r != c and m[r][c]:
                f = m[r][c]
                mr, mc = m[r], m[c]
                m[r] = [x - f * y for x, y in zip(mr, mc)]
    return [m[i][n] for i in range(n)]


class Model:
    """skill_* of a ratings table as straight lines of its c_* attributes, one set per playerstyle."""
    MIN_ROWS = 40

    def __init__(self, inputs, targets, lines):
        self.inputs, self.targets, self.lines = inputs, targets, lines  # lines: {style or None: {target: weights}}

    @classmethod
    def fit(cls, table):
        names = [f.name for f in table.fields]
        inputs = sorted(n for n in names if n.startswith('c_') and n not in NOT_INPUTS)
        targets = sorted(n for n in names if n.startswith('skill_'))
        rows = table.rows()
        groups = {None: rows}
        for r in rows:
            groups.setdefault(r['playerstyle'], []).append(r)
        lines = {}
        k = len(inputs) + 1
        for style, group in groups.items():
            if len(group) < max(cls.MIN_ROWS, 2 * k):
                continue
            xtx = [[0.0] * k for _ in range(k)]
            xty = {t: [0.0] * k for t in targets}
            for r in group:
                x = [r[n] for n in inputs] + [1]
                for i in range(k):
                    xi, row = x[i], xtx[i]
                    for j in range(i, k):
                        row[j] += xi * x[j]
                for t in targets:
                    y, acc = r[t], xty[t]
                    for i in range(k):
                        acc[i] += x[i] * y
            for i in range(k):
                for j in range(i):
                    xtx[i][j] = xtx[j][i]
            lines[style] = {t: _solve(xtx, xty[t]) for t in targets}
        return cls(inputs, targets, lines)

    def predict(self, row):
        """{skill field: value} for a record (dict with the c_* values and playerstyle)."""
        w = self.lines.get(row.get('playerstyle'), self.lines[None])
        x = [row[n] for n in self.inputs] + [1]
        return {t: max(0, min(TOP, round(sum(a * b for a, b in zip(w[t], x))))) for t in self.targets}


# --- matching and writing ----------------------------------------------------------------------
def _birth(b):
    return f"{b['year'] + 1900:04d}-{b['month'] + 1:02d}-{b['day'] + 1:02d}"


def _split(name):
    first, _, last = (name or '').strip().partition(' ')
    return first, last


def attribute_mean(values, goalie):
    """The mean of a player's listed attributes (`values` {c_* field: rating}): his level, what a starter deal goes by."""
    fields = {f for f in (GOALIE_ATTRS if goalie else SKATER_ATTRS).values() if f in values}
    return sum(values[f] for f in fields) / len(fields) if fields else 0.0


def level_offset(rows):
    """{goalie: how far EA's overall lies above the mean of a player's attributes}: the median of EA's list (`rows`), 0
    without one. A level plus this is an overall."""
    out = {False: 0.0, True: 0.0}
    for goalie, attrs in ((False, SKATER_ATTRS), (True, GOALIE_ATTRS)):
        gaps = []
        for r in rows or ():
            values = [v for k, v in (r.get('attrs') or {}).items() if k in attrs and v is not None]
            if (r.get('position') or '').startswith('G') == goalie and r.get('ovr') and len(values) >= 10:
                gaps.append(r['ovr'] - sum(values) / len(values))
        gaps.sort()
        if gaps:
            out[goalie] = gaps[len(gaps) // 2]
    return out


def level_line(pack):
    """{goalie: (a, b)} of the straight line level = a + b * overall through NHL 27's players (`pack`, nhl27.py): its
    overall runs lower than the level below the NHL (an OHL player's about 13 lower, an NHL player's about the same)."""
    out = {}
    for goalie, kind in ((False, 'skater'), (True, 'goalie')):
        at = {name: k for k, name in enumerate(pack['fields'][kind])}
        pairs = [(p['v'][at['c_overall']], attribute_mean({f: p['v'][at[f]] for f in at}, goalie))
                 for p in pack['players'] if (p.get('pos') == 'G') == goalie]
        n = len(pairs)
        mx, my = sum(x for x, _ in pairs) / max(n, 1), sum(y for _, y in pairs) / max(n, 1)
        var = sum((x - mx) ** 2 for x, _ in pairs)
        b = sum((x - mx) * (y - my) for x, y in pairs) / var if var else 1.0
        out[goalie] = (my - b * mx if var else 0.0, b)
    return out


def match(db, ratings, game_ids=None, shift=0):
    """[(rating, bio row, level)] for the rating rows that find their player (a goalie only a goalie, a skater only
    a skater); `game_ids` limits the players looked at (default: everyone with a bio). Birth dates also match up to
    `shift` years earlier (a roster on the game's clock, teams.year_shift). A row has 'name' and 'position' (EA's
    list) or 'first', 'last' and 'pos' (NHL 27's, nhl27.py)."""
    bios = db[BIOS]
    people = {True: [], False: []}
    for i in range(bios.count):
        b = bios.row(i)
        if game_ids is not None and b['game_id'] not in game_ids:
            continue
        people[b['position'] == GOALIE].append(Person(i, b['firstname'], b['lastname'], _birth(b)))
    out = []
    for goalie in (True, False):
        reals = []
        for r in ratings:
            if (r.get('position', r.get('pos')) == 'G') != goalie:
                continue
            first, last = (r['first'], r['last']) if 'last' in r else _split(r.get('name'))
            y, m, d = (list(r.get('birth') or []) + [0, 0, 0])[:3]
            reals.append((r, Person(id(r), first, last, f'{y:04d}-{m:02d}-{d:02d}' if y else '')))
        found = Matcher(people[goalie], shifts=range(shift + 1)).match_all([p for _r, p in reals])
        out += [(r, m.game.key, m.level) for (r, _p), m in zip(reals, found) if m.game is not None]
    return out


def plan(db, matches, models=None):
    """[(table, row, field, old, new)] that give the matched players EA's attributes and the skill_* that follow."""
    models = models or {}
    bios = db[BIOS]
    rows = {name: {db[name].get(i, 'game_id'): i for i in range(db[name].count)} for name in (SKATERS, GOALIES)}
    out = []
    for rating, brow, _level in matches:
        b = bios.row(brow)
        goalie = b['position'] == GOALIE
        name, attrs = (GOALIES, GOALIE_ATTRS) if goalie else (SKATERS, SKATER_ATTRS)
        row = rows[name].get(b['game_id'])
        if row is None:
            continue
        t = db[name]
        cur = t.row(row)
        new = dict(cur)
        for ea, field in attrs.items():
            v = (rating.get('attrs') or {}).get(ea)
            if isinstance(v, int) and not isinstance(v, bool) and field in cur:
                new[field] = max(0, min(TOP, v))
        if name not in models:
            models[name] = Model.fit(t)
        new.update(models[name].predict(new))
        out += [(name, row, f, cur[f], new[f]) for f in sorted(new) if new[f] != cur[f]]
    return out


def plan_nhl27(db, schema, matches, fields, models=None):
    """[(table, row, field, old, new)] that give the matched players (`matches`: match() on the NHL 27 pack's
    players) NHL 27's values (nhl27.ai_values: the fields both games have, clamped to this roster's ranges,
    playerstyle within the player's class) and the skill_* that follow. `models`: Model per table, fitted on the
    roster before any rating changed (fitted here when missing)."""
    from . import nhl27
    models = {} if models is None else models
    bios = db[BIOS]
    rows = {name: {db[name].get(i, 'game_id'): i for i in range(db[name].count)} for name in (SKATERS, GOALIES)}
    ranges = {}
    out = []
    for player, brow, _level in matches:
        b = bios.row(brow)
        name = GOALIES if b['position'] == GOALIE else SKATERS
        row = rows[name].get(b['game_id'])
        if row is None:
            continue
        t = db[name]
        if name not in ranges:
            meta = schema.by_name(name)
            ranges[name] = {f.name: (f.low, f.high) for f in meta.fields.values() if not f.is_string}
        if name not in models:
            models[name] = Model.fit(t)
        cur = t.row(row)
        new = dict(cur)
        new.update(nhl27.ai_values(player, fields, cur, ranges[name], b['position']))
        new.update(models[name].predict(new))
        out += [(name, row, f, cur[f], new[f]) for f in sorted(new) if new[f] != cur[f]]
    return out


def apply(db, todo, setter=None):
    for name, row, field, _old, new in todo:
        if setter is None:
            db[name].set(row, field, new)
        else:
            setter(name, row, field, new)
    return len(todo)
