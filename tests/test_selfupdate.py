"""The exe's self-update (overtime_roster/app/selfupdate.py) against a local http fixture, and the window's start-up
choices (WebView2 gate, browser fallback, --selftest)."""
import functools
import hashlib
import json
import os
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from overtime_roster.app import selfupdate
from overtime_roster.window import main as app_main
from overtime_roster.window import webview2

NEW = b'MZ new exe ' * 1000
OLD = b'MZ old exe ' * 900


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('OVERTIME_RELEASE_URL', raising=False)
    return tmp_path / 'home'


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def release_site(tmp_path):
    """A local http server with app/latest.json, app/SHA256SUMS.txt and app/OvertimeNHL19.exe; returns
    (latest.json URL, folder) so a test can spoil a file."""
    site = tmp_path / 'site' / 'app'
    site.mkdir(parents=True)
    (site / 'OvertimeNHL19.exe').write_bytes(NEW)
    (site / 'SHA256SUMS.txt').write_text(f'{hashlib.sha256(NEW).hexdigest()}  OvertimeNHL19.exe\n')
    (site / 'latest.json').write_text(json.dumps({'version': '9.1.0', 'exe': 'OvertimeNHL19.exe', 'notes': 'Seattle'}))
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(site.parent)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{server.server_address[1]}/app/latest.json', site
    server.shutdown()
    server.server_close()


@pytest.fixture
def exe(tmp_path):
    folder = tmp_path / 'install'
    folder.mkdir()
    path = folder / 'OvertimeNHL19.exe'
    path.write_bytes(OLD)
    return str(path)


# --- reading a release ------------------------------------------------------------------------------
def test_parse_version():
    assert selfupdate.parse_version('v0.11.0') == (0, 11, 0)
    assert selfupdate.parse_version('0.2') == (0, 2, 0)
    assert selfupdate.parse_version('latest') is None
    assert selfupdate.parse_version(None) is None


def test_beta_versions_sort_before_their_release():
    beta = selfupdate.parse_version('0.1.0-beta1')
    assert str(beta) == '0.1.0-beta1' and beta != (0, 1, 0)
    assert selfupdate.parse_version('0.1.0') > beta > (0, 0, 9)
    assert beta > selfupdate.parse_version('0.1.0-alpha3') and beta < selfupdate.parse_version('0.1.0-beta2')
    assert selfupdate.parse_version('0.1.0-beta2') < selfupdate.parse_version('0.1.0-rc1')
    assert selfupdate.parse_version('0.1.0rc1') == selfupdate.parse_version('0.1.0-rc1')
    assert selfupdate.parse_version('0.1.0-gamma') is None
    pages = {}

    def fetch(url):
        return pages[url]
    url = 'https://ot.puckpeak.com/app/latest.json'
    h = 'cd' * 32
    pages['https://ot.puckpeak.com/app/SHA256SUMS.txt'] = f'{h}  OvertimeNHL19.exe'
    for current, published, offered in (('0.1.0-beta1', '0.1.0', '0.1.0'), ('0.1.0-beta1', '0.1.0-beta2', '0.1.0-beta2'),
                                        ('0.1.0-beta1', '0.1.0-beta1', None), ('0.1.0', '0.1.0-beta1', None)):
        pages[url] = json.dumps({'version': published, 'exe': 'OvertimeNHL19.exe'})
        r = selfupdate.latest(current, url, fetch, selfupdate.EXE_ASSET)
        assert (r.text if r else None) == offered, (current, published)
    assert r is None and offered is None


def test_v0_50_0_is_offered_to_every_beta_and_0_10_0():
    from overtime_roster import VERSION
    v = selfupdate.parse_version(VERSION)
    assert str(v) == '0.70.7'
    assert v > selfupdate.parse_version('0.1.0-beta4') and v > selfupdate.parse_version('0.1.0')
    assert v > selfupdate.parse_version('0.1.0-beta3') and v > selfupdate.parse_version('0.20.0') and v < selfupdate.parse_version('0.70.8')
    url = 'https://ot.puckpeak.com/app/latest.json'
    pages = {url: json.dumps({'version': VERSION, 'exe': 'OvertimeNHL19.exe'}),
             'https://ot.puckpeak.com/app/SHA256SUMS.txt': f"{'ab' * 32}  OvertimeNHL19.exe"}
    r = selfupdate.latest('0.1.0-beta4', url, pages.__getitem__, selfupdate.EXE_ASSET)
    assert r is not None and r.text == '0.70.7'
    assert selfupdate.latest('0.20.0', url, pages.__getitem__, selfupdate.EXE_ASSET).text == '0.70.7'
    assert selfupdate.latest(VERSION, url, pages.__getitem__, selfupdate.EXE_ASSET) is None


