"""The shadPS4 builds (overtime_roster.app.boost, Setup's Boost performance card, the header's Play NHL 19): Kravickas and
Nightly from a local release fixture into the app's own folder; QtLauncher's files (apps before 0.90.2)."""
import hashlib
import json
import os
import pathlib
import re
import zipfile

import pytest

from overtime_core import art, overlay
from overtime_roster.app import boost, gamesetup, packdownload, setup_controller as SC

from test_setup_controller import sc, world  # noqa: F401  (fixtures)

BUILD = b'MZ the Kravickas build'
NIGHTLY = b'MZ the Nightly build'
NATIVE2 = b'MZ the Native v2 build'
OWN = 'D:/PS4/PS4 Emulator/shadPS4.exe'
INI = f'[general]\r\nx=1\r\n\r\n[version_manager]\r\nversionPath=D:/v\r\nversionSelected={OWN}\r\n'
THEIR_ENTRY = {'codename': 'Local', 'date': '2026-11-01', 'name': 'NHL 19', 'path': OWN, 'type': 2}
INSTALL = boost.install         # the real one (test_setup_controller's sc fixture fakes it)


def release(root, content=BUILD, names=('shadPS4.exe',), nightly=NIGHTLY, native2=NATIVE2):
    """A release folder with the three builds as packs (nightly / native2 None: that one is not served); latest.json's
    URL."""
    (root / 'packs').mkdir(parents=True, exist_ok=True)
    packs, sums = {}, ''
    for name, body in ((boost.PACK, content), (packdownload.NIGHTLY_PACK, nightly),
                       (packdownload.NATIVE2_PACK, native2)):
        if body is None:
            continue
        pack = root / 'packs' / name
        with zipfile.ZipFile(pack, 'w') as z:
            for member in (names if name == boost.PACK else ('shadPS4.exe',)):
                z.writestr(member, body)
        data = pack.read_bytes()
        packs[name] = {'file': f'packs/{name}', 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
        sums += f"{packs[name]['sha256']}  packs/{name}\n"
    (root / 'latest.json').write_text(json.dumps({'version': '0.30.0', 'packs': packs}))
    (root / 'SHA256SUMS.txt').write_text(sums)
    return pathlib.Path(root / 'latest.json').as_uri()


@pytest.fixture
def launcher(world):  # noqa: F811
    data = pathlib.Path(os.environ['APPDATA']) / gamesetup.LAUNCHER_DATA
    data.mkdir()
    (data / 'qt_ui.ini').write_bytes(INI.encode())
    (data / 'versions.json').write_text(json.dumps([THEIR_ENTRY]))
    return data


@pytest.fixture
def served(world, monkeypatch):  # noqa: F811
    url = release(world['tmp'] / 'release')
    monkeypatch.setenv('OVERTIME_RELEASE_URL', url)
    monkeypatch.delenv('OVERTIME_ART_PACKS', raising=False)
    monkeypatch.setattr(overlay, 'launcher_running', lambda: False)
    monkeypatch.setattr(SC, 'patch_cache', lambda: str(world['tmp'] / 'cache'))
    monkeypatch.setattr(boost, 'install', INSTALL)
    packdownload.forget()
    yield world['tmp'] / 'release'
    packdownload.forget()


@pytest.fixture
def started(sc, monkeypatch):  # noqa: F811
    """Play's start, recorded (no shadPS4 runs; the game counts as patched: no Question)."""
    from overtime_roster.app import patch_ctl
    runs = []
    monkeypatch.setattr(patch_ctl, 'start', lambda setup: runs.append(setup.emulator) or {'ok': True})
    return runs


def card_of(sc):  # noqa: F811
    return sc._boost_card(sc.known_emulator())


def versions(data):
    return json.loads((data / 'versions.json').read_text())


def test_the_launcher_selects_the_build_and_gets_its_own_selection_back(launcher):
    exe = r'C:\app\boost\shadPS4.exe'
    assert gamesetup.launcher_add(exe, boost.ENTRY) == OWN
    assert versions(launcher)[0] == THEIR_ENTRY                     # a player's own "NHL 19" stays
    new = versions(launcher)[1]
    assert (new['name'], new['path'], new['type'], new['codename']) == (boost.ENTRY, 'C:/app/boost/shadPS4.exe', 2,
                                                                        'Local')
    assert b'versionSelected=C:/app/boost/shadPS4.exe\r\n' in (launcher / 'qt_ui.ini').read_bytes()
    assert (launcher / 'qt_ui.ini.overtime-backup').read_bytes() == INI.encode()
    assert json.loads((launcher / 'versions.json.overtime-backup').read_text()) == [THEIR_ENTRY]
    gamesetup.launcher_add(exe, boost.ENTRY)                        # again (an update): one entry, the backup stays
    assert len(versions(launcher)) == 2 and (launcher / 'qt_ui.ini.overtime-backup').read_bytes() == INI.encode()
    gamesetup.launcher_remove(exe, OWN)
    assert versions(launcher) == [THEIR_ENTRY]
    assert (launcher / 'qt_ui.ini').read_bytes() == INI.encode()


def test_a_selection_the_player_changed_since_stays(launcher):
    exe = r'C:\app\boost\shadPS4.exe'
    gamesetup.launcher_add(exe, boost.ENTRY)
    ini = (launcher / 'qt_ui.ini').read_bytes().replace(b'C:/app/boost/shadPS4.exe', b'D:/other/shadPS4.exe')
    (launcher / 'qt_ui.ini').write_bytes(ini)
    gamesetup.launcher_remove(exe, OWN)
    assert (launcher / 'qt_ui.ini').read_bytes() == ini and versions(launcher) == [THEIR_ENTRY]


def test_the_setting_goes_in_when_the_launcher_never_selected_one(world):  # noqa: F811
    data = pathlib.Path(os.environ['APPDATA']) / gamesetup.LAUNCHER_DATA
    data.mkdir()
    for text, want in (('[general]\n', '[version_manager]\nversionSelected=C:/b.exe\n'),
                       ('[version_manager]\nversionPath=D:/v\n',
                        '[version_manager]\nversionSelected=C:/b.exe\nversionPath=D:/v\n')):
        (data / 'qt_ui.ini').write_bytes(text.encode())
        assert gamesetup.launcher_add('C:/b.exe', 'x') == ''
        assert want.encode() in (data / 'qt_ui.ini').read_bytes()


def test_no_launcher_and_a_broken_version_list_change_nothing(launcher):
    (launcher / 'versions.json').write_text('{not json')
    with pytest.raises(ValueError):
        gamesetup.launcher_add('C:/b.exe', 'x')
    assert (launcher / 'qt_ui.ini').read_bytes() == INI.encode()
    (launcher / 'qt_ui.ini').unlink()
    assert gamesetup.launcher_add('C:/b.exe', 'x') is None


def test_the_way_back_survives_a_lost_record(launcher):
    exe = r'C:\app\boost\shadPS4.exe'
    gamesetup.launcher_add(exe, boost.ENTRY)
    assert gamesetup.launcher_add(exe, boost.ENTRY) == OWN          # the app forgot it was on: enable again
    gamesetup.launcher_remove(exe, None)                            # or off with no record at all
    assert versions(launcher) == [THEIR_ENTRY]
    assert (launcher / 'qt_ui.ini').read_bytes() == INI.encode()


@pytest.mark.parametrize('content, names', [(BUILD, ('readme.txt',)), (b'PK not a program', ('shadPS4.exe',)),
                                            (BUILD, ('shadPS4.exe', 'old/shadPS4.exe'))])
def test_only_one_windows_program_passes_as_the_pack(tmp_path, content, names):
    release(tmp_path, content, names)
    with pytest.raises(art.ArtError):
        packdownload.check_emulator(str(tmp_path / 'packs' / boost.PACK))


def test_the_nightly_pack_is_checked_as_a_program_pack():
    assert packdownload.NIGHTLY_PACK in packdownload.TOOL_PACKS
    assert packdownload.CHECKS[packdownload.NIGHTLY_PACK] is packdownload.check_emulator
    assert packdownload.NATIVE2_PACK in packdownload.TOOL_PACKS
    assert packdownload.CHECKS[packdownload.NATIVE2_PACK] is packdownload.check_emulator
    assert len({boost.exe_path(b) for b in boost.BUILDS}) == 3 and boost.build_of(boost.exe_path('native2')) == 'native2'
    assert boost.exe_path('nightly') != boost.exe_path('kravickas') == boost.exe_path()
    assert boost.build_of(boost.exe_path('nightly')) == 'nightly' and boost.build_of(OWN) is None


def test_play_gets_overtime_native_v2_by_default_and_keeps_the_players_own(sc, served, world, started):  # noqa: F811
    # owner 2026-11-16: the dropdown lists Overtime Native v2 (the default), v1 (id 'nightly', the default from 0.92.0)
    # and Kravickas; the card's Update is for Kravickas only
    own = str(world['emu'])
    sc.setup_set_emulator(own)
    card = card_of(sc)
    assert boost.DEFAULT == 'native2' and boost.BUILDS['native2']['label'] == 'Overtime Native v2'
    assert card['build'] == 'native2' and [b['id'] for b in card['builds']] == ['native2', 'nightly', 'kravickas']
    assert [b['label'] for b in card['builds']] == ['Overtime Native v2', 'Overtime Native v1', 'Kravickas']
    assert [b['updatable'] for b in card['builds']] == [False, False, True]
    assert not card['can_update'] and not card['updatable'] and 'downloads it first' in card['text']
    assert sc.play_state()['can']
    sc.setup_play()
    exe = boost.exe_path('native2')
    assert pathlib.Path(exe).read_bytes() == NATIVE2 and started == [exe]
    assert sc.emulator == exe and sc.boost['emulator'] == own and card_of(sc)['playing'] == 'native2'
    assert pathlib.Path(own).read_bytes() == b'MZ'                  # a player's exe is never touched
    sc.setup_play()                                                 # here and current: no download, starts again
    assert started == [exe, exe]


def test_a_build_click_stays_chosen_without_a_warning_and_switches_when_here(sc, served, world, started):  # noqa: F811
    sc.setup_set_emulator(str(world['emu']))
    sc.setup_build('kravickas')
    assert sc.build == 'kravickas' and sc.ctl.prefs['setup']['build'] == 'kravickas'
    assert sc.ctl.said[-1] == ('Kravickas chosen: Play NHL 19 gets it first.', 'good')
    assert sc.emulator == str(world['emu'])                         # not here yet: Play gets it
    sc.setup_play()
    k = boost.exe_path('kravickas')
    assert pathlib.Path(k).read_bytes() == BUILD and started == [k]
    sc.setup_build('nightly')                                       # not here: the next Play downloads it
    text, tone = sc.ctl.said[-1]                                    # no experimental warning any more (owner 2026-11-13)
    assert tone == 'good' and text == 'Overtime Native v1 chosen: Play NHL 19 gets it first.' and sc.emulator == k
    sc.setup_play()
    sc.setup_build('kravickas')                                     # both here now: the click switches at once
    assert sc.emulator == k and card_of(sc)['build'] == 'kravickas'
    assert SC.SetupController(sc.ctl).build == 'kravickas'          # the next start of the app remembers it
    sc.setup_build('nightly')
    assert sc.ctl.said[-1] == ('NHL 19 plays on the Overtime Native v1 build of shadPS4.', 'good')


def test_apps_before_0920_move_to_overtime_native_and_apply_everywhere_once(sc):  # noqa: F811
    sc.ctl.prefs['setup'] = {'build': 'kravickas', 'replays60': False}   # a 0.91.1 player: Kravickas, the switch off
    again = SC.SetupController(sc.ctl)
    assert again.build == 'native2' and again.replays60
    again._remember()
    assert sc.ctl.prefs['setup']['rebuild'] == SC.REBUILD
    again.setup_build('kravickas')
    again.setup_everywhere(False)
    later = SC.SetupController(sc.ctl)                              # chosen after 0.92.0: kept
    assert later.build == 'kravickas' and not later.replays60


def test_players_on_overtime_native_v1_move_to_v2_once(sc):  # noqa: F811
    # owner 2026-11-16: v2 is the default; v1 was the default before, so its players are put on v2 once
    sc.ctl.prefs['setup'] = {'build': 'nightly', 'rebuild': SC.REBUILD}
    again = SC.SetupController(sc.ctl)
    assert again.build == 'native2'
    again.setup_build('nightly')                                    # chosen after the move: kept
    assert sc.ctl.prefs['setup'][SC.V2_MOVE] is True and SC.SetupController(sc.ctl).build == 'nightly'
    sc.ctl.prefs['setup'] = {'build': 'kravickas', 'rebuild': SC.REBUILD}
    assert SC.SetupController(sc.ctl).build == 'kravickas'           # another pick is left alone


def test_the_card_shows_only_the_kravickas_source_button_and_no_experimental_text():
    page = (pathlib.Path(SC.__file__).parents[1] / 'web' / 'js' / 'tabs' / 'setup.js').read_text(encoding='utf-8')
    assert 'experimental' not in page.lower() and 'su-exp' not in page and 'Nightly' not in page
    assert '.filter((x) => x.updatable)' in page                    # source buttons: the Kravickas one
    assert 'github.com/MatusRiedl/shadPS4, branch overtime-nightly' in page     # GPL-2.0: Native's source, in the Info
    assert 'github.com/MatusRiedl/shadPS4, branch overtime-native-v2' in page


def test_each_build_has_its_own_source_code(sc, monkeypatch):  # noqa: F811
    opened = []
    monkeypatch.setattr(SC.webbrowser, 'open', opened.append)
    sc.setup_boost_source('kravickas')
    sc.setup_boost_source('nightly')
    assert opened == [boost.BUILDS['kravickas']['source'], boost.BUILDS['nightly']['source']]
    assert 'Kravickas/shadPS4' in opened[0] and 'overtime-nightly' in opened[1]


def test_a_newer_build_is_offered_and_play_gets_it(sc, served, world, started):  # noqa: F811
    sc.setup_set_emulator(str(world['emu']))
    sc.setup_build('kravickas')
    sc.setup_play()
    release(served, b'MZ newer')
    packdownload.forget()
    sc._scan()
    card = card_of(sc)
    assert next(b for b in card['builds'] if b['id'] == 'kravickas')['newer']
    assert card['can_update'] and 'Press Update' in card['text']
    sc.setup_play()
    assert pathlib.Path(boost.exe_path('kravickas')).read_bytes() == b'MZ newer'
    assert not any(b['newer'] for b in card_of(sc)['builds'])


def test_play_gets_a_newly_published_overtime_native_without_the_update_button(sc, served, world, started):  # noqa: F811
    # Overtime publishes it with its releases: no Update for it, but Play still moves everyone to the one exe the
    # lobby pin and the matchmaking tag need
    sc.setup_set_emulator(str(world['emu']))
    sc.setup_play()
    release(served, native2=b'MZ native 2 newer')
    packdownload.forget()
    sc._scan()
    card = card_of(sc)
    assert next(b for b in card['builds'] if b['id'] == 'native2')['newer'] and not card['can_update']
    assert card['text'] == 'Overtime Native v2: a newer build is out. Play NHL 19 gets it.'
    sc.setup_play()
    assert pathlib.Path(boost.exe_path('native2')).read_bytes() == b'MZ native 2 newer'
    assert not any(b['newer'] for b in card_of(sc)['builds'])


def test_update_is_for_the_kravickas_build_only(sc, served, world):  # noqa: F811
    sc.setup_set_emulator(str(world['emu']))
    got = sc.setup_build_update()                                   # Overtime Native chosen (the default): refused
    assert 'comes with Overtime releases' in got['error'] and sc.ctl.said[-1][1] == 'caution'
    assert not os.path.exists(boost.exe_path('nightly')) and not os.path.exists(boost.exe_path('kravickas'))
    sc.setup_build('kravickas')
    assert card_of(sc)['can_update'] and card_of(sc)['updatable']
    sc.setup_build_update()
    assert pathlib.Path(boost.exe_path('kravickas')).read_bytes() == BUILD
    assert sc.ctl.said[-1] == ('The Kravickas build of shadPS4 is up to date.', 'good')


def test_offline_play_starts_the_build_here(sc, served, world, started):  # noqa: F811
    sc.setup_set_emulator(str(world['emu']))
    sc.setup_play()
    (served / 'latest.json').unlink()                               # the release host does not answer
    packdownload.forget()
    sc._scan()
    sc.boost['sha']['native2'] = 'cd' * 32                          # and the record names another build
    sc.boost_table = {packdownload.NATIVE2_PACK: type('R', (), {'digest': 'ef' * 32, 'size': 1})()}
    sc.setup_play()
    assert started == [boost.exe_path('native2')] * 2


def test_nothing_starts_while_shadps4_runs(sc, served, world, started, monkeypatch):  # noqa: F811
    sc.setup_set_emulator(str(world['emu']))
    sc.setup_build('kravickas')
    monkeypatch.setattr(overlay, 'emulator_running', lambda: True)
    assert 'already running' in sc.setup_play()['error'] and started == []
    assert 'Close shadPS4' in sc.setup_build_update()['error']
    assert not os.path.exists(boost.exe_path('kravickas'))


def test_a_portable_shadps4_keeps_playing_itself(sc, world, started):  # noqa: F811
    (world['emu'].parent / 'user').mkdir()
    sc.setup_set_emulator(str(world['emu']))
    sc.setup_play()
    assert started == [str(world['emu'])] and 'own user folder' in sc.ctl.said[-1][0]
    assert 'own user folder' in card_of(sc)['text'] and sc.calls['installed'] == []


def test_the_play_button_is_grey_until_a_game_is_found(sc, world):  # noqa: F811
    sc.ctl.game_dir, sc.emulator = '', ''
    sc.found = {'game': None}
    p = sc.play_state()
    assert not p['can'] and 'Find NHL 19' in p['why'] and p['text'] == 'Play NHL 19'
    sc.ctl.game_dir = str(world['game'])
    sc.setup_refresh()
    assert sc.play_state()['can']
    sc.boost_part, sc.boost_getting = 0.42, 'Nightly'
    assert sc.play_state() == {'can': False, 'text': 'Getting Nightly 42%', 'why': 'Downloading the shadPS4 build.',
                               'progress': 0.42}
    sc.boost_part = None
    sc.play = {'state': 'running'}
    assert sc.play_state()['text'] == 'NHL 19 is running'


def test_an_old_boost_record_reads_as_the_kravickas_build(sc):  # noqa: F811
    sc.ctl.prefs['setup'] = {'boost': {'sha256': 'ef' * 32, 'emulator': 'D:/own.exe', 'selected': 'x'}}
    again = SC.SetupController(sc.ctl)
    assert again.boost == {'emulator': 'D:/own.exe', 'sha': {'kravickas': 'ef' * 32}} and again.build == 'native2'


def test_every_help_box_has_heads_and_items():
    # ui.js Info maps s.items: a plain pair stops the whole tab when the box opens
    tabs = pathlib.Path(SC.__file__).parents[1] / 'web' / 'js' / 'tabs'
    for page in tabs.glob('*.js'):
        for block in re.findall(r'_INFO = \[(.*?)^\];', page.read_text(encoding='utf-8'), re.M | re.S):
            assert not re.search(r'^\s*\[', block, re.M), page.name


def test_a_build_not_published_says_so(sc, served, world, started):  # noqa: F811
    release(served, native2=None)
    packdownload.forget()
    sc.setup_set_emulator(str(world['emu']))
    card = card_of(sc)                                              # Overtime Native v2, the default, is not served
    assert not card['can_update'] and 'not available' in card['text']
    sc.setup_play()
    assert sc.emulator == str(world['emu']) and sc.ctl.said[-1][1] == 'bad' and started == []


def test_an_online_ready_switches_to_the_lobby_build_with_no_click_and_keeps_it_current(sc, served, world):  # noqa: F811
    # owner 2026-11-08: "make it automated to boost performance for the online"; sonku's other build desynced.
    # owner 2026-11-13: the lobby build is Overtime Native, also for a player who chose Kravickas (the choice stays);
    # owner 2026-11-16: "push everybody to use native v2 on the lobbies"
    own = str(world['emu'])
    sc.setup_set_emulator(own)
    sc.setup_build('kravickas')
    notes = []
    assert sc.online_boost(notes.append) == 'on'
    n = boost.exe_path('native2')
    assert sc.emulator == n and sc.boost['emulator'] == own and sc.ctl.busy is None and sc.build == 'kravickas'
    assert pathlib.Path(n).read_bytes() == NATIVE2 and not os.path.exists(boost.exe_path('kravickas'))
    assert notes and notes[-1].endswith('100 %')
    assert sc.online_boost() == 'already'
    release(served, native2=b'MZ newer')
    packdownload.forget()
    sc._scan()
    assert sc.online_boost() == 'on' and pathlib.Path(n).read_bytes() == b'MZ newer'


def test_an_online_ready_leaves_the_build_alone_while_shadps4_runs_or_nothing_is_published(sc, served, world,  # noqa: F811
                                                                                           monkeypatch):
    own = str(world['emu'])
    sc.setup_set_emulator(own)
    monkeypatch.setattr(overlay, 'emulator_running', lambda: True)
    assert 'Close shadPS4' in sc.online_boost() and sc.emulator == own
    sc.boost_table = {}
    assert sc.online_boost() == 'none published'
