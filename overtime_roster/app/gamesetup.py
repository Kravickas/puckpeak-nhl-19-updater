"""Game setup, the part of the one-click patch outside the data overlay: find shadPS4 and NHL 19, put the Overtime
eboot patch (overtime_core.xmlpatch) into the emulator's patches folder, switch the game's network settings on,
and undo all of it.

The game folder is only read (param.sfo, hashes). Every file written in the emulator's folder is listed in the setup
manifest (`gamesetup.json` in the app's folder) with a copy of what was there before, so `remove` puts each one back
byte for byte, or, when the user changed the file since, only our keys.

shadPS4 keeps its data in `user\\` under its working directory when that folder exists (portable), otherwise in
`%APPDATA%\\shadPS4`. With no `-p` file on the command line it applies every `patches\\<folder>\\` whose
`files.json` lists the game's serial (also when started from the Qt launcher); `-p` skips the folder scan, `-i`
turns it off. A block applies when isEnabled="true", AppElf is the eboot's name and AppVer is the game's APP_VER.
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

from overtime_core import gamefiles, overlay, sfo, xmlpatch

from . import paths

# NHL 19 (US) and the other region's disc (player request 2026-11-01): the same game and eboot as far as known. The
# eboot patch has no hash check, so the other id is taken as the same game; Patch notes the eboot's hash for support.
TITLE_IDS = ('CUSA11126', 'CUSA11116')
TITLE_ID, APP_VER = TITLE_IDS[0], '01.60'
_active = [TITLE_ID]    # the title id of the game folder in use: it names the save folder, the custom config, files.json
EMULATOR_URL = 'https://github.com/shadps4-emu/shadps4-qtlauncher/releases'   # for a player with no shadPS4 yet
LAUNCHER_DATA = 'shadPS4QtLauncher'     # QtLauncher's folder in %APPDATA%: qt_ui.ini, versions.json, versions\
LOCAL_VERSION = 2                       # versions.json: a version added by hand (0 stable, 1 Pre-release)
PATCH_FOLDER, PATCH_FILE = 'Overtime', 'overtime.xml'
NETWORK = {'connected_to_network': True, 'shad_net_enabled': True}  # custom_configs\CUSA11126.json, "General"
DMEM_KEY, DMEM_1440 = 'extra_dmem_in_mbytes', 3500   # "General": what the 1440p block (xmlpatch res1440) needs
# the ShadNet servers the game's "Network" section needs filled (live 2026-11-07: a tester's game-specific Network tab
# was empty and the game stopped at SIGN IN REQUIRED until he typed them); the shared config.json's are used if set
SERVERS = {'shadnet_server': 'srv.shadps4.net:31313', 'shadnet_webapi_server': 'http://srv.shadps4.net:31315'}
MANIFEST = 'gamesetup.json'
FIREWALL_RULE = 'Overtime NHL 19 (shadPS4)'


class SetupError(RuntimeError):
    pass


def active_title():
    """The title id of the game folder the app works on (CUSA11126 until use_game saw another)."""
    return _active[0]


def use_game(game_dir):
    """Work on `game_dir`: its title id names the save folder and the custom config from here on. A folder that is
    not NHL 19 changes nothing."""
    title = read_game(game_dir)['title_id'] if game_dir else None
    if title in TITLE_IDS:
        _active[0] = title
    return _active[0]


def _now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _read(path):
    with open(path, 'rb') as f:
        return f.read()


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.overtime-tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


def _refuse_while_running(running=None):
    if (running or overlay.emulator_running)():
        raise SetupError('shadPS4 is running. Close the game first, then try again.')


# ---- finding things ---------------------------------------------------------------------------------------------

_CUSTOM = {'data': ''}      # the data folder the player set in Setup's Folders list ('' = found)


def set_custom_data(path):
    """The shadPS4 data folder the player set (Setup, Folders, shadPS4 data); '' goes back to finding it."""
    _CUSTOM['data'] = os.path.normpath(path) if path else ''


def custom_data():
    return _CUSTOM['data']


def is_data_dir(path):
    """A shadPS4 data folder: it holds config.json (and is where shadPS4 keeps patches, custom_configs, home, log)."""
    return bool(path) and os.path.isfile(os.path.join(path, 'config.json'))


def emu_user_dir(emu_exe):
    """The emulator's data folder: the one the player set (for their own shadPS4; the Boost exe in the app's folder
    always uses %APPDATA%), else `user\\` next to it (portable; we start it from its own folder), else %APPDATA%."""
    custom = _CUSTOM['data']
    if custom and not (emu_exe and os.path.normcase(os.path.abspath(emu_exe)).startswith(
            os.path.normcase(os.path.abspath(paths.app_home())) + os.sep)):
        return custom
    portable = os.path.join(os.path.dirname(os.path.abspath(emu_exe)), 'user')
    if os.path.isdir(portable):
        return portable
    return appdata_dir()


def appdata_dir():
    return os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'shadPS4')


def reachable_data_dir(path):
    """shadPS4 can be made to use `path`: a folder named `user` (started from its parent) or %APPDATA%\\shadPS4."""
    path = os.path.normcase(os.path.abspath(path))
    return os.path.basename(path) == 'user' or path == os.path.normcase(os.path.abspath(appdata_dir()))


def start_dir(emu_exe):
    """The folder to start shadPS4 from so that it uses emu_user_dir(emu_exe), or None when it cannot. shadPS4 takes
    `user\\` inside the folder it starts from, else %APPDATA%\\shadPS4 (lab 2026-11-07: a start folder's `user\\` wins
    even over one beside the exe). A tester's QtLauncher layout (shadPS4 in V:\\ShadPS4\\ShadPS4\\NHL, data in
    V:\\ShadPS4\\user) started from the exe's folder ran on fresh %APPDATA% data: no patch, ShadNet off, no saves."""
    data = os.path.abspath(emu_user_dir(emu_exe))
    exe_dir = os.path.dirname(os.path.abspath(emu_exe))
    if os.path.basename(os.path.normcase(data)) == 'user':
        return os.path.dirname(data)
    if os.path.normcase(data) == os.path.normcase(os.path.abspath(appdata_dir())):
        for folder in (exe_dir, data):       # a folder without its own `user` folder
            if not os.path.isdir(os.path.join(folder, 'user')):
                return folder
    return None


def _is_emulator(name):
    low = name.lower()
    return low.startswith('shadps4') and low.endswith('.exe') and 'launcher' not in low


