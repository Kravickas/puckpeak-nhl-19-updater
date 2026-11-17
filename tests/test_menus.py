"""The menus layer's edits of homepage.lua / homepage.layout: every anchor exactly once, CRLF kept, any other
shape refused; on the game's own files, the edit is only the inserted lines."""
import difflib

import pytest

from overtime_core import gamefiles, menus, rules
from test_rules import fake as fake_rules, shootout_file


def fake_homepage():
    """A homepage.lua with the stock lines the edit looks for, in the stock order."""
    parts = [b'local IDENTIFIER =\r\n{\r\n', menus.STOCK[4] + b'\r\n', menus.STOCK[5] + b'\r\n}\r\n',
             b'local MODES_NAMES =\r\n{\r\n'] + [s + b'\r\n' for s in menus.STOCK[1:4]] + [
             b'}\r\n    o.TITLES =\r\n    {\r\n', menus.ONLINE_TITLE, menus.TITLES_ANCHOR,
             menus.STOCK[0] + b'\r\n', b'    self.MODES = {}\r\n\r\n', menus.MODES_ANCHOR, b'\r\n',
             menus.FEATURED_ANCHOR, menus.NEWS_ANCHOR, b'end\r\n']
    return b''.join(parts)


def fake_layout():
    return (b'{\r\n    "type": "PositionItemsInGrid",\r\n    "data":\r\n    {\r\n        '
            + menus.GRID_ANCHOR + b'        "paddingH": 5\r\n    }\r\n}\r\n')


CRLF = b'\r\n'


def fake_playnow():
    return CRLF.join([menus.PLAYNOW_STOCK[0], b'    --NHL19 BETA ProAM mode should be disabled',
                      menus.PROAM_LOCK_ANCHOR + b'    return o', b'end', b'function PlayNowMenu:_Initialize()',
                      b''.join(old for old, _new in menus.DROPIN_ACTIONS) + b'    ' + menus.PLAYNOW_STOCK[1], b''])


def fake_playnow_layout():
    tiles = [(b'ProamTile', b'125.0', menus.PROAM_ART[0]), (b'ThreesTile', b'965.0', b'"type": "resort_brand_threes",'),
             (b'GauntletTile', b'545.0', b'"type": "resort_brand_outdoor1",'), (b'EASHLTile', b'1385.0', b'"type": "resort_brand_eashl",')]
    return (CRLF.join([b'{', b'    "name": "PlayNowMenu",', b'            "targets":', b'            [', b''])
            + menus.PLAYNOW_TARGETS + CRLF.join([b'            ],', b''])
            + b''.join(CRLF.join([b'            "name": "' + n + b'",', b'            "x": ' + x + b',', b'            ' + t, b''])
                       for n, x, t in tiles)
            + b'}' + CRLF)


def fake_playnow_dd():
    return CRLF.join([b'{'] + [b'    ' + old for old, _new in menus.PLAYNOW_DD_EDITS] + [b'}', b''])


def fake_dropinhub():
    return CRLF.join([menus.DROPINHUB_STOCK[0], b'end', menus.DROPINHUB_STOCK[1], b'end',
                      b'function DropInHub:Initialize()', b'']) + menus.DROPINHUB_END


def fake_eashlmenu(walk=False):
    lines = [menus.SEASONS_STOCK[0], menus.SEASONS_LOCK_ANCHOR + b'end', b'    ' + menus.SEASONS_STOCK[1],
             menus.EASHLMENU_INIT + b'end']
    if walk:
        lines.insert(0, menus.EASHLMENU_STOCK[0] + b' = ' + menus.EASHLMENU_STOCK[1] + b',')
    return CRLF.join(lines + [b''])


def fake_eashlmenu_layout():
    return (CRLF.join([b'{', b'    "name": "EASHLMenu",', b'            "targets":', b'            [', b''])
            + menus.SEASONS_TARGET + CRLF.join([b'            ],', b'            "name": "DropInTile",', b''])
            + menus.SEASONS_MARGINS[0][0] + b'            "name": "OnlineSeasonsTile",' + CRLF
            + menus.SEASONS_MARGINS[1][0] + b'}' + CRLF)


