"""Today's NHL in the default roster: NHL.com 2026-27 rosters (tests/data, NHL.com 2026-10-02) and calendar."""
import json
import os
import re

import pytest

from overtime_core import calendar, equipment as EQ, lines, rosterupdate as U, tdb
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

    def column(self, name):
        return [r[name] for r in self.rows_]


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
def test_new_players_have_their_own_ufa_year_and_no_borrowed_pro_history(updated):
    """A made player takes no pro history from the record he was copied from: a club player without an NHL deal has
    no pro debut, first signing or waiver year (-1, as NHL 19's own junior and European players), and his UFA year is
    his birth year + 27, as the game's own players' (the Franchise's free agency reads it)."""
    _raw, _schema, db, _todo, report = updated
    bios = db[U.BIOS]
    rows = {bios.get(i, 'game_id'): bios.row(i) for i in range(bios.count)}
    made = [rows[c['game_id']] for c in report.created]
    assert made and all(b['yearufa'] == b['year'] + U.UFA_AGE for b in made)
    clubs = [b for b in made if b['proteam'] == -1 and b['team'] != T.SEATTLE]
    assert all(b[f] == -1 for b in clubs for f in N.PRO_YEARS)


@pytest.mark.game
def test_players_who_came_to_an_nhl_team_wear_its_mask_and_sticks(updated):
    """After the update every goalie who came to an NHL team (moved or made) wears one of its own masks (n and n + 126,
    Vegas 85 / 86) or, on Utah and Seattle, the plain one; no goalie of Utah wears Arizona's coyote; every skater who
    came holds a stick in the team's colours or a plain one (equipment.fits)."""
    raw, schema, db, _todo, report = updated
    before, now = U._bio_teams(tdb.Database.parse(raw, schema)), U._bio_teams(db)
    eq = {r['game_id']: r for r in db[U.EQUIPMENT[True]].rows()}
    came = [(gid, team) for gid, team in now.items()
            if gid in eq and before.get(gid) != team and (team in U.NHL or team == T.SEATTLE) and eq[gid]['masktype'] == 0]
    assert len(came) > 20 and report.nhl27['masks']
    assert all(eq[gid]['maskid'] in (U.nhl_masks(team) or (U.PLAIN_MASK,)) for gid, team in came)
    assert not any(eq[gid]['maskid'] in U.COYOTE for gid, team in now.items() if gid in eq and team == T.UTAH_SLOT)
    sticks = {r['game_id']: r['stick'] for r in db[U.EQUIPMENT[False]].rows()}
    skaters = [(gid, team) for gid, team in now.items()
               if gid in sticks and before.get(gid) != team and team in U.NHL]
    assert len(skaters) > 100 and report.nhl27['sticks']
    assert all(EQ.fits(sticks[gid], EQ.team_hues(db, team)) for gid, team in skaters)


@pytest.mark.game
def test_a_made_player_wears_new_player_gear_not_his_donors(game_db):
    """A player the update makes is copied from a donor of his build, but wears equipment.NEW_PLAYER's choices (a goalie
    of masktype 0 the plain mask), not the donor's visor, tucks, tape or mask; the models (stick, helmet, pads) stay the
    donor's."""
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    maker = U._Maker(db)
    for pos, kind in (('C', 'skater'), ('G', 'goalie')):
        real = {'first': 'Test', 'last': 'Player', 'position': pos, 'birth': '2006-05-01', 'shoots': 'L', 'country': 'CAN'}
        _pi, gid, _style, donor = maker.make(real, T.SLOTS['BOS'], T.SLOTS['BOS'], 99)
        row, from_row = EQ.row_of(db, gid, kind), EQ.row_of(db, donor, kind)
        gear, donors = EQ.read(db, row, kind), EQ.read(db, from_row, kind)
        plain = dict(EQ.NEW_PLAYER[kind])
        if kind == 'goalie' and db[EQ.GOALIE_TABLE].get(row, 'masktype') != 0:
            plain.pop('mask')
        assert {c: gear[c] for c in plain} == plain
        assert {c: v for c, v in gear.items() if c not in EQ.NEW_PLAYER[kind]} == \
               {c: v for c, v in donors.items() if c not in EQ.NEW_PLAYER[kind]}