def test_digest_from_sums():
    h = 'ab' * 32
    text = f'{"cd" * 32}  OvertimeNHL19-cli.exe\n{h.upper()} *OvertimeNHL19.exe\nnonsense\n'
    assert selfupdate.digest_from_sums(text, 'OvertimeNHL19.exe') == h
    assert selfupdate.digest_from_sums(text, 'Other.exe') is None


def test_from_json_relative_and_absolute_exe():
    h = 'ab' * 32
    sums = {'https://ot.puckpeak.com/app/SHA256SUMS.txt': f'{h}  OvertimeNHL19.exe'}
    r = selfupdate.from_json({'version': '0.2.0'}, 'https://ot.puckpeak.com/app/latest.json', sums.__getitem__)
    assert r.exe_url == 'https://ot.puckpeak.com/app/OvertimeNHL19.exe' and r.digest == h and r.can_install()
    r = selfupdate.from_json({'version': '0.2.0', 'exe': 'https://cdn.example/v2/OvertimeNHL19.exe'},
                             'https://ot.puckpeak.com/app/latest.json', sums.__getitem__)
    assert r.exe_url == 'https://cdn.example/v2/OvertimeNHL19.exe' and r.digest == h


def test_from_json_disagreeing_sha256_cannot_install():
    sums = lambda url: f'{"ab" * 32}  OvertimeNHL19.exe'  # noqa: E731
    r = selfupdate.from_json({'version': '0.2.0', 'sha256': 'cd' * 32}, 'http://x/app/latest.json', sums)
    assert r.digest is None and not r.can_install()


def test_from_json_without_sums_cannot_install():
    def missing(url):
        raise OSError('404')
    r = selfupdate.from_json({'version': '0.2.0', 'sha256': 'cd' * 32}, 'http://x/app/latest.json', missing)
    assert r is not None and not r.can_install()
    assert selfupdate.from_json({'version': 'soon'}, 'http://x/', missing) is None
    assert selfupdate.from_json(['nonsense'], 'http://x/', missing) is None


def test_release_url_override(monkeypatch):
    assert selfupdate.release_url() == 'https://ot.puckpeak.com/app/latest.json'
    monkeypatch.setenv('OVERTIME_RELEASE_URL', 'http://127.0.0.1:1/app/latest.json')
    assert selfupdate.release_url() == 'http://127.0.0.1:1/app/latest.json'


def test_latest_only_when_newer(release_site):
    url, _site = release_site
    r = selfupdate.latest('0.1.0', url)
    assert r.text == '9.1.0' and r.notes == 'Seattle' and r.digest == hashlib.sha256(NEW).hexdigest()
    assert selfupdate.latest('9.1.0', url) is None
    assert selfupdate.latest('0.1.0', 'http://127.0.0.1:1/app/latest.json') is None     # offline: say nothing


def test_due_every_12_hours(home):
    t = 1.7e9
    assert selfupdate.due(now=t)
    selfupdate.mark_checked(now=t)
    assert not selfupdate.due(now=t + 11 * 3600)
    assert selfupdate.due(now=t + 12 * 3600)
    assert not selfupdate.due(now=1e12, state={'check_updates': False})
    assert json.loads((home / 'selfupdate.json').read_text())['checked'] == t


def test_every_start_looks(home):
    """Legacy 0.50.3: the look at start does not wait for the 12 hours (a release of the same day is offered)."""
    t = 1.7e9
    selfupdate.mark_checked(now=t)
    assert not selfupdate.due(now=t + 60) and selfupdate.due(now=t + 60, first=True)
    assert not selfupdate.due(first=True, state={'check_updates': False})     # Setup's switch still turns it off


# --- replacing the exe ------------------------------------------------------------------------------
def test_install_swaps_the_exe(release_site, exe):
    url, _site = release_site
    release = selfupdate.latest('0.1.0', url)
    seen = []
    assert selfupdate.install(release, exe=exe, progress=seen.append, start=False, emulator=lambda: False) == exe
    assert open(exe, 'rb').read() == NEW
    assert open(exe + '.old', 'rb').read() == OLD
    assert not os.path.exists(exe + '.new') and seen and seen[-1] == 1.0
    selfupdate.clean_leftovers(exe)
    assert not os.path.exists(exe + '.old') and open(exe, 'rb').read() == NEW


def test_install_refuses_a_bad_sha256(release_site, exe):
    url, site = release_site
    (site / 'OvertimeNHL19.exe').write_bytes(NEW + b'tampered')
    release = selfupdate.latest('0.1.0', url)
    with pytest.raises(ValueError):
        selfupdate.install(release, exe=exe, start=False, emulator=lambda: False)
    assert open(exe, 'rb').read() == OLD
    assert not os.path.exists(exe + '.new') and not os.path.exists(exe + '.old')


