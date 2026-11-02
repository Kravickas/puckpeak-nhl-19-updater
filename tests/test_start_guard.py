"""The window that stays blank (window/watchdog.py, startlog.py, boot.js): the log, the way out, the browser's folder."""
import os
import pathlib

import pytest

from overtime_roster.app import launch, paths
from overtime_roster.window import api as A, startlog, watchdog


@pytest.fixture
def clean(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path))
    startlog.page_up.clear()
    startlog.ready_called.clear()
    yield tmp_path
    startlog.page_up.clear()
    startlog.ready_called.clear()


class Window:
    real_url = 'http://127.0.0.1:1/index.html?again=2'

    def __init__(self, on_load=None):
        self.loaded, self.destroyed, self.on_load = [], False, on_load

    def load_url(self, url):
        self.loaded.append(url)
        if self.on_load:
            self.on_load()

    def destroy(self):
        self.destroyed = True


def test_the_log_keeps_the_last_starts(clean):
    for n in range(startlog.KEEP + 5):
        startlog.begin(f'v{n}')
        startlog.note(f'line {n}')
    text = pathlib.Path(startlog.path()).read_text(encoding='utf-8')
    assert text.count(startlog.HEAD) == startlog.KEEP
    assert 'line 24' in text and 'line 4\n' not in text


def test_a_page_that_comes_up_is_left_alone(clean):
    startlog.page_up.set()
    w = Window()
    dog = watchdog.Watchdog(w, 0.01, 0.01)
    dog.run()
    assert dog.outcome == 'ok' and not w.loaded and not w.destroyed


def test_a_page_that_never_asked_is_loaded_again_at_a_new_address(clean):
    w = Window(on_load=startlog.page_up.set)
    dog = watchdog.Watchdog(w, 0.01, 1)
    dog.run()
    assert dog.outcome == 'reloaded' and w.loaded == ['http://127.0.0.1:1/index.html?reloaded=1'] and not w.destroyed


def test_a_page_that_asked_is_not_reloaded_and_nothing_means_the_browser(clean):
    startlog.ready_called.set()
    w = Window()
    dog = watchdog.Watchdog(w, 0.01, 0.01)
    dog.run()
    assert dog.outcome == 'browser' and not w.loaded and w.destroyed
    assert 'opening the browser' in pathlib.Path(startlog.path()).read_text(encoding='utf-8')


def test_each_start_has_its_own_folder_and_dead_ones_go(clean, monkeypatch):
    base = pathlib.Path(paths.app_dir(watchdog.FOLDER))
    for name in ('111', '222', 'kept'):
        (base / name).mkdir()
    monkeypatch.setattr(watchdog, 'running', lambda pid: pid == 222)
    watchdog.sweep(str(base))
    assert sorted(p.name for p in base.iterdir()) == ['222', 'kept']
    assert watchdog.browser_folder() == str(base / str(os.getpid()))


def test_the_page_tells_the_window(clean):
    class Host:
        def open_path(self, path):
            self.opened = path
    host = Host()
    api = A.Api(None, host)
    api.page_up()
    assert startlog.page_up.is_set()
    api.log_js('hello')
    api.open_start_log()
    assert host.opened == startlog.path()
    told = []
    api.way_out = told.append
    api.open_in_browser()
    assert told == ['the player asked for it']


def test_shadps4_starts_without_our_unpacked_folder(tmp_path, monkeypatch):
    seen = {}

    def popen(_cmd, **kw):
        seen.update(kw)
    (tmp_path / 'shadPS4.exe').write_bytes(b'MZ')
    monkeypatch.setattr(launch.gamesetup, 'read_game', lambda _d: {'ok': True})
    monkeypatch.setattr(launch, 'command', lambda *a: ['x'])
    monkeypatch.setattr(launch.selfupdate.sys, '_MEIPASS', str(tmp_path / '_MEI1'), raising=False)
    monkeypatch.setenv('PATH', os.pathsep.join([str(tmp_path / '_MEI1'), r'C:\Windows']))
    launch.start(str(tmp_path / 'shadPS4.exe'), 'g', running=lambda: False, popen=popen)
    assert seen['env']['PATH'] == r'C:\Windows' and seen['env']['PYINSTALLER_RESET_ENVIRONMENT'] == '1'
