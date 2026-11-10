"""shadPS4's controller and keyboard bindings: the Controllers and Keyboard views on Setup's Boost performance card.

shadPS4 reads `input_config\\default.ini` for every game while config.json's Input.use_unified_input_config is on (its
default), else `input_config\\<title>.ini` (made as a copy of default.ini when missing). A line is `output = input`
(up to three inputs joined by commas, all held), `#` starts a comment, and section headings are only comments: a line
belongs to the controller or the keyboard by its inputs. A save rewrites only its own kind of line (the controller's
or the keyboard's, for the outputs the view shows) and keeps every other line where it was: hotkeys, key toggles,
comments, the other view's lines. Names, grammar and defaults: docs/notes/emu-settings.md.
"""

import datetime
import glob
import json
import os

from . import gamesetup, paths

BACKUPS_KEPT = 5

# --- names shadPS4 knows (fork input_handler.h) ---
PAD_BUTTONS = ('cross', 'circle', 'square', 'triangle', 'l1', 'r1', 'l2', 'r2', 'l3', 'r3', 'options', 'back',
               'pad_up', 'pad_down', 'pad_left', 'pad_right')
PAD_OTHER = ('share', 'touchpad_left', 'touchpad_center', 'touchpad_right', 'lpaddle_high', 'lpaddle_low',
             'rpaddle_high', 'rpaddle_low', 'qam', 'l4', 'r4', 'l5', 'r5', 'axis_left_x', 'axis_left_y',
             'axis_right_x', 'axis_right_y') + tuple(f'axis_{s}_{a}_{d}' for s in ('left', 'right')
                                                     for a in ('x', 'y') for d in ('plus', 'minus'))
PAD_INPUTS = frozenset(PAD_BUTTONS + PAD_OTHER)
_PUNCT = ('grave', 'tilde', 'exclamation', 'at', 'hash', 'dollar', 'percent', 'caret', 'ampersand', 'asterisk',
          'lparen', 'rparen', 'minus', 'underscore', 'equals', 'plus', 'lbracket', 'rbracket', 'lbrace', 'rbrace',
          'backslash', 'pipe', 'semicolon', 'colon', 'apostrophe', 'quote', 'comma', 'less', 'period', 'greater',
          'slash', 'question')
_SPECIAL = ('escape', 'printscreen', 'scrolllock', 'pausebreak', 'backspace', 'delete', 'insert', 'home', 'end',
            'pgup', 'pgdown', 'tab', 'capslock', 'enter', 'lshift', 'rshift', 'lctrl', 'rctrl', 'lalt', 'ralt',
            'lmeta', 'rmeta', 'lwin', 'rwin', 'space', 'up', 'down', 'left', 'right')
_KEYPAD = tuple(f'kp{i}' for i in range(10)) + ('kpperiod', 'kpcomma', 'kpslash', 'kpasterisk', 'kpminus', 'kpplus',
                                                 'kpequals', 'kpenter')
KEYS = frozenset(tuple('abcdefghijklmnopqrstuvwxyz0123456789') + tuple(f'f{i}' for i in range(1, 13))
                 + _PUNCT + _SPECIAL + _KEYPAD)
WHEEL = frozenset(('mousewheelup', 'mousewheeldown', 'mousewheelleft', 'mousewheelright'))
MOUSE = frozenset(('leftbutton', 'rightbutton', 'middlebutton', 'sidebuttonback', 'sidebuttonforward')) | WHEEL
KB_INPUTS = KEYS | MOUSE | {'unmapped'}

# --- what the views show ---
PAD_OUTPUTS = (('cross', 'Cross'), ('circle', 'Circle'), ('square', 'Square'), ('triangle', 'Triangle'),
               ('l1', 'L1'), ('r1', 'R1'), ('l2', 'L2'), ('r2', 'R2'), ('l3', 'L3'), ('r3', 'R3'),
               ('options', 'Options'), ('touchpad_center', 'Touchpad click'), ('pad_up', 'D-pad up'),
               ('pad_down', 'D-pad down'), ('pad_left', 'D-pad left'), ('pad_right', 'D-pad right'))
