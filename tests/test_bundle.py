"""packaging/bundle.json (what a Linux or macOS build puts in) against packaging/build.ps1 (the Windows build), and the
pieces of packaging/build_unix.py and packaging/smoke.py that run without building anything."""
import importlib.util
import json
import os
import re
import tarfile

import pytest

from overtime_roster.app import desktopentry, selfupdate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGING = os.path.join(ROOT, 'packaging')


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(PACKAGING, name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_unix = _load('build_unix')
smoke = _load('smoke')


def _spec():
    with open(os.path.join(PACKAGING, 'bundle.json'), encoding='utf-8') as f:
        return json.load(f)


def _ps1():
    with open(os.path.join(PACKAGING, 'build.ps1'), encoding='utf-8-sig') as f:
        return f.read()


# --- bundle.json and the Windows build name the same things ----------------------------------------------------------
def test_every_system_bundles_the_data_the_windows_exe_does():
    """A folder added to build.ps1 and not to bundle.json would be missing from the Linux and macOS app."""
    slash = chr(92)
    windows = {m.replace(slash, '/') for m in re.findall(r"'--add-data', \"[^;\"]+;([^\"]+)\"", _ps1())}
    spec = _spec()
    assert windows == {dst for _src, dst in spec['data'] + spec['private']}
    assert len(windows) == 5


def test_the_windows_collects_and_pins_are_the_lists_own():
    ps1, spec = _ps1(), _spec()
    assert set(re.findall(r'--collect-all (\w+)', ps1)) == set(spec['collect']['win32'])
    for pin in ('pywebview==', 'pillow==', 'numpy=='):
        ours = next(r for r in spec['requirements']['all'] if r.startswith(pin))
        assert f'"{ours}"' in ps1, f'{ours}: build.ps1 installs another version'
    assert spec['entry'].replace('/', chr(92)) in ps1
    assert f"'{spec['name']}'" in ps1 or f'"{spec["name"]}"' in ps1


def test_the_listed_sources_are_in_the_repository():
    spec = _spec()
    for src, _dst in spec['data']:
        assert os.path.exists(os.path.join(ROOT, *src.split('/'))), src
    assert os.path.isfile(os.path.join(ROOT, *spec['entry'].split('/')))


def test_the_names_are_the_ones_the_app_updates_to():
    assert build_unix.APPIMAGE == selfupdate.LINUX_ASSET
    assert build_unix.DMG == selfupdate.MACOS_ASSET
    assert build_unix.DESKTOP_ID == desktopentry.ICON_NAME
    assert build_unix.DESKTOP_ID + '.desktop' == desktopentry.ENTRY


# --- build_unix.py ---------------------------------------------------------------------------------------------------
def test_a_build_without_the_private_data_says_so_in_its_name():
    assert build_unix.named('OvertimeNHL19-x86_64.AppImage', False) == 'OvertimeNHL19-x86_64.AppImage'
    assert build_unix.named('OvertimeNHL19-x86_64.AppImage', True) == 'OvertimeNHL19-x86_64-nodata.AppImage'
    assert build_unix.named('OvertimeNHL19-linux.tar.gz', True) == 'OvertimeNHL19-linux-nodata.tar.gz'
    assert build_unix.named('OvertimeNHL19-macos.dmg', True) == 'OvertimeNHL19-macos-nodata.dmg'


def test_the_private_data_goes_in_only_with_inputs(tmp_path):
    spec = _spec()
    plain = build_unix.data_pairs(spec, '')
    assert [dst for _src, dst in plain] == [dst for _src, dst in spec['data']]
    with pytest.raises(build_unix.BuildError):
        build_unix.data_pairs(spec, str(tmp_path))                  # the folder lacks defaults/ and the data pack
    (tmp_path / 'defaults').mkdir()
    (tmp_path / 'packs').mkdir()
    (tmp_path / 'packs' / 'nhl27.json.gz').write_bytes(b'')
    full = build_unix.data_pairs(spec, str(tmp_path))
    assert [dst for _src, dst in full[len(plain):]] == ['overtime_roster/defaults', 'overtime_roster/packs']
    assert full[-1][0] == str(tmp_path / 'packs' / 'nhl27.json.gz')


def test_a_relative_inputs_folder_reaches_pyinstaller_as_a_full_path(tmp_path, monkeypatch):
    (tmp_path / 'inputs' / 'defaults').mkdir(parents=True)          # PyInstaller reads a relative path from its spec
    (tmp_path / 'inputs' / 'packs').mkdir()                         # folder, not from where the build was started
    (tmp_path / 'inputs' / 'packs' / 'nhl27.json.gz').write_bytes(b'')
    monkeypatch.chdir(tmp_path)
    private = build_unix.data_pairs(_spec(), 'inputs')[-2:]
    assert all(os.path.isabs(src) and os.path.exists(src) for src, _dst in private)


def test_pyinstaller_gets_each_systems_own_list(tmp_path):
    spec = _spec()
    pairs = build_unix.data_pairs(spec, '')
    linux = build_unix.pyinstaller_args(spec, 'linux', pairs, 'app.png', str(tmp_path))
    mac = build_unix.pyinstaller_args(spec, 'darwin', pairs, 'app.png', str(tmp_path))
    assert linux[linux.index('--name') + 1] == 'OvertimeNHL19'
    assert mac[mac.index('--name') + 1] == 'Overtime NHL19'
    assert '--onefile' not in linux + mac                           # a folder: the AppDir, the .app
    assert linux.count('--add-data') == mac.count('--add-data') == len(spec['data'])
    assert 'PySide6.QtWebEngineWidgets' in linux and 'PySide6.QtWebEngineWidgets' not in mac
    assert '--osx-bundle-identifier' in mac and '--osx-bundle-identifier' not in linux
    assert '--codesign-identity' not in mac                         # ad hoc unless a Developer ID is named
    signed = build_unix.pyinstaller_args(spec, 'darwin', pairs, 'app.png', str(tmp_path), 'Developer ID Application: X')
    assert signed[signed.index('--codesign-identity') + 1] == 'Developer ID Application: X'
    assert '--codesign-identity' not in build_unix.pyinstaller_args(spec, 'linux', pairs, 'a.png', str(tmp_path), 'X')
    for args in (linux, mac):
        assert args[-1].endswith('launcher.py')
        assert [args[i + 1] for i, a in enumerate(args) if a == '--collect-all'] == ['webview']
        assert 'pythonnet' in [args[i + 1] for i, a in enumerate(args) if a == '--exclude-module']


def test_pip_gets_the_window_toolkit_on_linux_only():
    spec = _spec()
    linux, mac = build_unix.requirements(spec, 'linux'), build_unix.requirements(spec, 'darwin')
    assert [r for r in linux if r.startswith('PySide6')] and not [r for r in mac if r.startswith('PySide6')]
    assert [r for r in linux if r.lower().startswith('qtpy')]
    assert [r for r in linux if r.startswith('PySide6-WebEngine')]      # its own package since Qt 6.12
    assert all('==' in r or r == 'certifi' for r in linux)          # pinned: a build is the same next month


def test_the_appdir_has_what_appimagetool_needs(tmp_path):
    spec = _spec()
    folder = tmp_path / 'dist' / 'OvertimeNHL19'
    (folder / '_internal').mkdir(parents=True)
    (folder / 'OvertimeNHL19').write_bytes(b'program')
    png = tmp_path / 'app.png'
    png.write_bytes(b'png')
    appdir = build_unix.make_appdir(spec, str(folder), str(tmp_path / 'AppDir'), str(png), 'Overtime Roster')
    assert open(os.path.join(appdir, 'usr', 'lib', 'overtime-nhl19', 'OvertimeNHL19'), 'rb').read() == b'program'
    run = open(os.path.join(appdir, 'AppRun'), 'rb').read()
    assert run.startswith(b'#!/bin/sh\n') and b'\r' not in run
    assert b'usr/lib/overtime-nhl19/OvertimeNHL19" "$@"' in run
    entry = open(os.path.join(appdir, 'overtime-nhl19.desktop'), encoding='utf-8').read()
    assert 'Exec=OvertimeNHL19\n' in entry and 'Icon=overtime-nhl19\n' in entry
    # the window's class is the one the app-menu entry the app writes names: one icon in the task bar, not two
    assert 'StartupWMClass=OvertimeNHL19\n' in entry and 'StartupWMClass=OvertimeNHL19\n' in desktopentry.text('/x')
    assert open(os.path.join(appdir, '.DirIcon'), 'rb').read() == b'png'
    assert os.path.isfile(os.path.join(appdir, 'overtime-nhl19.png'))


def test_the_appimage_carries_the_system_libraries_not_every_desktop_has(tmp_path):
    spec = _spec()
    assert 'libwayland-server.so.0' in spec['libraries']['linux']      # Ubuntu 24.04 comes without it
    inner = tmp_path / 'app' / '_internal'
    inner.mkdir(parents=True)
    (inner / 'libxcb-cursor.so.0').write_bytes(b'PyInstaller took this one')
    libs = tmp_path / 'lib'
    libs.mkdir()
    (libs / 'libwayland-server.so.0.22.0').write_bytes(b'ELF the library')
    if hasattr(os, 'symlink') and os.name != 'nt':
        os.symlink('libwayland-server.so.0.22.0', libs / 'libwayland-server.so.0')
    else:
        (libs / 'libwayland-server.so.0').write_bytes(b'ELF the library')
    assert build_unix.carry_libraries(spec, str(tmp_path / 'app'), dirs=(str(libs),)) == ['libwayland-server.so.0']
    assert (inner / 'libwayland-server.so.0').read_bytes() == b'ELF the library'      # the file, not a link to it
    assert (inner / 'libxcb-cursor.so.0').read_bytes() == b'PyInstaller took this one'
    assert build_unix.carry_libraries(spec, str(tmp_path / 'app'), dirs=(str(libs),)) == []


def test_a_build_machine_without_a_listed_library_stops_the_build(tmp_path):
    (tmp_path / 'app' / '_internal').mkdir(parents=True)
    with pytest.raises(build_unix.BuildError, match='libwayland-server.so.0 is not on this machine'):
        build_unix.carry_libraries({'libraries': {'linux': ['libwayland-server.so.0']}}, str(tmp_path / 'app'), dirs=())


def test_the_download_keeps_the_exec_bit(tmp_path):
    image = tmp_path / 'OvertimeNHL19-x86_64-nodata.AppImage'
    image.write_bytes(b'\x7fELF' + b'0' * 100)
    out = build_unix.make_tarball(str(image), str(tmp_path / 'x.tar.gz'))
    with tarfile.open(out) as tar:
        (member,) = tar.getmembers()
        assert member.name == 'OvertimeNHL19-x86_64.AppImage'       # the name the app looks for, whatever the build
        assert member.mode == 0o755 and member.uid == 0 and member.uname == ''
        assert tar.extractfile(member).read() == image.read_bytes()


def test_the_record_is_what_latest_json_takes(tmp_path):
    image = tmp_path / 'OvertimeNHL19-x86_64.AppImage'
    image.write_bytes(b'image')
    tarball = tmp_path / 'OvertimeNHL19-linux.tar.gz'
    tarball.write_bytes(b'tarball')
    value = build_unix.record('linux', [str(image), str(tarball)], str(tmp_path), '0.97.0')
    assert value == {'version': '0.97.0', 'exe': 'OvertimeNHL19-x86_64.AppImage',
                     'sha256': build_unix.sha256(str(image)), 'size': 5}
    assert json.load(open(tmp_path / 'release-linux.json')) == value
    sums = open(tmp_path / 'SHA256SUMS-linux.txt', 'rb').read()
    assert sums.count(b'\n') == 2 and b'\r' not in sums
    assert f'{value["sha256"]}  OvertimeNHL19-x86_64.AppImage\n'.encode() in sums
    # the app reads it as its system's release (selfupdate.from_json) and takes the file by that name and sum
    feed = {'version': '0.97.0', 'exe': 'OvertimeNHL19.exe', 'sha256': '0' * 64, 'size': 1, 'linux': value}
    release = selfupdate.from_json(feed, 'https://example.test/app/', lambda url: sums.decode(),
                                   asset=selfupdate.LINUX_ASSET)
    assert release.exe_url == 'https://example.test/app/OvertimeNHL19-x86_64.AppImage'
    assert release.digest == value['sha256'] and release.size == 5
    mac = build_unix.record('darwin', [str(tarball)], str(tmp_path), '0.97.0')
    assert mac['exe'] == 'OvertimeNHL19-linux.tar.gz' and os.path.isfile(tmp_path / 'release-macos.json')


def test_the_record_can_be_written_again_for_the_files_that_are_there(tmp_path, monkeypatch, capsys):
    """A notarized dmg is another file than the one the build summed: --record-only sums what is there now."""
    monkeypatch.setattr(build_unix.sys, 'platform', 'darwin')
    assert build_unix.main(['--out', str(tmp_path), '--record-only']) == 1          # nothing built
    dmg = tmp_path / 'OvertimeNHL19-macos.dmg'
    dmg.write_bytes(b'first')
    assert build_unix.built('darwin', str(tmp_path)) == [str(dmg)]
    assert build_unix.built('linux', str(tmp_path)) == []                           # the AppImage and its tar.gz
    dmg.write_bytes(b'stapled')
    capsys.readouterr()
    assert build_unix.main(['--out', str(tmp_path), '--record-only']) == 0
    value = json.loads(capsys.readouterr().out)
    assert value['sha256'] == build_unix.sha256(str(dmg)) and value['size'] == 7
    (tmp_path / 'OvertimeNHL19-macos.dmg').unlink()
    (tmp_path / 'OvertimeNHL19-macos-nodata.dmg').write_bytes(b'x')
    assert build_unix.built('darwin', str(tmp_path)) == [str(tmp_path / 'OvertimeNHL19-macos-nodata.dmg')]


def test_the_icon_png_is_drawn_from_the_ico(tmp_path):
    image = pytest.importorskip('PIL.Image')
    ico = os.path.join(ROOT, 'overtime_roster', 'assets', 'app.ico')
    png = build_unix.make_png(ico, str(tmp_path / 'app.png'))
    with image.open(png) as im:
        assert im.format == 'PNG' and im.size == (256, 256) and im.mode == 'RGBA'


def test_this_pc_is_told_to_use_the_windows_build(capsys, monkeypatch):
    monkeypatch.setattr(build_unix.sys, 'platform', 'win32')
    assert build_unix.main([]) == 2
    assert 'build.ps1' in capsys.readouterr().err


# --- smoke.py --------------------------------------------------------------------------------------------------------
GOOD = 'Overtime Roster 0.97.0 selftest  frozen=True\nok    import webview\nPASS\n'
NO_DATA = ('Overtime Roster 0.97.0 selftest  frozen=True\nok    import webview\n'
           'FAIL  no default roster (nhl_game.db) in the exe\nFAIL (1)\n')
BROKEN = NO_DATA.replace('FAIL (1)', 'FAIL  import webview: No module named PySide6\nFAIL (2)')


def test_a_smoke_run_passes_on_pass_alone():
    assert smoke.passed(GOOD, 0)
    assert not smoke.passed(GOOD, 1)                # said PASS and ended badly: not a pass
    assert not smoke.passed('', 0)                  # said nothing
    assert not smoke.passed(NO_DATA, 1)


def test_a_build_without_data_may_lack_the_default_roster_and_nothing_else():
    assert smoke.passed(NO_DATA, 1, nodata=True)
    assert not smoke.passed(BROKEN, 1, nodata=True)
    assert smoke.unexpected(BROKEN, nodata=True) == ['FAIL  import webview: No module named PySide6']
    assert not smoke.passed('Traceback (most recent call last):\nImportError: libEGL.so.1\n', 1, nodata=True)


def test_the_smoke_run_asks_both_questions_and_survives_a_hang(capsys):
    import subprocess
    asked = []

    def runner(cmd, **kw):
        asked.append(cmd[1])
        if cmd[1] == '--selftest-window':
            raise subprocess.TimeoutExpired(cmd, kw['timeout'])
        # Qt and Chromium warn on stderr at every healthy start: that is not the verdict
        noise = 'qt.qpa.plugin: offscreen' + chr(10) + 'libEGL warning' + chr(10)
        return subprocess.CompletedProcess(cmd, 0, GOOD, noise)
    assert smoke.main(['./app', '--timeout', '5'], runner) == 1
    assert asked == ['--selftest', '--selftest-window']
    out = capsys.readouterr().out
    assert 'no answer within 5 s' in out and 'smoke: --selftest failed' not in out
    assert '--- --selftest stderr' in out and 'libEGL warning' in out            # shown, for the run's log
    assert smoke.main(['./app', '--no-window'], runner) == 0

    def missing(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    assert smoke.main(['./app', '--no-window'], missing) == 1