def test_install_refused_while_the_emulator_runs(release_site, exe):
    url, _site = release_site
    release = selfupdate.latest('0.1.0', url)
    with pytest.raises(selfupdate.Refused, match='shadPS4'):
        selfupdate.install(release, exe=exe, start=False, emulator=lambda: True)
    assert open(exe, 'rb').read() == OLD and not os.path.exists(exe + '.new')


def test_install_refused_from_source(release_site):
    url, _site = release_site
    release = selfupdate.latest('0.1.0', url)
    with pytest.raises(selfupdate.Refused):
        selfupdate.install(release, start=False, emulator=lambda: False)      # not frozen: no exe to replace


def test_swap_puts_the_old_exe_back_when_the_new_one_cannot_move(tmp_path, exe):
    with pytest.raises(OSError):
        selfupdate.swap(str(tmp_path / 'missing.new'), exe)
    assert open(exe, 'rb').read() == OLD and not os.path.exists(exe + '.old')


def test_restart_environment_is_fresh(monkeypatch):
    monkeypatch.setattr(selfupdate.sys, '_MEIPASS', r'C:\Temp\_MEI123', raising=False)
    monkeypatch.setenv('PATH', os.pathsep.join([r'C:\Temp\_MEI123', r'C:\Windows']))
    env = selfupdate.clean_environment()
    assert env['PYINSTALLER_RESET_ENVIRONMENT'] == '1' and env['PATH'] == r'C:\Windows'


class Host:
    def __init__(self):
        self.lines = []

    def log(self, *lines):
        self.lines.extend(lines)


def test_window_update_check_asks_then_swaps_and_quits(release_site, exe, monkeypatch):
    url, _site = release_site
    monkeypatch.setenv('OVERTIME_RELEASE_URL', url)
    monkeypatch.setattr(selfupdate, 'running_exe', lambda: exe)
    monkeypatch.setattr(selfupdate, 'emulator_running', lambda: False)
    started, quits, asked = [], [], []
    monkeypatch.setattr(selfupdate, 'restart', lambda path, args=(): started.append(path))
    ask = lambda title, text, ask=False: asked.append(text) or True  # noqa: E731
    host = Host()
    assert app_main.update_check(host, lambda: quits.append(1), ask=ask) == 'updated'
    assert open(exe, 'rb').read() == NEW and started == [exe] and quits == [1] and 'Seattle' in asked[0]
    assert app_main.update_check(host, lambda: quits.append(1), ask=ask) == 'off'      # 12 hours not over


def test_update_waits_for_a_question_on_screen(release_site, exe, monkeypatch):
    url, _site = release_site
    _frozen(monkeypatch, url, exe)
    ctl = Unsaved(0)
    ctl.shell.asking = {'id': 1, 'title': 'Delete this roster?'}
    ask = lambda *a, **k: pytest.fail('asked over the page question')  # noqa: E731
    assert app_main.update_check(Host(), lambda: pytest.fail('quit'), ask=ask, ctl=ctl, first=True) == 'busy'
    assert open(exe, 'rb').read() == OLD


def test_update_loop_looks_at_start_and_retries_soon(monkeypatch):
    said, sleeps = ['busy', 'busy', 'none', 'updated'], []
    firsts = []

    def check(host, quit, ctl=None, first=False):
        firsts.append(first)
        return said.pop(0)
    monkeypatch.setattr(app_main, 'update_check', check)
    monkeypatch.setattr(app_main.time, 'sleep', sleeps.append)
    monkeypatch.setattr(selfupdate, 'clean_leftovers', lambda *a: None)
    threads = []
    monkeypatch.setattr(app_main.threading, 'Thread', lambda target, **k: threads.append(target) or type(
        'T', (), {'start': lambda self: None})())
    app_main.start_update_ticks(Host(), lambda: None)
    threads[0]()
    assert firsts == [True, True, True, False]       # the start's look stays the start's until it got past the wait
    assert sleeps == [5, app_main.UPDATE_RETRY, app_main.UPDATE_RETRY, app_main.UPDATE_TICK]


def test_window_server_queue_is_roomy():
    """Legacy lab 47c: Python's queue of 5 left the window blank; both servers take 64."""
    from wsgiref.simple_server import WSGIServer

    from overtime_roster.window import server
    before = WSGIServer.request_queue_size
    try:
        app_main.roomy_server()
        assert WSGIServer.request_queue_size == server.QUEUE == 64
    finally:
        WSGIServer.request_queue_size = before
    assert server.AppServer.request_queue_size == 64