def _is_launcher(name):
    low = name.lower()
    return low.startswith('shadps4') and low.endswith('.exe') and 'launcher' in low


def _launcher_data():
    return os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), LAUNCHER_DATA)


def _write_keeping(path, text):
    """Write a QtLauncher file in one step; the first time, the player's own stays next to it as <name>.overtime-backup."""
    backup = path + '.overtime-backup'
    if os.path.exists(path) and not os.path.exists(backup):
        shutil.copy2(path, backup)
    with open(path + '.tmp', 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    os.replace(path + '.tmp', path)


def _read_launcher(data):
    """qt_ui.ini's text as it is, and the versions.json list. ValueError: a file that cannot be read safely."""
    with open(os.path.join(data, 'qt_ui.ini'), encoding='utf-8', newline='') as f:
        ini = f.read()
    try:
        with open(os.path.join(data, 'versions.json'), encoding='utf-8-sig') as f:
            versions = json.load(f)
    except FileNotFoundError:
        versions = []
    if not isinstance(versions, list):
        raise ValueError('versions.json is not a list')
    return ini, versions


def _with_selected(ini, value):
    """qt_ui.ini's text with versionSelected=value in [version_manager]."""
    line = f'versionSelected={value}'
    if re.search(r'^versionSelected=', ini, re.M):
        return re.sub(r'^versionSelected=[^\r\n]*', lambda _m: line, ini, flags=re.M)
    end = '\r\n' if '\r\n' in ini else '\n'
    if re.search(r'^\[version_manager\]', ini, re.M):
        return re.sub(r'^\[version_manager\][^\r\n]*', lambda m: m.group(0) + end + line, ini, count=1, flags=re.M)
    return f'{ini.rstrip()}{end}{end}[version_manager]{end}{line}{end}'


def _selected_in(ini):
    found = re.search(r'^versionSelected=([^\r\n]*)', ini, re.M)
    return found.group(1) if found else ''


def _selected_first(data):
    """What the player had selected before Overtime first wrote qt_ui.ini ('' without its backup)."""
    try:
        with open(os.path.join(data, 'qt_ui.ini.overtime-backup'), encoding='utf-8', newline='') as f:
            return _selected_in(f.read())
    except OSError:
        return ''


def launcher_add(exe, name):
    """QtLauncher lists `exe` as a Local version `name`, as its Version Manager adds one, and selects it. Returns what
    was selected before; None when there is no QtLauncher here. It must not be running: it writes these files back
    when it closes."""
    data = _launcher_data()
    if not os.path.isfile(os.path.join(data, 'qt_ui.ini')):
        return None
    ini, versions = _read_launcher(data)
    path = exe.replace('\\', '/')
    selected = _selected_in(ini)
    if selected == path:        # on already, and the app's own record of it is gone
        selected = _selected_first(data)
    versions = [v for v in versions if not (isinstance(v, dict) and v.get('path') == path)]
    versions.append({'codename': 'Local', 'date': datetime.date.today().isoformat(), 'name': name, 'path': path,
                     'type': LOCAL_VERSION})
    _write_keeping(os.path.join(data, 'versions.json'), json.dumps(versions, indent=4))
    _write_keeping(os.path.join(data, 'qt_ui.ini'), _with_selected(ini, path))
    return selected


def launcher_remove(exe, selected):
    """QtLauncher forgets `exe`; when it is the selected one, `selected` (launcher_add's answer; None: not known, the
    backup tells) is selected again."""
    data = _launcher_data()
    if not os.path.isfile(os.path.join(data, 'qt_ui.ini')):
        return
    ini, versions = _read_launcher(data)
    path = exe.replace('\\', '/')
    _write_keeping(os.path.join(data, 'versions.json'), json.dumps(
        [v for v in versions if not (isinstance(v, dict) and v.get('path') == path)], indent=4))
    if re.search(rf'^versionSelected={re.escape(path)}\s*$', ini, re.M):
        back = _selected_first(data) if selected is None else selected
        _write_keeping(os.path.join(data, 'qt_ui.ini'), _with_selected(ini, back))


def launcher_emulators():
    """The shadPS4 exes QtLauncher knows, the one selected in it first: qt_ui.ini ([version_manager] versionSelected,
    versionPath), its versions.json, its versions folder. Only exes that are still there."""
    data = _launcher_data()
    try:
        with open(os.path.join(data, 'qt_ui.ini'), encoding='utf-8', errors='replace') as f:
            ini = f.read()
    except OSError:
        ini = ''

    def setting(key):           # Qt writes a backslash as two
        m = re.search(rf'^{key}="?(.*?)"?\s*$', ini, re.M)
        return os.path.normpath(m.group(1).replace('\\\\', '\\')) if m and m.group(1) else ''
    paths = [setting('versionSelected')]
    try:
        with open(os.path.join(data, 'versions.json'), encoding='utf-8-sig') as f:
            paths += [os.path.normpath(v['path']) for v in json.load(f) if isinstance(v, dict) and v.get('path')]
    except (OSError, ValueError):
        pass
    for root in (setting('versionPath'), os.path.join(data, 'versions')):
        if root:
            paths += list(_walk(root, 1))
    found, seen = [], set()
    for path in paths:
        key = os.path.normcase(path)
        if key not in seen and _is_emulator(os.path.basename(path)) and os.path.isfile(path):
            seen.add(key)
            found.append(path)
    return found


def resolve_emulator(path):
    """The shadPS4 exe behind what the player picked: that exe, QtLauncher's selected version for the launcher or a
    folder holding it, else the newest shadPS4 exe in the folder. '' when there is none."""
    if os.path.isfile(path):
        name = os.path.basename(path)
        if _is_launcher(name):
            return next(iter(launcher_emulators()), '')
        return path if _is_emulator(name) or emulator_build(path) else ''
    if not os.path.isdir(path):
        return ''
    if any(_is_launcher(os.path.basename(p)) for p in _walk(path, 2)):
        emus = launcher_emulators()
        if emus:
            return emus[0]
    return next(iter(find_emulators([path])), '')


def _update_only(base):
    """True when the game's archives (base and update folder together) are all `patch_*.big`: the update without
    the base game. The art and the database then have nowhere to go (a tester's "art layer: ... its archive is unknown")."""
    names = []
    for root in gamefiles.roots(base):
        try:
            names += [n.lower() for n in os.listdir(os.path.join(root, 'databigs')) if n.lower().endswith('.big')] \
                if root else []
        except OSError:
            continue
    return bool(names) and all(n.startswith('patch_') for n in names)


def around(path, up=1):
    """`path` (a folder, or a file's folder) and up to `up` folders above it: where to look for shadPS4 or NHL 19 next
    to what the player pointed at (a tester, 2026-11-07: "search from the folder i point to, i have nothing in appdata")."""
    if not path:
        return []
    folder = os.path.abspath(path if os.path.isdir(path) else os.path.dirname(path))
    out = [folder]
    for _ in range(up):
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        out.append(parent)
        folder = parent
    return out


def find_emulators(roots=None, depth=2, near=()):
    """shadPS4 executables (not the Qt launcher) under `roots`, newest first. The default roots are the folders
    the emulator's own config lists for games (and their parents), the user's Desktop and Downloads, with QtLauncher's
    versions first: that is the shadPS4 the player runs. `near` (folders around what the player pointed at) comes
    next, before the rest (with nothing in %APPDATA%, the shadPS4 beside the game picked is the one)."""
    first = launcher_emulators() if roots is None else []
    if near:
        known = {os.path.normcase(p) for p in first}
        first += [p for p in find_emulators(list(near), depth) if os.path.normcase(p) not in known]
    if roots is None:
        roots = []
        for d in install_dirs(emu_user_dir('')):
            roots += [d, os.path.dirname(d.rstrip('\\/'))]
        home = os.path.expanduser('~')
        roots += [os.path.join(home, 'Desktop'), os.path.join(home, 'Downloads')]
    found, seen = [], set()
    for root in roots:
        for path in _walk(root, depth):
            if _is_emulator(os.path.basename(path)) and os.path.normcase(path) not in seen:
                seen.add(os.path.normcase(path))
                found.append(path)
    known = {os.path.normcase(p) for p in first}
    return first + sorted((p for p in found if os.path.normcase(p) not in known), key=os.path.getmtime, reverse=True)


def _walk(root, depth):
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    for e in entries:
        try:
            if e.is_file():
                yield e.path
            elif e.is_dir() and depth > 0:
                yield from _walk(e.path, depth - 1)
        except OSError:
            continue


def install_dirs(user_dir):
    """The game folders shadPS4 is set up to look in (config.json, General.install_dirs, enabled ones)."""
    try:
        with open(os.path.join(user_dir, 'config.json'), encoding='utf-8-sig') as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for d in ((cfg.get('General') or {}).get('install_dirs') or []):
        if isinstance(d, dict) and d.get('enabled', True) and d.get('path'):
            out.append(d['path'])
    return out


def read_game(game_dir):
    """What a game folder holds: {'path', 'ok', 'title_id', 'app_ver', 'problem', 'update'}; ok = NHL 19 CUSA11126
    v1.60. With the update in a folder of its own beside the base (`-UPDATE` / `-patch`, either folder picked), the
    version is the update's and 'update' names that folder."""
    base, update = gamefiles.roots(game_dir)
    info = {'path': game_dir, 'ok': False, 'title_id': None, 'app_ver': None, 'problem': None, 'update': update}
    game_dir = update or base
    try:
        values = {e.key: e.value for e in sfo.parse(_read(os.path.join(game_dir, 'sce_sys', 'param.sfo')))}
    except (OSError, sfo.SfoError) as e:
        info['problem'] = f'no readable sce_sys\\param.sfo ({e})'
        return info
    info['title_id'], info['app_ver'] = values.get('TITLE_ID'), values.get('APP_VER')
    if info['title_id'] not in TITLE_IDS:
        info['problem'] = f"this is {info['title_id'] or 'another game'}, not NHL 19 ({' or '.join(TITLE_IDS)})"
    elif info['app_ver'] != APP_VER:
        info['problem'] = f"NHL 19 version {info['app_ver']}; Overtime needs update {APP_VER}"
    elif not os.path.isfile(os.path.join(game_dir, 'eboot.bin')):
        info['problem'] = 'eboot.bin is missing'
    elif _update_only(base):
        info['problem'] = (f"only NHL 19's update files are in {base}: the base game's archives (databigs\\inxp_10.big "
                           "and others) are missing. Pick the folder with the base game, or copy the update into it")
    else:
        info['ok'] = True
    return info


def find_games(user_dir, extra=()):
    """NHL 19 folders in the emulator's game folders (and `extra`), each as read_game() sees it. A base game with its
    update in a folder of its own is one game, listed as the base folder."""
    out, seen = [], set()
    for root in list(extra) + install_dirs(user_dir):
        candidates = [root] + [e.path for e in _scandirs(root)]
        for c in candidates:
            if not os.path.isfile(os.path.join(c, 'sce_sys', 'param.sfo')):
                continue
            base = gamefiles.roots(c)[0]
            if os.path.normcase(base) not in seen:
                seen.add(os.path.normcase(base))
                same = os.path.normcase(base) == os.path.normcase(os.path.abspath(c))
                info = read_game(c if same else base)   # the folder as found, or the base of an update folder
                if info['title_id'] in TITLE_IDS:
                    out.append(info)
    return out


def _scandirs(root):
    try:
        return [e for e in os.scandir(root) if e.is_dir()]
    except OSError:
        return []


def shadnet_users(user_dir):
    """The emulator's users as far as Overtime needs them: [{'user_id', 'name', 'shadnet', 'npid', 'password'}].
    Only these fields are read out of users.json ('password': whether one is filled in); e-mail, password and token
    never leave it."""
    return [_user_row(u) for u in _raw_users(user_dir) if isinstance(u, dict)]


def _raw_users(user_dir):
    try:
        with open(os.path.join(user_dir, 'users.json'), encoding='utf-8-sig') as f:
            users = (json.load(f).get('Users') or {}).get('user') or []
        return users if isinstance(users, list) else []
    except (OSError, ValueError, AttributeError):
        return []


def _user_row(u):
    return {'user_id': u.get('user_id'), 'name': u.get('user_name') or '', 'shadnet': bool(u.get('shadnet_enabled')),
            'npid': u.get('shadnet_npid') or '', 'password': bool(u.get('shadnet_password'))}


# ShadNet accounts: the app makes them through the site's own form endpoint (shadnet.register), the site is the
# fallback (docs/notes/shadnet-protocol.md); an Online ID is 3-16 letters, digits, '-' or '_', and the server
# compares it with its capitals.
SHADNET_REGISTER = 'https://www.shadps4.net/shadnet/register/'
ONLINE_ID = re.compile(r'[A-Za-z0-9_-]{3,16}')
USERS_FILE = 'users.json'


def _player_one(users):
    """The user NHL 19 plays as: player_index 1 (user 1000), else the first one."""
    rows = [u for u in users if isinstance(u, dict)]
    return next((u for u in rows if u.get('player_index') == 1), rows[0] if rows else None)


def shadnet_player(user_dir):
    """shadnet_users' row of the user the game plays as, or None."""
    one = _player_one(_raw_users(user_dir))
    return _user_row(one) if one else None


def shadnet_identity(user_dir, log=None):
    """Who this PC is on ShadNet, as far as it can be proven: {'npid': the Online ID the game plays as, 'account': the
    ShadNet account id, or None, 'state': shadnet_log's, or 'stale'}. The account id counts only from a sign-in of
    that same Online ID: a log from before a change of account says nothing about the new one. (Not by file times:
    shadPS4 rewrites users.json by itself, unchanged, after the log of its run.)"""
    one = shadnet_player(user_dir) or {}
    npid = one.get('npid') or '' if one.get('shadnet') else ''
    log = shadnet_log(user_dir) if log is None else log
    out = {'npid': npid, 'account': None, 'state': (log or {}).get('state')}
    if not log or log.get('state') != 'signed_in' or not npid:
        return out
    if (log.get('npid') or '').casefold() == npid.casefold():
        out['account'] = log.get('account')
    else:
        out['state'] = 'stale'
    return out


def shadnet_check(npid, password):
    """(npid, password) cleaned, or SetupError in words."""
    npid = str(npid or '').strip()
    password = str(password or '')
    if not ONLINE_ID.fullmatch(npid):
        raise SetupError('The Online ID is 3 to 16 letters, digits, - or _ (capitals count).')
    if not password or len(password) > 64 or password != password.strip():
        raise SetupError('Type the ShadNet password (no spaces at the start or end).')
    return npid, password


def shadnet_signin(user_dir, npid, password, running=None):
    """Put the player's own ShadNet account into the user NHL 19 plays as (users.json: Online ID, password, ShadNet
    on; the old sign-in token goes, it belonged to the old account). The file as it was is kept next to it as
    users.json.overtime-<time>. shadPS4 must be closed (it writes the file itself). Returns the Online ID."""
    npid, password = shadnet_check(npid, password)
    _refuse_while_running(running)
    path = os.path.join(user_dir, USERS_FILE)
    try:
        with open(path, 'rb') as f:
            data = f.read()
        doc = json.loads(data.decode('utf-8-sig'))
        users = doc['Users']['user']
    except (OSError, ValueError, KeyError, TypeError):
        raise SetupError('shadPS4 has no users yet. Start shadPS4 once (Setup, Start), close it, then try again.')
    one = _player_one(users)
    if one is None:
        raise SetupError('shadPS4 has no users yet. Start shadPS4 once (Setup, Start), close it, then try again.')
    with open(path + time.strftime('.overtime-%Y%m%d-%H%M%S'), 'wb') as f:
        f.write(data)
    if (one.get('shadnet_npid') or '') != npid:
        one['shadnet_token'] = ''
    one.update(shadnet_npid=npid, shadnet_password=password, shadnet_enabled=True)
    _write(path, json.dumps(doc, indent=4).encode('utf-8'))
    return npid


# shadPS4's log of its last run (it starts a new one at every start): the ShadNet sign-in is near the top
# (docs/notes/shadps4-network.md "ShadNet sign-in").
LOG_FILE = os.path.join('log', 'shad_log.txt')
LOG_HEAD = 1 << 20
_SIGNED_IN = re.compile(rb"ConnectUser: user_id=\d+ signed in npid='([^'\r\n]{0,32})'(?: accountId=(\d{1,12}))?")
_REJECTED = re.compile(rb'Login rejected error code (\d+)')


def shadnet_log(user_dir):
    """What shadPS4's last run said about ShadNet: {'state': 'signed_in' | 'rejected' | 'signed_out' | None,
    'npid', 'account' (the ShadNet account id of that sign-in, or None: the Blaze externalId), 'code', 'when' (the
    log's time, seconds), plus the header's 'branch', 'own_config' (a game-specific config applied), 'shadnet_on',
    'network_on' (None when the header does not say) and 'disabled_globally'}, or None without a log. shadnet_why
    turns it into a sentence. 'rejected': the server refused the
    Online ID or password (code 8: a wrong password, or the Online ID with other capitals); None: the run ended
    before it got that far."""
    path = os.path.join(user_dir, LOG_FILE)
    try:
        with open(path, 'rb') as f:
            head = f.read(LOG_HEAD)
        when = os.path.getmtime(path)
    except OSError:
        return None
    out = {'state': None, 'npid': '', 'account': None, 'code': None, 'when': when}
    signed, refused = _SIGNED_IN.search(head), _REJECTED.search(head)
    if signed:
        out.update(state='signed_in', npid=signed.group(1).decode('ascii', 'replace'),
                   account=int(signed.group(2)) if signed.group(2) else None)
    elif refused:
        out.update(state='rejected', code=int(refused.group(1)))
    elif b'no users connected to shadNet' in head:
        out['state'] = 'signed_out'
    # the header says which build ran and with what settings (why there may be no sign-in to read)
    branch = _BRANCH.search(head)

    def flag(rx):
        m = rx.search(head)
        return m.group(1) == b'true' if m else None
    out.update(branch=branch.group(1).decode('ascii', 'replace') if branch else '', own_config=flag(_CFG_OWN),
               shadnet_on=flag(_CFG_SHADNET), network_on=flag(_CFG_NET),
               disabled_globally=b'shadNet disabled globally' in head)
    return out


_BRANCH = re.compile(rb'Run: Branch ([\x21-\x7e]{1,60})')
_CFG_OWN = re.compile(rb'Game-specific config used: (true|false)')
_CFG_SHADNET = re.compile(rb'isShadNetEnabled: (true|false)')
_CFG_NET = re.compile(rb'isConnectedToNetwork: (true|false)')


def shadnet_why(log):
    """One sentence on why the ShadNet id is not known, with the next step, from shadnet_log's answer; '' when the
    log holds the id."""
    if log is None:
        return ('shadPS4 has no log yet. Start NHL 19 from Setup, let it reach the main menu, then press Check again.')
    if log.get('account'):
        return ''
    if log.get('state') == 'rejected':
        return (f'ShadNet refused the sign-in (code {log.get("code")}): the Online ID or the password is wrong, the '
                "Online ID has other capitals, or a new account's e-mail is not confirmed yet. Fix it under ShadNet on "
                'the Multiplayer tab, then start the game again.')
    if log.get('shadnet_on') is False or log.get('disabled_globally'):
        own = ' (no game settings were used, so the shared ones applied)' if log.get('own_config') is False else ''
        net = ' and the network' if log.get('network_on') is False else ''
        return (f'The last run had ShadNet{net} turned off{own}. Turn it on in the Online card, start NHL 19 from '
                'Setup, then press Check again.')
    if log.get('state') == 'signed_in':
        return (f'The game signed in as {log.get("npid") or "your Online ID"}, but this shadPS4 build does not print '
                'the account id. Install the NHL 19 build of shadPS4 in Setup, then start the game again.')
    if log.get('state') == 'signed_out':
        return ('ShadNet was on, but nobody was signed in. Check the ShadNet user in the Online card, start the game '
                'again, then press Check again.')
    return ('The last run ended before it signed in. Start NHL 19 from Setup, wait for the main menu, then press '
            'Check again.')


def save_dir(user_dir, user_id=1000):
    """The game's save folder: in shadPS4's home folder, `home\\` in its data folder unless its settings move it
    (Paths tab, "Home Folder Location": config.json General.home_dir; a tester keeps it on another drive)."""
    try:
        with open(os.path.join(user_dir, 'config.json'), encoding='utf-8-sig') as f:
            home = ((json.load(f).get('General') or {}).get('home_dir') or '').strip()
    except (OSError, ValueError, AttributeError):
        home = ''
    return os.path.join(os.path.normpath(home) if home else os.path.join(user_dir, 'home'), str(user_id), 'savedata',
                        active_title())


# ---- which shadPS4 build (its exe carries the version block the log prints at start) -------------------------
# 'v0.20.1 WIP', the 40-hex revision, the branch, the short description, the remote: NUL-separated, in .rdata
# (log: "Starting shadps4 emulator v0.21.1 WIP", "Revision ...", "Branch main"). Any build will do: the network code
# is the same in the official one and the NHL19-Build fork (docs/notes/shadps4-network.md).
_SCM = re.compile(rb'(?<![\x20-\x7e])(\d+\.\d+\.\d+[ A-Za-z0-9.+-]{0,24})\x00+([0-9a-f]{40})\x00+([\x20-\x7e]{1,80})'
                  rb'\x00+([\x20-\x7e]{1,80})\x00+(https?://[\x20-\x7e]{1,200})\x00')
_builds = {}            # (path, size, mtime) -> emulator_build()


def emulator_build(emu_exe):
    """{'version', 'rev', 'branch', 'remote'} of a shadPS4 exe, or None when the exe carries no version block (another
    program, an exe we cannot read). Reads the exe (about 60 MB) once per size and time."""
    try:
        st = os.stat(emu_exe)
    except OSError:
        return None
    key = (os.path.normcase(os.path.abspath(emu_exe)), st.st_size, st.st_mtime_ns)
    if key not in _builds:
        try:
            data = _read(emu_exe)
        except OSError:
            return None
        _builds[key] = _scm_block(data)
    return dict(_builds[key]) if _builds[key] else None


def _scm_block(data):
    """The version block, looked for only around each NUL + http in the file (a whole-file search takes 0.5 s)."""
    i = data.find(b'\x00http')
    while i >= 0:
        for m in _SCM.finditer(data, max(0, i - 400), i + 220):
            if m.start(5) == i + 1:
                version, rev, branch, _desc, remote = (g.decode('ascii', 'replace') for g in m.groups())
                return {'version': version.strip(), 'rev': rev, 'branch': branch, 'remote': remote}
        i = data.find(b'\x00http', i + 1)
    return None


# ---- the Overtime server (the game's first call: the redirector) -------------------------------------------------
REDIRECTOR_PORT = 42230
REDIRECTOR_PATH = '/redirector/getServerInstance'


def server_answers(host, port=REDIRECTOR_PORT, timeout=4, tls=True):
    """(True, '') when `host` answers the game's first call as the Overtime server does (POST the redirector's
    getServerInstance, as deploy/README.md does it with curl -k: the game skips the certificate check too), else
    (False, why). A few seconds at most: call it in a job."""
    import http.client
    import ssl
    if tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request('POST', REDIRECTOR_PATH, body=b'<serverinstancerequest/>',
                     headers={'Content-Type': 'application/xml', 'User-Agent': 'OvertimeRoster setup check'})
        r = conn.getresponse()
        body = r.read(64 * 1024)
    except (OSError, http.client.HTTPException, ValueError) as err:
        return False, str(err) or type(err).__name__
    finally:
        conn.close()
    if r.status == 200 and b'serverinstanceinfo' in body.lower():
        return True, ''
    return False, f'HTTP {r.status}, not the Overtime server'


def custom_config_path(user_dir):
    return os.path.join(user_dir, 'custom_configs', active_title() + '.json')


def _net_value(cfg, key):
    """What shadPS4 reads for a network key in one config file: newer builds keep it in "Network" and take it from
    there when it is present; "General" is the older home and still read when "Network" lacks the key."""
    network = cfg.get('Network')
    if isinstance(network, dict) and key in network:
        return network[key]
    general = cfg.get('General')
    return general.get(key) if isinstance(general, dict) else None


def network_settings(user_dir):
    """The network keys as the game will see them (its custom config over config.json): {key: value or None}."""
    values = {k: None for k in NETWORK}
    for path in (os.path.join(user_dir, 'config.json'), custom_config_path(user_dir)):
        try:
            with open(path, encoding='utf-8-sig') as f:
                cfg = json.load(f)
            found = {k: _net_value(cfg, k) for k in NETWORK}
        except (OSError, ValueError, AttributeError):
            continue
        values.update({k: v for k, v in found.items() if v is not None})
    return values


def network_on(user_dir):
    """True when the game will start with Overtime's network keys on (network_settings)."""
    values = network_settings(user_dir)
    return all(values[k] == v for k, v in NETWORK.items())


def _both_on(cfg):
    """True when the config carries Overtime's network keys in "General" and in "Network", and "Network" names the
    ShadNet servers (install writes all of it)."""
    return (all(isinstance(cfg.get(s), dict) and cfg[s].get(k) == v for s in ('General', 'Network')
                for k, v in NETWORK.items())
            and all(isinstance(cfg['Network'].get(k), str) and cfg['Network'][k].strip() for k in SERVERS))


def _servers(user):
    """The ShadNet servers for a game config: the shared config.json's where it names them, else SERVERS."""
    try:
        with open(os.path.join(user, 'config.json'), encoding='utf-8-sig') as f:
            shared = json.load(f).get('Network')
    except (OSError, ValueError, AttributeError):
        shared = None
    shared = shared if isinstance(shared, dict) else {}
    return {k: shared[k] if isinstance(shared.get(k), str) and shared[k].strip() else v for k, v in SERVERS.items()}


def network_written(user_dir):
    """True when the game's own config carries the network keys in both sections (else the next start writes them)."""
    try:
        with open(custom_config_path(user_dir), encoding='utf-8-sig') as f:
            return _both_on(json.load(f))
    except (OSError, ValueError, AttributeError):
        return False


def _keys_on(path):
    """True when the config at `path` gives Overtime's network keys the values we need (status: only those keys are ours)."""
    try:
        with open(path, encoding='utf-8-sig') as f:
            cfg = json.load(f)
        # off in either section counts as off (builds differ in which one they read)
        sections = [cfg[s] for s in ('General', 'Network') if isinstance(cfg.get(s), dict)]
        return all(_net_value(cfg, k) == v and all(s.get(k, v) == v for s in sections) for k, v in NETWORK.items())
    except (OSError, ValueError, AttributeError):
        return False


def patch_fingerprint(emu_exe):
    """What the lobby compares between the two games (overtime_server/lobby.py _patch_status): a short hash of the patch
    file installed for this emulator, or 'none' when it is missing or changed (switched-off network keys do not count:
    the game start turns them on). Two games that play each other must carry the same patch, or they desync. Only what
    reaches the other game counts (xmlpatch.netplay_fingerprint): 1080p against 1440p is one patch (live 2026-11-08,
    the whole-file hash of 0.70.7 called them different)."""
    st = status(emu_exe)
    problems = [p for p in st.get('problems') or () if not str(p).startswith('network switched off')]
    text = installed_patch() if st.get('installed') and not problems else None
    if not text:
        return 'none'
    try:
        return xmlpatch.netplay_fingerprint(text)
    except xmlpatch.PatchError:
        return 'none'


CRLF, LF = chr(13) + chr(10), chr(10)


_IDENTITY = {}


def game_identity(game_dir):
    """What the lobby logs and compares about this install besides the patch (overtime_server/lobby.py _game):
    {'title': CUSA11126 | CUSA11116, 'data': a short hash of the disc maps (which release's archives these are),
    'layers': the data patch layers on}. Live 2026-11-08: pairs desynced with installs nobody could see."""
    info = read_game(game_dir)
    out = {'title': info.get('title_id') or '?'}
    base, update = gamefiles.roots(game_dir)
    names = [os.path.join(update or base, n) for n in ('sce_discmap.plt', 'sce_discmap_patch.plt')]
    try:
        key = tuple((n, os.path.getsize(n), os.path.getmtime(n)) for n in names if os.path.isfile(n))
        if key and key not in _IDENTITY:
            h = hashlib.sha256()
            for n, *_ in key:
                h.update(_read(n))
            _IDENTITY[key] = h.hexdigest()[:12]
        out['data'] = _IDENTITY.get(key, 'none')
    except OSError:
        out['data'] = 'none'
    try:
        out['layers'] = ','.join(sorted((overlay.status(game_dir).get('layers') or {}).keys())) or 'none'
    except Exception:   # a look must never stop Ready
        out['layers'] = '?'
    return out


def emulator_identity(emu_exe):
    """The shadPS4 side of the install identity: {'emu': short revision, 'timing': 'vblank<Hz>,neo<0|1>'} from the exe's
    version block and the game's custom config (gr4vity ran vblank 9999 Hz on 2026-11-08; the game paces frames by it)."""
    out = {}
    build = emulator_build(emu_exe) if emu_exe else None
    # '<branch>.<rev7>': the lobby refuses two branches (Kravickas's NHL19-Build against another, live 2026-11-08)
    out['emu'] = f"{re.sub(r'[^A-Za-z0-9_+-]', '-', build['branch'])[:40]}.{build['rev'][:7]}" if build else '?'
    try:
        with open(custom_config_path(emu_user_dir(emu_exe)), encoding='utf-8-sig') as f:
            cfg = json.load(f)
        gpu, general = cfg.get('GPU') or {}, cfg.get('General') or {}
        out['timing'] = f"vblank{int(gpu.get('vblank_frequency', 60))},neo{int(bool(general.get('neo_mode', False)))}"
    except (OSError, ValueError, TypeError, AttributeError, SetupError):
        out['timing'] = '?'
    return out


def installed_patch():
    """The text of the patch file install() wrote (its line ends as written), or None when there is none."""
    m = load_manifest()
    if not m or not m.get('user_dir'):
        return None
    try:
        with open(os.path.join(patch_dir(m['user_dir']), PATCH_FILE), encoding='utf-8', newline='') as f:
            return f.read()
    except (OSError, ValueError):
        return None


# ---- install / remove -------------------------------------------------------------------------------------------

def manifest_path():
    return paths.app_dir(MANIFEST)


def load_manifest():
    try:
        with open(manifest_path(), encoding='utf-8') as f:
            m = json.load(f)
            return m if isinstance(m, dict) else None
    except (OSError, ValueError):
        return None


def _save_manifest(m):
    _write(manifest_path(), json.dumps(m, indent=1).encode('utf-8'))


def _drop_manifest():
    try:
        os.remove(manifest_path())
    except FileNotFoundError:
        pass


def patch_dir(user_dir):
    return os.path.join(user_dir, 'patches', PATCH_FOLDER)


def _game_config(cfg_path, user):
    """The per-game config as install() will write it; a missing one starts as a copy of the global one, as the Qt
    launcher makes it. Refuses a file it could not put back (bad JSON, not an object)."""
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding='utf-8-sig') as f:
                cfg = json.load(f)
        except ValueError as e:
            raise SetupError(f'{cfg_path} is not valid JSON ({e}); fix or delete it first')
    else:
        try:
            with open(os.path.join(user, 'config.json'), encoding='utf-8-sig') as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = {}
    if not isinstance(cfg, dict) or not isinstance(cfg.get('General', {}), dict):
        raise SetupError(f'{cfg_path}: "General" is not a section; fix or delete the file first')
    return cfg