PAD_CHOICES = (('cross', 'Cross / A'), ('circle', 'Circle / B'), ('square', 'Square / X'), ('triangle', 'Triangle / Y'),
               ('l1', 'L1 / LB'), ('r1', 'R1 / RB'), ('l2', 'L2 / LT'), ('r2', 'R2 / RT'), ('l3', 'L3 (left stick)'),
               ('r3', 'R3 (right stick)'), ('options', 'Options / Start'), ('back', 'Touchpad / Back'),
               ('pad_up', 'D-pad up'), ('pad_down', 'D-pad down'), ('pad_left', 'D-pad left'),
               ('pad_right', 'D-pad right'), ('unmapped', 'Nothing'))
STICKS = ('left', 'right')
KEY_OUTPUTS = (('cross', 'Cross'), ('circle', 'Circle'), ('square', 'Square'), ('triangle', 'Triangle'),
               ('l1', 'L1'), ('r1', 'R1'), ('l2', 'L2'), ('r2', 'R2'), ('l3', 'L3'), ('r3', 'R3'),
               ('options', 'Options'), ('touchpad_left', 'Touchpad left'), ('touchpad_center', 'Touchpad click'),
               ('touchpad_right', 'Touchpad right'), ('pad_up', 'D-pad up'), ('pad_down', 'D-pad down'),
               ('pad_left', 'D-pad left'), ('pad_right', 'D-pad right'),
               ('axis_left_y_minus', 'Left stick up'), ('axis_left_y_plus', 'Left stick down'),
               ('axis_left_x_minus', 'Left stick left'), ('axis_left_x_plus', 'Left stick right'),
               ('axis_right_y_minus', 'Right stick up'), ('axis_right_y_plus', 'Right stick down'),
               ('axis_right_x_minus', 'Right stick left'), ('axis_right_x_plus', 'Right stick right'),
               ('leftjoystick_halfmode', 'Left stick half speed'),
               ('rightjoystick_halfmode', 'Right stick half speed'))
KEY_SLOTS, MAX_COMBO = 3, 3
HOTKEYS = (('hotkey_fullscreen', 'Fullscreen on / off'), ('hotkey_show_fps', 'Show FPS'), ('hotkey_pause', 'Pause'),
           ('hotkey_reload_inputs', 'Reload these bindings'), ('hotkey_quit', 'Quit the game'),
           ('hotkey_toggle_mouse_to_joystick', 'Mouse as a stick on / off'),
           ('hotkey_toggle_mouse_to_gyro', 'Mouse as motion on / off'),
           ('hotkey_toggle_mouse_to_touchpad', 'Mouse as touchpad on / off'),
           ('hotkey_volume_up', 'Volume up'), ('hotkey_volume_down', 'Volume down'),
           ('hotkey_screenshot_with_overlays', 'Screenshot'), ('hotkey_capture_frame', 'Capture a frame (RenderDoc)'),
           ('hotkey_emulator_settings', 'Emulator settings'), ('hotkey_toggle_friends', 'Friends list'),
           ('hotkey_add_virtual_user', 'Add a player'), ('hotkey_remove_virtual_user', 'Remove a player'))
MOUSE_PARAMS = (('deadzone', 0.0, 1.0, 0.5), ('speed', 0.1, 5.0, 1.0), ('offset', 0.0, 1.0, 0.125))

# shadPS4's own default map (the emulator writes it as default.ini)
DEFAULT_PAD = {'buttons': {o: ('back' if o == 'touchpad_center' else o) for o, _ in PAD_OUTPUTS},
               'sticks': {'left': 'left', 'right': 'right'},
               'deadzone': {'left': [5, 127], 'right': [5, 127]},
               'color': {'on': False, 'rgb': [0, 0, 255]}}
