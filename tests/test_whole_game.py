"""The whole-game Update (v0.40.0): the data pack's club rosters and calendars (clubdata.py, leaguecal.py), the national
teams, the record room the leagues need and the clubs that take over a stale slot (rosterupdate.py)."""
import pytest

from overtime_core import clubdata, leaguecal as L, lines, nhlcom, reallines as RL, roster as RO, rosterupdate as U, tdb
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


def test_a_spare_club_on_a_slot_gives_way_to_a_club_of_the_list(db_of):
    pos = ['C'] * 12 + ['D'] * 6 + ['G'] * 2
    for waiting, kept in ((True, False), (False, True)):
        db = db_of()
        rows = sorted((r for r in db[T.TEAMS].rows() if r['league'] == 13), key=lambda r: r['index'])
        players = []
        if waiting:
            players = [row(f'Kid{chr(97 + i)}', 'Wilder', [2008, 1, 1 + i], 'whl', 'Nowhere Wild', p) for i, p in enumerate(pos)]
        for r in rows:
            players += [row('Xa', f"Own{r['index']}x{i}", [2008, 2, 1 + i], 'whl', r['teamname'], p) for i, p in enumerate(pos)]
        pack = {'fields': {'skater': ['c_overall'], 'goalie': ['c_overall']}, 'players': [dict(p, v=[60]) for p in players],
                'towns': {'Nowhere Wild': ('Nowhere', 'NOW')}, 'spare': {rows[0]['teamname']}}
        U.rebuild_league(db, pack, 0, 13, 'whl', {}, 'whl', (20, 38), True, (), False, True)
        now = next(r for r in db[T.TEAMS].rows() if r['index'] == rows[0]['index'])
        assert (now['teamname'] == rows[0]['teamname']) is kept and (now['teamname'] == 'Nowhere Wild') is waiting


def club_of_the_list(db_of, league=13, tag='whl'):
    """(db, slot, feed) of a club rebuilt from its own list: numbers from 10, the first its C, the next two A's."""
    db = db_of()
    rows = sorted((r for r in db[T.TEAMS].rows() if r['league'] == league), key=lambda r: r['index'])
    pos = ['C', 'LW', 'RW'] * 4 + ['D'] * 6 + ['G'] * 2
    club = rows[1]['teamname']
    players = [dict(row(f'Kid{chr(97 + i)}', 'Wilder', [2008, 1, 1 + i], tag, club, p),
                    feed={'num': 10 + i, 'pos': p[0], 'height_cm': 200, 'weight_kg': 100, 'shoots': 'R',
                          'letter': {0: 'C', 1: 'A', 2: 'A'}.get(i)}) for i, p in enumerate(pos)]
    for r in rows:
        if r['index'] != rows[1]['index']:
            players += [row('Xa', f"Own{r['index']}x{i}", [2008, 2, 1 + i], tag, r['teamname'], p) for i, p in enumerate(pos)]
    pack = {'fields': {'skater': ['c_overall'], 'goalie': ['c_overall']}, 'players': [dict(p, v=[60 + 19 - (i % 20)]) for i, p in enumerate(players)]}
    feed = {}
    U.rebuild_league(db, pack, 0, league, tag, {}, tag, (20, 38), True, (), False, True, feed)
    return db, rows[1]['index'], feed


def on_club(db, slot):
    state = U.State(db)
    return {state.bio(r['playerindex'])['firstname']: (r, state.bio(r['playerindex'])) for r in db[U.ROSTER].rows() if r['team'] == slot}


def test_a_clubs_own_list_gives_numbers_size_and_hand(db_of):
    db, slot, feed = club_of_the_list(db_of)
    assert feed[slot]['club'] and feed[slot]['tag'] == 'whl' and sorted(feed[slot]['letters'].values()) == ['A', 'A', 'C']
    team = on_club(db, slot)
    r, b = team['Kida']
    assert (r['jersey'], b['jersey'], b['height'], b['weight'], b['handedness']) == (10, 10, 79 - U.HEIGHT_BASE, 220 - U.WEIGHT_BASE, 1)
    assert team['Kidt'][1]['position'] == U.POSITION['G']