def install(emu_exe, xml_text, running=None):
    """Put the patch into the emulator's patches folder and switch the game's network settings on. Returns the
    manifest. Installing again replaces our own files and keeps the first backups. Everything that can refuse is
    checked before the first write, and the manifest is saved around every write, so a failed install is still
    undone by remove()."""
    _refuse_while_running(running)
    xmlpatch.parse(xml_text)  # refuse a broken file before writing anything
    user = emu_user_dir(emu_exe)
    old = load_manifest() or {}
    if old.get('user_dir') and os.path.normcase(old['user_dir']) != os.path.normcase(user):
        raise SetupError(f"Overtime is set up for another emulator folder ({old['user_dir']}); remove it first.")
    entries = {e['path']: e for e in old.get('files', [])}
    folder = patch_dir(user)
    if os.path.isdir(folder) and not entries:
        strangers = set(os.listdir(folder)) - {PATCH_FILE, 'files.json'}
        if strangers:
            raise SetupError(f'{folder} holds files Overtime did not write: {", ".join(sorted(strangers))}')
    cfg_path = custom_config_path(user)
    cfg = _game_config(cfg_path, user)
    m = {'version': 1, 'emulator': os.path.abspath(emu_exe), 'user_dir': user,
         'installed': old.get('installed') or _now(), 'updated': _now(),
         'targets': xmlpatch.targets(xml_text), 'files': []}

    def record():
        m['files'] = list(entries.values())
        _save_manifest(m)

    def put(path, data, previous_keys=None, previous_network=None, added=()):
        before = _read(path) if os.path.exists(path) else None
        e = entries.get(path)
        if e is None:
            # files in our own folder are ours whatever is there (leftovers of an install that never finished)
            ours = os.path.normcase(os.path.dirname(path)) == os.path.normcase(folder)
            e = {'path': path, 'action': 'replaced' if before is not None and not ours else 'created'}
            if before is not None and not ours:
                backup = paths.app_dir('backups', 'gamesetup', datetime.datetime.now().strftime('%Y%m%d-%H%M%S-')
                                       + os.path.basename(path))
                _write(backup, before)
                e['backup'] = backup
            if previous_keys is not None:
                e['previous'] = previous_keys
                e['previous_network'] = previous_network or {}
            entries[path] = e
        elif before is not None and _sha(before) != e.get('sha256') and e.get('previous') is not None:
            # changed since we wrote it (the user's own edit): from now on remove() only puts our keys back
            e.pop('backup', None)
            e['action'] = 'replaced'
        if added:
            e['network_added'] = sorted(set(e.get('network_added') or ()) | set(added))
        record()  # before the write: a failure in between still leaves the file on record
        if before != data:
            _write(path, data)
        e['sha256'] = _sha(data)
        record()

    put(os.path.join(folder, PATCH_FILE), xml_text.encode('utf-8'))
    put(os.path.join(folder, 'files.json'), json.dumps({PATCH_FILE: [active_title()]}, indent=4).encode('utf-8'))
    general = cfg.setdefault('General', {})
    if not isinstance(cfg.get('Network'), dict):
        cfg.pop('Network', None)
    section = cfg.get('Network') or {}   # shadPS4 reads it before "General"
    kept = dict((entries.get(cfg_path) or {}).get('previous') or {})
    dmem_now = general.get(DMEM_KEY)
    if xmlpatch.res1440(xml_text):     # Kravickas: 1440p needs Additional DMem 3500 MB or more
        dmem_want = dmem_now if isinstance(dmem_now, int) and dmem_now >= DMEM_1440 else DMEM_1440
    else:                               # 1080p: the player's own value comes back
        dmem_want = kept[DMEM_KEY] if DMEM_KEY in kept else dmem_now
    if not _both_on(cfg) or cfg_path in entries or dmem_want != dmem_now:
        previous = kept or {k: general.get(k) for k in NETWORK}
        if dmem_want != dmem_now and DMEM_KEY not in previous:
            previous[DMEM_KEY] = dmem_now
        elif not xmlpatch.res1440(xml_text):
            previous.pop(DMEM_KEY, None)
        if dmem_want is None:
            general.pop(DMEM_KEY, None)
        else:
            general[DMEM_KEY] = dmem_want
        previous_network = (entries.get(cfg_path) or {}).get('previous_network') or {
            k: section[k] for k in NETWORK if k in section}
        general.update(NETWORK)
        # both homes (live 2026-11-07: the launcher's game-specific Network tab showed blank with "General" only, and
        # a build that reads "Network" over a shared config.json with them off would start the game offline)
        filled = {k: v for k, v in _servers(user).items()
                  if not (isinstance(section.get(k), str) and section[k].strip())}
        cfg['Network'] = dict(section, **filled, **NETWORK)
        put(cfg_path, json.dumps(cfg, indent=4).encode('utf-8'), previous_keys=previous,
            previous_network=previous_network, added=[k for k in filled if k not in section])
        if entries[cfg_path].get('previous') is not None:
            entries[cfg_path]['previous'] = previous     # an earlier install's record learns the DMem key too
    record()
    return m


