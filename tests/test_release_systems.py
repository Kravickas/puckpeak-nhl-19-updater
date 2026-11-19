"""The Linux and macOS apps' own release inside latest.json, and the cross-play switch the server lays over it
(overtime_roster/app/selfupdate.py; the server's side is tests/test_appupdate_systems.py)."""
import hashlib
import json

import pytest

from overtime_roster.app import selfupdate

IMAGE = bytes([0x7F]) + b'ELF new app ' * 800
OLD = bytes([0x7F]) + b'ELF old app ' * 700
LIN, WIN = 'aa' * 32, 'bb' * 32
BASE = 'https://ot.example/app/latest.json'
WINDOWS = {'version': '0.97.0', 'exe': 'OvertimeNHL19.exe', 'size': 14, 'sha256': 'cc' * 32, 'notes': 'Seattle',
           'page': 'https://ot.example/'}
OTHERS = {'linux': {'version': '0.97.1', 'exe': selfupdate.LINUX_ASSET, 'size': len(IMAGE),
                    'sha256': hashlib.sha256(IMAGE).hexdigest()},
          'macos': {'version': '0.96.0', 'notes': 'Experimental.', 'page': 'https://ot.example/mac'},
          'crossplay': {LIN: WIN}}


def sums(url):
    return f"{'cc' * 32}  OvertimeNHL19.exe\n{hashlib.sha256(IMAGE).hexdigest()}  {selfupdate.LINUX_ASSET}\n"


def facts(r):
    return (r.version, r.notes, r.page, r.exe_url, r.size, r.digest, r.asset)


def test_a_windows_app_reads_the_same_release_with_the_new_keys_there():
    """What every released exe does: the keys for the other systems change nothing it reads."""
    plain = selfupdate.from_json(dict(WINDOWS), BASE, sums)
    mixed = selfupdate.from_json({**WINDOWS, **OTHERS}, BASE, sums)
    assert facts(plain) == facts(mixed) and plain.asset == 'OvertimeNHL19.exe' and plain.can_install()
    assert selfupdate.asset_for(r'C:\x\OvertimeNHL19.exe', 'win32') == 'OvertimeNHL19.exe'
    assert selfupdate.asset_for(r'C:\x\OvertimeNHL19-cli.exe', 'win32') == 'OvertimeNHL19-cli.exe'


def test_linux_and_macos_read_their_own_release():
    data = {**WINDOWS, **OTHERS}
    lin = selfupdate.from_json(data, BASE, sums, selfupdate.asset_for('/x/OvertimeNHL19.AppImage', 'linux'))
    assert str(lin.version) == '0.97.1' and lin.exe_url == 'https://ot.example/app/' + selfupdate.LINUX_ASSET
    assert lin.size == len(IMAGE) and lin.digest == hashlib.sha256(IMAGE).hexdigest() and lin.can_install()
    assert lin.notes == 'Seattle' and lin.page == 'https://ot.example/'            # the ones above it
    mac = selfupdate.from_json(data, BASE, sums, selfupdate.asset_for(None, 'darwin'))
    assert str(mac.version) == '0.96.0' and mac.notes == 'Experimental.' and mac.page == 'https://ot.example/mac'
    assert mac.exe_url.endswith('/' + selfupdate.MACOS_ASSET) and not mac.can_install()     # told, never swapped


def test_no_key_for_the_system_is_no_release_for_it():
    assert selfupdate.from_json(dict(WINDOWS), BASE, sums, selfupdate.LINUX_ASSET) is None
    assert selfupdate.from_json({**WINDOWS, 'macos': 'soon'}, BASE, sums, selfupdate.MACOS_ASSET) is None
    assert selfupdate.latest('0.1.0', BASE, lambda url: json.dumps(WINDOWS) if url == BASE else sums(url),
                             asset=selfupdate.LINUX_ASSET) is None


def test_a_sha256_that_disagrees_with_the_sums_cannot_be_installed():
    data = {**WINDOWS, 'linux': {**OTHERS['linux'], 'sha256': 'dd' * 32}}
    assert not selfupdate.from_json(data, BASE, sums, selfupdate.LINUX_ASSET).can_install()


def test_the_running_appimage_is_what_gets_swapped(tmp_path, monkeypatch):
    image = tmp_path / 'OvertimeNHL19.AppImage'
    image.write_bytes(OLD)
    monkeypatch.setattr(selfupdate.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(selfupdate.sys, 'platform', 'linux')
    monkeypatch.setattr(selfupdate.os, 'name', 'posix')
    monkeypatch.setenv('APPIMAGE', str(image))
    assert selfupdate.running_exe() == str(image)
    monkeypatch.setenv('APPIMAGE', str(tmp_path / 'gone.AppImage'))
    assert selfupdate.running_exe() is None                                         # unpacked, or moved away
    monkeypatch.setattr(selfupdate.sys, 'platform', 'darwin')
    monkeypatch.setenv('APPIMAGE', str(image))
    assert selfupdate.running_exe() is None                                         # the Mac app is told only


def test_install_swaps_the_appimage_for_the_linux_file(tmp_path, monkeypatch):
    image = tmp_path / 'OvertimeNHL19.AppImage'
    image.write_bytes(OLD)
    (tmp_path / 'new').write_bytes(IMAGE)
    release = selfupdate.Release(selfupdate.parse_version('0.97.1'), exe_url=(tmp_path / 'new').as_uri(),
                                 size=len(IMAGE), digest=hashlib.sha256(IMAGE).hexdigest(),
                                 asset=selfupdate.LINUX_ASSET)
    monkeypatch.setattr(selfupdate, 'asset_for', lambda exe, system=None: selfupdate.LINUX_ASSET)
    monkeypatch.setattr(selfupdate, 'download', lambda rel, target, progress=None: open(target, 'wb').write(IMAGE))
    selfupdate.install(release, exe=str(image), start=False, emulator=lambda: False)
    assert image.read_bytes() == IMAGE and (tmp_path / 'OvertimeNHL19.AppImage.old').read_bytes() == OLD
    windows = selfupdate.Release(selfupdate.parse_version('0.97.1'), exe_url='https://x/OvertimeNHL19.exe',
                                 digest='cc' * 32)
    with pytest.raises(selfupdate.Refused, match='OvertimeNHL19.exe'):
        selfupdate.install(windows, exe=str(image), start=False, emulator=lambda: False)
