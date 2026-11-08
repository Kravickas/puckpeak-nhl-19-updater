"""The online emulator copy for lobby matches (overtime_roster/app/onlineemu.py)."""
import hashlib
import os
import zipfile

import pytest

from overtime_roster.app import gamesetup, onlineemu, packdownload


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'apphome'))
    monkeypatch.setenv('APPDATA', str(tmp_path / 'appdata'))
    return tmp_path


def _pack(folder, body=b'MZ online'):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, packdownload.EMULATOR_PACK)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('shadps4/shadPS4.exe', body)
    with open(path, 'rb') as f:
        return path, hashlib.sha256(f.read()).hexdigest()


def _serve(monkeypatch, pack, sha, calls):
    def download(names, cache_dir, progress=None, cancelled=None, **kw):
        calls.append(names)
        return [(names[0], True, '')]
    monkeypatch.setattr(packdownload, 'download', download)
    monkeypatch.setattr(packdownload, 'located', lambda name, cache_dir: (pack, sha))


def test_ensure_unpacks_once_and_reuses(home, monkeypatch):
    pack, sha = _pack(str(home / 'cache'))
    calls = []
    _serve(monkeypatch, pack, sha, calls)
    exe, got = onlineemu.ensure(str(home / 'cache'))
    assert got == sha and open(exe, 'rb').read() == b'MZ online'
    assert onlineemu.ready(sha) == exe
    exe2, _ = onlineemu.ensure(str(home / 'cache'), want=sha)
    assert exe2 == exe and len(calls) == 1          # here already: no download


def test_ensure_refuses_another_build_than_the_lobby_names(home, monkeypatch):
    pack, sha = _pack(str(home / 'cache'))
    _serve(monkeypatch, pack, sha, [])
    with pytest.raises(onlineemu.OnlineEmuError):
        onlineemu.ensure(str(home / 'cache'), want='0' * 64)


def test_a_failed_download_says_why(home, monkeypatch):
    monkeypatch.setattr(packdownload, 'download', lambda names, cache, progress=None, cancelled=None:
                        [(names[0], False, 'offline')])
    with pytest.raises(onlineemu.OnlineEmuError, match='offline'):
        onlineemu.ensure(str(home / 'cache'))


def test_exe_path_refuses_a_name_that_is_not_a_sha(home):
    for bad in (None, '', '../x', 'A' * 64, '0' * 63):
        with pytest.raises(onlineemu.OnlineEmuError):
            onlineemu.exe_path(bad)


def test_old_builds_are_pruned_to_two(home, monkeypatch):
    cache = str(home / 'cache')
    shas = []
    for i, body in enumerate((b'MZ 1', b'MZ 2', b'MZ 3')):
        pack, sha = _pack(os.path.join(cache, str(i)), body)
        _serve(monkeypatch, pack, sha, [])
        onlineemu.ensure(cache)
        old = os.path.dirname(onlineemu.exe_path(sha))
        os.utime(old, (1000 + i, 1000 + i))
        shas.append(sha)
    assert onlineemu.ready(shas[2]) and onlineemu.ready(shas[1])
    assert not onlineemu.ready(shas[0])


def test_start_dir_follows_the_players_own_data(home, monkeypatch):
    portable = home / 'emu'
    (portable / 'user').mkdir(parents=True)
    exe = portable / 'shadPS4.exe'
    exe.write_bytes(b'MZ')
    assert os.path.normcase(onlineemu.start_dir(str(exe))) == os.path.normcase(str(portable))
    monkeypatch.setattr(gamesetup, 'start_dir', lambda e: None)
    with pytest.raises(onlineemu.OnlineEmuError):
        onlineemu.start_dir(str(exe))
    with pytest.raises(onlineemu.OnlineEmuError):
        onlineemu.start_dir('')
