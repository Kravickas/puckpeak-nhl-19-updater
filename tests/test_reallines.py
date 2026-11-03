"""Real lines and captains from the data pack's `lines` part (reallines.py), laid on the default roster and through the
whole update (NHL.com 2026-27 rosters, tests/data)."""
from collections import Counter

import pytest

from overtime_core import lines as L
from overtime_core import reallines as RL
from overtime_core import roster, rosterupdate as U, tdb
from overtime_core.roster import ALTERNATE, CAPTAIN

from test_rosterupdate import real_rosters, season

TEAM = 27           # Toronto's place in exhibitionrostertable
FAKE = 10_000_000   # fake NHL.com ids on the default roster: FAKE + playerindex


def test_part_needs_the_season_and_a_lines_part():
    pack = {'season': 2026, 'lines': {'TOR': {'slots': {}}}}
    assert RL.part(pack, 2026) == pack['lines']
    assert RL.part(pack, 2025) is None
    assert RL.part({'season': 2026}, 2026) is None and RL.part(None, 2026) is None
    assert RL.part({'season': 2026, 'lines': {}}, 2026) is None


def test_the_pack_slots_are_lines_own_slots():
    named = [s for g in RL.REAL_GROUPS.values() for s in g]
    assert len(named) == 52 == len(set(named)) and set(named) <= set(L.SLOTS)


def fresh(game_db):
    raw, schema = game_db
    return tdb.Database.parse(raw, schema)


def holders(db, team, table=L.ROSTER):
    r = db[table]
    rows = [i for i in range(r.count) if r.get(i, 'team') == team]
    return {s: next(r.get(i, 'playerindex') for i in rows if r.get(i, s)) for s in L.SLOTS}


def rows_of(db, team, table=L.ROSTER):
    r = db[table]
    return {r.get(i, 'playerindex'): r.row(i) for i in range(r.count) if r.get(i, 'team') == team}


def shuffled(db, team):
    """A 'real' lineup of the team's dressed 20 that differs from the one the default roster has: the lines in reverse
    order, the pairs in reverse order, the goalies swapped, the second units first."""
    h = holders(db, team)
    real = {}
    for k, j in zip((1, 2, 3, 4), (4, 3, 2, 1)):
        for s in ('lw', 'c', 'rw'):
            real[f'l{k}{s}'] = h[f'l{j}{s}']
    for k, j in zip((1, 2, 3), (3, 2, 1)):
        for s in ('ld', 'rd'):
            real[f'l{k}{s}'] = h[f'l{j}{s}']
    real['g1'], real['g2'] = h['g2'], h['g1']
    for group in ('pp', 'pp4_', 'pk4_', 'pk3_'):
        for s in RL.REAL_GROUPS[{'pp': 'Power play', 'pp4_': 'Power play 4 on 3', 'pk4_': 'Penalty kill',
                                 'pk3_': 'Penalty kill 3 on 5'}[group]]:
            other = s.replace(f'{group}1', f'{group}#').replace(f'{group}2', f'{group}1').replace(f'{group}#',
                                                                                                   f'{group}2')
            real[s] = h[other]
    return {s: FAKE + pi for s, pi in real.items()}


def pis_of(db):
    p = db[L.PLAYERS]
    return {FAKE + p.get(i, 'index'): p.get(i, 'index') for i in range(p.count)}


@pytest.mark.game
def test_real_lines_go_in_group_by_group(game_db):
    db = fresh(game_db)
    wanted = shuffled(db, TEAM)
    assert RL.line_up(db, L.ROSTER, TEAM, wanted, pis_of(db)) == []
    got = holders(db, TEAM)
    rows = rows_of(db, TEAM)
    for s, nhl_id in wanted.items():
        pi = nhl_id - FAKE
        if s in roster.ES_SLOTS and s.endswith(('ld', 'rd')):    # a pair may swap sides: the right shot on the right
            pair = {wanted[s[:-2] + 'ld'] - FAKE, wanted[s[:-2] + 'rd'] - FAKE}
            assert {got[s[:-2] + 'ld'], got[s[:-2] + 'rd']} == pair
            ld, rd = got[s[:-2] + 'ld'], got[s[:-2] + 'rd']
            assert not (handed(db, ld) and not handed(db, rd))
        else:
            assert got[s] == pi, s
    assert L.check_lineup(db, TEAM) == []
    dressed = {pi for pi, r in rows.items() if r[L.DRESSED]}
    assert dressed == {got[s] for s in roster.ES_SLOTS} and len(dressed) == 20
    assert all(got[s] in dressed for g in L.GROUPS if g != L.THREES for s in L.GROUPS[g])