DEFAULT_KEYS = {'bindings': {
    'triangle': ['kp8', 'c'], 'circle': ['kp6', 'b'], 'cross': ['kp2', 'n'], 'square': ['kp4', 'v'],
    'l1': ['q'], 'r1': ['u'], 'l2': ['e'], 'r2': ['o'], 'l3': ['x'], 'r3': ['m'],
    'options': ['enter'], 'touchpad_center': ['space'],
    'pad_up': ['up'], 'pad_down': ['down'], 'pad_left': ['left'], 'pad_right': ['right'],
    'axis_left_x_minus': ['a'], 'axis_left_x_plus': ['d'], 'axis_left_y_minus': ['w'], 'axis_left_y_plus': ['s'],
    'axis_right_x_minus': ['j'], 'axis_right_x_plus': ['l'], 'axis_right_y_minus': ['i'], 'axis_right_y_plus': ['k']},
    'mouse': {'stick': 'none', 'params': [0.5, 1.0, 0.125]}}

# the emulator's own block headings: dropped with the block they head when a view rewrites it
STOCK_HEADINGS = {'pad': ('# controller bindings', '# range of deadzones'),
                  'keys': ('# keyboard bindings', '# alternatives for users without a keypad')}
PAD_HEAD = '# Controller (Overtime: Setup > Boost performance > Controllers)'
KEYS_HEAD = '# Keyboard (Overtime: Setup > Boost performance > Keyboard)'
DEADZONE_NOTE = '# Deadzones: 1 (almost none) to 127 (most)'
OWN_HEADINGS = {'pad': (PAD_HEAD.lower(), DEADZONE_NOTE.lower()), 'keys': (KEYS_HEAD.lower(),)}


class InputError(RuntimeError):
    pass


# ---- files ---------------------------------------------------------------------------------------------------------
def unified(user_dir):
    """config.json's Input.use_unified_input_config (shadPS4's default: on)."""
    try:
        with open(os.path.join(user_dir, 'config.json'), encoding='utf-8-sig') as f:
            value = (json.load(f).get('Input') or {}).get('use_unified_input_config', True)
        return value is not False
    except (OSError, ValueError, AttributeError):
        return True


def input_file(user_dir):
    """The input file shadPS4 reads for NHL 19."""
    name = 'default.ini' if unified(user_dir) else gamesetup.active_title() + '.ini'
    return os.path.join(user_dir, 'input_config', name)


def _text(user_dir):
    """The input file's text as shadPS4 would read it: the game's file, else default.ini (which it copies), else the
    emulator's defaults."""
    for path in (input_file(user_dir), os.path.join(user_dir, 'input_config', 'default.ini')):
        try:
            with open(path, encoding='utf-8', errors='replace', newline='') as f:
                return f.read()
        except OSError:
            continue
    return default_text()


def default_text():
    return '\n'.join(_keys_block(DEFAULT_KEYS) + [''] + _pad_block(DEFAULT_PAD)) + '\n'


# ---- lines ---------------------------------------------------------------------------------------------------------
def parse(line):
    """(output, [inputs]) for a binding line, ('#', []) for a comment or blank line. Inputs lose their ':N' pad id."""
    body = line.split('#', 1)[0]
    body = ''.join(body.split())
    if '=' not in body:
        return '#', []
    out, _, inp = body.partition('=')
    return out.lower(), [t.split(':', 1)[0].lower() for t in inp.split(',') if t]


def kind_of(line):
    """'pad', 'keys' or '' (anything a view leaves alone: comments, hotkeys, key toggles, other special lines)."""
    out, inputs = parse(line)
    if out == '#' or not inputs or out.startswith('hotkey_'):
        return ''
    if out in ('analog_deadzone', 'override_controller_color'):
        return 'pad'
    if out in ('mouse_to_joystick', 'mouse_movement_params'):
        return 'keys'
    if all(t in PAD_INPUTS for t in inputs):
        return 'pad'
    if all(t in KB_INPUTS for t in inputs):
        return 'keys'
    return ''


def _raw_value(line):
    return line.split('#', 1)[0].partition('=')[2]


def _numbers(line, count, cast=int):
    parts = [p.strip() for p in _raw_value(line).split(',')]
    try:
        return [cast(p) for p in parts[1:1 + count]] if len(parts) > count else None
    except ValueError:
        return None


