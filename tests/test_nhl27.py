"""NHL 27's data in NHL 19 rosters (overtime_core/nhl27.py): a synthetic NHL 27-like t3db (bio, skater AI, goalie AI
and team tables with NHL 27's field names and ranges) -> the pack; matching on name + birth date (spike D1, static
part); the values written stay in NHL 19's ranges and player types in their class; contracts; where the app finds
the pack; the league layer's money rows. The game-marked tests run the whole update on the default roster."""
import collections
import gzip
import json
import os
import random
import struct

import pytest

from overtime_core import calendar, careerstats, nhl27 as N, overlay, ratings as R, rosterupdate as U, tdb
from overtime_core import teams as T
from overtime_core.schema import parse_schema
from overtime_core.tdb import TYPE_INT, TYPE_STRING, Database, Field, Table

DATA = os.path.join(os.path.dirname(__file__), 'data')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_PACK = os.path.join(ROOT, 'packs', N.PACK_NAME)

# (name, bits, low, high) or (name, 'str', bytes)
BIO = [('firstname', 'str', 16), ('lastname', 'str', 16), ('game_id', 16, 0, 65535), ('year', 8, 0, 255),
       ('month', 4, 0, 11), ('day', 5, 0, 30), ('position', 3, 0, 7), ('handedness', 1, 0, 1), ('height', 5, 0, 31),
       ('weight', 8, 0, 255), ('team', 10, -1, 1022), ('proteam', 6, -1, 62), ('gender', 1, 0, 1),
       ('playerclassid', 10, -1, 1022), ('islegend', 1, 0, 1), ('ismascot', 1, 0, 1), ('contractdollars', 14, 0, 16383),
       ('contractlength', 4, 0, 15), ('contractis2way', 1, 0, 1), ('contractismultiyear', 1, 0, 1),
       ('extensionlength', 4, 0, 15), ('extensiondollars', 14, 0, 16383), ('extensionis2way', 1, 0, 1),
       ('contractstatus', 3, -1, 6)]
SKATER = [('game_id', 16, 0, 65535), ('c_speed', 7, 0, 99), ('c_passing', 7, 0, 99), ('c_overall', 7, 0, 99),
          ('c_potential', 7, 0, 99), ('c_fighting', 2, 0, 3), ('playerstyle', 4, 0, 15), ('off_defbias', 4, 0, 15),
          ('pass_carrybias', 4, 0, 15), ('shoot_passbias', 4, 0, 15), ('skatingstyle', 3, 0, 7)]
GOALIE = [('game_id', 16, 0, 65535), ('c_gsh', 7, 0, 99), ('c_5hole', 7, 0, 99), ('c_overall', 7, 0, 99),
          ('c_potential', 7, 0, 99), ('playerstyle', 2, 0, 3)]
TEAM = [('teamname', 'str', 24), ('abbrname', 'str', 8), ('index', 10, 0, 1022), ('league', 6, 0, 63)]
# the NHL 19 side: the same names, NHL 19's skater style range and a narrower c_speed to see the clamp
SKATER19 = [f if f[0] not in ('c_speed', 'skatingstyle') else (f[0], 8, -1, 254) if f[0] == 'skatingstyle'
            else ('c_speed', 7, 0, 90) for f in SKATER] + [('skill_overall', 7, 0, 99)]
GOALIE19 = GOALIE + [('skill_overall', 7, 0, 99)]
PRO = [('yearprodebut', 8, -1, 254), ('nhlgamesplayedcareer', 12, 0, 4095), ('rookie', 1, 0, 1),
       ('expansiondraftstatus', 3, -1, 6)]  # some of NHL 27's pro history fields
CAREER = [('game_id', 16, 0, 65535), ('year', 8, 0, 255), ('league', 6, 0, 63), ('team', 10, -1, 1022)] + [
    (f, 20, 0, 1048575) for f in careerstats.STATS]
TABLES27 = {'exhibitionplayerbiotable': ('PBIO', BIO), 'exhibitionskaterai': ('SKAI', SKATER),
            'exhibitiongoalieai': ('GOAI', GOALIE), 'exhibitionteams': ('TEAM', TEAM),
            'stockcareerseasongoaliestats': ('GSTA', CAREER)}
TABLES19 = {'exhibitionplayerbiotable': ('PBIO', BIO), 'exhibitionskaterai': ('SKAI', SKATER19),
            'exhibitiongoalieai': ('GOAI', GOALIE19)}


def schema_xml(tables):
    out = ['<?xml version="1.0" encoding="utf-8"?>\n<database name="t" shortname="t" version="1">']
    for name, (tag, fields) in tables.items():
        out.append(f'<table name="{name}" shortname="{tag}" savegroups="rosters"><fields>')
        for k, f in enumerate(fields):
            if f[1] == 'str':
                out.append(f'<field name="{f[0]}" shortname="f{k:03d}" type="FIELDTYPE_STRING" depth="{8 * f[2]}" '
                           'rangelow="0" rangehigh="0" />')
            else:
                out.append(f'<field name="{f[0]}" shortname="f{k:03d}" type="FIELDTYPE_INTEGER" depth="{f[1]}" '
                           f'rangelow="{f[2]}" rangehigh="{f[3]}" />')
        out.append('</fields></table>')
    out.append('</database>')
    return '\n'.join(out).encode('utf-8')


def make_db(tables, rows, meta):
    """A t3db with `rows[name]` ([{field: value}]) in each table, through bytes and back (CRCs checked)."""
    schema = parse_schema(meta)
    out = []
    for name, (tag, fields) in tables.items():
        tfields, bit = [], 0
        for k, f in enumerate(fields):  # strings first: they sit on whole bytes
            if f[1] == 'str':
                tfields.append(Field(f'f{k:03d}', TYPE_STRING, bit, 8 * f[2], f[0]))
                bit += 8 * f[2]
        for k, f in enumerate(fields):
            if f[1] != 'str':
                tfields.append(Field(f'f{k:03d}', TYPE_INT, bit, f[1], f[0], f[2]))
                bit += f[1]
        reclen = (bit + 31) // 32 * 4
        data = rows.get(name, [])
        h = bytearray(0x28)
        struct.pack_into('<IIII', h, 4, 2, reclen, reclen * 8 - 1, 0)
        struct.pack_into('<HHII', h, 0x14, max(1, len(data)), len(data), 0xFFFF0000, len(tfields))
        t = Table(tag, h, tfields, bytes(reclen * max(1, len(data))), schema.tables[tag])
        for i, r in enumerate(data):
            for k, v in r.items():
                t.set(i, k, v)
        out.append(t)
    return tdb.Database.parse(Database(out).to_bytes(), schema), schema


# --- a synthetic NHL 27 -------------------------------------------------------------------------
FIRST = ['Alex', 'Ben', 'Carl', 'Dan', 'Erik', 'Filip', 'Gus', 'Hugo', 'Ivan', 'Jon', 'Kai', 'Leo', 'Max', 'Nils']
LAST = ['Aho', 'Berg', 'Carr', 'Dahl', 'Eng', 'Falk', 'Gran', 'Holm', 'Isak', 'Juhl', 'Kull', 'Lind', 'Moe', 'Nord',
        'Ojala', 'Pihl', 'Quist', 'Ruud', 'Salo', 'Tuck']


def letters(n):
    """A number as letters (matching.norm drops digits from names): 460 -> 'ega'."""
    return ''.join(chr(ord('a') + int(c)) for c in str(n))


def bio(gid, first, last, born, pos, team, **kw):
    y, m, d = born
    out = {'game_id': gid, 'firstname': first, 'lastname': last, 'year': y - 1900, 'month': m - 1, 'day': d - 1,
           'position': pos, 'handedness': gid % 2, 'height': 18, 'weight': 75, 'team': team, 'proteam': -1,
           'gender': 0, 'playerclassid': -1, 'contractstatus': -1}
    out.update(kw)
    return out


