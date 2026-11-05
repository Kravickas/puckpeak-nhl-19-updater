import json
import os

import pytest

from overtime_core import sfo, xmlpatch
from overtime_roster.app import gamesetup, launch


def _sfo(title_id='CUSA11126', app_ver='01.60'):
    return sfo.build([sfo.Entry('APP_VER', sfo.FMT_UTF8, app_ver, 8), sfo.Entry('TITLE_ID', sfo.FMT_UTF8, title_id, 12)])


def _game(root, name='NHL 19', **kw):
    g = root / name
    (g / 'sce_sys').mkdir(parents=True)
    (g / 'sce_sys' / 'param.sfo').write_bytes(_sfo(**kw))
    (g / 'eboot.bin').write_bytes(b'\x7fELF fake eboot')
    (g / 'databigs').mkdir()
    (g / 'databigs' / 'game_60.big').write_bytes(b'x' * 1000)
    return g


@pytest.fixture
def world(tmp_path, monkeypatch):
    appdata = tmp_path / 'appdata'
    user = appdata / 'shadPS4'
    (user / 'custom_configs').mkdir(parents=True)
    monkeypatch.setenv('APPDATA', str(appdata))
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'apphome'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    emu_dir = tmp_path / 'PS4' / 'PS4 Emulator'
    emu_dir.mkdir(parents=True)
    emu = emu_dir / 'shadPS419.exe'
    emu.write_bytes(b'MZ')
    (emu_dir / 'shadPS4QtLauncher.exe').write_bytes(b'MZ')
    game = _game(tmp_path / 'PS4')
    cfg = {'General': {'install_dirs': [{'enabled': True, 'path': str(tmp_path / 'PS4')}],
                       'connected_to_network': False}, 'GPU': {'full_screen': True}}
    (user / 'config.json').write_text(json.dumps(cfg, indent=4), encoding='utf-8')
    users = {'Users': {'user': [{'user_id': 1000, 'user_name': 'shadPS4', 'shadnet_enabled': True,
                                 'shadnet_npid': 'skater', 'shadnet_email': 'a@b.c', 'shadnet_password': 'hunter2',
                                 'shadnet_token': 'tok'}]}}
    (user / 'users.json').write_text(json.dumps(users), encoding='utf-8')
    return {'tmp': tmp_path, 'user': user, 'emu': emu, 'game': game}


def _tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_finds_emulator_and_game(world):
    assert gamesetup.emu_user_dir(str(world['emu'])) == str(world['user'])
    emus = gamesetup.find_emulators()
    assert [os.path.basename(e) for e in emus] == ['shadPS419.exe']  # not the Qt launcher
    games = gamesetup.find_games(str(world['user']))
    assert [g['path'] for g in games] == [str(world['game'])] and games[0]['ok']


def test_portable_user_dir(world):
    (world['emu'].parent / 'user').mkdir()
    assert gamesetup.emu_user_dir(str(world['emu'])) == str(world['emu'].parent / 'user')


@pytest.mark.parametrize('kw, problem', [({'title_id': 'CUSA00001'}, 'not NHL 19'), ({'app_ver': '01.00'}, '01.60')])
def test_wrong_game_refused(tmp_path, kw, problem):
    info = gamesetup.read_game(str(_game(tmp_path, **kw)))
    assert not info['ok'] and problem in info['problem']


def test_shadnet_secrets_never_read_out(world):
    users = gamesetup.shadnet_users(str(world['user']))
    assert users == [{'user_id': 1000, 'name': 'shadPS4', 'shadnet': True, 'npid': 'skater',
                      'password': True}]
    assert 'hunter2' not in repr(users) and 'tok' not in repr(users) and 'a@b.c' not in repr(users)


