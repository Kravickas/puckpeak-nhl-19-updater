"""NHL 19's teams set up as the 2026-27 league: Arizona's slot becomes Utah, the game's own 32nd team becomes Seattle.

    Utah      exhibitionteams 22 (Arizona Coyotes): names, abbreviation and colours of the Utah Mammoth, moved from the
              Pacific to the Central. The art stays Arizona's (artabbr 'PHX': the loc text and logos are keyed by it).
    Seattle   customteams 499 ("BURNABY NHL 32"): the team a Franchise with the 32-team expansion makes league team 31
              (run X1). Names, abbreviation, colours, Pacific. Its AHL club, customteams 498 ("Aces", league team 63 in
              that Franchise), becomes the Coachella Valley Firebirds.
    Play Now  exhibitionteams 399 ("NHL 32", the game's inactive copy of the expansion team, art id 10499 like 499):
              Seattle again, moved into the NHL league (0) and made active, so Play Now lists it; its players are
              customrostertable's team 499 through their own exhibitionplayers records (rosterupdate.mirror_seattle,
              as the All-Star teams have theirs). exhibitionteams is in the `rosterupdate` savegroup: this copy of
              Seattle travels in the online roster too.
    Arenas    exhibitionarena 22 becomes the Delta Center, customarena 499 Climate Pledge Arena (with Seattle's city:
              the game resets a custom arena's '$BURNABY' to '$ABBOTSFORD' when the team is saved in the Creation
              Zone, run x2-20261016/run6), customarena 498 Acrisure Arena, exhibitionarena 399 Climate Pledge Arena.
              The other NHL arenas: 2026's names and capacities (NHL_ARENAS_2026).
    AHL       the clubs as they are in 2026-27 (AHL_2026, found by name): the four slots rosterupdate.rename_ahl
              names after their 2026 club get its town, abbreviation, division, colours and arena; every NHL team's
              farm link (ahlaffiliate) points at its 2026 club (FARMS_2026).

customteams is in the `rosters` / `custom` savegroups (not in `rosterupdate`): Seattle's team 499 travels in a custom
roster save, not in the online roster (exhibitionteams 399 does). Seattle's draftees keep `draftteam` -1 (the field is 5 bits: -1..30).
Colours are 0xRRGGBB; the Kraken's and the Mammoth's are the clubs' published ones, the Firebirds' approximate.
"""
import re
import unicodedata

from .calendar import SLOTS
from .equipment import GEAR, NEAR, hue_of

PACIFIC, CENTRAL, ATLANTIC, METROPOLITAN = 8, 9, 10, 11  # divisiongroup (stock data)
WEST, EAST = 6, 7  # conferencegroup
CONFERENCE = {PACIFIC: WEST, CENTRAL: WEST, ATLANTIC: EAST, METROPOLITAN: EAST}
DIVISIONS_2026 = {
    PACIFIC: ('ANA', 'CGY', 'EDM', 'LAK', 'SEA', 'SJS', 'VAN', 'VGK'),
    CENTRAL: ('CHI', 'COL', 'DAL', 'MIN', 'NSH', 'STL', 'UTA', 'WPG'),
    ATLANTIC: ('BOS', 'BUF', 'DET', 'FLA', 'MTL', 'OTT', 'TBL', 'TOR'),
    METROPOLITAN: ('CAR', 'CBJ', 'NJD', 'NYI', 'NYR', 'PHI', 'PIT', 'WSH'),
}
DIVISION_OF = {code: div for div, codes in DIVISIONS_2026.items() for code in codes}

TEAMS, CUSTOM = 'exhibitionteams', 'customteams'
STOCK_JERSEYS, CUSTOM_JERSEYS = 'stockteamjerseys', 'customteamjerseys'
ARENAS, CUSTOM_ARENAS = 'exhibitionarena', 'customarena'
UTAH_SLOT = SLOTS['UTA']  # 22
SEATTLE, SEATTLE_AHL = 499, 498  # customteams index
SEATTLE_PLAY_NOW = 399  # exhibitionteams index of the game's "NHL 32" copy
NHL_LEAGUE = 0  # stockleagues: 0 NHL (Play Now's NHL list), 16 custom teams, 17 EASHL (399's stock league)

