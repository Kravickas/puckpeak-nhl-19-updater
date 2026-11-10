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


def test_update_without_the_base_game_is_refused(tmp_path):
    """A tester's "art layer: ...hutcardheritage/t1.gnf: neither the texture nor its folder is in the game": the folder
    held only the update's patch_*.big, so the base game's inxp_10.big was never seen. Said at the scan, not mid-patch."""
    g = _game(tmp_path)
    (g / 'databigs' / 'game_60.big').unlink()
    (g / 'databigs' / 'patch_inxp_56.big').write_bytes(b'x')
    info = gamesetup.read_game(str(g))
    assert not info['ok'] and 'update files' in info['problem'] and 'inxp_10.big' in info['problem']


def test_base_with_its_update_beside_it_is_fine(tmp_path):
    base = _game(tmp_path, 'CUSA11126', app_ver='01.00')
    upd = _game(tmp_path, 'CUSA11126-UPDATE')
    (upd / 'databigs' / 'game_60.big').unlink()
    (upd / 'databigs' / 'patch_inxp_56.big').write_bytes(b'x')
    assert gamesetup.read_game(str(base))['ok'] and gamesetup.read_game(str(upd))['ok']


def test_shadps4_is_found_beside_the_game_picked(tmp_path, monkeypatch):
    """Nothing in %APPDATA% (a tester: "search from the folder i point to"): shadPS4 next to the game is found."""
    monkeypatch.setenv('APPDATA', str(tmp_path / 'empty'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    emu = tmp_path / 'Emu' / 'shadPS4' / 'shadPS4.exe'
    emu.parent.mkdir(parents=True)
    emu.write_bytes(b'MZ')
    game = _game(tmp_path / 'Emu', 'NHL 19')
    assert gamesetup.find_emulators() == []
    assert gamesetup.find_emulators(near=gamesetup.around(str(game))) == [str(emu)]


def test_a_testers_portable_layout(tmp_path, monkeypatch):
    """A tester's setup (2026-11-07 screenshot of shadPS4's Paths tab): V:\\ShadPS4\\shadPS4.exe, its data in
    V:\\ShadPS4\\user, games in V:\\ShadPS4\\game installs\\<game>, saves in a Home Folder set there, %APPDATA% empty."""
    monkeypatch.setenv('APPDATA', str(tmp_path / 'empty'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    root = tmp_path / 'V' / 'ShadPS4'
    (root / 'user').mkdir(parents=True)
    emu = root / 'shadPS4.exe'
    emu.write_bytes(b'MZ')
    game = _game(root / 'game installs', 'CUSA11126')
    cfg = {'General': {'install_dirs': [{'enabled': True, 'path': str(root / 'game installs')}],
                       'home_dir': str(root / 'user' / 'home')}}
    (root / 'user' / 'config.json').write_text(json.dumps(cfg), encoding='utf-8')
    assert gamesetup.find_emulators(near=gamesetup.around(str(game), 2)) == [str(emu)]    # Find game at eboot.bin
    user = gamesetup.emu_user_dir(str(emu))
    assert user == str(root / 'user')
    assert [g['path'] for g in gamesetup.find_games(user)] == [str(game)] and gamesetup.find_games(user)[0]['ok']
    assert gamesetup.save_dir(user) == str(root / 'user' / 'home' / '1000' / 'savedata' / 'CUSA11126')


def test_game_is_found_beside_a_portable_shadps4(tmp_path, monkeypatch):
    monkeypatch.setenv('APPDATA', str(tmp_path / 'empty'))
    emu = tmp_path / 'Emu' / 'shadPS4' / 'shadPS4.exe'
    (emu.parent / 'user').mkdir(parents=True)          # portable, its config lists no game folder
    emu.write_bytes(b'MZ')
    game = _game(tmp_path / 'Emu', 'NHL 19')
    user = gamesetup.emu_user_dir(str(emu))
    assert gamesetup.find_games(user) == []
    assert [g['path'] for g in gamesetup.find_games(user, extra=gamesetup.around(str(emu)))] == [str(game)]


def test_saves_follow_shadps4s_home_folder_setting(world, tmp_path):
    user = str(world['user'])
    assert gamesetup.save_dir(user) == os.path.join(user, 'home', '1000', 'savedata', 'CUSA11126')
    cfg = json.loads((world['user'] / 'config.json').read_text())
    cfg['General']['home_dir'] = str(tmp_path / 'V' / 'home')       # Paths tab, Home Folder Location
    (world['user'] / 'config.json').write_text(json.dumps(cfg), encoding='utf-8')
    assert gamesetup.save_dir(user) == str(tmp_path / 'V' / 'home' / '1000' / 'savedata' / 'CUSA11126')


def test_shadnet_secrets_never_read_out(world):
    users = gamesetup.shadnet_users(str(world['user']))
    assert users == [{'user_id': 1000, 'name': 'shadPS4', 'shadnet': True, 'npid': 'skater',
                      'password': True}]
    assert 'hunter2' not in repr(users) and 'tok' not in repr(users) and 'a@b.c' not in repr(users)


def test_emulator_files_with_a_byte_order_mark_are_read(world):
    # PowerShell and older Notepad save UTF-8 with a BOM; shadPS4 reads such files, so Overtime must too
    plain = gamesetup.network_settings(str(world['user']))
    assert any(v is not None for v in plain.values())
    for name in ('users.json', 'config.json'):
        path = world['user'] / name
        path.write_text(path.read_text(encoding='utf-8'), encoding='utf-8-sig')
    assert [u['npid'] for u in gamesetup.shadnet_users(str(world['user']))] == ['skater']
    assert gamesetup.network_settings(str(world['user'])) == plain


def test_install_and_remove_leave_nothing_behind(world):
    before = _tree(world['user'])
    text = xmlpatch.build('ot.puckpeak.com', 'https://91.98.195.150/')
    m = gamesetup.install(str(world['emu']), text, running=lambda: False)
    folder = world['user'] / 'patches' / 'Overtime'
    assert (folder / 'overtime.xml').read_bytes() == text.encode('utf-8')
    assert json.loads((folder / 'files.json').read_text()) == {'overtime.xml': ['CUSA11126']}
    cfg = json.loads((world['user'] / 'custom_configs' / 'CUSA11126.json').read_text())
    assert cfg['General']['connected_to_network'] is True and cfg['General']['shad_net_enabled'] is True
    # a new per-game config starts from the global one; readbacks Precise and readback linear images on for everyone,
    # fullscreen borderless by default (owner 2026-11-10)
    assert cfg['GPU'] == {'full_screen': True, 'full_screen_mode': 'Fullscreen (Borderless)', 'readbacks_mode': 2,
                          'readback_linear_images_enabled': True}
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
    back = json.loads(path.read_text())
    assert back['General'] == {'connected_to_network': False, 'volume_slider': 80} and 'Network' not in back


def test_install_writes_the_network_section_too_and_remove_puts_it_back(world):
    """Live 2026-11-07: the launcher's game-specific Network tab was blank with the keys in "General" only."""
    path = world['user'] / 'custom_configs' / 'CUSA11126.json'
    path.write_text(json.dumps({'General': dict(gamesetup.NETWORK), 'Network': {'enable_upnp': True,
                                                                                'shad_net_enabled': False}}))
    assert not gamesetup.network_written(str(world['user']))
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    cfg = json.loads(path.read_text())
    assert cfg['Network'] == {'enable_upnp': True, **gamesetup.NETWORK, **gamesetup.SERVERS}
    assert gamesetup.network_written(str(world['user']))
    cfg['General']['volume_slider'] = 70                # the user's own edit: remove() then puts back only our keys
    path.write_text(json.dumps(cfg))
    gamesetup.remove(running=lambda: False)
    assert json.loads(path.read_text())['Network'] == {'enable_upnp': True, 'shad_net_enabled': False}


def test_empty_servers_are_filled_from_the_shared_config(world):
    """Live 2026-11-07: the tester's game-specific Network tab had empty servers until he typed them."""
    (world['user'] / 'config.json').write_text(json.dumps({'Network': {'shadnet_server': 'my.host:1',
                                                                       'shadnet_webapi_server': ''}}))
    path = world['user'] / 'custom_configs' / 'CUSA11126.json'
    path.write_text(json.dumps({'General': {}, 'Network': {'shadnet_server': '', 'p2p_port': 3658}}))
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    net = json.loads(path.read_text())['Network']
    assert net['shadnet_server'] == 'my.host:1' and net['p2p_port'] == 3658
    assert net['shadnet_webapi_server'] == gamesetup.SERVERS['shadnet_webapi_server']


def test_a_key_off_in_the_network_section_is_a_problem(world):
    path = world['user'] / 'custom_configs' / 'CUSA11126.json'
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    cfg = json.loads(path.read_text())
    cfg['Network']['connected_to_network'] = False      # the launcher saved its blank tab
    path.write_text(json.dumps(cfg))
    assert gamesetup.status(str(world['emu']))['problems'] == [f'network switched off: {path}']
    assert not gamesetup.network_written(str(world['user']))


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
    back = json.loads(path.read_text())
    assert back['General'] == {'connected_to_network': False, 'volume_slider': 80} and 'Network' not in back


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
    raw = json.dumps({'General': dict(gamesetup.NETWORK),
                      'Network': dict(gamesetup.NETWORK, **gamesetup.SERVERS),
                      'GPU': gamesetup.gpu_wanted()}).encode()
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


def _cwd_of_play(world):
    calls = []
    launch.start(str(world['emu']), str(world['game']), running=lambda: False,
                 popen=lambda cmd, **kw: calls.append(kw) or 'proc')
    return calls[0]['cwd']


def test_play_starts_where_shadps4_finds_the_data_folder(world, tmp_path):
    """shadPS4 reads `user` inside the folder it starts from (lab 2026-11-07), so Play starts from that folder's parent:
    a tester's QtLauncher layout (data V/ShadPS4/user, exe deeper) ran on fresh %APPDATA% data from the exe's folder."""
    emu_dir = str(world['emu'].parent)
    assert gamesetup.start_dir(str(world['emu'])) == emu_dir == _cwd_of_play(world)          # %APPDATA%: exe folder
    (world['emu'].parent / 'user').mkdir()                                                # portable beside the exe
    assert _cwd_of_play(world) == emu_dir
    shared = tmp_path / 'V' / 'ShadPS4' / 'user'
    shared.mkdir(parents=True)
    gamesetup.set_custom_data(str(shared))
    try:
        assert _cwd_of_play(world) == str(shared.parent)                                  # QtLauncher's shared folder
        gamesetup.set_custom_data(str(world['user']))                                     # %APPDATA% by hand, though a
        assert _cwd_of_play(world) == str(world['user'])                                  # user\ sits beside the exe
        gamesetup.set_custom_data(str(tmp_path / 'V' / 'data'))                           # never reachable
        assert gamesetup.start_dir(str(world['emu'])) is None
        with pytest.raises(launch.LaunchError, match='cannot use the data folder'):
            _cwd_of_play(world)
    finally:
        gamesetup.set_custom_data('')


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
    assert 'skater' in gamesetup.shadnet_why(gamesetup.shadnet_log(user)) and 'NHL 19 build' in gamesetup.shadnet_why(
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


def test_save_dir_follows_player_one(tmp_path):
    """Saves are where the user NHL 19 plays as keeps them: users.json's player 1, else 1000."""
    import json
    user = tmp_path / 'shadPS4'
    user.mkdir()
    assert gamesetup.save_dir(str(user)) == str(user / 'home' / '1000' / 'savedata' / gamesetup.active_title())
    rows = [{'user_id': 1000, 'player_index': 2}, {'user_id': 1001, 'player_index': 1}]
    (user / 'users.json').write_text(json.dumps({'Users': {'user': rows}}), encoding='utf-8')
    assert gamesetup.save_dir(str(user)) == str(user / 'home' / '1001' / 'savedata' / gamesetup.active_title())
    assert gamesetup.save_dir(str(user), 1000).startswith(str(user / 'home' / '1000'))


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


def _versioninfo(game, region, online='NHL19_1.60'):
    cfg = game / 'nhl' / 'data' / 'kettle' / 'config'
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / f'{region}_versioninfo.ini').write_text(
        '; skuVersion is the game\'s current version\nskuVersion=1.60\n\n; onlineVersion is used to segregate users\n'
        f'onlineVersion={online}\n')


def test_online_version_reads_the_region_file_the_game_reads(tmp_path):
    """docs/notes/crossplay.md: the game takes the first of ww_, na_, eu_versioninfo.ini; NA and EU say NHL19_1.60."""
    na = _game(tmp_path / 'NA')
    assert gamesetup.online_version(str(na)) == ('?', '?')
    _versioninfo(na, 'na')
    assert gamesetup.online_version(str(na)) == ('na', 'NHL19_1.60')
    eu = _game(tmp_path / 'EU', title_id='CUSA11116')
    _versioninfo(eu, 'eu')
    assert gamesetup.online_version(str(eu)) == ('eu', 'NHL19_1.60')
    _versioninfo(eu, 'ww', 'NHL19_WW')                     # ww wins over the others, as in the game
    assert gamesetup.online_version(str(eu)) == ('ww', 'NHL19_WW')
    odd = _game(tmp_path / 'Odd')
    _versioninfo(odd, 'na', 'NHL 19 / 1.60')                # a value the lobby would refuse is sent as unknown
    assert gamesetup.online_version(str(odd)) == ('na', '?')


def test_online_version_takes_the_update_folder_over_the_base(tmp_path):
    base = _game(tmp_path, 'CUSA11116')
    update = _game(tmp_path, 'CUSA11116-UPDATE', title_id='CUSA11116')
    _versioninfo(base, 'eu', 'NHL19_1.00')
    assert gamesetup.online_version(str(base)) == ('eu', 'NHL19_1.00')
    _versioninfo(update, 'eu')
    assert gamesetup.online_version(str(base)) == ('eu', 'NHL19_1.60')


def test_game_identity_says_region_and_online_version(tmp_path):
    eu = _game(tmp_path / 'EU', title_id='CUSA11116')
    _versioninfo(eu, 'eu')
    got = gamesetup.game_identity(str(eu))
    assert (got['title'], got['region'], got['online']) == ('CUSA11116', 'eu', 'NHL19_1.60')
    lobby = pytest.importorskip('overtime_server.lobby')    # not in the public tree
    assert lobby._game(got) == got                          # every field is one the lobby takes


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
    assert cfg['Network'] == {'connected_to_network': True, 'shad_net_enabled': True, 'upnp': 1, **gamesetup.SERVERS}
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
    assert made['Network'] == {'connected_to_network': True, 'shad_net_enabled': True, **gamesetup.SERVERS}


def test_1440p_sets_additional_dmem_and_1080p_or_remove_puts_the_players_own_back(world):
    path = world['user'] / 'custom_configs' / 'CUSA11126.json'
    path.write_text(json.dumps({'General': {'extra_dmem_in_mbytes': 512}}))
    emu, base = str(world['emu']), xmlpatch.build('localhost')
    hi = xmlpatch.with_resolution(base, 1440)

    def dmem():
        return json.loads(path.read_text())['General'].get('extra_dmem_in_mbytes')
    gamesetup.install(emu, base, running=lambda: False)
    assert dmem() == 512                                    # 1080p: not touched
    gamesetup.install(emu, hi, running=lambda: False)
    assert dmem() == gamesetup.DMEM_1440
    gamesetup.install(emu, base, running=lambda: False)
    assert dmem() == 512                                    # back to 1080p: the player's own value
    gamesetup.install(emu, xmlpatch.with_resolution(base, 720), running=lambda: False)
    assert dmem() == 512                                    # 720p: below the stock size, no DMem needed
    gamesetup.install(emu, hi, running=lambda: False)
    gamesetup.install(emu, xmlpatch.with_resolution(base, 720), running=lambda: False)
    assert dmem() == 512                                    # 1440p -> 720p: the player's own value again
    gamesetup.install(emu, hi, running=lambda: False)
    gamesetup.remove(running=lambda: False)
    assert dmem() == 512


def test_1440p_keeps_a_bigger_dmem_and_a_first_install_at_1440p_is_undone(world):
    path = world['user'] / 'custom_configs' / 'CUSA11126.json'
    path.write_text(json.dumps({'General': {'extra_dmem_in_mbytes': 6000}}))
    hi = xmlpatch.with_resolution(xmlpatch.build('localhost'), 1440)
    gamesetup.install(str(world['emu']), hi, running=lambda: False)
    assert json.loads(path.read_text())['General']['extra_dmem_in_mbytes'] == 6000
    path.write_text(json.dumps({'General': {}}))
    gamesetup.remove(running=lambda: False)
    gamesetup.install(str(world['emu']), hi, running=lambda: False)
    assert json.loads(path.read_text())['General']['extra_dmem_in_mbytes'] == gamesetup.DMEM_1440
    gamesetup.remove(running=lambda: False)
    assert 'extra_dmem_in_mbytes' not in json.loads(path.read_text())['General']


@pytest.mark.parametrize('vendor,windows,own,want', [
    ('intel', True, None, True), ('?', True, False, True),
    ('amd', True, None, None), ('amd', True, False, False), ('intel', False, None, None)])
def test_install_turns_shadps4s_amd_math_on_where_the_pc_needs_it(world, monkeypatch, vendor, windows, own, want):
    # 0.81.0: every start (open matchmaking too), not only a lobby match, plays with the AMD math on an Intel PC
    monkeypatch.setattr(gamesetup, 'cpu_vendor', lambda: vendor)
    monkeypatch.setattr(gamesetup, 'WINDOWS', windows)
    path, user = world['user'] / 'custom_configs' / 'CUSA11126.json', str(world['user'])
    path.write_text(json.dumps({'General': {} if own is None else {gamesetup.AMD_MATH_KEY: own}}))
    emu = str(world['emu'])

    def key():
        return json.loads(path.read_text())['General'].get(gamesetup.AMD_MATH_KEY)
    gamesetup.install(emu, xmlpatch.build('localhost'), running=lambda: False)
    assert key() == want and gamesetup.amd_math_on(user)
    gamesetup.install(emu, xmlpatch.build('localhost'), running=lambda: False)    # again: no change
    assert key() == want
    if want and own is None:
        general = json.loads(path.read_text())
        general['General'][gamesetup.AMD_MATH_KEY] = False                         # the launcher switched it off
        path.write_text(json.dumps(general))
        assert not gamesetup.amd_math_on(user)
        gamesetup.install(emu, xmlpatch.build('localhost'), running=lambda: False)
        assert key() is True
    gamesetup.remove(running=lambda: False)
    assert key() == own                                     # the player's own value (or none) comes back


def test_emulator_identity_names_the_build_and_the_frame_timing(tmp_path, monkeypatch):
    # live 2026-11-08: gr4vity ran vblank 9999 Hz; the lobby logs it next to the other player's
    cfg = tmp_path / 'CUSA11126.json'
    cfg.write_text('{"GPU": {"vblank_frequency": 9999}, "General": {"neo_mode": false}}', encoding='utf-8')
    monkeypatch.setattr(gamesetup, 'emulator_build', lambda exe: {'rev': 'b23fb6716c4416cd90e8d9f3487d3572f6dab833',
                                                                  'branch': 'NHL19-Build'})
    monkeypatch.setattr(gamesetup, 'emu_user_dir', lambda exe: str(tmp_path))
    monkeypatch.setattr(gamesetup, 'custom_config_path', lambda user: str(cfg))
    assert gamesetup.emulator_identity('x.exe') == {'emu': 'NHL19-Build.b23fb67', 'timing': 'vblank9999,neo0'}
    monkeypatch.setattr(gamesetup, 'emulator_build', lambda exe: {'rev': 'a' * 40, 'branch': 'feature/x.y'})
    assert gamesetup.emulator_identity('x.exe')['emu'] == 'feature-x-y.aaaaaaa'
    cfg.write_text('not json', encoding='utf-8')
    assert gamesetup.emulator_identity('x.exe')['timing'] == '?'


@pytest.mark.parametrize('name,tag', [
    ('Intel(R) Core(TM) i5-10210U CPU @ 1.60GHz', 'Intel-Core-i5-10210U-CPU-1.60GHz'),
    ('AMD Ryzen 7 9800X3D 8-Core Processor           ', 'AMD-Ryzen-7-9800X3D-8-Core-Processor'),
    ('13th Gen Intel(R) Core(TM) i7-13700K', '13th-Gen-Intel-Core-i7-13700K'),
    ('', '?'), ('(R)(TM)', '?'), ('x' * 70, 'x' * 48)])
def test_the_cpu_tag_fits_the_lobbys_short_text(name, tag):
    import re
    game_text = re.compile(r'[A-Za-z0-9._,+?-]{0,80}')     # overtime_server/lobby.py _GAME_TEXT (not in the public tree)
    got = gamesetup.cpu_tag(name)
    assert got == tag and game_text.fullmatch(got) and len(got) <= 48
    assert re.fullmatch(r'[^\s]*', gamesetup.cpu_tag())       # this PC's, whatever it is: never raises, no spaces


# --- readbacks Precise, readback linear images on, for everyone (owner 2026-11-10, docs/notes/standalone.md) -----------
def _cfg(world):
    return json.loads((world['user'] / 'custom_configs' / 'CUSA11126.json').read_text(encoding='utf-8'))


def test_readbacks_precise_over_the_players_value_and_put_back(world):
    path = world['user'] / 'custom_configs' / 'CUSA11126.json'
    path.write_text(json.dumps({'General': {}, 'GPU': {'readbacks_mode': 1, 'fsr_enabled': True}}), encoding='utf-8')
    assert not gamesetup.readbacks_on(str(world['user']))
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    assert _cfg(world)['GPU'] == {'readbacks_mode': 2, 'fsr_enabled': True, 'readback_linear_images_enabled': True,
                                  'full_screen': True, 'full_screen_mode': 'Fullscreen (Borderless)'}
    assert gamesetup.readbacks_on(str(world['user']))
    # the player switches to Relaxed after the patch: Play's refresh (install again) puts Precise back, and the value
    # kept for Unpatch stays the one from before Overtime
    cfg = _cfg(world)
    cfg['GPU']['readbacks_mode'] = 0
    cfg['GPU']['readback_linear_images_enabled'] = False
    cfg['General']['own_edit'] = 1
    path.write_text(json.dumps(cfg), encoding='utf-8')
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    assert {k: _cfg(world)['GPU'][k] for k in gamesetup.GPU_SETTINGS} == gamesetup.GPU_SETTINGS
    entry = next(e for e in gamesetup.load_manifest()['files'] if e['path'].endswith('CUSA11126.json'))
    assert entry['previous_gpu'] == {'readbacks_mode': 1, 'readback_linear_images_enabled': None, 'full_screen': None,
                                     'full_screen_mode': None}
    gamesetup.remove(running=lambda: False)
    after = _cfg(world)
    assert after['GPU'] == {'readbacks_mode': 1, 'fsr_enabled': True} and after['General']['own_edit'] == 1


def test_readbacks_key_overtime_added_goes_again(world):
    path = world['user'] / 'custom_configs' / 'CUSA11126.json'
    path.write_text(json.dumps({'General': {}}), encoding='utf-8')
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    cfg = _cfg(world)
    cfg['General']['own_edit'] = 1          # changed since: Unpatch puts back only our keys
    path.write_text(json.dumps(cfg), encoding='utf-8')
    gamesetup.remove(running=lambda: False)
    assert 'GPU' not in _cfg(world)


def test_gpu_key_added_later_learns_the_players_value(world):
    """A record from before readback linear images joined GPU_SETTINGS keeps readbacks_mode's first value and learns
    the new key's own value at the next install, so Unpatch puts both back."""
    path = world['user'] / 'custom_configs' / 'CUSA11126.json'
    path.write_text(json.dumps({'General': {}, 'GPU': {'readbacks_mode': 1}}), encoding='utf-8')
    m = gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    entry = next(e for e in m['files'] if e['path'].endswith('CUSA11126.json'))
    entry['previous_gpu'] = {'readbacks_mode': 1}       # what a 0.83.0 dev build recorded
    gamesetup._save_manifest(m)
    cfg = _cfg(world)
    cfg['GPU']['readback_linear_images_enabled'] = False
    path.write_text(json.dumps(cfg), encoding='utf-8')
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    entry = next(e for e in gamesetup.load_manifest()['files'] if e['path'].endswith('CUSA11126.json'))
    learned = {k: entry['previous_gpu'][k] for k in gamesetup.GPU_SETTINGS}
    assert learned == {'readbacks_mode': 1, 'readback_linear_images_enabled': False}
    assert gamesetup.readbacks_on(str(world['user']))


def test_readbacks_switched_back_is_not_a_patch_problem(world):
    """Readbacks are no status() problem: patch_fingerprint forgives only switched-off network keys, and a problem
    would make the lobby see no patch. Play's refresh_network puts Precise back."""
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    cfg = _cfg(world)
    cfg['GPU']['readbacks_mode'] = 0
    (world['user'] / 'custom_configs' / 'CUSA11126.json').write_text(json.dumps(cfg), encoding='utf-8')
    st = gamesetup.status(str(world['emu']))
    assert st['intact'] and not st['problems'] and not gamesetup.readbacks_on(str(world['user']))


# --- a PC that never started shadPS4 (the app set it up) ------------------------------------------------------------
def test_signin_without_users_json_writes_shadps4s_defaults(world):
    (world['user'] / 'users.json').unlink()
    assert gamesetup.shadnet_signin(str(world['user']), 'Skater_2', 's3cret', running=lambda: False) == 'Skater_2'
    doc = json.loads((world['user'] / 'users.json').read_text(encoding='utf-8'))
    users = doc['Users']['user']
    assert doc['Users']['commit_hash'] == '' and [u['user_id'] for u in users] == [1000, 1001, 1002, 1003]
    keys = {'player_index', 'shadnet_email', 'shadnet_enabled', 'shadnet_npid', 'shadnet_password', 'shadnet_token',
            'user_color', 'user_id', 'user_name'}
    assert all(set(u) == keys for u in users)
    one = users[0]
    assert (one['player_index'], one['user_name'], one['shadnet_npid'], one['shadnet_enabled']) == \
        (1, 'shadPS4', 'Skater_2', True)
    assert [u['user_name'] for u in users[1:]] == ['shadPS4-2', 'shadPS4-3', 'shadPS4-4']
    assert not any(u['shadnet_enabled'] for u in users[1:])
    assert gamesetup.shadnet_identity(str(world['user']))['npid'] == 'Skater_2'


def test_signin_into_a_data_folder_not_made_yet(tmp_path):
    user = tmp_path / 'never' / 'shadPS4'
    gamesetup.shadnet_signin(str(user), 'Skater_2', 's3cret', running=lambda: False)
    assert (user / 'users.json').is_file()
