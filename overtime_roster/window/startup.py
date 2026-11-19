"""How long the exe takes to show its window, step by step, written to %APPDATA%\\OvertimeRoster\\logs\\startup.txt:
from the double-click (the onefile bootloader's start) to Python running (the unpack), the app built, the window
shown and the page loaded. Also closes PyInstaller's splash (packaging/build.ps1 --splash) once the window is up."""
import os
import sys
import time

MARKS = []


def _created(pid):
    """When process `pid` started (seconds since the epoch), or None."""
    if os.name != 'nt':
        return None
    import ctypes
    import ctypes.wintypes as wt
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wt.HANDLE
    handle = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        times = [wt.FILETIME() for _ in range(4)]
        if not k32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            return None
        ft = times[0].dwHighDateTime << 32 | times[0].dwLowDateTime
        return (ft - 116444736000000000) / 1e7
    finally:
        k32.CloseHandle(handle)


def launched():
    """The double-click: the bootloader (the parent of this onefile child), else this process."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return _created(os.getppid()) or _created(os.getpid())
    return _created(os.getpid())


def mark(name):
    MARKS.append((name, time.time()))


def close_splash():
    if 'pyi_splash' not in sys.modules and '_PYI_SPLASH_IPC' not in os.environ:    # no splash here: importing it only
        return                                  # writes a traceback to stderr (Linux, macOS, source runs)
    try:
        import pyi_splash  # the bootloader's splash (only in a build made with --splash)
        pyi_splash.close()
    except Exception:  # noqa: BLE001 (no splash: nothing to close)
        pass


def write(name='startup.txt'):
    start = launched()
    lines = []
    before = start
    for what, when in MARKS:
        lines.append(f'{what:<14} {when - start:6.2f} s   (+{when - before:.2f})' if start else f'{what:<14} {when:.2f}')
        before = when
    try:
        from ..app import paths
        with open(paths.app_dir('logs', name), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
    except OSError:
        pass
    return lines