# NHL 19's league year (leaguestates key 138; the league kernel compares with 2018 in ~100 places, so the patch keeps
# it). Ages are counted from it: a roster for season S stores birth and draft years S - 2018 earlier.
GAME_YEAR = 2018


def year_shift(season):
    """Years an updated roster's birth / draft years sit behind the real ones (8 for 2026-27)."""
    return max(0, season - GAME_YEAR) if season else 0


def colours(primary, secondary, tertiary):
    out = {}
    for prefix in ('fe', 'overlay', 'pres'):
        out.update({f'{prefix}primarycolor': primary, f'{prefix}secondarycolor': secondary,
                    f'{prefix}tertiarycolor': tertiary})
    return out


UTAH = {'cityname': 'Utah', 'teamname': 'Utah Mammoth', 'nickname': 'Utah Mammoth', 'abbrname': 'UTA',
        'divisiongroup': CENTRAL, 'conferencegroup': WEST, **colours(0x010101, 0x6CACE4, 0xFFFFFF)}
# a custom team's city is a loc string id with '$' ('$BURNABY' -> "Burnaby"); a name that is not one shows as the
# first city of the list ("Abbotsford") and the Creation Zone stopped taking input (run x2-20261016)
SEATTLE_FIELDS = {'cityname': '$SEATTLE', 'teamname': 'Kraken', 'nickname': 'Kraken', 'abbrname': 'SEA',
                  'divisiongroup': PACIFIC, 'conferencegroup': WEST, **colours(0x001628, 0x99D9D9, 0x355464)}
# NHL teams and All-Stars have leaguegroup 1 (399's stock 53 is the custom teams'). Play Now lists 399 as "Seattle
# Kraken" after the All-Stars once the served roster is the active one (run ws8 run1b: an older RosterDownload save
# had kept the stock 399 off the list)
NHL_LEAGUE_GROUP = 1
SEATTLE_EXHIBITION = {**SEATTLE_FIELDS, 'league': NHL_LEAGUE, 'leaguegroup': NHL_LEAGUE_GROUP, 'active': 1}
# no loc id for Coachella Valley: the city stays '$BURNABY' (the text layer can rename "Burnaby", Phase B)
COACHELLA = {'teamname': 'Firebirds', 'nickname': 'Firebirds', 'abbrname': 'CV', **colours(0xC8102E, 0xF47A38, 0x001628)}

UTAH_ARENA = {'cityname': 'Salt Lake City, UT', 'arenaname': 'Delta Center', 'maxattendance': 16020, 'yearopened': 1991}
SEATTLE_ARENA = {'cityname': '$SEATTLE', 'arenaname': 'Climate Pledge Arena', 'maxattendance': 17151, 'yearopened': 2021}
COACHELLA_ARENA = {'arenaname': 'Acrisure Arena', 'maxattendance': 10087, 'yearopened': 2022}

# (table, index field value, fields)
CHANGES = ((TEAMS, UTAH_SLOT, UTAH), (CUSTOM, SEATTLE, SEATTLE_FIELDS), (CUSTOM, SEATTLE_AHL, COACHELLA),
           (ARENAS, UTAH_SLOT, UTAH_ARENA), (CUSTOM_ARENAS, SEATTLE, SEATTLE_ARENA),
           (CUSTOM_ARENAS, SEATTLE_AHL, COACHELLA_ARENA), (TEAMS, SEATTLE_PLAY_NOW, SEATTLE_EXHIBITION),
           (ARENAS, SEATTLE_PLAY_NOW, SEATTLE_ARENA))