# ---- read ----------------------------------------------------------------------------------------------------------
def pad_model(text):
    m = json.loads(json.dumps(DEFAULT_PAD))
    m['buttons'] = {o: 'unmapped' for o, _ in PAD_OUTPUTS}
    seen = set()
    for line in text.splitlines():
        if kind_of(line) != 'pad':
            continue
        out, inputs = parse(line)
        if out == 'analog_deadzone':
            which = _raw_value(line).split(',')[0].strip().lower()
            nums = _numbers(line, 2)
            side = {'leftjoystick': 'left', 'rightjoystick': 'right'}.get(which)
            if side and nums:
                m['deadzone'][side] = [max(1, min(127, n)) for n in nums]
        elif out == 'override_controller_color':
            on = _raw_value(line).split(',')[0].strip().lower() == 'true'
            rgb = _numbers(line, 3)
            m['color'] = {'on': on, 'rgb': [max(0, min(255, n)) for n in rgb] if rgb else [0, 0, 255]}
        elif out in ('axis_left_x', 'axis_right_x') and len(inputs) == 1 and inputs[0] in ('axis_left_x', 'axis_right_x'):
            m['sticks'][out.split('_')[1]] = inputs[0].split('_')[1]
        elif out in m['buttons'] and out not in seen and len(inputs) == 1 and inputs[0] in dict(PAD_CHOICES):
            m['buttons'][out] = inputs[0]
            seen.add(out)
    return m


def keys_model(text):
    m = {'bindings': {o: [] for o, _ in KEY_OUTPUTS}, 'mouse': json.loads(json.dumps(DEFAULT_KEYS['mouse']))}
    for line in text.splitlines():
        if kind_of(line) != 'keys':
            continue
        out, inputs = parse(line)
        if out == 'mouse_to_joystick':
            m['mouse']['stick'] = inputs[0] if inputs and inputs[0] in ('left', 'right') else 'none'
        elif out == 'mouse_movement_params':
            nums = [p.strip() for p in _raw_value(line).split(',')]
            try:
                m['mouse']['params'] = [min(hi, max(lo, float(n))) for n, (_, lo, hi, _) in zip(nums, MOUSE_PARAMS)]
            except ValueError:
                pass
            if len(m['mouse']['params']) != len(MOUSE_PARAMS):
                m['mouse']['params'] = list(DEFAULT_KEYS['mouse']['params'])
        elif out in m['bindings'] and 'unmapped' not in inputs:
            m['bindings'][out].append(','.join(inputs))
    return m


def hotkeys(user_dir):
    """[[label, combo]] from global.ini (shadPS4 fills in the missing ones at every start)."""
    found = {}
    try:
        with open(os.path.join(user_dir, 'input_config', 'global.ini'), encoding='utf-8', errors='replace') as f:
            for line in f.read().splitlines():
                out, inputs = parse(line)
                if out.startswith('hotkey_') and inputs and out not in found:
                    found[out] = ' + '.join(inputs)
    except OSError:
        pass
    defaults = {'hotkey_fullscreen': 'f11', 'hotkey_show_fps': 'f10', 'hotkey_pause': 'f9',
                'hotkey_reload_inputs': 'f8', 'hotkey_quit': 'lctrl + lshift + end'}
    return [[label, found.get(name) or defaults.get(name, '')] for name, label in HOTKEYS
            if found.get(name) or name in defaults]


def view(user_dir, kind):
    """What the Controllers ('pad') or Keyboard ('keys') view shows."""
    if kind not in ('pad', 'keys'):
        raise InputError('Unknown view.')
    text = _text(user_dir)
    base = {'kind': kind, 'path': input_file(user_dir), 'unified': unified(user_dir)}
    if kind == 'pad':
        return {**base, 'model': pad_model(text), 'defaults': DEFAULT_PAD,
                'outputs': [list(o) for o in PAD_OUTPUTS], 'choices': [list(c) for c in PAD_CHOICES]}
    return {**base, 'model': keys_model(text), 'defaults': DEFAULT_KEYS, 'outputs': [list(o) for o in KEY_OUTPUTS],
            'slots': KEY_SLOTS, 'hotkeys': hotkeys(user_dir),
            'mouse_params': [list(p) for p in MOUSE_PARAMS]}


