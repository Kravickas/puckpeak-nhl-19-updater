"""Setup, Folders, Downloads: the cache folder set by hand (paths.app_dir('cache') follows it from the first call on)
and the move of its files there and back (cachemove: renamed on one drive; copied, switched, then removed on another;
a copy that fails leaves everything as it was)."""
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
    out = cachemove.move(src, dst, lambda: seen.append(held(dst)))
    assert out['files'] == 3 and seen == [FILES] and held(dst) == FILES and not os.path.exists(src)


def test_move_to_another_drive_copies_all_before_the_switch_then_removes_the_old(home, monkeypatch):
    monkeypatch.setattr(cachemove, '_same_drive', lambda a, b: False)
    src, dst = str(home / 'old'), str(home / 'new')
    fill(src, dict(FILES, **{'half.part': b'x'}))                      # a leftover: not copied, removed
    seen = []
    out = cachemove.move(src, dst, lambda: seen.append((held(dst), held(src))))
    assert seen == [(FILES, FILES)]                                     # the switch: all there, the old untouched
    assert out == {'files': 3, 'bytes': 1202, 'left': 0} and held(dst) == FILES and not os.path.exists(src)
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
        cachemove.move(src, dst, lambda: switched.append(1))
    assert not switched and held(src) == FILES
    assert held(dst) == {'photos.zip': b'already here'}                 # the copies gone, what was there kept
    assert not any(n.endswith('.part') for n in os.listdir(dst))


def test_a_cache_folder_inside_the_old_one_is_refused(home):
    src = str(home / 'old')
    fill(src, FILES)
    with pytest.raises(cachemove.CacheMoveError, match='inside'):
        cachemove.move(src, os.path.join(src, 'sub'), lambda: None)
    assert held(src) == FILES