# Seattle's art id: both records carry `artid` 10499, but their jerseys use the custom-team template's teamartid 1000,
# which is also the EA placeholder's (t1000, jersey_1_1000_*: the logo on the trade screen, run x4). With the
# art layer's 10499 logo and jersey files in the game, `jersey_art` points the jerseys at 10499
# (docs/notes/nhl19-32teams-re.md, S2).
SEATTLE_ART, TEMPLATE_ART = 10499, 1000

# Utah's equipment: stockteamequipmenttable keeps Arizona's colours per team (zone1..zone15, 0xRRGGBB; equipment 7
# is the helmet, 4 the gloves), so Utah's helmets rendered Coyotes red (WS7 run g). Arizona's own reds become the
# black of the other teams' helmets (0x0f0f0f) and gear (0x202020), the navy of its alternate kits Mountain Blue;
# whites and the shared colours stay. stockteamcolorstable's accents (colorid 0, 1) brick red and sand become
# Mountain Blue and white.
EQUIPMENT, TEAM_COLOURS = 'stockteamequipmenttable', 'stockteamcolorstable'
ZONES = tuple(f'zone{z}' for z in range(1, 16))
UTAH_EQUIPMENT = {0x821113: 0x0F0F0F, 0x732227: 0x0F0F0F, 0x6B141A: 0x202020, 0x6B1B20: 0x202020,
                  0x631219: 0x202020, 0x90181C: 0x202020, 0x122063: 0x6CACE4, 0x253B73: 0x6CACE4}
UTAH_COLOURS = {0x7F1112: 0x6CACE4, 0xE7C49C: 0xFFFFFF}


def _colour_plan(db, schema):
    out = []
    for name, fields, colours in ((EQUIPMENT, ZONES, UTAH_EQUIPMENT), (TEAM_COLOURS, ('color',), UTAH_COLOURS)):
        if schema.by_name(name).short not in db:
            continue
        t = db[schema.by_name(name).short]
        for i in range(t.count):
            if t.get(i, 'team') == UTAH_SLOT:
                out += [(name, i, f, t.get(i, f), colours[t.get(i, f)]) for f in fields if t.get(i, f) in colours]
    return out


# --- the rest of the league as it is in 2026-27 (Legacy builder.NHL_LOOK / AHL_ARENAS, docs/notes/legacy-align.md) ---
# The NHL arenas (exhibitionarena, index = team slot): buildings renamed or replaced since 2018, and every capacity as
# NHL 27's arena table gives it for 2026-27. ANA, BOS, DAL, NYR and TOR's rows are 2018's already; Utah: UTAH_ARENA.
NHL_ARENAS_2026 = {
    'WPG': {'arenaname': 'Canada Life Centre', 'maxattendance': 15321}, 'BUF': {'maxattendance': 19070},
    'CGY': {'maxattendance': 19289}, 'CAR': {'arenaname': 'Lenovo Center', 'maxattendance': 18700},
    'CHI': {'maxattendance': 19717}, 'COL': {'arenaname': 'Ball Arena', 'maxattendance': 17809},
    'CBJ': {'maxattendance': 18144}, 'DET': {'maxattendance': 19515}, 'EDM': {'maxattendance': 18347},
    'FLA': {'arenaname': 'Amerant Bank Arena'}, 'LAK': {'arenaname': 'Crypto.com Arena', 'maxattendance': 18230},
    'MIN': {'arenaname': 'Grand Casino Arena', 'maxattendance': 17954}, 'MTL': {'maxattendance': 21105},
    'NSH': {'maxattendance': 17159}, 'NJD': {'maxattendance': 16514},
    'NYI': {'arenaname': 'UBS Arena', 'cityname': 'Elmont, NY', 'maxattendance': 17255, 'yearopened': 2021},
    'OTT': {'maxattendance': 19153}, 'PHI': {'arenaname': 'Xfinity Mobile Arena', 'maxattendance': 19538},
    'PIT': {'maxattendance': 18387}, 'STL': {'maxattendance': 18096}, 'SJS': {'maxattendance': 17435},
    'TBL': {'arenaname': 'Benchmark International Arena', 'maxattendance': 19092}, 'VAN': {'maxattendance': 18910},
    'WSH': {'maxattendance': 18573}, 'VGK': {'maxattendance': 17367},
}