PLAYNOW_FILES = {menus.PLAYNOW_PATH: fake_playnow(), menus.PLAYNOW_LAYOUT_PATH: fake_playnow_layout(),
                 menus.EASHLMENU_PATH: fake_eashlmenu(), menus.EASHLMENU_LAYOUT_PATH: fake_eashlmenu_layout(),
                 menus.PLAYNOW_DD_PATH: fake_playnow_dd(), menus.DROPINHUB_PATH: fake_dropinhub()}


def changes(old, new):
    """[(tag, old lines, new lines)] of the line diff, equal runs left out."""
    a, b = old.split(b'\r\n'), new.split(b'\r\n')
    return [(tag, a[i1:i2], b[j1:j2]) for tag, i1, i2, j1, j2 in
            difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if tag != 'equal']


@pytest.mark.parametrize('chel', [False, True])
def test_homepage_edit(chel):
    raw = fake_homepage()
    new = menus.edit_homepage(raw, chel=chel)
    assert new.count(b'\r\n') == new.count(b'\n')
    assert new.count(menus.MARK) >= 4
    assert menus.NEWS_ANCHOR not in new and b'table.insert(auxList2,{identifier = IDENTIFIER.EMPTY})' in new
    assert new.index(b'local overtimeHidden') < new.index(menus.MODES_ANCHOR)
    assert new.index(menus.FEATURED_GUARD) < new.index(menus.FEATURED_ANCHOR)
    assert b'table.remove(o.TITLES, 3)' in new
    hidden = new.split(b'local overtimeHidden = ', 1)[1].split(b'\r\n', 1)[0]
    assert b'ULTIMATETEAM' in hidden and b'HOCKEYDRAFT' in hidden and (b'EASHL' in hidden) is not chel
    with pytest.raises(menus.MenuError):
        menus.edit_homepage(new)  # already edited


def test_homepage_keeps_news_when_asked():
    new = menus.edit_homepage(fake_homepage(), news=True)
    assert menus.NEWS_ANCHOR in new


@pytest.mark.parametrize('anchor', [menus.MODES_ANCHOR, menus.FEATURED_ANCHOR, menus.NEWS_ANCHOR,
                                    menus.TITLES_ANCHOR])
def test_homepage_refuses_anchor_twice_or_missing(anchor):
    raw = fake_homepage()
    with pytest.raises(menus.MenuError, match='found 2 times'):
        menus.edit_homepage(raw.replace(anchor, anchor + anchor))
    with pytest.raises(menus.MenuError, match='found 0 times'):
        menus.edit_homepage(raw.replace(anchor, b'-- gone\r\n'))


def test_homepage_refuses_other_shapes():
    raw = fake_homepage()
    with pytest.raises(menus.MenuError, match='CRLF'):
        menus.edit_homepage(raw.replace(b'\r\n', b'\n'))
    with pytest.raises(menus.MenuError, match='knows'):
        menus.edit_homepage(raw.replace(menus.STOCK[3], b'    EASHL = "Chel",'))
    swapped = raw.replace(menus.FEATURED_ANCHOR + menus.NEWS_ANCHOR, menus.NEWS_ANCHOR + menus.FEATURED_ANCHOR)
    with pytest.raises(menus.MenuError, match='order'):
        menus.edit_homepage(swapped)


def test_layout_edit():
    raw = fake_layout()
    new = menus.edit_layout(raw)
    assert new == raw.replace(b'"numSections": 6,', b'"numSections": 5,')
    with pytest.raises(menus.MenuError):
        menus.edit_layout(new)
    with pytest.raises(menus.MenuError):
        menus.edit_layout(raw + raw)
    with pytest.raises(menus.MenuError):
        menus.edit_layout(raw.replace(b'\r\n', b'\n'))


def test_options():
    assert menus.options() == {'chel': True, 'news': True, 'hut': False}
    assert menus.options(served={'chel': False}) == {'chel': False, 'news': True, 'hut': False}
    assert menus.options({'chel': False}, {'chel': True}) == {'chel': False, 'news': True, 'hut': False}
    assert menus.options(served={'chel': False, 'news': False}) == {'chel': False, 'news': False, 'hut': False}
    with pytest.raises(menus.MenuError):
        menus.options({'woc': True})
    assert menus.record(menus.options({'chel': True}))['hidden'] == ['ULTIMATETEAM', 'HOCKEYDRAFT']
    assert menus.record(menus.options({'chel': False}))['hidden'] == list(menus.DEAD)
    assert menus.record(menus.options())['news'] is True