def remove(running=None):
    """Undo install(): our files go, replaced files come back from their backups. A file changed since we wrote it
    gets only our keys put back (the custom config, also one we created) or is left alone. Returns what was done."""
    _refuse_while_running(running)
    m = load_manifest()
    if not m:
        return []
    said = []
    for e in reversed(m.get('files', [])):
        path = e['path']
        if not os.path.exists(path):
            said.append(f'already gone: {path}')
            continue
        same = _sha(_read(path)) == e.get('sha256')
        if e['action'] == 'created' and (same or os.path.dirname(path) == patch_dir(m['user_dir'])):
            os.remove(path)
            said.append(f'removed {path}')
        elif same and e.get('backup') and os.path.exists(e['backup']):
            _write(path, _read(e['backup']))
            said.append(f'restored {path}')
        elif e.get('previous') is not None:
            with open(path, encoding='utf-8-sig') as f:
                cfg = json.load(f)
            general = cfg.setdefault('General', {})
            for k, v in e['previous'].items():
                if v is None:
                    general.pop(k, None)
                else:
                    general[k] = v
            if isinstance(cfg.get('Network'), dict):
                was = e.get('previous_network') or {}
                for k in NETWORK:
                    if k in was:
                        cfg['Network'][k] = was[k]
                    else:
                        cfg['Network'].pop(k, None)     # a key install() added
                for k in e.get('network_added') or ():
                    cfg['Network'].pop(k, None)
                if not cfg['Network']:
                    del cfg['Network']
            _write(path, json.dumps(cfg, indent=4).encode('utf-8'))
            said.append(f'put back the network settings in {path}')
        elif e['action'] == 'created':
            said.append(f'left (changed since Overtime wrote it): {path}')
        else:
            said.append(f'left (no backup to restore): {path}')
    try:
        os.rmdir(patch_dir(m['user_dir']))
    except OSError:
        pass
    _drop_manifest()
    return said