def cross_key(user_dir):
    """The first one-character key (letter or digit) the keyboard map gives Cross, or None."""
    for combo in keys_model(_text(user_dir))['bindings']['cross']:
        if len(combo) == 1 and combo.isalnum():
            return combo
    return None


# ---- write ---------------------------------------------------------------------------------------------------------
def _pad_block(m):
    lines = [PAD_HEAD]
    lines += [f'{o} = {m["buttons"][o]}' for o, _ in PAD_OUTPUTS if m['buttons'][o] != 'unmapped']
    for side in STICKS:
        src = m['sticks'][side]
        lines += [f'axis_{side}_x = axis_{src}_x', f'axis_{side}_y = axis_{src}_y']
    lines.append(DEADZONE_NOTE)
    lines += [f'analog_deadzone = {side}joystick, {m["deadzone"][side][0]}, {m["deadzone"][side][1]}'
              for side in STICKS]
    c = m['color']
    lines.append(f'override_controller_color = {"true" if c["on"] else "false"}, {c["rgb"][0]}, {c["rgb"][1]}, '
                 f'{c["rgb"][2]}')
    return lines


def _keys_block(m):
    lines = [KEYS_HEAD]
    for o, _ in KEY_OUTPUTS:
        lines += [f'{o} = {combo}' for combo in m['bindings'].get(o, [])]
    lines.append(f'mouse_to_joystick = {m["mouse"]["stick"]}')
    lines.append('mouse_movement_params = ' + ', '.join(f'{v:g}' for v in m['mouse']['params']))
    return lines


def _check_pad(m):
    if not isinstance(m, dict):
        raise InputError('Nothing to save.')
    choices = dict(PAD_CHOICES)
    b = m.get('buttons')
    if not isinstance(b, dict) or set(b) != {o for o, _ in PAD_OUTPUTS} or any(v not in choices for v in b.values()):
        raise InputError('A button is set to something the controller does not have.')
    s = m.get('sticks')
    if not isinstance(s, dict) or set(s) != set(STICKS) or any(v not in STICKS for v in s.values()):
        raise InputError('Each stick takes the left or the right stick.')
    d = m.get('deadzone')
    if not isinstance(d, dict) or set(d) != set(STICKS):
        raise InputError('Deadzones: two numbers per stick.')
    for side in STICKS:
        v = d[side]
        if (not isinstance(v, list) or len(v) != 2 or any(isinstance(n, bool) or not isinstance(n, int) for n in v)
                or not 1 <= v[0] <= v[1] <= 127):
            raise InputError(f'The {side} stick deadzone: from 1 to 127, the inner one not above the outer one.')
    c = m.get('color')
    if (not isinstance(c, dict) or not isinstance(c.get('on'), bool) or not isinstance(c.get('rgb'), list)
            or len(c['rgb']) != 3 or any(isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 255
                                         for n in c['rgb'])):
        raise InputError('Lightbar colour: on or off and three numbers from 0 to 255.')
    return {'buttons': dict(b), 'sticks': dict(s), 'deadzone': {k: list(v) for k, v in d.items()},
            'color': {'on': c['on'], 'rgb': list(c['rgb'])}}


