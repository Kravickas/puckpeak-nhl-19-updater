"""shadPS4's game settings for NHL 19: the Game settings view on Setup's Boost performance card.

The view reads the game's own config file (custom_configs\\CUSA11126.json, over config.json, over the emulator's
defaults) and writes back only the keys the player changed; everything else in the file stays as it is. The keys,
defaults and ranges are the Kravickas build's (docs/notes/emu-settings.md); the tabs follow the launcher's per-game
set, the wording is Overtime's own. Keys Overtime sets itself are shown locked, with the reason, and refused here too.
"""

import datetime
import glob
import json
import os
import subprocess
import sys

from overtime_core import overlay

from . import gamesetup, matchsetup, paths

TABS = ('General', 'Graphics', 'User', 'Input', 'Network', 'Log', 'Debug', 'Experimental')
BACKUPS_KEPT = 5
DEFAULT_DEVICE = 'Default Device'
MAX_TEXT = 300

LANGUAGES = ('Japanese', 'English (US)', 'French (France)', 'Spanish (Spain)', 'German', 'Italian', 'Dutch',
             'Portuguese (Portugal)', 'Russian', 'Korean', 'Traditional Chinese', 'Simplified Chinese', 'Finnish',
             'Swedish', 'Danish', 'Norwegian', 'Polish', 'Portuguese (Brazil)', 'English (UK)', 'Turkish',
             'Spanish (Latin America)', 'Arabic', 'French (Canada)', 'Czech', 'Hungarian', 'Greek', 'Romanian', 'Thai',
             'Vietnamese', 'Indonesian', 'Ukrainian')

LOCK_GPU = ('Overtime sets this for NHL 19: it stops graphical glitches, and every player in an online match needs '
            'the same value.')
LOCK_NETWORK = ('Overtime sets the network for online play: the ShadNet sign-in and servers come from Setup and the '
                'Multiplayer tab.')
LOCK_REDZONE = ('On for Intel CPUs: Overtime turns it on so the game does its math like an AMD CPU, which online '
                'matches with AMD players need.')
WARN_FULLSCREEN = ("Exclusive fullscreen hides the Overtime HUD (chat, results, connection). Online matches play "
                   "borderless anyway.")


class SettingsError(RuntimeError):
    pass


def _f(tab, group, sec, key, label, kind, default, help, **kw):
    return {'id': f'{sec}.{key}', 'tab': tab, 'group': group, 'sec': sec, 'key': key, 'label': label,
            'kind': kind, 'default': default, 'help': help, **kw}


def _opts(*pairs):
    return [{'value': v, 'label': lab} for v, lab in pairs]


DEVICE_HELP = {
    'main': 'Where the game sound plays. Default Device follows the Windows default.',
    'padSpk': "The controller speaker's sound. Default Device plays it on your speakers.",
    'mic': 'The microphone the game hears. None turns it off.',
}