def adopt(accept):
    """The patch file was written under another record (a second app folder: a lab run, a test, a copy of the app):
    when its bytes are exactly one of the texts `accept` (what this Overtime writes), the record takes it over, i.e.
    it gets the file's sha, instead of calling a good patch changed. Returns True when the record changed."""
    m = load_manifest()
    if not m or not m.get('user_dir'):
        return False
    path = os.path.normcase(os.path.join(patch_dir(m['user_dir']), PATCH_FILE))
    for e in m.get('files', []):
        if os.path.normcase(e['path']) == path and os.path.isfile(e['path']):
            data = _read(e['path'])
            if _sha(data) != e.get('sha256') and data in {t.encode('utf-8') for t in accept}:
                e['sha256'] = _sha(data)
                _save_manifest(m)
                return True
    return False


def status(emu_exe=None):
    """{'installed': bool, 'intact': bool, 'targets', 'problems': [...], 'manifest'} for the Setup tab."""
    m = load_manifest()
    if not m:
        return {'installed': False, 'intact': False, 'targets': None, 'problems': [], 'manifest': None}
    problems = []
    if emu_exe and os.path.normcase(emu_user_dir(emu_exe)) != os.path.normcase(m['user_dir']):
        problems.append(f"set up for the emulator data in {m['user_dir']}, not this emulator's")
    for e in m.get('files', []):
        if not os.path.exists(e['path']):
            problems.append(f"missing: {e['path']}")
        elif e.get('previous') is not None:
            # the game's custom config: only our network keys are ours; any other setting there is the player's
            # (a whole-file hash asked for Patch after every shadPS4 setting changed, 2026-11-03). Play puts them back.
            if not _keys_on(e['path']):
                problems.append(f"network switched off: {e['path']}")
        elif _sha(_read(e['path'])) != e.get('sha256'):
            problems.append(f"changed since setup: {e['path']}")
    return {'installed': True, 'intact': not problems, 'targets': m.get('targets'), 'problems': problems,
            'manifest': m}