def test_install_and_remove_leave_nothing_behind(world):
    before = _tree(world['user'])
    text = xmlpatch.build('ot.puckpeak.com', 'https://91.98.195.150/')
    m = gamesetup.install(str(world['emu']), text, running=lambda: False)
    folder = world['user'] / 'patches' / 'Overtime'
    assert (folder / 'overtime.xml').read_bytes() == text.encode('utf-8')
    assert json.loads((folder / 'files.json').read_text()) == {'overtime.xml': ['CUSA11126']}
    cfg = json.loads((world['user'] / 'custom_configs' / 'CUSA11126.json').read_text())
    assert cfg['General']['connected_to_network'] is True and cfg['General']['shad_net_enabled'] is True
    assert cfg['GPU'] == {'full_screen': True}  # a new per-game config starts from the global one
    assert gamesetup.network_settings(str(world['user'])) == gamesetup.NETWORK
    assert m['targets']['redirector'] == 'ot.puckpeak.com'
    st = gamesetup.status(str(world['emu']))
    assert st['installed'] and st['intact']
    gamesetup.install(str(world['emu']), text, running=lambda: False)  # again: same result, still one entry each
    assert len(gamesetup.load_manifest()['files']) == 3
    gamesetup.remove(running=lambda: False)
    assert _tree(world['user']) == before
    assert not folder.exists() and gamesetup.load_manifest() is None


def test_adopt_takes_over_a_patch_another_record_wrote(world):
    """2026-10-29 17:59: a lab run patched the real shadPS4 under its own app folder, so the owner's record held an
    older sha and the app said "Patched, with 1 problem". A file that is exactly this Overtime's own is taken over;
    anything else stays a problem."""
    emu = str(world['emu'])
    old = xmlpatch.build('ot.puckpeak.com', 'https://91.98.195.150/')
    gamesetup.install(emu, old, running=lambda: False)
    patch_file = world['user'] / 'patches' / 'Overtime' / 'overtime.xml'
    mine = old.replace('91.98.195.150', '91.98.195.151')       # another text of the same kind, now on disk
    patch_file.write_bytes(mine.encode('utf-8'))
    assert gamesetup.status(emu)['problems'] and not gamesetup.adopt((old.replace('150', '152'),))    # not ours: kept
    assert gamesetup.status(emu)['problems']
    assert gamesetup.adopt((mine, old)) is True
    st = gamesetup.status(emu)
    assert st['intact'] and not st['problems']
    assert gamesetup.adopt((mine,)) is False                    # nothing left to change
    patch_file.write_bytes(b'hand edited')
    assert gamesetup.adopt((mine, old)) is False and gamesetup.status(emu)['problems']
    gamesetup.remove(running=lambda: False)


def test_adopt_patch_notes_the_version_too(world):
    import types
    from overtime_roster import VERSION
    from overtime_roster.app import patch_ctl
    emu = str(world['emu'])
    xml = xmlpatch.build('ot.puckpeak.com', 'https://91.98.195.150/')
    gamesetup.install(emu, xml + ' ', running=lambda: False)           # recorded under another text...
    (world['user'] / 'patches' / 'Overtime' / 'overtime.xml').write_bytes(xmlpatch.expansion32_off(xml).encode('utf-8'))
    prefs, logs = {}, []
    setup = types.SimpleNamespace(_xml=lambda: xml, ctl=types.SimpleNamespace(
        prefs=prefs, remember=prefs.update, host=types.SimpleNamespace(log=logs.append)))
    patch_ctl.adopt_patch(setup)                                        # ...and on disk the 31-team variant of ours
    assert prefs == {'patched_by': VERSION} and len(logs) == 1 and gamesetup.status(emu)['intact']
    patch_ctl.adopt_patch(setup)                                        # nothing more to adopt: quiet
    assert len(logs) == 1
    gamesetup.remove(running=lambda: False)


def test_existing_custom_config_restored_byte_exact(world):
    path = world['user'] / 'custom_configs' / 'CUSA11126.json'
    raw = b'{\n  "General": {"connected_to_network": false, "volume_slider": 50}\n}\n'
    path.write_bytes(raw)
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    assert json.loads(path.read_text())['General'] == {'connected_to_network': True, 'volume_slider': 50,
                                                       'shad_net_enabled': True}
    gamesetup.remove(running=lambda: False)
    assert path.read_bytes() == raw


def test_changed_custom_config_gets_only_our_keys_back(world):
    path = world['user'] / 'custom_configs' / 'CUSA11126.json'
    path.write_text(json.dumps({'General': {'connected_to_network': False, 'volume_slider': 50}}))
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    cfg = json.loads(path.read_text())
    cfg['General']['volume_slider'] = 80  # the user changes a setting while patched: the patch stays intact
    path.write_text(json.dumps(cfg))
    st = gamesetup.status(str(world['emu']))
    assert st['installed'] and st['intact'], st['problems']
    cfg['General']['shad_net_enabled'] = False      # one of our keys off: said, Play puts it back (patch_ctl)
    path.write_text(json.dumps(cfg))
    st = gamesetup.status(str(world['emu']))
    assert not st['intact'] and st['problems'] == [f'network switched off: {path}']
    cfg['General']['shad_net_enabled'] = True
    path.write_text(json.dumps(cfg))
    gamesetup.remove(running=lambda: False)
    assert json.loads(path.read_text())['General'] == {'connected_to_network': False, 'volume_slider': 80}


