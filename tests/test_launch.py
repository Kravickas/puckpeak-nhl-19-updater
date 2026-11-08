"""launch.stop_emulator (lobby Ready restarts NHL 19) and launch.start's online-copy exe. Every process list, window
and kill here is a fake: nothing touches a real process or window."""
import ctypes
import subprocess
import sys

import pytest

from overtime_roster.app import gamesetup, launch
from test_gamesetup import world  # noqa: F401

TASKLIST = '''"System Idle Process","0","Services","0","8 K"
"shadPS419.exe","4242","Console","1","2,345,678 K"
"shadPS4QtLauncher.exe","5151","Console","1","80,000 K"
"ShadPS4.exe","4343","Console","1","1,000 K"
"notshadps4.exe","999","Console","1","1 K"
"shadPS4.exe","not a pid","Console","1","1 K"
'''


def test_parse_tasklist_keeps_game_processes_only():
    assert launch.parse_tasklist(TASKLIST) == [(4242, 'shadps419.exe'), (4343, 'shadps4.exe')]
    assert launch.parse_tasklist('INFO: No tasks are running which match the specified criteria.\n') == []
    assert launch.parse_tasklist('') == []


def test_game_processes_reads_tasklist_or_says_unknown():
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=TASKLIST)

    assert launch.game_processes(run) == [(4242, 'shadps419.exe'), (4343, 'shadps4.exe')]
    assert seen == [['tasklist', '/FO', 'CSV', '/NH']]

    def broken(cmd, **kw):
        raise OSError('no tasklist')

    assert launch.game_processes(broken) is None


