"""Where things are: the game, the emulator's saves, and the app's own folder (settings, cache, backups)."""
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


def app_dir(*parts):
    path = os.path.join(app_home(), *parts)
    os.makedirs(os.path.dirname(path) if os.path.splitext(path)[1] else path, exist_ok=True)
    return path