def test_failed_install_is_still_undone(world, monkeypatch):
    before = _tree(world['user'])
    real = gamesetup._write

    def failing(path, data):
        if path.endswith('CUSA11126.json'):
            raise OSError('disk full')
        real(path, data)
    monkeypatch.setattr(gamesetup, '_write', failing)
    with pytest.raises(OSError):
        gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    m = gamesetup.load_manifest()
    assert m and len(m['files']) == 3  # the patch files and the config are on record
    monkeypatch.setattr(gamesetup, '_write', real)
    gamesetup.remove(running=lambda: False)
    assert _tree(world['user']) == before and gamesetup.load_manifest() is None


def test_bad_config_refused_before_any_write(world):
    path = world['user'] / 'custom_configs' / 'CUSA11126.json'
    for raw in (b'{not json', b'[1, 2]', b'{"General": 5}'):
        path.write_bytes(raw)
        with pytest.raises(gamesetup.SetupError):
            gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
        assert not (world['user'] / 'patches').exists() and gamesetup.load_manifest() is None
        assert path.read_bytes() == raw


def test_leftovers_in_our_folder_are_not_backed_up(world):
    folder = world['user'] / 'patches' / 'Overtime'
    folder.mkdir(parents=True)
    (folder / 'overtime.xml').write_text('<Patch/>')  # an install that never saved its manifest
    m = gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    assert all(e['action'] == 'created' and 'backup' not in e for e in m['files'] if 'patches' in e['path'])
    gamesetup.remove(running=lambda: False)
    assert not folder.exists()


def test_repatch_after_user_edit_keeps_the_edit(world):
    path = world['user'] / 'custom_configs' / 'CUSA11126.json'
    path.write_text(json.dumps({'General': {'connected_to_network': False, 'volume_slider': 50}}))
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    cfg = json.loads(path.read_text())
    cfg['General']['volume_slider'] = 80
    path.write_text(json.dumps(cfg))
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)  # "Patch again"
    gamesetup.remove(running=lambda: False)
    assert json.loads(path.read_text())['General'] == {'connected_to_network': False, 'volume_slider': 80}


def test_created_config_changed_by_user_gets_our_keys_back(world):
    path = world['user'] / 'custom_configs' / 'CUSA11126.json'
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)  # creates it
    cfg = json.loads(path.read_text())
    cfg['General']['volume_slider'] = 80
    path.write_text(json.dumps(cfg))
    gamesetup.remove(running=lambda: False)
    general = json.loads(path.read_text())['General']
    assert general['volume_slider'] == 80  # the user's edit stays
    assert general['connected_to_network'] is False and 'shad_net_enabled' not in general  # ours go back


def test_config_already_right_is_not_touched(world):
    path = world['user'] / 'custom_configs' / 'CUSA11126.json'
    raw = json.dumps({'General': dict(gamesetup.NETWORK)}).encode()
    path.write_bytes(raw)
    m = gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    assert path.as_posix() not in [p.replace('\\', '/') for p in (e['path'] for e in m['files'])]
    assert path.read_bytes() == raw


def test_refusals(world):
    with pytest.raises(gamesetup.SetupError):
        gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: True)
    with pytest.raises(xmlpatch.PatchError):
        gamesetup.install(str(world['emu']), 'not a patch', running=lambda: False)
    stranger = world['user'] / 'patches' / 'Overtime'
    stranger.mkdir(parents=True)
    (stranger / 'someone_else.xml').write_text('<Patch/>')
    with pytest.raises(gamesetup.SetupError):
        gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    assert not (world['user'] / 'custom_configs' / 'CUSA11126.json').exists()


def test_snapshot_and_compare(world):
    snap = gamesetup.snapshot(str(world['game']))
    assert snap['files']['eboot.bin'][1] and snap['files'][os.path.join('databigs', 'game_60.big')][1] is None
    full = gamesetup.snapshot(str(world['game']), full=True)
    assert gamesetup.compare(snap, full) == []
    (world['game'] / 'eboot.bin').write_bytes(b'\x7fELF fake eboox')  # same size, other content
    (world['game'] / 'extra.txt').write_text('x')
    assert gamesetup.compare(full, gamesetup.snapshot(str(world['game']), full=True)) == [
        ('eboot.bin', 'content'), ('extra.txt', 'added')]


