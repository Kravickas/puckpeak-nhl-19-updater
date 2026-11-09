"""The Multiplayer tab's controller (docs/plans/m3-multiplayer-tab.md): who the player is, the lobby calls against a fake
service, the poller's state machine, and the game start with fakes for the hook, shadPS4 and the key presses."""
import json
import os
import threading
import types

import pytest

from overtime_core import overlay, rules as RU, xmlpatch
from overtime_roster.app import gamesetup, keypress, launch, lobby_client as LC, multiplayer_ctl as MC, shadnet


class Host:
    def __init__(self):
        self.lines = []

    def log(self, msg):
        self.lines.append(msg)


class FakeCtl:
    def __init__(self, tmp_path, host='ot.puckpeak.com'):
        self.prefs = {}
        self.saved = []
        self.pushed = []
        self.host = Host()
        self.game_dir = str(tmp_path / 'game')
        self.game = types.SimpleNamespace(ok=True)
        self.lock = threading.RLock()
        self.session = None
        self.setup = types.SimpleNamespace(server={'host': host}, known_emulator=lambda: str(tmp_path / 'emu' / 'shadPS4.exe'),
                                           ctl=self, _xml=lambda: xmlpatch.build(host, 'https://91.98.195.150/'))

    def remember(self, **kv):
        self.prefs.update(kv)
        self.saved.append(kv)

    def changed(self, *names):
        self.pushed += names


class FakeService:
    """The lobby API as lobby_client calls it: one lobby, two players, scripted answers."""

    def __init__(self):
        self.calls = []
        self.lobby = None
        self.announced = []
        self.you = 0
        self.recipe = None
        self.fail = None            # an exception the next call raises
        self.public = [{'code': 'AB123', 'host': 'Bo', 'players': 1, 'age': 130}]

    def _go(self, name, *args):
        self.calls.append((name, *args))
        if self.fail:
            err, self.fail = self.fail, None
            raise err

    def view(self, **kw):
        lobby = {'code': 'K7M2Q', 'public': False, 'state': 'open', 'waiting': None, 'rules': dict(RU.DEFAULTS),
                 'players': [{'name': 'iksperial', 'ready': False, 'launch': False, 'roster': 'unknown', 'stage': 'lobby'}],
                 **kw}
        return lobby

    def create(self, name, ext, public=False, roster_crc=None):
        self._go('create', name, ext, public)
        self.lobby = self.view(public=public)
        self.you = 0
        return {'token': 'secret-token', 'you': 0, 'lobby': self.lobby}

    def join(self, code, name, ext, roster_crc=None):
        self._go('join', code, name, ext)
        self.lobby = self.view()
        self.lobby['players'].insert(0, {'name': 'Bo', 'ready': False, 'launch': False, 'roster': 'unknown', 'stage': 'lobby'})
        self.you = 1
        return {'token': 'secret-token', 'you': 1, 'lobby': self.lobby}

    def ready(self, code, token, value=True, patch=None, game=None, caps=None):
        self.caps = caps
        if caps and not value and patch is None and game is None:     # the caps announcement after create/join
            self.announced = (self.announced or []) + [('ready', code, token, value, tuple(caps))]
            return {**self.lobby, 'you': self.you}
        self.patch, self.game = patch, game
        self._go('ready', code, token, value)
        return {**self.lobby, 'you': 0}

    def match(self, code, token, recipe):
        self.announced = (self.announced or []) + [('match', code, token)]
        self.recipe = recipe
        return {**self.lobby, 'you': self.you}

    def mode(self, code, token, mode):
        self._go('mode', code, token, mode)
        self.lobby = {**self.lobby, 'mode': mode, 'rules': RU.defaults(mode)}
        for p in self.lobby['players']:
            p['ready'] = False
        return {**self.lobby, 'you': 0}

    def settings(self, code, token, rules):
        self._go('settings', code, token, rules)
        self.lobby = {**self.lobby, 'rules': {**RU.defaults(self.lobby.get('mode') or 'versus'), **(self.lobby.get('rules') or {}), **rules}}
        for p in self.lobby['players']:
            p['ready'] = False
        return {**self.lobby, 'you': 0}

    def say(self, code, token, text):
        self._go('say', code, token, text)
        chat = (self.lobby.get('chat') or []) + [{'n': len(self.lobby.get('chat') or []) + 1, 'who': 0, 'name': 'iksperial',
                                                  'text': text}]
        self.lobby = {**self.lobby, 'chat': chat}
        return {**self.lobby, 'you': 0}

    def state(self, code, token):
        self._go('state', code, token)
        return {**self.lobby, 'you': 0}

    def leave(self, code, token):
        self._go('leave', code, token)
        return {}

    def lobbies(self):
        self._go('lobbies')
        return {'lobbies': self.public}


@pytest.fixture
def mp(tmp_path):
    ctl = FakeCtl(tmp_path)
    part = MC.MultiplayerCtl(ctl)
    part.threads = False
    part.hud_ok = lambda: False         # tests never draw over a real screen
    part.service = FakeService()
    part.make_client = lambda url: part.service
    part.sleep = lambda s: None
    part.sn_login = _sn_down                # tests never reach the real ShadNet
    part.sn_register = _sn_down
    return part


def _sn_down(*a, **k):
    raise shadnet.ShadNetDown('ShadNet did not answer.')


def log_in(tmp_path, monkeypatch, account=16349, npid='iksperial'):
    user = tmp_path / 'user'
    (user / 'log').mkdir(parents=True, exist_ok=True)
    write_users(user, npid)
    os.utime(user / 'users.json', (1000, 1000))
    (user / 'log' / 'shad_log.txt').write_bytes(
        f"[Lib.Np] ConnectUser: user_id=1000 signed in npid='{npid}' accountId={account}\n".encode())
    monkeypatch.setattr(gamesetup, 'emu_user_dir', lambda emu: str(user))
    return user


def write_users(user, npid, password='pw'):
    rows = [{'player_index': i, 'user_id': 999 + i, 'user_name': 'shadPS4', 'shadnet_enabled': i == 1 and bool(npid),
             'shadnet_npid': npid if i == 1 else '', 'shadnet_password': password if i == 1 else '',
             'shadnet_token': 'old' if i == 1 else '', 'shadnet_email': ''} for i in (1, 2)]
    (user / 'users.json').write_text(json.dumps({'Users': {'commit_hash': 'x', 'user': rows}}), encoding='utf-8')


def good_checks(part, tone='good'):
    part.look = lambda: part.__dict__.update(checks=[{'key': 'patch', 'label': 'Patch', 'tone': tone,
                                                       'text': 'on and intact' if tone == 'good' else 'not patched',
                                                       'go': None}]) or part.checks


# --- who I am -----------------------------------------------------------------------------------------------------
def test_the_id_comes_from_the_log_and_beats_a_typed_one(mp, tmp_path, monkeypatch):
    log_in(tmp_path, monkeypatch)
    mp._checks = lambda emu: []
    assert mp.ext() == (None, '') and mp.view()['you']['ext'] is None          # not looked yet
    mp.look()
    v = mp.view()['you']
    assert (v['ext'], v['ext_from'], v['name'], v['name_from']) == (16349, 'log', 'iksperial', 'game')
    assert v['ext_why'] == ''                                                  # the id is known: nothing to explain
    assert mp.set_ext('777') == {'ok': True}                                   # live 2026-11-07: typed ids got shared
    assert mp.view()['you']['ext'] == 16349 and mp.view()['you']['ext_from'] == 'log'
    assert mp.ctl.prefs['multiplayer']['ext'] == 777
    mp.logged = dict(mp.logged, account=None, state='signed_in')               # an old build: no account id in the log
    assert mp.ext() == (777, 'typed')
    mp.logged['state'] = 'stale'                                               # the account changed since: nothing counts
    assert mp.ext() == (None, '')
    mp.look()
    assert mp.set_ext('') == {'ok': True} and mp.view()['you']['ext_from'] == 'log'