def test_edits_keep_the_news_tile_by_default():
    """The news tile stays (the text pack makes it the Puck Peak line); `news` off swaps it for an EMPTY tile."""
    files = {menus.HOMEPAGE_PATH: fake_homepage(), menus.LAYOUT_PATH: fake_layout(), **PLAYNOW_FILES}
    kept = menus.edits(files.__getitem__, menus.options())[menus.HOMEPAGE_PATH]
    assert menus.NEWS_ANCHOR in kept and menus.NEWS_EMPTY not in kept
    gone = menus.edits(files.__getitem__, menus.options({'news': False}))[menus.HOMEPAGE_PATH]
    assert menus.NEWS_ANCHOR not in gone and menus.NEWS_EMPTY in gone


def test_the_hut_tile_stays_hidden_unless_the_option_is_on():
    """HUT's CardHouse is scaffolding (docs/notes/hut.md): the tile is hidden like before, `hut` brings it back."""
    files = {menus.HOMEPAGE_PATH: fake_homepage(), menus.LAYOUT_PATH: fake_layout(), **PLAYNOW_FILES}
    off = menus.edits(files.__getitem__, menus.options({'chel': False}))[menus.HOMEPAGE_PATH]
    on = menus.edits(files.__getitem__, menus.options({'hut': True, 'chel': False}))[menus.HOMEPAGE_PATH]
    assert b'[MODES_NAMES.ULTIMATETEAM] = true' in off and b'[MODES_NAMES.ULTIMATETEAM] = true' not in on
    assert b'[MODES_NAMES.HOCKEYDRAFT] = true' in on and b'[MODES_NAMES.EASHL] = true' in on
    assert menus.record(menus.options({'hut': True, 'chel': False}))['hidden'] == ['HOCKEYDRAFT', 'EASHL']
    assert menus.record(menus.options({'hut': True, 'chel': True}))['hidden'] == ['HOCKEYDRAFT']


@pytest.mark.game
@pytest.mark.parametrize('chel', [False, True])
def test_game_files_edit_is_only_insertions(game_dir, chel):
    """On the user's own homepage.lua the edit only inserts lines (and swaps the one news line); the layout edit
    is the one number."""
    raw = gamefiles.read_latest(game_dir, menus.HOMEPAGE_PATH)[0]
    new = menus.edit_homepage(raw, chel=chel)
    diff = changes(raw, new)
    assert [tag for tag, _a, _b in diff] == ['insert', 'insert', 'insert', 'replace']
    assert diff[-1][1] == [menus.NEWS_ANCHOR.rstrip(b'\r\n')]
    assert all(line.lstrip().startswith(b'-- Overtime menus') for _t, _a, b in diff for line in b[:1])
    layout = gamefiles.read_latest(game_dir, menus.LAYOUT_PATH)[0]
    assert menus.edit_layout(layout) == layout.replace(b'"numSections": 6,', b'"numSections": 5,')


def test_the_play_menu_has_three_tiles_with_drop_in_3s_and_6s():
    """World of Chel's PLAY menu: Threes | Drop-in 3s (the Pro-Am slot, unlocked) | Drop-in 6s (the EASHL slot), Ones
    hidden (0.97.0: off the cursor and the canvas, its action does nothing); each Drop-in tile names its room and opens
    the EASHL menu; served with every build."""
    lua = menus.edit_playnow(fake_playnow())
    assert lua.count(b'o.mProAmModeLocked = false') == 1 and lua.count(b'_G.OvertimeDropIn = nil') == 1
    assert b"_G.OvertimeDropIn = '3s'; self:_OnAdvanceEASHL()" in lua and b"_G.OvertimeDropIn = '6s'; self:_OnAdvanceEASHL()" in lua
    assert b'EVENTS.GAUNTLET' not in lua and b'RegisterAction(ACTIONS.GAUNTLET, function() end)' in lua
    lay = menus.edit_playnow_layout(fake_playnow_layout())
    assert menus.PLAYNOW_ORDER in lay and menus.PROAM_ART[0] not in lay and b'"GauntletTile"' not in lay.split(b']')[0]
    for name, (_old, new) in menus.TILE_X.items():
        at = lay.index(b'"name": "' + name + b'",')
        assert lay.index(b'"x": ' + new + b',', at) < (lay.find(b'"name": "', at + 1) % (len(lay) + 1))
    dd = menus.edit_playnow_dd(fake_playnow_dd())
    assert all(new in dd and old not in dd for old, new in menus.PLAYNOW_DD_EDITS)
    hub = menus.edit_dropinhub_direct(fake_dropinhub())
    assert b"if room == '6s' then s:_OpenPlayers6s() else s:_OpenPlayers3s() end" in hub
    assert hub.endswith(b'end' + CRLF) and menus.DROPINHUB_END not in hub
    with pytest.raises(menus.MenuError):
        menus.edit_playnow(lua)
    with pytest.raises(menus.MenuError):
        menus.edit_playnow_layout(lay)
    for opts in (menus.options({'chel': False}), menus.options()):
        out = menus.edits(fake_files().__getitem__, opts)
        assert out[menus.PLAYNOW_PATH] == lua and out[menus.PLAYNOW_LAYOUT_PATH] == lay and out[menus.PLAYNOW_DD_PATH] == dd
        assert out[menus.DROPINHUB_PATH] == hub