# ---- the clean game ---------------------------------------------------------------------------------------------

HASHED_ALWAYS = ('eboot.bin', os.path.join('sce_sys', 'param.sfo'))


def _file_sha(path, chunk=1 << 20, progress=None):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            block = f.read(chunk)
            if not block:
                return h.hexdigest()
            h.update(block)
            if progress:
                progress(len(block))


def snapshot(game_dir, full=False, progress=None, pair=True):
    """The game folder as it is: {rel path: [size, sha256 or None]}. Quick = sizes plus eboot.bin and param.sfo
    hashed; full = every file hashed (34 GB, minutes). `progress(done_bytes, total_bytes)`. With an update folder
    beside the base (and `pair`), both: the update's files as `..\\<update folder>\\...`, 'update' names it."""
    base, update = gamefiles.roots(game_dir) if pair else (os.path.abspath(game_dir), None)
    hashed = set(HASHED_ALWAYS)
    files = {}
    for root in (base, update):
        if root is None:
            continue
        hashed |= {os.path.relpath(os.path.join(root, h), base) for h in HASHED_ALWAYS}
        for dirpath, _dirs, names in os.walk(root):
            for n in names:
                p = os.path.join(dirpath, n)
                files[os.path.relpath(p, base)] = [os.path.getsize(p), None]
    total = sum(s for s, _ in files.values()) if full else sum(files.get(r, [0])[0] for r in hashed)
    done = [0]

    def tick(n):
        done[0] += n
        if progress:
            progress(done[0], total)

    for rel in sorted(files):
        if full or rel in hashed:
            files[rel][1] = _file_sha(os.path.join(base, rel), progress=tick)
    return {'game_dir': game_dir, 'update': update, 'made': _now(), 'full': full, 'files': files}