def test_signing_in_writes_the_own_account_and_a_stale_log_does_not_count(mp, tmp_path, monkeypatch):
    user = log_in(tmp_path, monkeypatch)
    mp._checks = lambda emu: []
    monkeypatch.setattr(overlay, 'emulator_running', lambda: False)
    mp.look()
    mp.set_ext('777')
    assert mp.shadnet_signin('x', 'pw')['error'].startswith('The Online ID')
    assert 'password' in mp.shadnet_signin('Skater_2', '')['error']
    assert mp.shadnet_signin('Skater_2', 's3cret') == {'ok': True, 'npid': 'Skater_2', 'account': None}
    doc = json.loads((user / 'users.json').read_text(encoding='utf-8'))
    one, two = doc['Users']['user']
    assert (one['shadnet_npid'], one['shadnet_password'], one['shadnet_enabled'], one['shadnet_token']) == (
        'Skater_2', 's3cret', True, '')
    assert two['shadnet_npid'] == '' and doc['Users']['commit_hash'] == 'x'
    assert len(list(user.glob('users.json.overtime-*'))) == 1                   # the old file is kept
    assert mp.typed_ext is None
    v = mp.view()['you']                                                       # the log still says iksperial
    assert v['ext'] is None and v['shadnet'] == {'npid': 'Skater_2', 'state': 'stale', 'ready': True}
    assert 'Skater_2' in v['ext_why'] and 'Start NHL 19' in v['ext_why']
    (user / 'log' / 'shad_log.txt').write_bytes(b"[Lib.Np] ConnectUser: user_id=1000 signed in npid='Skater_2' accountId=5\n")
    mp.look()
    assert mp.ext() == (5, 'log')
    monkeypatch.setattr(overlay, 'emulator_running', lambda: True)
    assert 'running' in mp.shadnet_signin('Skater_2', 'x')['error']
    for bad in ('abc', '-4', '0', '1234567890123', '16 349'):
        assert 'number' in mp.set_ext(bad)['error'], bad
    assert mp.view()['you']['ext_from'] == 'log'


def test_signing_in_checks_with_shadnet_and_needs_no_game_run(mp, tmp_path, monkeypatch):
    user = log_in(tmp_path, monkeypatch)                                       # the log says iksperial / 16349
    mp._checks = lambda emu: []
    monkeypatch.setattr(overlay, 'emulator_running', lambda: False)
    mp.look()
    tried = []

    def login(npid, pw):
        tried.append((npid, pw))
        if pw != 's3cret':
            raise shadnet.ShadNetError('Wrong Online ID or password. Capitals count.', 8)
        return 501

    mp.sn_login = login
    before = (user / 'users.json').read_bytes()
    assert 'Capitals' in mp.shadnet_signin('Skater_2', 'wrong')['error']
    assert (user / 'users.json').read_bytes() == before                        # a refused password is not written
    assert mp.shadnet_signin('Skater_2', 's3cret') == {'ok': True, 'npid': 'Skater_2', 'account': 501}
    v = mp.view()['you']
    assert (v['ext'], v['ext_from'], v['ext_why']) == (501, 'shadnet', '')
    assert mp.ctl.prefs['multiplayer']['shadnet'] == {'npid': 'Skater_2', 'account': 501}
    assert 's3cret' not in json.dumps(mp.ctl.prefs)                            # the password stays in users.json only
    mp.look()                                                                  # the old log does not undo it
    assert mp.ext() == (501, 'shadnet')
    again = MC.MultiplayerCtl(mp.ctl)                                          # nor a restart of the app
    again._checks = lambda emu: []
    again.look()
    assert again.ext() == (501, 'shadnet')
    (user / 'log' / 'shad_log.txt').write_bytes(b"[Lib.Np] ConnectUser: user_id=1000 signed in npid='Skater_2' accountId=501\n")
    again.look()
    assert again.ext() == (501, 'log')                                         # the game's own sign-in agrees
    (user / 'log' / 'shad_log.txt').write_bytes(b'[Lib.Np] Login rejected error code 8\n')
    again.look()
    assert again.ext() == (None, '')                                           # the password changed on the site
    write_users(user, 'Other_1')                                               # another account put in by hand
    (user / 'log' / 'shad_log.txt').write_bytes(b'')
    again.look()
    assert again.ext() == (None, '')                                           # the check was for Skater_2 only


def test_creating_an_account_in_the_app(mp, tmp_path, monkeypatch):
    log_in(tmp_path, monkeypatch)
    mp._checks = lambda emu: []
    monkeypatch.setattr(overlay, 'emulator_running', lambda: False)
    mp.look()
    made = []

    def register(npid, pw, email, agent=''):
        if npid == 'Taken':
            raise shadnet.ShadNetError('Username already taken.')
        made.append((npid, pw, email))

    mp.sn_register = register
    mp.sn_login = lambda npid, pw: 777
    assert 'e-mail' in mp.shadnet_create('Skater_2', 'nope', 's3cret')['error']
    assert '6 characters' in mp.shadnet_create('Skater_2', 'a@b.cd', 'abc')['error']
    assert 'already taken' in mp.shadnet_create('Taken', 'a@b.cd', 's3cret')['error']
    assert mp.shadnet_create('Skater_2', 'a@b.cd', 's3cret') == {'ok': True, 'npid': 'Skater_2', 'account': 777,
                                                                 'created': True}
    assert made == [('Skater_2', 's3cret', 'a@b.cd')] and mp.ext() == (777, 'shadnet')
    mp.sn_register = _sn_down
    assert 'ShadNet site' in mp.shadnet_create('Skater_3', 'a@b.cd', 's3cret')['error']
    mp.sn_register = register
    monkeypatch.setattr(overlay, 'emulator_running', lambda: True)             # checked before the account is made
    assert 'running' in mp.shadnet_create('Skater_4', 'a@b.cd', 's3cret')['error'] and len(made) == 1
    monkeypatch.setattr(overlay, 'emulator_running', lambda: False)

    def unconfirmed(npid, pw):
        raise shadnet.ShadNetError('Wrong Online ID or password.', 8)

    mp.sn_login = unconfirmed
    out = mp.shadnet_create('Skater_5', 'a@b.cd', 's3cret')
    assert out['ok'] and out['account'] is None and out['created']             # saved: the password is right
    assert 'Confirm the e-mail' in mp.view()['you']['ext_why'] and mp.ext() == (None, '')
    assert 'Wrong' in mp.shadnet_signin('Skater_5', 'other')['error']          # a plain sign-in still refuses


def test_name_is_trimmed_and_remembered(mp):
    mp.set_name('  Puck   Fan ' + 'x' * 40)
    assert mp.name == ('Puck Fan ' + 'x' * 40)[:MC.NAME_MAX]
    again = MC.MultiplayerCtl(mp.ctl)
    assert again.name == mp.name


