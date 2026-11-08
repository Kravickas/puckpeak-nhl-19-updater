"""Match-only setup (overtime_roster/app/matchsetup.py): recipe, apply, restore after a crash at every step."""
import hashlib
import json
import os

import pytest

from overtime_core import overlay, xmlpatch
from overtime_roster.app import gamesetup, matchsetup as MS


def _tree(folder):
    """{relative path: sha256} of every file under folder (None when it does not exist)."""
    if not os.path.isdir(folder):
        return None
    out = {}
    for root, _dirs, files in os.walk(folder):
        for n in files:
            p = os.path.join(root, n)
            with open(p, 'rb') as f:
                out[os.path.relpath(p, folder)] = hashlib.sha256(f.read()).hexdigest()
    return out


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'apphome'))
    monkeypatch.setenv('APPDATA', str(tmp_path / 'appdata'))
    game = tmp_path / 'games' / 'NHL 19'
    (game / 'databigs').mkdir(parents=True)
    (game / 'eboot.bin').write_bytes(b'eboot')
    mods = tmp_path / 'games' / 'NHL 19-mods'
    (mods / 'databigs').mkdir(parents=True)
    (mods / 'databigs' / 'boot.big').write_bytes(b'players boot')
    (mods / 'databigs' / 'patch_inxp_57.big').write_bytes(b'players art')
    (mods / overlay.STATE_NAME).write_text('{"layers": {}}', encoding='utf-8')
    user = tmp_path / 'appdata' / 'shadPS4'
    (user / 'custom_configs').mkdir(parents=True)
    cfg_path = gamesetup.custom_config_path(str(user))
    with open(cfg_path, 'w', encoding='utf-8', newline='') as f:   # odd spacing: must come back byte for byte
        f.write('{"General": {"connected_to_network": false},  "GPU": {"vblank_frequency": 9999}}\r\n')
    host_text = xmlpatch.build('ot.puckpeak.com', 'https://91.98.195.150/')
    monkeypatch.setattr(overlay, 'status', lambda gd, **kw: {'layers': {}})
    added = []

    def add_layers(gd, layers):
        added.append(list(layers))
        # an overlay write: temp file + os.replace, as overlay.py does
        target = os.path.join(str(mods), 'databigs', 'boot.big')
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target + '.tmp', 'wb') as f:
            f.write(b'menus boot with hook')
        os.replace(target + '.tmp', target)

    return {'game': str(game), 'mods': str(mods), 'user': str(user), 'cfg': cfg_path, 'host': host_text,
            'add': add_layers, 'added': added, 'off': lambda: False}


def _snapshot(w):
    with open(w['cfg'], 'rb') as f:
        cfg = f.read()
    return _tree(w['mods']), cfg


def test_match_patch_carries_the_host_netplay_bytes_and_my_local_blocks():
    host = xmlpatch.build('ot.puckpeak.com', 'https://91.98.195.150/')
    mine = xmlpatch.with_res1440(xmlpatch.build('ot.example.org', 'https://10.0.0.2/'), True)
    r = MS.recipe(host)
    text = MS.match_xml(r, mine)
    assert xmlpatch.netplay_fingerprint(text) == xmlpatch.netplay_fingerprint(host)
    assert xmlpatch.res1440(text)                                   # my picture size
    assert xmlpatch.targets(text)['redirector'] == 'ot.example.org'   # my server name
    assert not xmlpatch.res1440(MS.match_xml(r, host))              # the host's 1080p stays the host's


def test_recipe_check_refuses_what_does_not_read():
    good = MS.recipe(xmlpatch.build('ot.puckpeak.com', 'https://91.98.195.150/'))
    MS.check(good)
    assert all(isinstance(t, str) for t in good['xml_blocks'])     # the server keeps patch texts (lobby.md)
    assert json.loads(json.dumps(good)) == good
    zz = MS.render([{'name': 'a', 'lines': [['0x1', 'zz']]}])
    for bad in ({'v': 99}, dict(good, xml_blocks='x'), dict(good, xml_blocks=['<not xml']),
                dict(good, xml_blocks=[{'name': 'a', 'lines': [['0x1', '00']]}]), dict(good, xml_blocks=[zz]),
                dict(good, xml_blocks=['x' * (MS.MAX_TEXT + 1)]),
                dict(good, layers=[{'id': 'roster'}]), dict(good, timing={'vblank_frequency': 9999}),
                dict(good, timing={'speed': 2})):
        with pytest.raises(MS.MatchSetupError):
            MS.check(bad)


def test_apply_then_restore_gives_the_players_files_back_byte_for_byte(world):
    w = world
    before = _snapshot(w)
    got = MS.apply(w['game'], w['user'], MS.recipe(w['host']), w['host'], add_layers=w['add'], running=w['off'])
    assert MS.active()
    assert w['added'] == [['menus']]
    with open(os.path.join(w['mods'], 'databigs', 'boot.big'), 'rb') as f:
        assert f.read() == b'menus boot with hook'                  # the game sees the match view
    with open(os.path.join(w['mods'] + MS.OWN_SUFFIX, 'databigs', 'boot.big'), 'rb') as f:
        assert f.read() == b'players boot'                          # the hardlink was replaced, not written through
    cfg = json.load(open(w['cfg'], encoding='utf-8'))
    assert cfg['GPU']['vblank_frequency'] == 60 and cfg['Network']['shad_net_enabled'] is True
    assert os.path.isfile(got['patch'])
    assert MS.restore(running=w['off']) == 'done'
    assert not MS.active()
    assert _snapshot(w) == before
    assert not os.path.exists(w['mods'] + MS.VIEW_SUFFIX) and not os.path.exists(w['mods'] + MS.OWN_SUFFIX)


