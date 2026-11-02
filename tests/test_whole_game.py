"""The whole-game Update (v0.40.0): the data pack's club rosters and calendars (clubdata.py, leaguecal.py), the national
teams, the record room the leagues need and the clubs that take over a stale slot (rosterupdate.py)."""
import pytest

from overtime_core import clubdata, leaguecal as L, rosterupdate as U, tdb
from overtime_core import teams as T


def row(first, last, birth, league='shl', team='A', pos='C'):
    return {'first': first, 'last': last, 'birth': birth, 'pos': pos, 'league': league, 'team': team, 'v': [70, 71]}


NHL27 = {'fields': {'skater': ['c_overall', 'c_speed'], 'goalie': ['c_overall', 'g_x']},
         'players': [row('Ann', 'Stay', [2000, 1, 1], team='Old'), row('Bo', 'Gone', [2001, 1, 1]),
                     row('Cy', 'Other', [2002, 1, 1], 'ahl', 'Z')]}
PACK = {'leagues': {
    'shl': {'teams': [{'full': 'New Club', 'players': [
        {'first': 'Ann', 'last': 'Stay', 'birth': [2000, 1, 1], 'pos': 'F'},
        {'first': 'Di', 'last': 'Fresh', 'birth': [2003, 1, 1], 'pos': 'G', 'height_cm': 190, 'weight_kg': 90}]}]},
    'chl': {'teams': [{'full': 'Ohl Club', 'league_id': 9, 'players': [
        {'first': 'Ed', 'last': 'Kid', 'birth': [2008, 1, 1], 'pos': 'D'}]}]},
    'norway': {'teams': [{'full': 'Oslo', 'players': [{'first': 'Fy', 'last': 'No', 'birth': [2000, 1, 1], 'pos': 'D'}]}]}}}


def test_a_feed_moves_the_players_nhl27_keeps_their_ratings():
    by = {p['last']: p for p in clubdata.merged(PACK, NHL27)['players']}
    assert (by['Stay']['league'], by['Stay']['team'], by['Stay']['v']) == ('shl', 'New Club', [70, 71])
    assert by['Fresh']['v'] == [0, 0] and by['Fresh']['pos'] == 'G' and by['Fresh']['league'] == 'shl'
    assert by['Kid']['league'] == 'ohl'
    assert by['Gone']['league'] is None             # no longer listed there: he is no retirement
    assert by['Other']['league'] == 'ahl' and 'No' not in by
    assert clubdata.merged(None, NHL27) is None and clubdata.merged(PACK, None) is None


def test_a_player_a_feed_lists_twice_is_one_player():
    twice = {'first': 'Di', 'last': 'Twice', 'birth': [2003, 1, 1], 'pos': 'F'}
    pack = {'leagues': {'shl': {'teams': [{'full': 'One', 'short': 'Ett', 'abbr': 'ONE', 'players': [twice, twice]},
                                          {'full': 'Two', 'players': [twice]}]}}}
    got = clubdata.merged(pack, NHL27)
    assert [p['team'] for p in got['players'] if p['last'] == 'Twice'] == ['One']
    assert got['towns'] == {'One': ('Ett', 'ONE')}


def test_pack_schedules_name_their_clubs():
    pack = {'season': 2026, 'leagues': {'chl': {'teams': [{'slot': 7, 'full': 'Seven'}, {'slot': 8, 'full': 'Eight'}]}},
            'schedules': {'ohl': [['2026-09-20', 7, 8], ['2026-09-21', 8, 'Guest']], 'norway': [['2026-09-20', 7, 8]],
                          'whl': [['2026-09-20', 7, 99]]}}
    assert L.pack_games(pack, 2026) == {'ohl': [('2026-09-20', 'Seven', 'Eight'), ('2026-09-21', 'Eight', 'Guest')]}
    assert L.pack_games(pack, 2027) == {} and L.pack_games(None, 2026) == {}


def test_a_game_of_a_club_without_a_place_goes():
    games = [('2026-09-20', 'A', 'B'), ('2026-09-21', 'B', 'A'), ('2026-09-22', 'A', 'Guest')]
    assert sorted(r[1:] for r in L.other_rows(games, {'A': 0, 'B': 1})) == [(0, 1), (1, 0)]


@pytest.fixture(scope='module')
def db_of(game_db):
    raw, schema = game_db
    return lambda: tdb.Database.parse(raw, schema)


def test_a_spare_slot_plays_the_fullest_calendar_not_a_guest(db_of):
    db = db_of()
    rows = sorted((r for r in db[T.TEAMS].rows() if r['league'] == 12), key=lambda r: r['index'])
    names = [r['teamname'] for r in rows[1:]]
    games = [('2026-09-20', n, names[(i + 1) % len(names)]) for i, n in enumerate(names)]
    games += [('2026-09-21', 'New Club', n) for n in names[:6]] + [('2026-09-22', names[0], '- A Guest -')]
    places = U._calendar_places(db, 'qmjhl', games)
    assert places['New Club'] == 0 and '- A Guest -' not in places