FIELDS = [
    # --- General ---
    _f('General', 'System', 'General', 'console_language', 'Console language', 'select', 1,
       'The language the game is told the console uses. NHL 19 shows its menus in it where it has it.',
       options=_opts(*enumerate(LANGUAGES))),
    _f('General', 'System', 'General', 'redzone_patches', 'Red Zone CPU patches', 'check', False,
       'Lets shadPS4 patch CPU instructions when the game loads (Windows).'),
    _f('General', 'System', 'General', 'show_splash', 'Splash screen at start', 'check', False,
       "Shows the game's splash picture while NHL 19 starts."),
    _f('General', 'Volume', 'General', 'volume_slider', 'Volume', 'slider', 100,
       "The game's volume in shadPS4. 100 % is the game's own level.", min=0, max=500, unit='%'),
    _f('General', 'Audio', 'Audio', 'audio_backend', 'Audio engine', 'select', 0,
       'SDL works on most PCs. OpenAL is the other engine shadPS4 has: try it if the sound crackles.',
       options=_opts((0, 'SDL'), (1, 'OpenAL'))),
    *[_f('General', 'Audio', 'Audio', f'{eng}_{dev}', label, 'device', DEFAULT_DEVICE, DEVICE_HELP[part],
         device=kind, none=part == 'mic', show_if={'Audio.audio_backend': n})
      for eng, n in (('sdl', 0), ('openal', 1))
      for dev, part, label, kind in (('main_output_device', 'main', 'Audio device', 'render'),
                                     ('padSpk_output_device', 'padSpk', 'Controller speaker', 'render'),
                                     ('mic_device', 'mic', 'Microphone', 'capture'))],
    # --- Graphics ---
    _f('Graphics', 'Graphics device', 'Vulkan', 'gpu_id', 'Graphics card', 'gpu', -1,
       'Auto picks the fastest graphics card. The numbers follow the order Vulkan lists the cards in.'),
    _f('Graphics', 'Graphics device', 'GPU', 'null_gpu', 'NULL GPU (no picture)', 'check', False,
       'Draws nothing: only for testing the emulator. NHL 19 shows a black window.'),
    _f('Graphics', 'Video', 'GPU', 'full_screen_mode', 'Display mode', 'select', gamesetup.DISPLAY_DEFAULT,
       'Fullscreen (Borderless) fills the screen and lets the Overtime HUD show over the game. Fullscreen takes the '
       'screen for the game alone. F11 switches in the game.',
       options=_opts(*((m, m) for m in gamesetup.DISPLAY_MODES)), warn={'Fullscreen': WARN_FULLSCREEN}),
    _f('Graphics', 'Video', 'GPU', 'present_mode', 'Present mode', 'select', 'Mailbox',
       'How frames reach the screen. Mailbox: smooth with little delay. FIFO: strict V-Sync. Immediate: the least '
       'delay, can tear.',
       options=_opts(('Mailbox', 'Mailbox (V-Sync)'), ('Fifo', 'FIFO (V-Sync)'), ('Immediate', 'Immediate (no V-Sync)'))),
    _f('Graphics', 'Video', 'GPU', 'window_width', 'Window width', 'number', 1280,
       'The window size in Windowed mode, and the size it goes back to from fullscreen.', min=0, max=9999),
    _f('Graphics', 'Video', 'GPU', 'window_height', 'Window height', 'number', 720,
       'The window size in Windowed mode, and the size it goes back to from fullscreen.', min=0, max=9999),
    _f('Graphics', 'Video', 'GPU', 'hdr_allowed', 'HDR', 'check', False,
       'HDR output, on an HDR monitor with HDR on in Windows.'),
    _f('Graphics', 'Upscaling', 'GPU', 'fsr_enabled', 'FSR upscaling', 'check', False,
       'AMD FidelityFX Super Resolution: scales the picture up to the window size.'),
    _f('Graphics', 'Upscaling', 'GPU', 'rcas_enabled', 'RCAS sharpening', 'check', True,
       'Sharpens the picture after FSR.', show_if={'GPU.fsr_enabled': True}),
    _f('Graphics', 'Upscaling', 'GPU', 'rcas_attenuation', 'Sharpening softness', 'slider', 250,
       'How much RCAS holds back: 0 is the sharpest, higher is softer.', min=0, max=3000, scale=1000, digits=2,
       show_if={'GPU.fsr_enabled': True, 'GPU.rcas_enabled': True}),
    # --- User ---
    _f('User', 'Trophies', 'General', 'trophy_popup_disabled', 'Hide trophy pop-ups', 'check', False,
       'No pop-up when a trophy unlocks.'),
    _f('User', 'Trophies', 'General', 'trophy_notification_side', 'Pop-up side', 'select', 'right',
       'Where trophy pop-ups appear.',
       options=_opts(('top', 'Top'), ('left', 'Left'), ('right', 'Right'), ('bottom', 'Bottom'))),
    _f('User', 'Trophies', 'General', 'trophy_notification_duration', 'Pop-up time (seconds)', 'number', 6.0,
       'How long a trophy pop-up stays.', min=0, max=60, step=0.5, real=True),
    # --- Input ---
    _f('Input', 'Controller', 'Input', 'motion_controls_enabled', 'Motion controls', 'check', True,
       "Passes the controller's motion sensor to the game. NHL 19 doesn't use it."),
    _f('Input', 'Controller', 'Input', 'background_controller_input', 'Controller in the background', 'check', False,
       "The game keeps reading the controller while its window isn't in front."),
    _f('Input', 'Mouse cursor', 'Input', 'cursor_state', 'Hide the cursor', 'select', 1,
       'When the mouse cursor hides over the game window.',
       options=_opts((0, 'Never'), (1, 'When idle'), (2, 'Always'))),
    _f('Input', 'Mouse cursor', 'Input', 'cursor_hide_timeout', 'Idle time (seconds)', 'number', 5,
       'Seconds without a mouse move before the cursor hides.', min=0, max=3600,
       show_if={'Input.cursor_state': 1}),
    _f('Input', 'Devices', 'Input', 'usb_device_backend', 'USB device', 'select', 0,
       'Real passes your own USB devices to the game. The toy portals are for other games.',
       options=_opts((0, 'Real'), (1, 'Skylanders Portal'), (2, 'Infinity Base'), (3, 'Dimensions Toypad'))),
    # --- Network (Overtime's) ---
    _f('Network', 'Network', 'Network', 'connected_to_network', 'Network connected', 'check', False,
       'Tells the game the console is online.', lock=LOCK_NETWORK),
    _f('Network', 'Network', 'Network', 'shad_net_enabled', 'ShadNet', 'check', False,
       "shadPS4's online service: the sign-in the game asks for.", lock=LOCK_NETWORK),
    _f('Network', 'Network', 'Network', 'enable_upnp', 'UPnP', 'check', True,
       'Asks the router to open the ports the game needs.', lock=LOCK_NETWORK),
    _f('Network', 'Network', 'Network', 'disable_https', 'Disable HTTPS', 'check', False,
       'Plain HTTP instead of HTTPS for the game web requests.', lock=LOCK_NETWORK),
    _f('Network', 'Servers', 'Network', 'shadnet_server', 'ShadNet server', 'text', gamesetup.SERVERS['shadnet_server'],
       'The ShadNet server address.', lock=LOCK_NETWORK),
    _f('Network', 'Servers', 'Network', 'shadnet_webapi_server', 'ShadNet web server', 'text',
       gamesetup.SERVERS['shadnet_webapi_server'], "The ShadNet web address.", lock=LOCK_NETWORK),
    _f('Network', 'Servers', 'Network', 'p2p_port', 'P2P port', 'number', 3658,
       'The port for direct connections between players (0: any free port).', min=0, max=65535, lock=LOCK_NETWORK),
    # --- Log ---
    _f('Log', 'Log', 'Log', 'enable', 'Logging', 'check', True,
       "Writes shadPS4's log (log\\shad_log.txt). A crash or desync report needs it. Online matches use their own "
       'log settings and put yours back after.'),
    _f('Log', 'Log', 'Log', 'separate', 'One log per game', 'check', False, 'A log file for each game.'),
    _f('Log', 'Log', 'Log', 'sync', 'Write at once', 'check', True,
       'Writes each line right away, so a crash keeps the last lines. A little slower.'),
    _f('Log', 'Log', 'Log', 'append', 'Add to the last log', 'check', False,
       'Keeps the last log and adds to it, instead of starting a new one.'),
    _f('Log', 'Log', 'Log', 'skip_duplicate', 'Skip repeated lines', 'check', True,
       'A line that repeats is written once.'),
    _f('Log', 'Log', 'Log', 'max_skip_duration', 'Skip repeats for up to (ms)', 'number', 5000,
       'How long a repeated line stays skipped.', min=0, max=9999999, show_if={'Log.skip_duplicate': True}),
    _f('Log', 'Log', 'Log', 'size_limit', 'Size limit (MB)', 'number', 104857600,
       'The log stops growing at this size.', min=0, max=999999999, scale=1048576, digits=0),
    _f('Log', 'Filter', 'Log', 'filter', 'Filter', 'text', '',
       'Which messages to keep, for example *:Info Render:Error. Empty keeps the default.'),
    # --- Debug ---
    *[_f('Debug', group, sec, key, label, 'check', default,
         'For finding emulator bugs: it slows the game down. Leave it off to play.', **kw)
      for group, sec, key, label, default, kw in (
          ('General', 'GPU', 'dump_shaders', 'Dump shaders', False, {}),
          ('General', 'Debug', 'debug_dump', 'Debug dump', False, {}),
          ('General', 'Vulkan', 'renderdoc_enabled', 'RenderDoc', False, {}),
          ('General', 'GPU', 'copy_gpu_buffers', 'Copy GPU command buffers', False, {}),
          ('Advanced', 'Debug', 'shader_collect', 'Collect shaders', False, {}),
          ('Advanced', 'Vulkan', 'vkcrash_diagnostic_enabled', 'Crash diagnostics', False, {}),
          ('Advanced', 'Vulkan', 'vkhost_markers', 'Host debug markers', False, {}),
          ('Advanced', 'Vulkan', 'vkguest_markers', 'Guest debug markers', False, {}),
          ('Vulkan validation', 'Vulkan', 'vkvalidation_enabled', 'Vulkan validation layers', False, {}),
          ('Vulkan validation', 'Vulkan', 'vkvalidation_core_enabled', 'Core checks', True,
           {'show_if': {'Vulkan.vkvalidation_enabled': True}}),
          ('Vulkan validation', 'Vulkan', 'vkvalidation_sync_enabled', 'Sync checks', False,
           {'show_if': {'Vulkan.vkvalidation_enabled': True}}),
          ('Vulkan validation', 'Vulkan', 'vkvalidation_gpu_enabled', 'GPU-assisted checks', False,
           {'show_if': {'Vulkan.vkvalidation_enabled': True}}))],
    # --- Experimental ---
    _f('Experimental', 'GPU', 'GPU', 'readbacks_mode', 'Readbacks', 'select', 0,
       'How shadPS4 copies GPU results back for the game. Precise is the most exact.',
       options=_opts((0, 'Disabled'), (1, 'Relaxed'), (2, 'Precise')), lock=LOCK_GPU),
    _f('Experimental', 'GPU', 'GPU', 'readback_linear_images_enabled', 'Readback linear images', 'check', False,
       'Copies linear images back too.', lock=LOCK_GPU),
    _f('Experimental', 'GPU', 'GPU', 'direct_memory_access_enabled', 'Direct memory access', 'check', False,
       'Lets the GPU read game memory directly. Faster on some games, glitches on others.'),
    _f('Experimental', 'GPU', 'Vulkan', 'pipeline_cache_enabled', 'Shader cache', 'check', False,
       'Keeps compiled shaders on disk: fewer stutters after the first time.'),
    _f('Experimental', 'GPU', 'Vulkan', 'pipeline_cache_archived', 'Compress the shader cache', 'check', False,
       'Keeps the shader cache in one zip file.', show_if={'Vulkan.pipeline_cache_enabled': True}),
    _f('Experimental', 'Console', 'General', 'neo_mode', 'PS4 Pro mode', 'check', False,
       'Runs the game as on a PS4 Pro. Online matches play with it off.'),
    _f('Experimental', 'Console', 'General', 'dev_kit_mode', 'Devkit console mode', 'check', False,
       'Runs the game as on a developer console.'),
    _f('Experimental', 'Console', 'General', 'extra_dmem_in_mbytes', 'Additional DMem (MB)', 'number', 0,
       'Extra memory for the game. 1440p needs 3500 MB or more: Overtime sets it with the Resolution choice.',
       min=0, max=100000),
    _f('Experimental', 'Console', 'GPU', 'vblank_frequency', 'Vblank (Hz)', 'number', 60,
       'The game paces its frames by this: 60 Hz is right for NHL 19. Online matches always use 60 Hz.',
       min=60, max=240),
]
BY_ID = {f['id']: f for f in FIELDS}
DISPLAY_ID = 'GPU.full_screen_mode'