@pytest.mark.game
def test_a_renamed_club_slots_goalies_lose_the_old_clubs_masks(game_db):
    """Binghamton's slot plays as Abbotsford after rename_ahl: its goalies' masks were Binghamton's (160, 81), so they
    wear the plain one; the other three renamed slots too. A second run changes nothing."""
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    before = U._bio_teams(db)
    renamed = set(U.rename_ahl(db))
    assert renamed == {37, 38, 55, 59}
    eq = {r['game_id']: r for r in db[U.EQUIPMENT[True]].rows()}
    goalies = [gid for gid, team in before.items() if team in renamed and gid in eq and eq[gid]['masktype'] == 0]
    old = {eq[gid]['maskid'] for gid in goalies}
    assert goalies and old - U.GENERIC_MASKS
    U._fit_masks(db, before)  # without the renamed slots: Utah's coyotes go, Binghamton's masks still count as the club's
    assert {gid: r['maskid'] for gid, r in eq.items() if gid in goalies} == \
           {r['game_id']: r['maskid'] for r in db[U.EQUIPMENT[True]].rows() if r['game_id'] in goalies}
    assert U._fit_masks(db, before, renamed)['masks'] == len([g for g in goalies if eq[g]['maskid'] not in U.GENERIC_MASKS])
    now = {r['game_id']: r['maskid'] for r in db[U.EQUIPMENT[True]].rows()}
    assert all(now[gid] == U.PLAIN_MASK or now[gid] in U.GENERIC_MASKS for gid in goalies)
    assert U._fit_masks(db, U._bio_teams(db)) == {'masks': 0, 'goalie_colours': 0}


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


def test_who_retired_after_last_season_is_gone_at_any_age():
    # Legacy builder.retired_people: the pack's list, and last season's players unsigned at 38
    pack = {'retired': [{'first': 'Anze', 'last': 'Kopitar', 'birth': [1987, 8, 24]}],
            'nhl_last': [{'first': 'Anze', 'last': 'Kopitar', 'birth': [1987, 8, 24], 'team': None},
                         {'first': 'Jonathan', 'last': 'Toews', 'birth': [1988, 4, 29], 'team': None},   # 38: gone
                         {'first': 'Gustav', 'last': 'Nyquist', 'birth': [1989, 9, 1], 'team': None},    # 37: stays
                         {'first': 'Brent', 'last': 'Burns', 'birth': [1985, 3, 9], 'team': 'COL'}]}     # signed
    assert [p['last'] for p in U.gone_people(pack, 2026)] == ['Kopitar', 'Toews']
    assert [p['last'] for p in U.still_playing(pack, 2026)] == ['Nyquist', 'Burns']
    nhl27 = [{'first': 'Jonathan', 'last': 'Toews', 'birth': [1988, 4, 30], 'team': None},   # NHL 27's free agent
             {'first': 'Anze', 'last': 'Kopitar', 'birth': [1987, 8, 24], 'team': 'LAK'}]     # on a club: wins
    assert [p['last'] for p in U.without_gone(nhl27, U.gone_people(pack, 2026), free_only=True)] == ['Kopitar']
    assert U.gone_people(None) == [] and U.without_gone(nhl27, None) == nhl27


