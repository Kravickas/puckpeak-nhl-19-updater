"""Today's NHL in the default roster: NHL.com 2026-27 rosters (tests/data, NHL.com 2026-10-02) and calendar."""
import json
import os
import re

import pytest

from overtime_core import calendar, rosterupdate as U, tdb
from overtime_core import nhl27 as N
from overtime_core import teams as T

DATA = os.path.join(os.path.dirname(__file__), 'data')
UNSIGNED = dict(N.NO_CONTRACT, team=-1)


def real_rosters():
    with open(os.path.join(DATA, 'nhl_rosters_20262027.json'), encoding='utf-8') as f:
        return json.load(f)


def season():
    with open(os.path.join(DATA, 'nhl_schedule_20262027.json'), encoding='utf-8') as f:
        return [tuple(g) for g in json.load(f)]


def test_targets():
    assert U.target_of('TOR') == (U.ROSTER, 27) and U.target_of('ARI') == U.target_of('UTA') == (U.ROSTER, 22)
    assert U.target_of('SEA') == (U.CUSTOM_ROSTER, T.SEATTLE)
    with pytest.raises(U.UpdateError):
        U.target_of('QUE')


def test_clock_years_on_the_2018_clock():
    ovi = {'first': 'Alex', 'last': 'Ovechkin', 'birth': '1985-09-17'}
    out = U._clock_years(ovi, {}, 8, draftyear=104)  # drafted 2004, the data pack doesn't know it
    assert out == {'year': 77, 'month': 8, 'day': 16, 'draftyear': 96}
    assert U._clock_years(ovi, {}, 8, draftyear=96) == {'year': 77, 'month': 8, 'day': 16}  # second run
    assert 'draftyear' not in U._clock_years(ovi, {}, 8)  # undrafted stays undrafted
    drafts = {('alex', 'ovechkin'): (0, 0, 0, 2004, 1, 1)}
    assert U._clock_years(ovi, drafts, 8, draftyear=104)['draftyear'] == 96


def test_fixture_covers_the_league():
    real = real_rosters()
    assert {p['team'] for p in real} == set(calendar.SLOTS)
    assert all(p['first'] and p['last'] and p['birth'] for p in real)


class Rows:
    def __init__(self, rows):
        self.rows_, self.count = rows, len(rows)

    def get(self, i, name):
        return self.rows_[i][name]


def test_main_record_is_the_clubs():
    # game_id: (bio team, [(playerindex, roster table or 'FA' or None, team)])
    people = {
        1: (30, [(10, U.ROSTER, 140), (11, U.ROSTER, 30), (12, U.ROSTER, 603)]),  # Haula: Team Finland first
        2: (104, [(20, U.ROSTER, 142), (21, U.ROSTER, 104)]),  # a DEL player with a Team Germany record
        3: (-1, [(30, U.ROSTER, 140), (31, 'FA', -1)]),  # a free agent with a national team record
        4: (T.SEATTLE, [(40, U.ROSTER, U.MIRROR), (41, U.CUSTOM_ROSTER, T.SEATTLE)]),
        5: (140, [(50, U.ROSTER, 140)]),
        6: (-1, [(60, U.ROSTER, 31), (61, None, -1)]),  # All-Star record only
        7: (5, [(70, U.ROSTER, 216), (71, U.ROSTER, 5)]),  # Top Prospects record, then the club's
    }
    rows = {U.ROSTER: [], U.CUSTOM_ROSTER: [], U.FREE: []}
    for _gid, (_team, recs) in people.items():
        for pi, table, team in recs:
            if table == 'FA':
                rows[U.FREE].append({'playerindex': pi})
            elif table:
                rows[table].append({'playerindex': pi, 'team': team})
    db = {name: Rows(r) for name, r in rows.items()}
    db[U.BIOS] = Rows([{'game_id': gid, 'team': team} for gid, (team, _r) in people.items()])
    db[U.PLAYERS] = Rows([{'table': 0, 'playerid': gid, 'index': pi}
                          for gid, (_t, recs) in people.items() for pi, _tb, _tm in recs])
    state = U.State(db)
    assert {gid: state.main_pi(gid) for gid in people} == {1: 11, 2: 21, 3: 31, 4: 41, 5: 50, 6: 60, 7: 71}
    assert state.main_pi(99) is None


def sorted_roster(t):
    rows = [(t.get(i, 'team'), t.get(i, 'key')) for i in range(t.count)]
    return rows == sorted(rows) and len({k for _t, k in rows}) == len(rows)


