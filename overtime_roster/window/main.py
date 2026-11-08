"""Starts the app: a pywebview window when pywebview and Microsoft's WebView2 are there, else (or with --browser) the
local web server opened in the default browser.

The exe (packaging/launcher.py) enters through `entry`, which also answers --selftest and --update."""
import os
import sys
import threading
import time
import webbrowser

from .. import APP_NAME, SITE, SITE_LABEL, TAGLINE, VERSION
from . import startlog, startup, watchdog, webview2
from .server import QUEUE, WEB

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(PACKAGE, 'assets')
PACKS = os.path.join(PACKAGE, 'packs')      # the build's packs/: the NHL 27 data pack only (absent from source)
ICON = os.path.join(ASSETS, 'app.ico')
TABS = ('setup', 'patch', 'update', 'roster', 'lines', 'strategy', 'jerseys', 'calendar', 'office',
        'multiplayer')   # web/js/main.js
NEEDED = [os.path.join(WEB, *p) for p in (
    ('index.html',), ('css', 'app.css'), ('css', 'tokens.css'), ('img', 'logo.png'),
    *(('js', f'{name}.js') for name in ('boot', 'main', 'bridge', 'store', 'lib', 'ui', 'shell', 'rail', 'savebar')),
    *(('js', 'tabs', f'{name}.js') for name in TABS + ('roster-face', 'roster-gear')),
    *(('css', 'tabs', f'{name}.css') for name in TABS),
    ('vendor', 'react.production.min.js'), ('vendor', 'react-dom.production.min.js'), ('vendor', 'htm.module.js'))]
BACKGROUND = '#111116'
TITLE_BAR = 0x161111        # the title bar's colour on Windows 11 (#111116 as Windows writes it: blue, green, red)
UPDATE_TICK = 3600          # seconds between two looks at whether the 12 hours are over (the first look is at start)
UPDATE_RETRY = 30           # seconds to wait while a job runs or a question is on screen before offering it again
LARGEST, SHARE, MIN_SIZE = (1760, 1100), (0.9, 0.94), (940, 640)   # the window: most of the screen (Legacy's fit)
WIDTH, HEIGHT = 1080, 780   # at least this where the screen has room (Legacy's old window)
HEADLESS = False            # the windowed exe has no console: browser mode then shows a box to stop it (launcher.py)


def have_pywebview():
    try:
        import webview  # noqa: F401
    except ImportError:
        return False
    return True


def missing_files():
    """The app's own files that are not there (an antivirus or a cleaner removed them from the temporary folder the
    exe unpacks into)."""
    return [p for p in NEEDED if not os.path.exists(p)]


def meta():
    """What the header shows (the page's `meta`)."""
    return {'app': APP_NAME, 'app_name': APP_NAME, 'version': VERSION, 'tagline': TAGLINE, 'site_label': SITE_LABEL,
            'site': SITE, 'title': [APP_NAME, 'NHL 19 on shadPS4', VERSION]}


def build(game_dir=None, save_dir=None, reopen=True):
    """The host, the controller and the page's api. reopen: open the roster opened last time (a job)."""
    from ..app.controller import Controller
    from .api import Api
    from .host import WebHost
    host = WebHost(meta())
    controller = Controller(host, game_dir=game_dir, save_dir=save_dir, reopen=reopen)
    return host, controller, Api(controller, host)


# --- self-update ------------------------------------------------------------------------------------
def _claim(ctl, text):
    """Take the controller's busy flag (no patch, save or copy job starts while it is held); False when a job runs."""
    if ctl is None:
        return True
    with ctl.lock:
        if ctl.busy:
            return False
        ctl.busy = text
    ctl.say(text, 'info', -1)
    return True


def _unclaim(ctl):
    if ctl is not None:
        with ctl.lock:
            ctl.busy = None
        ctl.say('')


def asking(ctl):
    """A question of the page is on screen (the update's box waits for its answer)."""
    shell = getattr(ctl, 'shell', None)
    return bool(getattr(shell, 'asking', None))


