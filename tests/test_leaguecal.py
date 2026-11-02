"""The AHL and Liiga calendars (overtime_core/leaguecal.py): feed parsing, the AHL farm-team mapping, the tables'
rows, apply and check on the game's database, and the offline copy the app ships
(overtime_roster/assets/leaguecal.json: HockeyTech season 94 and liiga.fi season 2027, read 2026-10-28)."""
import json

import pytest

from overtime_core import calendar as C
from overtime_core import leaguecal as L
from overtime_core import tdb
from overtime_roster.app import update


@pytest.fixture(scope='module')
def copy():
    return L.load_snapshot(update.LEAGUES_COPY, 2026)


def nhl_slots():
    """AHL place = NHL slot (a stand-in for ahl_slots), SEA the expansion place."""
    return dict(C.SLOTS)


def test_feeds_parse_to_dated_games_in_order():
    ahl = {'SiteKit': {'Schedule': [
        {'game_id': '9', 'date_played': '2026-10-03', 'home_team_code': 'CV', 'visiting_team_code': 'SD'},
        {'game_id': '7', 'date_played': '2026-10-03', 'home_team_code': 'HAM', 'visiting_team_code': 'TOR'},
        {'game_id': '8', 'date_played': '2026-10-02', 'home_team_code': 'BEL', 'visiting_team_code': 'HAM'}]}}
    assert L.ahl_games(ahl) == [('2026-10-02', 'BEL', 'HAM'), ('2026-10-03', 'HAM', 'TOR'), ('2026-10-03', 'CV', 'SD')]
    liiga = [{'id': 2, 'start': '2026-09-01T15:30:00Z', 'homeTeam': {'teamName': 'Jukurit',
              'gameStartDateTime': '2026-09-01T18:30:00+03:00'}, 'awayTeam': {'teamName': 'HPK'}},
             {'id': 1, 'start': '2026-09-01T21:30:00Z', 'homeTeam': {'teamName': 'Kärpät'}, 'awayTeam': {'teamName': 'TPS'}}]
    assert L.liiga_games(liiga) == [('2026-09-01', 'Kärpät', 'TPS'), ('2026-09-01', 'Jukurit', 'HPK')]
    assert L.ahl_games({}) == [] and L.liiga_games(None) == []


def test_every_ahl_club_has_one_nhl_parent():
    assert sorted(L.AHL_PARENT.values()) == sorted(C.SLOTS) and len(L.AHL_PARENT) == 32
    assert L.AHL_PARENT['CV'] == 'SEA' and L.AHL_PARENT['HAM'] == 'NYI' and L.AHL_PARENT['CHI'] == 'CAR'


def test_the_offline_copy_is_the_whole_2026_27_season(copy):
    assert len(copy['ahl']) == 1152 and len(copy['liiga']) == 544
    assert copy['ahl'][0][0] == '2026-10-02' and copy['ahl'][-1][0] == '2027-04-11'
    assert {c for _d, h, a in copy['ahl'] for c in (h, a)} == set(L.AHL_PARENT)
    assert {c for _d, h, a in copy['liiga'] for c in (h, a)} == set(L.LIIGA_SLOTS) | set(L.LIIGA_NO_PLACE)
    with open(update.LEAGUES_COPY, encoding='utf-8') as f:
        assert json.load(f)['credit'] == L.AHL_CREDIT
    assert L.load_snapshot(update.LEAGUES_COPY, 2027) == {} and L.load_snapshot('no/such/file.json', 2026) == {}


def test_ahl_rows_32_keep_every_game_and_31_fold_coachella_valley(copy):
    r32 = L.ahl_rows(copy['ahl'], nhl_slots(), 32)
    assert len(r32) == 1152 and set(C.per_team(r32).values()) == {72}
    r31 = L.ahl_rows(copy['ahl'], nhl_slots(), 31)
    assert len(r31) == 1116 and set(C.per_team(r31).values()) == {72} and L.AHL_EXPANSION not in C.per_team(r31)
    assert [g[0] for g in r31] == sorted(g[0] for g in r31)
    with pytest.raises(C.CalendarError, match='no NHL parent'):
        L.ahl_rows([('2026-10-02', 'XYZ', 'CV')], nhl_slots())


def test_liiga_rows_leave_out_the_clubs_without_a_place(copy):
    rows = L.liiga_rows(copy['liiga'])
    counts = C.per_team(rows)
    assert len(rows) == 420 and set(counts.values()) == {56} and sorted(counts) == list(range(15))
    with pytest.raises(C.CalendarError, match='no Liiga place'):
        L.liiga_rows([('2026-09-01', 'Hockey Club', 'TPS')])


@pytest.mark.game
def test_apply_and_check_on_the_game_database(game_db, copy):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    nhl = db['nhl32schedule'].body_bytes()
    slots = L.ahl_slots(db)
    assert slots['CAR'] == 4 and slots['SEA'] == L.AHL_EXPANSION    # Carolina's farm: the game's Charlotte place
    assert sorted(v for k, v in slots.items() if k != 'SEA') == list(range(31))
    expected = L.apply(db, schema, copy)
    assert {k: (v['games'], v['per_team'], v['teams']) for k, v in expected.items()} == {
        L.AHL32: (1152, (72, 72), 32), L.AHL31: (1116, (72, 72), 31), L.LIIGA: (420, (56, 56), 15)}
    assert C.check(db, schema, expected, 2026) == []
    assert db['nhl32schedule'].body_bytes() == nhl
    _d, home, away = copy['ahl'][0]     # Oct 2, Hamilton at Belleville: NYI's farm place at OTT's
    assert C.read(db[L.AHL32])[0] == (9, 1, slots[L.AHL_PARENT[home]], slots[L.AHL_PARENT[away]])
    blob = db.to_bytes()
    again = tdb.Database.parse(blob, schema)
    assert again.to_bytes() == blob and C.check(again, schema, expected, 2026) == []


@pytest.mark.game
def test_apply_writes_nothing_when_it_cannot(game_db, copy):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    before = db.to_bytes()
    with pytest.raises(C.CalendarError, match='do not fit'):
        L.apply(db, schema, {'ahl': copy['ahl'], 'liiga': copy['liiga'] * 2})   # 840 Liiga rows, room 480
    t = db['exhibitionteams']
    row = next(i for i in range(t.count) if t.get(i, 'index') == C.SLOTS['CAR'])
    t.set(row, 'ahlaffiliate', -1)
    with pytest.raises(C.CalendarError, match='no AHL farm team'):
        L.apply(db, schema, copy)
    t.set(row, 'ahlaffiliate', 39)
    assert db.to_bytes() == before


def test_gather_leagues_live_first_then_the_app_copy(copy):
    assert update.gather_leagues(2026, offline=True) == (copy, 'app copy')
    assert update.gather_leagues(2026, fetch=None) == (copy, 'app copy')

    def down(url):
        raise OSError('no network')
    assert update.gather_leagues(2026, fetch=down) == (copy, 'app copy')
    one = {'SiteKit': {'Schedule': [{'game_id': '1', 'date_played': '2026-10-02', 'home_team_code': 'CLE',
                                     'visiting_team_code': 'GR'}]}}

    def ahl_only(url):
        if 'hockeytech' in url:
            return json.dumps(one).encode()
        raise OSError('liiga.fi down')
    got, where = update.gather_leagues(2026, fetch=ahl_only)
    assert got['ahl'] == [('2026-10-02', 'CLE', 'GR')] and got['liiga'] == copy['liiga'] and where == 'live + app copy'
    assert update.leagues_text(got, where) == 'AHL 1, ECHL 1,080, Liiga 544 (live + app copy)'