def test_window_update_check_refused_while_the_emulator_runs(release_site, exe, monkeypatch):
    url, _site = release_site
    monkeypatch.setenv('OVERTIME_RELEASE_URL', url)
    monkeypatch.setattr(selfupdate, 'running_exe', lambda: exe)
    monkeypatch.setattr(selfupdate, 'emulator_running', lambda: True)
    monkeypatch.setattr(webview2, 'message', lambda *a, **k: False)
    quits = []
    assert app_main.update_check(Host(), lambda: quits.append(1), ask=lambda *a, **k: True) == 'refused'
    assert open(exe, 'rb').read() == OLD and not quits


def test_window_update_check_from_source_only_tells(release_site, monkeypatch):
    url, _site = release_site
    monkeypatch.setenv('OVERTIME_RELEASE_URL', url)
    host = Host()
    assert app_main.update_check(host, lambda: None, ask=lambda *a, **k: pytest.fail('asked')) == 'told'
    assert '9.1.0' in host.lines[0]


def test_update_now_cli(release_site, exe, monkeypatch, home):
    url, site = release_site
    monkeypatch.setenv('OVERTIME_RELEASE_URL', url)
    monkeypatch.setattr(selfupdate, 'running_exe', lambda: exe)
    monkeypatch.setattr(selfupdate, 'emulator_running', lambda: False)
    (site / 'latest.json').write_text(json.dumps({'version': '0.0.9'}))
    assert app_main.entry(['--update']) == 3
    (site / 'latest.json').write_text(json.dumps({'version': '9.1.0'}))
    assert app_main.entry(['--update']) == 0 and open(exe, 'rb').read() == NEW
    assert 'installed' in (home / 'logs' / 'update.txt').read_text()


# --- the window's start-up choices --------------------------------------------------------------------
def test_selftest_passes_from_source(home, default_roster):
    assert app_main.entry(['--selftest']) == 0
    assert (home / 'logs' / 'selftest.txt').read_text().rstrip().endswith('PASS')


def test_selftest_fails_when_a_web_file_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(app_main, 'NEEDED', app_main.NEEDED + [str(tmp_path / 'gone.js')])
    assert app_main.selftest() == 1


def test_no_webview2_falls_back_to_the_browser(monkeypatch, tmp_path):
    monkeypatch.setenv('OVERTIME_NO_WEBVIEW2', '1')
    assert not webview2.available()
    monkeypatch.setattr(app_main, 'have_pywebview', lambda: True)
    monkeypatch.setattr(app_main, 'run_window', lambda *a, **k: pytest.fail('window without WebView2'))
    used = []
    monkeypatch.setattr(app_main, 'run_browser', lambda host, api, port, open_browser, quit=None: used.append(port) or 0)
    assert app_main.main(port=4321, game_dir=str(tmp_path / 'no-game'), save_dir=str(tmp_path / 'no-saves')) == 0
    assert used == [4321]


def test_broken_window_falls_back_to_the_browser(monkeypatch, tmp_path):
    monkeypatch.setattr(app_main, 'have_pywebview', lambda: True)
    monkeypatch.setattr(webview2, 'available', lambda: True)

    def broken(*a, **k):
        raise RuntimeError('WebView2 failed to initialise')
    monkeypatch.setattr(app_main, 'run_window', broken)
    used = []
    monkeypatch.setattr(app_main, 'run_browser', lambda host, api, port, open_browser, quit=None: used.append(1) or 0)
    assert app_main.main(game_dir=str(tmp_path / 'no-game'), save_dir=str(tmp_path / 'no-saves')) == 0
    assert used == [1]


def test_headless_browser_mode_stops_on_ok(monkeypatch, tmp_path):
    """The windowed exe without WebView2: the server runs until the box is closed."""
    import urllib.request
    host, _c, api = app_main.build(str(tmp_path / 'no-game'), str(tmp_path / 'no-saves'))
    monkeypatch.setattr(app_main, 'HEADLESS', True)
    seen = {}

    def box(title, text, ask=False, info=False):
        url = text.split('\n')[1]
        seen['page'] = urllib.request.urlopen(url, timeout=5).status
        return False
    monkeypatch.setattr(webview2, 'message', box)
    assert app_main.run_browser(host, api, open_browser=False, ready=lambda s: seen.setdefault('server', s)) == 0
    assert seen['page'] == 200


