"""Controllers and Keyboard (Setup > Boost performance): shadPS4's input file for NHL 19, read and written by emuinput."""
import copy
import json
import os

import pytest

from overtime_roster.app import emuinput

KB_HEAD = emuinput.KEYS_HEAD
PAD_HEAD = emuinput.PAD_HEAD
SAMPLE = ('# my notes\n'
          'cross = n\n'
          'cross = kp2\n'
          'l1 = q\n'
          'key_toggle = i, lalt\n'
          'hotkey_pause = f9\n'
          '\n'
          '# pads\n'
          'cross = cross\n'
          'circle = circle\n'
          'axis_left_x = axis_left_x\n'
          'axis_left_y = axis_left_y\n'
          'analog_deadzone = leftjoystick, 2, 127\n'
          'override_controller_color = false, 0, 0, 255\n')


@pytest.fixture
def user(tmp_path, monkeypatch):
    u = tmp_path / 'user'
    (u / 'input_config').mkdir(parents=True)
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'apphome'))
    return u


def _ini(u, name='default.ini'):
    return u / 'input_config' / name


def _keys(text=SAMPLE):
    return emuinput.keys_model(text)


def test_input_file_follows_the_unified_switch(user):
    assert emuinput.input_file(str(user)) == str(_ini(user))
    (user / 'config.json').write_text(json.dumps({'Input': {'use_unified_input_config': False}}), encoding='utf-8')
    assert emuinput.input_file(str(user)) == str(_ini(user, 'CUSA11126.ini'))


def test_text_falls_back_to_default_ini_then_the_emulators_defaults(user):
    assert emuinput._text(str(user)) == emuinput.default_text()
    _ini(user).write_text(SAMPLE, encoding='utf-8', newline='')
    (user / 'config.json').write_text(json.dumps({'Input': {'use_unified_input_config': False}}), encoding='utf-8')
    assert emuinput._text(str(user)) == SAMPLE          # shadPS4 copies default.ini into the game's file
    _ini(user, 'CUSA11126.ini').write_text('cross = z\n', encoding='utf-8', newline='')
    assert emuinput._text(str(user)) == 'cross = z\n'


def test_parse_and_kind():
    assert emuinput.parse(' Cross = N , kp2:1  # note') == ('cross', ['n', 'kp2'])
    assert emuinput.parse('# only a note') == ('#', [])
    assert emuinput.kind_of('cross = n') == 'keys'
    assert emuinput.kind_of('cross = cross') == 'pad'
    assert emuinput.kind_of('hotkey_pause = f9') == ''
    assert emuinput.kind_of('analog_deadzone = leftjoystick, 2, 127') == 'pad'
    assert emuinput.kind_of('mouse_to_joystick = left') == 'keys'


def test_models_read_the_file():
    k = _keys()
    assert k['bindings']['cross'] == ['n', 'kp2'] and k['bindings']['l1'] == ['q'] and k['bindings']['r1'] == []
    p = emuinput.pad_model(SAMPLE)
    assert p['buttons']['cross'] == 'cross' and p['buttons']['square'] == 'unmapped'
    assert p['deadzone'] == {'left': [2, 127], 'right': [5, 127]} and p['color'] == {'on': False, 'rgb': [0, 0, 255]}


def test_keys_rewrite_keeps_every_other_line():
    m = _keys()
    m['bindings']['r1'] = ['lshift,u']
    out = emuinput.rewrite(SAMPLE, 'keys', m)
    lines = out.splitlines()
    assert lines[:2] == ['# my notes', KB_HEAD]                      # where the first keyboard line was
    assert 'r1 = lshift,u' in lines and 'cross = n' in lines and 'cross = kp2' in lines
    for kept in ('key_toggle = i, lalt', 'hotkey_pause = f9', '# pads', 'cross = cross',
                 'analog_deadzone = leftjoystick, 2, 127'):
        assert kept in lines
    assert lines.index('key_toggle = i, lalt') > lines.index(KB_HEAD)
    assert emuinput.rewrite(out, 'keys', emuinput.keys_model(out)) == out       # a second save changes nothing


def test_pad_rewrite_keeps_the_keyboard_and_the_newline_style():
    crlf = SAMPLE.replace('\n', '\r\n')
    p = emuinput.pad_model(crlf)
    p['buttons']['cross'] = 'circle'
    p['deadzone']['left'] = [10, 120]
    p['color'] = {'on': True, 'rgb': [255, 0, 0]}
    out = emuinput.rewrite(crlf, 'pad', p)
    assert '\r\n' in out and '\n' not in out.replace('\r\n', '')
    lines = out.splitlines()
    assert lines[lines.index('# pads') + 1] == PAD_HEAD
    assert 'cross = circle' in lines and 'cross = cross' not in lines
    assert 'analog_deadzone = leftjoystick, 10, 120' in lines
    assert 'override_controller_color = true, 255, 0, 0' in lines
    assert lines[:6] == ['# my notes', 'cross = n', 'cross = kp2', 'l1 = q', 'key_toggle = i, lalt', 'hotkey_pause = f9']