# ---- devices (shown as choices; the current value is always one of them) -------------------------------------------
_CACHE = {}


def _audio_endpoints(kind):
    """Windows' active audio devices ('render' or 'capture') by the name SDL uses: "<device> (<interface>)"."""
    if sys.platform != 'win32':
        return []
    key = 'audio-' + kind
    if key not in _CACHE:
        names = []
        try:
            import winreg
            sep = '\\'
            base = sep.join(('SOFTWARE', 'Microsoft', 'Windows', 'CurrentVersion', 'MMDevices', 'Audio',
                             'Render' if kind == 'render' else 'Capture'))
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
                for i in range(winreg.QueryInfoKey(root)[0]):
                    try:
                        with winreg.OpenKey(root, winreg.EnumKey(root, i)) as dev:
                            if winreg.QueryValueEx(dev, 'DeviceState')[0] != 1:
                                continue
                            with winreg.OpenKey(dev, 'Properties') as props:
                                desc = winreg.QueryValueEx(props, '{a45c254e-df1c-4efd-8020-67d146a850e0},2')[0]
                                try:
                                    face = winreg.QueryValueEx(props, '{b3f8fa53-0004-438e-9003-51a46e139bfc},6')[0]
                                except OSError:
                                    face = ''
                        names.append(f'{desc} ({face})' if face else desc)
                    except OSError:
                        continue
        except (OSError, ImportError):
            names = []
        _CACHE[key] = sorted(set(n for n in names if isinstance(n, str) and n.strip()))
    return _CACHE[key]