# --- review fixes: the console exe's own file, busy jobs, shadPS4 during the download, sizes, the fallback's quit ---
def test_cli_exe_takes_its_own_file(release_site, tmp_path, monkeypatch):
    url, site = release_site
    assert selfupdate.asset_for(r'C:\x\OvertimeNHL19-cli.exe') == 'OvertimeNHL19-cli.exe'
    assert selfupdate.asset_for(r'C:\x\OvertimeNHL19.exe') == 'OvertimeNHL19.exe'
    cli_new = b'MZ new cli ' * 500
    (site / 'OvertimeNHL19-cli.exe').write_bytes(cli_new)
    (site / 'SHA256SUMS.txt').write_text(f'{hashlib.sha256(NEW).hexdigest()}  OvertimeNHL19.exe\n'
                                         f'{hashlib.sha256(cli_new).hexdigest()}  OvertimeNHL19-cli.exe\n')
    (site / 'latest.json').write_text(json.dumps({'version': '9.1.0', 'size': len(NEW),
                                                  'sha256': hashlib.sha256(NEW).hexdigest()}))
    cli = tmp_path / 'OvertimeNHL19-cli.exe'
    cli.write_bytes(OLD)
    monkeypatch.setattr(selfupdate, 'running_exe', lambda: str(cli))
    release = selfupdate.latest('0.1.0', url)          # the running exe's file by default
    assert release.asset == 'OvertimeNHL19-cli.exe' and release.exe_url.endswith('/OvertimeNHL19-cli.exe')
    assert release.size == 0 and release.digest == hashlib.sha256(cli_new).hexdigest()
    selfupdate.install(release, exe=str(cli), start=False, emulator=lambda: False)
    assert cli.read_bytes() == cli_new


def test_window_file_never_replaces_the_cli_exe(release_site, tmp_path):
    url, _site = release_site
    cli = tmp_path / 'OvertimeNHL19-cli.exe'
    cli.write_bytes(OLD)
    release = selfupdate.latest('0.1.0', url, asset='OvertimeNHL19.exe')
    with pytest.raises(selfupdate.Refused, match='OvertimeNHL19-cli.exe'):
        selfupdate.install(release, exe=str(cli), start=False, emulator=lambda: False)
    assert cli.read_bytes() == OLD and not os.path.exists(str(cli) + '.new')


def test_cli_exe_without_its_file_cannot_install(release_site):
    url, _site = release_site          # SHA256SUMS lists only the window exe
    release = selfupdate.latest('0.1.0', url, asset='OvertimeNHL19-cli.exe')
    assert release is not None and not release.can_install()


def test_emulator_started_during_the_download(release_site, exe):
    url, _site = release_site
    release = selfupdate.latest('0.1.0', url)
    answers = iter([False, True])
    with pytest.raises(selfupdate.Refused, match='shadPS4'):
        selfupdate.install(release, exe=exe, start=False, emulator=lambda: next(answers))
    assert open(exe, 'rb').read() == OLD
    assert not os.path.exists(exe + '.new') and not os.path.exists(exe + '.old')


def test_download_size_must_match_latest_json(release_site, exe):
    url, site = release_site
    (site / 'latest.json').write_text(json.dumps({'version': '9.1.0', 'size': len(NEW) - 1}))
    release = selfupdate.latest('0.1.0', url)
    with pytest.raises(ValueError):
        selfupdate.install(release, exe=exe, start=False, emulator=lambda: False)
    assert open(exe, 'rb').read() == OLD and not os.path.exists(exe + '.new')


def test_download_stops_at_the_limit(release_site, exe, monkeypatch):
    url, _site = release_site
    release = selfupdate.latest('0.1.0', url)
    release.size = 0
    monkeypatch.setattr(selfupdate, 'MAX_BYTES', 1000)
    with pytest.raises(ValueError):
        selfupdate.install(release, exe=exe, start=False, emulator=lambda: False)
    assert open(exe, 'rb').read() == OLD and not os.path.exists(exe + '.new')


class Ctl:
    def __init__(self, busy=None):
        self.lock = threading.RLock()
        self.busy = busy
        self.said = []

    def say(self, text, tone='info', progress=None):
        self.said.append(text)


def _frozen(monkeypatch, url, exe):
    monkeypatch.setenv('OVERTIME_RELEASE_URL', url)
    monkeypatch.setattr(selfupdate, 'running_exe', lambda: exe)
    monkeypatch.setattr(selfupdate, 'emulator_running', lambda: False)
    monkeypatch.setattr(webview2, 'message', lambda *a, **k: False)


def test_update_waits_for_a_running_job(release_site, exe, monkeypatch):
    url, _site = release_site
    _frozen(monkeypatch, url, exe)
    ctl = Ctl('Saving...')
    ask = lambda *a, **k: pytest.fail('asked while a job runs')  # noqa: E731
    assert app_main.update_check(Host(), lambda: pytest.fail('quit'), ask=ask, ctl=ctl) == 'busy'
    assert selfupdate.due() and open(exe, 'rb').read() == OLD      # not marked: asked again at the next tick


def test_job_started_while_the_box_was_open(release_site, exe, monkeypatch):
    url, _site = release_site
    _frozen(monkeypatch, url, exe)
    ctl = Ctl()

    def ask(*a, **k):
        ctl.busy = 'Patching...'           # the player clicked Patch before answering
        return True
    assert app_main.update_check(Host(), lambda: pytest.fail('quit'), ask=ask, ctl=ctl) == 'busy'
    assert ctl.busy == 'Patching...' and open(exe, 'rb').read() == OLD and selfupdate.due()