def nhl27_rows():
    rnd = random.Random(27)
    teams = [{'index': i, 'abbrname': calendar.CODES[i][:3], 'teamname': f'Club {calendar.CODES[i]}', 'league': 0}
             for i in range(32)]
    teams += [{'index': 35, 'abbrname': 'AHL', 'teamname': 'Farm Team', 'league': 1},
              {'index': 40, 'abbrname': 'ALU', 'teamname': 'Alumni', 'league': 21}]
    bios, skaters, goalies = [], [], []
    gid = 100
    for club in range(32):  # 13 per club: 11 skaters, 2 goalies
        for k in range(13):
            gid += 1
            pos = 4 if k >= 11 else k % 4
            born = (1990 + gid % 17, 1 + gid % 12, 1 + gid % 28)
            name = (FIRST[gid % len(FIRST)], f'{LAST[gid % len(LAST)]}{letters(gid)}')
            deal = {}
            if k < 10:
                deal = dict(proteam=club, contractdollars=155 + (gid * 37) % 2300, contractlength=1 + gid % 8,
                            contractis2way=int(k == 9), contractstatus=0)
                if k == 0:
                    deal.update(extensionlength=5, extensiondollars=3760, extensionis2way=0)
            bios.append(bio(gid, *name, born, pos, club, **deal))
    specials = [bio(9001, 'Wayne', 'Legend', (1961, 1, 26), 0, -1, islegend=1),
                bio(9002, 'Mascot', 'Bear', (2000, 1, 1), 0, 0, ismascot=1),
                bio(9003, 'Pat', 'Woman', (1999, 5, 5), 3, 0, gender=1),
                bio(9004, 'Made', 'Up', (2001, 2, 2), 2, 0, playerclassid=14),
                bio(9005, 'Old', 'Timer', (1970, 3, 3), 1, 40),
                bio(9006, 'No', 'Year', (1900, 1, 1), 1, 0),
                bio(9007, 'Jordan', 'NHL', (2000, 1, 1), 0, -1),
                bio(9008, 'Jordan', 'NHL', (2000, 1, 1), 0, -1),
                bio(9009, 'Free', 'Agent', (1995, 6, 7), 3, -1),
                bio(9010, 'Farm', 'Hand', (2003, 8, 9), 2, 35, proteam=5, contractdollars=170, contractlength=2,
                    contractis2way=1, contractstatus=0)]
    bios += specials
    for b in bios:
        r = {'game_id': b['game_id']}
        if b['position'] == 4:
            r.update(c_gsh=40 + rnd.randrange(60), c_5hole=40 + rnd.randrange(60), c_overall=50 + rnd.randrange(50),
                     c_potential=50, playerstyle=b['game_id'] % 3)
            goalies.append(r)
        else:
            style = (1 + b['game_id'] % 4) if b['position'] == 3 else (5 + b['game_id'] % 6)
            r.update(c_speed=40 + rnd.randrange(60), c_passing=40 + rnd.randrange(60), c_overall=50 + rnd.randrange(50),
                     c_potential=50, c_fighting=rnd.randrange(4), playerstyle=style, off_defbias=rnd.randrange(16),
                     pass_carrybias=rnd.randrange(16), shoot_passbias=rnd.randrange(16), skatingstyle=rnd.randrange(8))
            skaters.append(r)
    # goalie 112 (club 0): an NHL and an AHL season, out of order, and a season in another league; a skater's row
    career = [{'game_id': 112, 'year': 125, 'league': 0, 'team': 0, 'gamesplayed': 50, 'wins': 30, 'shutouts': 4,
               'timeinnetseconds': 180000},
              {'game_id': 112, 'year': 124, 'league': 1, 'team': 35, 'gamesplayed': 40, 'wins': 20},
              {'game_id': 112, 'year': 123, 'league': 5, 'team': -1, 'gamesplayed': 30},
              {'game_id': 101, 'year': 125, 'league': 0, 'team': 0, 'gamesplayed': 9}]
    return {'exhibitionplayerbiotable': bios, 'exhibitionskaterai': skaters, 'exhibitiongoalieai': goalies,
            'exhibitionteams': teams, 'stockcareerseasongoaliestats': career}


def money_brk(floor=769, cap=1040, rows=overlay.NHL27_ROWS):
    raw = bytearray(200)
    struct.pack_into('<2H', raw, N.MONEY_AT, floor, cap)
    struct.pack_into('<48H', raw, N.MONEY_AT + 4, *sum(rows, ()))
    return bytes(raw)


@pytest.fixture(scope='module')
def nhl27_db():
    meta = schema_xml(TABLES27)
    db, _schema = make_db(TABLES27, nhl27_rows(), meta)
    return db, meta


@pytest.fixture(scope='module')
def pack(nhl27_db):
    return N.build(nhl27_db[0], money_brk(), source={'nhl_game.db': 'x'}, generated='2026-10-18')


def test_goalies_carry_their_nhl_and_ahl_seasons(pack):
    by_last = {p['last']: p for p in pack['players']}
    g = by_last['Moe' + letters(112)]
    assert g['pos'] == 'G'
    stats = dict.fromkeys(careerstats.STATS, 0)
    assert g['career'] == [[124, 1] + list(dict(stats, gamesplayed=40, wins=20).values()),
                           [125, 0] + list(dict(stats, gamesplayed=50, wins=30, shutouts=4,
                                                timeinnetseconds=180000).values())]
    assert [dict(zip(careerstats.FIELDS, v))['gamesplayed'] for v in g['career']] == [40, 50]
    assert sum('career' in p for p in pack['players']) == 1  # not the skater, not goalies without seasons


def test_players_carry_their_pro_history(nhl27_db):
    rows = nhl27_rows()
    for b in rows['exhibitionplayerbiotable']:
        b.update(yearprodebut=115 + b['game_id'] % 10, nhlgamesplayedcareer=b['game_id'] % 900, rookie=0,
                 expansiondraftstatus=3)
    tables = dict(TABLES27, exhibitionplayerbiotable=('PBIO', BIO + PRO))
    meta = schema_xml(tables)
    db, _schema = make_db(tables, rows, meta)
    _fields, players = N.players_part(db)
    by_last = {p['last']: p for p in players}
    assert by_last['Moe' + letters(112)]['pro'] == {'yearprodebut': 117, 'nhlgamesplayedcareer': 112, 'rookie': 0,
                                                    'expansiondraftstatus': 3}
    assert all(set(p['pro']) == {'yearprodebut', 'nhlgamesplayedcareer', 'rookie', 'expansiondraftstatus'}
               for p in players)


def test_players_part_keeps_real_men_of_the_packs_leagues(pack):
    players = pack['players']
    names = {(p['first'], p['last']) for p in players}
    assert len(players) == 32 * 13 + 2  # + the free agent and the farm hand
    for gone in (('Wayne', 'Legend'), ('Mascot', 'Bear'), ('Pat', 'Woman'), ('Made', 'Up'), ('Old', 'Timer'),
                 ('No', 'Year'), ('Jordan', 'NHL')):
        assert gone not in names
    fa = next(p for p in players if p['last'] == 'Agent')
    assert fa['team'] is None and fa['league'] is None and fa['birth'] == [1995, 6, 7] and fa['pos'] == 'D'
    farm = next(p for p in players if p['last'] == 'Hand')
    assert farm['team'] == 'Farm Team' and farm['league'] == 'ahl' and farm['pos'] == 'RW'
    edm = [p for p in players if p['team'] == 'EDM']
    assert len(edm) == 13 and all(p['league'] == 'nhl' for p in edm)
    assert pack['fields'] == {'skater': ['c_fighting', 'c_overall', 'c_passing', 'c_potential', 'c_speed',
                                         'playerstyle', 'off_defbias', 'pass_carrybias', 'shoot_passbias'],
                              'goalie': ['c_5hole', 'c_gsh', 'c_overall', 'c_potential', 'playerstyle']}
    assert all(len(p['v']) == len(pack['fields']['goalie' if p['pos'] == 'G' else 'skater']) for p in players)
    order = {k: n for n, k in enumerate(N.LEAGUES.values())}
    keys = [(order.get(p['league'], 99), p['team'] or '', p['last'], p['first']) for p in players]
    assert keys == sorted(keys)