def test_no_id_no_lobby(mp):
    mp.set_name('Me')
    out = mp.create()
    assert 'ShadNet id' in out['error'] and mp.service.calls == [] and mp.view()['error'] == out['error']
    mp.set_ext('5')
    mp.set_name('')
    assert 'name' in mp.create()['error'] and mp.service.calls == []


# --- the lobby calls ----------------------------------------------------------------------------------------------
def start_lobby(mp, ext='16349'):
    mp.set_name('iksperial')
    mp.set_ext(ext)
    assert mp.create(public=True) == {'ok': True}


def test_create_shows_the_lobby_and_never_the_token(mp):
    start_lobby(mp)
    assert mp.service.calls[0] == ('create', 'iksperial', 16349, True)
    v = mp.view()
    assert v['lobby']['code'] == 'K7M2Q' and v['lobby']['players'][0]['you'] is True and v['lobby']['partner'] == ''
    assert 'secret-token' not in json.dumps(v) and mp.token == 'secret-token'
    assert 'Leave' in mp.create()['error']      # one lobby at a time


def test_a_new_lobby_is_public_unless_asked_otherwise(mp):
    mp.set_name('iksperial')
    mp.set_ext('16349')
    assert mp.create() == {'ok': True}
    assert mp.service.calls[0] == ('create', 'iksperial', 16349, True)


def test_join_validates_the_code_before_asking(mp):
    mp.set_name('Me')
    mp.set_ext('5')
    assert 'lobby code' in mp.join('??')['error'] and mp.service.calls == []
    assert mp.join(' k7m2q ') == {'ok': True}
    assert mp.service.calls[0] == ('join', 'K7M2Q', 'Me', 5)
    v = mp.view()['lobby']
    assert [p['name'] for p in v['players']] == ['Bo', 'iksperial'] and v['partner'] == 'Bo' and v['players'][1]['you']


def test_a_refused_call_says_why_in_the_servers_words(mp):
    mp.set_name('Me')
    mp.set_ext('5')
    mp.service.fail = LC.LobbyRefused(409, 'the lobby is full')
    assert mp.join('K7M2Q') == {'error': 'the lobby is full'} and mp.view()['error'] == 'the lobby is full'
    assert mp.view()['lobby'] is None and mp.busy == ''


def test_an_unreachable_service_is_told_and_recovers(mp):
    start_lobby(mp)
    mp.service.fail = LC.LobbyDown('x')
    mp.poll_once()
    assert mp.view()['error'] == ''                      # one miss is not news
    mp.service.fail = LC.LobbyDown('x')
    mp.poll_once()
    assert 'did not answer' in mp.view()['error'] and mp.view()['lobby'] is not None
    mp.poll_once()
    assert mp.view()['error'] == ''


def test_the_server_row_follows_the_public_list_ask(mp):
    mp._lobbies()
    assert {r['key']: r['tone'] for r in mp.view()['checks']}['server'] == 'good'
    assert mp.view()['lobbies'] == [{'code': 'AB123', 'host': 'Bo', 'players': 1, 'age': '2 min'}]
    mp.service.fail = LC.LobbyDown('x')
    mp._lobbies()
    row = [r for r in mp.view()['checks'] if r['key'] == 'server'][0]
    assert row['tone'] == 'bad' and row['text'] == 'not reachable' and 'Check again' in mp.view()['error']


def test_a_gone_lobby_is_left_with_a_note(mp):
    start_lobby(mp)
    mp.service.fail = LC.LobbyRefused(404, 'no such lobby')
    mp.poll_once()
    v = mp.view()
    assert v['lobby'] is None and '30 minutes' in v['error'] and mp.token is None
    assert mp.create() == {'ok': True}                    # free to start another


def test_leave_forgets_the_lobby_even_when_the_service_is_gone(mp):
    start_lobby(mp)
    mp.service.fail = LC.LobbyDown('x')
    assert mp.leave() == {'ok': True} and mp.view()['lobby'] is None
    assert mp.leave() == {'ok': True}                     # nothing to leave


def test_leaving_shows_the_public_list_again(mp):
    mp._spawn = lambda work, name: work()
    start_lobby(mp)
    assert mp.lobbies == []
    mp.leave()
    assert [r['code'] for r in mp.view()['lobbies']] == ['AB123'] and mp.ctl.pushed[-1] == 'multiplayer'


def test_ready_first_makes_the_game_fit_for_online_with_no_click(mp, monkeypatch):
    # owner 2026-11-08: the Kravickas build and the bare-minimum patch go in by themselves before the lobby is told
    start_lobby(mp)
    done, prints = [], iter(['none', 'f' * 20])
    mp.ctl.setup.online_boost = lambda note: done.append('boost') or note('Getting...') or 'on'
    monkeypatch.setattr(MC.patch_ctl, '_refresh_before_start', lambda setup: done.append('refresh'))
    monkeypatch.setattr(MC.patch_ctl, 'online_minimum', lambda setup: done.append('minimum'))
    monkeypatch.setattr(MC.overlay, 'status', lambda game_dir: {'layers': {}})
    monkeypatch.setattr(MC.gamesetup, 'patch_fingerprint', lambda emu: next(prints))
    mp.service.lobby['players'].append({'name': 'Bo', 'ready': False, 'launch': False, 'roster': 'unknown', 'stage': 'lobby'})
    mp.service.lobby.update(state='full')
    assert mp.ready(True) == {'ok': True}
    assert done == ['boost', 'refresh', 'minimum'] and mp.busy == '' and mp.prep == ''
    assert mp.service.calls[-1][0] == 'ready'
    # the same lobby never patches twice (a game that stays unpatched is the lobby's to refuse)
    prints = iter(['none', 'none'])
    mp.ready(True)
    assert done.count('minimum') == 1


def test_a_lobby_refusal_says_what_ready_could_not_do_here(mp, monkeypatch):
    start_lobby(mp)
    mp.ctl.setup.online_boost = lambda note: 'Close shadPS4 first.'
    monkeypatch.setattr(MC.patch_ctl, '_refresh_before_start', lambda setup: None)
    monkeypatch.setattr(MC.overlay, 'status', lambda game_dir: {'layers': {'menus': {}}})
    monkeypatch.setattr(MC.gamesetup, 'patch_fingerprint', lambda emu: 'f' * 20)
    mp.service.lobby['players'].append({'name': 'Bo', 'ready': False, 'launch': False, 'roster': 'unknown', 'stage': 'lobby'})
    mp.service.lobby.update(state='full')
    mp.service.fail = LC.LobbyRefused(409, 'two shadPS4 builds')
    got = mp.ready(True)
    assert 'two shadPS4 builds (here: the NHL 19 build of shadPS4 could not be switched on (Close shadPS4 first))'         == got['error']


def test_ready_and_the_launch_trigger(mp):
    start_lobby(mp)
    started = []
    mp._start_job = lambda: started.append(1)
    mp.service.lobby['players'].append({'name': 'Bo', 'ready': False, 'launch': False, 'roster': 'unknown', 'stage': 'lobby'})
    mp.service.lobby.update(state='full')
    assert mp.ready(True) == {'ok': True} and started == []
    assert mp.service.calls[-1] == ('ready', 'K7M2Q', 'secret-token', True)
    mp.service.lobby.update(state='launching')
    mp.poll_once()
    mp.poll_once()
    assert started == [1]                                 # once per launch, not once per poll
    mp.service.lobby.update(state='matched')
    mp.poll_once()
    assert started == [1]
    mp.service.lobby.update(state='full')                 # someone un-readied: the next launch counts again
    mp.poll_once()
    mp.service.lobby.update(state='launching')
    mp.poll_once()
    assert started == [1, 1]


