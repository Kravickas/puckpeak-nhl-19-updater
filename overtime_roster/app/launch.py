"""Play: start NHL 19 in shadPS4 and read back from the emulator's log whether the Overtime patch and ShadNet took.

The game starts from the folder whose `user\\` is the emulator's data folder (gamesetup.start_dir: the exe's own
folder for a portable `user\\` beside it or %APPDATA%, the parent of a `user` data folder set by hand), with the
patch from its patches folder (gamesetup.install), or with `-p <file>` when one is given (that skips the folder).

stop_emulator() closes a running NHL 19 (WM_CLOSE to its window, then terminate) so lobby Ready can restart it with the
match setup. It is only for lobby Ready; nothing else in the app stops shadPS4.
"""
import csv
import os
import re
import subprocess
import sys
import time

from overtime_core import gamefiles, overlay

from . import gamesetup, onlinetag, selfupdate


class LaunchError(RuntimeError):
    pass


def command(emu_exe, game_dir, patch_file=None):
    """shadPS4 starts the base game's eboot.bin and lays its `-UPDATE` / `-patch` and `-mods` folders over it."""
    cmd = [os.path.abspath(emu_exe), '-g', os.path.join(gamefiles.roots(game_dir)[0], 'eboot.bin')]
    if patch_file:
        cmd += ['-p', os.path.abspath(patch_file)]
    return cmd


def start(emu_exe, game_dir, patch_file=None, running=None, popen=subprocess.Popen, exe=None):
    """Start the game; returns the process. Refuses while another shadPS4 runs (one emulator at a time: the caller
    stops it first, stop_emulator). `exe` starts another shadPS4 instead of the player's own `emu_exe` (the online copy
    for a lobby match). The start folder is always the player's own shadPS4's (gamesetup.start_dir(emu_exe)): shadPS4
    takes `user\\` in the folder it starts from, so the copy plays on the player's saves, sign-in and config
    (docs/notes/match-setup.md 0e)."""
    if (running or overlay.emulator_running)():
        raise LaunchError('shadPS4 is already running.')
    run = exe or emu_exe
    if not os.path.isfile(run):
        raise LaunchError(f'shadPS4 not found: {run}')
    game = gamesetup.read_game(game_dir)
    if not game['ok']:
        raise LaunchError(f'cannot start {game_dir}: {game["problem"]}')
    cwd = gamesetup.start_dir(emu_exe)
    if not cwd:
        raise LaunchError(f'shadPS4 cannot use the data folder {gamesetup.emu_user_dir(emu_exe)}: it reads the "user" '
                          'folder inside the folder it starts from, or %APPDATA%\\shadPS4. Pick one of those in Setup, '
                          'Folders, shadPS4 data.')
    try:        # the matchmaking tag of this very start: only games that stay in step meet (onlinetag.py)
        onlinetag.apply(emu_exe, game_dir, patch_file, exe)
    except onlinetag.TagError as err:
        raise LaunchError(str(err)) from err
    flags = 0
    if sys.platform == 'win32':
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return popen(command(run, game_dir, patch_file), cwd=cwd,
                 creationflags=flags, close_fds=True, env=selfupdate.clean_environment())


WM_CLOSE = 0x0010
POLL = 0.5          # seconds between process checks while waiting
KILL_WAIT = 5       # seconds a terminated shadPS4 gets to disappear


def _no_window():
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def parse_tasklist(text):
    """[(pid, lower-case name)] of the shadPS4 game processes in `tasklist /FO CSV /NH` output. The name rule is
    overlay.emulator_running's: names starting with shadps4, not the Qt launcher."""
    found = []
    for row in csv.reader(text.splitlines()):
        if len(row) < 2:
            continue                                    # blank or "INFO: No tasks ..." lines
        name = row[0].strip().lower()
        if not name.startswith('shadps4') or 'launcher' in name:
            continue
        try:
            found.append((int(row[1].strip()), name))
        except ValueError:
            continue
    return found


def game_processes(run=subprocess.run):
    """[(pid, name)] of the running shadPS4 game processes (Windows), or None when tasklist could not be read."""
    try:
        out = run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, timeout=30,
                  creationflags=_no_window()).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_tasklist(out or '')


