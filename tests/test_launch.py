"""launch.stop_emulator (lobby Ready restarts NHL 19) and launch.start's online-copy exe. Every process list, window
and kill here is a fake: nothing touches a real process or window."""
import ctypes
import subprocess
import sys
import threading

import pytest

from overtime_core import overlay
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
    win = sys.platform == 'win32'

    def run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=TASKLIST if win else PS)

    want = [(4242, 'shadps419.exe'), (4343, 'shadps4.exe')] if win else [(4242, 'shadps4'), (4343, 'shadps4'), (4444, 'shadps4-sdl.app')]
    assert launch.game_processes(run) == want
    assert seen == [['tasklist', '/FO', 'CSV', '/NH'] if win else ['ps', '-A', '-o', 'pid=,comm=']]

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


PS = '''    1 systemd
 4242 shadps4
 4343 /Users/pat/Library/Application Support/OvertimeRoster/boost/native2/shadps4
 5151 shadPS4QtLaunch
 5252 /Applications/shadPS4QtLauncher.app/Contents/MacOS/shadPS4QtLauncher
  999 notshadps4
  abc shadps4
 4444 Shadps4-sdl.App
'''


def test_parse_ps_keeps_game_processes_only():
    """Linux prints the name cut to 15 characters (QtLauncher is shadPS4QtLaunch: it must not be stopped as the
    game), macOS the whole path (spaces in it too): the last part is the name."""
    assert launch.parse_ps(PS) == [(4242, 'shadps4'), (4343, 'shadps4'), (4444, 'shadps4-sdl.app')]
    assert launch.parse_ps('') == []
    assert overlay.launcher_process('shadPS4QtLaunch') and overlay.launcher_process('shadPS4QtLauncher.exe')
    assert not overlay.launcher_process('shadps4') and not overlay.launcher_process('shadPS419.exe')


def test_game_processes_reads_ps_off_windows(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    seen = []

    def run(cmd, **kw):
        seen.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, stdout=PS)

    assert launch.game_processes(run) == [(4242, 'shadps4'), (4343, 'shadps4'), (4444, 'shadps4-sdl.app')]
    assert seen[0][0] == ['ps', '-A', '-o', 'pid=,comm='] and 'creationflags' not in seen[0][1]

    def broken(cmd, **kw):
        raise OSError('no ps')

    assert launch.game_processes(broken) is None


@pytest.mark.parametrize('platform', ['linux', 'darwin'])
def test_off_windows_the_game_is_asked_then_killed_by_signal(monkeypatch, platform):
    """Linux and macOS: SIGTERM first (SDL's quit), SIGKILL for what stays: lobby Ready can restart NHL 19 there too."""
    import signal
    monkeypatch.setattr(sys, 'platform', platform)
    monkeypatch.setattr(signal, 'SIGKILL', 9, raising=False)        # Windows' signal module has no SIGKILL
    sent = []
    emu = Emu([4242, 4343])

    def kill(pid, sig):
        sent.append((pid, sig))
        if sig == signal.SIGTERM and pid == 4242:
            emu.running.discard(pid)                # this one closes when asked
        if sig == signal.SIGKILL:
            emu.running.discard(pid)

    monkeypatch.setattr(launch.os, 'kill', kill)
    assert emu.stop(windows=None, kill=None) == 'killed'
    assert sent == [(4242, signal.SIGTERM), (4343, signal.SIGTERM), (4343, signal.SIGKILL)]
    assert emu.slept and not emu.running

    sent.clear()
    emu = Emu([4242])
    assert emu.stop(windows=None, kill=None) == 'closed' and sent == [(4242, signal.SIGTERM)]


