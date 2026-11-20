"""The Help bar's status line is never held up by a job: its snapshot takes no lock, the quick pusher sends it on its
own while the controller's lock is held, and every message lists it first."""
import json
import queue
import time

import pytest

from overtime_roster.app import jobs
from overtime_roster.window import main as app_main


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'home'))
    host, c, api = app_main.build(str(tmp_path / 'no-game'), str(tmp_path / 'no-saves'), reopen=False)
    return host, c, api


def test_status_arrives_while_the_lock_is_held(app):
    host, c, api = app
    got = queue.Queue()
    host.add_transport(lambda text: got.put((time.monotonic(), json.loads(text))))
    api.ready()
    time.sleep(0.15)
    while not got.empty():
        got.get_nowait()
    with c.lock:                        # a job holds the lock (a save, the update)
        c.changed('roster', 'rail')     # slices whose snapshots wait for the lock
        start = time.monotonic()
        c.say('Saving the roster...', 'info', 0.5)
        when, message = got.get(timeout=2)
        assert when - start < 0.1
        assert message['slices']['status'] == {'text': 'Saving the roster...', 'tone': 'info', 'progress': 0.5,
                                               'busy': False}
        assert set(message['slices']) <= {'status', 'question'}
    when, message = got.get(timeout=2)  # the rest once the lock is free
    assert {'roster', 'rail'} <= set(message['slices']) and 'status' not in message['slices']


def test_status_comes_first(app):
    host, c, api = app
    first = api.ready()
    assert list(first['slices'])[0] == 'status'
    c.changed('roster', 'app', 'rail')
    c.say('Checking...')
    message = host.take()
    assert list(message['slices'])[0] == 'status' and {'roster', 'app', 'rail'} <= set(message['slices'])
    assert host.take() is None


def test_quick_and_slices_lanes(app):
    host, c, _api = app
    host.first()                        # what the controller marked while it started
    c.changed('roster')
    c.say('One')
    host.log('a line')
    host.send('unsaved', {'answer': 'go'})
    quick = host.take('quick')
    assert set(quick['slices']) == {'status'} and quick['log']['lines'][0].endswith('a line')
    assert quick['events'] == [['unsaved', {'answer': 'go'}]]
    rest = host.take('slices')
    assert set(rest['slices']) == {'roster'} and 'log' not in rest and 'events' not in rest
    assert host.take('quick') is None and host.take('slices') is None


def test_a_failing_slice_never_stops_the_pushes(app, monkeypatch):
    host, c, api = app
    logged = []
    monkeypatch.setattr(jobs, 'log_unexpected', lambda err: logged.append(err) or 'logged')
    host.register('boom', lambda: 1 / 0)
    got = queue.Queue()
    host.add_transport(lambda text: got.put(json.loads(text)))
    first = api.ready()
    assert 'boom' not in first['slices'] and 'rail' in first['slices']    # left out: the page keeps what it had

    def arrives(name):
        end = time.monotonic() + 2
        while time.monotonic() < end:
            try:
                message = got.get(timeout=0.2)
            except queue.Empty:
                continue
            if name in message.get('slices', {}):
                return message
        return None
    c.changed('boom', 'rail')
    message = arrives('rail')
    assert message and 'boom' not in message['slices']
    real, calls = host.take, []

    def take(which='all'):
        calls.append(which)
        if len(calls) == 1:
            raise RuntimeError('a bug while taking')
        return real(which)
    monkeypatch.setattr(host, 'take', take)
    c.changed('rail')
    assert arrives('rail') is None or calls          # the first take failed (logged) ...
    c.changed('rail')
    assert arrives('rail') is not None               # ... and the pushes went on
    assert any(isinstance(e, ZeroDivisionError) for e in logged)
    assert any(isinstance(e, RuntimeError) for e in logged)


def test_every_message_is_numbered_newer_than_the_one_before(app):
    """The page drops a slice older than the one it has (store.js): ready's answer and the pushes run at once, so each
    message carries seq, taken as its slices are taken."""
    host, c, _api = app
    first = host.first()
    c.changed('roster')
    c.say('One')
    quick, rest = host.take('quick'), host.take('slices')
    assert first['seq'] < quick['seq'] < rest['seq']
    c.changed('rail')
    assert host.take()['seq'] == rest['seq'] + 1


def test_ready_twice_at_once_starts_one_pair_of_pushers(app):
    import threading
    host, _c, _api = app
    before = set(threading.enumerate())     # pushers of the other tests' hosts live on (daemon threads)
    go = threading.Barrier(8)

    def start():
        go.wait()
        host.start_pushing()
    ts = [threading.Thread(target=start) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    names = [t.name for t in set(threading.enumerate()) - before]
    assert names.count('push') == 1 and names.count('push-quick') == 1