def update_check(host, quit, ask=None, force=False, ctl=None, first=False):
    """Look for a newer exe (`first`: the look at start; later ones at most every 12 hours) and, on Yes, swap it in
    and restart. Returns what happened: 'off' / 'busy' (a job of `ctl` runs or the page asks a question: offered
    again soon) / 'none' / 'told' (a newer one exists but this copy can't install it) / 'declined' / 'refused' /
    'failed' / 'updated' / 'asked' (the app's own question is shown).
    `ctl` (the Controller): while one of its jobs writes (patch, save, copy) nothing is swapped and the app is not
    closed; from Yes to the restart the update holds its busy flag."""
    from ..app import selfupdate
    if not force and not selfupdate.due(first=first):
        return 'off'
    if ctl is not None and (ctl.busy or asking(ctl)):
        return 'busy'
    selfupdate.mark_checked()
    release = selfupdate.latest()
    if release is None:
        return 'none'
    host.log(f'{APP_NAME} {release.text} is out (this is {VERSION}).')
    setup = getattr(ctl, 'setup', None)
    if setup is not None:   # Setup's This program card says so
        setup.newer = {'version': release.text, 'notes': [release.notes[:300]] if release.notes else []}
        ctl.changed('setup')
    if not selfupdate.running_exe() or not release.can_install():
        return 'told'
    shell = getattr(ctl, 'shell', None)
    if setup is not None and shell is not None and ask is None:
        # the app's own question (Update now / Later / Skip), with the download's progress in the Help bar: one
        # question, no Windows box. Setup asks about unsaved edits first, installs, and closes this copy.
        if setup.skipped == release.text:
            return 'declined'
        setup._ask_newer(release)
        return 'asked'
    ask = ask or webview2.message
    if unsaved_edits(ctl):  # the box cannot ask about them: Setup's card offers it (it asks first, Shell.ask_unsaved)
        selfupdate.mark_checked(now=0)      # and the next tick looks again
        host.log(f'{APP_NAME} {release.text} waits: your edits are not saved yet (Setup has the update).')
        return 'unsaved'
    notes = f'\n\n{release.notes[:600]}' if release.notes else ''
    if not ask(APP_NAME, f'{APP_NAME} {release.text} is out (you have {VERSION}).{notes}\n\n'
                         'Update now? The app closes and starts again.', ask=True):
        return 'declined'
    if not _claim(ctl, f'Updating {APP_NAME} to {release.text}...'):
        selfupdate.mark_checked(now=0)      # ask again at the next tick
        host.log(f'Update postponed: {ctl.busy} is still running.')
        webview2.message(APP_NAME, f'{ctl.busy} is still running. The update is offered again when it is done.',
                         info=True)
        return 'busy'
    try:
        selfupdate.install(release)
    except selfupdate.Refused as err:
        _unclaim(ctl)
        host.log(f'Update not installed: {err}')
        webview2.message(APP_NAME, f'{err}', info=True)
        return 'refused'
    except Exception as err:  # noqa: BLE001 (a failed download must not take the app down)
        _unclaim(ctl)
        host.log(f'Update failed: {err}')
        webview2.message(APP_NAME, f'The update did not work: {err}\n\nThis version keeps running.')
        return 'failed'
    quit()
    return 'updated'


def unsaved_edits(ctl):
    """How many applied edits the open roster has that Save has not written (0 without a Controller)."""
    parts = getattr(ctl, 'parts', None) or {}
    save = parts.get('save')
    try:
        return save.unsaved() if save is not None else 0
    except Exception:  # noqa: BLE001 (a question that cannot be asked must not keep the window open)
        return 0


def closing_guard(ctl, destroy):
    """The window's close button: with unsaved edits the page asks first (Shell.ask_unsaved 'close the program').
    Save first (after a good save) and Lose them close the window; Cancel keeps it open. Returns the handler for
    pywebview's `closing` event (False keeps the window open)."""
    state = {'go': False}

    def go():
        state['go'] = True
        threading.Thread(target=destroy, daemon=True, name='close').start()   # not inside the closing event

    def closing():
        if state['go'] or not unsaved_edits(ctl):
            return True
        ctl.shell.ask_unsaved('close the program', go=go)
        return False
    return closing


class Quit:
    """How to close the app after an update: the window's destroy, or (browser mode) the process. Set by the mode
    that is showing the app, so a window that failed to start is not the one that gets closed."""

    def __init__(self):
        self.fn = lambda: os._exit(0)

    def __call__(self):
        self.fn()


def start_update_ticks(host, quit, ctl=None):
    from ..app import selfupdate
    selfupdate.clean_leftovers()

    def loop():
        time.sleep(5)       # let the window come up first
        selfupdate.clean_leftovers()    # the old exe has quit by now (it is still closing when this one starts)
        first = True        # every start looks (Legacy 0.50.3: a version out the same day was not offered)
        while True:
            try:
                said = update_check(host, quit, ctl=ctl, first=first)
            except Exception:  # noqa: BLE001
                said = None
            if said == 'updated':
                return
            first = first and said == 'busy'    # still the start's look until it got past the job / question
            time.sleep(UPDATE_RETRY if said == 'busy' else UPDATE_TICK)
    threading.Thread(target=loop, daemon=True, name='selfupdate').start()