def clean_path():
    return paths.app_dir('clean', active_title() + '.json')


def save_clean(snap):
    _write(clean_path(), json.dumps(snap).encode('utf-8'))


def load_clean():
    try:
        with open(clean_path(), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def compare(before, now):
    """Differences between two snapshots: [(rel, 'missing' | 'added' | 'size' | 'content')]. A hash compares only
    where both snapshots have one."""
    out = []
    a, b = before['files'], now['files']
    for rel in sorted(set(a) | set(b)):
        if rel not in b:
            out.append((rel, 'missing'))
        elif rel not in a:
            out.append((rel, 'added'))
        elif a[rel][0] != b[rel][0]:
            out.append((rel, 'size'))
        elif a[rel][1] and b[rel][1] and a[rel][1] != b[rel][1]:
            out.append((rel, 'content'))
    return out


# ---- firewall (read-only check; the rule is added only on the user's click, through UAC) ------------------------

def firewall_allows(emu_exe):
    """True / False whether an enabled inbound allow rule exists for the emulator, None when Windows won't say."""
    if sys.platform != 'win32':
        return None
    script = ("$p = '" + os.path.abspath(emu_exe).replace("'", "''") + "'; "
              "$r = Get-NetFirewallApplicationFilter -Program $p -ErrorAction SilentlyContinue | Get-NetFirewallRule | "
              "Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Allow' -and $_.Enabled -eq 'True' }; "
              "if ($r) { 'yes' } else { 'no' }")
    try:
        out = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                             capture_output=True, text=True, timeout=60,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return {'yes': True, 'no': False}.get(out.splitlines()[-1] if out else '', None)


def firewall_rule_args(emu_exe):
    """netsh arguments for the inbound rule (run elevated, only when the user asks)."""
    return ['advfirewall', 'firewall', 'add', 'rule', f'name={FIREWALL_RULE}', 'dir=in', 'action=allow',
            f'program={os.path.abspath(emu_exe)}', 'enable=yes', 'profile=private,public']
