"""The Penticton Vees: the WHL's 23rd club in the game's inactive placeholder slot (overtime_core/vees.py)."""
import pytest

from overtime_core import tdb, vees
from overtime_core import teams as T


def _slot(db, slot, table=T.TEAMS):
    t = db[table]
    return t, vees._row(t, slot)


def test_the_vees_are_wanted_only_when_the_pack_lists_them():
    squad = [{'league': 'whl', 'team': 'Penticton Vees'}]
    assert vees.wanted(squad) and not vees.wanted([{'league': 'whl', 'team': 'Kelowna Rockets'}])
    assert not vees.wanted([{'league': 'ohl', 'team': 'Penticton Vees'}]) and not vees.wanted(None)


@pytest.mark.game
def test_make_room_turns_the_placeholder_slot_into_a_whl_club_once(game_db):
    raw, schema = game_db
    db = tdb.Database.parse(raw, schema)
    teams, row = _slot(db, vees.SLOT)
    donor = vees._row(teams, vees.DONOR)
    assert teams.get(row, 'active') == 0 and teams.get(row, 'league') != teams.get(donor, 'league')
    assert vees.make_room(db) is True and vees.make_room(db) is False
    assert teams.get(row, 'league') == teams.get(donor, 'league') == 13
    assert teams.get(row, 'active') == 1 and teams.get(row, 'index') == vees.SLOT
    assert (teams.get(row, 'teamname'), teams.get(row, 'abbrname'), teams.get(row, 'cityname')) == \
        ('Penticton Vees', 'PEN', 'Penticton')
    assert teams.get(row, 'divisiongroup') == teams.get(donor, 'divisiongroup')   # the B.C. Division
    assert teams.get(row, 'arenaid') == vees.SLOT and teams.get(row, 'feprimarycolor') == 0x0C1E42
    arenas, arow = _slot(db, vees.SLOT, T.ARENAS)
    assert arenas.get(arow, 'arenaname') == 'South Okanagan Events Centre' and arenas.get(arow, 'maxattendance') == 4494
    # the jerseys keep their art id and take the donor's looks; the equipment is the donor's colours
    jerseys = db[T.STOCK_JERSEYS]
    mine = [i for i in range(jerseys.count) if jerseys.get(i, 'teamid') == vees.SLOT]
    assert len(mine) == 3 and {jerseys.get(i, 'hastie') for i in mine} == {1}
    gear = db[T.EQUIPMENT]
    donor_helmet = next(gear.get(i, 'zone1') for i in range(gear.count)
                        if gear.get(i, 'team') == vees.DONOR and gear.get(i, 'equipment') == 7)
    assert all(gear.get(i, 'zone1') == donor_helmet for i in range(gear.count)
               if gear.get(i, 'team') == vees.SLOT and gear.get(i, 'equipment') == 7)
    assert tdb.Database.parse(db.to_bytes(), schema)[T.TEAMS].get(row, 'teamname') == 'Penticton Vees'


def test_the_logo_loses_its_white_ground_but_keeps_the_white_inside():
    from PIL import Image, ImageDraw
    pytest.importorskip('tools.build_clubart')    # not in the public tree
    from tools import build_clubart
    img = Image.new('RGB', (60, 60), 'white')
    pen = ImageDraw.Draw(img)
    pen.ellipse((8, 8, 52, 52), fill=(12, 30, 66))
    pen.ellipse((24, 24, 36, 36), fill='white')                 # white lettering inside the crest
    out = build_clubart.knock_out_white(img)
    assert out.getpixel((1, 1))[3] == 0 and out.getpixel((58, 30))[3] == 0
    assert out.getpixel((30, 30)) == (255, 255, 255, 255)       # inside: opaque white
    assert out.getpixel((16, 30)) == (12, 30, 66, 255)


def test_the_slot_keeps_the_art_id_the_logo_is_drawn_on():
    assert vees.ART == 10497 and vees.LEAGUE == 13 and vees.LOGO_URL.endswith('.jpg')


def test_the_vees_slot_takes_the_plymouth_loc_texts():
    """The menus' names are the loc texts keyed by artabbr: the slot's is the Whalers' (no slot has it), renamed in NAMES."""
    from overtime_core import overlay
    assert vees.IDENTITY['artabbr'] == vees.ART_ABBR == 'PLYM'
    assert overlay.NAMES['NHLTeamName_PLYM'][1] == vees.NAME
    assert overlay.NAMES['NHLCityName_PLYM'][1] == vees.CITY
    assert overlay.NAMES['NHLTeamName_Abbr3_PLYM'][1] == vees.ABBR
