"""Setup, Folders, Downloads: the cache folder set by hand (paths.app_dir('cache') follows it from the first call on)
and the move of its files there and back (cachemove: renamed on one drive; copied, switched, then removed on another;
a copy that fails leaves everything as it was). A cache folder is a folder of its own (MARKER): a picked folder with
other files gets one inside it, and the files of a folder without MARKER are never moved."""
import json
import os
import shutil

import pytest

from overtime_roster.app import cachemove, paths


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'home'))
    return tmp_path


def fill(folder, files):
    for rel, data in files.items():
        path = os.path.join(folder, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)


def held(folder):
    return {rel: open(os.path.join(folder, rel), 'rb').read() for rel, _n in cachemove.files_of(folder)}


FILES = {'photos.zip': b'p' * 300, 'alts_intl_local.zip': b'j' * 900, os.path.join('nhlcom', 'a.json'): b'{}'}


def test_the_cache_folder_follows_the_setting_and_falls_back_without_its_drive(home):
    assert paths.app_dir('cache', 'x.zip') == os.path.join(paths.default_cache_dir(), 'x.zip')
    mine = str(home / 'D' / 'cache')
    os.makedirs(home / 'D')
    with open(os.path.join(paths.app_home(), 'settings.json'), 'w') as f:
        json.dump({'setup': {'custom': {'cache': mine}}}, f)
    paths._cache.clear()                                                # a new start reads the settings
    assert paths.app_dir('cache', 'x.zip') == os.path.join(mine, 'x.zip') and paths.chosen_cache_dir() == mine
    shutil.rmtree(home / 'D')                                           # its drive unplugged: nothing goes there
    assert paths.cache_dir() == paths.default_cache_dir()
    paths.set_cache_dir(None)
    assert paths.chosen_cache_dir() is None


def test_move_on_one_drive_renames_every_file_then_switches(home):
    src, dst = str(home / 'old'), str(home / 'new')
    fill(src, FILES)
    seen = []
    out = cachemove.move(src, dst, lambda: seen.append(held(dst)), default=src)
    assert out['files'] == 3 and seen == [FILES] and held(dst) == FILES and not os.path.exists(src)


def test_move_to_another_drive_copies_all_before_the_switch_then_removes_the_old(home, monkeypatch):
    monkeypatch.setattr(cachemove, '_same_drive', lambda a, b: False)
    src, dst = str(home / 'old'), str(home / 'new')
    fill(src, dict(FILES, **{'half.part': b'x'}))                      # a leftover: not copied, removed
    seen = []
    out = cachemove.move(src, dst, lambda: seen.append((held(dst), held(src))), default=src)
    assert seen == [(FILES, FILES)]                                     # the switch: all there, the old untouched
    assert out == {'files': 3, 'bytes': 1202, 'left': 0, 'kept': ''} and held(dst) == FILES and not os.path.exists(src)
    assert not any(n.endswith('.part') for n in os.listdir(dst))


def test_a_copy_that_fails_leaves_the_old_cache_in_use_and_the_new_folder_as_it_was(home, monkeypatch):
    monkeypatch.setattr(cachemove, '_same_drive', lambda a, b: False)
    src, dst = str(home / 'old'), str(home / 'new')
    fill(src, FILES)
    fill(dst, {'photos.zip': b'already here'})
    real, n = shutil.copyfile, []

    def flaky(a, b):
        n.append(a)
        if len(n) == 2:
            raise OSError('disk full')
        return real(a, b)
    monkeypatch.setattr(cachemove.shutil, 'copyfile', flaky)
    switched = []
    with pytest.raises(cachemove.CacheMoveError, match='stays in'):
        cachemove.move(src, dst, lambda: switched.append(1), default=src)
    assert not switched and held(src) == FILES
    assert held(dst) == {'photos.zip': b'already here'}                 # the copies gone, what was there kept
    assert not any(n.endswith('.part') for n in os.listdir(dst))


def test_a_cache_folder_inside_the_old_one_is_refused(home):
    src = str(home / 'old')
    fill(src, FILES)
    with pytest.raises(cachemove.CacheMoveError, match='inside'):
        cachemove.move(src, os.path.join(src, 'sub'), lambda: None, default=src)
    assert held(src) == FILES


MINE = {'tax-2025.pdf': b'pdf', os.path.join('holiday', 'img1.jpg'): b'jpg', 'installer.tmp': b'tmp'}


def everything(folder):
    """Every file under `folder`, leftovers and MARKER included."""
    out = {}
    for top, _dirs, names in os.walk(folder):
        for name in names:
            p = os.path.join(top, name)
            out[os.path.relpath(p, folder)] = open(p, 'rb').read()
    return out


def test_a_picked_folder_that_holds_other_files_gets_a_cache_folder_of_its_own(home):
    mine, empty, new = str(home / 'Downloads'), str(home / 'empty'), str(home / 'new')
    fill(mine, MINE)
    os.makedirs(empty)
    assert cachemove.pick(mine) == os.path.join(mine, cachemove.SUBFOLDER)
    assert cachemove.pick(empty) == empty and cachemove.pick(new) == new
    cachemove.mark(empty)
    fill(empty, {'photos.zip': b'p'})
    assert cachemove.pick(empty) == empty                                # a cache folder of this program
    fill(os.path.join(mine, cachemove.SUBFOLDER), {'other.txt': b'x'})
    with pytest.raises(cachemove.CacheMoveError, match='empty folder'):
        cachemove.pick(mine)


@pytest.mark.parametrize('same_drive', [True, False])
def test_change_then_auto_never_moves_or_deletes_the_players_files(home, monkeypatch, same_drive):
    monkeypatch.setattr(cachemove, '_same_drive', lambda a, b: same_drive)
    monkeypatch.setattr(cachemove, 'SPARE', 0)
    default, mine = str(home / 'appdata' / 'cache'), str(home / 'Downloads')
    fill(default, FILES)
    fill(mine, MINE)
    picked = cachemove.pick(mine)
    cachemove.move(default, picked, lambda: None, default=default)       # Change...
    assert held(picked) == FILES and everything(mine) == dict(
        MINE, **{os.path.join(cachemove.SUBFOLDER, rel): data for rel, data in FILES.items()},
        **{os.path.join(cachemove.SUBFOLDER, cachemove.MARKER): cachemove.MARKER_TEXT})
    out = cachemove.move(picked, default, lambda: None, default=default)  # Auto
    assert out['files'] == 3 and held(default) == FILES
    assert everything(mine) == MINE                                     # the cache's own folder gone, the rest as it was


@pytest.mark.parametrize('same_drive', [True, False])
def test_a_folder_without_the_marker_keeps_its_files(home, monkeypatch, same_drive):
    """A cache folder picked before MARKER existed may hold the player's own files: only the setting changes."""
    monkeypatch.setattr(cachemove, '_same_drive', lambda a, b: same_drive)
    default, mine = str(home / 'appdata' / 'cache'), str(home / 'Downloads')
    fill(mine, dict(MINE, **FILES))
    switched = []
    out = cachemove.move(mine, default, lambda: switched.append(1), default=default)
    assert switched == [1] and out == {'files': 0, 'bytes': 0, 'left': 0, 'kept': mine}
    assert everything(mine) == dict(MINE, **FILES) and held(default) == {}