@pytest.mark.game
def test_the_play_menu_edit_on_the_games_own_files(game_dir):
    import json
    read = lambda path: gamefiles.read_latest(game_dir, path)[0]
    lay = json.loads(menus.edit_playnow_layout(read(menus.PLAYNOW_LAYOUT_PATH)))
    sel = next(b for b in lay['behaviors'] if b['name'] == 'SelectionManager')
    assert sel['targets'] == ['ThreesTile', 'ProamTile', 'EASHLTile']
    assert {c['name']: c['x'] for c in lay['children']} == {'ProamTile': 755.0, 'GauntletTile': 6000.0,
                                                           'ThreesTile': 335.0, 'EASHLTile': 1175.0}
    assert next(c for c in lay['children'] if c['name'] == 'ProamTile')['type'] == 'resort_brand_eashl'
    json.loads(menus.edit_playnow_dd(read(menus.PLAYNOW_DD_PATH)))
    menus.edit_dropinhub_direct(read(menus.DROPINHUB_PATH))
    raw = read(menus.PLAYNOW_PATH)
    assert [tag for tag, _a, _b in changes(raw, menus.edit_playnow(raw))] == ['insert', 'replace']   # the 3 actions in a row


# --- the zero-press launch hook (docs/plans/m2-zero-press.md) ---------------------------------------------------

UNTIL = 1893456000


def fake_hub():
    return (b'function Hub:PublishData()\r\n    local data = {}\r\n    if self.mGameMode == GAMEMODES.MODE_SHOOTOUT_ONLINE then\r\n'
            b'    end\r\n' + menus.HUB_END_ANCHOR + b'\r\nfunction Hub:_OnAdvance(evt)\r\nend\r\n')


def fake_files(end=True):
    home = fake_homepage()
    if end:
        home = home[:-len(b'end\r\n')] + menus.HOME_END_ANCHOR + b'end\r\n'
    return {menus.HOMEPAGE_PATH: home, menus.LAYOUT_PATH: fake_layout(), menus.HUB_PATH: fake_hub(), **PLAYNOW_FILES}


def test_launch_off_changes_nothing_and_serves_no_hub():
    files = fake_files()
    off = menus.edits(files.__getitem__, menus.options({'chel': False}))
    assert sorted(off) == sorted(menus.PATHS)
    assert b'OvertimeAutoplay' not in off[menus.HOMEPAGE_PATH]
    assert off[menus.HOMEPAGE_PATH] == menus.edit_homepage(files[menus.HOMEPAGE_PATH], news=True)


def test_launch_on_hooks_the_homepage_and_the_hub_inside_pcall():
    files = fake_files()
    on = menus.edits(files.__getitem__, menus.options(), {'until': UNTIL})
    assert sorted(on) == sorted(set(menus.LAUNCH_PATHS) - set(rules.PATHS.values()) - {menus.THREES_HUB_PATH} - (set(menus.CHEL_WALK_PATHS) - set(menus.PATHS)))  # the rules file only when rules are named; the Threes hub only for Threes
    home, hub = on[menus.HOMEPAGE_PATH], on[menus.HUB_PATH]
    for lua in (home, hub):
        assert b'pcall(function()' in lua and b'os.time() <= %d' % UNTIL in lua
        assert lua.count(b'\r\n') == lua.count(b'\n')
        assert lua.index(b'pcall') < lua.index(b'_G.OvertimeAutoplay')
    assert b'_G.OvertimeAutoplay == nil' in home and b'afterMovieTarget = "evt_playonline"' in home
    # the global flag: the hub only follows a homepage jump and only for the Online Versus hub
    assert b"_G.OvertimeAutoplay == 'home'" in hub and b'GAMEMODES.' + menus.HUB_MODE.encode() in hub
    assert hub.index(b'self:_OnAdvance(EVENTS.PLAYNOW_ONLINE)') > hub.index(b'pcall')
    # the hook sits at the end of the function it hooks, before its `end`
    assert home.rindex(b'end\r\n') > home.index(b'Overtime autoplay')
    assert hub.index(b'Overtime autoplay') > hub.index(b'BUTTONS_FONT_STYLE')


