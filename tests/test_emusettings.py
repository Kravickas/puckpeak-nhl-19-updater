"""Game settings (Setup > Boost performance): shadPS4's per-game settings for NHL 19, read and written by emusettings."""
import json
import os

import pytest

from overtime_core import overlay, xmlpatch
from overtime_roster.app import emusettings, gamesetup, matchsetup
from test_gamesetup import world  # noqa: F401  (fixture)

TITLE = 'CUSA11126.json'


@pytest.fixture
def user(tmp_path, monkeypatch):
    u = tmp_path / 'user'
    (u / 'custom_configs').mkdir(parents=True)
    (u / 'config.json').write_text(json.dumps({'GPU': {'present_mode': 'Fifo', 'window_width': 1920},
                                               'General': {'volume_slider': 80}}), encoding='utf-8')
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'apphome'))
    monkeypatch.setattr(gamesetup, 'amd_math_needed', lambda: False)
    monkeypatch.setattr(emusettings, '_gpus', lambda: ['Some GPU'])            # no PowerShell
    monkeypatch.setattr(emusettings, '_audio_endpoints', lambda kind: ['Speakers (Realtek)'])   # no registry
    return u


def _game_file(u):
    return u / 'custom_configs' / TITLE


def _write(u, cfg):
    _game_file(u).write_text(json.dumps(cfg), encoding='utf-8')


def _read(u):
    return json.loads(_game_file(u).read_text(encoding='utf-8'))


def _field(view, fid):
    return next(f for f in view['fields'] if f['id'] == fid)


def test_every_tab_has_fields_and_ids_are_unique():
    ids = [f['id'] for f in emusettings.FIELDS]
    assert len(ids) == len(set(ids))
    assert {f['tab'] for f in emusettings.FIELDS} == set(emusettings.TABS)
    for f in emusettings.FIELDS:
        if f['kind'] == 'select':
            assert any(o['value'] == f['default'] for o in f['options']), f['id']


def test_view_reads_game_file_then_config_json_then_default(user):
    _write(user, {'GPU': {'present_mode': 'Immediate'}})
    v = emusettings.view(str(user))
    present = _field(v, 'GPU.present_mode')
    assert (present['value'], present['own']) == ('Immediate', True)
    width = _field(v, 'GPU.window_width')
    assert (width['value'], width['own']) == (1920, False)
    fsr = _field(v, 'GPU.fsr_enabled')
    assert (fsr['value'], fsr['own']) == (False, False)
    assert _field(v, emusettings.DISPLAY_ID)['value'] == 'Fullscreen (Borderless)'
    assert v['tabs'] == list(emusettings.TABS) and v['blocked'] == '' and v['path'] == str(_game_file(user))


def test_view_choices_for_devices_and_cards(user):
    _write(user, {'Audio': {'sdl_main_output_device': 'Headset (USB)'}, 'Vulkan': {'gpu_id': 3}})
    v = emusettings.view(str(user))
    dev = [o['value'] for o in _field(v, 'Audio.sdl_main_output_device')['options']]
    assert dev == ['Default Device', 'Speakers (Realtek)', 'Headset (USB)']     # the saved one stays a choice
    assert 'None' in [o['value'] for o in _field(v, 'Audio.sdl_mic_device')['options']]
    gpu = _field(v, 'Vulkan.gpu_id')
    assert [o['value'] for o in gpu['options']] == [-1, 0, 3] and 'Some GPU' in gpu['help']


def test_save_writes_only_the_changed_keys(user):
    _write(user, {'GPU': {'present_mode': 'Immediate', 'mystery': 7}, 'Extra': {'x': 1}})
    assert emusettings.save(str(user), {'GPU.fsr_enabled': True, 'General.volume_slider': 120}) == \
        ['GPU.fsr_enabled', 'General.volume_slider']
    assert _read(user) == {'GPU': {'present_mode': 'Immediate', 'mystery': 7, 'fsr_enabled': True},
                           'Extra': {'x': 1}, 'General': {'volume_slider': 120}}


def test_a_new_game_file_starts_from_config_json(user):
    emusettings.save(str(user), {'GPU.hdr_allowed': True})
    cfg = _read(user)
    assert cfg['GPU'] == {'present_mode': 'Fifo', 'window_width': 1920, 'hdr_allowed': True}
    assert cfg['General'] == {'volume_slider': 80}


@pytest.mark.parametrize('changes, says', [
    ({'GPU.readbacks_mode': 0}, 'set by Overtime'),
    ({'Network.shadnet_server': 'evil:1'}, 'set by Overtime'),
    ({'Nope.key': 1}, 'Unknown setting'),
    ({}, 'Nothing changed'),
    ({'GPU.fsr_enabled': True, 'GPU.window_width': 99999}, 'from 0 to 9999'),   # one bad value: nothing written
])
def test_refused_changes_write_nothing(user, changes, says):
    with pytest.raises(emusettings.SettingsError, match=says):
        emusettings.save(str(user), changes)
    assert not _game_file(user).exists()