def test_copy_game(world):
    dst = world['tmp'] / 'copy' / 'NHL 19'
    gamesetup.copy_game(str(world['game']), str(dst))
    assert _tree(dst) == _tree(world['game'])
    with pytest.raises(gamesetup.SetupError):
        gamesetup.copy_game(str(world['game']), str(dst))  # not empty
    with pytest.raises(gamesetup.SetupError):
        gamesetup.copy_game(str(world['game']), str(world['game'] / 'inside'))
    with pytest.raises(gamesetup.SetupError):
        gamesetup.copy_game(str(world['game']), str(world['tmp'] / 'other'), margin=1 << 60)


def test_launch_command_and_refusals(world):
    calls = []
    proc = launch.start(str(world['emu']), str(world['game']), running=lambda: False,
                        popen=lambda cmd, **kw: calls.append((cmd, kw)) or 'proc')
    assert proc == 'proc'
    cmd, kw = calls[0]
    assert cmd == [str(world['emu']), '-g', str(world['game'] / 'eboot.bin')]
    assert kw['cwd'] == str(world['emu'].parent)
    assert launch.command(str(world['emu']), str(world['game']), 'p.xml')[-2] == '-p'
    with pytest.raises(launch.LaunchError):
        launch.start(str(world['emu']), str(world['game']), running=lambda: True, popen=None)
    bad = _game(world['tmp'], 'Other', title_id='CUSA00001')
    with pytest.raises(launch.LaunchError):
        launch.start(str(world['emu']), str(bad), running=lambda: False, popen=None)


def test_read_log():
    text = ('[Loader] <Info> memory_patcher.cpp:1 PatchMemory: Applied patch: Nucleus hosts: localhost, '
            'Offset: 0x526e089, Value: 6874\n'
            '[Loader] <Info> memory_patcher.cpp:1 PatchMemory: Applied patch: Nucleus hosts: localhost, '
            'Offset: 0x526e0a2, Value: 6874\n'
            '[Lib.NpManager] <Info> np.cpp:1 x: hello\n')
    assert launch.read_log(text) == {'patches': {'Nucleus hosts: localhost': 2}, 'shadnet': True, 'crash': None}
    assert launch.read_log('[Lib.Np] no users connected to shadNet')['shadnet'] is False
    assert launch.read_log('')['shadnet'] is None


# --- what Setup reads of shadPS4: its last log, its build, the Overtime server (2026-10-21) ------------------------
def test_shadnet_log_says_how_the_last_run_signed_in(world):
    assert gamesetup.shadnet_log(str(world['user'])) is None                     # no log yet
    log = world['user'] / 'log'
    log.mkdir()
    cases = [(b"[Lib.Np] ConnectUser: user_id=1000 signed in npid='skater'\n", ('signed_in', 'skater', None)),
             (b'[Lib.Np] Login rejected error code 8\n', ('rejected', '', 8)),
             (b'[Lib.Np] no users connected to shadNet\n', ('signed_out', '', None)),
             (b'[Core] Starting shadps4 emulator\n', (None, '', None))]
    for text, (state, npid, code) in cases:
        (log / 'shad_log.txt').write_bytes(b'[Core] start\n' + text)
        out = gamesetup.shadnet_log(str(world['user']))
        assert (out['state'], out['npid'], out['code']) == (state, npid, code) and out['when'] > 0
        assert out['account'] is None
    (log / 'shad_log.txt').write_bytes(b"[Lib.Np] ConnectUser: user_id=1000 signed in npid='skater' accountId=16349\n")
    out = gamesetup.shadnet_log(str(world['user']))
    assert (out['npid'], out['account']) == ('skater', 16349)


def _header(branch='NHL19-Build', own='true', net='true', shadnet='true', extra=''):
    """The top of a real shad_log.txt (cut down): the build, the settings, the game."""
    return (f'[Loader] <Info> emulator.cpp:468 Run: Branch {branch}\n'
            f'[Config] <Info> emulator.cpp:473 Run: Game-specific config used: {own}\n'
            f'[Config] <Info> emulator.cpp:477 Run: General isConnectedToNetwork: {net}\n'
            f'[Config] <Info> emulator.cpp:478 Run: General isShadNetEnabled: {shadnet}\n' + extra).encode()


