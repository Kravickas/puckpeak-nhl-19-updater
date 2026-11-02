import os
import tempfile

import pytest

GAME_DIR = os.environ.get('OVERTIME_GAME_DIR', r'D:\PS4\NHL 19')
SAVE_DIR = os.environ.get('OVERTIME_SAVE_DIR', os.path.expandvars(
    r'%APPDATA%\shadPS4\home\1000\savedata\CUSA11126'))
RUN_DIR = None  # the whole run's own app folder and save folder (pytest_configure)


def pytest_configure(config):
    """Before any test: the app folder and the emulator's save folder point into one temp folder for the whole run
    and are never set back. A test's monkeypatch puts back this folder, not the owner's, so a background job that
    ends after its test cannot write the owner's settings, backups or saves (Legacy round 46). Tests that read the
    real saves use SAVE_DIR above, taken before this ran."""
    global RUN_DIR
    RUN_DIR = tempfile.mkdtemp(prefix='overtime-tests-')
    os.environ['OVERTIME_ROSTER_HOME'] = os.path.join(RUN_DIR, 'home')
    os.environ['OVERTIME_SAVE_DIR'] = os.path.join(RUN_DIR, 'savedata')
    # shadPS4's data folder too: with no portable `user\` beside a fake emulator a test would find the real %APPDATA%
    # one and patch it (2026-10-29: a patch file the app's record did not know)
    os.environ['APPDATA'] = os.path.join(RUN_DIR, 'appdata')


NHL_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')


def _skip_without_nhl_data():
    """The NHL.com samples in tests/data are not in git (NHL.com's data): a test that opens one skips without it."""
    try:
        return (yield)
    except FileNotFoundError as err:
        if os.path.dirname(os.path.abspath(str(err.filename or ''))) == NHL_DATA:
            pytest.skip(f'no NHL.com sample {os.path.basename(err.filename)} in tests/data')
        raise


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    return (yield from _skip_without_nhl_data())


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    return (yield from _skip_without_nhl_data())


@pytest.fixture(scope='session')
def default_roster():
    """The verified default nhl_game.db (made from the maintainer's game files, never in git): skip without it."""
    from overtime_roster.app import defaultdb
    path, _ = defaultdb.embedded_place()
    if not path:
        pytest.skip('no verified default roster (nhl_game.db) here')
    return path


@pytest.fixture(scope='session')
def game_dir():
    if not os.path.isdir(os.path.join(GAME_DIR, 'databigs')):
        pytest.skip('NHL 19 game files not found (set OVERTIME_GAME_DIR)')
    return GAME_DIR


@pytest.fixture(scope='session')
def game_db(game_dir):
    from overtime_core import gamefiles
    from overtime_core.schema import parse_schema
    raw, _ = gamefiles.default_database(game_dir)
    xml, _ = gamefiles.schema_xml(game_dir)
    return raw, parse_schema(xml)


@pytest.fixture(autouse=True)
def no_running_emulator(monkeypatch):
    """A game the maintainer has open must not stop a save in a test (saves refuse while shadPS4 runs); a test that
    wants the refusal patches it back."""
    from overtime_core import overlay
    monkeypatch.setattr(overlay, 'emulator_running', lambda: False)


@pytest.fixture(autouse=True)
def no_real_art_packs(monkeypatch):
    """The art switch is on by default: no test may pick up the owner's real packs/ (a test sets its own folder)."""
    monkeypatch.setenv('OVERTIME_ART_PACKS', 'off')