def test_update_holds_the_busy_flag_until_quit(release_site, exe, monkeypatch):
    url, _site = release_site
    _frozen(monkeypatch, url, exe)
    monkeypatch.setattr(selfupdate, 'restart', lambda path, args=(): None)
    ctl, flags = Ctl(), []
    assert app_main.update_check(Host(), lambda: flags.append(ctl.busy), ask=lambda *a, **k: True, ctl=ctl) == 'updated'
    assert flags and flags[0].startswith('Updating') and open(exe, 'rb').read() == NEW


def test_failed_update_gives_the_busy_flag_back(release_site, exe, monkeypatch):
    url, site = release_site
    _frozen(monkeypatch, url, exe)
    (site / 'OvertimeNHL19.exe').write_bytes(NEW + b'tampered')
    ctl = Ctl()
    assert app_main.update_check(Host(), lambda: pytest.fail('quit'), ask=lambda *a, **k: True, ctl=ctl) == 'failed'
    assert ctl.busy is None and open(exe, 'rb').read() == OLD


def test_fallback_browser_takes_over_the_quit(monkeypatch, tmp_path):
    """A window that failed to start must not be the one an accepted update closes."""
    monkeypatch.setattr(app_main.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(app_main, 'have_pywebview', lambda: True)
    monkeypatch.setattr(webview2, 'available', lambda: True)
    ticks = []
    monkeypatch.setattr(app_main, 'start_update_ticks', lambda host, quit, ctl=None: ticks.append((quit, ctl)))
    dead_window = []

    def broken(host, api, quit=None, ctl=None):
        quit.fn = lambda: dead_window.append(1)
        raise RuntimeError('WebView2 failed to initialise')
    monkeypatch.setattr(app_main, 'run_window', broken)
    monkeypatch.setattr(app_main, 'HEADLESS', True)
    monkeypatch.setattr(webview2, 'message', lambda *a, **k: False)
    assert app_main.main(open_browser=False, game_dir=str(tmp_path / 'g'), save_dir=str(tmp_path / 's')) == 0
    (quit, ctl), = ticks                   # one update thread, bound to the controller
    assert ctl is not None and quit.fn is not None
    monkeypatch.setattr(app_main.os, '_exit', lambda code: dead_window.append(('exit', code)))
    quit()
    assert dead_window == [('exit', 0)]


class Unsaved(Ctl):
    """A Controller with `n` unsaved edits and a shell that records the unsaved question."""

    def __init__(self, n):
        super().__init__()
        outer = self
        self.asked = []

        class Save:
            def unsaved(self):
                return outer.n

        class Shell:
            def ask_unsaved(self, what, go=None):
                outer.asked.append((what, go))
                return {'asked': 1}
        self.n, self.parts, self.shell = n, {'save': Save()}, Shell()


def test_update_waits_for_unsaved_edits(release_site, exe, monkeypatch):
    url, _site = release_site
    _frozen(monkeypatch, url, exe)
    ctl = Unsaved(2)
    ask = lambda *a, **k: pytest.fail('asked with unsaved edits')  # noqa: E731
    assert app_main.update_check(Host(), lambda: pytest.fail('quit'), ask=ask, ctl=ctl) == 'unsaved'
    assert selfupdate.due() and open(exe, 'rb').read() == OLD      # Setup offers it; the next tick looks again


def test_closing_the_window_asks_about_unsaved_edits():
    closed = []
    ctl = Unsaved(0)
    guard = app_main.closing_guard(ctl, lambda: closed.append(1))
    assert guard() is True and ctl.asked == []                     # nothing unsaved: it closes
    ctl.n = 3
    assert guard() is False                                        # the page asks; the window stays
    (what, go), = ctl.asked
    assert what == 'close the program'
    go()                                                           # Save first (saved) or Lose them
    deadline = time.time() + 5
    while not closed and time.time() < deadline:
        time.sleep(0.01)
    assert closed == [1] and guard() is True                       # destroy's own closing event goes through
    assert app_main.closing_guard(None, lambda: None)() is True


# --- what the exe carries, the kits download and the default roster check (2026-10-20) ---------------------------
def test_selftest_checks_the_packs_inside(monkeypatch, tmp_path, home, default_roster):
    """Since beta2 the exe carries no picture pack (the app downloads them): one inside fails."""
    from overtime_core import art, xmlpatch
    inside, art_dir = tmp_path / 'packs', tmp_path / 'art'
    inside.mkdir()
    art_dir.mkdir()
    art.write_pack(str(art_dir / 'looks.zip'), 'looks', {'nhl/a.gnf': b'GNF ' + b'.' * 60})
    monkeypatch.setattr(app_main, 'PACKS', str(inside))
    monkeypatch.setenv('OVERTIME_ART_PACKS', str(art_dir))
    assert app_main.selftest() == 0
    text = (home / 'logs' / 'selftest.txt').read_text()
    assert 'ok    no picture packs in the exe' in text and 'art packs the patch finds: looks.zip' in text
    assert 'info  picture packs to download: none' in text
    assert f'eboot patch default: {", ".join(xmlpatch.DEFAULT)} ({len(xmlpatch.DEFAULT)})' in text
    art.write_pack(str(inside / 'looks.zip'), 'looks', {'nhl/a.gnf': b'GNF ' + b'.' * 60})
    assert app_main.selftest() == 1
    assert 'FAIL  pack looks.zip is inside the exe' in (home / 'logs' / 'selftest.txt').read_text()


def test_selftest_checks_the_text_pack(monkeypatch, tmp_path, home, default_roster):
    """The text layer (on by default) reads client/textpack, outside overtime_roster: a missing pack fails."""
    from overtime_core import textpack
    assert app_main.selftest() == 0
    assert 'ok    text pack eng_us (' in (home / 'logs' / 'selftest.txt').read_text()
    monkeypatch.setattr(textpack, 'PACK_DIR', str(tmp_path / 'gone'))
    assert app_main.selftest() == 1
    assert 'FAIL  text pack eng_us: ' in (home / 'logs' / 'selftest.txt').read_text()
    (tmp_path / 'gone').mkdir()
    (tmp_path / 'gone' / 'eng_us.json').write_text('{"strings": {}}')
    assert app_main.selftest() == 1
    assert 'FAIL  text pack eng_us: no strings' in (home / 'logs' / 'selftest.txt').read_text()


def test_build_bundles_the_text_pack():
    build = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'packaging', 'build.ps1'),
                 encoding='utf-8').read()
    assert '"$textpack;client\\textpack"' in build