def test_shadnet_why_names_the_reason(world):
    """Player report 2026-10-29: "ShadNet id not found yet" with no reason; each cause of a missing id says its own."""
    user = str(world['user'])
    (world['user'] / 'log').mkdir()
    put = lambda raw: (world['user'] / 'log' / 'shad_log.txt').write_bytes(raw)
    assert 'no log yet' in gamesetup.shadnet_why(gamesetup.shadnet_log(user))
    off = b'[NpHandler] np_handler.cpp:138 Initialize: shadNet disabled globally we are in offline mode\n'
    put(_header(branch='main', own='false', net='false', shadnet='false', extra=off.decode()))   # the Pre-release build
    log = gamesetup.shadnet_log(user)
    assert (log['branch'], log['own_config'], log['shadnet_on'], log['network_on'], log['disabled_globally']) == (
        'main', False, False, False, True)
    why = gamesetup.shadnet_why(log)
    assert 'ShadNet and the network turned off' in why                              # the build does not matter
    put(_header(own='false', net='false', shadnet='false', extra=off.decode()))
    why = gamesetup.shadnet_why(gamesetup.shadnet_log(user))
    assert 'ShadNet and the network turned off' in why and 'shared ones applied' in why and 'Online card' in why
    put(_header(extra="[Lib.Np] Login rejected error code 8\n"))
    assert 'code 8' in gamesetup.shadnet_why(gamesetup.shadnet_log(user))
    put(_header(extra='[Lib.Np] no users connected to shadNet\n'))
    assert 'nobody was signed in' in gamesetup.shadnet_why(gamesetup.shadnet_log(user))
    put(_header(extra="[Lib.Np] ConnectUser: user_id=1000 signed in npid='skater'\n"))
    assert 'skater' in gamesetup.shadnet_why(gamesetup.shadnet_log(user)) and 'Type the id' in gamesetup.shadnet_why(
        gamesetup.shadnet_log(user))
    put(_header())
    assert 'ended before it signed in' in gamesetup.shadnet_why(gamesetup.shadnet_log(user))
    put(_header(extra="[Lib.Np] ConnectUser: user_id=1000 signed in npid='skater' accountId=16349\n"))
    assert gamesetup.shadnet_why(gamesetup.shadnet_log(user)) == ''


def test_emulator_build_reads_the_version_block(tmp_path):
    exe = tmp_path / 'shadPS4.exe'
    block = (b'0.20.1 WIP\x00' + b'a' * 40 + b'\x00NHL19-Build\x00v0.20.1-12-gabc\x00'
             b'https://github.com/Kravickas/shadPS4\x00')
    exe.write_bytes(b'MZ' + b'\x01' * 5000 + block + b'\x02' * 100)
    assert gamesetup.emulator_build(str(exe)) == {'version': '0.20.1 WIP', 'rev': 'a' * 40, 'branch': 'NHL19-Build',
                                                  'remote': 'https://github.com/Kravickas/shadPS4'}
    (tmp_path / 'plain.exe').write_bytes(b'MZ no version block here')
    assert gamesetup.emulator_build(str(tmp_path / 'plain.exe')) is None
    assert gamesetup.emulator_build(str(tmp_path / 'gone.exe')) is None


def test_server_answers_only_as_the_redirector_does():
    """A local stand-in on 127.0.0.1 (no network): the redirector's answer is ok, anything else is not."""
    import http.server
    import threading
    answers = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length') or 0))
            status, body = answers['now']
            self.send_response(status)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        answers['now'] = (200, b'<serverInstanceInfo><address/></serverInstanceInfo>')
        assert gamesetup.server_answers('127.0.0.1', port, timeout=2, tls=False) == (True, '')
        answers['now'] = (200, b'<html>a web page</html>')
        assert gamesetup.server_answers('127.0.0.1', port, timeout=2, tls=False) == (
            False, 'HTTP 200, not the Overtime server')
        answers['now'] = (404, b'')
        assert gamesetup.server_answers('127.0.0.1', port, timeout=2, tls=False)[0] is False
    finally:
        server.shutdown()
        server.server_close()
    ok, why = gamesetup.server_answers('127.0.0.1', port, timeout=1, tls=False)       # nobody listens now
    assert not ok and why