def test_off_windows_a_gone_process_is_not_an_error(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')

    def kill(pid, sig):
        raise ProcessLookupError(pid)

    monkeypatch.setattr(launch.os, 'kill', kill)
    assert launch.Signals().close(4242) is False
    launch._sigkill(4242) if hasattr(launch.signal, 'SIGKILL') else None


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
    if sys.platform == 'win32':                                  # owner 2026-11-13: above normal priority, every build
        assert kw['creationflags'] & launch.ABOVE_NORMAL == 0x8000
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


class FakeKernel32:
    def __init__(self, handle=77, ok=1):
        self.handle, self.ok, self.calls = handle, ok, []

    def OpenProcess(self, access, inherit, pid):
        self.calls.append(('open', access, pid))
        return self.handle

    def SetProcessInformation(self, handle, kind, state, size):
        self.calls.append(('set', handle, kind, size))
        return self.ok

    def CloseHandle(self, handle):
        self.calls.append(('close', handle))


@pytest.mark.windows_only
def test_full_speed_turns_power_throttling_off_and_never_raises():
    k = FakeKernel32()
    assert launch.full_speed(1234, k) is True
    assert k.calls == [('open', 0x0200, 1234), ('set', 77, 4, 12), ('close', 77)]   # ProcessPowerThrottling, 3 ULONGs
    assert launch.full_speed(1234, FakeKernel32(handle=0)) is False                 # the process is gone already
    refused = FakeKernel32(ok=0)
    assert launch.full_speed(1234, refused) is False and refused.calls[-1] == ('close', 77)
    assert launch.full_speed(1234, object()) is False                               # no such API: the game runs anyway


EMU_TITLE = 'shadPS4 v0.21.1 WIP Kravickas/overtime-nightly 1.0 | NHL 19'


class FakeTitles:
    """launch.Windows stand-in: {hwnd: [pid, visible, title]}. The test may change a title between looks."""

    def __init__(self, windows):
        self.windows, self.sets = windows, []

    def visible_of(self, pids):
        return [h for h, (pid, vis, _) in self.windows.items() if pid in pids and vis]

    def title(self, hwnd):
        return self.windows[hwnd][2]

    def set_title(self, hwnd, text):
        self.sets.append((hwnd, text))
        self.windows[hwnd][2] = text
        return True


class FakeClock:
    """sleep() moves the clock on; on_tick(n) runs after the n-th sleep."""

    def __init__(self, on_tick=None):
        self.now, self.slept, self.on_tick = 0.0, [], on_tick

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds
        if self.on_tick:
            self.on_tick(len(self.slept))


class FakeProc:
    pid = 4242

    def __init__(self):
        self.exit = None

    def poll(self):
        return self.exit


def test_title_is_set_on_the_emulators_window_only():
    win = FakeTitles({0x10: [4242, True, EMU_TITLE], 0x20: [777, True, 'Other app'], 0x30: [4242, False, EMU_TITLE]})
    proc = FakeProc()
    clk = FakeClock(on_tick=lambda n: setattr(proc, 'exit', 0) if n == 2 else None)
    launch._keep_title(proc, win, clk.sleep, clk.clock)
    assert win.windows[0x10][2] == 'NHL 19'
    assert win.windows[0x20][2] == 'Other app'                  # another process's window is not touched
    assert win.windows[0x30][2] == EMU_TITLE                    # hidden: not a window to title yet
    assert win.sets == [(0x10, 'NHL 19')]


def test_title_is_set_again_when_the_emulator_changes_it_back():
    win = FakeTitles({0x10: [4242, True, EMU_TITLE]})
    proc = FakeProc()

    def tick(n):
        if n == 3:
            win.windows[0x10][2] = EMU_TITLE                    # the emulator wrote its long title again
        if n == 6:
            proc.exit = 0

    clk = FakeClock(on_tick=tick)
    launch._keep_title(proc, win, clk.sleep, clk.clock)
    assert win.windows[0x10][2] == 'NHL 19'
    assert win.sets == [(0x10, 'NHL 19'), (0x10, 'NHL 19')]


def test_the_watch_stops_after_15_seconds_while_the_process_runs():
    win = FakeTitles({0x10: [4242, True, 'NHL 19']})
    clk = FakeClock()
    launch._keep_title(FakeProc(), win, clk.sleep, clk.clock)
    assert len(clk.slept) == 30 and clk.now == 15.0             # 30 looks at 0.5 s
    assert win.sets == []                                       # the title already reads NHL 19


def test_the_watch_stops_when_the_process_ends():
    win = FakeTitles({})
    proc = FakeProc()
    clk = FakeClock(on_tick=lambda n: setattr(proc, 'exit', 1) if n == 2 else None)
    launch._keep_title(proc, win, clk.sleep, clk.clock)
    assert len(clk.slept) == 2


def test_a_window_that_never_shows_does_not_block_start_or_raise():
    gate = threading.Event()
    proc = FakeProc()
    t = launch.title_watch(proc, windows=FakeTitles({0x10: [4242, False, EMU_TITLE]}), sleep=lambda s: gate.wait(5))
    assert t.daemon and t.is_alive()                            # returned at once, watching in the background
    gate.set()
    proc.exit = 0
    t.join(5)
    assert not t.is_alive()


def test_a_failing_window_api_is_logged_and_the_watch_stops(caplog):
    class Broken(FakeTitles):
        def visible_of(self, pids):
            raise RuntimeError('no user32')

    t = launch.title_watch(FakeProc(), windows=Broken({}), sleep=lambda s: None)
    t.join(5)
    assert not t.is_alive()
    assert 'window title' in caplog.text


def test_start_passes_the_window_title_in_the_emulators_environment(world, monkeypatch):   # noqa: F811
    seen = []
    monkeypatch.setattr(launch, 'title_watch', lambda proc, **kw: seen.append(proc))
    calls = []
    proc = launch.start(str(world['emu']), str(world['game']), running=lambda: False,
                        popen=lambda cmd, **kw: calls.append(kw) or 'proc')
    assert calls[0]['env']['OVERTIME_WINDOW_TITLE'] == 'NHL 19'
    assert 'PYINSTALLER_RESET_ENVIRONMENT' in calls[0]['env']
    assert seen == []                                           # a fake popen gets no window watch
    assert proc == 'proc'


@pytest.mark.skipif(sys.platform != 'win32', reason='the window watch is Windows only')
def test_start_watches_the_window_of_a_real_launch(world, monkeypatch):   # noqa: F811
    from overtime_roster.app import gameicon
    seen = []

    class FakePopen:
        pid = 4242

        def __init__(self, cmd, **kw):
            self.kw = kw

    monkeypatch.setattr(launch.subprocess, 'Popen', FakePopen)  # the start path checks `popen is subprocess.Popen`
    monkeypatch.setattr(launch, 'full_speed', lambda pid: True)
    monkeypatch.setattr(gameicon, 'watch', lambda *a, **kw: None)
    monkeypatch.setattr(launch, 'title_watch', lambda proc, **kw: seen.append(proc))
    proc = launch.start(str(world['emu']), str(world['game']), running=lambda: False, popen=FakePopen)
    assert seen == [proc] and proc.kw['env']['OVERTIME_WINDOW_TITLE'] == 'NHL 19'