def test_contracts_part(pack):
    deals = pack['contracts']
    assert len(deals) == 32 * 10 + 1  # ten per club, the farm hand (org 5)
    assert {d['org'] for d in deals} == set(calendar.SLOTS)
    farm = next(d for d in deals if d['last'] == 'Hand')
    assert farm == {'first': 'Farm', 'last': 'Hand', 'birth': [2003, 8, 9], 'pos': 'RW', 'org': calendar.CODES[5],
                    'cap': 850_000, 'years': 2, 'two_way': 1}
    ext = [d for d in deals if 'ext' in d]
    assert len(ext) == 32 and all(d['ext'] == [5, 18_800_000, 0] for d in ext)
    assert all(d['cap'] % N.UNIT == 0 and 1 <= d['years'] <= 15 for d in deals)
    assert deals == sorted(deals, key=lambda d: (d['org'], d['last'], d['first'], d['birth']))
    assert N.terms(farm) == {'contractdollars': 170, 'contractlength': 2, 'contractis2way': 1,
                             'contractismultiyear': 1, 'extensionlength': 0, 'extensiondollars': 0,
                             'extensionis2way': 0}
    assert N.terms(ext[0])['extensiondollars'] == 3760


def test_money_rows_read_and_refused():
    m = N.money(money_brk())
    assert m == {'floor': 769, 'cap': 1040, 'rows': [list(r) for r in overlay.NHL27_ROWS]}
    with pytest.raises(N.Nhl27Error):
        N.money(money_brk(floor=1100))  # floor above the cap
    with pytest.raises(N.Nhl27Error):
        N.money(bytes(50))
    assert N.season_money({'money': m}) == (850_000, 1_025_000) == N.season_money(None)


def test_pack_is_deterministic(nhl27_db, tmp_path):
    db, meta = nhl27_db
    a = N.build(db, money_brk(), generated='2026-10-18')
    b = N.build(N.read_db(db.to_bytes(), meta), money_brk(), generated='2026-10-18')
    assert a == b
    one, two = tmp_path / 'a' / N.PACK_NAME, tmp_path / 'b' / N.PACK_NAME
    assert N.write_pack(a, str(one)) == N.write_pack(b, str(two))
    assert one.read_bytes() == two.read_bytes()
    assert N.load(str(one)) == json.loads(json.dumps(a))
    bad = tmp_path / 'bad.json.gz'
    bad.write_bytes(gzip.compress(b'{"format": 99}'))
    assert N.load(str(bad)) is None and N.load(str(tmp_path / 'missing.json.gz')) is None


def nhlcom_rosters(pack):
    """NHL.com-like rosters of the synthetic clubs: a few first names differ (Alex / Alexander), a few birth dates
    have a typo, a few players are not in NHL 27."""
    out = []
    for i, p in enumerate(q for q in pack['players'] if q['league'] == 'nhl'):
        y, m, d = p['birth']
        r = {'first': p['first'], 'last': p['last'], 'birth': f'{y:04d}-{m:02d}-{d:02d}',
             'position': {'LW': 'L', 'RW': 'R'}.get(p['pos'], p['pos']), 'team': p['team']}
        if i % 40 == 1:
            r['first'] += 'ander'
        if i % 50 == 2:
            r['birth'] = f'{y:04d}-{m:02d}-{min(28, d + 1) if d < 28 else d - 1:02d}'
        out.append(r)
    out += [{'first': 'Not', 'last': f'There{letters(k)}', 'birth': '2005-01-01', 'position': 'C', 'team': 'SEA'}
            for k in range(4)]
    return out


def test_d1_name_and_birth_match_rate(pack):
    reals = nhlcom_rosters(pack)
    rate = N.match_rate(reals, pack['players'])
    assert rate['total'] == 32 * 13 + 4
    assert rate['rate'] >= 0.95
    nhl = [p for p in pack['players'] if p['league'] == 'nhl']
    typos = [i for i in range(len(nhl)) if i % 50 == 2]
    assert rate['levels'] == {'exact': len(nhl) - len(typos) - sum(1 for i in range(len(nhl)) if i % 40 == 1),
                              'date': sum(1 for i in range(len(nhl)) if i % 40 == 1), 'name': len(typos)}
    assert len(rate['misses']) == len(typos) + 4
    assert sum(1 for m in rate['misses'] if m.startswith('Not There')) == 4
    assert {m.split(' (')[0] for m in rate['misses'] if not m.startswith('Not')} == {
        f"{nhl[i]['first']} {nhl[i]['last']}" for i in typos}


# --- writing into an NHL 19-like roster --------------------------------------------------------
def nhl19_rows(pack, shift=0):
    """An NHL 19-like roster with the synthetic NHL 27 players under other game_ids (birth years `shift` back),
    stock ratings on NHL 19's lines (skill_overall = mean of the two c_* inputs), 2018 contracts."""
    bios, skaters, goalies = [], [], []
    for k, p in enumerate(pack['players']):
        gid = 1000 + k
        y, m, d = p['birth']
        pos = N.POSITIONS.index(p['pos'])
        team = calendar.SLOTS[p['team']] if p['league'] == 'nhl' and p['team'] != 'SEA' else (
            T.SEATTLE if p['team'] == 'SEA' else 40 if p['league'] == 'ahl' else -1)
        bios.append(bio(gid, p['first'], p['last'], (y - shift, m, d), pos, team,
                        proteam=team if 0 <= team < 31 else 3 if team == 40 else -1,
                        contractdollars=500, contractlength=4, contractstatus=0 if team != -1 else -1))
        if pos == 4:
            g, h = 50 + k % 40, 60 + k % 30
            goalies.append({'game_id': gid, 'c_gsh': g, 'c_5hole': h, 'c_overall': 70, 'c_potential': 1,
                            'playerstyle': 1, 'skill_overall': round((g + h) / 2)})
        else:
            s, q = 50 + k % 40, 55 + (3 * k) % 40
            skaters.append({'game_id': gid, 'c_speed': s, 'c_passing': q, 'c_overall': 70, 'c_potential': 1,
                            'c_fighting': 1, 'playerstyle': 2 if pos == 3 else 9, 'off_defbias': 7,
                            'pass_carrybias': 7, 'shoot_passbias': 7, 'skatingstyle': 200,
                            'skill_overall': round((s + q) / 2)})
    # a player NHL 27 does not have, and an AHL player with a 2018 deal and none in NHL 27
    bios.append(bio(5000, 'Gone', 'Home', (1985, 1, 1), 0, 7, proteam=7, contractdollars=900, contractlength=3,
                    contractstatus=0))
    skaters.append({'game_id': 5000, 'c_speed': 60, 'c_passing': 60, 'c_overall': 60, 'c_potential': 1,
                    'c_fighting': 0, 'playerstyle': 9, 'off_defbias': 7, 'pass_carrybias': 7, 'shoot_passbias': 7,
                    'skatingstyle': 3, 'skill_overall': 60})
    bios.append(bio(5001, 'Stale', 'Rights', (1999, 1, 1), 3, 40, proteam=12, contractdollars=300,
                    contractlength=2, contractis2way=1, contractstatus=0))
    skaters.append({'game_id': 5001, 'c_speed': 60, 'c_passing': 60, 'c_overall': 60, 'c_potential': 1,
                    'c_fighting': 0, 'playerstyle': 2, 'off_defbias': 7, 'pass_carrybias': 7, 'shoot_passbias': 7,
                    'skatingstyle': 3, 'skill_overall': 60})
    return {'exhibitionplayerbiotable': bios, 'exhibitionskaterai': skaters, 'exhibitiongoalieai': goalies}