def test_selftest_checks_the_default_roster_and_the_nhl27_pack(monkeypatch, tmp_path, home):
    import gzip
    from overtime_roster.app import defaultdb
    inside, defaults = tmp_path / 'packs', tmp_path / 'defaults'
    inside.mkdir()
    defaults.mkdir()
    monkeypatch.setattr(app_main, 'PACKS', str(inside))
    monkeypatch.setattr(defaultdb, 'SHIPPED', str(defaults))
    monkeypatch.setattr(defaultdb, 'REPO', str(tmp_path / 'no-repo'))
    from overtime_core import art
    (defaults / 'nhl_game.db').write_bytes(b'roster')
    photos = art.write_pack(str(tmp_path / 'photos.zip'), 'photos', {art.PORTRAIT.format(20641): b'GNF ' + b'.' * 60})
    record = {'sha256': hashlib.sha256(b'roster').hexdigest(), 'photos': {'sha256': photos, 'portraits': 1}}
    (defaults / 'default.json').write_text(json.dumps(record))
    assert app_main.selftest() == 0
    text = (home / 'logs' / 'selftest.txt').read_text()
    assert 'default roster' in text
    assert 'photos.zip ' + photos[:8] + ' is published with the default roster (1 portraits)' in text
    # photos.zip is downloaded with the default roster: inside the exe, or not in the record -> FAIL
    (tmp_path / 'photos.zip').replace(inside / 'photos.zip')
    assert app_main.selftest() == 1
    assert 'photos.zip is inside the exe' in (home / 'logs' / 'selftest.txt').read_text()
    (inside / 'photos.zip').unlink()
    (defaults / 'default.json').write_text(json.dumps({'sha256': record['sha256']}))
    assert app_main.selftest() == 1
    assert 'names no photos.zip' in (home / 'logs' / 'selftest.txt').read_text()
    (defaults / 'default.json').write_text(json.dumps(record))
    assert app_main.selftest() == 0
    (defaults / 'nhl_game.db').write_bytes(b'a variant')
    assert app_main.selftest() == 1
    assert 'is not the recorded' in (home / 'logs' / 'selftest.txt').read_text()
    (defaults / 'nhl_game.db').write_bytes(b'roster')
    with gzip.open(inside / 'nhl27.json.gz', 'wt', encoding='utf-8') as f:
        json.dump({'format': 1, 'players': [{'first': 'Leo', 'blob': 'x' * 500}]}, f)
    assert app_main.selftest() == 1
    assert 'FAIL  NHL 27 data pack in the exe' in (home / 'logs' / 'selftest.txt').read_text()