def _prefixed(prefix, primary, secondary, tertiary):
    return {f'{prefix}primarycolor': primary, f'{prefix}secondarycolor': secondary, f'{prefix}tertiarycolor': tertiary}


# NHL teams whose 2018 menu (fe) and presentation (pres) colours are off since their 2020-21 looks (NHL 27's team
# rows); their overlay colours stay.
NHL_COLOURS_2026 = {
    'BUF': {**_prefixed('fe', 0x1D305F, 0xDD9B26, 0), **_prefixed('pres', 0x103057, 0xFDBB30, 0)},
    'CBJ': {**_prefixed('fe', 0x002D62, 0xE51937, 0), **_prefixed('pres', 0x002D62, 0xE51937, 0)},
    'NYI': {**_prefixed('fe', 0x00529B, 0xE2621B, 0), **_prefixed('pres', 0x004E8A, 0xF06D27, 0)},
}

# The AHL (exhibitionteams league 1, slots 35-65, each its own arena row) as it is in 2026-27. A club is found by its
# name (club_key: letters only, so 'Hershey Bears®' is Hershey's), so a slot rosterupdate.rename_ahl gave its 2026
# club's name gets that club's record and a 2018 club the update did not move keeps its own. The four moved slots
# take the AHL's own abbreviation (the Wranglers' CGY is the Flames' too, as the stock CHI and COL are the Wolves' and
# the Eagles'), their 2026 division and NHL 27's colours. The other clubs' divisions are 2026's already: Atlantic 7,
# North 8, Central 7, Pacific 9 (the 10th, Coachella Valley, is Seattle's customteams 498).
AHL = 1
AHL_WEST, AHL_EAST = 13, 14  # conferencegroup (stock data; NHL 27 numbers them alike)
AHL_ATLANTIC, AHL_NORTH, AHL_CENTRAL, AHL_PACIFIC = 15, 16, 17, 18  # divisiongroup
AHL_2026 = {
    'Abbotsford Canucks': {'cityname': 'Abbotsford', 'abbrname': 'ABB', 'divisiongroup': AHL_PACIFIC,
                           'conferencegroup': AHL_WEST, **colours(0x004995, 0xC5C5C5, 0)},
    'Hamilton Hammers': {'cityname': 'Hamilton', 'abbrname': 'HAM', 'divisiongroup': AHL_NORTH,
                         'conferencegroup': AHL_EAST, **colours(0xE3621E, 0x213349, 0)},
    'Henderson Silver Knights': {'cityname': 'Henderson', 'abbrname': 'HSK', 'divisiongroup': AHL_PACIFIC,
                                 'conferencegroup': AHL_WEST, **colours(0x7C8E98, 0x131313, 0)},
    'Calgary Wranglers': {'cityname': 'Calgary', 'abbrname': 'CGY', 'divisiongroup': AHL_PACIFIC,
                          'conferencegroup': AHL_WEST, **colours(0xAB1C14, 0xC5C5C5, 0)},
    'Hershey Bears': colours(0x3D1315, 0x131313, 0), 'Ontario Reign': colours(0x572A84, 0xE0BE07, 0),
    'Utica Comets': colours(0xB12B32, 0x131313, 0), 'Wilkes-Barre/Scranton Penguins': colours(0xFEB61B, 0x202020, 0),
    'Manitoba Moose': {'presprimarycolor': 0x0069AA},
}
# Arenas renamed, moved or rebuilt since 2018 (exhibitionarena, the club's arenaid); a year only for a new building.
AHL_ARENAS_2026 = {
    'Abbotsford Canucks': {'arenaname': 'Rogers Forum', 'cityname': 'Abbotsford, BC', 'maxattendance': 7000,
                           'yearopened': 2009},
    'Hamilton Hammers': {'arenaname': 'TD Coliseum', 'cityname': 'Hamilton, ON', 'maxattendance': 17383,
                         'yearopened': 1985},
    'Henderson Silver Knights': {'arenaname': "Lee's Family Forum", 'cityname': 'Henderson, NV', 'maxattendance': 9500,
                                 'yearopened': 2022},
    'Calgary Wranglers': {'arenaname': 'Scotiabank Saddledome', 'cityname': 'Calgary, AB', 'maxattendance': 19289,
                          'yearopened': 1983},
    'Bakersfield Condors': {'arenaname': 'Dignity Health Arena'}, 'Belleville Senators': {'arenaname': 'CAA Arena'},
    'Chicago Wolves': {'arenaname': 'Allstate Arena', 'cityname': 'Rosemont, IL'},
    'Cleveland Monsters': {'arenaname': 'Rocket Mortgage FieldHouse'}, 'Colorado Eagles': {'arenaname': 'Blue Arena'},
    'Hartford Wolf Pack': {'arenaname': 'PeoplesBank Arena'}, 'Iowa Wild': {'arenaname': "Casey's Center"},
    'Manitoba Moose': {'arenaname': 'Canada Life Centre', 'maxattendance': 15321},
    'Ontario Reign': {'arenaname': 'Toyota Arena'}, 'Providence Bruins': {'arenaname': 'Amica Mutual Pavilion'},
    'Rochester Americans': {'arenaname': 'Blue Cross Arena at the War Memorial'},
    'Rockford IceHogs': {'arenaname': 'BMO Center'}, 'San Diego Gulls': {'arenaname': 'Pechanga Arena San Diego'},
    'San Jose Barracuda': {'arenaname': 'Tech CU Arena', 'maxattendance': 4200, 'yearopened': 2022},
    'Syracuse Crunch': {'arenaname': 'Upstate Medical University Arena'},
}
# Each NHL team's AHL club in 2026-27 (leaguecal.AHL_PARENT by club name). The links are written only when all 31 clubs
# are on the roster (the four moved slots renamed), one each: leaguecal.ahl_slots and the call-ups (rosterupdate.
# _farm_of) read them, and the stock links sent six teams to the wrong club (Vegas's to Chicago, New Jersey's to
# Binghamton's slot, which holds Abbotsford's players after the update).
FARMS_2026 = {
    'ANA': 'San Diego Gulls', 'WPG': 'Manitoba Moose', 'BOS': 'Providence Bruins', 'BUF': 'Rochester Americans',
    'CGY': 'Calgary Wranglers', 'CAR': 'Chicago Wolves', 'CHI': 'Rockford IceHogs', 'COL': 'Colorado Eagles',
    'CBJ': 'Cleveland Monsters', 'DAL': 'Texas Stars', 'DET': 'Grand Rapids Griffins', 'EDM': 'Bakersfield Condors',
    'FLA': 'Charlotte Checkers', 'LAK': 'Ontario Reign', 'MIN': 'Iowa Wild', 'MTL': 'Laval Rocket',
    'NSH': 'Milwaukee Admirals', 'NJD': 'Utica Comets', 'NYI': 'Hamilton Hammers', 'NYR': 'Hartford Wolf Pack',
    'OTT': 'Belleville Senators', 'PHI': 'Lehigh Valley Phantoms', 'UTA': 'Tucson Roadrunners',
    'PIT': 'Wilkes-Barre/Scranton Penguins', 'STL': 'Springfield Thunderbirds', 'SJS': 'San Jose Barracuda',
    'TBL': 'Syracuse Crunch', 'TOR': 'Toronto Marlies', 'VAN': 'Abbotsford Canucks', 'WSH': 'Hershey Bears',
    'VGK': 'Henderson Silver Knights',
}
# A club whose colours change repaints its gear (stockteamequipmenttable, the GEAR categories) and its accents
# (stockteamcolorstable) as Utah's were: a colour with the hue of its old primary or secondary that changed takes the
# new one of the same rank (Abbotsford's Binghamton red goes blue, Utica's Canucks blue and green go red and black);
# black, white, grey and hues the old colours lack stay (Wilkes-Barre's gold pads, Hershey's chocolate gear).