def test_trash_moves_only_roster_saves(tmp_path, monkeypatch):
    from overtime_roster.app import trash
    saves = tmp_path / 'saves'
    (saves / 'RosterCustom3').mkdir(parents=True)
    (saves / 'Profile0').mkdir()
    (tmp_path / 'RosterCustom9').mkdir()
    for path, why in ((saves / 'Profile0', 'not a roster save'), (tmp_path / 'RosterCustom9', 'in your saves folder'),
                      (saves / 'RosterCustom7', 'not there any more')):
        with pytest.raises(trash.TrashError, match=why):
            trash.check(str(path), str(saves))
    asked = []

    def shell_delete(op):                       # what Windows does with FOF_ALLOWUNDO: the folder goes
        asked.append((op.wFunc, op.pFrom, op.fFlags))
        import shutil
        shutil.rmtree(op.pFrom.rstrip('\0'))
        return 0
    monkeypatch.setattr(trash, '_shell_delete', shell_delete)
    monkeypatch.setattr(trash.sys, 'platform', 'win32')
    assert trash.recycle(str(saves / 'RosterCustom3'), str(saves)) == str(saves / 'RosterCustom3')
    assert asked == [(trash.FO_DELETE, str(saves / 'RosterCustom3'), trash.FLAGS)]    # (ctypes reads up to the NUL)
    assert trash.FLAGS & trash.FOF_ALLOWUNDO and not (saves / 'RosterCustom3').exists()
    (saves / 'RosterCustom4').mkdir()
    monkeypatch.setattr(trash, '_shell_delete', lambda op: 5)       # Windows refused: the folder stays
    with pytest.raises(trash.TrashError, match='could not move RosterCustom4'):
        trash.recycle(str(saves / 'RosterCustom4'), str(saves))
    assert (saves / 'RosterCustom4').is_dir()


def test_other_disc_cusa11116_is_the_same_game(world, monkeypatch):
    """CUSA11116 is read as NHL 19; its id names the save folder, the custom config and the save's param.sfo."""
    from overtime_roster.app import paths, savegame
    monkeypatch.setattr(gamesetup, '_active', ['CUSA11126'])
    monkeypatch.delenv('OVERTIME_SAVE_DIR')
    other = _game(world['tmp'] / 'Other', title_id='CUSA11116')
    assert gamesetup.read_game(str(other))['ok']
    assert [g['title_id'] for g in gamesetup.find_games(str(world['user']))] == ['CUSA11126']
    assert gamesetup.use_game(str(world['game'])) == 'CUSA11126'
    assert gamesetup.use_game(str(other)) == 'CUSA11116'
    assert gamesetup.save_dir(str(world['user'])).endswith('CUSA11116')
    assert gamesetup.custom_config_path(str(world['user'])).endswith('CUSA11116.json')
    assert paths.default_save_dir('CUSA11116').endswith('CUSA11116')
    entries = {e.key: e.value for e in sfo.parse(savegame.default_sfo('SAVE0', title='CUSA11116'))}
    assert entries['TITLE_ID'] == 'CUSA11116'
    # a folder that is not NHL 19 changes nothing
    assert gamesetup.use_game(str(_game(world['tmp'] / 'Third', title_id='CUSA00001'))) == 'CUSA11116'


def _launcher(tmp_path, monkeypatch, selected=True):
    """A QtLauncher as it lies on a PC: its data in %APPDATA%, the selected version with Qt's doubled backslash."""
    monkeypatch.setenv('APPDATA', str(tmp_path / 'roaming'))
    data = tmp_path / 'roaming' / 'shadPS4QtLauncher'
    for name in ('v0.19.0', 'Pre-release'):
        (data / 'versions' / name).mkdir(parents=True)
        (data / 'versions' / name / 'shadPS4.exe').write_bytes(b'MZ')
    ini = '[version_manager]\n'
    if selected:
        ini += f"versionSelected={(data / 'versions').as_posix()}/Pre-release\\\\shadPS4.exe\n"
    (data / 'qt_ui.ini').write_text(ini, encoding='utf-8')
    folder = tmp_path / 'PS4 Emulator'
    folder.mkdir()
    (folder / 'shadPS4QtLauncher.exe').write_bytes(b'MZ')
    return data / 'versions' / 'Pre-release' / 'shadPS4.exe', folder