def test_launch_rules_serve_the_rules_file_with_those_defaults():
    files = {**fake_files(), rules.RULES_PATH: fake_rules()}
    on = menus.edits(files.__getitem__, menus.options(), {'until': UNTIL, 'rules': {'periodlength': 10, 'icing': 1}})
    assert sorted(on) == sorted(set(menus.LAUNCH_PATHS) - {rules.SHOOTOUT_PATH, rules.THREES_PATH, menus.THREES_HUB_PATH} - (set(menus.CHEL_WALK_PATHS) - set(menus.PATHS)))
    assert rules.read(on[rules.RULES_PATH])['periodlength'] == '10' and rules.read(on[rules.RULES_PATH])['icing'] == '1'
    assert menus.edits(files.__getitem__, menus.options(), {'until': UNTIL, 'rules': {}}).keys() ==         set(menus.LAUNCH_PATHS) - set(rules.PATHS.values()) - {menus.THREES_HUB_PATH} - (set(menus.CHEL_WALK_PATHS) - set(menus.PATHS))
    with pytest.raises(menus.MenuError, match='pick one'):
        menus.edits(files.__getitem__, menus.options(), {'until': UNTIL, 'rules': {'periodlength': 7}})
    with pytest.raises(menus.MenuError, match='0 times'):
        menus.edits({**files, rules.RULES_PATH: b'{}'}.__getitem__, menus.options(), {'until': UNTIL, 'rules': {'icing': 1}})
    rec = menus.record(menus.options(), {'until': UNTIL, 'rules': {'periodlength': 10}})
    assert rec['rules'] == {'periodlength': '10'} and 'rules' not in rec['options']
    assert 'rules' not in menus.record(menus.options(), {'until': UNTIL}) and 'rules' not in menus.record(menus.options())


def test_launch_diag_puts_the_clock_in_the_last_title():
    files = fake_files()
    plain = menus.edits(files.__getitem__, menus.options(), {'until': UNTIL})[menus.HOMEPAGE_PATH]
    diag = menus.edits(files.__getitem__, menus.options(), {'until': UNTIL, 'diag': True})[menus.HOMEPAGE_PATH]
    assert b'os.time ' not in plain and b"'os.time ' .. tostring(os.time())" in diag
    assert diag.index(b'o.TITLES[#o.TITLES].Text') > diag.index(b'table.insert(o.TITLES, { Text = "" })')


def test_launch_refuses_other_shapes():
    files = fake_files(end=False)
    with pytest.raises(menus.MenuError, match='found 0 times'):
        menus.edits(files.__getitem__, menus.options(), {'until': UNTIL})
    files = fake_files()
    files[menus.HUB_PATH] = files[menus.HUB_PATH].replace(menus.HUB_END_ANCHOR, b'')
    with pytest.raises(menus.MenuError, match='hub.lua'):
        menus.edits(files.__getitem__, menus.options(), {'until': UNTIL})
    files = fake_files()
    files[menus.HUB_PATH] = files[menus.HUB_PATH].replace(b'\r\n', b'\n')
    with pytest.raises(menus.MenuError, match='CRLF'):
        menus.edits(files.__getitem__, menus.options(), {'until': UNTIL})


def test_launch_is_never_an_option_nor_served_on():
    with pytest.raises(menus.MenuError):
        menus.options({'autoplay_until': UNTIL})
    rec = menus.record(menus.options(), {'until': UNTIL})
    assert rec['autoplay_until'] == UNTIL and 'autoplay_until' not in rec['options']
    assert 'autoplay_until' not in menus.record(menus.options())