def club_key(name):
    """A club's name as letters only, lower case, without accents or marks (rosterupdate._team_key)."""
    return re.sub('[^a-z]', '', unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower())


AHL_BY_KEY = {club_key(k): v for k, v in AHL_2026.items()}
AHL_ARENA_BY_KEY = {club_key(k): v for k, v in AHL_ARENAS_2026.items()}


def _apart(a, b):
    return min((a - b) % 360, (b - a) % 360)


def _hue_map(found, old, new):
    """{colour: new colour} for the colours in `found` whose hue is an old colour's (`old` / `new`: [primary,
    secondary]) that changed."""
    out = {}
    for c in found:
        h = hue_of(c)
        k = None if h is None else next((k for k, o in enumerate(old) if hue_of(o) is not None
                                         and _apart(hue_of(o), h) <= NEAR), None)
        if k is not None and new[k] != old[k] and new[k] != c:
            out[c] = new[k]
    return out


def _repaint(db, schema, team, old, new):
    """Rows of `team`'s gear and accents to repaint from its fe colours `old` to `new` (_hue_map)."""
    out = []
    for name, fields, kinds in ((EQUIPMENT, ZONES, GEAR), (TEAM_COLOURS, ('color',), None)):
        if schema.by_name(name).short not in db:
            continue
        t = db[schema.by_name(name).short]
        rows = [i for i in range(t.count) if t.get(i, 'team') == team and (kinds is None or t.get(i, 'equipment') in kinds)]
        mapping = _hue_map({t.get(i, f) for i in rows for f in fields}, old, new)
        out += [(name, i, f, t.get(i, f), mapping[t.get(i, f)]) for i in rows for f in fields if t.get(i, f) in mapping]
    return out