def test_launch_now_needs_a_launching_lobby(mp):
    start_lobby(mp)
    assert 'ready first' in mp.launch_now()['error']
    started = []
    mp._start_job = lambda: started.append(1)
    mp.lobby['state'] = 'launching'
    assert mp.launch_now() == {'ok': True} and started == [1]


# --- the game start -----------------------------------------------------------------------------------------------
class Rig:
    """Fakes for the hook, shadPS4 and the key presses. `running` answers from `seq` (then False): the launch asks once
    before it starts, then the watch asks until the game closes."""

    def __init__(self, mp, monkeypatch, seq=(False, True, True, False), start_error=None):
        self.events, self.seq = [], list(seq)
        mp.running = lambda: self.seq.pop(0) if self.seq else False
        mp.press = lambda key: self.events.append(('press', key)) or True
        mp.sleep = lambda s: self.events.append(('sleep', s))
        mp.now = lambda: 1000.0
        monkeypatch.setattr(overlay, 'set_menus', self.set_menus)
        monkeypatch.setattr(launch, 'start', self.start)
        monkeypatch.setattr(keypress, 'cross_key', lambda emu: 'n')
        # NHL 19's player has a ShadNet sign-in and the log says nothing against it (tests below change these)
        self.player = {'shadnet': True, 'npid': 'Me', 'password': True}
        self.logs = []                  # shadnet_log answers in turn (then the last one)
        monkeypatch.setattr(gamesetup, 'shadnet_player', lambda user: self.player)
        monkeypatch.setattr(gamesetup, 'shadnet_log', lambda user: (self.logs.pop(0) if len(self.logs) > 1
                                                                    else self.logs[0] if self.logs else None))
        self.start_error = start_error

    def set_menus(self, game_dir, launch_opts, running=None):
        self.events.append(('hook', launch_opts))

    def start(self, emu, game_dir):
        self.events.append(('started', game_dir))
        if self.start_error:
            raise self.start_error
        return types.SimpleNamespace(pid=1)


def kinds(rig):
    return [e[0] for e in rig.events if e[0] != 'sleep']


def test_the_game_start_bakes_the_hook_starts_presses_and_takes_it_off(mp, monkeypatch):
    good_checks(mp)
    rig = Rig(mp, monkeypatch)
    start_lobby(mp)
    mp._launch_job()
    assert kinds(rig) == ['hook', 'started', 'press', 'press', 'hook']
    assert rig.events[0] == ('hook', {'until': 1000 + MC.HOOK_SECONDS}) and rig.events[-1] == ('hook', None)
    assert [e for e in rig.events if e[0] == 'press'] == [('press', 'n'), ('press', 'n')]
    assert ('sleep', MC.BOOT_WAIT) in rig.events and ('sleep', MC.TITLE_GAP) in rig.events
    assert mp.game['phase'] == 'ended'


def test_no_shadnet_sign_in_refuses_before_the_game_starts(mp, monkeypatch):
    """Live 2026-11-07: a tester's game stopped at SIGN IN REQUIRED while the friend waited."""
    good_checks(mp)
    rig = Rig(mp, monkeypatch)
    rig.player = {'shadnet': False, 'npid': 'Me', 'password': True}
    start_lobby(mp)
    mp._launch_job()
    assert 'started' not in kinds(rig) and mp.game['phase'] == 'failed' and mp.game['note'] == MC.SIGNIN_MISSING


def test_a_game_that_did_not_sign_in_stops_before_the_presses(mp, monkeypatch):
    good_checks(mp)
    rig = Rig(mp, monkeypatch)
    old = {'state': 'signed_in', 'when': 10.0, 'account': 5}
    new = {'state': 'signed_out', 'when': 20.0, 'account': None, 'shadnet_on': True, 'network_on': True}
    rig.logs = [old, new]
    start_lobby(mp)
    mp._launch_job()
    assert 'press' not in kinds(rig) and kinds(rig)[-1] == 'hook'     # the hook still comes off
    assert mp.game['phase'] == 'failed' and 'SIGN IN REQUIRED' in mp.game['note'] and 'nobody was signed in' in mp.game['note']


def test_the_last_runs_log_does_not_stop_a_new_start(mp, monkeypatch):
    good_checks(mp)
    rig = Rig(mp, monkeypatch)
    rig.logs = [{'state': 'rejected', 'code': 8, 'when': 10.0}]       # the new run has not written a log yet
    start_lobby(mp)
    mp._launch_job()
    assert kinds(rig) == ['hook', 'started', 'press', 'press', 'hook']


def test_without_the_press_setting_the_card_says_what_to_press(mp, monkeypatch):
    good_checks(mp)
    rig = Rig(mp, monkeypatch)
    start_lobby(mp)
    mp.set_press(False)
    mp._launch_job()
    assert 'press' not in kinds(rig) and kinds(rig)[0] == 'hook' and kinds(rig)[-1] == 'hook'
    mp.game = {'phase': 'title', 'note': '', 'manual': True}
    steps = mp.view()['game']['steps']
    assert steps[2] == {'text': 'Press ✕ on the title screen', 'state': 'now'}


def test_a_press_that_found_no_window_turns_the_card_manual(mp, monkeypatch):
    good_checks(mp)
    rig = Rig(mp, monkeypatch)
    mp.press = lambda key: False
    start_lobby(mp)
    mp._launch_job()
    assert kinds(rig).count('hook') == 2 and mp.game['phase'] == 'ended'


def test_the_hook_comes_off_when_the_game_will_not_start(mp, monkeypatch):
    good_checks(mp)
    rig = Rig(mp, monkeypatch, start_error=launch.LaunchError('shadPS4 not found: x'))
    start_lobby(mp)
    mp._launch_job()
    assert kinds(rig) == ['hook', 'started', 'hook'] and rig.events[-1] == ('hook', None)
    assert mp.game['phase'] == 'failed' and 'shadPS4 not found' in mp.game['note']


def test_an_unpatched_game_is_not_started(mp, monkeypatch):
    good_checks(mp, tone='bad')
    rig = Rig(mp, monkeypatch)
    start_lobby(mp)
    mp._launch_job()
    assert rig.events == [] and mp.game['phase'] == 'failed' and 'Patch the game first' in mp.game['note']
    mp.lobby['state'] = 'launching'
    assert mp.view()['game']['again'] is True


def test_a_running_game_is_a_rematch_with_no_hook(mp, monkeypatch):
    good_checks(mp)
    rig = Rig(mp, monkeypatch, seq=(True, True, False))
    start_lobby(mp)
    mp._launch_job()
    assert 'hook' not in kinds(rig) and 'started' not in kinds(rig)
    assert mp.game['phase'] == 'ended'


def test_a_hook_that_cannot_come_off_while_the_game_runs_waits_for_it(mp, monkeypatch):
    rig = Rig(mp, monkeypatch, seq=(True,))
    tries = []

    def set_menus(game_dir, opts, running=None):
        tries.append(opts)
        if len(tries) == 1:
            raise overlay.PatchError('shadPS4 is running: close the game first')
    monkeypatch.setattr(overlay, 'set_menus', set_menus)
    mp._unhook('game')
    assert tries == [None, None] and ('sleep', MC.WATCH_POLL) in rig.events


