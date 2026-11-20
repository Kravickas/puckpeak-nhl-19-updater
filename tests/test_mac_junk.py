"""0.98.0, a Mac tester: "the app hits a flag whenever a random Mac file is noticed ... ignore DS_Store files when
patching". Finder drops `.DS_Store` into every folder it shows and `._<name>` (AppleDouble) beside every file on a
non-Mac disk; none of them is a game, emulator or patch file, so no check judges them (gamefiles.junk)."""
import os

import pytest

from overtime_core import gamefiles, xmlpatch
from overtime_roster.app import cachemove, gamesetup, onlinetag

from test_gamesetup import _game, world  # noqa: F401 (the fixture)
from test_onlinetag import game  # noqa: F401 (the fixture)


def _finder(folder):
    """What a Mac leaves in a folder it showed: .DS_Store and an AppleDouble file per file."""
    with open(os.path.join(folder, '.DS_Store'), 'wb') as f:
        f.write(b'\x00\x00\x00\x01Bud1')
    for name in os.listdir(folder):
        if not name.startswith('.') and os.path.isfile(os.path.join(folder, name)):
            with open(os.path.join(folder, '._' + name), 'wb') as f:
                f.write(b'\x00\x05\x16\x07')


def test_junk_names():
    for name in ('.DS_Store', '.ds_store', '._eboot.bin', '._patch_inxp_56.big', '__MACOSX', 'Thumbs.db',
                 'desktop.ini', 'Icon\r', '.Spotlight-V100', '.Trashes', '.fseventsd'):
        assert gamefiles.junk(name), name
    for name in ('eboot.bin', 'patch_inxp_56.big', 'sce_sys', 'overtime.xml', 'files.json', '.big', 'DS_Store'):
        assert not gamefiles.junk(name), name
    assert gamefiles.junk_path(os.path.join('databigs', '._game_60.big'))
    assert gamefiles.junk_path('__MACOSX/databigs/game_60.big') and gamefiles.junk_path('a\\.DS_Store')
    assert not gamefiles.junk_path(os.path.join('databigs', 'game_60.big'))


def test_a_ds_store_in_the_patches_folder_does_not_refuse_the_install(world):  # noqa: F811
    folder = world['user'] / 'patches' / 'Overtime'
    folder.mkdir(parents=True)
    (folder / '.DS_Store').write_bytes(b'Bud1')
    (folder / '._overtime.xml').write_bytes(b'\x00\x05\x16\x07')
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    assert (folder / 'overtime.xml').is_file()
    gamesetup.remove(running=lambda: False)
    assert not folder.exists()                       # the folder held only Finder's files: it goes with the patch
    (folder).mkdir(parents=True)                     # a real stranger still refuses
    (folder / 'someone_else.xml').write_text('<Patch/>')
    with pytest.raises(gamesetup.SetupError, match='someone_else.xml'):
        gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)


def test_the_clean_game_check_does_not_see_finder_files(world):  # noqa: F811
    gd = str(world['game'])
    clean = gamesetup.snapshot(gd, full=True)
    for folder in (world['game'], world['game'] / 'databigs', world['game'] / 'sce_sys'):
        _finder(str(folder))
    (world['game'] / '__MACOSX').mkdir()
    (world['game'] / '__MACOSX' / '._eboot.bin').write_bytes(b'x')
    now = gamesetup.snapshot(gd, full=True)
    assert now['files'] == clean['files'] and gamesetup.compare(clean, now) == []
    # a record made before 0.98.0 that listed them does not turn them into "missing" once they are gone
    old = {**now, 'files': {**now['files'], '.DS_Store': [10, None], os.path.join('databigs', '._game_60.big'): [4, None]}}
    assert gamesetup.compare(old, now) == [] and gamesetup.compare(now, old) == []
    (world['game'] / 'extra.txt').write_text('x')    # a real change still shows
    assert gamesetup.compare(clean, gamesetup.snapshot(gd)) == [('extra.txt', 'added')]


def test_appledouble_files_are_not_archives(tmp_path):
    g = _game(tmp_path)
    _finder(str(g / 'databigs'))
    assert [os.path.basename(p) for p in gamefiles.archives(str(g))] == ['game_60.big']
    assert gamesetup.read_game(str(g))['ok']
    # an update-only folder is still told apart: `._game_60.big` beside patch files is no base archive
    u = _game(tmp_path, 'upd')
    (u / 'databigs' / 'game_60.big').unlink()
    (u / 'databigs' / 'patch_inxp_56.big').write_bytes(b'x')
    (u / 'databigs' / '._inxp_10.big').write_bytes(b'x')
    info = gamesetup.read_game(str(u))
    assert not info['ok'] and 'update files' in info['problem']


def test_a_mods_folder_left_with_finder_files_is_removed_with_the_tag(game):  # noqa: F811
    gd = str(game['game'])
    onlinetag.apply(str(game['emu']), gd)
    folder = os.path.dirname(game['ini'])
    _finder(folder)
    _finder(gamefiles.mods_dir(gd))
    assert onlinetag.remove(gd) == [game['ini']]
    assert not os.path.exists(gamefiles.mods_dir(gd))


def test_a_cache_folder_holding_only_finder_files_counts_as_empty(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'home'))
    picked = tmp_path / 'Cache'
    picked.mkdir()
    (picked / '.DS_Store').write_bytes(b'Bud1')
    assert cachemove.pick(str(picked)) == str(picked)
    (picked / 'mine.txt').write_text('x')
    assert cachemove.pick(str(picked)) == os.path.join(str(picked), cachemove.SUBFOLDER)
