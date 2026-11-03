import hashlib
import json
import threading
import types

import pytest

from overtime_roster.app import defaultdb, patch, setup_controller as SC

BASE = b'verified default roster'
REBUILT = b'default rebuilt from the update'


def _sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def shipped(tmp_path, monkeypatch):
    """A verified default in the exe's place (with its build record); the repository capture out of reach."""
    folder = tmp_path / 'defaults'
    folder.mkdir()
    (folder / defaultdb.DB_NAME).write_bytes(BASE)
    (folder / defaultdb.RECORD).write_text(json.dumps({'sha256': _sha(BASE), 'bytes': len(BASE)}))
    monkeypatch.setattr(defaultdb, 'SHIPPED', str(folder))
    monkeypatch.setattr(defaultdb, 'REPO', str(tmp_path / 'no-repo'))
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'home'))
    return folder


def _setup(gathered=None, season=20262027):
    ctl = types.SimpleNamespace(lock=threading.RLock(), upd_gathered=gathered, upd_season=season, upd_per32=None,
                                upd_offline=True, game=object(), host=types.SimpleNamespace(logs=[]))
    ctl.host.log = ctl.host.logs.append
    return types.SimpleNamespace(ctl=ctl)


def test_the_default_of_an_update_plays_the_real_lines(monkeypatch):
    seen = {}

    def run(*a, **k):
        seen.update(k)
        raise InterruptedError

    monkeypatch.setattr(patch, 'RosterSession', lambda *a: type('Session', (), {'db': None}))
    monkeypatch.setattr(patch.update, 'plan', lambda *a: type('Plan', (), {'summary': staticmethod(str)}))
    monkeypatch.setattr(patch.update, 'run', run)
    with pytest.raises(InterruptedError):
        patch.updated_default(type('Game', (), {'default_db': staticmethod(bytes)}), None)
    assert seen['lines'] is True


def test_embedded_needs_its_record(shipped):
    assert defaultdb.embedded() == (BASE, _sha(BASE))
    assert defaultdb.check()[0]
    (shipped / defaultdb.DB_NAME).write_bytes(b'another roster')
    assert defaultdb.embedded() == (None, None)
    ok, text = defaultdb.check()
    assert not ok and 'not the recorded' in text


def test_no_update_serves_the_embedded_bytes(shipped, monkeypatch):
    monkeypatch.setattr(patch, 'updated_default', lambda *a, **k: pytest.fail('nothing is built without an Update'))
    assert SC.SetupController._default_roster(_setup()) == BASE


def test_update_done_serves_its_cache(shipped, monkeypatch):
    built = []
    monkeypatch.setattr(patch, 'updated_default', lambda game, g, per32, log=None: built.append(g) or (REBUILT, {}))
    gathered = types.SimpleNamespace(season=20262027)
    assert SC.SetupController._default_roster(_setup(gathered)) == REBUILT and built == [gathered]
    # a later patch (another app session, no Update in it) serves the kept rebuild
    monkeypatch.setattr(patch, 'updated_default', lambda *a, **k: pytest.fail('the cache is served'))
    s = _setup()
    assert SC.SetupController._default_roster(s) == REBUILT
    assert 'last Update' in s.ctl.host.logs[-1]


def test_a_new_verified_default_drops_the_old_cache(shipped, tmp_path, monkeypatch):
    cache = str(tmp_path / 'home' / 'cache')
    defaultdb.remember(cache, REBUILT, _sha(BASE), 20262027)
    assert defaultdb.pick(cache) == (REBUILT, 'cache')
    newer = b'newer verified default'
    (shipped / defaultdb.DB_NAME).write_bytes(newer)
    (shipped / defaultdb.RECORD).write_text(json.dumps({'sha256': _sha(newer)}))
    assert defaultdb.pick(cache) == (newer, 'embedded')


def test_a_broken_cache_is_not_served(shipped, tmp_path):
    cache = tmp_path / 'home' / 'cache'
    defaultdb.remember(str(cache), REBUILT, _sha(BASE), 20262027)
    (cache / defaultdb.CACHE_DB).write_bytes(b'half written')
    assert defaultdb.pick(str(cache)) == (BASE, 'embedded')


def test_without_a_verified_default_it_is_built_fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(defaultdb, 'SHIPPED', str(tmp_path / 'none'))
    monkeypatch.setattr(defaultdb, 'REPO', str(tmp_path / 'none'))
    assert defaultdb.pick(str(tmp_path)) == (None, 'fresh')


def test_numbers_only():
    assert defaultdb.numbers_only({'players': [{'first': "Jean-Luc", 'last': "O'Neil", 'v': [80, 71.5]}],
                                   'source': {'nhl_game.db': 'ab' * 32}}) == []
    bad = defaultdb.numbers_only({'blob': 'A' * 65, 'raw': b'\x00', 'texture\n': 1, 'note': 'line\nbreak'})
    assert len(bad) == 4
    assert defaultdb.numbers_only({}, size=defaultdb.MAX_PACK + 1)