@pytest.fixture()
def nhl19(pack):
    meta = schema_xml(TABLES19)
    return make_db(TABLES19, nhl19_rows(pack), meta)


def test_ratings_written_in_range_style_in_class(pack, nhl19):
    db, schema = nhl19
    players = [dict(p) for p in pack['players']]
    fwd = next(p for p in players if p['pos'] == 'C' and p['league'] == 'nhl')
    fwd['v'] = list(fwd['v'])
    names = pack['fields']['skater']
    fwd['v'][names.index('playerstyle')] = 2  # a defenceman's type on a forward: not written
    fwd['v'][names.index('c_speed')] = 99  # above this roster's c_speed range (0-90): clamped
    found = R.match(db, players)
    assert len(found) == len(players)
    models = {name: R.Model.fit(db[name]) for name in (R.SKATERS, R.GOALIES)}
    todo = R.plan_nhl27(db, schema, found, pack['fields'], models)
    assert todo and not {f for _t, _r, f, _o, _n in todo} & {'c_overall', 'c_potential', 'skatingstyle'}
    R.apply(db, todo)
    bios = {r['game_id']: r for r in db[R.BIOS].rows()}
    for name in (R.SKATERS, R.GOALIES):
        meta = schema.by_name(name)
        for r in db[name].rows():
            for f in meta.fields.values():
                assert f.low <= r[f.name] <= f.high, (name, f.name, r[f.name])
            b = bios[r['game_id']]
            assert r['playerstyle'] in N.STYLE_CLASS[N.style_class(b['position'])]
    by_name = {(b['firstname'], b['lastname']): gid for gid, b in bios.items()}
    gid = by_name[(fwd['first'], fwd['last'])]
    row = next(r for r in db[R.SKATERS].rows() if r['game_id'] == gid)
    assert row['c_speed'] == 90 and row['playerstyle'] == 9  # clamped; NHL 19's own type kept
    for p in players:
        if p is fwd:
            continue
        gid = by_name[(p['first'], p['last'])]
        table = R.GOALIES if p['pos'] == 'G' else R.SKATERS
        row = next(r for r in db[table].rows() if r['game_id'] == gid)
        meta = schema.by_name(table).fields.values()
        rng = {f.name: (f.low, f.high) for f in meta}
        want = {k: min(max(v, rng[k][0]), rng[k][1]) for k, v in N.values_of(p, pack['fields']).items()
                if k not in N.NOT_WRITTEN}
        assert {k: row[k] for k in want} == want  # NHL 27's values (clamped), its type within the class
        inputs = (row['c_gsh'], row['c_5hole']) if table == R.GOALIES else (row['c_speed'], row['c_passing'])
        assert abs(row['skill_overall'] - sum(inputs) / 2) <= 1  # the summary follows NHL 19's line


def test_contracts_after_the_update(pack, nhl19):
    db, _schema = nhl19
    bios = db[U.BIOS]
    before = {r['game_id']: r for r in bios.rows()}
    deals = list(pack['contracts'])
    # a deal under a birth date typo: kept for the same club, not for another
    club = next(d for d in deals if d['org'] == 'TOR')
    deals.remove(club)
    deals.append(dict(club, birth=[club['birth'][0], club['birth'][1], 1 + club['birth'][2] % 27]))
    other = next(d for d in deals if d['org'] == 'BOS')
    deals.remove(other)
    deals.append(dict(other, org='MTL', birth=[other['birth'][0] - 1, 1, 1]))
    counts = U._contracts(db, dict(pack, contracts=deals), 2026, 0, set())
    after = {r['game_id']: r for r in bios.rows()}
    name_of = {(b['firstname'], b['lastname']): gid for gid, b in after.items()}
    for d in deals:
        b = after[name_of[(d['first'], d['last'])]]
        if d is deals[-1]:
            continue  # the other club's deal: estimated instead
        terms = N.terms(d)
        assert {k: b[k] for k in terms} == terms and b['contractstatus'] == 0
        if d['last'] == 'Hand':
            assert b['proteam'] == calendar.SLOTS[d['org']] and b['team'] == 40  # a minor leaguer's organisation
    b = after[name_of[(other['first'], other['last'])]]
    assert b['contractlength'] in (1, 3) and b['contractdollars'] in (170, 205)
    gone = after[5000]  # an NHL club player NHL 27 does not have: one season at the lowest salary (41)
    assert (gone['contractdollars'], gone['contractlength'], gone['contractstatus']) == (170, 1, 0)
    stale = after[5001]  # an AHL player with 2018 rights and no NHL 27 deal: no contract
    assert {k: stale[k] for k in N.NO_CONTRACT} == N.NO_CONTRACT
    fa = next(gid for gid, r in before.items() if r['team'] == -1)
    assert after[fa] == before[fa]  # free agents keep what they have
    assert counts['deals'] >= 300 and counts['minors'] == 1 and counts['cleared'] == 1 and counts['estimated'] >= 2
    meta = _schema.by_name(U.BIOS)
    for r in bios.rows():
        for f in meta.fields.values():
            if not f.is_string:
                assert f.low <= r[f.name] <= f.high


def test_estimates():
    young, old = N.estimate(20), N.estimate(30, 900_000, 1_075_000)
    assert (young['contractdollars'], young['contractlength'], young['contractismultiyear']) == (205, 3, 1)
    assert (old['contractdollars'], old['contractlength'], old['contractismultiyear']) == (180, 1, 0)


# --- where the app finds the pack, the update's lines ----------------------------------------------
def test_app_finds_the_pack(tmp_path, monkeypatch, pack):
    from overtime_roster.app import sources
    cache = tmp_path / 'cache'
    path = cache / N.PACK_NAME
    N.write_pack(pack, str(path))
    monkeypatch.delenv(sources.NHL27_ENV, raising=False)
    found, where = sources.nhl27_pack(str(cache))
    assert where == str(path) and found['players'] == json.loads(json.dumps(pack['players']))
    other = tmp_path / 'elsewhere.json.gz'
    N.write_pack(dict(pack, generated='env'), str(other))
    monkeypatch.setenv(sources.NHL27_ENV, str(other))
    assert sources.nhl27_pack(str(cache))[0]['generated'] == 'env'
    monkeypatch.setenv(sources.NHL27_ENV, 'off')
    assert sources.nhl27_pack(str(cache)) == (None, '')


def test_update_passes_the_pack_and_reports_it(tmp_path, monkeypatch, pack):
    from overtime_roster.app import sources, update
    monkeypatch.setenv(sources.NHL27_ENV, str(tmp_path / N.PACK_NAME))
    N.write_pack(pack, str(tmp_path / N.PACK_NAME))
    g = update.gather_files(2026, str(tmp_path / 'nocache'), os.path.join(DATA, 'nhl_rosters_20262027.json'),
                            os.path.join(DATA, 'nhl_schedule_20262027.json'))
    assert g.nhl27 and len(g.nhl27['players']) == len(pack['players']) and g.sources['nhl27']
    assert g.active is None  # no data pack: rosterupdate.apply adds NHL 27's players itself
    rep = U.Report({}, [], [], 120, {}, [], [], [], nhl27={'rated': 5, 'values': 100, 'styles': 2, 'deals': 3,
                                                           'minors': 1, 'estimated': 2, 'cleared': 4})
    lines = update.details(U.Plan(), rep, lambda team, table: str(team))
    text = {what: new for what, _old, new in lines}
    assert text['NHL 27 ratings and player types'] == '5 player(s), 100 value(s), 2 type(s)'
    assert text['EA ratings'] == '20 value(s)'
    assert text['Contracts (NHL 27)'] == '3 club, 1 minors' and text['2018 NHL contracts ended'] == '4 player(s)'


