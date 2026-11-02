"""Boost performance (overtime_roster.app.boost, the Setup card): Kravickas's NHL 19 build from a local release fixture
into the app's own folder, QtLauncher's files, and back."""
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
OWN = 'D:/PS4/PS4 Emulator/shadPS4.exe'
INI = f'[general]\r\nx=1\r\n\r\n[version_manager]\r\nversionPath=D:/v\r\nversionSelected={OWN}\r\n'
THEIR_ENTRY = {'codename': 'Local', 'date': '2026-11-01', 'name': 'NHL 19', 'path': OWN, 'type': 2}


def release(root, content=BUILD, names=('shadPS4.exe',)):
    """A release folder with the build as its pack; latest.json's URL."""
    (root / 'packs').mkdir(parents=True, exist_ok=True)
    pack = root / 'packs' / boost.PACK
    with zipfile.ZipFile(pack, 'w') as z:
        for name in names:
            z.writestr(name, content)
    data = pack.read_bytes()
    entry = {'file': f'packs/{boost.PACK}', 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
    (root / 'latest.json').write_text(json.dumps({'version': '0.30.0', 'packs': {boost.PACK: entry}}))
    (root / 'SHA256SUMS.txt').write_text(f"{entry['sha256']}  packs/{boost.PACK}\n")
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
    packdownload.forget()
    yield world['tmp'] / 'release'
    packdownload.forget()


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


@pytest.mark.parametrize('content, names', [(BUILD, ('readme.txt',)), (b'PK not a program', ('shadPS4.exe',)),
                                            (BUILD, ('shadPS4.exe', 'old/shadPS4.exe'))])
def test_only_one_windows_program_passes_as_the_pack(tmp_path, content, names):
    release(tmp_path, content, names)
    with pytest.raises(art.ArtError):
        packdownload.check_emulator(str(tmp_path / 'packs' / boost.PACK))


def test_on_and_off_in_setup(sc, served, launcher, world):  # noqa: F811
    own = str(world['emu'])
    sc.setup_set_emulator(own)
    card = card_of(sc)
    assert card['can'] and not card['on'] and 'Off' in card['text']
    assert not os.path.exists(boost.exe_path())
    sc.setup_boost(True)
    exe = boost.exe_path()
    assert pathlib.Path(exe).read_bytes() == BUILD
    assert sc.emulator == exe and card_of(sc)['on'] and sc.known_emulator() == exe
    assert pathlib.Path(own).read_bytes() == b'MZ'                  # a player's exe is never touched
    assert f"versionSelected={exe.replace(os.sep, '/')}" in (launcher / 'qt_ui.ini').read_text()
    assert sc.boost['emulator'] == own
    sc.setup_boost(False)
    assert sc.emulator == own and not card_of(sc)['on'] and sc.boost == {}
    assert versions(launcher) == [THEIR_ENTRY] and (launcher / 'qt_ui.ini').read_bytes() == INI.encode()
    assert sc.ctl.said[-1][1] == 'good'


def test_a_newer_build_is_offered_and_the_way_back_stays(sc, served, launcher, world):  # noqa: F811
    own = str(world['emu'])
    sc.setup_set_emulator(own)
    sc.setup_boost(True)
    release(served, b'MZ newer')
    packdownload.forget()
    sc._scan()
    assert card_of(sc)['newer']
    sc.setup_boost(True)
    assert pathlib.Path(boost.exe_path()).read_bytes() == b'MZ newer' and not card_of(sc)['newer']
    sc.setup_boost(False)
    assert sc.emulator == own and (launcher / 'qt_ui.ini').read_bytes() == INI.encode()


def test_on_a_pick_by_hand_and_on_again_still_finds_the_way_back(sc, served, launcher, world):  # noqa: F811
    own = str(world['emu'])
    sc.setup_set_emulator(own)
    sc.setup_boost(True)
    sc.setup_set_emulator(own)
    assert not card_of(sc)['on']
    sc.setup_boost(True)
    sc.setup_boost(False)
    assert sc.emulator == own and versions(launcher) == [THEIR_ENTRY]
    assert (launcher / 'qt_ui.ini').read_bytes() == INI.encode()


def test_works_without_a_launcher(sc, served, world):  # noqa: F811
    sc.setup_set_emulator(str(world['emu']))
    sc.setup_boost(True)
    assert sc.emulator == boost.exe_path() and 'selected' not in sc.boost


@pytest.mark.parametrize('running, text', [('emulator_running', 'Close shadPS4'),
                                           ('launcher_running', 'Close QtLauncher')])
def test_nothing_changes_while_shadps4_or_the_launcher_runs(sc, served, launcher, world, monkeypatch, running,  # noqa: F811
                                                            text):
    sc.setup_set_emulator(str(world['emu']))
    monkeypatch.setattr(overlay, running, lambda: True)
    assert text in sc.setup_boost(True)['error']
    assert not os.path.exists(boost.exe_path()) and (launcher / 'qt_ui.ini').read_bytes() == INI.encode()


def test_a_portable_shadps4_is_refused(sc, served, world):  # noqa: F811
    (world['emu'].parent / 'user').mkdir()
    sc.setup_set_emulator(str(world['emu']))
    assert 'own user folder' in sc.setup_boost(True)['error'] and sc.emulator == str(world['emu'])


def test_the_way_back_survives_a_lost_record(launcher):
    exe = r'C:\app\boost\shadPS4.exe'
    gamesetup.launcher_add(exe, boost.ENTRY)
    assert gamesetup.launcher_add(exe, boost.ENTRY) == OWN          # the app forgot it was on: enable again
    gamesetup.launcher_remove(exe, None)                            # or off with no record at all
    assert versions(launcher) == [THEIR_ENTRY]
    assert (launcher / 'qt_ui.ini').read_bytes() == INI.encode()


def test_every_help_box_has_heads_and_items():
    # ui.js Info maps s.items: a plain pair stops the whole tab when the box opens
    tabs = pathlib.Path(SC.__file__).parents[1] / 'web' / 'js' / 'tabs'
    for page in tabs.glob('*.js'):
        for block in re.findall(r'_INFO = \[(.*?)^\];', page.read_text(encoding='utf-8'), re.M | re.S):
            assert not re.search(r'^\s*\[', block, re.M), page.name


def test_a_build_not_published_says_so(sc, served, world):  # noqa: F811
    (served / 'latest.json').write_text(json.dumps({'version': '0.30.0'}))
    packdownload.forget()
    sc.setup_set_emulator(str(world['emu']))
    card = card_of(sc)
    assert not card['can'] and 'Not available' in card['text']
    sc.setup_boost(True)
    assert sc.emulator == str(world['emu']) and sc.ctl.said[-1][1] == 'bad'