class Emu:
    """A fake world: running pids, windows per pid, and how processes react to WM_CLOSE and to a kill."""

    def __init__(self, pids, closes=True, dies_on_kill=True, windows=True):
        self.running = set(pids)
        self.closes, self.dies_on_kill, self.has_windows = closes, dies_on_kill, windows
        self.closed, self.killed, self.slept, self.now = [], [], [], 0.0

    def processes(self):
        return [(pid, 'shadps419.exe') for pid in sorted(self.running)]

    def visible_of(self, pids):
        return [pid * 10 for pid in sorted(pids) if pid in self.running] if self.has_windows else []

    def close(self, hwnd):
        self.closed.append(hwnd)
        if self.closes:
            self.running.discard(hwnd // 10)
        return True

    def kill(self, pid):
        self.killed.append(pid)
        if self.dies_on_kill:
            self.running.discard(pid)

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def clock(self):
        return self.now

    def stop(self, grace=10, **kw):
        args = dict(processes=self.processes, windows=self, kill=self.kill, sleep=self.sleep, clock=self.clock)
        args.update(kw)
        return launch.stop_emulator(grace, **args)


@pytest.fixture
def windows_only(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')


def test_off_windows_nothing_is_done(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    emu = Emu([4242])
    assert emu.stop(processes=lambda: pytest.fail('listed processes')) == 'unsupported'
    assert emu.running == {4242} and not emu.closed and not emu.killed


def test_nothing_running(windows_only):
    emu = Emu([])
    assert emu.stop(windows=None) == 'none'
    assert not emu.closed and not emu.killed


def test_an_unreadable_process_list_is_a_failure_not_none(windows_only):
    emu = Emu([4242])
    assert emu.stop(processes=lambda: None) == 'failed'
    assert not emu.closed and not emu.killed


def test_the_game_closes_on_wm_close_and_is_never_killed(windows_only):
    emu = Emu([4242])
    assert emu.stop() == 'closed'
    assert emu.closed == [42420] and emu.killed == []


def test_a_game_that_ignores_wm_close_is_killed_after_the_grace(windows_only):
    emu = Emu([4242, 4343], closes=False)
    assert emu.stop(grace=10) == 'killed'
    assert emu.closed == [42420, 43430] and emu.killed == [4242, 4343]
    assert 10 <= emu.now < 10 + launch.POLL * 2                 # waited the grace (fake clock), no longer


def test_a_slow_close_inside_the_grace_counts_as_closed(windows_only):
    emu = Emu([4242], closes=False)
    real = emu.sleep

    def sleep(seconds):
        real(seconds)
        if emu.now >= 3:
            emu.running.clear()                                  # saved and quit after 3 s

    assert emu.stop(sleep=sleep) == 'closed'
    assert emu.killed == [] and 3 <= emu.now < 4


def test_no_window_skips_the_wait(windows_only):
    emu = Emu([4242], windows=False)
    assert emu.stop() == 'killed'
    assert emu.closed == [] and emu.killed == [4242] and emu.now == 0


def test_a_broken_window_api_still_terminates(windows_only):
    class Broken:
        def visible_of(self, pids):
            raise OSError('no user32')

    emu = Emu([4242])
    assert emu.stop(windows=Broken()) == 'killed'
    assert emu.killed == [4242]


def test_a_process_that_survives_the_kill_is_a_failure(windows_only):
    emu = Emu([4242], closes=False, dies_on_kill=False)
    assert emu.stop(grace=2) == 'failed'
    assert emu.killed == [4242]
    assert emu.now >= 2 + launch.KILL_WAIT


def test_only_the_survivors_are_killed(windows_only):
    emu = Emu([4242, 4343], closes=False)
    real = emu.close

    def close(hwnd):                                             # only 4242 listens
        real(hwnd)
        if hwnd == 42420:
            emu.running.discard(4242)
        return True

    emu.close = close
    assert emu.stop() == 'killed'
    assert emu.killed == [4343]


def test_taskkill_command():
    seen = []
    launch._taskkill(4242, run=lambda cmd, **kw: seen.append(cmd))
    assert seen == [['taskkill', '/PID', '4242', '/T', '/F']]

    def broken(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 30)

    launch._taskkill(4242, run=broken)                           # swallowed: the re-list decides


class FakeUser32:
    """user32 for launch.Windows: EnumWindows drives the real ctypes callback; PostMessageW only records."""

    def __init__(self, windows):
        self.windows, self.posted = windows, []                  # {hwnd: (pid, visible)}

    def EnumWindows(self, callback, lparam):
        for hwnd in self.windows:
            if not callback(hwnd, lparam):
                break
        return 1

    def GetWindowThreadProcessId(self, hwnd, pid_ptr):
        pid = self.windows[hwnd][0]
        if pid is None:
            return 0                                             # destroyed: fails, out-param untouched
        pid_ptr.contents.value = pid
        return 1

    def IsWindowVisible(self, hwnd):
        return self.windows[hwnd][1]

    def PostMessageW(self, hwnd, msg, wparam, lparam):
        self.posted.append((hwnd, msg, wparam, lparam))
        return 1


needs_win = pytest.mark.skipif(not hasattr(ctypes, 'WINFUNCTYPE'), reason='Windows ctypes')


@needs_win
def test_windows_finds_visible_windows_of_the_pids_and_posts_wm_close():
    big = 0x7fff_1234_5678                                       # a 64-bit HWND passes through intact
    user32 = FakeUser32({big: (4242, True), 0x20: (4242, False), 0x30: (777, True)})
    win = launch.Windows(user32)
    assert win.visible_of({4242}) == [big]
    assert win.close(big) is True
    assert user32.posted == [(big, 0x0010, 0, 0)]


@needs_win
def test_windows_callback_errors_do_not_stop_the_scan():
    user32 = FakeUser32({0x10: (4242, True), 0x20: (4242, True)})
    real = user32.GetWindowThreadProcessId

    def flaky(hwnd, ptr):
        if hwnd == 0x10:
            raise RuntimeError('gone')
        return real(hwnd, ptr)

    user32.GetWindowThreadProcessId = flaky
    assert launch.Windows(user32).visible_of({4242}) == [0x20]


@needs_win
def test_a_window_destroyed_mid_scan_is_skipped():
    user32 = FakeUser32({0x10: (None, True), 0x20: (4242, True)})
    assert launch.Windows(user32).visible_of({0, 4242}) == [0x20]


@needs_win
def test_the_real_user32_lists_windows_without_posting():
    """Read-only: EnumWindows over the real desktop with the argtypes set. No pid is ours to close, so nothing is
    posted (pid 0 owns no top-level window)."""
    win = launch.Windows()
    assert win.user32 is not ctypes.windll.user32
    assert win.visible_of({0}) == []


def test_start_runs_the_online_copy_from_the_players_own_start_folder(world, monkeypatch):   # noqa: F811
    copy_dir = world['tmp'] / 'apphome' / 'online-emu' / 'abc123'
    copy_dir.mkdir(parents=True)
    copy = copy_dir / 'shadPS4.exe'
    copy.write_bytes(b'MZ')
    calls = []
    launch.start(str(world['emu']), str(world['game']), 'match.xml', running=lambda: False,
                 popen=lambda cmd, **kw: calls.append((cmd, kw)) or 'proc', exe=str(copy))
    cmd, kw = calls[0]
    assert cmd[0] == str(copy) and cmd[1:3] == ['-g', str(world['game'] / 'eboot.bin')]
    assert cmd[3] == '-p' and cmd[4].endswith('match.xml')
    assert kw['cwd'] == gamesetup.start_dir(str(world['emu']))   # the player's data, not the copy's folder
    portable = world['tmp'] / 'portable'
    (portable / 'user').mkdir(parents=True)
    own = portable / 'shadPS4.exe'
    own.write_bytes(b'MZ')
    calls.clear()
    launch.start(str(own), str(world['game']), running=lambda: False,
                 popen=lambda cmd, **kw: calls.append((cmd, kw)) or 'proc', exe=str(copy))
    assert calls[0][0][0] == str(copy) and calls[0][1]['cwd'] == str(portable)   # a portable own install's user\
    monkeypatch.setattr(gamesetup, 'start_dir', lambda e: None)
    with pytest.raises(launch.LaunchError, match='data folder'):
        launch.start(str(own), str(world['game']), running=lambda: False, popen=None, exe=str(copy))


def test_start_with_the_copy_still_refuses_while_shadps4_runs(world):   # noqa: F811
    with pytest.raises(launch.LaunchError, match='already running'):
        launch.start(str(world['emu']), str(world['game']), running=lambda: True, popen=None,
                     exe=str(world['emu']))
    with pytest.raises(launch.LaunchError, match='not found'):
        launch.start(str(world['emu']), str(world['game']), running=lambda: False, popen=None,
                     exe=str(world['tmp'] / 'missing' / 'shadPS4.exe'))
