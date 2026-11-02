"""A window that never comes up must not stay that way (Legacy's blank window, docs/notes/legacy-0.92-check.md). After the
start the page has FIRST seconds to draw its data (Api.page_up). If it never asked for them it is loaded again; after
SECOND seconds more the window closes and the app opens in the player's browser. The graphics are off already
(main.run_window), so Legacy's restart without them is not needed."""
import ctypes
import os
import shutil
import threading

from ..app import paths
from . import startlog

FIRST, SECOND = 15.0, 20.0
FOLDER = 'webview'          # in the app's folder: one folder per start, named by its process


def running(pid):
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            pass
        return True
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)         # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
    return bool(handle)


def sweep(base):
    """What starts that crashed or were ended left (a window that closes deletes its own folder)."""
    for name in os.listdir(base):
        if name.isdigit() and not running(int(name)):
            shutil.rmtree(os.path.join(base, name), ignore_errors=True)


def browser_folder():
    """The browser's own folder, a new one for every start. In a folder shared by all starts, a browser still closing
    holds it and WebView2 refuses to start ("0x800700AA: The requested resource is in use"): an empty window for good.
    A closing window also deletes the folder under a start already using it."""
    base = paths.app_dir(FOLDER)
    threading.Thread(target=sweep, args=(base,), daemon=True).start()
    return os.path.join(base, str(os.getpid()))


class Watchdog:
    def __init__(self, window, first=FIRST, second=SECOND):
        self.window = window
        self.first, self.second = first, second
        self.outcome = None         # 'ok', 'reloaded', 'browser'

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()
        return self

    def reload(self):
        """Under a new address, not boot.js's own: asked for the one it has, the browser does nothing and pywebview,
        which waits for that page to load, stops answering the page that is there."""
        try:
            self.window.load_url(self.window.real_url.split('?')[0] + '?reloaded=1')
            return True
        except Exception as err:  # noqa: BLE001 (a window that is gone)
            startlog.note(f'could not load the page again: {err}')
        return False

    def to_browser(self, reason):
        """The way out: `main.run_window` opens the app in the browser when the window has closed."""
        startlog.note(f'opening the browser: {reason}')
        self.outcome = 'browser'
        self.window.destroy()

    def run(self):
        if startlog.page_up.wait(self.first):
            self.outcome = 'ok'
            return
        called = startlog.ready_called.is_set()
        startlog.note(f'nothing after {self.first:.0f} s: the page '
                      + ('asked for its data and did not draw it' if called else 'never asked for its data'))
        if not called:
            startlog.note('loading the page again' if self.reload() else 'the page cannot be loaded again')
        if startlog.page_up.wait(self.second):
            startlog.note('the page came up after the wait')
            self.outcome = 'reloaded'
            return
        self.to_browser(f'the page did not come up within {self.first + self.second:.0f} seconds')