def test_a_stale_slot_becomes_a_club_without_one(db_of):
    db = db_of()
    rows = sorted((r for r in db[T.TEAMS].rows() if r['league'] == 13), key=lambda r: r['index'])
    pos = ['C'] * 12 + ['D'] * 6 + ['G'] * 2
    players = [row(f'Kid{chr(97 + i)}', 'Wilder', [2008, 1, 1 + i], 'whl', 'Nowhere Wild', p) for i, p in enumerate(pos)]
    for r in rows[1:]:
        players += [row('Xa', f"Own{r['index']}x{i}", [2008, 2, 1 + i], 'whl', r['teamname'], p) for i, p in enumerate(pos)]
    pack = {'fields': {'skater': ['c_overall'], 'goalie': ['c_overall']}, 'players': [dict(p, v=[60]) for p in players],
            'towns': {'Nowhere Wild': ('Nowhere', 'NOW')}}
    counts, changed = U.rebuild_league(db, pack, 0, 13, 'whl', {}, 'whl', (20, 38), True, (), False, True)
    now = next(r for r in db[T.TEAMS].rows() if r['index'] == rows[0]['index'])
    assert (now['teamname'], now['cityname'], now['abbrname']) == ('Nowhere Wild', 'Nowhere', 'NOW')
    assert counts['whl_teams'] == len(rows) and rows[0]['index'] in changed


def test_a_town_comes_from_the_pack_never_from_the_words_of_a_name(db_of):
    t = db_of()[T.TEAMS]
    row0 = t.row(0)['index']
    for name, town, abbr, whole in (('Motor Ceske Budejovice', 'Budejovice', 'MOT', True), ('Motor Brno', 'Brno', None, False)):
        U._rename_club(t, row0, name, whole, {name: (town, 'MOT')})
        got = next(r for r in t.rows() if r['index'] == row0)
        assert got['cityname'] == town and (abbr is None or got['abbrname'] == abbr)
    U._rename_club(t, row0, 'Tahoe Knight Monsters', True)
    assert next(r for r in t.rows() if r['index'] == row0)['cityname'] == 'Tahoe'
    keep = next(r for r in t.rows() if r['index'] == row0)
    U._rename_club(t, row0, 'HC Some Long Name', True)          # no town known: the slot's stay
    now = next(r for r in t.rows() if r['index'] == row0)
    assert (now['cityname'], now['abbrname']) == (keep['cityname'], keep['abbrname'])


def test_unused_players_go_for_room_and_nothing_else(db_of):
    db = db_of()
    state, bios = U.State(db), db[U.BIOS]
    free = [bios.get(i, 'game_id') for i in range(bios.count) if bios.get(i, 'team') == -1
            and bios.get(i, 'game_id') < U.SPECIAL_IDS
            and not any(p in state.entry or p in state.free for p in state.pis_of.get(bios.get(i, 'game_id'), ()))]
    listed, before = free[0], bios.count
    gone = U.drop_unused(db, {listed})
    assert gone > 0 and bios.count == before - gone
    gids = {bios.get(i, 'game_id') for i in range(bios.count)}
    assert listed in gids
    state = U.State(db)
    assert all(state.bio(pi) is not None for pi in state.entry if state.entry[pi][0] == U.ROSTER)
    for name in (*U.AI.values(), *U.EQUIPMENT.values()):
        assert {db[name].get(i, 'game_id') for i in range(db[name].count)} <= gids
    assert U.drop_unused(db, {listed}) == 0        # nothing left to take


def test_a_national_squad_creates_who_the_roster_lacks(db_of):
    db = db_of()
    keeper = {'first': 'New', 'last': 'Keeper', 'pos': 'G', 'num': 30, 'shoots': 'L', 'birth': [2000, 1, 1],
              'height_cm': 185, 'weight_kg': 85}
    goalies = [keeper, dict(keeper, last='Backup', num=31, birth=[2000, 2, 2])]
    fresh = [{'first': 'Fresh', 'last': f'Skater{chr(97 + i)}', 'pos': 'F' if i < 12 else 'D', 'num': 40 + i,
              'shoots': 'L', 'birth': [2001, 1, 1 + i], 'height_cm': 180, 'weight_kg': 80} for i in range(18)]
    counts, changed = U.rebuild_national(db, {'CAN': goalies + fresh}, 0)
    slot = U._national_slots(db)[U._team_key('Canada')]
    assert changed == {slot} and counts['national_created'] == 20 and counts['national_teams'] == 1
    roster, state = db[U.ROSTER], U.State(db)
    on = [roster.row(i) for i in range(roster.count) if roster.get(i, 'team') == slot]
    assert len(on) == 20 and {state.bio(r['playerindex'])['lastname'] for r in on} >= {'Keeper', 'Backup'}


def test_russia_is_the_best_russians_and_a_team_gets_letters(db_of):
    db = db_of()
    assert U.team_russia(db)
    slot = U._national_slots(db)[U._team_key(U.RUSSIA)]
    roster, state = db[U.ROSTER], U.State(db)
    on = [i for i in range(roster.count) if roster.get(i, 'team') == slot]
    assert len(on) == sum(U.RUSSIA_SHAPE.values())
    assert all(state.bio(roster.get(i, 'playerindex'))['intlcountry'] == U.COUNTRY['RUS'] for i in on)
    for i in on:
        roster.set(i, 'captain', 0)
    assert U.give_captains(db) >= 1
    assert sum(1 for i in on if roster.get(i, 'captain')) == 3
    assert U.give_captains(db) == 0