def _gpus():
    """The graphics cards Windows lists (virtual displays left out); names only, for the help text."""
    if sys.platform != 'win32':
        return []
    if 'gpus' not in _CACHE:
        try:
            out = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                                  'Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }'],
                                 capture_output=True, text=True, timeout=20,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
        except (OSError, subprocess.SubprocessError):
            out = ''
        skip = ('virtual', 'basic display', 'basic render', 'remote', 'mirror', 'indirect')
        _CACHE['gpus'] = [n.strip() for n in out.splitlines()
                          if n.strip() and not any(s in n.lower() for s in skip)]
    return _CACHE['gpus']


def _choices(f, value):
    """The select choices of a device or graphics card field, with the current value always among them."""
    if f['kind'] == 'gpu':
        cards = _gpus()
        opts = [{'value': -1, 'label': 'Auto'}] + [{'value': i, 'label': f'Card {i}'}
                                                    for i in range(max(len(cards), 1))]
        if isinstance(value, int) and not any(o['value'] == value for o in opts):
            opts.append({'value': value, 'label': f'Card {value}'})
        return opts, (f"This PC: {', '.join(cards)}." if cards else '')
    names = [DEFAULT_DEVICE] + (['None'] if f.get('none') else [])
    if f['key'].startswith('sdl_'):
        names += _audio_endpoints(f['device'])
    if isinstance(value, str) and value and value not in names:
        names.append(value)
    return [{'value': n, 'label': n} for n in names], ''