def test_red_zone_is_locked_where_overtime_turns_it_on(user, monkeypatch):
    assert 'General.redzone_patches' not in emusettings.locks()
    monkeypatch.setattr(gamesetup, 'amd_math_needed', lambda: True)
    assert _field(emusettings.view(str(user)), 'General.redzone_patches')['lock'] == emusettings.LOCK_REDZONE
    with pytest.raises(emusettings.SettingsError):
        emusettings.save(str(user), {'General.redzone_patches': False})


def test_coerce():
    by = emusettings.BY_ID
    with pytest.raises(emusettings.SettingsError):
        emusettings.coerce(by['GPU.fsr_enabled'], 1)                  # a check takes a bool only
    assert emusettings.coerce(by['General.console_language'], '2') == 2
    with pytest.raises(emusettings.SettingsError):
        emusettings.coerce(by['General.console_language'], True)
    with pytest.raises(emusettings.SettingsError):
        emusettings.coerce(by['GPU.present_mode'], 'Vsync')
    assert emusettings.coerce(by['GPU.window_width'], 1920.4) == 1920
    assert emusettings.coerce(by['General.trophy_notification_duration'], 2.5) == 2.5
    with pytest.raises(emusettings.SettingsError):
        emusettings.coerce(by['GPU.vblank_frequency'], 30)
    assert emusettings.coerce(by['Vulkan.gpu_id'], -1) == -1
    with pytest.raises(emusettings.SettingsError):
        emusettings.coerce(by['Vulkan.gpu_id'], -2)
    assert emusettings.coerce(by['Log.filter'], '  *:Info ') == '*:Info'
    with pytest.raises(emusettings.SettingsError):
        emusettings.coerce(by['Log.filter'], 'a\nb')
    dmem = by['General.' + gamesetup.DMEM_KEY]
    assert emusettings.coerce(dmem, 0) == 0
    with pytest.raises(emusettings.SettingsError, match='from 3500'):
        emusettings.coerce(dmem, 0, resolution=1440)


def test_dmem_floor_at_1440_in_the_view(user):
    assert _field(emusettings.view(str(user), 1440), 'General.' + gamesetup.DMEM_KEY)['min'] == gamesetup.DMEM_1440
    assert _field(emusettings.view(str(user), 1080), 'General.' + gamesetup.DMEM_KEY)['min'] == 0


def test_no_save_while_the_game_runs_or_a_match_is_set_up(user, monkeypatch):
    monkeypatch.setattr(overlay, 'emulator_running', lambda: True)
    assert 'Close NHL 19' in emusettings.view(str(user))['blocked']
    with pytest.raises(emusettings.SettingsError, match='Close NHL 19'):
        emusettings.save(str(user), {'GPU.fsr_enabled': True})
    monkeypatch.setattr(overlay, 'emulator_running', lambda: False)
    monkeypatch.setattr(matchsetup, 'active', lambda: True)
    with pytest.raises(emusettings.SettingsError, match='match'):
        emusettings.save(str(user), {'GPU.fsr_enabled': True})
    assert not _game_file(user).exists()


def test_display_mode_is_the_apps_choice(user):
    emusettings.save(str(user), {emusettings.DISPLAY_ID: 'Windowed'})
    assert _read(user)['GPU']['full_screen'] is False and _read(user)['GPU']['full_screen_mode'] == 'Windowed'
    assert gamesetup.display_mode() == 'Windowed'
    assert _field(emusettings.view(str(user)), emusettings.DISPLAY_ID)['value'] == 'Windowed'
    emusettings.save(str(user), {emusettings.DISPLAY_ID: 'Fullscreen'})
    assert _read(user)['GPU']['full_screen'] is True and gamesetup.display_mode() == 'Fullscreen'
    # a match plays borderless: exclusive fullscreen hides the HUD
    assert gamesetup.display_keys(match=True) == {'full_screen': True, 'full_screen_mode': 'Fullscreen (Borderless)'}


def test_a_failed_write_keeps_the_display_choice(user, monkeypatch):
    def broken(path, data):
        raise OSError('disk full')
    monkeypatch.setattr(gamesetup, '_write', broken)
    with pytest.raises(OSError):
        emusettings.save(str(user), {emusettings.DISPLAY_ID: 'Windowed'})
    assert gamesetup.display_mode() == 'Fullscreen (Borderless)'


def test_backups_keep_the_newest_five(user, tmp_path):
    _write(user, {'GPU': {}})
    for n in range(7):
        emusettings.save(str(user), {'GPU.window_width': 1000 + n})
    folder = tmp_path / 'apphome' / 'backups' / 'emusettings'
    kept = sorted(os.listdir(folder))
    assert len(kept) == emusettings.BACKUPS_KEPT
    assert json.loads((folder / kept[-1]).read_text(encoding='utf-8'))['GPU']['window_width'] == 1005