def _kits_release(root, data, sha=None):
    (root / 'packs').mkdir(parents=True, exist_ok=True)
    (root / 'packs' / 'kits.zip').write_bytes(data)
    real = hashlib.sha256(data).hexdigest()
    (root / 'SHA256SUMS.txt').write_text(f'{sha or real}  packs/kits.zip\n')
    (root / 'latest.json').write_text(json.dumps({'version': '0.9.0', 'packs': {'kits.zip': {
        'file': 'packs/kits.zip', 'size': len(data)}}}))
    return (root / 'latest.json').as_uri()


def test_download_kits_switch(monkeypatch, tmp_path, home):
    from overtime_core import art
    kits = tmp_path / 'made.zip'
    art.write_pack(str(kits), 'kits', {'nhl/k.gnf': b'GNF ' + b'K' * 60})
    data = kits.read_bytes()
    monkeypatch.setenv('OVERTIME_RELEASE_URL', _kits_release(tmp_path / 'good' / 'app', data))
    assert app_main.entry(['--download-kits']) == 0
    assert (home / 'cache' / 'kits.zip').read_bytes() == data
    assert 'kits pack downloaded' in (home / 'logs' / 'kits.txt').read_text()


def test_download_kits_refuses_a_bad_sha256(monkeypatch, tmp_path, home):
    from overtime_core import art
    kits = tmp_path / 'made.zip'
    art.write_pack(str(kits), 'kits', {'nhl/k.gnf': b'GNF ' + b'K' * 60})
    monkeypatch.setenv('OVERTIME_RELEASE_URL', _kits_release(tmp_path / 'bad' / 'app', kits.read_bytes(), '0' * 64))
    assert app_main.entry(['--download-kits']) == 1
    assert not (home / 'cache' / 'kits.zip').exists() and not (home / 'cache' / 'kits.zip.part').exists()
    assert 'not downloaded' in (home / 'logs' / 'kits.txt').read_text()


def test_default_db_switch_needs_its_files(home):
    assert app_main.entry(['--default-db', 'x.db']) == 1
    assert 'needs --rosters' in (home / 'logs' / 'default-db.txt').read_text()


def test_start_offer_is_the_apps_own_question_with_progress(release_site, exe, monkeypatch):
    url, _site = release_site
    _frozen(monkeypatch, url, exe)
    ctl = Unsaved(0)
    offered = []
    ctl.changed = lambda *a: None
    ctl.setup = type('Setup', (), {'skipped': '', 'newer': None,
                                   '_ask_newer': lambda self, release: offered.append(release.text)})()
    monkeypatch.setattr(webview2, 'message', lambda *a, **k: pytest.fail('a Windows box over the app'))
    assert app_main.update_check(Host(), lambda: pytest.fail('quit'), ctl=ctl, first=True) == 'asked'
    assert len(offered) == 1
    assert open(exe, 'rb').read() == OLD                                # nothing swapped until Update now
    selfupdate.mark_checked(now=0)
    ctl.setup.skipped = offered[0]
    assert app_main.update_check(Host(), lambda: pytest.fail('quit'), ctl=ctl, first=True) == 'declined'
    assert len(offered) == 1                                            # a skipped version is not offered again


def test_signed_exe_only_takes_an_update_of_the_same_publisher(release_site, exe, monkeypatch):
    url, _site = release_site
    _frozen(monkeypatch, url, exe)
    monkeypatch.setattr(selfupdate, 'restart', lambda path, args=(): None)
    release = selfupdate.latest()
    table = {exe: 'CN=Puck Peak'}
    monkeypatch.setattr(selfupdate, 'signer', lambda path: table.get(path) or table.get('new'))
    table['new'] = 'CN=Somebody Else'
    with pytest.raises(ValueError, match='same publisher'):
        selfupdate.install(release)
    assert open(exe, 'rb').read() == OLD and not os.path.exists(exe + '.new')
    table['new'] = 'CN=Puck Peak'
    selfupdate.install(release)
    assert open(exe, 'rb').read() == NEW


def test_unsigned_exe_has_nothing_to_compare(tmp_path):
    exe = tmp_path / 'a.exe'
    exe.write_bytes(b'x')
    selfupdate.check_signature(str(exe), str(exe), who=lambda path: None)           # unsigned: the sha256 is the check
    with pytest.raises(ValueError):
        selfupdate.check_signature('new', 'old', who=lambda path: 'CN=A' if path == 'old' else None)


@pytest.mark.skipif(os.name != 'nt', reason='Authenticode is Windows')
def test_signer_reads_windows_signatures(tmp_path):
    system = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'WindowsPowerShell', 'v1.0',
                          'powershell.exe')
    assert 'Microsoft' in (selfupdate.signer(system) or '')
    plain = tmp_path / 'plain.exe'
    plain.write_bytes(b'MZ' + bytes(100))
    assert selfupdate.signer(str(plain)) is None and selfupdate.signer(str(tmp_path / 'none.exe')) is None
