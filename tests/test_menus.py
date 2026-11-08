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
    assert menus.options() == {'chel': False, 'news': True, 'hut': False}
    assert menus.options(served={'chel': True}) == {'chel': True, 'news': True, 'hut': False}
    assert menus.options({'chel': False}, {'chel': True}) == {'chel': False, 'news': True, 'hut': False}
    assert menus.options(served={'chel': False, 'news': False}) == {'chel': False, 'news': False, 'hut': False}
    with pytest.raises(menus.MenuError):
        menus.options({'woc': True})
    assert menus.record(menus.options({'chel': True}))['hidden'] == ['ULTIMATETEAM', 'HOCKEYDRAFT']
    assert menus.record(menus.options())['hidden'] == list(menus.DEAD)
    assert menus.record(menus.options())['news'] is True


def test_edits_keep_the_news_tile_by_default():
    """The news tile stays (the text pack makes it the Puck Peak line); `news` off swaps it for an EMPTY tile."""
    files = {menus.HOMEPAGE_PATH: fake_homepage(), menus.LAYOUT_PATH: fake_layout()}
    kept = menus.edits(files.__getitem__, menus.options())[menus.HOMEPAGE_PATH]
    assert menus.NEWS_ANCHOR in kept and menus.NEWS_EMPTY not in kept
    gone = menus.edits(files.__getitem__, menus.options({'news': False}))[menus.HOMEPAGE_PATH]
    assert menus.NEWS_ANCHOR not in gone and menus.NEWS_EMPTY in gone


def test_the_hut_tile_stays_hidden_unless_the_option_is_on():
    """HUT's CardHouse is scaffolding (docs/notes/hut.md): the tile is hidden like before, `hut` brings it back."""
    files = {menus.HOMEPAGE_PATH: fake_homepage(), menus.LAYOUT_PATH: fake_layout()}
    off = menus.edits(files.__getitem__, menus.options())[menus.HOMEPAGE_PATH]
    on = menus.edits(files.__getitem__, menus.options({'hut': True}))[menus.HOMEPAGE_PATH]
    assert b'[MODES_NAMES.ULTIMATETEAM] = true' in off and b'[MODES_NAMES.ULTIMATETEAM] = true' not in on
    assert b'[MODES_NAMES.HOCKEYDRAFT] = true' in on and b'[MODES_NAMES.EASHL] = true' in on
    assert menus.record(menus.options({'hut': True}))['hidden'] == ['HOCKEYDRAFT', 'EASHL']
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


# --- the zero-press launch hook (docs/plans/m2-zero-press.md) ---------------------------------------------------

UNTIL = 1893456000


def fake_hub():
    return (b'function Hub:PublishData()\r\n    local data = {}\r\n    if self.mGameMode == GAMEMODES.MODE_SHOOTOUT_ONLINE then\r\n'
            b'    end\r\n' + menus.HUB_END_ANCHOR + b'\r\nfunction Hub:_OnAdvance(evt)\r\nend\r\n')


def fake_files(end=True):
    home = fake_homepage()
    if end:
        home = home[:-len(b'end\r\n')] + menus.HOME_END_ANCHOR + b'end\r\n'
    return {menus.HOMEPAGE_PATH: home, menus.LAYOUT_PATH: fake_layout(), menus.HUB_PATH: fake_hub()}


def test_launch_off_changes_nothing_and_serves_no_hub():
    files = fake_files()
    off = menus.edits(files.__getitem__, menus.options())
    assert sorted(off) == sorted(menus.PATHS)
    assert b'OvertimeAutoplay' not in off[menus.HOMEPAGE_PATH]
    assert off[menus.HOMEPAGE_PATH] == menus.edit_homepage(files[menus.HOMEPAGE_PATH], news=True)


def test_launch_on_hooks_the_homepage_and_the_hub_inside_pcall():
    files = fake_files()
    on = menus.edits(files.__getitem__, menus.options(), {'until': UNTIL})
    assert sorted(on) == sorted(set(menus.LAUNCH_PATHS) - set(rules.PATHS.values()) - {menus.THREES_HUB_PATH})  # the rules file only when rules are named; the Threes hub only for Threes
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
    assert sorted(on) == sorted(set(menus.LAUNCH_PATHS) - {rules.SHOOTOUT_PATH, rules.THREES_PATH, menus.THREES_HUB_PATH})
    assert rules.read(on[rules.RULES_PATH])['periodlength'] == '10' and rules.read(on[rules.RULES_PATH])['icing'] == '1'
    assert menus.edits(files.__getitem__, menus.options(), {'until': UNTIL, 'rules': {}}).keys() ==         set(menus.LAUNCH_PATHS) - set(rules.PATHS.values()) - {menus.THREES_HUB_PATH}
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