@pytest.mark.game
def test_launch_on_the_games_own_files_is_only_insertions(game_dir):
    read = lambda path: gamefiles.read_latest(game_dir, path)[0]
    hub = read(menus.HUB_PATH)
    new = menus.edit_hub(hub, UNTIL)
    diff = changes(hub, new)
    assert [tag for tag, _a, _b in diff] == ['insert']
    home = menus.edit_homepage(read(menus.HOMEPAGE_PATH), launch={'until': UNTIL, 'diag': True})
    plain = menus.edit_homepage(read(menus.HOMEPAGE_PATH))
    assert [tag for tag, _a, _b in changes(plain, home)] == ['insert', 'insert']


def test_a_shootout_launch_jumps_into_the_shootout_hub():
    files = fake_files()
    on = menus.edits(files.__getitem__, menus.options(), {'until': UNTIL, 'mode': 'shootout'})
    home, hub = on[menus.HOMEPAGE_PATH], on[menus.HUB_PATH]
    assert b'afterMovieTarget = "evt_goto_online_shootout"' in home and b'evt_playonline' not in home
    assert b'GAMEMODES.MODE_SHOOTOUT_ONLINE' in hub and menus.HUB_MODE.encode() not in hub
    assert b"_G.OvertimeAutoplay == 'home'" in hub and b'self:_OnAdvance(EVENTS.PLAYNOW_ONLINE)' in hub
    assert menus.edits(files.__getitem__, menus.options(), {'until': UNTIL, 'mode': 'versus'})[menus.HUB_PATH] ==         menus.edits(files.__getitem__, menus.options(), {'until': UNTIL})[menus.HUB_PATH]
    with pytest.raises(menus.MenuError, match='unknown game mode'):
        menus.edits(files.__getitem__, menus.options(), {'until': UNTIL, 'mode': 'hut'})


def test_a_chel_launch_serves_the_tile_with_the_switch_off_and_no_hook():
    """A CHEL lobby launch (0.90.0): the World of Chel tile whatever the player's own switch, no hub hook, no rules."""
    files = {**fake_files()}
    off = menus.options({'chel': False})
    on = menus.edits(files.__getitem__, off, {'until': UNTIL, 'mode': 'chel'})
    assert set(on) == set(menus.PATHS)
    assert b'[MODES_NAMES.EASHL] = true' not in on[menus.HOMEPAGE_PATH]
    assert b'[MODES_NAMES.EASHL] = true' in menus.edits(files.__getitem__, off)[menus.HOMEPAGE_PATH]
    assert on[menus.HOMEPAGE_PATH] == menus.edits(files.__getitem__, menus.options({'chel': True}))[menus.HOMEPAGE_PATH]
    assert 'rules' not in menus.record(off, {'until': UNTIL, 'mode': 'chel', 'rules': {'skilllevel': 4}})


@pytest.mark.game
def test_a_chel_launch_on_the_games_own_files(game_dir):
    read = lambda path: gamefiles.read_latest(game_dir, path)[0]
    on = menus.edits(read, menus.options({'chel': False}), {'until': UNTIL, 'mode': 'chel'})
    assert b'[MODES_NAMES.EASHL] = true' not in on[menus.HOMEPAGE_PATH]
    assert on[menus.HOMEPAGE_PATH] == menus.edits(read, menus.options({'chel': True}))[menus.HOMEPAGE_PATH]
    assert {tag for tag, _a, _b in changes(read(menus.HOMEPAGE_PATH), on[menus.HOMEPAGE_PATH])} <= {'insert', 'replace'}


def test_shootout_launch_rules_serve_the_shootout_file_only():
    files = {**fake_files(), rules.SHOOTOUT_PATH: shootout_file()}
    launch = {'until': UNTIL, 'mode': 'shootout', 'rules': {'skilllevel': 4, 'goaliecontrol': 0}}
    on = menus.edits(files.__getitem__, menus.options(), launch)
    assert rules.RULES_PATH not in on and rules.SHOOTOUT_PATH in on
    assert rules.read(on[rules.SHOOTOUT_PATH])['skilllevel'] == '4' and b'"defaultvalue": "5"' in on[rules.SHOOTOUT_PATH]
    rec = menus.record(menus.options(), launch)
    assert rec['rules'] == {'skilllevel': '4', 'goaliecontrol': '0'} and rec['autoplay_mode'] == 'shootout'
    with pytest.raises(menus.MenuError, match='pick one|Unknown'):
        menus.edits(files.__getitem__, menus.options(), {'until': UNTIL, 'mode': 'shootout', 'rules': {'periodlength': 10}})
    assert menus.record(menus.options(), {'until': UNTIL})['autoplay_mode'] == 'versus'