def handed(db, pi):
    bios = db[L.BIOS]
    p = db[L.PLAYERS]
    gid = next(p.get(i, 'playerid') for i in range(p.count) if p.get(i, 'index') == pi and p.get(i, 'table') == 0)
    return next(bios.get(i, 'handedness') for i in range(bios.count) if bios.get(i, 'game_id') == gid) == 1


@pytest.mark.game
def test_a_second_run_writes_nothing(game_db):
    db = fresh(game_db)
    wanted, pis = shuffled(db, TEAM), pis_of(db)
    RL.line_up(db, L.ROSTER, TEAM, wanted, pis)
    writes = []
    setter = lambda table, row, f, v: (writes.append((row, f)), db[table].set(row, f, v))  # noqa: E731
    assert RL.line_up(db, L.ROSTER, TEAM, wanted, pis, setter) == [] and writes == []


@pytest.mark.game
def test_a_group_missing_a_few_players_is_completed(game_db):
    db = fresh(game_db)
    before = holders(db, TEAM)
    wanted = shuffled(db, TEAM)
    wanted['pp1c'] = 1              # nobody on the team: he who holds it now keeps it
    wanted['l2c'] = wanted['l1c']   # one player twice: the first slot stands
    gaps = []
    assert RL.line_up(db, L.ROSTER, TEAM, wanted, pis_of(db), gaps=gaps) == []
    got = holders(db, TEAM)
    assert gaps == ['Lines (1 of 18 filled)', 'Power play (1 of 10 filled)']
    assert all(got[s] == wanted[s] - FAKE for s in RL.REAL_GROUPS['Lines'] if s != 'l2c')
    assert got['l2c'] not in {got[s] for s in RL.REAL_GROUPS['Lines'] if s != 'l2c'}
    assert got['g1'] == before['g2'] and got['g2'] == before['g1']         # the goalies are their own group
    assert L.check_lineup(db, TEAM) == []


@pytest.mark.game
def test_a_group_with_too_many_open_slots_stays_as_dealt(game_db):
    db = fresh(game_db)
    before = holders(db, TEAM)
    wanted = shuffled(db, TEAM)
    for s in RL.REAL_GROUPS['Lines'][:8]:
        wanted[s] = 1
    gaps = []
    assert RL.line_up(db, L.ROSTER, TEAM, wanted, pis_of(db), gaps=gaps) == []
    assert gaps == ['Lines dealt']
    got = holders(db, TEAM)
    assert all(got[s] == before[s] for s in RL.REAL_GROUPS['Lines'])
    assert L.check_lineup(db, TEAM) == []


@pytest.mark.game
def test_a_goalie_in_a_skaters_place_is_an_open_slot(game_db):
    db = fresh(game_db)
    before = holders(db, TEAM)
    wanted = {s: FAKE + pi for s, pi in before.items() if s in RL.REAL_GROUPS['Lines'] + RL.GOALIE_PAIR}
    wanted['l1c'], wanted['g1'] = wanted['g1'], wanted['l1c']
    gaps = []
    assert RL.line_up(db, L.ROSTER, TEAM, wanted, pis_of(db), gaps=gaps) == []
    assert gaps[:2] == ['Lines (1 of 18 filled)', 'Goalies dealt']
    got = holders(db, TEAM)
    assert all(got[s] == before[s] for s in RL.REAL_GROUPS['Lines'] + RL.GOALIE_PAIR)


@pytest.mark.game
def test_nobody_of_the_real_lines_on_the_team_is_refused(game_db):
    db = fresh(game_db)
    before = holders(db, TEAM)
    assert RL.line_up(db, L.ROSTER, TEAM, {s: 1 for s in RL.REAL_GROUPS['Lines']}, pis_of(db)) == \
        ['no group of the real lines has all its players on the team']
    assert holders(db, TEAM) == before


