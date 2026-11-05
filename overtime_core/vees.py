"""The Penticton Vees, the WHL's 23rd club (they join for 2026-27), in a slot NHL 19 does not use.

NHL 19 has 22 WHL slots, all real clubs. exhibitionteams has room (519 rows, 423 used) but every table keyed by team
(jerseys, equipment, arenas, rosters ...) would need new rows, so the Vees take over one of the game's inactive placeholder
slots instead: `SLOT` (397, "Notes", EASHL league 17, no players, 39 equipment rows and 3 jersey rows of its own, its own
arena row). `make_room` turns it into a WHL slot that is a copy of a WHL club of the B.C. Division (`DONOR`, Kelowna) in every
field the game does not name; `rosterupdate.rebuild_league` then fills it like any free WHL slot (its `take_over`: the club
the league's feed lists and no slot holds, here the Vees) and `lines.build` builds its lines.

Like NHL Legacy's Vees (its last custom slot): Play Now and Roster Management, not the game's own WHL calendar (the
game's season tables hold 22 clubs). Notes: docs/notes/penticton-vees.md.
"""
from . import teams as T

SLOT = 397
LEAGUE = 13                              # the WHL (exhibitionteams.league)
ART = 10497                              # the slot's art id: its logo files (tools/build_clubart.py draws the Vees' on them)
LOGO_URL = 'https://assets.leaguestat.com/whl/logos/277_295.jpg'    # the WHL's own picture of the club's logo
DONOR = 199                              # Kelowna Rockets: WHL, B.C. Division
NAME, ABBR, CITY = 'Penticton Vees', 'PEN', 'Penticton'
COLOURS = T.colours(0x0C1E42, 0xA3D2F0, 0xFFFFFF)   # navy, light blue, white (the logo's)
ARENA = {'cityname': 'Penticton, BC', 'arenaname': 'South Okanagan Events Centre', 'maxattendance': 4494,
         'yearopened': 2008}
ART_ABBR = 'PLYM'                        # the menus show the loc texts keyed by artabbr (overlay.NAMES): the Plymouth Whalers' (an
                                         # OHL club of NHL 19 no slot uses) are renamed to the Vees'; the slot's own art id has none
KEEP = ('index', 'arenaid', 'artid', 'artabbr')     # what the slot keeps of its own
IDENTITY = {'teamname': NAME, 'nickname': NAME, 'cityname': CITY, 'abbrname': ABBR, 'artabbr': ART_ABBR, **COLOURS}
CLUB = 'Penticton Vees'


def wanted(players):
    """True when the pack's WHL players include the Vees (`players`: the pack's player rows, nhl27 / clubdata shape)."""
    return any(p.get('league') == 'whl' and p.get('team') == CLUB for p in players or ())


def _row(table, index):
    return next(i for i in range(table.count) if table.get(i, 'index') == index)


def _copy(table, src, dst, keep=()):
    """Every field of record `src` onto record `dst` but `keep` (the compressed strings too)."""
    for name in table.by_name:
        if name in keep:
            continue
        table.set(dst, name, table.get(src, name))


def is_made(db):
    """True when slot SLOT is already the Vees' (a roster this module made)."""
    t = db[T.TEAMS]
    row = _row(t, SLOT)
    return t.get(row, 'league') == t.get(_row(t, DONOR), 'league') and t.get(row, 'active') == 1


def make_room(db):
    """Slot SLOT becomes the Vees' slot in the WHL: the donor's record, then the Vees' names and colours, their arena and
    the jerseys' and equipment's own art. Returns True when it changed anything (a second call changes nothing)."""
    teams = db[T.TEAMS]
    if is_made(db):
        return False
    slot, donor = _row(teams, SLOT), _row(teams, DONOR)
    _copy(teams, donor, slot, keep=KEEP)
    for field, value in IDENTITY.items():
        teams.set(slot, field, value)
    arenas = db[T.ARENAS]
    _copy(arenas, _row(arenas, DONOR), _row(arenas, SLOT), keep=('index',))
    for field, value in ARENA.items():
        arenas.set(_row(arenas, SLOT), field, value)
    _copy_group(db[T.STOCK_JERSEYS], 'teamid', DONOR, SLOT, keep=('teamid', 'teamartid'))
    _gear(db[T.EQUIPMENT])
    return True


def _copy_group(table, key, src, dst, keep):
    """The donor's records onto the slot's own, in order (the jerseys: three each, Home / Away / Alternate)."""
    a = [i for i in range(table.count) if table.get(i, key) == src]
    b = [i for i in range(table.count) if table.get(i, key) == dst]
    for i, j in zip(a, b):
        _copy(table, i, j, keep=keep)


def _gear(table):
    """Every equipment record of the slot gets the colours of the donor's record of the same equipment (the variant's
    when the donor has it, else its first): the placeholder's variants are its own blue and cream."""
    mine = [i for i in range(table.count) if table.get(i, 'team') == SLOT]
    theirs = {}
    for i in range(table.count):
        if table.get(i, 'team') == DONOR:
            theirs.setdefault(table.get(i, 'equipment'), {}).setdefault(table.get(i, 'variant'), i)
    for j in mine:
        by_variant = theirs.get(table.get(j, 'equipment'))
        if by_variant:
            i = by_variant.get(table.get(j, 'variant')) or next(iter(by_variant.values()))
            _copy(table, i, j, keep=('team', 'index', 'equipment', 'variant', 'era'))