def test_a_stale_hook_is_cleared_only_while_the_game_is_off(mp, monkeypatch):
    calls = []
    monkeypatch.setattr(overlay, 'status', lambda d: {'layers': {'menus': {'autoplay_until': 5}}})
    monkeypatch.setattr(overlay, 'set_menus', lambda d, opts, running=None: calls.append(opts))
    mp.running = lambda: True
    mp._clear_stale_hook()
    assert calls == []
    mp.running = lambda: False
    mp._clear_stale_hook()
    assert calls == [None]
    monkeypatch.setattr(overlay, 'status', lambda d: {'layers': {'menus': {}}})
    mp._clear_stale_hook()
    assert calls == [None]


def test_the_card_follows_the_games_progress(mp, monkeypatch):
    start_lobby(mp)
    mp.lobby = {**mp.service.lobby, 'state': 'launching',
                'players': [{'name': 'iksperial', 'ready': True, 'stage': 'lobby', 'roster': 'ok'},
                            {'name': 'Bo', 'ready': True, 'stage': 'lobby', 'roster': 'ok'}]}

    def states():
        return [s['state'] for s in mp.view()['game']['steps']]
    for phase, expect in (('hook', 'now todo todo todo todo todo'), ('starting', 'done now todo todo todo todo'),
                          ('title', 'done done now todo todo todo'), ('ready', 'done done done now todo todo'),
                          ('running', 'done done done done now todo')):
        mp.game = {'phase': phase, 'note': '', 'manual': False}
        assert ' '.join(states()) == expect, phase
    mp.lobby['state'] = 'matched'
    assert ' '.join(states()) == 'done done done done done now'
    assert mp.view()['game']['steps'][3]['text'] == 'Game Setup: pressing READY'
    assert mp.view()['game']['steps'][4]['text'] == 'Online Versus, searching for Bo'
    mp.game = {'phase': 'running', 'note': '', 'manual': False, 'ready_manual': True}
    assert mp.view()['game']['steps'][3]['text'] == 'Press ✕ (READY) on Game Setup'
    json.dumps(mp.view())


# --- READY on Game Setup ------------------------------------------------------------------------------------------
class Clock:
    """A clock that moves on sleep, and the server's stage for me: `stages` is [(from second, stage)], and a READY
    press can move it (`after_press`)."""

    def __init__(self, mp, stages=((0, 'lobby'),), after_press=None, until=600):
        self.t, self.presses, self.stages, self.after_press = 0.0, [], list(stages), after_press
        mp.now = lambda: self.t
        mp.sleep = self.sleep
        mp.running = lambda: self.t < until
        mp.press = self.press
        mp._my_stage = self.stage

    def sleep(self, s):
        self.t += s

    def press(self, key):
        self.presses.append(self.t)
        if self.after_press:
            self.stages.append((self.t, self.after_press))
        return True

    def stage(self):
        return [s for at, s in self.stages if at <= self.t][-1]


def ready_rig(mp, monkeypatch, **kw):
    monkeypatch.setattr(keypress, 'cross_key', lambda emu: 'n')
    mp.game = {'phase': 'title', 'note': '', 'manual': False}
    return Clock(mp, **kw)


def test_ready_waits_for_game_setup_then_presses_once(mp, monkeypatch):
    c = ready_rig(mp, monkeypatch, stages=((0, 'lobby'), (40, 'setup')), after_press='searching')
    mp._ready('emu')
    assert len(c.presses) == 1 and 40 + MC.READY_SETTLE <= c.presses[0] < 40 + MC.READY_SETTLE + 2 * MC.WATCH_POLL
    assert not mp.game.get('ready_manual')


def test_a_title_press_that_was_ready_gets_no_extra_press(mp, monkeypatch):
    c = ready_rig(mp, monkeypatch, stages=((0, 'setup'), (MC.READY_SETTLE - 1, 'searching')))
    mp._ready('emu')
    assert c.presses == [] and not mp.game.get('ready_manual')


def test_ready_presses_again_while_no_search_starts(mp, monkeypatch):
    c = ready_rig(mp, monkeypatch, stages=((0, 'setup'),))
    mp._ready('emu')
    assert len(c.presses) == MC.READY_TRIES
    assert all(b - a >= MC.READY_GAP for a, b in zip(c.presses, c.presses[1:]))
    assert mp.game['ready_manual'] is True and mp.game['phase'] == 'ready'


def test_a_server_that_never_says_setup_gets_a_late_ready(mp, monkeypatch):
    c = ready_rig(mp, monkeypatch, stages=((0, 'lobby'),), after_press='searching')
    mp._ready('emu')
    assert len(c.presses) == 1 and MC.READY_BLIND <= c.presses[0] < MC.READY_BLIND + MC.WATCH_POLL


def test_game_setup_after_a_blind_press_gets_ready_soon(mp, monkeypatch):
    # lab mp3b: the blind press was the one that left the title screen, and Game Setup came later; a retry due just
    # then waits for the screen too
    late = MC.READY_BLIND + MC.READY_GAP + 1
    c = ready_rig(mp, monkeypatch, stages=((0, 'lobby'), (late, 'setup')))
    c.after_press = None
    mp._ready('emu')
    assert MC.READY_BLIND <= c.presses[0] < MC.READY_BLIND + MC.WATCH_POLL
    assert late + MC.READY_SETTLE <= c.presses[1] < late + MC.READY_SETTLE + 2 * MC.WATCH_POLL


def test_a_search_started_by_hand_needs_no_ready(mp, monkeypatch):
    c = ready_rig(mp, monkeypatch, stages=((0, 'lobby'), (10, 'searching')))
    mp._ready('emu')
    assert c.presses == [] and not mp.game.get('ready_manual')


def test_ready_is_manual_without_presses_or_after_a_manual_title(mp, monkeypatch):
    c = ready_rig(mp, monkeypatch)
    mp.set_press(False)
    mp._ready('emu')
    assert c.presses == [] and mp.game['ready_manual'] is True
    mp.set_press(True)
    mp.game = {'phase': 'title', 'note': '', 'manual': True}
    mp._ready('emu')
    assert c.presses == [] and mp.game['ready_manual'] is True


def test_ready_stops_when_the_game_closes(mp, monkeypatch):
    c = ready_rig(mp, monkeypatch, until=20)
    mp._ready('emu')
    assert c.presses == [] and c.t < 30


# --- the lobby address, the checks, the keys ----------------------------------------------------------------------
def test_the_lobby_is_the_server_the_game_is_patched_to(mp):
    assert mp.url() == 'https://ot.puckpeak.com'
    mp.url_override = 'https://evil.example.com'
    with pytest.raises(LC.LobbyRefused, match='must be the server Setup uses'):
        mp.url()
    mp.url_override = 'http://127.0.0.1:8081'
    with pytest.raises(LC.LobbyRefused):
        mp.url()                                           # a lab address only counts when Setup's server is the lab
    mp.ctl.setup.server['host'] = '127.0.0.1'
    assert mp.url() == 'http://127.0.0.1:8081'
    mp.url_override = 'https://evil.example.com'
    with pytest.raises(LC.LobbyRefused):
        mp.url()