@pytest.mark.game
def test_letters_skaters_only_one_c_three_in_all(game_db):
    db = fresh(game_db)
    h = holders(db, TEAM)
    pis = pis_of(db)
    letters = {str(FAKE + h['l2c']): 'C', str(FAKE + h['l3c']): 'C', str(FAKE + h['g1']): 'A'}
    assert RL.letter(db, L.ROSTER, TEAM, letters, pis)
    marks = {pi: r['captain'] for pi, r in rows_of(db, TEAM).items() if r['captain']}
    assert Counter(marks.values()) == {CAPTAIN: 1, ALTERNATE: 2}
    assert sorted((marks[h['l2c']], marks[h['l3c']])) == [CAPTAIN, ALTERNATE] and h['g1'] not in marks
    assert not RL.letter(db, L.ROSTER, TEAM, {'1': 'C'}, pis)    # nobody of the team: the letters stay
    assert {pi: r['captain'] for pi, r in rows_of(db, TEAM).items() if r['captain']} == marks
    assert [i for i in roster.Roster.from_database(db).verify() if i.level == 'error'] == []


def pack_of(real):
    """A `lines` part from NHL.com's rosters: per club its first 12 forwards, 6 defencemen and 2 goalies in the list's
    order, the units from them, the first forward C and the first defenceman A."""
    by = {}
    for p in real:
        by.setdefault(p['team'], []).append(p)
    out = {}
    for code, ps in sorted(by.items()):
        f = [p['id'] for p in ps if p['position'] in ('C', 'L', 'R')][:12]
        d = [p['id'] for p in ps if p['position'] == 'D'][:6]
        g = [p['id'] for p in ps if p['position'] == 'G'][:2]
        if len(f) < 12 or len(d) < 6 or len(g) < 2:
            continue
        s = {'g1': g[0], 'g2': g[1]}
        for k in range(4):
            s[f'l{k + 1}lw'], s[f'l{k + 1}c'], s[f'l{k + 1}rw'] = f[3 * k], f[3 * k + 1], f[3 * k + 2]
        for k in range(3):
            s[f'l{k + 1}ld'], s[f'l{k + 1}rd'] = d[2 * k], d[2 * k + 1]
        for k in (1, 2):
            a = 3 * (k - 1)
            s.update({f'pp{k}lw': f[a], f'pp{k}c': f[a + 1], f'pp{k}rw': f[a + 2], f'pp{k}ld': d[2 * k - 2],
                      f'pp{k}rd': d[2 * k - 1]})
            s.update({f'pp4_{k}lw': f[a], f'pp4_{k}c': f[a + 1], f'pp4_{k}ld': d[2 * k - 2], f'pp4_{k}rd': d[2 * k - 1]})
            s.update({f'pk4_{k}lw': f[a + 6], f'pk4_{k}c': f[a + 7], f'pk4_{k}ld': d[2 * k], f'pk4_{k}rd': d[2 * k + 1]
                      if k == 1 else d[1]})
            s.update({f'pk3_{k}c': f[a + 7], f'pk3_{k}ld': d[2 * k], f'pk3_{k}rd': d[2 * k + 1] if k == 1 else d[1]})
        out[code] = {'date': '2026-10-01', 'slots': s, 'letters': {str(f[1]): 'C', str(d[0]): 'A'}}
    return out


@pytest.fixture(scope='module')
def real_updated(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    todo = U.plan(db, real_rosters())
    part = pack_of(real_rosters())
    report = U.apply(db, schema, todo, games=season(), start_year=2026, real_lines=part)
    return db, todo, report, part


@pytest.mark.game
def test_the_update_lays_the_real_lines_on_every_club(real_updated):
    db, todo, report, part = real_updated
    assert report.problems == []
    real = report.real
    assert sorted(real['lined']) == sorted(part) and real['refused'] == {} and real['date'] == '2026-10-01'
    assert sorted(real['lettered']) == sorted(part)
    ids = {p['id']: pi for p, pi, _to, _l in todo.placed if pi is not None}
    for code in part:
        table, team = U.target_of(code)
        assert L.check_lineup(db, team, table) == [], code
        h = holders(db, team, table)
        want = part[code]['slots']
        for s in ('l1c', 'l2lw', 'l4rw', 'pp1c', 'pk4_1c'):
            if want[s] in ids:
                assert h[s] == ids[want[s]], (code, s)
        marks = Counter(r['captain'] for r in rows_of(db, team, table).values() if r['captain'])
        assert marks == {CAPTAIN: 1, ALTERNATE: 2}, code
        goalies = {h['g1'], h['g2']}
        assert not any(r['captain'] for pi, r in rows_of(db, team, table).items() if pi in goalies)
    assert U._mirror_problems(db) == []
    sea = {r['playerindex']: r['captain'] for r in rows_of(db, U.T.SEATTLE, U.CUSTOM_ROSTER).values()}
    assert sorted(v for v in sea.values() if v) == [CAPTAIN, ALTERNATE, ALTERNATE]