# ---- read ----------------------------------------------------------------------------------------------------------
def _load(path):
    try:
        with open(path, encoding='utf-8-sig') as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def _value_in(cfg, f):
    """The field's value in one config file, or None. Network keys: "Network" first, then "General" (older home)."""
    if f['sec'] == 'Network':
        return gamesetup._net_value(cfg, f['key'])
    sec = cfg.get(f['sec'])
    return sec.get(f['key']) if isinstance(sec, dict) else None


def locks():
    """{field id: reason} for the keys Overtime sets on this PC now."""
    out = {f['id']: f['lock'] for f in FIELDS if f.get('lock')}
    if gamesetup.amd_math_needed():
        out['General.' + gamesetup.AMD_MATH_KEY] = LOCK_REDZONE
    return out


def view(user_dir, resolution=1080):
    """What the Game settings view shows: the tabs, every field with its value (game file, else config.json, else the
    emulator's default) and whether the game file sets it, the locks, and whether a save would be refused now."""
    game = _load(gamesetup.custom_config_path(user_dir))
    common = _load(os.path.join(user_dir, 'config.json'))
    locked = locks()
    fields = []
    for f in FIELDS:
        own = _value_in(game, f)
        value = own if own is not None else _value_in(common, f)
        if value is None:
            value = f['default']
        if f['id'] == DISPLAY_ID:
            value = gamesetup.display_mode()     # the app's choice: Patch and Play write it
        out = {k: v for k, v in f.items() if k not in ('lock', 'device', 'none')}
        out.update(value=value, own=own is not None, lock=locked.get(f['id'], ''))
        if f['kind'] in ('device', 'gpu'):
            out['options'], note = _choices(f, value)
            if note:
                out['help'] = f"{f['help']} {note}"
        if f['id'] == 'General.' + gamesetup.DMEM_KEY and resolution == 1440:
            out['min'] = gamesetup.DMEM_1440
        fields.append(out)
    return {'tabs': list(TABS), 'fields': fields, 'path': gamesetup.custom_config_path(user_dir),
            'blocked': blocked()}