def test_overlay_rows_take_nhl27_after_the_fixed_years():
    fixed_rises, fixed_lowest = overlay.FIXED_RISES, overlay.FIXED_LOWEST
    assert overlay.CAP_2026 == overlay.NHL27_CAP
    for k in (0, 1):
        assert overlay.ROWS_2026[k][fixed_rises:] == overlay.NHL27_ROWS[k][fixed_rises:]
    assert overlay.ROWS_2026[2][fixed_lowest:] == overlay.NHL27_ROWS[2][fixed_lowest:]
    assert overlay.ROWS_2026[2][:4] == (850, 900, 950, 1000)
    assert all(e - lo == 175 for e, lo in zip(overlay.ROWS_2026[3], overlay.ROWS_2026[2]))
    assert overlay.ROWS_2026[3] == overlay.NHL27_ROWS[3]  # NHL 27 keeps the same ELC rule
    assert overlay.ROWS_2026[1][1:3] == (9500, 14000)  # caps $113.5M / $127.5M for 2027-28 / 2028-29 stay


@pytest.mark.skipif(not os.path.isfile(LOCAL_PACK), reason='no local NHL 27 pack (tools/build_datapack.py)')
def test_local_pack_matches_the_overlay_and_d1():
    pack = N.load(LOCAL_PACK)
    assert pack is not None
    assert (pack['money']['floor'], pack['money']['cap']) == overlay.NHL27_CAP
    assert [tuple(r) for r in pack['money']['rows']] == list(overlay.NHL27_ROWS)
    with open(os.path.join(DATA, 'nhl_rosters_20262027.json'), encoding='utf-8') as f:
        reals = json.load(f)
    rate = N.match_rate(reals, pack['players'])
    assert rate['rate'] >= 0.95, rate['misses']


# --- the whole update on the default roster --------------------------------------------------------
def fake_pack(reals, schema):
    """An NHL 27-like pack for NHL.com's players, values across the whole range, some types of the wrong class."""
    rnd = random.Random(19)
    sk = sorted(f.name for f in schema.by_name(R.SKATERS).fields.values() if f.name.startswith('c_'))
    gk = sorted(f.name for f in schema.by_name(R.GOALIES).fields.values() if f.name.startswith('c_'))
    fields = {'skater': sk + list(N.EXTRA_SKATER), 'goalie': gk + list(N.EXTRA_GOALIE)}
    players, deals = [], []
    for i, r in enumerate(reals):
        pos = {'L': 'LW', 'R': 'RW'}.get(r['position'], r['position'])
        y, m, d = (int(x) for x in r['birth'].split('-'))
        names = fields['goalie' if pos == 'G' else 'skater']
        v = []
        for n in names:
            if n == 'playerstyle':
                v.append(rnd.randrange(0, 11) if pos != 'G' else rnd.randrange(0, 3))
            elif n.endswith('bias'):
                v.append(rnd.randrange(16))
            elif n in ('c_fighting', 'c_consistency', 'c_paddledown'):
                v.append(rnd.randrange(2))
            else:
                v.append(rnd.choice((36, 99, rnd.randrange(36, 100))))
        debut = -1 if i % 25 == 0 else 125 - i % 12  # NHL 27's raw years; a few never played pro
        pro = {'yearprodebut': debut, 'yearfirstsigned': debut, 'yearwaivereligible': -1 if debut == -1 else debut + 3,
               'progamesplayedcareer': 0 if debut == -1 else 70 * (126 - debut),
               'nhlgamesplayedcareer': 0 if debut == -1 else 60 * (126 - debut), 'rookie': int(debut >= 125),
               'expansiondraftstatus': 0 if debut == -1 or debut >= 124 else 3}
        players.append({'first': r['first'], 'last': r['last'], 'birth': [y, m, d], 'pos': pos, 'team': r['team'],
                        'league': 'nhl', 'v': v, 'pro': pro})
        if i % 10:
            deals.append({'first': r['first'], 'last': r['last'], 'birth': [y, m, d], 'pos': pos, 'org': r['team'],
                          'cap': 850_000 + 5000 * rnd.randrange(2500), 'years': 1 + i % 8, 'two_way': 0})
    return {'format': N.FORMAT, 'fields': fields, 'players': players, 'contracts': deals,
            'money': {'floor': 769, 'cap': 1040, 'rows': [list(r) for r in overlay.NHL27_ROWS]}}