@pytest.fixture(scope='module')
def updated(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    todo = U.plan(db, real_rosters())
    rating = [{'name': 'Leo Carlsson', 'position': 'C', 'birth': [2004, 12, 26], 'attrs': {'Passing': 90}}]
    report = U.apply(db, schema, todo, rating_rows=rating, games=season(), start_year=2026)
    return raw, schema, db, todo, report


@pytest.mark.game
@pytest.mark.game
def test_a_goalie_is_never_given_to_a_skater(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    state, bios = U.State(db), db[U.BIOS]
    gid = next(g for g, i in state.bio_row.items() if bios.get(i, 'position') == 0 and state.main_pi(g) is not None)
    b = bios.row(state.bio_row[gid])
    who = {'first': b['firstname'], 'last': b['lastname'], 'birth': U._birth(b), 'id': 1, 'team': 'TOR'}
    assert [m for _p, m, _t, _l in U.plan(db, [dict(who, position='C')]).placed] != [None]
    assert [m for _p, m, _t, _l in U.plan(db, [dict(who, position='G')]).placed] == [None]


@pytest.mark.game
def test_the_default_roster_has_no_short_team_and_a_cut_one_is_named(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    assert U.short_teams(db) == []
    state = U.State(db)
    goalies = [pi for pi, e in state.entry.items() if e == (U.ROSTER, 5) and state.bio(pi)['position'] == U.GOALIE]
    t = db[U.ROSTER]
    rows = [i for i in range(t.count) if t.get(i, 'playerindex') in goalies]
    for i in rows[1:]:
        t.set(i, 'team', 400)
    name = next(r['teamname'] for r in db[T.TEAMS].rows() if r['index'] == 5)
    assert U.short_teams(db) == [f'{name} has 1 goalie and {sum(1 for e in state.entry.values() if e == (U.ROSTER, 5)) - len(goalies)} skaters']


def test_a_free_agent_on_a_club_is_named(updated):
    _raw, _schema, db, _todo, _report = updated
    print('both after an update:', U.free_and_on_a_club(db))
    assert U.short_teams(db) == []
    state = U.State(db)
    pi = next(p for p in sorted(state.free) if state.bio(p) is not None and not U.free_and_on_a_club(db).count(
        f"{state.bio(p)['firstname']} {state.bio(p)['lastname']}"))
    b = state.bio(pi)
    club = next(i for i in range(db[U.ROSTER].count) if db[U.ROSTER].get(i, 'team') == 5)
    other = [o for o in state.pis_of[b['game_id']]]
    before = db[U.ROSTER].get(club, 'playerindex')
    db[U.ROSTER].set(club, 'playerindex', other[0])
    try:
        assert f"{b['firstname']} {b['lastname']}" in U.free_and_on_a_club(db)
    finally:
        db[U.ROSTER].set(club, 'playerindex', before)


def test_update_places_every_real_player(updated):
    raw, schema, db, todo, report = updated
    s = todo.summary()
    assert s['players'] == 772 and s['stay'] + s['moves'] + s['new'] == 772
    assert report.problems == [] and report.skipped_lines == []
    assert len(report.created) == s['new'] > 0 and report.ratings > 0
    roster, custom = db[U.ROSTER], db[U.CUSTOM_ROSTER]
    assert sorted_roster(roster) and sorted_roster(custom)
    fa = [db[U.FREE].get(i, 'playerindex') for i in range(db[U.FREE].count)]
    assert fa == sorted(fa) and len(set(fa)) == len(fa)
    state = U.State(db)
    real = real_rosters()
    seattle = [p for p in real if p['team'] == 'SEA']
    on_seattle = [pi for pi, e in state.entry.items() if e == (U.CUSTOM_ROSTER, T.SEATTLE)]
    assert len(on_seattle) == len(seattle) >= 20
    names = {f"{state.bio(pi)['firstname']} {state.bio(pi)['lastname']}" for pi in on_seattle}
    assert names == {f"{p['first']} {p['last']}" for p in seattle}
    utah = [pi for pi, e in state.entry.items() if e == (U.ROSTER, T.UTAH_SLOT)]
    assert len(utah) == sum(p['team'] == 'UTA' for p in real)
    for pi in utah:
        b = state.bio(pi)
        assert (b['team'], b['proteam']) == (T.UTAH_SLOT, T.UTAH_SLOT)
    carlsson = next(pi for pi in state.entry if (state.bio(pi) or {}).get('lastname') == 'Carlsson'
                    and state.bio(pi)['firstname'] == 'Leo')
    b = state.bio(carlsson)
    # born 26 Dec 2004: on the game's clock (league year 2018) 8 years earlier, so the game counts his real age
    assert (b['year'], b['month'], b['day'], b['jersey'], b['position']) == (96, 11, 25, 91, 0)
    assert b['headid'] >= U.GENERIC_HEAD and b['hasportrait'] == 0
    # his own portrait art id (the donor's p<artid> is the donor's face): his game id, which no stock bio uses
    assert b['artid'] == b['game_id'] and b['artid'] in U.NEW_ARTIDS
    new_art = {state.bio(pi)['game_id']: state.bio(pi)['artid'] for pi in state.entry
               if state.bio(pi) and state.bio(pi)['artid'] in U.NEW_ARTIDS}
    assert len(set(new_art.values())) == len(new_art) > 50
    assert U._ai_value(db, b, 'c_passing', None) == 90
    assert T.check(db, schema) == []
    # every NHL.com roster player has the portrait flag, made or matched (the photos pack is made of them)
    # a matched player (Crosby, stock record) gets his birth date on the game's clock too
    crosby = next(p for p in real if (p['first'], p['last']) == ('Sidney', 'Crosby'))
    b = next(state.bio(pi) for pi in state.entry if (state.bio(pi) or {}).get('lastname') == 'Crosby'
             and state.bio(pi)['firstname'] == 'Sidney')
    assert f"{b['year'] + 1900 + T.year_shift(2026):04d}-{b['month'] + 1:02d}-{b['day'] + 1:02d}" == crosby['birth']


@pytest.mark.game
def test_new_players_get_free_regular_ids_in_sorted_tables(updated):
    """New players take ids after the regular ones, below the game's special (56500+) and created (57000+)
    players, and the player tables stay sorted: the default roster with colliding ids crashed the game at boot."""
    raw, schema, db, todo, report = updated
    stock = tdb.Database.parse(raw, schema)
    before = U._used_ids(stock)
    regular_max = max(g for g in before if g < U.SPECIAL_IDS)
    ids = [c['game_id'] for c in report.created]
    assert len(set(ids)) == len(ids) and min(ids) > regular_max and max(ids) < U.SPECIAL_IDS
    assert not set(ids) & before
    for name, key in U.SORTED:
        t = db[name]
        keys = [t.get(i, key) for i in range(t.count)]
        assert keys == sorted(keys) and len(set(keys)) == len(keys), name
    players = db[U.PLAYERS]
    mirror = {r['playerindex'] for r in U._mirror_rows(db)}  # Seattle's Play Now copy has records of its own
    new = [players.row(i) for i in range(players.count)
           if players.get(i, 'playerid') in set(ids) and players.get(i, 'index') not in mirror]
    assert len(new) == len(ids) and all(r['table'] == 0 for r in new)
    old_index = {stock[U.PLAYERS].get(i, 'index') for i in range(stock[U.PLAYERS].count)}
    old_index |= {stock['customplayers'].get(i, 'index') for i in range(stock['customplayers'].count)}
    assert not {r['index'] for r in new} & old_index and max(r['index'] for r in new) < U.SPECIAL_IDS
    for name in ('customplayers', 'customplayerbiotable', 'customskaterai', 'exhibitionresortplayerextras'):
        assert db[name].data == stock[name].data, name  # the special and created players are untouched
    bios = db[U.BIOS]
    rows = {bios.get(i, 'game_id'): i for i in range(bios.count)}
    assert all(bios.row(rows[c['game_id']])['lastname'] in c['name'] for c in report.created)


@pytest.mark.game
def test_update_round_trips_and_runs_once(updated):
    raw, schema, db, todo, report = updated
    blob = db.to_bytes()
    again = tdb.Database.parse(blob, schema)
    assert again.to_bytes() == blob
    second = U.plan(again, real_rosters())
    assert second.summary() == {'players': 772, 'stay': 772, 'moves': 0, 'new': 0, 'releases': 0, 'kept': 0}
    rep = U.apply(again, schema, second, games=season(), start_year=2026)
    assert rep.problems == [] and again.to_bytes() == blob


@pytest.mark.game
def test_empty_expansion_makes_seattle_free_agents(updated):
    raw, schema, db, todo, report = updated
    db = tdb.Database.parse(db.to_bytes(), schema)
    seattle = sorted(pi for pi, e in U.State(db).entry.items() if e == (U.CUSTOM_ROSTER, T.SEATTLE))
    assert U.empty_expansion(db) == seattle and len(seattle) >= 20
    state = U.State(db)
    assert (U.CUSTOM_ROSTER, T.SEATTLE) not in state.entry.values() and set(seattle) <= state.free
    assert all(state.bio(pi)[f] == v for pi in seattle for f, v in UNSIGNED.items())
    stock = tdb.Database.parse(raw, schema)[U.CUSTOM_ROSTER]
    assert db[U.CUSTOM_ROSTER].data == stock.data and sorted_roster(db[U.CUSTOM_ROSTER])  # as the game ships it
    fa = [db[U.FREE].get(i, 'playerindex') for i in range(db[U.FREE].count)]
    assert fa == sorted(fa) and len(set(fa)) == len(fa)
    assert U.empty_expansion(db) == [] and T.check(db, schema) == []


@pytest.mark.game
def test_expansion_free_agents_lists_seattle_and_keeps_it(updated):
    """The expansion career takes its free agents from the default roster: Seattle's players are listed there and
    stay on team 499 with their deals (ws8 s2 / s3)."""
    raw, schema, db, todo, report = updated
    db = tdb.Database.parse(db.to_bytes(), schema)
    bios = [dict(r) for r in db[U.BIOS].rows()]
    seattle = sorted(pi for pi, e in U.State(db).entry.items() if e == (U.CUSTOM_ROSTER, T.SEATTLE))
    assert U.expansion_free_agents(db) == seattle and len(seattle) >= 20
    state = U.State(db)
    assert set(seattle) <= state.free and all(state.entry[pi] == (U.CUSTOM_ROSTER, T.SEATTLE) for pi in seattle)
    assert [dict(r) for r in db[U.BIOS].rows()] == bios
    fa = [db[U.FREE].get(i, 'playerindex') for i in range(db[U.FREE].count)]
    assert fa == sorted(set(fa)) and U.check(db, schema) == []
    blob = db.to_bytes()
    assert U.expansion_free_agents(db) == [] and db.to_bytes() == blob
    assert U.empty_expansion(db) == seattle and U.State(db).free >= set(seattle)  # the expansion draft's copy


@pytest.mark.game
def test_seattle_is_active_exactly_when_it_has_players(updated):
    """Season with the 32-team switch crashed on an inactive Seattle (no team-ratings entry, ws8 run7a)."""
    raw, schema, db, todo, report = updated
    custom = lambda d: d[T.CUSTOM].get(U._seattle_row(d), 'active')
    assert custom(tdb.Database.parse(raw, schema)) == 0  # stock: the empty expansion team
    assert not U.seattle_ready(tdb.Database.parse(raw, schema))
    db = tdb.Database.parse(db.to_bytes(), schema)
    assert custom(db) == 1 and U._seattle_has_players(db) and U.seattle_ready(db)
    assert not [p for p in U.check(db, schema) if 'active' in p]
    db[T.CUSTOM].set(U._seattle_row(db), 'active', 0)  # a custom roster saved before expansion_active
    assert not U.seattle_ready(db)
    db[T.CUSTOM].set(U._seattle_row(db), 'active', 1)
    U.empty_expansion(db)
    assert custom(db) == 0 and not U.seattle_ready(db) and not [p for p in U.check(db, schema) if 'active' in p]
    db[T.CUSTOM].set(U._seattle_row(db), 'active', 1)
    assert [p for p in U.check(db, schema) if 'active' in p] and not U.seattle_ready(db)
    assert U.expansion_active(db) == 0 and custom(db) == 0


@pytest.mark.game
def test_club_players_are_no_free_agents_and_free_agents_have_no_deal(updated):
    raw, schema, db, todo, report = updated
    state, stock = U.State(db), U.State(tdb.Database.parse(raw, schema))
    real = {(p['first'], p['last']): p['team'] for p in real_rosters()}
    gid_of = {(r['firstname'], r['lastname']): r['game_id'] for r in db[U.BIOS].rows()}
    # 2018 Vegas players with a national team record before the Vegas one: that one stays on the national team
    for first, last, national in (('Erik', 'Haula', 140), ('William', 'Karlsson', 152)):
        pis = stock.pis_of[gid_of[(first, last)]]
        main = stock.main_pi(gid_of[(first, last)])
        assert stock.entry[main] == (U.ROSTER, 30) and state.entry[main] == U.target_of(real[(first, last)])
        assert [state.entry[pi] for pi in pis if stock.entry.get(pi) == (U.ROSTER, national)] == [(U.ROSTER, national)]
        assert not set(pis) & state.free
    club = [pi for pi, e in state.entry.items() if e == (U.CUSTOM_ROSTER, T.SEATTLE) or e[0] == U.ROSTER and e[1] in U.NHL]
    ids = {state.bio(pi)['game_id'] for pi in club if state.bio(pi)}
    assert not {pi for gid in ids for pi in state.pis_of[gid]} & state.free
    signed = {pi for pi, _n, _t in report.signed}  # by a minor league club short of players
    released = [state.bio(pi) for pi, _n, _t in todo.releases if pi not in signed]
    released = [b for b in released if b and b['game_id'] not in ids]
    assert len(released) > 400 and all(b[f] == v for b in released for f, v in UNSIGNED.items())
    # stock never has a player under contract (status 0) without an organisation: 25 signings that way crashed
    # the game's SimThread on the Creation Zone save (run ws5-20261018/run1)
    for pi, _n, (table, team) in report.signed:
        b = state.bio(pi)
        assert b['contractstatus'] == -1 or b['proteam'] == team and b['contractlength'] >= 1, (pi, team)
    assert not [r['game_id'] for r in db[U.BIOS].rows() if r['contractstatus'] == 0 and r['proteam'] == -1
                and r['team'] != T.SEATTLE]  # Seattle's: a custom team, no proteam


@pytest.mark.game
def test_old_free_agents_nobody_lists_retire(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    state = U.State(db)
    age = {pi: 2026 - 1900 - state.bio(pi)['year'] for pi in state.free if state.bio(pi)}
    old = sorted(pi for pi, a in age.items() if a >= U.FA_RETIRE_AGE)
    keep = state.bio(old[0])  # still listed somewhere (data pack birth date as it is)
    active = [{'first': keep['firstname'], 'last': keep['lastname'],
               'birth': [keep['year'] + 1900, keep['month'] + 1, keep['day'] + 1]}]
    gone = U.retire_free_agents(db, active, 2026)
    pis = {pi for pi, _n, _a in gone}
    assert old[0] not in pis and pis <= set(old) and len(pis) >= len(old) // 2
    assert all(a >= U.FA_RETIRE_AGE for _pi, _n, a in gone)
    after = U.State(db)
    assert not pis & after.free and old[0] in after.free
    assert {pi for pi, a in age.items() if a < U.FA_RETIRE_AGE} <= after.free  # the young stay
    fa = [db[U.FREE].get(i, 'playerindex') for i in range(db[U.FREE].count)]
    assert fa == sorted(fa)
    assert U.retire_free_agents(db, active, 2026) == []  # a second run retires nobody else


def test_still_playing_reads_every_list():
    pack = {'nhl_last': [{'first': 'A', 'last': 'B', 'birth': [1990, 1, 2]}],
            'leagues': {'ahl': {'teams': [{'players': [{'first': 'C', 'last': 'D', 'birth': [2001, 3, 4]}]}]}},
            'iihf': {'AUT': [{'first': 'E', 'last': 'F', 'birth': [1995, 5, 6]}]}}
    assert [p['last'] for p in U.still_playing(pack)] == ['B', 'D', 'F'] and U.still_playing(None) == []


@pytest.mark.game
def test_update_needs_the_custom_tables(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    online = db.subset('rosterupdate')
    assert U.CUSTOM_ROSTER not in online
    with pytest.raises(U.UpdateError):
        U.apply(online, schema, U.plan(online, real_rosters()))
    added = U.graft_custom(online, db)
    assert U.CUSTOM_ROSTER in online and T.CUSTOM in online and added
    online[T.CUSTOM].set(0, 'teamname', 'changed')
    assert db[T.CUSTOM].get(0, 'teamname') != 'changed'  # copies, not the default's tables


@pytest.mark.game
def test_play_now_seattle_mirrors_team_499(updated):
    """exhibitionteams 399 is Seattle in the NHL league, with team 499's players through records of its own; it stays
    when the expansion team is emptied (the expansion career's start roster), and it is in the online roster
    (rosterupdate savegroup)."""
    from overtime_core import lines
    from overtime_core.roster import Roster
    raw, schema, db, todo, report = updated
    db = tdb.Database.parse(db.to_bytes(), schema)
    teams = db[T.TEAMS]
    row = next(i for i in range(teams.count) if teams.get(i, 'index') == T.SEATTLE_PLAY_NOW)
    sea = teams.row(row)
    assert (sea['cityname'], sea['teamname'], sea['abbrname']) == ('$SEATTLE', 'Kraken', 'SEA')
    assert (sea['league'], sea['leaguegroup'], sea['active'], sea['divisiongroup'], sea['artid']) == (
        T.NHL_LEAGUE, T.NHL_LEAGUE_GROUP, 1, T.PACIFIC, 10499)
    gid = U._record_ids(db)
    custom = db[U.CUSTOM_ROSTER]
    src = [custom.row(i) for i in range(custom.count) if custom.get(i, 'team') == T.SEATTLE]
    mirror = U._mirror_rows(db)
    assert len(mirror) == len(src) >= 20
    assert [gid[r['playerindex']] for r in mirror] == [gid[r['playerindex']] for r in src]
    assert [U._slot_values(r) for r in mirror] == [U._slot_values(r) for r in src]
    assert not {r['playerindex'] for r in mirror} & (set(U.State(db).free) | {r['playerindex'] for r in src})
    assert max(r['playerindex'] for r in mirror) < U.SPECIAL_IDS
    assert lines.check_groups(db, T.SEATTLE_PLAY_NOW) == []
    errors = [i for i in Roster.from_database(db).verify() if i.level == 'error']
    assert errors == [] and U._mirror_problems(db) == []
    # every Seattle player's main record is still his team-499 one (an update plans with it)
    state = U.State(db)
    assert {state.main_pi(gid[r['playerindex']]) for r in mirror} == {r['playerindex'] for r in src}
    # the expansion career's start roster: team 499 empty, team 399 kept, nothing more to do
    U.empty_expansion(db)
    blob = db.to_bytes()
    assert len(U._mirror_rows(db)) == len(src) and U.mirror_seattle(db) == len(src) and db.to_bytes() == blob
    assert U.check(db, schema) == []
    online = db.subset('rosterupdate')
    assert any(online[T.TEAMS].get(i, 'abbrname') == 'SEA' and online[T.TEAMS].get(i, 'active') == 1
               for i in range(online[T.TEAMS].count))
    on = online[U.ROSTER]
    assert sum(on.get(i, 'team') == T.SEATTLE_PLAY_NOW for i in range(on.count)) == len(src)


@pytest.mark.game
def test_mirror_follows_seattle_roster_changes(updated):
    """A player who leaves Seattle loses his Play Now record; one who joins gets a new one; the rest keep theirs."""
    raw, schema, db, todo, report = updated
    db = tdb.Database.parse(db.to_bytes(), schema)
    gid = U._record_ids(db)
    before = {gid[r['playerindex']]: r['playerindex'] for r in U._mirror_rows(db)}
    custom = db[U.CUSTOM_ROSTER]
    rows = [i for i in range(custom.count) if custom.get(i, 'team') == T.SEATTLE]
    gone_pi = custom.get(rows[-1], 'playerindex')
    custom.delete(rows[-1])
    U.mirror_seattle(db)
    after = {U._record_ids(db)[r['playerindex']]: r['playerindex'] for r in U._mirror_rows(db)}
    assert gid[gone_pi] not in after and before[gid[gone_pi]] not in U._record_ids(db)
    assert {g: pi for g, pi in before.items() if g != gid[gone_pi]} == after
    assert U._mirror_problems(db) == []


def test_new_player_artid_skips_taken():
    m = U._Maker.__new__(U._Maker)
    m.used_art, m.next_art = {20641, 20000, 20001}, U.NEW_ARTIDS.start
    assert m.artid(20642) == 20642  # his game id
    assert m.artid(20641) == 20002  # taken: the next free one
    assert m.artid(500) == 20003  # a game id outside the free range (a stock portrait's number)
    m.used_art |= set(U.NEW_ARTIDS)
    with pytest.raises(U.UpdateError):
        m.artid(1)


def test_new_artids_miss_stock_portraits():
    """NEW_ARTIDS holds no stock portrait number (the game index, when it was built on this PC)."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 're', 'dumps', 'nhl19_art.json')
    if not os.path.exists(path):
        pytest.skip('no NHL 19 art index (tools/art_index.py nhl19)')
    with open(path, encoding='utf-8') as f:
        index = json.load(f)
    nums = {int(m.group(1)) for k in index for m in [re.search(r'playerportraits/p(\d+)\.gnf$', k)] if m}
    assert nums and not nums & set(U.NEW_ARTIDS)