def start_match_restore(host):
    """A lobby match setup left by a crash or a closed app (matchsetup.py) comes back once shadPS4 is closed."""
    from ..app import matchsetup
    if not matchsetup.active():
        return None
    t = threading.Thread(target=lambda: matchsetup.restore_when_closed(log=host.log), daemon=True, name='match-restore')
    t.start()
    return t


# --- the two ways to show the app -------------------------------------------------------------------
def run_browser(host, api, port=0, open_browser=True, ready=None, quit=None):
    from .server import AppServer
    startup.close_splash()
    server = AppServer(api, host, port)
    url = server.url
    print(f'{APP_NAME} {VERSION} is running at {url}', flush=True)
    if ready:
        ready(server)
    if open_browser:
        threading.Timer(0.3, webbrowser.open, (url,)).start()
    if quit is not None:
        quit.fn = lambda: os._exit(0)
    if HEADLESS:            # no console to press Ctrl+C in: a box is the way to stop
        server.serve_background()
        webview2.message(APP_NAME, f'{APP_NAME} is open in your browser:\n{url}\n\n'
                                   'Keep this box open while you use it. Press OK to close the app.', info=True)
        server.shutdown()
        server.server_close()
        return 0
    print('Keep this window open while you use the app; press Ctrl+C to stop.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def dark_title_bar(window):
    """Windows: a dark title bar in the colour of the page (Windows 10 takes the dark mode only)."""
    if os.name != 'nt':
        return
    try:
        import ctypes
        hwnd = window.native.Handle.ToInt64()
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))          # dark mode
        colour = ctypes.c_int(TITLE_BAR)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colour), ctypes.sizeof(colour))  # caption colour (Windows 11)
    except Exception:  # noqa: BLE001
        pass