def test_a_club_plays_its_real_lines_and_wears_its_own_letters(db_of):
    db, slot, feed = club_of_the_list(db_of)
    lines.build(db, slot)
    kid = lambda i: [f'Kid{chr(97 + i)}', 'Wilder', 2008]  # noqa: E731
    wanted = {f'l{n + 1}{p}': kid(n * 3 + i) for n in range(4) for i, p in enumerate(('rw', 'lw', 'c'))}
    wanted |= {f'l{n + 1}{p}': kid(12 + n * 2 + i) for n in range(3) for i, p in enumerate(('ld', 'rd'))}
    club = feed[slot]['club']
    got = U._club_finish(db, feed, {club: wanted})
    team = on_club(db, slot)
    assert got == {'club_lined': 1, 'club_refused': {}} and team['Kidc'][0]['l1c']
    assert (team['Kida'][0]['captain'], team['Kidb'][0]['captain']) == (RO.CAPTAIN, RO.ALTERNATE)


def test_a_national_player_nobody_rates_gets_the_estimate_of_his_team(db_of):
    db = db_of()
    bios = db[U.BIOS]
    table = U.AI[False]
    models = {table: type('Same', (), {'predict': staticmethod(lambda row: {})})}
    rows = {db[table].get(i, 'game_id'): i for i in range(db[table].count)}
    skaters = [g for g in (bios.get(i, 'game_id') for i in range(bios.count)) if g in rows][:2]
    born = {g: ('FIN', f'Name {g}', 2000) for g in skaters}
    want = U.estimate.national(bios.get(U.State(db).bio_row[skaters[1]], 'position'), 'FIN', 26, f'Name {skaters[1]}')
    was = db[table].row(rows[skaters[0]])
    assert U._estimate_national(db, born, {skaters[0]}, models, 2026) == 1
    assert db[table].row(rows[skaters[0]]) == was                                       # rated: left alone
    got = db[table].row(rows[skaters[1]])
    assert {f: got[f] for f in want} == want


def test_a_list_without_letters_gives_them_to_the_best_dressed(db_of):
    db, slot, _feed = club_of_the_list(db_of)
    lines.build(db, slot)
    RL.club_letters(db, U.ROSTER, slot, {})
    worn = [r['captain'] for r, _b in on_club(db, slot).values() if r['captain']]
    assert sorted(worn) == sorted([RO.CAPTAIN, RO.ALTERNATE, RO.ALTERNATE])


def test_nhl_coms_player_page_says_where_he_plays():
    got = nhlcom.landing_player({'playerId': 7, 'firstName': {'default': 'Max'}, 'lastName': {'default': 'Domi'}, 'birthDate': '1995-03-02',
                                 'sweaterNumber': 11, 'position': 'C', 'shootsCatches': 'L', 'currentTeamAbbrev': 'TOR', 'isActive': True})
    assert (got['id'], got['first'], got['last'], got['team'], got['active']) == (7, 'Max', 'Domi', 'TOR', True)
    assert nhlcom.landing_player({'playerId': 8})['team'] is None


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
    bios = db[U.BIOS]
    russians = {bios.get(i, 'game_id'): 'RUS' for i in range(bios.count)
                if bios.get(i, 'intlcountry') == U.COUNTRY['RUS']}
    assert U.fill_national(db, russians) >= 1
    slot = U._national_slots(db)[U._team_key(U.RUSSIA)]
    roster, state = db[U.ROSTER], U.State(db)
    on = [i for i in range(roster.count) if roster.get(i, 'team') == slot]
    assert 20 <= len(on) <= U.NATIONAL_ROOM
    assert all(state.bio(roster.get(i, 'playerindex'))['intlcountry'] == U.COUNTRY['RUS'] for i in on)
    for i in on:
        roster.set(i, 'captain', 0)
    assert U.give_captains(db) >= 1
    assert sum(1 for i in on if roster.get(i, 'captain')) == 3
    assert U.give_captains(db) == 0