def test_a_file_without_a_block_gets_it_at_the_end():
    out = emuinput.rewrite('# hotkeys only\nhotkey_pause = f9\n\n\n', 'pad', copy.deepcopy(emuinput.DEFAULT_PAD))
    lines = out.splitlines()
    assert lines[:3] == ['# hotkeys only', 'hotkey_pause = f9', ''] and lines[3] == PAD_HEAD
    assert out.endswith('\n') and not out.endswith('\n\n')


@pytest.mark.parametrize('change, says', [
    (lambda m: m['bindings']['r1'].append('n'), 'on both Cross and R1'),
    (lambda m: m['bindings'].update(cross=['kp2']), 'Keep a letter or digit key on Cross'),
    (lambda m: m['bindings']['axis_left_x_minus'].append('mousewheelup'), 'mouse wheel'),
    (lambda m: m['bindings']['r1'].append('notakey'), 'not a key'),
    (lambda m: m['bindings']['r1'].append('a,b,c,d'), 'not a key'),
    (lambda m: m['bindings'].update(fly=['f']), 'does not have'),
    (lambda m: m['mouse'].update(params=[0.5, 9.0, 0.125]), 'out of range'),
    (lambda m: m['mouse'].update(stick='up'), 'none, left or right'),
])
def test_bad_keyboard_saves_write_nothing(user, change, says):
    _ini(user).write_text(SAMPLE, encoding='utf-8', newline='')
    m = _keys()
    change(m)
    with pytest.raises(emuinput.InputError, match=says):
        emuinput.save(str(user), 'keys', m)
    assert _ini(user).read_text(encoding='utf-8') == SAMPLE


@pytest.mark.parametrize('change', [
    lambda p: p['buttons'].update(cross='jump'),
    lambda p: p['sticks'].update(left='middle'),
    lambda p: p['deadzone'].update(left=[50, 20]),
    lambda p: p['deadzone'].update(left=[0, 127]),
    lambda p: p['color'].update(rgb=[0, 0, 256]),
    lambda p: p['color'].update(on='yes'),
])
def test_bad_controller_saves_write_nothing(user, change):
    _ini(user).write_text(SAMPLE, encoding='utf-8', newline='')
    p = emuinput.pad_model(SAMPLE)
    change(p)
    with pytest.raises(emuinput.InputError):
        emuinput.save(str(user), 'pad', p)
    assert _ini(user).read_text(encoding='utf-8') == SAMPLE


def test_save_writes_the_games_file_and_keeps_a_backup(user, tmp_path):
    _ini(user).write_text(SAMPLE, encoding='utf-8', newline='')
    (user / 'config.json').write_text(json.dumps({'Input': {'use_unified_input_config': False}}), encoding='utf-8')
    m = _keys()
    m['bindings']['cross'] = ['z']
    path = emuinput.save(str(user), 'keys', m)
    assert path == str(_ini(user, 'CUSA11126.ini'))
    assert 'cross = z' in _ini(user, 'CUSA11126.ini').read_text(encoding='utf-8').splitlines()
    assert _ini(user).read_text(encoding='utf-8') == SAMPLE           # default.ini is not the game's file here
    emuinput.save(str(user), 'keys', m)                               # the second save backs the first one up
    assert len(os.listdir(tmp_path / 'apphome' / 'backups' / 'emuinput')) == 1
    assert emuinput.cross_key(str(user)) == 'z'


def test_cross_key_is_the_first_letter_or_digit(user):
    _ini(user).write_text('cross = kp2\ncross = lshift,x\ncross = 7\n', encoding='utf-8')
    assert emuinput.cross_key(str(user)) == '7'
    _ini(user).write_text('cross = kp2\n', encoding='utf-8')
    assert emuinput.cross_key(str(user)) is None


def test_views(user):
    _ini(user).write_text(SAMPLE, encoding='utf-8', newline='')
    (user / 'input_config' / 'global.ini').write_text('hotkey_pause = f6\nhotkey_quit = lctrl, lshift, end\n',
                                                      encoding='utf-8')
    pad = emuinput.view(str(user), 'pad')
    assert pad['model']['buttons']['cross'] == 'cross' and pad['defaults'] == emuinput.DEFAULT_PAD
    assert [o for o, _ in pad['outputs']] == [o for o, _ in emuinput.PAD_OUTPUTS]
    keys = emuinput.view(str(user), 'keys')
    assert keys['slots'] == emuinput.KEY_SLOTS and keys['path'] == str(_ini(user))
    hot = dict(keys['hotkeys'])
    assert hot['Pause'] == 'f6' and hot['Fullscreen on / off'] == 'f11'      # the missing ones: shadPS4's defaults
    with pytest.raises(emuinput.InputError):
        emuinput.view(str(user), 'mouse')