# --- 0.96.0 Phase 4: the World of Chel auto-walk ---------------------------------------------------------------------
def fake_chel_files():
    return {**fake_files(), menus.PLAYNOW_PATH: fake_playnow(),
            menus.MAINHUB_PATH: CRLF.join([menus.MAINHUB_STOCK[0], menus.MAINHUB_SHOW + b'end',
                                           menus.MAINHUB_INPUTS + b'end', menus.MAINHUB_STOCK[1], b'end', b'']),
            menus.EASHLMENU_PATH: fake_eashlmenu(walk=True),
            menus.DROPINHUB_PATH: fake_dropinhub(),
            menus.GAUNTLETHUB_PATH: CRLF.join([menus.GAUNTLETHUB_STOCK[2], menus.GAUNTLETHUB_STOCK[0], b'end',
                                               b'x = ' + menus.GAUNTLETHUB_STOCK[1], menus.GAUNTLETHUB_DATA + b'end', b'']),
            menus.DRESSINGROOM_PATH: CRLF.join(list(menus.DRESSINGROOM_STOCK) + [b'end', b'function DressingRoomFlow:new(init)',
                                                b'']) + menus.DRESSINGROOM_NEW_END}


def walk(files, chel):
    return menus.edits(files.__getitem__, menus.options({'chel': False}), {'until': UNTIL, 'mode': 'chel', 'chel': chel})


def test_a_chel_launch_walks_to_the_lobbys_drop_in_mode():
    files = fake_chel_files()
    six, three, gm = (walk(files, m) for m in (rules.CHEL_DROPIN, rules.CHEL_DROPIN3, rules.CHEL_GM3ON3))
    home = six[menus.HOMEPAGE_PATH]
    assert b'afterMovieTarget = "evt_eashl"' in home and b'_G.OvertimeChelStep = 1' in home
    assert b'[MODES_NAMES.EASHL] = true' not in home                        # the tile is on
    assert set(six) == set(three) == set(menus.PATHS) | {menus.MAINHUB_PATH}
    assert set(gm) == set(menus.PATHS) | {menus.MAINHUB_PATH}                # Drop-in Threes: straight from PLAY
    assert b's.nav.Event(nil, EVENTS.PLAY, nil)' in six[menus.MAINHUB_PATH]
    assert b'self.mOvertimeInputs = newstate' in six[menus.MAINHUB_PATH]
    assert b's:_OnAdvanceEASHL()' in six[menus.PLAYNOW_PATH] and b's:_OnAdvance(EVENTS.THREES)' in gm[menus.PLAYNOW_PATH]
    assert b'o.mProAmModeLocked = false' in gm[menus.PLAYNOW_PATH]           # the Pro-Am slot is Drop-in 3s
    assert b's:_OnAdvance(EVENTS.DROPIN)' in six[menus.EASHLMENU_PATH]
    assert b'self.mOnlineSeasonsLocked = true' in six[menus.EASHLMENU_PATH]   # Online Seasons stays locked
    assert b's:_OpenPlayers6s()' in six[menus.DROPINHUB_PATH] and b's:_OpenPlayers3s()' in three[menus.DROPINHUB_PATH]
    for out in (six, three, gm):
        for raw in out.values():
            assert raw.count(b'\r\n') == raw.count(b'\n')
    steps = [b'< %d and' % n for n in (2, 3, 4, 5)]
    assert all(s in b''.join(six.values()) for s in steps)


def test_a_chel_launch_walks_ones_through_its_hub():
    files = fake_chel_files()
    ones = walk(files, rules.CHEL_ONES)
    assert set(ones) == set(menus.PATHS) | {menus.MAINHUB_PATH, menus.GAUNTLETHUB_PATH}
    assert b's:_OnAdvance(EVENTS.GAUNTLET)' in ones[menus.PLAYNOW_PATH]
    hub = ones[menus.GAUNTLETHUB_PATH]
    assert b's:_GotoPlayNow()' in hub and b'< 4 and' in hub and b'HUB_STATE.BLACK_OUT' in hub
    assert hub.index(menus.GAUNTLETHUB_DATA) < hub.index(b's:_GotoPlayNow()')
    assert hub.count(CRLF) == hub.count(b'\n')