def test_settings_survive_patch_and_unpatch_puts_back_only_overtimes_keys(world, monkeypatch):  # noqa: F811
    """Patch, the player changes Game settings, Patch again (Play's refresh): the player's values stay; Unpatch puts
    back what Overtime changed (readbacks, display) and keeps the player's own."""
    monkeypatch.setattr(emusettings, '_gpus', lambda: [])
    monkeypatch.setattr(emusettings, '_audio_endpoints', lambda kind: [])
    user = str(world['user'])
    path = world['user'] / 'custom_configs' / TITLE
    path.write_text(json.dumps({'General': {}, 'GPU': {'readbacks_mode': 1, 'present_mode': 'Fifo'}}), encoding='utf-8')
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    emusettings.save(user, {'GPU.present_mode': 'Immediate', emusettings.DISPLAY_ID: 'Windowed'})
    gamesetup.install(str(world['emu']), xmlpatch.build('localhost'), running=lambda: False)
    cfg = json.loads(path.read_text(encoding='utf-8'))
    assert cfg['GPU']['present_mode'] == 'Immediate'
    assert (cfg['GPU']['full_screen'], cfg['GPU']['full_screen_mode']) == (False, 'Windowed')
    assert cfg['GPU']['readbacks_mode'] == 2
    gamesetup.remove(running=lambda: False)
    after = json.loads(path.read_text(encoding='utf-8'))
    assert after['GPU']['present_mode'] == 'Immediate' and after['GPU']['readbacks_mode'] == 1
    assert 'full_screen_mode' not in after['GPU']


def test_a_match_plays_borderless_over_exclusive_fullscreen(user):
    from overtime_roster.app import matchsetup as MS
    gamesetup.set_display('Fullscreen')
    cfg = MS._config_values({'GPU': {'present_mode': 'Fifo'}}, str(user), xmlpatch.build('localhost'), {})
    assert (cfg['GPU']['full_screen'], cfg['GPU']['full_screen_mode']) == (True, 'Fullscreen (Borderless)')
    assert cfg['GPU']['present_mode'] == 'Fifo'
    gamesetup.set_display('Windowed')
    cfg = MS._config_values({}, str(user), xmlpatch.build('localhost'), {})
    assert (cfg['GPU']['full_screen'], cfg['GPU']['full_screen_mode']) == (False, 'Windowed')


# --- the Setup controller's calls -------------------------------------------------------------------------------------
from test_setup_controller import SC, sc  # noqa: E402,F401  (fixture)


@pytest.fixture
def ready(sc, monkeypatch):  # noqa: F811
    monkeypatch.setattr(emusettings, '_gpus', lambda: [])
    monkeypatch.setattr(emusettings, '_audio_endpoints', lambda kind: [])
    sc.setup_refresh()
    return sc


def test_calls_are_wired():
    for name, method in (('setup_emu_settings', 'emu_settings'), ('setup_emu_settings_save', 'emu_settings_save'),
                         ('setup_emu_input', 'emu_input'), ('setup_emu_input_save', 'emu_input_save')):
        assert SC.SetupController.CALLS[name] == method and callable(getattr(SC.SetupController, method))


def test_views_wait_for_the_emulator(sc, monkeypatch):  # noqa: F811
    monkeypatch.setattr(SC.SetupController, 'known_emulator', lambda self: '')
    for got in (sc.emu_settings(), sc.emu_settings_save({'GPU.fsr_enabled': True}), sc.emu_input('pad'),
                sc.emu_input_save('pad', {})):
        assert got == {'error': 'Find NHL 19 in Setup first.'}


def test_display_choice_is_kept_for_the_next_start(ready):
    assert 'error' not in ready.emu_settings()
    got = ready.emu_settings_save({emusettings.DISPLAY_ID: 'Windowed'})
    assert got['ok'] and _field(got, emusettings.DISPLAY_ID)['value'] == 'Windowed'
    assert ready.ctl.prefs['setup']['display'] == 'Windowed'
    gamesetup.set_display(None)
    SC.SetupController(ready.ctl)                                       # the next start
    assert gamesetup.display_mode() == 'Windowed'
    assert ready.emu_settings_save({'GPU.readbacks_mode': 0})['error'].endswith('is set by Overtime.')


def test_input_save_says_when_the_bindings_apply(ready, monkeypatch):
    model = ready.emu_input('keys')['model']
    model['bindings']['r1'] = ['lshift,u']
    assert ready.emu_input_save('keys', model)['ok']
    assert ready.ctl.said[-1] == ('Keyboard bindings saved. NHL 19 uses them from its next start.', 'good')
    monkeypatch.setattr(overlay, 'emulator_running', lambda: True)       # allowed while it runs: F8 re-reads
    got = ready.emu_input_save('pad', ready.emu_input('pad')['model'])
    assert got['ok'] and ready.ctl.said[-1][0].endswith('Press F8 in NHL 19 to use them now.')
    bad = dict(model, bindings=dict(model['bindings'], cross=['kp2']))
    assert 'Cross' in ready.emu_input_save('keys', bad)['error']
