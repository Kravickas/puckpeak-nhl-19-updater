"""2026-27 teams: Utah in Arizona's slot, Seattle in the game's 32nd team (customteams 499), divisions."""
import pytest

from overtime_core import calendar, tdb
from overtime_core import teams as T


def test_divisions_cover_the_32_teams_once():
    codes = [c for codes in T.DIVISIONS_2026.values() for c in codes]
    assert sorted(codes) == sorted(calendar.SLOTS) and len(codes) == 32
    assert all(len(c) == 8 for c in T.DIVISIONS_2026.values())


def test_draft_team():
    assert T.draft_team('TOR') == 27 and T.draft_team('ARI') == T.UTAH_SLOT == T.draft_team('UTA')
    assert T.draft_team('SEA') == -1 and T.draft_team('QUE') == -1


@pytest.mark.game
def test_apply_sets_up_utah_and_seattle_once(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    stock = T.check(db, schema)
    assert any('ARZ' in p or 'Arizona' in p for p in stock)
    assert any(p.startswith('UTA (team 22) in division 8') for p in stock)  # Arizona sat in the Pacific
    written = []
    done = T.apply(db, schema, setter=lambda tag, row, f, v: (written.append(f), db[tag].set(row, f, v)))
    assert done and len(written) == len(done)
    assert T.check(db, schema) == [] and T.plan(db, schema) == [] and T.apply(db, schema) == []
    blob = db.to_bytes()
    again = tdb.Database.parse(blob, schema)
    assert again.to_bytes() == blob and T.check(again, schema) == []
    custom = again[schema.by_name(T.CUSTOM).short]
    rows = {custom.get(i, 'index'): i for i in range(custom.count)}
    seattle = custom.row(rows[T.SEATTLE])
    assert (seattle['cityname'], seattle['teamname'], seattle['abbrname']) == ('$SEATTLE', 'Kraken', 'SEA')
    assert seattle['divisiongroup'] == T.PACIFIC and seattle['feprimarycolor'] == 0x001628
    assert seattle['teamtype'] == 1 and seattle['artid'] == 10499  # the rest of the expansion record is kept
    utah = again[schema.by_name(T.TEAMS).short].row(T.UTAH_SLOT)
    assert (utah['abbrname'], utah['artabbr'], utah['divisiongroup']) == ('UTA', 'PHX', T.CENTRAL)


@pytest.mark.game
def test_jersey_art_points_seattle_jerseys_at_10499(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    done = T.jersey_art(db, schema)
    assert {(name, old, new) for name, _row, old, new in done} == {
        (T.CUSTOM_JERSEYS, T.TEMPLATE_ART, T.SEATTLE_ART), (T.STOCK_JERSEYS, T.TEMPLATE_ART, T.SEATTLE_ART)}
    assert len(done) == 6 and T.jersey_art(db, schema) == []
    for name, team in T.JERSEYS:
        t = db[schema.by_name(name).short]
        assert {t.get(i, 'teamartid') for i in range(t.count) if t.get(i, 'teamid') == team} == {T.SEATTLE_ART}
    stock = db[schema.by_name(T.STOCK_JERSEYS).short]
    assert sum(stock.get(i, 'teamartid') == T.SEATTLE_ART for i in range(stock.count)) == 3  # nobody else's


@pytest.mark.game
def test_seattle_kit_is_art_900_byte_exact(game_db):
    """Seattle wears art 900 (HUT's `pre_order` 3D set): exactly its three stockteamjerseys rows (Play Now) and three
    customteamjerseys rows (Season, Be a Pro, Franchise) change, their teamartid only; the Creation Zone teams keep art
    1000, the database is otherwise byte for byte the same, and a second run changes nothing."""
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    teams = db[T.TEAMS]
    rows = {}
    for name, team in T.SEATTLE_KIT:
        t = db[schema.by_name(name).short]
        wearers = {t.get(i, 'teamid') for i in range(t.count) if t.get(i, 'teamartid') == T.SEATTLE_KIT_ART}
        assert not any(teams.get(i, 'active') for i in range(teams.count)
                       if teams.get(i, 'index') in wearers)  # only inactive teams wear it
        rows[name] = [i for i in range(t.count) if t.get(i, 'teamid') == team]
        assert len(rows[name]) == 3
    custom = db[schema.by_name(T.CUSTOM_JERSEYS).short]
    creation = [custom.row(i) for i in range(custom.count) if custom.get(i, 'teamid') != T.SEATTLE]
    done = T.seattle_kit(db, schema)
    assert [(n, r) for n, r, _, _ in done] == [(n, i) for n, _ in T.SEATTLE_KIT for i in rows[n]]
    assert T.seattle_kit(db, schema) == []
    assert [custom.row(i) for i in range(custom.count) if custom.get(i, 'teamid') != T.SEATTLE] == creation
    expect = tdb.Database.parse(raw, schema)
    for name, _ in T.SEATTLE_KIT:
        for i in rows[name]:
            expect[schema.by_name(name).short].set(i, 'teamartid', T.SEATTLE_KIT_ART)
    assert db.to_bytes() == expect.to_bytes() != raw
    assert schema.by_name(T.CUSTOM_JERSEYS).short not in [t.tag for t in db.subset('rosterupdate').tables]


@pytest.mark.game
def test_seattle_center_ice_is_its_own_logo(game_db):
    """Seattle (exhibitionteams 399, customteams 499) gets centre ice as the NHL teams have it; the Creation Zone slots
    keep the generic logo, and nothing else changes."""
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    before = {name: [db[name].row(i) for i in range(db[name].count)] for name in (T.TEAMS, T.CUSTOM)}
    nhl = {(r['centericelogotype'], r['centericelogo']) for r in before[T.TEAMS] if r['index'] in range(31)}
    assert nhl == {tuple(T.CENTER_ICE_OWN.values())}
    assert T.seattle_center_ice(db) == 2 and T.seattle_center_ice(db) == 0
    for name, index in ((T.TEAMS, T.SEATTLE_PLAY_NOW), (T.CUSTOM, T.SEATTLE)):
        after = [db[name].row(i) for i in range(db[name].count)]
        changed = [(b, a) for b, a in zip(before[name], after) if b != a]
        assert len(after) == len(before[name]) and len(changed) == 1
        b, a = changed[0]
        assert a['index'] == index and (b['centericelogotype'], b['centericelogo']) == (0, 1000)
        assert dict(a) == {**b, **T.CENTER_ICE_OWN}
    assert all(r['centericelogo'] == 1000 for r in after if 400 <= r['index'] < 450)  # Creation Zone slots
    blob = db.to_bytes()
    assert tdb.Database.parse(blob, schema).to_bytes() == blob


@pytest.mark.game
def test_drop_throwbacks_leaves_utah_its_adidas_kits(game_db):
    """Arizona's style 0 / 1 rows (Coyotes retro) go; Utah keeps its 3 adidas rows, numbered from 0 like Vegas's, and
    the resort goalie extras that wear one follow."""
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    t = db[schema.by_name(T.STOCK_JERSEYS).short]
    goalies = db[schema.by_name('exhibitionresortgoalieextras').short]
    others = [t.row(i) for i in range(t.count) if t.get(i, 'teamid') != T.UTAH_SLOT]
    utah_before = [t.row(i) for i in range(t.count) if t.get(i, 'teamid') == T.UTAH_SLOT]
    worn = sorted(goalies.get(i, 'casualjerseyindex') for i in range(goalies.count)
                  if goalies.get(i, 'casualjerseyteam') == T.UTAH_SLOT)
    assert worn == [9, 10]  # stock: Utah's adidas home and away
    removed = T.drop_throwbacks(db, schema)
    assert sorted(removed) == [(0, 0), (0, 1), (0, 3), (0, 4), (1, 0), (1, 1), (1, 3), (1, 4), (1, 5)]
    assert T.drop_throwbacks(db, schema) == []
    blob = db.to_bytes()
    db = tdb.Database.parse(blob, schema)
    assert db.to_bytes() == blob
    t = db[schema.by_name(T.STOCK_JERSEYS).short]
    utah = [t.row(i) for i in range(t.count) if t.get(i, 'teamid') == T.UTAH_SLOT]
    assert [(r['style'], r['variant'], r['jerseyindex']) for r in utah] == [(2, 0, 0), (2, 1, 1), (2, 2, 2)]
    adidas = [dict(r, jerseyindex=None) for r in utah_before if r['style'] == T.ADIDAS]
    assert [dict(r, jerseyindex=None) for r in utah] == adidas  # nothing else of the kept rows changed
    assert [t.row(i) for i in range(t.count) if t.get(i, 'teamid') != T.UTAH_SLOT] == others
    goalies = db[schema.by_name('exhibitionresortgoalieextras').short]
    assert sorted(goalies.get(i, 'casualjerseyindex') for i in range(goalies.count)
                  if goalies.get(i, 'casualjerseyteam') == T.UTAH_SLOT) == [0, 1]

@pytest.mark.game
def test_utah_wears_utah_colours_not_arizona_red(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    eq = db[schema.by_name(T.EQUIPMENT).short]

    def helmets(team):
        return {eq.get(i, 'zone1') for i in range(eq.count)
                if eq.get(i, 'team') == team and eq.get(i, 'equipment') == 7 and eq.get(i, 'variant') == -1}

    repainted = {eq.get(row, 'team') for name, row, *_ in T.plan(db, schema) if name == T.EQUIPMENT}
    assert repainted == {T.UTAH_SLOT, 64}  # Utah, and Utica in New Jersey's red and black
    others = [eq.row(i) for i in range(eq.count) if eq.get(i, 'team') not in repainted]
    assert 0x821113 in helmets(T.UTAH_SLOT)  # stock: the Coyotes' brick-red helmet
    assert any(T.EQUIPMENT in p for p in T.check(db, schema))
    T.apply(db, schema)
    assert T.plan(db, schema) == []
    assert 0x0F0F0F in helmets(T.UTAH_SLOT) and not helmets(T.UTAH_SLOT) & set(T.UTAH_EQUIPMENT)
    utah = [eq.row(i) for i in range(eq.count) if eq.get(i, 'team') == T.UTAH_SLOT]
    assert not {r[z] for r in utah for z in T.ZONES} & set(T.UTAH_EQUIPMENT)
    assert [eq.row(i) for i in range(eq.count) if eq.get(i, 'team') not in repainted] == others
    tc = db[schema.by_name(T.TEAM_COLOURS).short]
    assert sorted(tc.get(i, 'color') for i in range(tc.count) if tc.get(i, 'team') == T.UTAH_SLOT) == \
        sorted([0x6CACE4, 0xFFFFFF, 0x101010])


def test_farms_name_every_nhl_teams_2026_club():
    from overtime_core import leaguecal
    assert set(T.FARMS_2026) == set(calendar.SLOTS) - {'SEA'}  # Seattle's farm is Coachella Valley (customteams)
    assert len({T.club_key(c) for c in T.FARMS_2026.values()}) == 31
    assert set(T.FARMS_2026) == set(leaguecal.AHL_PARENT.values()) - {'SEA'}


def test_gear_follows_the_colour_its_hue_matches():
    # Binghamton's red becomes Abbotsford's blue; black has no hue and stays; gold matches neither old colour
    assert T._hue_map({0x922328, 0x131313, 0xFDBB30}, [0xB12B32, 0x131313], [0x004995, 0xC5C5C5]) == {0x922328: 0x004995}
    assert T._hue_map({0x922328}, [0xB12B32, 0x131313], [0xB12B32, 0x131313]) == {}  # same colours, nothing to do


@pytest.mark.game
def test_renamed_ahl_clubs_take_their_2026_records_and_farm_links(game_db):
    from overtime_core import leaguecal
    from overtime_core import rosterupdate as U
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    teams, eq = db[T.TEAMS], db[schema.by_name(T.EQUIPMENT).short]

    def gear(team):
        return [eq.row(i) for i in range(eq.count) if eq.get(i, 'team') == team]

    kept = {team: gear(team) for team in (45, 65)}  # Hershey, Wilkes-Barre: new colours, gear already fits
    T.apply(db, schema)
    rows = T._rows_by_index(teams)
    assert teams.get(rows[calendar.SLOTS['VGK']], 'ahlaffiliate') == 40  # stock: Chicago; Henderson is not there yet
    binghamton = gear(37)
    assert sorted(U.rename_ahl(db)) == [37, 38, 55, 59] and U.rename_ahl(db) == []
    assert T.apply(db, schema)
    assert T.plan(db, schema) == [] and T.check(db, schema) == []
    links = {code: teams.get(rows[calendar.SLOTS[code]], 'ahlaffiliate') for code in T.FARMS_2026}
    assert (links['VGK'], links['NJD'], links['VAN'], links['CAR'], links['STL'], links['FLA']) == (55, 64, 37, 40, 58, 39)
    assert all(T.club_key(teams.get(rows[slot], 'teamname')) == T.club_key(T.FARMS_2026[code])
               for code, slot in links.items())
    slots = leaguecal.ahl_slots(db)
    assert len(slots) == 32 and len(set(slots.values())) == 32
    hsk = teams.row(rows[55])
    assert (hsk['teamname'], hsk['cityname'], hsk['abbrname']) == ('Henderson Silver Knights', 'Henderson', 'HSK')
    assert (hsk['divisiongroup'], hsk['conferencegroup']) == (T.AHL_PACIFIC, T.AHL_WEST)
    arenas = db[T.ARENAS]
    arena = arenas.row(T._rows_by_index(arenas)[hsk['arenaid']])
    assert (arena['arenaname'], arena['cityname']) == ("Lee's Family Forum", 'Henderson, NV')
    abbotsford = gear(37)
    assert abbotsford != binghamton and 0x922328 not in {r[z] for r in abbotsford for z in T.ZONES}  # the red is gone
    assert all(gear(team) == before for team, before in kept.items())
    blob = db.to_bytes()
    assert tdb.Database.parse(blob, schema).to_bytes() == blob