def test_auto_ready_readies_and_searches_in_the_dressing_room_only_when_asked():
    files = fake_chel_files()
    for chel in (rules.CHEL_DROPIN, rules.CHEL_DROPIN3, rules.CHEL_GM3ON3, rules.CHEL_ONES):
        assert menus.DRESSINGROOM_PATH not in walk(files, chel)               # a PC with a picture presses by hand
        on = menus.edits(files.__getitem__, menus.options({'chel': False}),
                         {'until': UNTIL, 'mode': 'chel', 'chel': chel, 'auto_ready': True})
        room = on[menus.DRESSINGROOM_PATH]
        assert room.count(CRLF) == room.count(b'\n') and room.endswith(b'    return o\r\nend\r\n')
        assert room.index(b'    o:initialize()') < room.index(b'o.update = function') < room.rindex(b'return o')
        for press in (b's:HandleSelectPosition(nil, dev)', b's:HandleReady(PRESENCE_IDS.READY, dev)',
                      b's:HandleStartMatchMaking()', b'it.Position ~= goalie', b'os.time() > %d' % UNTIL):
            assert press in room
    plain = menus.edits(files.__getitem__, menus.options({'chel': False}),
                        {'until': UNTIL, 'mode': 'chel', 'chel': rules.CHEL_PROAM, 'auto_ready': True})
    assert menus.DRESSINGROOM_PATH not in plain                               # no walk, no auto-ready


def test_a_chel_launch_of_another_mode_serves_the_tile_only():
    files = fake_chel_files()
    plain = menus.edits(files.__getitem__, menus.options({'chel': False}), {'until': UNTIL, 'mode': 'chel'})
    assert walk(files, rules.CHEL_PROAM) == plain and set(plain) == set(menus.PATHS)
    assert b'evt_eashl' not in plain[menus.HOMEPAGE_PATH]


@pytest.mark.game
def test_the_chel_walk_on_the_games_own_files_only_inserts(game_dir):
    read = lambda path: gamefiles.read_latest(game_dir, path)[0]
    for chel in (rules.CHEL_DROPIN, rules.CHEL_DROPIN3, rules.CHEL_GM3ON3, rules.CHEL_ONES):
        on = menus.edits(read, menus.options({'chel': False}), {'until': UNTIL, 'mode': 'chel', 'chel': chel})
        for path in menus.CHEL_WALK_PATHS:
            if path in on:
                assert {tag for tag, _a, _b in changes(read(path), on[path])} == {'insert'}


def test_the_eashl_menu_loses_the_online_seasons_tile():
    lua = menus.edit_eashlmenu_seasons(fake_eashlmenu())
    assert b'    self.mOnlineSeasonsLocked = true' in lua
    lay = menus.edit_eashlmenu_layout(fake_eashlmenu_layout())
    assert b'                "OnlineSeasonsTile"' not in lay and b'"name": "OnlineSeasonsTile",' in lay
    assert b'"marginRight": 460.0' not in lay and b'"marginLeft": 6000.0' in lay
    with pytest.raises(menus.MenuError):
        menus.edit_eashlmenu_seasons(lua)
    for opts in (menus.options({'chel': False}), menus.options()):
        out = menus.edits(fake_files().__getitem__, opts)
        assert out[menus.EASHLMENU_PATH] == lua and out[menus.EASHLMENU_LAYOUT_PATH] == lay


@pytest.mark.game
def test_the_eashl_menu_edit_on_the_games_own_files(game_dir):
    import json
    read = lambda path: gamefiles.read_latest(game_dir, path)[0]
    lay = json.loads(menus.edit_eashlmenu_layout(read(menus.EASHLMENU_LAYOUT_PATH)))
    assert next(b for b in lay['behaviors'] if b['name'] == 'SelectionManager')['targets'] == ['DropInTile']
    assert {c['name']: c.get('marginLeft') for c in lay['children']} == {'DropInTile': None, 'OnlineSeasonsTile': 6000.0}
    raw = read(menus.EASHLMENU_PATH)
    assert [tag for tag, _a, _b in changes(raw, menus.edit_eashlmenu_seasons(raw))] == ['insert', 'insert']