class Windows:
    """Top-level windows through a private user32 handle (ctypes), with argtypes set so 64-bit HWNDs pass intact."""

    def __init__(self, user32=None):
        import ctypes
        from ctypes import wintypes
        self._ctypes, self._wt = ctypes, wintypes
        self._enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user32 = user32 if user32 is not None else self._load()

    def _load(self):
        ct, wt = self._ctypes, self._wt
        u = ct.WinDLL('user32', use_last_error=True)       # private: these argtypes never touch ctypes.windll.user32
        u.EnumWindows.argtypes = [self._enum_proc, wt.LPARAM]
        u.EnumWindows.restype = wt.BOOL
        u.GetWindowThreadProcessId.argtypes = [wt.HWND, ct.POINTER(wt.DWORD)]
        u.GetWindowThreadProcessId.restype = wt.DWORD
        u.IsWindowVisible.argtypes = [wt.HWND]
        u.IsWindowVisible.restype = wt.BOOL
        u.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        u.PostMessageW.restype = wt.BOOL
        return u

    def visible_of(self, pids):
        """Handles of the visible top-level windows owned by `pids`."""
        pids, found = set(pids), []

        def each(hwnd, _lparam):
            try:
                pid = self._wt.DWORD()
                if not self.user32.GetWindowThreadProcessId(hwnd, self._ctypes.pointer(pid)):
                    return 1                            # the window went away meanwhile
                if pid.value in pids and self.user32.IsWindowVisible(hwnd):
                    found.append(hwnd)
            except Exception:                           # a callback must not raise: ctypes would only print it
                pass
            return 1

        callback = self._enum_proc(each)                # kept referenced for the whole EnumWindows call
        self.user32.EnumWindows(callback, 0)
        return found

    def close(self, hwnd):
        """Ask a window to close (WM_CLOSE, posted: never waits on the window)."""
        return bool(self.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))


def _taskkill(pid, run=subprocess.run):
    try:
        run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, text=True, timeout=30,
            creationflags=_no_window())
    except (OSError, subprocess.SubprocessError):
        pass                                            # the process list after it decides


def _wait_gone(pids, seconds, processes, sleep, clock):
    """Poll until none of `pids` runs or `seconds` pass; returns the pids still running (an unreadable list keeps
    the last known ones)."""
    left, end = set(pids), clock() + seconds
    while True:
        now = processes()
        if now is not None:
            left = set(pids) & {pid for pid, _ in now}
            if not left:
                return left
        if clock() >= end:
            return left
        sleep(POLL)


def stop_emulator(grace=10, *, processes=None, windows=None, kill=None, sleep=time.sleep, clock=time.monotonic):
    """Close the running shadPS4 game so lobby Ready can restart NHL 19 with the match setup. WM_CLOSE to its windows
    first so the game can shut down cleanly, up to `grace` seconds, then terminate what is left (taskkill /T /F).
    Returns 'none' (nothing ran), 'closed', 'killed', 'failed' (still running, or the process list was unreadable), or
    'unsupported' off Windows (nothing is done there; the player closes NHL 19)."""
    if sys.platform != 'win32':
        return 'unsupported'
    processes = processes or game_processes
    found = processes()
    if found is None:
        return 'failed'
    pids = {pid for pid, _ in found}
    if not pids:
        return 'none'
    asked = 0
    try:
        win = windows if windows is not None else Windows()
        for hwnd in win.visible_of(pids):
            asked += bool(win.close(hwnd))
    except Exception:                                   # no window API: terminating is the fallback
        asked = 0
    left = _wait_gone(pids, grace if asked else 0, processes, sleep, clock)
    if not left:
        return 'closed'
    for pid in sorted(left):
        (kill or _taskkill)(pid)
    return 'failed' if _wait_gone(left, KILL_WAIT, processes, sleep, clock) else 'killed'


def log_path(emu_exe):
    return os.path.join(gamesetup.emu_user_dir(emu_exe), 'log', 'shad_log.txt')


APPLIED = re.compile(r'Applied patch: (?P<name>.+?), Offset: (?P<addr>0x[0-9a-fA-F]+)')
CRITICAL = re.compile(r'.*<Critical>.*')


def read_log(text):
    """{'patches': {block name: lines applied}, 'shadnet': True | False | None, 'crash': first critical line or None}.
    ShadNet is None when the log never reached NP (an early stop proves nothing)."""
    patches = {}
    for m in APPLIED.finditer(text):
        patches[m.group('name')] = patches.get(m.group('name'), 0) + 1
    if re.search(r'no users connected to shadNet', text, re.I):
        shadnet = False
    elif re.search(r'Lib\.Np', text):
        shadnet = True
    else:
        shadnet = None
    crash = CRITICAL.search(text)
    return {'patches': patches, 'shadnet': shadnet, 'crash': crash.group(0).strip() if crash else None}


def check(emu_exe):
    """read_log() of the emulator's current log, or None when there is none."""
    try:
        with open(log_path(emu_exe), encoding='utf-8', errors='replace') as f:
            return read_log(f.read())
    except OSError:
        return None