def _check_keys(m):
    if not isinstance(m, dict) or not isinstance(m.get('bindings'), dict):
        raise InputError('Nothing to save.')
    labels = dict(KEY_OUTPUTS)
    clean, used = {}, {}
    for o, combos in m['bindings'].items():
        if o not in labels or not isinstance(combos, list) or len(combos) > max(KEY_SLOTS, 8):
            raise InputError('A binding is for something the game does not have.')
        clean[o] = []
        for combo in combos:
            names = [t.strip().lower() for t in combo.split(',')] if isinstance(combo, str) else []
            if not 1 <= len(names) <= MAX_COMBO or any(t not in KEYS | MOUSE for t in names) or len(set(names)) != len(names):
                raise InputError(f'{labels[o]}: "{combo}" is not a key shadPS4 knows.')
            if o.startswith('axis_') and any(t in WHEEL for t in names):
                raise InputError(f'{labels[o]}: the mouse wheel cannot move a stick.')
            key = ','.join(names)
            if key in used:
                raise InputError(f'{key.replace(",", " + ")} is on both {used[key]} and {labels[o]}.')
            used[key] = labels[o]
            clean[o].append(key)
    if not any(len(k) == 1 and k.isalnum() for k in clean.get('cross', [])):
        raise InputError('Keep a letter or digit key on Cross: Overtime presses it to start online matches.')
    mouse = m.get('mouse') or {}
    stick = mouse.get('stick', 'none')
    params = mouse.get('params', DEFAULT_KEYS['mouse']['params'])
    if stick not in ('none', 'left', 'right'):
        raise InputError('Mouse as a stick: none, left or right.')
    if (not isinstance(params, list) or len(params) != len(MOUSE_PARAMS)
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi
                   for v, (_, lo, hi, _) in zip(params, MOUSE_PARAMS))):
        raise InputError('Mouse settings out of range.')
    return {'bindings': clean, 'mouse': {'stick': stick, 'params': [float(v) for v in params]}}


def _managed(kind, line):
    """True for a line the `kind` view rewrites: its kind of binding for an output it shows, or its special lines."""
    if kind_of(line) != kind:
        stripped = line.strip().lower()
        return stripped.startswith(STOCK_HEADINGS[kind]) or stripped in OWN_HEADINGS[kind]
    out, _ = parse(line)
    if kind == 'pad':
        if out == 'analog_deadzone':
            return _raw_value(line).split(',')[0].strip().lower() in ('leftjoystick', 'rightjoystick')
        return out == 'override_controller_color' or out in dict(PAD_OUTPUTS) or out in (
            'axis_left_x', 'axis_left_y', 'axis_right_x', 'axis_right_y')
    return out in ('mouse_to_joystick', 'mouse_movement_params') or out in dict(KEY_OUTPUTS)


def rewrite(text, kind, model):
    """`text` with the `kind` view's lines replaced by `model`'s, placed where the first of them was (else at the end);
    every other line stays in order."""
    nl = '\r\n' if '\r\n' in text else '\n'
    lines = text.splitlines()
    block = _pad_block(model) if kind == 'pad' else _keys_block(model)
    out, at = [], None
    for line in lines:
        if _managed(kind, line):
            if at is None:
                at = len(out)
            continue
        out.append(line)
    if at is None:
        while out and not out[-1].strip():
            out.pop()
        at = len(out) + 1 if out else 0
        if out:
            out.append('')
    out[at:at] = block + ([''] if at < len(out) and out[at].strip() else [])
    tidy = []
    for line in out:                    # no runs of blank lines where removed lines were
        if not line.strip() and (not tidy or not tidy[-1].strip()):
            continue
        tidy.append(line)
    while tidy and not tidy[-1].strip():
        tidy.pop()
    return nl.join(tidy) + nl


def _backup(path):
    if not os.path.isfile(path):
        return
    name = os.path.basename(path)
    folder = paths.app_dir('backups', 'emuinput')
    gamesetup._write(os.path.join(folder, datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f-') + name),
                     gamesetup._read(path))
    for old in sorted(glob.glob(os.path.join(folder, '*-' + name)))[:-BACKUPS_KEPT]:
        try:
            os.remove(old)
        except OSError:
            pass


def save(user_dir, kind, model):
    """Write the Controllers ('pad') or Keyboard ('keys') view into the input file shadPS4 reads. Returns its path.
    Allowed while the game runs (shadPS4 re-reads the file on F8)."""
    if kind not in ('pad', 'keys'):
        raise InputError('Unknown view.')
    model = _check_pad(model) if kind == 'pad' else _check_keys(model)
    path = input_file(user_dir)
    new = rewrite(_text(user_dir), kind, model)
    _backup(path)
    gamesetup._write(path, new.encode('utf-8'))
    return path