@pytest.mark.game
def test_update_with_nhl27_on_the_default_roster(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    with open(os.path.join(DATA, 'nhl_rosters_20262027.json'), encoding='utf-8') as f:
        reals = json.load(f)
    pack = fake_pack(reals, schema)
    todo = U.plan(db, reals)
    rep = U.apply(db, schema, todo, start_year=2026, active=[], nhl27=pack)
    n = rep.nhl27
    assert n['rated'] >= 0.95 * len(reals) and n['values'] == rep.ratings and n['styles'] > 0
    assert n['deals'] >= 0.85 * len(reals) and n['estimated'] > 0 and n['cleared'] > 0
    assert rep.problems == [] and U.check(db, schema, None, 2026) == []
    for name in (U.BIOS, *U.AI.values(), U.ROSTER, U.CUSTOM_ROSTER):
        meta = schema.by_name(name)
        rng = [(f.name, f.low, f.high) for f in meta.fields.values() if not f.is_string and f.high > f.low]
        for r in db[name].rows():
            for f, lo, hi in rng:
                assert lo <= r[f] <= hi, (name, f, r[f])
    state = U.State(db)
    bios = {r['game_id']: r for r in db[U.BIOS].rows()}
    stock = tdb.Database.parse(raw, schema)
    changed = 0
    for name in U.AI.values():
        before = {r['game_id']: r['playerstyle'] for r in stock[name].rows()}
        for r in db[name].rows():
            if r['playerstyle'] != before.get(r['game_id']):  # a type written: of the player's class
                changed += 1
                assert r['playerstyle'] in N.STYLE_CLASS[N.style_class(bios[r['game_id']]['position'])]
    assert changed >= n['styles'] // 2
    club = [b for b in bios.values() if b['team'] in U.NHL or b['team'] == T.SEATTLE]
    assert club and all(b['contractdollars'] >= 170 and b['contractlength'] >= 1 and b['contractstatus'] == 0
                        for b in club)
    assert all(b['proteam'] == -1 for b in bios.values() if b['team'] == -1 and b['game_id'] < U.SPECIAL_IDS)
    # with NHL 27's lists every free agent nobody lists left the pool, whatever his age; Kessel's All-Star and
    # national team records did not keep him there
    kessel = next(gid for gid, b in bios.items() if (b['firstname'], b['lastname']) == ('Phil', 'Kessel'))
    assert not set(state.pis_of[kessel]) & state.free
    assert len(state.free) <= sum(1 for _pi, _n, _t in rep.signed) + 60
    # every free agent is unsigned (no 2018 deal kept) and none plays for an NHL club under another record; the
    # stock list has four players of other clubs (Jurco, Bentivoglio...), left as EA ships them
    stock_free = U.State(stock).free
    free = [(pi, state.bio(pi)) for pi in state.free]
    assert all(b[f] == v for _pi, b in free for f, v in N.NO_CONTRACT.items())
    assert all(b['team'] == -1 or pi in stock_free for pi, b in free)
    assert not {b['game_id'] for _pi, b in free} & {b['game_id'] for b in club}
    assert not [b['game_id'] for b in bios.values() if b['contractstatus'] == 0 and b['proteam'] == -1
                and b['team'] != T.SEATTLE]  # no stock pattern; Seattle's are free agents before the game sees them
    # NHL 27's pro history, years on the game's clock: club players have a pro debut, so the Franchise expansion
    # draft has players to take from every team
    assert n['pro_history'] >= 0.9 * len(reals)
    shift = T.year_shift(2026)
    names = collections.Counter((p['first'], p['last']) for p in pack['players'])  # two Sebastian Ahos
    pro_of = {(p['first'], p['last']): p['pro'] for p in pack['players'] if names[(p['first'], p['last'])] == 1}
    seen = 0
    for b in club:
        pro = pro_of.get((b['firstname'].strip(), b['lastname'].strip()))
        if pro and pro['yearprodebut'] != -1:
            seen += 1
            assert (b['yearprodebut'], b['yearwaivereligible']) == (pro['yearprodebut'] - shift,
                                                                    pro['yearwaivereligible'] - shift)
            assert (b['nhlgamesplayedcareer'], b['expansiondraftstatus']) == (pro['nhlgamesplayedcareer'],
                                                                             pro['expansiondraftstatus'])
    assert seen >= 0.8 * len(club)
    assert sum(b['yearprodebut'] == -1 for b in club) <= len(club) // 20 + 30


@pytest.mark.game
def test_update_rebuilds_the_ahl_clubs_from_nhl27(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    with open(os.path.join(DATA, 'nhl_rosters_20262027.json'), encoding='utf-8') as f:
        reals = json.load(f)
    pack = fake_pack(reals, schema)
    teams = {r['teamname']: r['index'] for r in db[T.TEAMS].rows() if r['league'] == U.AHL_LEAGUE}
    marlies, binghamton = teams['Toronto Marlies'], teams['Binghamton Devils']
    hershey = next(i for name, i in teams.items() if name.startswith('Hershey'))  # 'Hershey Bears' and a stray byte
    stock = U.State(db)
    own = [stock.bio(pi) for pi, e in stock.entry.items() if e == (U.ROSTER, marlies)]
    nhlcom = {(r['first'], r['last']) for r in reals}
    own = [b for b in own if (b['firstname'].strip(), b['lastname'].strip()) not in nhlcom]
    kept = [b for b in own if b['position'] != U.GOALIE][:7] + [b for b in own if b['position'] == U.GOALIE][:1]
    extra, where = [], []  # NHL.com-like rows for fake_pack, (league, team) of each

    def add(first, last, birth, pos, league, team):
        extra.append({'first': first, 'last': last, 'birth': birth, 'position': pos, 'team': team})
        where.append((league, team))
    for b in kept:  # 2018 Marlies NHL 27 still has there
        add(b['firstname'].strip(), b['lastname'].strip(), R._birth(b), 'GCLRDG'[b['position'] + 1], 'ahl',
            'Toronto Marlies')
    for i in range(6):  # new Marlies, two with Toronto deals (prospects)
        add('Marlie', letters(i), f'2004-0{1 + i}-1{i}', 'CDLRDC'[i], 'ahl', 'Toronto Marlies')
    for i in range(4):  # Toronto's ECHL players: the Marlies fill from them first
        add('Growler', letters(i), f'2003-0{1 + i}-0{1 + i}', 'GCDL'[i], 'echl', 'Newfoundland Growlers')
    for i in range(28):  # too many Bears: trimmed to AHL_SIZE[1]
        add('Bear', letters(i), f'2002-{1 + i % 12:02d}-{1 + i:02d}', 'G' if i < 3 else 'CLRDD'[i % 5], 'ahl',
            'Hershey Bears')
    for i in range(21):  # Binghamton's slot plays as NHL 27's Abbotsford Canucks
        add('Canuck', letters(i), f'2001-{1 + i % 12:02d}-{1 + i:02d}', 'G' if i < 2 else 'CLRDD'[i % 5], 'ahl',
            'Abbotsford Canucks')
    nhl = reals[0]  # on an NHL club: stays there although NHL 27 lists him in the AHL
    add(nhl['first'], nhl['last'], nhl['birth'], nhl['position'], 'ahl', 'Hershey Bears')
    more = fake_pack(extra, schema)['players']
    for p, (league, team) in zip(more, where):
        p['league'], p['team'] = league, team
    pack['players'] += more
    deals = [p for p in more if p['first'] in ('Marlie', 'Growler')][:2] + [p for p in more if p['first'] == 'Growler']
    pack['contracts'] += [{'first': p['first'], 'last': p['last'], 'birth': p['birth'], 'pos': p['pos'], 'org': 'TOR',
                           'cap': 900_000, 'years': 2, 'two_way': 1} for p in deals]
    rep = U.apply(db, schema, U.plan(db, reals), start_year=2026, active=[], nhl27=pack)
    n = rep.nhl27
    assert n['ahl_teams'] == 3 and n['ahl_created'] > 0 and n['ahl_trimmed'] > 0 and n['ahl_filled'] > 0
    assert rep.problems == [] and U.check(db, schema, None, 2026) == [] and U.key_problems(db) == []
    state = U.State(db)
    bios = {r['game_id']: r for r in db[U.BIOS].rows()}
    on = collections.defaultdict(list)
    for pi, (table, team) in state.entry.items():
        if table == U.ROSTER and team not in U.SHADOW_TEAMS:
            on[team].append(state.bio(pi))
    for team in (marlies, hershey, binghamton):
        pos = collections.Counter(b['position'] == U.GOALIE for b in on[team])
        assert U.AHL_SIZE[0] <= len(on[team]) <= U.AHL_SIZE[1] and pos[True] >= 2 and pos[False] >= 18, team
    club_teams = {r['index'] for r in db[T.TEAMS].rows() if r['league'] in U.CLUB_LEAGUES}
    clubs = collections.Counter(b['game_id'] for team, bs in on.items() if team in club_teams for b in bs)
    assert not [g for g, k in clubs.items() if k > 1]  # nobody on two club rosters
    names = lambda team: {(b['firstname'], b['lastname']) for b in on[team]}  # noqa: E731
    assert {(b['firstname'], b['lastname']) for b in kept} <= names(marlies)
    assert {('Growler', letters(i)) for i in range(4)} <= names(marlies)  # Toronto's ECHL players filled in
    assert len({ln for fn, ln in names(binghamton) if fn == 'Canuck'}) == 21
    assert len({ln for fn, ln in names(hershey) if fn == 'Bear'}) == U.AHL_SIZE[1]
    assert (nhl['first'], nhl['last']) not in names(hershey)
    # Toronto's prospects carry Toronto as their NHL club, the others no deal (contractstatus -1, a stock pattern)
    tor = U.target_of('TOR')[1]
    signed = {(p['first'], p['last']) for p in deals}
    for b in on[marlies] + on[hershey] + on[binghamton]:
        if (b['firstname'], b['lastname']) in signed:
            assert b['proteam'] == tor and b['contractstatus'] == 0
        elif b['firstname'] in ('Marlie', 'Bear', 'Canuck'):
            assert b['proteam'] == -1 and b['contractstatus'] == -1
    # the 2018 Marlies NHL 27 does not list left with no club and no deal (as the retired free agents)
    gone = [b for b in own if b['game_id'] not in {x['game_id'] for x in on[marlies]}]
    assert gone
    for b in gone:
        now = bios[b['game_id']]
        if now['team'] == -1:
            assert all(now[f] == v for f, v in N.NO_CONTRACT.items())


def test_nhl27_club_players_nhlcom_leaves_out_are_added():
    real = [{'first': 'Sidney', 'last': 'Crosby', 'birth': '1987-08-07', 'position': 'C', 'team': 'PIT'}]
    players = [{'first': 'Sidney', 'last': 'Crosby', 'birth': [1987, 8, 7], 'pos': 'C', 'team': 'PIT', 'league': 'nhl'},
               {'first': 'Mathew', 'last': 'Barzal', 'birth': [1997, 5, 26], 'pos': 'C', 'hand': 'R', 'height': 72,
                'weight': 190, 'team': 'NYI', 'league': 'nhl'},  # injured reserve: not on NHL.com's list
               {'first': 'Kevin', 'last': 'Traded', 'birth': [1995, 1, 1], 'pos': 'D', 'team': 'BOS', 'league': 'nhl'},
               {'first': 'Ahl', 'last': 'Prospect', 'birth': [2005, 1, 1], 'pos': 'D', 'team': 'Bridgeport', 'league': 'ahl'}]
    deal = lambda p, org: {'first': p['first'], 'last': p['last'], 'birth': p['birth'], 'org': org}  # noqa: E731
    pack = {'players': players, 'contracts': [deal(players[0], 'PIT'), deal(players[1], 'NYI'),
                                              deal(players[2], 'TOR'), deal(players[3], 'NYI')]}
    out, extra = U.with_nhl27_clubs(real, pack)
    assert [(r['first'], r['last'], r['team'], r['birth'], r['position']) for r in extra] == [
        ('Mathew', 'Barzal', 'NYI', '1997-05-26', 'C')]
    assert out == real + extra and round(extra[0]['height']) == 183


@pytest.mark.game
def test_update_keeps_injured_nhl27_players_on_the_clock(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    with open(os.path.join(DATA, 'nhl_rosters_20262027.json'), encoding='utf-8') as f:
        reals = json.load(f)
    pack = fake_pack(reals, schema)  # deals at their clubs for all but every tenth
    injured = [r for i, r in enumerate(reals) if i % 10 == 3 and r['team'] != 'SEA'][:30]
    listed = [r for r in reals if r not in injured]
    rep = U.apply(db, schema, U.plan(db, listed, nhl27=pack), start_year=2026, active=[], nhl27=pack)
    assert rep.problems == [] and U.key_problems(db) == []
    shift = T.year_shift(2026)
    hurt = [pack['players'][reals.index(r)] for r in injured]
    found = U._nhl27_matches(db, hurt, shift, 'team')  # names as the update matches them ('Jacob' Middleton is Jake)
    assert len(found) == len(hurt)
    for p, brow, _level in found:  # on his club, a deal, his age on the game's clock
        b = db[U.BIOS].row(brow)
        r = injured[hurt.index(p)]
        assert b['year'] == int(r['birth'][:4]) - 1900 - shift
        assert b['team'] == U.target_of(r['team'])[1] and b['contractstatus'] == 0 and b['contractlength'] >= 1
    # every bio NHL 27 matched is on the clock: a second run moves nobody
    assert U._clock_nhl27(db, U._nhl27_matches(db, pack['players'], shift, 'team'), shift) == set()
    # the expansion career's deals: one season longer, free agents untouched
    before = {r['game_id']: r for r in db[U.BIOS].rows()}
    n = U.expansion_contracts(db)
    after = {r['game_id']: r for r in db[U.BIOS].rows()}
    longer = [g for g in before if after[g]['contractlength'] == min(15, before[g]['contractlength'] + 1)
              and before[g]['contractlength']]
    assert n == len(longer) > 0.9 * len(listed)
    assert all(after[g] == before[g] for g in before if before[g]['proteam'] == -1 and before[g]['team'] != T.SEATTLE)
    seattle = [g for g in before if before[g]['team'] == T.SEATTLE and before[g]['contractstatus'] == 0]
    assert seattle and all(after[g]['contractlength'] == before[g]['contractlength'] + 1 for g in seattle)


# --- real equipment (A4) ------------------------------------------------------------------------
SKATER_EQ = [('game_id', 16, 0, 65535), ('stick', 10, 0, 1023), ('skatesocktuck', 3, 0, 7), ('pantstypecode', 3, 0, 7),
             ('stickbladetapecolor', 24, 0, 16777215), ('stickshafttapecolor', 24, 0, 16777215)]
GOALIE_EQ = [('game_id', 16, 0, 65535), ('neckprotector', 1, 0, 1)]
TAPE = N.DEFAULT_TAPE


def gear_tables():
    tables = dict(TABLES27, exhibitionskaterequipment=('SKEQ', SKATER_EQ), exhibitiongoalieequipment=('GLEQ', GOALIE_EQ))
    rows = nhl27_rows()
    sk, gl = [], []
    for b in rows['exhibitionplayerbiotable']:
        g = b['game_id']
        if b['position'] == 4:
            gl.append({'game_id': g, 'neckprotector': int(g % 3 == 0)})
        elif g == 101:    # curated: a stick of his own, a default tuck and pants are his choice
            sk.append({'game_id': g, 'stick': 36, 'skatesocktuck': 0, 'pantstypecode': 0, 'stickbladetapecolor': TAPE,
                       'stickshafttapecolor': 0x202020})
        elif g == 102:    # a default stick, but a real tuck and black blade tape
            sk.append({'game_id': g, 'stick': 221, 'skatesocktuck': 3, 'pantstypecode': 1,
                       'stickbladetapecolor': 0x202020, 'stickshafttapecolor': TAPE})
        else:             # the default row
            sk.append({'game_id': g, 'stick': 221, 'skatesocktuck': 0, 'pantstypecode': 0, 'stickbladetapecolor': TAPE,
                       'stickshafttapecolor': TAPE})
    rows.update(exhibitionskaterequipment=sk, exhibitiongoalieequipment=gl)
    return tables, rows


def test_gear_is_real_per_value_not_per_row():
    tables, rows = gear_tables()
    db, _schema = make_db(tables, rows, schema_xml(tables))
    gear = N.gear_part(db)
    assert gear['skater'][101] == {'skatesocktuck': 0, 'pantstypecode': 0, 'stickbladetapecolor': TAPE,
                                   'stickshafttapecolor': 0x202020}                # a curated row says its zeros
    assert gear['skater'][102] == {'skatesocktuck': 3, 'pantstypecode': 1, 'stickbladetapecolor': 0x202020}
    assert 103 not in gear['skater'] and 104 not in gear['skater']                 # the default row says nothing
    assert {g for g, v in gear['goalie'].items()} == {g for g in gear['goalie'] if g % 3 == 0}
    assert all(v == {'neckprotector': 1} for v in gear['goalie'].values())         # a guard is never taken off


def test_pack_players_carry_their_gear():
    tables, rows = gear_tables()
    db, _schema = make_db(tables, rows, schema_xml(tables))
    pack = N.build(db, money_brk(), source={'nhl_game.db': 'x'}, generated='2026-10-28')
    by_gid = {(p['first'], p['last']): p for p in pack['players']}
    gids = {b['game_id']: (b['firstname'].strip(), b['lastname'].strip()) for b in rows['exhibitionplayerbiotable']}
    assert by_gid[gids[102]]['gear']['skatesocktuck'] == 3
    assert 'gear' not in by_gid[gids[103]]
    assert sum('gear' in p for p in pack['players']) >= 2
    assert N.build(db, money_brk(), source={'nhl_game.db': 'x'}, generated='2026-10-28') == pack   # still deterministic
    plain = N.build(make_db(TABLES27, nhl27_rows(), schema_xml(TABLES27))[0], money_brk())
    assert not any('gear' in p for p in plain['players'])                           # no equipment tables: no gear


@pytest.mark.game
def test_real_gear_goes_through_the_equipment_checks(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    bios = db[U.BIOS]
    sk = next(i for i in range(bios.count) if bios.get(i, 'position') != 4 and bios.get(i, 'game_id') < U.SPECIAL_IDS)
    gl = next(i for i in range(bios.count) if bios.get(i, 'position') == 4 and bios.get(i, 'game_id') < U.SPECIAL_IDS)
    gid = {i: bios.get(i, 'game_id') for i in (sk, gl)}
    eq = {i: U.EQ.row_of(db, gid[i], 'goalie' if i == gl else 'skater') for i in (sk, gl)}
    db[U.EQUIPMENT[False]].set(eq[sk], 'skatesocktuck', 2)
    found = [({'pos': 'C', 'gear': {'skatesocktuck': 3, 'pantstypecode': 6, 'stickbladetapecolor': 0x202020}}, sk, 'x'),
             ({'pos': 'G', 'gear': {'neckprotector': 1}}, gl, 'x'),
             ({'pos': 'C'}, sk + 1, 'x')]                                         # no gear: left alone
    out = U._real_gear(db, found)
    t = db[U.EQUIPMENT[False]]
    assert (t.get(eq[sk], 'skatesocktuck'), t.get(eq[sk], 'stickbladetapecolor')) == (3, 0x202020)
    assert t.get(eq[sk], 'pantstypecode') != 6                                     # pants 6: the game has no such length
    assert db[U.EQUIPMENT[True]].get(eq[gl], 'neckprotector') == 1
    assert out['gear'] == 2 and out['gear_values'] >= 3 and out['gear_skipped'] == 1
    assert U._real_gear(db, found)['gear_values'] == 0                             # a second pass changes nothing


@pytest.mark.game
def test_update_rebuilds_hockeyallsvenskan_from_nhl27(game_db):
    """The league-8 slots take NHL 27's clubs: AIK stays AIK with its NHL 27 players, Bjorkloven's slot becomes
    Ostersunds IK (the pack's club it has no 2018 twin for); a slot the pack has no club for is left alone."""
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    with open(os.path.join(DATA, 'nhl_rosters_20262027.json'), encoding='utf-8') as f:
        reals = json.load(f)
    pack = fake_pack(reals, schema)
    teams = {r['teamname']: r['index'] for r in db[T.TEAMS].rows() if r['league'] == U.ALLSVENSKAN}
    aik, bjor, pantern = teams['AIK'], teams['IF Bjorkloven'], teams['IK Pantern']
    stock_pantern = [e for e in U.State(db).entry.values() if e == (U.ROSTER, pantern)]
    extra, where = [], []

    def add(first, last, birth, pos, team):
        extra.append({'first': first, 'last': last, 'birth': birth, 'position': pos, 'team': team})
        where.append(team)
    for i in range(23):
        add('Aik', letters(i), f'2000-{1 + i % 12:02d}-{1 + i:02d}', 'G' if i < 2 else 'CLRDD'[i % 5], 'AIK')
    for i in range(22):
        add('Ostersund', letters(i), f'2001-{1 + i % 12:02d}-{1 + i:02d}', 'G' if i < 2 else 'CLRDD'[i % 5],
            'Ostersunds IK')
    more = fake_pack(extra, schema)['players']
    for p, team in zip(more, where):
        p['league'], p['team'] = 'allsvenskan', team
    pack['players'] += more
    rep = U.apply(db, schema, U.plan(db, reals), start_year=2026, active=[], nhl27=pack)
    n = rep.nhl27
    assert n['allsv_teams'] == 2 and n['allsv_renamed'] == 1 and n['allsv_created'] > 0
    assert rep.problems == [] and U.check(db, schema, None, 2026) == [] and U.key_problems(db) == []
    row = {r['index']: r for r in db[T.TEAMS].rows()}
    assert (row[bjor]['teamname'], row[bjor]['nickname'], row[bjor]['cityname'], row[bjor]['abbrname']) == (
        'Ostersunds IK', 'Ostersunds IK', 'Ostersund', 'OST')
    assert row[aik]['teamname'] == 'AIK' and row[pantern]['teamname'] == 'IK Pantern'   # no pack club: unchanged
    state = U.State(db)
    on = collections.defaultdict(list)
    for pi, (table, team) in state.entry.items():
        if table == U.ROSTER and team in (aik, bjor, pantern):
            on[team].append(state.bio(pi))
    for team in (aik, bjor):
        pos = collections.Counter(b['position'] == U.GOALIE for b in on[team])
        assert U.AHL_SIZE[0] <= len(on[team]) <= U.AHL_SIZE[1] and pos[True] >= 2 and pos[False] >= 18, team
    assert {b['firstname'] for b in on[bjor]} == {'Ostersund'} and {b['firstname'] for b in on[aik]} == {'Aik'}
    assert len(on[pantern]) == len(stock_pantern)


def test_team_key_folds_accents_and_fuzzy_clubs_pair_one_franchise_once():
    assert U._team_key('Frölunda HC') == U._team_key('Frolunda HC') == 'frolundahc'
    teams = {1: {'cityname': 'Frölunda', 'nickname': 'Indians'}, 2: {'cityname': 'Hamilton', 'nickname': 'Bulldogs'},
             3: {'cityname': 'Mississauga', 'nickname': 'Steelheads'}, 4: {'cityname': 'Kootenay', 'nickname': 'Ice'}}
    names = {U._team_key(n): n for n in ('Frolunda HC', 'Brantford Bulldogs', 'Brampton Steelheads', 'Penticton Vees')}
    got = U._fuzzy_clubs(teams, {1, 2, 3, 4}, names)
    assert {s: names[k] for s, k in got.items()} == {1: 'Frolunda HC', 2: 'Brantford Bulldogs',
                                                    3: 'Brampton Steelheads'}   # Kootenay has no club
    assert U._fuzzy_clubs(teams, {2}, {U._team_key('Brantford Bulldogs'): 'Brantford Bulldogs',
                                       U._team_key('Bulldogs Two'): 'Bulldogs Two'}) == {}   # two hits: none


@pytest.mark.game
def test_update_rebuilds_the_other_club_leagues_from_nhl27(game_db):
    """SHL: the slot of a club NHL 27 spells differently takes its players and name (Frolunda Indians -> Frolunda HC);
    a slot with no NHL 27 club keeps its 2018 roster; a player the AHL took from the ECHL is not taken back."""
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    with open(os.path.join(DATA, 'nhl_rosters_20262027.json'), encoding='utf-8') as f:
        reals = json.load(f)
    pack = fake_pack(reals, schema)
    teams = {r['teamname']: r['index'] for r in db[T.TEAMS].rows() if r['league'] == 2}
    froelunda = next(i for name, i in teams.items() if name.startswith('Fr'))
    mora = teams['Mora IK']
    stock_mora = len([e for e in U.State(db).entry.values() if e == (U.ROSTER, mora)])
    extra = [{'first': 'Frolunda', 'last': letters(i), 'birth': f'2000-{1 + i % 12:02d}-{1 + i:02d}',
              'position': 'G' if i < 2 else 'CLRDD'[i % 5], 'team': 'Frolunda HC'} for i in range(23)]
    more = fake_pack(extra, schema)['players']
    for p in more:
        p['league'], p['team'] = 'shl', 'Frolunda HC'
    pack['players'] += more
    rep = U.apply(db, schema, U.plan(db, reals), start_year=2026, active=[], nhl27=pack)
    n = rep.nhl27
    assert n['shl_teams'] == 1 and n['shl_renamed'] == 1 and n['shl_created'] > 0
    assert rep.problems == [] and U.check(db, schema, None, 2026) == [] and U.key_problems(db) == []
    row = {r['index']: r for r in db[T.TEAMS].rows()}
    assert row[froelunda]['teamname'] == row[froelunda]['nickname'] == 'Frolunda HC' and row[mora]['teamname'] == 'Mora IK'
    state = U.State(db)
    on = collections.defaultdict(list)
    for pi, (table, team) in state.entry.items():
        if table == U.ROSTER and team in (froelunda, mora):
            on[team].append(state.bio(pi))
    assert {b['firstname'] for b in on[froelunda]} == {'Frolunda'} and len(on[froelunda]) == 23
    assert len(on[mora]) == stock_mora