def test_checks_read_the_patch_and_the_roster(mp, monkeypatch):
    status = {'installed': True, 'intact': True}
    layers = {'menus': {}, 'database': {}}
    monkeypatch.setattr(gamesetup, 'status', lambda emu: status)
    monkeypatch.setattr(overlay, 'status', lambda d: {'layers': layers, 'problems': []})
    got = {c['key']: (c['tone'], c['text']) for c in mp._checks('emu.exe')}
    assert got == {'roster': ('good', 'Overtime roster'), 'patch': ('good', 'on and intact')}
    layers.pop('database')
    assert mp._checks('emu.exe')[0]['tone'] == 'caution' and mp._checks('emu.exe')[0]['go'] == 'update'
    layers.pop('menus')
    assert mp._checks('emu.exe')[1]['tone'] == 'bad'
    status['intact'] = False
    assert 'not patched' in mp._checks('emu.exe')[1]['text']
    assert mp._checks('')[1]['go'] == 'setup'


def test_the_cross_key_comes_from_the_players_own_map(tmp_path, monkeypatch):
    user = tmp_path / 'user'
    (user / 'input_config').mkdir(parents=True)
    monkeypatch.setattr(gamesetup, 'emu_user_dir', lambda emu: str(user))
    assert keypress.cross_key('emu.exe') == 'n'                              # no map: the default profile's key
    ini = user / 'input_config' / 'default.ini'
    ini.write_text('# Keyboard bindings\ncross = kp2\n# Alternatives\ncross = N\nsquare = v\n'
                   '# Controller bindings\ncross = cross\n', encoding='utf-8')
    assert keypress.cross_key('emu.exe') == 'n'
    ini.write_text('cross = kp2\ncross = x\n# Controller bindings\ncross = z\n', encoding='utf-8')
    assert keypress.cross_key('emu.exe') == 'x'
    ini.write_text('cross = kp2\n# Controller bindings\ncross = z\n', encoding='utf-8')
    assert keypress.cross_key('emu.exe') == 'n'                              # the pad section is not a keyboard key


def test_a_press_needs_one_key():
    assert keypress.press('nn') is False and keypress.press('') is False


def test_polling_stops_when_there_is_no_lobby_and_no_tab(mp):
    mp.shown_now = False
    mp.poll_once = lambda: pytest.fail('asked the service')
    mp._poll_loop()                                         # returns at once


# --- match rules (docs/plans/m3b-match-settings.md) ---------------------------------------------------------------
def test_the_host_picks_a_rule_and_the_card_shows_it(mp):
    start_lobby(mp)
    card = mp.view()['lobby']['rules']
    assert card['can_edit'] and card['is_default'] and card['summary'] == 'Default rules'
    assert [r['key'] for r in card['rows']] == list(RU.KEYS)
    assert mp.set_rule('periodlength', 10) == {'ok': True}
    assert mp.service.calls[-1] == ('settings', 'K7M2Q', 'secret-token', {'periodlength': '10'})
    card = mp.view()['lobby']['rules']
    assert not card['is_default'] and card['summary'] == '10 min'
    assert next(r for r in card['rows'] if r['key'] == 'periodlength')['value'] == '10'
    assert 'secret-token' not in json.dumps(mp.view())


def test_the_partner_sees_the_rules_but_cannot_change_them(mp):
    mp.set_name('Me')
    mp.set_ext('5')
    mp.join('K7M2Q')                         # the fake puts the partner first: this player is the guest (you = 1)
    card = mp.view()['lobby']['rules']
    assert not card['can_edit'] and not any(r['can_edit'] for r in card['rows'])
    mp.service.calls.clear()
    assert 'host' in mp.set_rule('periodlength', 10)['error']
    assert mp.service.calls == []


def test_a_bad_rule_is_refused_before_asking(mp):
    start_lobby(mp)
    mp.service.calls.clear()
    assert 'choices' in mp.set_rule('periodlength', 7)['error']
    assert 'Unknown' in mp.set_rule('nope', 1)['error']
    assert mp.service.calls == []


def test_the_rules_are_fixed_once_the_game_is_starting(mp):
    start_lobby(mp)
    mp.lobby['state'] = 'launching'
    assert not mp.view()['lobby']['rules']['can_edit']
    mp.service.calls.clear()
    assert 'fixed' in mp.set_rule('periodlength', 10)['error'] and mp.service.calls == []


def test_the_launch_bakes_the_lobbys_rules_only_when_they_are_not_the_defaults(mp, monkeypatch):
    good_checks(mp)
    rig = Rig(mp, monkeypatch)
    start_lobby(mp)
    mp._launch_job()
    assert rig.events[0] == ('hook', {'until': 1000 + MC.HOOK_SECONDS})         # defaults: nothing baked
    mp.set_rule('periodlength', 10)
    mp.set_rule('fighting', 0)
    rig = Rig(mp, monkeypatch)
    mp._launch_job()
    baked = rig.events[0][1]
    assert baked['rules']['periodlength'] == '10' and baked['rules']['fighting'] == '0' and baked['until'] == 1000 + MC.HOOK_SECONDS


def test_a_running_game_keeps_its_rules_and_the_card_says_so(mp, monkeypatch):
    good_checks(mp)
    rig = Rig(mp, monkeypatch, seq=(True, True, False))
    start_lobby(mp)
    mp.set_rule('periodlength', 15)
    notes = []
    real = mp._phase
    mp._phase = lambda phase, note='', **kw: notes.append((phase, note)) or real(phase, note, **kw)
    mp._launch_job()
    assert 'hook' not in kinds(rig)
    assert any(ph == 'rematch' and 'keeps the rules' in note for ph, note in notes)


def test_reset_puts_every_rule_back(mp):
    start_lobby(mp)
    mp.set_rule('periodlength', 20)
    assert not mp.view()['lobby']['rules']['is_default']
    assert mp.reset_rules() == {'ok': True}
    assert mp.service.calls[-1][3] == RU.DEFAULTS and mp.view()['lobby']['rules']['is_default']


def test_the_guest_bakes_the_hosts_rules_and_cannot_change_them(mp, monkeypatch):
    good_checks(mp)
    rig = Rig(mp, monkeypatch)
    mp.set_name('Me')
    mp.set_ext('5')
    mp.join('K7M2Q')                         # the guest: the fake lists the partner first
    picked = {**RU.DEFAULTS, 'periodlength': '15', 'icing': '0'}
    mp.service.lobby = {**mp.service.lobby, 'rules': picked, 'state': 'launching'}
    mp.poll_once()                           # the polled state carries what the host picked
    assert mp.view()['lobby']['rules']['summary'] == RU.summary(picked) and not mp.view()['lobby']['rules']['can_edit']
    mp._launch_job()
    assert rig.events[0][1]['rules'] == picked
    mp.service.calls.clear()
    assert mp.set_rule('periodlength', 4)['error'] and mp.service.calls == []


def test_a_server_without_match_rules_shows_no_card_and_bakes_nothing(mp, monkeypatch):
    good_checks(mp)
    rig = Rig(mp, monkeypatch)
    start_lobby(mp)
    mp.lobby = {k: v for k, v in mp.lobby.items() if k != 'rules'}     # a lobby from a server before M3b
    assert mp.view()['lobby']['rules'] is None
    mp._launch_job()
    assert rig.events[0] == ('hook', {'until': 1000 + MC.HOOK_SECONDS})