@pytest.mark.game
def test_free_agents_under_30_stay_and_the_gone_retire_at_any_age(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    state = U.State(db)
    age = {pi: 2026 - 1900 - state.bio(pi)['year'] for pi in state.free if state.bio(pi)}
    young = sorted(pi for pi, a in age.items() if a < U.NHL27_RETIRE_AGE)
    b = state.bio(young[0])
    who = {'first': b['firstname'], 'last': b['lastname'], 'birth': [b['year'] + 1900, b['month'] + 1, b['day'] + 1]}
    got = {pi for pi, _n, _a in U.retirees(db, [], 2026, U.NHL27_RETIRE_AGE)}
    assert got and not got & set(young) and all(age[pi] >= U.NHL27_RETIRE_AGE for pi in got)
    assert young[0] in {pi for pi, _n, _a in U.retirees(db, [], 2026, U.NHL27_RETIRE_AGE, [who])}
    assert young[0] not in {pi for pi, _n, _a in U.retirees(db, [who], 2026, U.NHL27_RETIRE_AGE, [who])}  # listed


@pytest.mark.game
def test_nhl_coms_birthplace_fills_an_empty_one_and_a_made_players(game_db):
    # Legacy nhl_bio; NHL 19 writes the city alone and left 579 bios empty: a stock birthplace stays
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    state = U.State(db)
    before = {r['game_id']: r['birthplace'] for r in db[U.BIOS].rows()}
    todo = U.plan(db, [dict(p, birthplace='Testville') for p in real_rosters()])
    placed = {state.bio(pi)['game_id'] for _p, pi, _to, _l in todo.placed if pi is not None}
    report = U.apply(db, schema, todo, start_year=2026)
    after = {r['game_id']: r['birthplace'] for r in db[U.BIOS].rows()}
    assert report.created and all(after[c['game_id']] == 'Testville' for c in report.created)
    assert [g for g in placed if not before[g].strip()]
    assert all(after[g] == (before[g] if before[g].strip() else 'Testville') for g in placed)


def test_unsigned_last_is_who_no_club_signed_and_did_not_retire():
    pack = {'nhl_last': [{'first': 'Hunter', 'last': 'Shepard', 'birth': [1995, 11, 7], 'pos': 'G', 'team': None},
                         {'first': 'Jonathan', 'last': 'Toews', 'birth': [1988, 4, 29], 'pos': 'C', 'team': None},  # 38
                         {'first': 'Brent', 'last': 'Burns', 'birth': [1985, 3, 9], 'pos': 'D', 'team': 'COL'},
                         {'first': 'No', 'last': 'Position', 'birth': [1999, 1, 1], 'team': None}]}
    assert [p['last'] for p in U.unsigned_last(pack, 2026)] == ['Shepard'] and U.unsigned_last(None) == []


def bio_row(b, pos):
    return {'first': b['firstname'], 'last': b['lastname'], 'birth': [b['year'] + 1900, b['month'] + 1, b['day'] + 1],
            'pos': pos}


@pytest.mark.game
def test_last_seasons_unsigned_players_are_free_agents(game_db):
    # Legacy builder.add_unsigned: on no team and off the list -> the list; missing -> made; on a club -> stays
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    state, bios = U.State(db), db[U.BIOS]
    lone = next(pi for pi in sorted(state.free) if state.bio(pi) and state.bio(pi)['position'] < U.GOALIE
                and state.bio(pi)['team'] == -1 and state.pis_of[state.bio(pi)['game_id']] == [pi])
    year = state.bio(lone)['year']
    U._rebuild_free(db, remove=[lone], add=[])  # the 2018 bio on no team and off the list (Aube-Kubel's)
    club_pi = next(pi for pi, (table, team) in sorted(state.entry.items()) if table == U.ROSTER and team == 218)
    rows = [bio_row(state.bio(lone), 'C'), bio_row(state.bio(club_pi), 'C'),
            {'first': 'Hunterx', 'last': 'Shepardx', 'birth': [1995, 11, 7], 'pos': 'G', 'country': 'USA'}]
    counts, ids = U.add_unsigned(db, rows, 8, {})
    assert counts == {'unsigned_listed': 1, 'unsigned_made': 1}
    after = U.State(db)
    assert lone in after.free and after.bio(lone)['year'] == year - 8  # onto the game's clock
    assert after.entry[club_pi] == (U.ROSTER, 218) and club_pi not in after.free
    made = next(r for r in bios.rows() if r['lastname'] == 'Shepardx')
    assert made['game_id'] in ids and made['team'] == -1 and made['jersey'] == U.UNSIGNED_NUMBER
    assert made['position'] == U.GOALIE and made['contractstatus'] == -1 and made['year'] == 1995 - 1900 - 8
    assert set(after.pis_of[made['game_id']]) & after.free
    fa = [db[U.FREE].get(i, 'playerindex') for i in range(db[U.FREE].count)]
    assert fa == sorted(fa)
    blob = db.to_bytes()
    assert U.add_unsigned(db, rows, 8, {})[0] == {'unsigned_listed': 0, 'unsigned_made': 0} and db.to_bytes() == blob


def free_agents(db, kind):
    state = U.State(db)
    out = []
    for pi in sorted(state.free):
        b = state.bio(pi)
        if b is None or any(o in state.entry for o in state.pis_of.get(b['game_id'], [])):
            continue
        if ('G' if b['position'] == U.GOALIE else 'D' if b['position'] == 3 else 'F') == kind:
            out.append((pi, b['game_id'], U._overall(db, state, pi), U.DEFAULT_SEASON - U.YEAR_BASE - b['year']))
    return out


def club_kinds(db, team):
    have = lines.players_of(db, table=U.ROSTER, team=team)
    return {k: [p.index for p in have if ('G' if p.pos == U.GOALIE else 'D' if p.pos == 3 else 'F') == k] for k in 'GDF'}


@pytest.mark.game
def test_a_minor_club_signs_the_free_agent_nearest_its_level_and_never_a_listed_one(game_db):
    # Legacy clubs._fill_lineup: an ECHL club short of a forward signed Henrique, Saad or Kane, the best free agents
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    team = 220  # ECHL: 2 G, 9 D, 11 F
    state = U.State(db)
    own = sorted(U._overall(db, state, p.index) for p in lines.players_of(db, table=U.ROSTER, team=team))
    top, level = own[-1], own[len(own) // 2]
    assert len(club_kinds(db, team)['F']) == 11
    pool = free_agents(db, 'F')
    near = min((q > top, abs(q - level), -q, pi) for pi, _g, q, _a in pool)[-1]
    best = max(pool, key=lambda r: r[2])
    first = tdb.Database.parse(raw, schema)
    assert [pi for pi, _n, _t in U._sign_free_agents(first, U.ROSTER, team)] == [near] and near != best[0]
    gid = next(g for pi, g, _q, _a in pool if pi == near)
    got = U._sign_free_agents(db, U.ROSTER, team, listed={gid})  # a club's list has him: his league takes him
    assert len(got) == 1 and got[0][0] != near and got[0][0] != best[0]
    assert U._sign_free_agents(db, U.ROSTER, team) == []  # dressed now


@pytest.mark.game
def test_a_junior_club_signs_no_over_age_player_while_it_dresses_its_20(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    team = 156  # OHL: 2 G, 7 D, 13 F; every free agent of the stock roster is older than 20
    kinds = club_kinds(db, team)
    U._rebuild_roster(db[U.ROSTER], set(kinds['F'][:2]), [])  # 7 D + 11 F: 18 skaters, short of a forward
    assert U._sign_free_agents(db, U.ROSTER, team) == []
    U._rebuild_roster(db[U.ROSTER], {kinds['D'][0]}, [])  # 17 skaters: he can't dress, the youngest forward comes
    youngest = min(free_agents(db, 'F'), key=lambda r: r[3])  # one forward of 26, the others 31 and more
    assert [pi for pi, _n, _t in U._sign_free_agents(db, U.ROSTER, team)] == [youngest[0]]


@pytest.mark.game
def test_a_short_nhl_club_takes_back_its_own_then_calls_up_from_its_farm_club(game_db):
    # Legacy builder.call_ups: a former player, then the farm club's best while it can dress 20, then a free agent
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    team, farm = 27, U._farm_of(db, 27)  # Toronto and the Marlies
    state = U.State(db)
    assert farm is not None and next(r['teamname'] for r in db[T.TEAMS].rows() if r['index'] == farm).startswith('Toronto')
    alone = lambda pi: state.pis_of[state.bio(pi)['game_id']] == [pi]  # noqa: E731
    leaving = [pi for pi in club_kinds(db, team)['D'] if alone(pi)][:2]
    U._rebuild_roster(db[U.ROSTER], set(leaving), [])
    U._rebuild_free(db, remove=[], add=leaving)  # let go in this update (not on NHL.com's list)
    while len(club_kinds(db, team)['D']) > 5:
        U._rebuild_roster(db[U.ROSTER], {club_kinds(db, team)['D'][-1]}, [])
    called = []
    assert [pi for pi, _n, _t in U._sign_free_agents(db, U.ROSTER, team, former=set(leaving), called=called)] \
        in ([leaving[0]], [leaving[1]]) and called == []  # one of his own comes back first
    U._rebuild_roster(db[U.ROSTER], {club_kinds(db, team)['D'][-1]}, [])
    farm_d = [(U._overall(db, U.State(db), pi), pi) for pi in club_kinds(db, farm)['D']
              if U.State(db).bio(pi)['proteam'] in (team, -1)]
    signed = U._sign_free_agents(db, U.ROSTER, team, called=called)  # no former player now: the farm's best
    after = U.State(db)
    assert signed == [] and [c[0] for c in called] == [max(farm_d)[1]]
    up = after.bio(called[0][0])
    assert after.entry[called[0][0]] == (U.ROSTER, team) and up['team'] == up['proteam'] == team
    assert called[0][2:] == ([U.ROSTER, farm], [U.ROSTER, team]) and called[0][0] not in after.free
    gs = club_kinds(db, farm)
    while len(gs['D']) + len(gs['F']) > 18:  # the farm club is down to a 20 it can just dress: a free agent comes
        U._rebuild_roster(db[U.ROSTER], {gs['F'][-1]}, [])
        gs = club_kinds(db, farm)
    U._rebuild_roster(db[U.ROSTER], {club_kinds(db, team)['D'][-1]}, [])
    called = []
    assert len(U._sign_free_agents(db, U.ROSTER, team, called=called)) == 1 and called == []


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