def test_restore_waits_while_the_game_runs(world):
    w = world
    MS.apply(w['game'], w['user'], MS.recipe(w['host']), w['host'], add_layers=w['add'], running=w['off'])
    assert MS.restore(running=lambda: True) == 'later'
    assert MS.active()
    assert MS.restore(running=w['off']) == 'done'


def test_a_game_with_no_mods_folder_gets_none_back(world):
    w = world
    import shutil
    shutil.rmtree(w['mods'])
    MS.apply(w['game'], w['user'], MS.recipe(w['host']), w['host'], add_layers=w['add'], running=w['off'])
    assert os.path.isdir(w['mods'])
    MS.restore(running=w['off'])
    assert not os.path.exists(w['mods'])


@pytest.mark.parametrize('crash_at', ['view', 'own_moving', 'own_moved', 'view_moving', 'view_in', 'config_writing',
                                      'applied'])
def test_a_crash_after_any_step_is_undone_by_restore(world, monkeypatch, crash_at):
    w = world
    before = _snapshot(w)
    real_save = MS._save

    class Crash(Exception):
        pass

    def save(j):
        real_save(j)
        if j.get('steps') and j['steps'][-1] == crash_at:
            raise Crash()
    monkeypatch.setattr(MS, '_save', save)
    with pytest.raises(Crash):
        MS.apply(w['game'], w['user'], MS.recipe(w['host']), w['host'], add_layers=w['add'], running=w['off'])
    monkeypatch.setattr(MS, '_save', real_save)
    assert MS.restore(running=w['off']) == 'done'
    assert _snapshot(w) == before
    assert not MS.active()


@pytest.mark.parametrize('nth', [1, 2])
def test_a_crash_right_after_a_rename_is_undone_by_restore(world, monkeypatch, nth):
    """The rename went through but the journal never heard of it."""
    w = world
    before = _snapshot(w)
    real_rename, calls = os.rename, []

    def rename(a, b):
        real_rename(a, b)
        calls.append(a)
        if len(calls) == nth:
            raise KeyboardInterrupt()
    monkeypatch.setattr(os, 'rename', rename)
    with pytest.raises(KeyboardInterrupt):
        MS.apply(w['game'], w['user'], MS.recipe(w['host']), w['host'], add_layers=w['add'], running=w['off'])
    monkeypatch.setattr(os, 'rename', real_rename)
    assert MS.restore(running=w['off']) == 'done'
    assert _snapshot(w) == before


def test_a_crash_while_adding_layers_is_undone_by_restore(world):
    w = world
    before = _snapshot(w)

    def broken(gd, layers):
        w['add'](gd, layers)
        raise OSError('disk full')
    with pytest.raises(OSError):
        MS.apply(w['game'], w['user'], MS.recipe(w['host']), w['host'], add_layers=broken, running=w['off'])
    assert MS.restore(running=w['off']) == 'done'
    assert _snapshot(w) == before


def test_copy_fallback_when_links_fail(world, monkeypatch):
    w = world
    before = _snapshot(w)

    def no_link(a, b):
        raise OSError('no hardlinks here')
    monkeypatch.setattr(os, 'link', no_link)
    got = MS.apply(w['game'], w['user'], MS.recipe(w['host']), w['host'], add_layers=w['add'], running=w['off'])
    assert got['view'] == 'copy'
    MS.restore(running=w['off'])
    assert _snapshot(w) == before


def test_restore_never_deletes_a_folder_without_the_marker(world):
    w = world
    stranger = w['mods'] + MS.VIEW_SUFFIX
    os.makedirs(stranger)
    with open(os.path.join(stranger, 'mine.txt'), 'w') as f:
        f.write('keep')
    with pytest.raises(MS.MatchSetupError):
        MS.apply(w['game'], w['user'], MS.recipe(w['host']), w['host'], add_layers=w['add'], running=w['off'])
    assert os.path.isfile(os.path.join(stranger, 'mine.txt'))


def test_apply_refuses_a_match_patch_without_a_server(world):
    w = world
    no_server = MS.render([])
    with pytest.raises(MS.MatchSetupError):
        MS.apply(w['game'], w['user'], MS.recipe(w['host']), no_server, add_layers=w['add'], running=w['off'])
    assert not MS.active()


def test_apply_refuses_while_shadps4_runs(world):
    w = world
    with pytest.raises(MS.MatchSetupError):
        MS.apply(w['game'], w['user'], MS.recipe(w['host']), w['host'], running=lambda: True)
    assert not MS.active()


def test_app_start_puts_a_left_setup_back_once_shadps4_closed(world):
    w = world
    before = _snapshot(w)
    MS.apply(w['game'], w['user'], MS.recipe(w['host']), w['host'], add_layers=w['add'], running=w['off'], tag='t1')
    assert MS.tag() == 't1'
    seq, slept = [True, True, False, False], []
    got = MS.restore_when_closed(running=lambda: seq.pop(0), sleep=slept.append, every=3)
    assert got == 'done' and slept == [3, 3] and _snapshot(w) == before and MS.tag() is None
    assert MS.restore_when_closed(running=w['off']) == 'none'
