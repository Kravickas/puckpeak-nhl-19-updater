"""Linux: the app in the desktop's app menu, and what a Steam Deck needs to show it in Gaming Mode
(docs/plans/proud-shimmying-kettle.md, docs/notes/linux-support.md).

An AppImage is one file the player keeps wherever they like, so nothing puts it in the app menu by itself. On the
player's Yes the app writes the freedesktop entry for it (`~/.local/share/applications/overtime-nhl19.desktop`) and
its icon. The entry names the AppImage by its full path; when the file moves, the next start writes the entry anew
(refresh), and only if the player had said Yes. On SteamOS the app does not touch Steam's own files: it tells the
steps of Steam's "Add a Non-Steam Game". Standard library only; every look at the system can be replaced for tests.
"""
import json
import os
import shutil
import sys

from overtime_core import durable

from .. import APP_NAME
from . import paths

ENTRY = 'overtime-nhl19.desktop'
ICON_NAME = 'overtime-nhl19'
STATE = 'appmenu.json'                  # in the app's folder: {"answer": "yes" | "no", "exec": "<the AppImage>"}
STEAM_STEPS = ('To have it in Gaming Mode: in Desktop Mode open Steam, choose Games > Add a Non-Steam Game to My '
               'Library, and tick ' + APP_NAME + '. It is then in your Library under Non-Steam.')


def data_home(env=None):
    env = os.environ if env is None else env
    return env.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')


def entry_path(env=None):
    return os.path.join(data_home(env), 'applications', ENTRY)


def icon_path(env=None):
    return os.path.join(data_home(env), 'icons', 'hicolor', '256x256', 'apps', ICON_NAME + '.png')


def appimage(env=None, system=None):
    """The AppImage this app runs from (its runtime names it in APPIMAGE), or None: a run from source, another
    system, or an AppImage that was unpacked."""
    env = os.environ if env is None else env
    path = env.get('APPIMAGE') if (system or sys.platform) == 'linux' else None
    return os.path.abspath(path) if path and os.path.isfile(path) else None


def steamos(os_release='/etc/os-release'):
    """Is this SteamOS (a Steam Deck, or another PC with it)?"""
    try:
        with open(os_release, encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines()
    except OSError:
        return False
    ids = [ln.partition('=')[2].strip().strip('"\'').lower() for ln in lines if ln.startswith(('ID=', 'ID_LIKE='))]
    return any('steamos' in value.split() for value in ids)


def _quote(path):
    """A path as the Exec key wants it: in double quotes, with the characters the spec reserves escaped."""
    out = path.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
    return '"' + out.replace('%', '%%') + '"'


def text(exe):
    """The desktop entry of the AppImage at `exe`."""
    return '\n'.join(['[Desktop Entry]', 'Type=Application', f'Name={APP_NAME}',
                      'Comment=NHL 19 on shadPS4: rosters, patch and online play', f'Exec={_quote(exe)}',
                      f'Icon={ICON_NAME}', 'Terminal=false', 'Categories=Game;SportsGame;',
                      'StartupWMClass=OvertimeNHL19', '']) + '\n'


def state():
    try:
        with open(os.path.join(paths.app_home(), STATE), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _keep(data):
    path = os.path.join(paths.app_home(), STATE)
    try:
        os.makedirs(paths.app_home(), exist_ok=True)
        with open(path + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1, sort_keys=True)
        durable.replace(path + '.tmp', path)
    except OSError:
        pass


def install(exe, icon=None, env=None):
    """Write the entry (and the icon, when the app has a PNG) for the AppImage at `exe`. OSError when it cannot."""
    target = entry_path(env)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target + '.tmp', 'w', encoding='utf-8', newline='\n') as f:
        f.write(text(exe))
    os.chmod(target + '.tmp', 0o755)
    os.replace(target + '.tmp', target)
    if icon and os.path.isfile(icon):
        os.makedirs(os.path.dirname(icon_path(env)), exist_ok=True)
        shutil.copyfile(icon, icon_path(env))
    return target


def answer(yes, exe, icon=None, env=None):
    """The player's answer to the one-time question. Yes writes the entry. Returns True when the entry is there."""
    done = False
    if yes and exe:
        try:
            install(exe, icon, env)
            done = True
        except OSError:
            done = False
    _keep({'answer': 'yes' if yes else 'no', 'exec': exe if done else ''})
    return done


def wanted(exe):
    """Should the one-time question be asked now? Only from an AppImage, and only until it was answered."""
    return bool(exe) and state().get('answer') not in ('yes', 'no')


def refresh(exe, icon=None, env=None):
    """The AppImage moved since the player said Yes (or the entry was deleted): write the entry anew. True when it
    wrote."""
    seen = state()
    if not exe or seen.get('answer') != 'yes':
        return False
    if seen.get('exec') == exe and os.path.isfile(entry_path(env)):
        return False
    return answer(True, exe, icon, env)