def fit(area):
    """(x, y, width, height) of the screen's free area (no taskbar) -> the window's (width, height, x, y): 90 % x
    94 % of it, centred, at most 1760 x 1100, at least 1080 x 780 where that fits and never under 940 x 640
    (Legacy's fit: a 1366 x 768 screen gets 1229 x 720)."""
    ax, ay, aw, ah = area
    w = min(LARGEST[0], max(min(WIDTH, aw), int(aw * SHARE[0])))
    h = min(LARGEST[1], max(min(HEIGHT, ah), int(ah * SHARE[1])))
    w, h = max(w, MIN_SIZE[0]), max(h, MIN_SIZE[1])
    return w, h, ax + max(0, (aw - w) // 2), ay + max(0, (ah - h) // 2)


def work_area(webview):
    """The main screen's free area in the window's units (Windows: its WorkingArea; elsewhere the screen less 80)."""
    screens = list(webview.screens)
    screen = next((s for s in screens if s.x == 0 and s.y == 0), screens[0])
    frame = getattr(screen, 'frame', None)
    try:
        return int(frame.X), int(frame.Y), int(frame.Width), int(frame.Height)
    except AttributeError:
        return int(screen.x), int(screen.y), int(screen.width), int(screen.height) - 80


def window_box(webview):
    try:
        return fit(work_area(webview))
    except Exception:  # noqa: BLE001 (no screen to measure: the old size)
        return 1400, 880, None, None


def picker(window):
    """host.picker for the window: Windows' folder or file picker (Legacy's host._dialog)."""
    def pick(folder, start, kinds):
        import webview
        mode = webview.FileDialog.FOLDER if folder else webview.FileDialog.OPEN
        start = start if start and os.path.isdir(start) else os.path.expanduser('~')
        try:
            picked = window.create_file_dialog(mode, directory=start, file_types=tuple(kinds or ()))
        except ValueError:      # a file type pywebview does not take: ask without
            picked = window.create_file_dialog(mode, directory=start)
        if not picked:
            return ''
        return picked if isinstance(picked, str) else picked[0]
    return pick


def roomy_server():
    """pywebview's local server (wsgiref's WSGIServer) listens with Python's queue of 5 connections; the page asks for
    more files at once, Windows refuses what does not fit and the window stays blank (Legacy's lab round 47c)."""
    from wsgiref.simple_server import WSGIServer
    WSGIServer.request_queue_size = QUEUE


WEB_TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css',
             '.png': 'image/png', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.json': 'application/json'}


def web_types():
    """pywebview's server names each file's type from `mimetypes`, which reads the Windows registry, where another
    program can have changed it. A browser refuses a module of another type and the window stays empty."""
    import mimetypes
    for ending, kind in WEB_TYPES.items():
        said = mimetypes.guess_type('file' + ending)[0]
        if said != kind:
            if said:
                startlog.note(f'this PC says {ending} files are {said}: using {kind}')
            mimetypes.add_type(kind, ending)


def run_window(host, api, quit=None, ctl=None):
    import webview
    startlog.begin(VERSION)
    roomy_server()
    web_types()
    # The page is flat UI: software drawing keeps it alive when a screen grabber (Snipping Tool, Win+Shift+S, OBS) or a
    # GPU reset takes the window's GPU surface away, which left it black or empty until a restart. OVERTIME_GPU=1 undoes it.
    if os.environ.get('OVERTIME_GPU') != '1':
        flags = os.environ.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', '')
        if '--disable-gpu' not in flags:
            os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = (flags + ' --disable-gpu').strip()
    width, height, x, y = window_box(webview)
    window = webview.create_window(f'{APP_NAME} {VERSION}', os.path.join(WEB, 'index.html'), js_api=api,
                                   width=width, height=height, x=x, y=y, min_size=MIN_SIZE,
                                   background_color=BACKGROUND, text_select=False)
    host.picker = picker(window)

    def send(text):
        window.evaluate_js(f'window.OT && window.OT.receive({text})')
    host.add_transport(send)
    dog = watchdog.Watchdog(window)
    api.way_out = dog.to_browser

    def shown():
        startup.mark('window shown')
        startup.close_splash()
        dark_title_bar(window)

    def loaded():
        startup.mark('page loaded')
        startup.write()
        startlog.note('page loaded')
    window.events.shown += shown
    window.events.loaded += loaded
    window.events.closing += closing_guard(ctl, window.destroy)
    if quit is not None:
        quit.fn = window.destroy
    dog.start()
    webview.start(http_server=True, private_mode=True, storage_path=watchdog.browser_folder(),
                  debug=os.environ.get('OVERTIME_DEVTOOLS') == '1', icon=ICON if os.path.exists(ICON) else None)
    if dog.outcome == 'browser':
        host.remove_transport(send)
        return run_browser(host, api, quit=quit)
    return 0


def main(browser=False, port=0, open_browser=True, game_dir=None, save_dir=None):
    if missing_files():
        startup.close_splash()
        webview2.message(APP_NAME, 'Some of the app\'s own files are missing (an antivirus or a cleaner may have '
                                   'removed them). Download the app again.')
        return 1
    host, controller, api = build(game_dir, save_dir)
    startup.mark('app built')
    start_match_restore(host)
    quit = Quit()
    if getattr(sys, 'frozen', False):       # the exe looks for a newer exe; source runs don't
        start_update_ticks(host, quit, controller)
    if not browser and not have_pywebview():
        print('pywebview is not installed: opening the app in your browser instead '
              '(install it with "pip install pywebview" for a window of its own).', file=sys.stderr)
        browser = True
    if not browser and not webview2.available():
        print('Microsoft Edge WebView2 Runtime is not installed: opening the app in your browser instead '
              f'(get it at {webview2.DOWNLOAD} for a window of its own).', file=sys.stderr)
        browser = True
    if browser:
        return run_browser(host, api, port, open_browser, quit=quit)
    try:
        return run_window(host, api, quit=quit, ctl=controller)
    except Exception as err:  # noqa: BLE001 (a broken WebView2: the browser still works)
        from ..app import jobs
        jobs.log_unexpected(err)
        print(f'The window could not start ({err}): opening the app in your browser instead.', file=sys.stderr)
        return run_browser(host, api, port, open_browser, quit=quit)


# --- the exe's own switches -------------------------------------------------------------------------
def _report(lines, name):
    """Print, or (the windowed exe has nowhere to print) write to %APPDATA%\\OvertimeRoster\\logs\\<name>."""
    text = '\n'.join(lines) + '\n'
    if not HEADLESS and sys.stdout is not None:
        sys.stdout.write(text)
        sys.stdout.flush()
    try:
        from ..app import paths
        with open(paths.app_dir('logs', name), 'w', encoding='utf-8') as f:
            f.write(text)
    except OSError:
        pass


def _short(path):
    try:
        return os.path.relpath(path, PACKAGE)
    except ValueError:      # another drive
        return path


def selftest():
    """--selftest: the modules import and the page's files are there. 0 when all is well, 1 otherwise."""
    import importlib
    lines, bad = [f'{APP_NAME} {VERSION} selftest  frozen={bool(getattr(sys, "frozen", False))}'], 0
    modules = ['overtime_roster.app.controller', 'overtime_roster.app.selfupdate', 'overtime_roster.window.api',
               'overtime_roster.window.host', 'overtime_roster.window.server', 'overtime_core.overlay']
    if getattr(sys, 'frozen', False) or have_pywebview():
        modules.append('webview')
    for name in modules:
        try:
            importlib.import_module(name)
            lines.append(f'ok    import {name}')
        except Exception as err:  # noqa: BLE001
            bad += 1
            lines.append(f'FAIL  import {name}: {err}')
    try:    # every tab's part (app/registry.py imports them when the controller starts)
        from ..app import registry
        lines.append(f'ok    parts {len(registry.part_classes())}, calls {len(registry.calls())}')
    except Exception as err:  # noqa: BLE001
        bad += 1
        lines.append(f'FAIL  parts: {err}')
    for path in NEEDED:
        ok = os.path.isfile(path)
        bad += not ok
        lines.append(f'{"ok  " if ok else "FAIL"}  file {_short(path)}')
    lines.append(f'info  icon {"present" if os.path.isfile(ICON) else "missing"}; WebView2 {webview2.available()}')
    try:    # the server's certificate is checked against Mozilla's list too: a PC without the newest roots (2026-11-03)
        from overtime_core import net
        ok = net.certifi_loaded() or not getattr(sys, 'frozen', False)
        bad += not ok
        lines.append(f'{"ok  " if ok else "FAIL"}  certificates: Windows' + (' + certifi' if net.certifi_loaded() else ' only'))
    except Exception as err:  # noqa: BLE001
        bad += 1
        lines.append(f'FAIL  certificates: {err}')
    try:
        _found, failed = _pack_lines(lines)
        bad += failed
    except Exception as err:  # noqa: BLE001
        bad += 1
        lines.append(f'FAIL  packs: {err}')
    lines.append('PASS' if not bad else f'FAIL ({bad})')
    _report(lines, 'selftest.txt')
    return 0 if not bad else 1


def _pack_lines(lines):
    """Selftest lines for what the exe carries: no picture pack (since beta2 the app downloads them), the verified
    default roster (its sha256 against the build record), the NHL 27 data pack (numbers and names only), the art
    packs the patch finds and those it would download, the cached ratings data pack and the eboot patch's default
    features."""
    import gzip
    import json
    from overtime_core import nhl27 as nhl27_pack, textpack, xmlpatch
    from ..app import defaultdb, packdownload, patch, paths, sources
    failed = 0
    inside = sorted(n for n in os.listdir(PACKS) if n.endswith('.zip')) if os.path.isdir(PACKS) else []
    for name in inside:
        failed += 1
        lines.append(f'FAIL  pack {name} is inside the exe: picture packs are downloaded since beta2')
    if not inside:
        lines.append('ok    no picture packs in the exe (the app downloads them)')
    for result in (defaultdb.check(), defaultdb.photos_check(PACKS)):
        if result is not None:
            ok, text = result
            failed += not ok
            lines.append(f'{"ok  " if ok else "FAIL"}  {text}')
    cache = paths.app_dir('cache')
    found = patch.art_found(cache)
    lines.append(f'info  art packs the patch finds: {", ".join(found) or "none"}')
    lines.append(f'info  picture packs to download: {", ".join(packdownload.missing_core(cache)) or "none"}')
    nhl27 = next((p for p in sources.nhl27_places(cache) if os.path.isfile(p)), None)
    lines.append(f'info  NHL 27 data pack: {nhl27 or "none"}')
    carried = os.path.join(PACKS, nhl27_pack.PACK_NAME)
    if os.path.isfile(carried):
        try:
            with gzip.open(carried, 'rt', encoding='utf-8') as f:
                problems = defaultdb.numbers_only(json.load(f), os.path.getsize(carried))
            problems += [] if nhl27_pack.load(carried) is not None else ['does not load']
        except (OSError, ValueError) as err:
            problems = [str(err)]
        failed += bool(problems)
        lines.append(f'ok    NHL 27 data pack in the exe: numbers and names only ({os.path.getsize(carried)} bytes)'
                     if not problems else f'FAIL  NHL 27 data pack in the exe: {"; ".join(problems[:3])}')
    try:        # the text layer (on by default) reads it outside overtime_roster: build.ps1 bundles client\textpack
        strings = textpack.load_pack().get('strings') or {}
        ok = bool(strings) and all(isinstance(k, str) and isinstance(v, str) for k, v in strings.items())
        lines.append(f'ok    text pack eng_us ({len(strings)} strings)' if ok else 'FAIL  text pack eng_us: no strings')
    except (OSError, ValueError, AttributeError) as err:
        ok = False
        lines.append(f'FAIL  text pack eng_us: {err}')
    failed += not ok
    ratings = os.path.join(cache, 'datapack.json.gz')
    lines.append(f'info  ratings data pack: {ratings if os.path.isfile(ratings) else "not downloaded yet"}')
    lines.append(f'info  eboot patch default: {", ".join(xmlpatch.DEFAULT)} ({len(xmlpatch.DEFAULT)})')
    return found, failed


def _value(argv, name):
    """The value after `name` in argv (None when absent)."""
    if name in argv and argv.index(name) + 1 < len(argv):
        return argv[argv.index(name) + 1]
    return None


def default_db(argv):
    """--default-db OUT --rosters F --schedule F [--game-dir D]: build the updated default roster (nhl_game.db) the
    way the patch does, from recorded NHL.com files, and write it to OUT (the game folder is only read). Prints its
    sha256 and the NHL 27 pack used: a release check that the exe's code makes the shipped default. 0 / 1."""
    import hashlib
    from ..app import patch, paths, sources, update
    out, rosters, schedule = (_value(argv, k) for k in ('--default-db', '--rosters', '--schedule'))
    if not (out and rosters and schedule):
        _report(['--default-db OUT needs --rosters FILE and --schedule FILE'], 'default-db.txt')
        return 1
    game_dir = _value(argv, '--game-dir') or paths.default_game_dir()
    try:
        g = update.gather_files(update.DEFAULT_SEASON, paths.app_dir('cache'), rosters, schedule)
        database, _rep = patch.updated_default(sources.GameData(game_dir), g)
    except Exception as err:  # noqa: BLE001
        _report([f'default roster not built: {err}'], 'default-db.txt')
        return 1
    with open(out, 'wb') as f:
        f.write(database)
    _report([f'nhl_game.db {hashlib.sha256(database).hexdigest()}  {len(database)} bytes  -> {out}',
             f'NHL 27 pack: {g.sources.get("nhl27") or "none"}'], 'default-db.txt')
    return 0


def download_kits():
    """--download-kits: download the optional kits pack from the release host into the app's cache (sha256 and size
    checked; a wrong file is deleted). 0 / 1."""
    import hashlib
    from ..app import packdownload, paths
    try:
        path = packdownload.download_kits(paths.app_dir('cache'))
    except Exception as err:  # noqa: BLE001
        _report([f'kits pack not downloaded: {err}'], 'kits.txt')
        return 1
    with open(path, 'rb') as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    _report([f'kits pack downloaded: {path} ({digest})'], 'kits.txt')
    return 0


def update_now():
    """--update: look now and, when newer, swap the exe in (no restart, no question). 0 updated, 3 up to date,
    1 refused or failed."""
    from ..app import selfupdate
    release = selfupdate.latest()
    if release is None:
        _report([f'{APP_NAME} {VERSION} is up to date ({selfupdate.release_url()}).'], 'update.txt')
        return 3
    try:
        exe = selfupdate.install(release, start=False)
    except Exception as err:  # noqa: BLE001
        _report([f'{APP_NAME} {release.text} not installed: {err}'], 'update.txt')
        return 1
    _report([f'{APP_NAME} {release.text} installed in {exe}.'], 'update.txt')
    return 0


def entry(argv=None):
    """The exe's entry: --selftest, --update, --download-kits, --default-db, or the app (`python -m overtime_roster`
    arguments)."""
    argv = sys.argv[1:] if argv is None else list(argv)
    if any(a in argv for a in ('--selftest', '--update', '--download-kits', '--default-db')):
        startup.close_splash()          # no window comes: the splash goes now
    if '--selftest' in argv:
        return selftest()
    if '--update' in argv:
        return update_now()
    if '--download-kits' in argv:
        return download_kits()
    if '--default-db' in argv:
        return default_db(argv)
    from ..__main__ import main as app
    return app(argv)