FE = ('feprimarycolor', 'fesecondarycolor')


def _league_plan(db, schema):
    """The NHL arenas and colours of 2026-27, the AHL clubs' records, gear and farm links (see above)."""
    teams, arenas = db[schema.by_name(TEAMS).short], db[schema.by_name(ARENAS).short]
    team_rows, arena_rows = _rows_by_index(teams), _rows_by_index(arenas)
    out = []

    def fields(name, t, row, values):
        return [(name, row, f, t.get(row, f), v) for f, v in values.items() if _clean(t.get(row, f)) != v]
    for code, values in NHL_ARENAS_2026.items():
        out += fields(ARENAS, arenas, arena_rows[teams.get(team_rows[SLOTS[code]], 'arenaid')], values)
    for code, values in NHL_COLOURS_2026.items():
        out += fields(TEAMS, teams, team_rows[SLOTS[code]], values)
    slot_of = {}
    for row in range(teams.count):
        if teams.get(row, 'league') != AHL:
            continue
        key = club_key(teams.get(row, 'teamname'))
        slot_of[key] = teams.get(row, 'index')
        values = AHL_BY_KEY.get(key, {})
        out += fields(TEAMS, teams, row, values)
        arena = arena_rows.get(teams.get(row, 'arenaid'))
        if arena is not None:
            out += fields(ARENAS, arenas, arena, AHL_ARENA_BY_KEY.get(key, {}))
        old = [teams.get(row, f) for f in FE]
        new = [values.get(f, o) for f, o in zip(FE, old)]
        if new != old:
            out += _repaint(db, schema, teams.get(row, 'index'), old, new)
    farms = {code: slot_of.get(club_key(club)) for code, club in FARMS_2026.items()}
    if None not in farms.values() and len(set(farms.values())) == len(farms):
        for code, slot in farms.items():
            out += fields(TEAMS, teams, team_rows[SLOTS[code]], {'ahlaffiliate': slot})
    return out