def test_why_the_service_did_not_answer_goes_to_the_error_log_once(mp, monkeypatch):
    logged = []
    monkeypatch.setattr(MC.jobs, 'log_block', lambda err, step='': logged.append((str(err), step)))
    mp.service.fail = LC.LobbyDown('the lobby service did not answer (timed out)')
    mp._lobbies()
    mp.service.fail = LC.LobbyDown('the lobby service did not answer (timed out)')
    mp._lobbies()
    assert mp.view()['error'] == MC.DOWN_TEXT and len(logged) == 1 and logged[0][1].startswith('Lobby service')
    mp.service.fail = LC.LobbyDown('the lobby service did not answer (CERTIFICATE_VERIFY_FAILED)', certificate=True)
    mp._lobbies()
    assert mp.view()['error'] == MC.CERT_TEXT and len(logged) == 2
    mp._lobbies()                                         # it answers again: the words go
    assert mp.view()['error'] == ''


def _roster_service(svc):
    def roster_mode(code, token, mode):
        svc._go('roster_mode', code, token, mode)
        svc.lobby = {**svc.lobby, 'roster_mode': mode, 'host_roster': False}
        return {**svc.lobby, 'you': 0}

    def upload_roster(code, token, blob):
        svc._go('upload_roster', code, token, bytes(blob))
        svc.lobby = {**svc.lobby, 'host_roster': True}
        return {**svc.lobby, 'you': 0}
    svc.roster_mode, svc.upload_roster = roster_mode, upload_roster


def test_the_host_plays_its_own_roster_and_sends_it_at_ready(mp, monkeypatch):
    # live 2026-11-07: the server roster had dealt lines; the host may play its own roster, the guest adopts it
    _roster_service(mp.service)
    start_lobby(mp)
    mp.service.lobby['roster_mode'] = 'server'
    mp.lobby = dict(mp.service.lobby)
    assert mp.view()['lobby']['roster_mode'] == {'mode': 'server', 'uploaded': False, 'edit': True}
    assert 'Pick' in mp.set_roster_mode('mine')['error']
    assert mp.set_roster_mode('host') == {'ok': True}
    assert mp.view()['lobby']['roster_mode']['mode'] == 'host'
    mp.ctl.game.schema = lambda: 'schema'
    monkeypatch.setattr(MC.hostroster, 'host_roster', lambda game_dir, schema, db: (b'ROSTER', 'C' * 54, 'patch'))
    mp.service.calls.clear()
    assert mp.ready() == {'ok': True}
    assert [c[0] for c in mp.service.calls] == ['upload_roster', 'ready']
    assert mp.service.calls[0][3] == b'ROSTER'


def test_a_host_without_a_served_roster_is_told_to_patch(mp, monkeypatch):
    _roster_service(mp.service)
    start_lobby(mp)
    mp.service.lobby['roster_mode'] = 'server'
    mp.lobby = dict(mp.service.lobby)
    mp.set_roster_mode('host')
    mp.ctl.game.schema = lambda: 'schema'

    def none(game_dir, schema, db):
        raise MC.hostroster.HostRosterError('press Patch first')
    monkeypatch.setattr(MC.hostroster, 'host_roster', none)
    mp.service.calls.clear()
    assert 'Patch' in mp.ready()['error'] and mp.service.calls == []


def test_the_guest_cannot_pick_the_roster(mp):
    _roster_service(mp.service)
    mp.set_name('Me')
    mp.set_ext('5')
    mp.join('K7M2Q')
    mp.service.calls.clear()
    assert 'host' in mp.set_roster_mode('host')['error'] and mp.service.calls == []
    assert mp.view()['lobby']['roster_mode'] is None      # a server without the roster choice shows none


# --- Online Shootout ------------------------------------------------------------------------------------------------

def test_the_host_picks_shootout_and_the_card_greys_out_the_rules_it_has_not(mp):
    start_lobby(mp)
    assert mp.view()['lobby']['mode'] == 'versus' and not any(r['off'] for r in mp.view()['lobby']['rules']['rows'])
    assert mp.set_mode('shootout') == {'ok': True}
    assert mp.service.calls[-1] == ('mode', 'K7M2Q', 'secret-token', 'shootout')
    view = mp.view()['lobby']
    assert view['mode'] == 'shootout' and view['game'] == 'Shootout'
    rows = {r['key']: r for r in view['rules']['rows']}
    assert [k for k, r in rows.items() if not r['off']] == [r[0] for r in RU.SHOOTOUT_RULES]
    assert all(not r['can_edit'] for r in rows.values() if r['off']) and rows['goaliecontrol']['can_edit']
    assert view['rules']['is_default'] and view['rules']['summary'] == 'Default rules'
    assert mp.set_rule('goaliecontrol', 0) == {'ok': True}
    assert mp.service.calls[-1][3] == {'goaliecontrol': '0'}
    assert 'Unknown' in mp.set_rule('periodlength', 10)['error'] or 'periodlength' in mp.set_rule('periodlength', 10)['error']


def test_only_the_host_picks_the_game_and_not_once_it_is_starting(mp):
    start_lobby(mp)
    assert 'Pick' in mp.set_mode('hockey')['error'] and mp.service.calls[-1][0] != 'mode'
    mp.me = 1
    assert 'host' in mp.set_mode('shootout')['error']
    mp.me = 0
    mp.lobby = dict(mp.lobby, state='launching')
    assert 'fixed' in mp.set_mode('shootout')['error']


def test_a_server_before_shootout_is_told_so_and_the_lobby_stays_versus(mp):
    start_lobby(mp)
    mp.service.fail = LC.LobbyRefused(404, 'not found')
    assert 'does not offer Online Shootout' in mp.set_mode('shootout')['error']
    assert mp.view()['lobby']['mode'] == 'versus'


def test_a_shootout_launch_hooks_the_shootout_hub_and_bakes_its_rules(mp, monkeypatch):
    good_checks(mp)
    start_lobby(mp)
    mp.set_mode('shootout')
    rig = Rig(mp, monkeypatch)
    mp._launch_job()
    assert rig.events[0] == ('hook', {'until': 1000 + MC.HOOK_SECONDS, 'mode': 'shootout'})   # defaults: no rules baked
    mp.set_rule('goaliecontrol', 0)
    rig = Rig(mp, monkeypatch)
    mp._launch_job()
    assert rig.events[0][1]['mode'] == 'shootout' and set(rig.events[0][1]['rules']) == {r[0] for r in RU.SHOOTOUT_RULES} and rig.events[0][1]['rules']['goaliecontrol'] == '0'
    mp.game = {'phase': 'running', 'note': '', 'manual': False}
    assert mp.view()['game']['steps'][4]['text'] == 'Online Shootout, searching for your friend'


# --- 0.80: the match-only setup (docs/plans/mellow-crunching-hippo.md) ---------------------------------------------
from overtime_roster.app import matchsetup, onlineemu  # noqa: E402


def test_the_host_announces_its_recipe_and_caps_the_guest_its_caps(mp):
    start_lobby(mp)
    assert [a[0] for a in mp.service.announced] == ['match', 'ready']
    assert mp.service.announced[-1][-1] == MC.CAPS
    matchsetup.check(mp.service.recipe)                  # what the guest's app will read
    assert mp.service.calls == [('create', 'iksperial', 16349, True)]   # no Ready said on the player's behalf
    guest = MC.MultiplayerCtl(mp.ctl)
    guest.threads, guest.service = False, FakeService()
    guest.make_client = lambda url: guest.service
    guest.set_name('Me')
    guest.set_ext('5')
    guest.join('K7M2Q')
    assert [a[0] for a in guest.service.announced] == ['ready'] and guest.me == 1