def test_the_launcher_or_its_folder_leads_to_the_selected_shadps4(tmp_path, monkeypatch):
    exe, folder = _launcher(tmp_path, monkeypatch)
    assert os.path.samefile(gamesetup.launcher_emulators()[0], exe)
    assert os.path.samefile(gamesetup.resolve_emulator(str(folder)), exe)
    assert os.path.samefile(gamesetup.resolve_emulator(str(folder / 'shadPS4QtLauncher.exe')), exe)
    assert os.path.samefile(gamesetup.find_emulators()[0], exe)     # the app finds it with no pick at all


def test_a_launcher_with_nothing_selected_takes_a_version_it_has(tmp_path, monkeypatch):
    exe, folder = _launcher(tmp_path, monkeypatch, selected=False)
    assert os.path.basename(gamesetup.resolve_emulator(str(folder))) == 'shadPS4.exe'


def test_a_folder_or_any_shadps4_exe_is_taken(tmp_path, monkeypatch):
    monkeypatch.setenv('APPDATA', str(tmp_path / 'roaming'))
    (tmp_path / 'emu' / 'inner').mkdir(parents=True)
    exe = tmp_path / 'emu' / 'inner' / 'shadPS419.exe'
    exe.write_bytes(b'MZ')
    assert gamesetup.resolve_emulator(str(tmp_path / 'emu')) == str(exe)
    assert gamesetup.resolve_emulator(str(exe)) == str(exe)
    other = tmp_path / 'emu' / 'notes.exe'
    other.write_bytes(b'MZ no version block here')
    assert gamesetup.resolve_emulator(str(other)) == ''
    assert gamesetup.resolve_emulator(str(tmp_path / 'gone')) == ''
    empty = tmp_path / 'empty'
    empty.mkdir()
    assert gamesetup.resolve_emulator(str(empty)) == ''


def test_a_launcher_with_no_version_is_not_taken(tmp_path, monkeypatch):
    monkeypatch.setenv('APPDATA', str(tmp_path / 'roaming'))
    (tmp_path / 'emu').mkdir()
    (tmp_path / 'emu' / 'shadPS4QtLauncher.exe').write_bytes(b'MZ')
    assert gamesetup.resolve_emulator(str(tmp_path / 'emu')) == ''
    assert gamesetup.resolve_emulator(str(tmp_path / 'emu' / 'shadPS4QtLauncher.exe')) == ''


def test_network_section_of_a_newer_shadps4_is_switched_too(world):
    """Newer shadPS4 builds read connected_to_network from "Network" before "General": a custom config (or the
    config.json copy it starts as) with that section kept the game OFFLINE although "General" said on (tester log)."""
    path = world['user'] / 'custom_configs' / 'CUSA11126.json'
    raw = json.dumps({'General': {'volume_slider': 50},
                      'Network': {'connected_to_network': False, 'shad_net_enabled': True, 'upnp': 1}}).encode()
    path.write_bytes(raw)
    assert not gamesetup.network_on(str(world['user']))
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    cfg = json.loads(path.read_text())
    assert cfg['Network'] == {'connected_to_network': True, 'shad_net_enabled': True, 'upnp': 1}
    assert cfg['General']['connected_to_network'] is True
    assert gamesetup.network_on(str(world['user']))
    st = gamesetup.status(str(world['emu']))
    assert st['intact'], st['problems']
    cfg['Network']['connected_to_network'] = False      # switched off in the launcher afterwards: said
    path.write_text(json.dumps(cfg))
    assert gamesetup.status(str(world['emu']))['problems'] == [f'network switched off: {path}']
    cfg['Network']['connected_to_network'] = True
    path.write_text(json.dumps(cfg))
    gamesetup.remove(running=lambda: False)
    assert json.loads(path.read_text())['Network'] == {'connected_to_network': False, 'shad_net_enabled': True,
                                                       'upnp': 1}


def test_config_json_copy_with_network_section(world):
    cfg_path = world['user'] / 'config.json'
    cfg = json.loads(cfg_path.read_text())
    cfg['Network'] = {'connected_to_network': False, 'shad_net_enabled': False}
    cfg_path.write_text(json.dumps(cfg))
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    assert gamesetup.network_on(str(world['user']))
    made = json.loads((world['user'] / 'custom_configs' / 'CUSA11126.json').read_text())
    assert made['Network'] == {'connected_to_network': True, 'shad_net_enabled': True}