JERSEYS = ((CUSTOM_JERSEYS, SEATTLE), (STOCK_JERSEYS, SEATTLE_PLAY_NOW))


def jersey_art(db, schema, art=SEATTLE_ART, setter=None, jerseys=JERSEYS):
    """Point Seattle's jerseys (customteamjerseys 499, stockteamjerseys 399; `jerseys`) at `art`. Returns [(table,
    row, old, new)] of the rows changed; a second run changes nothing."""
    out = []
    for name, team in jerseys:
        short = schema.by_name(name).short
        t = db[short]
        for i in range(t.count):
            if t.get(i, 'teamid') == team and t.get(i, 'teamartid') != art:
                out.append((name, i, t.get(i, 'teamartid'), art))
                if setter is None:
                    t.set(i, 'teamartid', art)
                else:
                    setter(short, i, 'teamartid', art)
    return out


# Seattle's 3D kit (WS7 run p): with the custom-team art 1000 the game draws Seattle as a Creation Zone recolour
# (czjersey_0 in its equipment zone colours; in game plain black, no crest), never the rbk_template files. Art 900 is
# Hockey Ultimate Team's (inactive; 3D set `pre_order`, menus jersey_1_900_*) and has real 3D kits for the style-1
# variants 0-2 Seattle's rows use, so Play Now's Seattle wears it and the looks pack lays NHL 27's Kraken kits over
# it (tools/nhl27/warp19.seattle). Three stockteamjerseys rows (rosterupdate: Play Now, online) and Seattle's three
# customteamjerseys rows (499; only in nhl_game.db, the database layer: Season, Be a Pro, Franchise's Seattle). The
# Creation Zone teams (400-449) keep art 1000.
SEATTLE_KIT_ART = 900
SEATTLE_KIT = ((STOCK_JERSEYS, SEATTLE_PLAY_NOW), (CUSTOM_JERSEYS, SEATTLE))


def seattle_kit(db, schema):
    """Seattle's jerseys (stockteamjerseys 399, customteamjerseys 499: SEATTLE_KIT) on art SEATTLE_KIT_ART. Returns
    the rows changed (jersey_art)."""
    return jersey_art(db, schema, SEATTLE_KIT_ART, jerseys=SEATTLE_KIT)


# Utah's throwbacks: Arizona's stockteamjerseys style 0 and 1 rows are Coyotes retro kits (WS7, docs/notes/art.md), so
# Utah would wear them. They go, as Vegas has none: Utah keeps its adidas rows (style 2), and their jerseyindex is
# renumbered from 0 in order, like every team's (it is the row's place among the team's rows). The resort goalie
# extras that wear a Utah kit (casualjerseyteam / casualjerseyindex) follow the new numbers.
ADIDAS = 2
RESORT_EXTRAS = ('exhibitionresortskaterextras', 'exhibitionresortgoalieextras', 'customresortskaterextras',
                 'customresortgoalieextras')


def drop_throwbacks(db, schema, team=UTAH_SLOT):
    """Remove `team`'s non-adidas stockteamjerseys rows. Returns [(style, variant)] removed; a second run removes
    nothing."""
    t = db[schema.by_name(STOCK_JERSEYS).short]
    rows = [i for i in range(t.count) if t.get(i, 'teamid') == team]
    old = [i for i in rows if t.get(i, 'style') != ADIDAS]
    if not old:
        return []
    keep = sorted((i for i in rows if t.get(i, 'style') == ADIDAS), key=lambda i: t.get(i, 'jerseyindex'))
    renumber = {t.get(i, 'jerseyindex'): n for n, i in enumerate(keep)}
    for i in keep:
        t.set(i, 'jerseyindex', renumber[t.get(i, 'jerseyindex')])
    for name in RESORT_EXTRAS:
        if schema.by_name(name).short not in db:
            continue
        x = db[schema.by_name(name).short]
        for i in range(x.count):
            if x.get(i, 'casualjerseyteam') == team:
                x.set(i, 'casualjerseyindex', renumber.get(x.get(i, 'casualjerseyindex'), 0))
    removed = [(t.get(i, 'style'), t.get(i, 'variant')) for i in old]
    for i in reversed(old):
        t.delete(i)
    return removed