def match_lobby(mp, emu_sha=None):
    start_lobby(mp)
    mp.lobby.update(match=mp.service.recipe, match_setup=True, match_id='0123456789abcdef',
                    online_emu={'sha256': emu_sha, 'url': 'https://x/'} if emu_sha else None)
    mp.service.lobby.update(mp.lobby)


class MatchRig(Rig):
    """Rig plus fakes for the online copy, the match setup and the restart."""

    def __init__(self, mp, monkeypatch, seq=(False, True, True, False), stop='closed', tag=None):
        super().__init__(mp, monkeypatch, seq)
        self.stop, self.tag = stop, tag
        mp.stop_emulator = lambda: self.events.append(('stop',)) or self.stop
        monkeypatch.setattr(onlineemu, 'start_dir', lambda emu: 'D:/emu')
        monkeypatch.setattr(onlineemu, 'ensure', lambda cache, want=None, progress=None:
                            (self.events.append(('ensure', want)) or 'C:/online/shadPS4.exe', 'f' * 64))
        monkeypatch.setattr(matchsetup, 'apply', self.apply)
        monkeypatch.setattr(matchsetup, 'restore', lambda running=None, log=None, only=None:
                            self.events.append(('restore',)) or 'done')
        monkeypatch.setattr(matchsetup, 'tag', lambda: self.tag)
        monkeypatch.setattr(overlay, 'status', lambda gd, **kw: {'layers': {}})

    def apply(self, game_dir, user, r, own_text, running=None, log=None, tag=None):
        self.events.append(('apply', tag))
        self.own_text = own_text
        return {'patch': 'C:/match/overtime-match.xml', 'view': 'link'}

    def start(self, emu, game_dir, patch_file=None, exe=None):
        self.events.append(('started', patch_file, exe))
        return types.SimpleNamespace(pid=1)


def test_a_match_launch_sets_up_starts_the_online_copy_and_puts_everything_back(mp, monkeypatch):
    rig = MatchRig(mp, monkeypatch)
    match_lobby(mp)
    mp._launch_job()
    assert kinds(rig) == ['ensure', 'apply', 'hook', 'started', 'press', 'press', 'hook', 'restore']
    assert ('apply', '0123456789abcdef') in rig.events
    assert ('started', 'C:/match/overtime-match.xml', 'C:/online/shadPS4.exe') in rig.events
    assert not xmlpatch.parse(rig.own_text)[0] is None and mp.game['phase'] == 'ended'


def test_an_unpatched_game_starts_with_the_match_setup(mp, monkeypatch):
    good_checks(mp, tone='bad')             # the player's own game is not patched: the match setup is its own
    rig = MatchRig(mp, monkeypatch)
    match_lobby(mp)
    mp._launch_job()
    assert 'started' in kinds(rig) and mp.game['phase'] == 'ended'


def test_a_game_running_with_another_setup_is_restarted(mp, monkeypatch):
    rig = MatchRig(mp, monkeypatch, seq=(True, False, True, True, False))
    match_lobby(mp)
    mp._launch_job()
    assert kinds(rig)[:3] == ['stop', 'ensure', 'apply'] and 'started' in kinds(rig)


def test_a_game_that_does_not_close_fails_the_start_and_nothing_is_set_up(mp, monkeypatch):
    for stop, text in (('failed', MC.RESTART_FAILED), ('unsupported', MC.RESTART_UNSUPPORTED)):
        rig = MatchRig(mp, monkeypatch, seq=(True,), stop=stop)
        mp.code = None
        match_lobby(mp)
        mp._launch_job()
        assert kinds(rig) == ['stop'] and mp.game['phase'] == 'failed' and mp.game['note'] == text


def test_a_game_running_with_this_matchs_setup_is_a_rematch(mp, monkeypatch):
    rig = MatchRig(mp, monkeypatch, seq=(True, True, False), tag='0123456789abcdef')
    match_lobby(mp)
    mp._launch_job()
    assert kinds(rig) == ['restore'] and mp.game['phase'] == 'ended'


def test_a_failed_setup_still_puts_things_back(mp, monkeypatch):
    rig = MatchRig(mp, monkeypatch)

    def broken(*a, **k):
        rig.events.append(('apply', None))
        raise matchsetup.MatchSetupError('in the way')
    monkeypatch.setattr(matchsetup, 'apply', broken)
    match_lobby(mp)
    mp._launch_job()
    assert kinds(rig)[-2:] == ['hook', 'restore'] and 'started' not in kinds(rig)
    assert mp.game['phase'] == 'failed' and 'in the way' in mp.game['note']


def test_ready_in_a_match_lobby_gets_the_copy_and_sends_the_match_fingerprint(mp, monkeypatch):
    MatchRig(mp, monkeypatch)
    match_lobby(mp, emu_sha='a' * 64)
    boosted = []
    mp.ctl.setup.online_boost = lambda note: boosted.append(1) or 'on'
    assert mp.ready(True) == {'ok': True}
    assert boosted == [] and mp.service.caps == MC.CAPS
    own = mp._own_text()
    assert mp.service.patch == xmlpatch.netplay_fingerprint(matchsetup.match_xml(mp.service.recipe, own))
    assert mp.service.patch == xmlpatch.netplay_fingerprint(mp.ctl.setup._xml())   # the same as the host's


def test_ready_says_why_when_the_online_copy_cannot_be_had(mp, monkeypatch):
    MatchRig(mp, monkeypatch)
    match_lobby(mp)

    def no(cache, want=None, progress=None):
        raise onlineemu.OnlineEmuError('The lobby plays with another shadPS4 build than this app has: update the app.')
    monkeypatch.setattr(onlineemu, 'ensure', no)
    assert 'update the app' in mp.ready(True)['error']
    assert not any(c[0] == 'ready' for c in mp.service.calls)


def test_a_match_launch_shows_the_setup_step_first(mp, monkeypatch):
    MatchRig(mp, monkeypatch)
    match_lobby(mp)
    mp.game = {'phase': 'restarting', 'note': '', 'manual': False}
    steps = mp.view()['game']['steps']
    assert steps[0] == {'text': MC.RESTART_STEP, 'state': 'now'} and len(steps) == len(MC.STEPS) + 1
    mp.game = {'phase': 'title', 'note': '', 'manual': True}
    steps = mp.view()['game']['steps']
    assert steps[0] == {'text': MC.MATCH_STEP, 'state': 'done'}
    assert steps[3] == {'text': 'Press ✕ on the title screen', 'state': 'now'}


def test_an_unpatched_game_is_ready_for_online_in_the_pre_flight(mp):
    mp.checks = [{'key': 'patch', 'label': 'Patch', 'tone': 'bad', 'text': 'not patched', 'go': 'patch'},
                 {'key': 'roster', 'label': 'Roster', 'tone': 'bad', 'text': 'shadPS4 not set up', 'go': 'setup'}]
    assert next(r for r in mp.view()['checks'] if r['key'] == 'roster')['tone'] == 'bad'   # only the patch row
    patch = next(r for r in mp.view()['checks'] if r['key'] == 'patch')
    assert patch['tone'] == 'good' and patch['text'] == MC.ONLINE_READY