def blocked():
    """Why a save would be refused now, or ''."""
    if overlay.emulator_running():
        return 'Close NHL 19 first: shadPS4 reads these settings when the game starts.'
    if matchsetup.active():
        return 'A match is set up: change the settings after it.'
    return ''


# ---- save ----------------------------------------------------------------------------------------------------------
def coerce(f, v, resolution=1080):
    """The value to store for field `f`, or SettingsError."""
    label = f['label']
    kind = f['kind']
    if kind == 'check':
        if not isinstance(v, bool):
            raise SettingsError(f'{label}: on or off')
        return v
    if kind == 'select':
        for o in f['options']:
            if not isinstance(v, bool) and str(o['value']) == str(v):
                return o['value']
        raise SettingsError(f'{label}: not one of the choices')
    if kind in ('number', 'slider', 'gpu'):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise SettingsError(f'{label}: a number')
        if kind == 'gpu':
            if v != int(v) or v < -1 or v > 63:
                raise SettingsError(f'{label}: not one of the choices')
            return int(v)
        v = float(v) if f.get('real') else round(v)
        low = f.get('min', 0)
        if f['id'] == 'General.' + gamesetup.DMEM_KEY and resolution == 1440:
            low = gamesetup.DMEM_1440
        if not low <= v <= f.get('max', low):
            shown = f.get('scale') or 1
            raise SettingsError(f'{label}: from {low / shown:g} to {f["max"] / shown:g}')
        return v
    if kind in ('text', 'device'):
        if not isinstance(v, str) or len(v) > MAX_TEXT or any(ord(c) < 32 for c in v):
            raise SettingsError(f'{label}: a line of text up to {MAX_TEXT} characters')
        return v.strip() if kind == 'text' else v
    raise SettingsError(f'{label}: cannot be set here')


def _backup(path):
    """A copy of the game file before a write (the newest BACKUPS_KEPT kept)."""
    if not os.path.isfile(path):
        return None
    name = os.path.basename(path)
    folder = paths.app_dir('backups', 'emusettings')
    dest = os.path.join(folder, datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f-') + name)
    gamesetup._write(dest, gamesetup._read(path))
    for old in sorted(glob.glob(os.path.join(folder, '*-' + name)))[:-BACKUPS_KEPT]:
        try:
            os.remove(old)
        except OSError:
            pass
    return dest


def save(user_dir, changes, resolution=1080):
    """Write the changed fields ({field id: value}) into the game's own config file. Returns the list of field ids
    written. Refused while the game runs or a match is set up, for a locked or unknown field and a bad value; nothing
    is written then. The display mode also becomes the app's choice (gamesetup.set_display)."""
    if not isinstance(changes, dict) or not changes:
        raise SettingsError('Nothing changed.')
    why = blocked()
    if why:
        raise SettingsError(why)
    locked = locks()
    values = {}
    for fid, v in changes.items():
        f = BY_ID.get(fid)
        if f is None:
            raise SettingsError(f'Unknown setting: {fid}')
        if fid in locked:
            raise SettingsError(f"{f['label']} is set by Overtime.")
        values[fid] = coerce(f, v, resolution)
    path = gamesetup.custom_config_path(user_dir)
    try:
        cfg = gamesetup._game_config(path, user_dir)    # a new file starts from config.json; a broken one is refused
    except gamesetup.SetupError as err:
        raise SettingsError(str(err))
    for fid, v in values.items():
        f = BY_ID[fid]
        sec = cfg.setdefault(f['sec'], {})
        if not isinstance(sec, dict):
            raise SettingsError(f'{path}: "{f["sec"]}" is not a section; fix or delete the file first')
        sec[f['key']] = v
        if fid == DISPLAY_ID:
            sec['full_screen'] = v != 'Windowed'
    _backup(path)
    gamesetup._write(path, json.dumps(cfg, indent=4).encode('utf-8'))
    if DISPLAY_ID in values:
        gamesetup.set_display(values[DISPLAY_ID])   # after the write: a failed one leaves the app's choice as it was
    return sorted(values)
