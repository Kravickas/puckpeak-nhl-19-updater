"""Where the app and shadPS4 keep their data on Windows, Linux and macOS, what a shadPS4 program file is called there,
and how a file is opened (docs/notes/linux-support.md, macos-support.md)."""
import os
import subprocess
import sys

import pytest

from overtime_roster.app import gamesetup, paths
from overtime_roster.window import host


@pytest.fixture
def no_appdata(monkeypatch, tmp_path):
    monkeypatch.delenv('APPDATA', raising=False)
    monkeypatch.delenv('XDG_DATA_HOME', raising=False)
    monkeypatch.delenv('OVERTIME_ROSTER_HOME', raising=False)
    monkeypatch.delenv('OVERTIME_SAVE_DIR', raising=False)
    monkeypatch.setattr(os.path, 'expanduser', lambda p: p.replace('~', str(tmp_path / 'home'), 1))
    return tmp_path / 'home'


def test_a_set_appdata_is_the_root_on_every_system(monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path / 'roaming'))
    for system in ('win32', 'linux', 'darwin'):
        monkeypatch.setattr(sys, 'platform', system)
        assert paths.data_root() == str(tmp_path / 'roaming')


def test_linux_uses_the_xdg_data_folder(monkeypatch, no_appdata, tmp_path):
    monkeypatch.setattr(sys, 'platform', 'linux')
    assert paths.data_root() == os.path.join(str(no_appdata), '.local', 'share')
    assert gamesetup.appdata_dir() == os.path.join(str(no_appdata), '.local', 'share', 'shadPS4')
    assert gamesetup.data_label() == '~/.local/share/shadPS4'
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'xdg'))          # a Steam Deck sets none; a Flatpak does
    assert paths.data_root() == str(tmp_path / 'xdg')
    assert paths.default_save_dir('CUSA11116') == os.path.join(
        str(tmp_path / 'xdg'), 'shadPS4', 'home', '1000', 'savedata', 'CUSA11116')
    assert paths.app_home() == os.path.join(str(tmp_path / 'xdg'), 'OvertimeRoster')


def test_macos_uses_application_support(monkeypatch, no_appdata):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    root = os.path.join(str(no_appdata), 'Library', 'Application Support')
    assert paths.data_root() == root
    assert gamesetup.appdata_dir() == os.path.join(root, 'shadPS4')
    assert gamesetup.data_label() == '~/Library/Application Support/shadPS4'
    assert gamesetup._launcher_data() == os.path.join(root, gamesetup.LAUNCHER_DATA)


def test_windows_names_appdata_in_its_messages(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    assert gamesetup.data_label() == '%APPDATA%' + chr(92) + 'shadPS4'


@pytest.mark.parametrize('name, system, emulator, launcher', [
    ('shadPS4.exe', 'win32', True, False),
    ('shadPS419.exe', 'win32', True, False),
    ('shadPS4QtLauncher.exe', 'win32', False, True),
    ('shadps4', 'win32', False, False),                     # no .exe: not a program on Windows
    ('shadps4', 'linux', True, False),
    ('Shadps4-sdl.AppImage', 'linux', True, False),
    ('shadPS4QtLauncher', 'linux', False, True),
    ('shadPS4QtLauncher-qt.AppImage', 'linux', False, True),
    ('shadPS4.exe', 'linux', False, False),                 # a Windows build in a Linux folder is not started
    ('shadps4.desktop', 'linux', False, False),
    ('shadps4-linux-sdl.zip', 'linux', False, False),
    ('shadps4', 'darwin', True, False),
    ('readme.txt', 'linux', False, False),
])
def test_a_shadps4_program_file_by_system(name, system, emulator, launcher):
    assert gamesetup._is_emulator(name, system) is emulator
    assert gamesetup._is_launcher(name, system) is launcher


@pytest.mark.parametrize('system, program', [('linux', 'xdg-open'), ('darwin', 'open')])
def test_off_windows_a_file_opens_through_the_systems_opener(monkeypatch, tmp_path, system, program):
    monkeypatch.setattr(sys, 'platform', system)
    monkeypatch.setenv('LD_LIBRARY_PATH', '/tmp/_MEI1')
    monkeypatch.setenv('LD_LIBRARY_PATH_ORIG', '/usr/lib')
    monkeypatch.setattr(os, 'name', 'posix')
    monkeypatch.setattr(sys, '_MEIPASS', '/tmp/_MEI1', raising=False)
    calls = []
    assert host.open_file(str(tmp_path / 'log.txt'), popen=lambda cmd, **kw: calls.append((cmd, kw))) is True
    (cmd, kw), = calls
    assert cmd == [program, str(tmp_path / 'log.txt')]
    assert kw['env']['LD_LIBRARY_PATH'] == '/usr/lib' and kw['stdout'] is subprocess.DEVNULL


def test_off_windows_no_opener_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'platform', 'linux')

    def missing(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    assert host.open_file(str(tmp_path / 'log.txt'), popen=missing) is False
