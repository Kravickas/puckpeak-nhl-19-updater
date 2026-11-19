"""The online emulator copy for lobby matches (overtime_roster/app/onlineemu.py)."""
import hashlib
import os
import zipfile

import pytest

from overtime_roster.app import emufile, gamesetup, onlineemu, packdownload

HEAD = emufile.MAGIC[emufile.system_of()][0]    # the first bytes of a program on this system


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'apphome'))
    monkeypatch.setenv('APPDATA', str(tmp_path / 'appdata'))
    monkeypatch.setattr(emufile, 'extract', lambda appimage, run=None: None)   # Linux: no AppImage is run here
    return tmp_path


def _pack(folder, body=HEAD + b' online'):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, packdownload.EMULATOR_PACK)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('shadps4/' + emufile.name(), body)
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
    assert got == sha and open(exe, 'rb').read() == HEAD + b' online'
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
    for i, body in enumerate((b' 1', b' 2', b' 3')):
        pack, sha = _pack(os.path.join(cache, str(i)), HEAD + body)
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


def test_the_pack_follows_the_servers_pin(monkeypatch):
    """0.90.2: lobbies play whichever pack the server pins. 0.92.0 (owner 2026-11-13): with no pin or an unknown
    digest it is the Overtime Native pack (Kravickas before). Every pack this system serves is pinnable."""
    class Rel:
        def __init__(self, digest):
            self.digest = digest
    digests = {name: hashlib.sha256(name.encode()).hexdigest() for name in onlineemu.PACKS}
    table = {name: Rel(digest.upper()) for name, digest in digests.items()}
    for name, digest in digests.items():
        assert onlineemu.pack_for(digest, table) == name
    assert onlineemu.pack_for('c' * 64, table) == onlineemu.PACK == packdownload.NATIVE2_PACK   # v2: the default
    assert onlineemu.pack_for(None, table) == onlineemu.PACK
    assert onlineemu.pack_for('b' * 64, {}) == onlineemu.PACK


@pytest.mark.windows_only
def test_the_pack_pins_of_the_windows_builds(monkeypatch):
    class Rel:
        def __init__(self, digest):
            self.digest = digest
    table = {packdownload.EMULATOR_PACK: Rel('a' * 64), packdownload.NIGHTLY_PACK: Rel('B' * 64)}
    assert onlineemu.pack_for('b' * 64, table) == packdownload.NIGHTLY_PACK
    assert onlineemu.pack_for('a' * 64, table) == packdownload.EMULATOR_PACK


@pytest.mark.windows_only
def test_a_nightly_pin_unpacks_the_nightly_zip_with_its_exe_at_the_root(home, monkeypatch):
    folder = str(home / 'cache')
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, packdownload.NIGHTLY_PACK)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('shadPS4.exe', b'MZ nightly')          # upstream's layout: the exe at the root
    sha = hashlib.sha256(open(path, 'rb').read()).hexdigest()

    class Rel:
        digest = sha
    monkeypatch.setattr(packdownload, 'published', lambda: {packdownload.NIGHTLY_PACK: Rel()})
    asked = []

    def download(names, cache_dir, progress=None, cancelled=None, **kw):
        asked.append(names)
        return [(names[0], True, '')]
    monkeypatch.setattr(packdownload, 'download', download)
    monkeypatch.setattr(packdownload, 'located', lambda name, cache_dir: (path, sha) if name == packdownload.NIGHTLY_PACK else None)
    exe, got = onlineemu.ensure(folder, want=sha)
    assert asked == [[packdownload.NIGHTLY_PACK]] and got == sha and open(exe, 'rb').read() == b'MZ nightly'
