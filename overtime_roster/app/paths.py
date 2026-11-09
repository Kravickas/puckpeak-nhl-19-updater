"""Where things are: the game, the emulator's saves, and the app's own folder (settings, cache, backups)."""
import json
import os
import sys
import tempfile

GAME_DIR = r'D:\PS4\NHL 19'
SAVE_SUBDIR = os.path.join('shadPS4', 'home', '1000', 'savedata')   # + the game's title id (CUSA11126, CUSA11116)


def default_game_dir():
    return os.environ.get('OVERTIME_GAME_DIR', GAME_DIR)


def default_save_dir(title='CUSA11126'):
    if 'OVERTIME_SAVE_DIR' in os.environ:
        return os.environ['OVERTIME_SAVE_DIR']
    return os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), SAVE_SUBDIR, title)


def temporary(path):
    """True when the exe should neither use nor remember `path`: it lies in the temp folder (a test's fake emulator
    or save folder that reached the settings; Legacy round 46). Running from source, tests use such paths."""
    if not path or not getattr(sys, 'frozen', False):
        return False
    try:
        tmp = os.path.normcase(os.path.realpath(tempfile.gettempdir()))
        return os.path.commonpath([tmp, os.path.normcase(os.path.realpath(path))]) == tmp
    except (OSError, ValueError):
        return False


def app_home():
    """%APPDATA%\\OvertimeRoster (or OVERTIME_ROSTER_HOME)."""
    home = os.environ.get('OVERTIME_ROSTER_HOME') or os.path.join(
        os.environ.get('APPDATA', os.path.expanduser('~')), 'OvertimeRoster')
    os.makedirs(home, exist_ok=True)
    return home


CACHE = 'cache'
_cache = {}     # app_home() -> the cache folder set in Setup (None: the default), read from settings.json once


def default_cache_dir():
    """%APPDATA%\\OvertimeRoster\\cache: where the downloads and the files made on this PC go unless Setup says."""
    return os.path.join(app_home(), CACHE)


def _cache_setting():
    """The cache folder set in Setup's Folders list (settings.json: setup.custom.cache), or None. Read here, not
    through settings (which imports this module), so every app_dir('cache') sees it from the first call on."""
    try:
        with open(os.path.join(app_home(), 'settings.json'), encoding='utf-8') as f:
            folder = ((json.load(f).get('setup') or {}).get('custom') or {}).get(CACHE)
    except (OSError, ValueError, AttributeError):
        return None
    return folder if isinstance(folder, str) and folder and not temporary(folder) else None


def set_cache_dir(folder):
    """Use `folder` for the cache from now on (None: the default). Setup's Folders list calls it once the files are
    there (cachemove)."""
    _cache[app_home()] = folder or None


def chosen_cache_dir():
    """The cache folder set in Setup, or None (the default)."""
    home = app_home()
    if home not in _cache:
        _cache[home] = _cache_setting()
    return _cache[home]


def cache_dir():
    """The cache folder in use: the one set in Setup while its drive is there (an unplugged drive: the default, so
    nothing writes to a missing disk), else the default."""
    folder = chosen_cache_dir()
    if folder and os.path.isdir(os.path.dirname(os.path.normpath(folder)) or folder):
        return folder
    return default_cache_dir()


def app_dir(*parts):
    if parts and parts[0] == CACHE:        # the cache can be on another drive (Setup, Folders)
        path = os.path.join(cache_dir(), *parts[1:])
    else:
        path = os.path.join(app_home(), *parts)
    os.makedirs(os.path.dirname(path) if os.path.splitext(path)[1] else path, exist_ok=True)
    return path