# Centre ice as the NHL teams have it: the team's own logo (art id = team art id, WS7's ice_centerlogo_10499_cm for
# Seattle), not the generic logo 1000 the game's "NHL 32" copy and the custom team slots use.
CENTER_ICE_OWN = {'centericelogotype': -1, 'centericelogo': 0}


def seattle_center_ice(db):
    """Seattle's centre ice from its own logo: exhibitionteams 399 and customteams 499 get CENTER_ICE_OWN; the Creation
    Zone slots (customteams 400-449) keep logo 1000. Returns the number of team rows changed."""
    n = 0
    for name, index in ((TEAMS, SEATTLE_PLAY_NOW), (CUSTOM, SEATTLE)):
        t = db[name]
        row = next(i for i in range(t.count) if t.get(i, 'index') == index)
        if any(t.get(row, f) != v for f, v in CENTER_ICE_OWN.items()):
            for f, v in CENTER_ICE_OWN.items():
                t.set(row, f, v)
            n += 1
    return n


def draft_team(code):
    """`draftteam` for a player drafted by `code` (NHL.com code; 'ARI' counts as Utah): the team index, -1 for
    Seattle and teams the game has no slot for."""
    code = 'UTA' if code in ('ARI', 'PHX') else code
    slot = SLOTS.get(code, -1)
    return -1 if slot > 30 else slot


def _clean(value):
    return value.replace('™', '').strip() if isinstance(value, str) else value


def _rows_by_index(table):
    return {table.get(i, 'index'): i for i in range(table.count)}


def plan(db, schema):
    """[(table name, row, field, old, new)] still needed to set the teams up: empty when they already are (so a
    second run changes nothing)."""
    out = []
    for name, index, fields in CHANGES:
        t = db[schema.by_name(name).short]
        row = _rows_by_index(t).get(index)
        if row is None:
            raise KeyError(f"{name} has no team {index}")
        for field, value in fields.items():
            old = t.get(row, field)
            if _clean(old) != value:
                out.append((name, row, field, old, value))
    return out + _colour_plan(db, schema) + _league_plan(db, schema)


def apply(db, schema, setter=None):
    """Set the teams up. `setter(short tag, row, field, value)` writes one value (default: straight into `db`;
    the roster app passes its undoable one). Returns the plan that was applied."""
    todo = plan(db, schema)
    for name, row, field, _old, new in todo:
        short = schema.by_name(name).short
        if setter is None:
            db[short].set(row, field, new)
        else:
            setter(short, row, field, new)
    return todo


def check(db, schema):
    """Problems: the 31 NHL teams' divisions and conferences as in 2026-27 (Seattle's in customteams), Utah and
    Seattle set up."""
    problems = [f"{name} row {row}: {field} is {old!r}, expected {new!r}" for name, row, field, old, new in plan(db, schema)]
    t = db[schema.by_name(TEAMS).short]
    rows = _rows_by_index(t)
    for code, slot in SLOTS.items():
        if slot > 30:
            continue
        div, conf = t.get(rows[slot], 'divisiongroup'), t.get(rows[slot], 'conferencegroup')
        if div != DIVISION_OF[code] or conf != CONFERENCE[DIVISION_OF[code]]:
            problems.append(f"{code} (team {slot}) in division {div} / conference {conf}, expected "
                            f"{DIVISION_OF[code]} / {CONFERENCE[DIVISION_OF[code]]}")
    return problems
