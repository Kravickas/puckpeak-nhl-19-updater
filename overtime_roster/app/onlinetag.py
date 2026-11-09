"""The matchmaking tag (0.81.0, plan WP3): only games that stay in step meet, in open matchmaking and in a lobby.

EA's `<region>_versioninfo.ini` key `onlineVersion` is the game's Blaze gameProtocolVersionString, and the server pairs
only equal ones (overtime_server game_manager._partner_for). The ini is a loose file, so shadPS4's `<game>-mods` overlay
replaces it; the WP1 spike (2026-11-09, docs/notes/crossplay.md) showed the game sends only the first 15 characters.

The tag is the game's own onlineVersion (10 characters at most) + '-' + 4 base-62 characters of a hash of what decides
whether two games play the same math:
  - the game's own onlineVersion (in full),
  - the netplay fingerprint of the patch shadPS4 loads (xmlpatch.netplay_fingerprint: the Cross-CPU block counts),
  - the sha256 of the shadPS4 exe that runs,
  - the CPU math class: 'amd' for an AMD PC and for an Intel PC on a TRUSTED_EXES build with the AMD math key on (that
    build's pass puts AMD's results in, docs/notes/cross-vendor-desync.md); any other is a class of its own.
A setup that would drift apart then waits for its own kind instead of desyncing. 0.80 apps send the bare `NHL19_1.60`,
which no tag equals.

launch.start writes it before every start (apply), the lobby Ready sends the same value from the same inputs
(start_inputs / match_inputs, then sent), Unpatch removes it (remove). Writes go through a temp file and os.replace:
in a lobby match the `-mods` folder is a view of hardlinks (matchsetup.py), and a replace swaps only the view's link.
A start from outside the app (QtLauncher) keeps the last tag written. Standard library only.
"""
import hashlib
import json
import os

from overtime_core import gamefiles, xmlpatch

from . import gamesetup

TAG_MAX, BASE_MAX, HASH_CHARS = 15, 10, 4
DIGITS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
SALT = 'overtime-tag-1'
# shadPS4 builds whose static pass gives AMD's estimate results on Intel when the AMD math key is on (full sha256 of the
# exe, not of its pack): Kravickas NHL19-Build b23fb67 (the 0.80/0.81 Boost and online-copy exe,
# docs/notes/cross-vendor-review.md) and 749170d (0.82.0's; its 11 commits since b23fb67 leave cpu_patches, the linker
# and memory_patcher as they were, docs/notes/shadps4-builds.md)
TRUSTED_EXES = {'fe88293d67e4e9ab6d0799ac6dcff84644def7806ff0d03b028967cbfdf0e994': 'Kravickas NHL19-Build b23fb67',
                'e8226f593c74e5f60bf0525e00f892e0f79d9d4d2cd452303bfa6bc692c9275c': 'Kravickas NHL19-Build 749170d'}
MARK = '; Overtime Roster: matchmaking tag (only games that stay in step meet). Unpatch removes this file.'
TMP = '.overtime-tmp'


class TagError(RuntimeError):
    """The tag could not be written, nor an old one taken away: the game would meet games it may drift from."""


# --- the inputs and the tag -----------------------------------------------------------------------------------------

_SHA = {}


def exe_sha(path):
    """sha256 of the file at `path`, cached by (path, size, mtime); '?' when it cannot be read."""
    try:
        st = os.stat(path)
    except (OSError, TypeError, ValueError):
        return '?'
    key = (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns)
    if key not in _SHA:
        h = hashlib.sha256()
        try:
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(1 << 20), b''):
                    h.update(chunk)
        except OSError:
            return '?'
        _SHA[key] = h.hexdigest()
    return _SHA[key]


def key_on(user_dir):
    """The game's own config has the AMD math key on (gamesetup.AMD_MATH_KEY is True)."""
    try:
        with open(gamesetup.custom_config_path(user_dir), encoding='utf-8-sig') as f:
            general = json.load(f).get('General') or {}
        return general.get(gamesetup.AMD_MATH_KEY) is True
    except (OSError, ValueError, AttributeError, gamesetup.SetupError):
        return False


def math_class(sha, vendor, key):
    """'amd' when the game plays AMD's math (an AMD CPU; an Intel one on a trusted build with the key on), else
    '<vendor>/key' or '<vendor>/nokey': its own class."""
    if vendor == 'amd' or (sha in TRUSTED_EXES and key):
        return 'amd'
    return f'{vendor or "?"}/{"key" if key else "nokey"}'


def fingerprint(text):
    """The netplay fingerprint of a patch text, or 'none' (no patch, or one that does not parse)."""
    if not text:
        return 'none'
    try:
        return xmlpatch.netplay_fingerprint(text)
    except xmlpatch.PatchError:
        return 'none'


def inputs(game_dir, run_exe, patch_text, key):
    """What the tag is made of, for the game in `game_dir` started with `run_exe`, the patch `patch_text` and the AMD
    math key `key`: {'base', 'fingerprint', 'sha', 'vendor', 'key', 'math', 'crossvendor', 'foreign'}. 'foreign': the
    onlineVersion of another mod's versioninfo.ini in `-mods` (left as it is, so the game sends that), else None."""
    base = gamesetup.online_version(game_dir, mods=False)[1] if game_dir else '?'
    sha = exe_sha(run_exe) if run_exe else '?'
    vendor = gamesetup.cpu_vendor()
    try:
        cross = bool(patch_text) and xmlpatch.has_crossvendor(patch_text)
    except xmlpatch.PatchError:
        cross = False
    return {'base': base, 'fingerprint': fingerprint(patch_text), 'sha': sha, 'vendor': vendor, 'key': bool(key),
            'math': math_class(sha, vendor, bool(key)), 'crossvendor': cross,
            'foreign': gamesetup.online_version(game_dir)[1] if game_dir and _foreign(game_dir) else None}


def compute(base, fp, sha, math):
    """`<base, cut to BASE_MAX>-<HASH_CHARS base-62 characters>`: TAG_MAX characters at most (the game sends no more)."""
    digest = hashlib.sha256('|'.join((SALT, base, fp, sha, math)).encode('utf-8')).digest()
    n, chars = int.from_bytes(digest[:8], 'big'), ''
    for _ in range(HASH_CHARS):
        n, r = divmod(n, len(DIGITS))
        chars += DIGITS[r]
    return f'{base[:BASE_MAX]}-{chars}'


def tag(inp):
    """The tag for these inputs, or None when there is none to write: the game's own onlineVersion is unknown (no ini
    to copy) or there is no patch (an unpatched game reaches no Overtime server)."""
    if inp['base'] in ('', '?') or inp['fingerprint'] == 'none':
        return None
    return compute(inp['base'], inp['fingerprint'], inp['sha'], inp['math'])


def sent(inp):
    """What the game sends as its online version with these inputs: another mod's value when its file is in the way,
    else the tag, else its own onlineVersion."""
    return inp.get('foreign') or tag(inp) or inp['base']


def own_patch_text(emu_exe, patch_file=None):
    """The patch text shadPS4 loads for this start: `patch_file` (-p) when given, else the patch in the emulator's own
    patches folder (gamesetup.install). None when there is none."""
    path = patch_file or os.path.join(gamesetup.patch_dir(gamesetup.emu_user_dir(emu_exe)), gamesetup.PATCH_FILE)
    try:
        with open(path, encoding='utf-8', newline='') as f:
            return f.read()
    except (OSError, ValueError):
        return None


def start_inputs(emu_exe, game_dir, patch_file=None, exe=None):
    """inputs() of a start as launch.start makes it (the player's own data folder's patch and config)."""
    user = gamesetup.emu_user_dir(emu_exe)
    return inputs(game_dir, exe or emu_exe, own_patch_text(emu_exe, patch_file), key_on(user))


def match_inputs(emu_exe, game_dir, match_text, run_exe):
    """inputs() of a lobby match start before matchsetup.apply: its config gets the key where this PC needs it."""
    user = gamesetup.emu_user_dir(emu_exe)
    return inputs(game_dir, run_exe, match_text, gamesetup.amd_math_needed() or key_on(user))


def why(inp):
    """'' when this start meets every 0.81 player on the online build, else one sentence on why it meets only its own
    kind (for the Start message)."""
    reasons = []
    if inp['fingerprint'] == 'none':
        return ''
    if inp.get('foreign'):
        return (f"Another mod's versioninfo.ini in the NHL 19-mods folder sets your online version "
                f"({inp['foreign']}), so Overtime's matchmaking tag is not used: you meet only games with that one.")
    if inp['sha'] not in TRUSTED_EXES:
        reasons.append('this shadPS4 is not the online build (turn on Boost performance in Setup: that is the one; '
                       'a Multiplayer lobby plays on it too)')
    if not inp['crossvendor']:
        reasons.append('the Cross-CPU fix is not in the patch (it needs the v1.60 eboot.bin)')
    if gamesetup.amd_math_needed() and not inp['key']:
        reasons.append("AMD math is off in the game's shadPS4 settings (Game patch, Patch turns it on)")
    if not reasons:
        return ''
    return 'Online you meet only players with the same setup: ' + '; '.join(reasons) + '.'


# --- the file in -mods ----------------------------------------------------------------------------------------------

def _target(game_dir, region):
    return os.path.join(gamefiles.mods_dir(game_dir), *gamesetup.VERSION_DIR, f'{region}_versioninfo.ini')


def _ours(path):
    try:
        with open(path, 'rb') as f:
            return MARK.encode('utf-8') in f.read(4096)
    except OSError:
        return False


def _foreign(game_dir):
    """The versioninfo.ini the game reads is another mod's file in `-mods` (not ours): it wins over any tag."""
    _region, path = gamesetup.version_ini(game_dir, mods=True)
    mods = os.path.normcase(os.path.abspath(gamefiles.mods_dir(game_dir)))
    return bool(path) and os.path.normcase(os.path.abspath(path)).startswith(mods + os.sep) and not _ours(path)


def text_with(source, value):
    """`source` (the game's own versioninfo.ini bytes) with onlineVersion set to `value` and MARK as the first line;
    every other line and the line ends as they were. TagError when it has no onlineVersion line."""
    text = source.decode('utf-8', 'replace')
    lines = text.splitlines(keepends=True)
    end = '\r\n' if '\r\n' in text else '\n'
    out, done = [MARK + end], False
    for line in lines:
        key, sep, _value = line.partition('=')
        if not done and sep and not key.strip().startswith(';') and key.strip() == 'onlineVersion':
            out.append(key + '=' + value + line[len(line.rstrip('\r\n')):])    # the line's own end
            done = True
        else:
            out.append(line)
    if not done:
        raise TagError('the game\'s versioninfo.ini has no onlineVersion line')
    return ''.join(out).encode('utf-8')


def write(game_dir, value):
    """Put `value` into `<game>-mods` as the versioninfo.ini the game reads (a copy of the game's own with only
    onlineVersion changed). Returns its path, or None when another mod's file is there (left as it is). OSError /
    TagError when it cannot be written."""
    region, source = gamesetup.version_ini(game_dir, mods=False)
    if source is None:
        raise TagError('the game has no versioninfo.ini to copy')
    path = _target(game_dir, region)
    if (os.path.exists(path) and not _ours(path)) or _foreign(game_dir):
        return None
    data = text_with(gamesetup._read(source), value)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + TMP
    try:
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)       # a fresh file: a hardlink of the match view is replaced, its target stays
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path


def remove(game_dir):
    """Take the tag files out of `<game>-mods` (only files with MARK) and the folders left empty, up to the `-mods`
    folder itself. Returns the paths removed."""
    mods = gamefiles.mods_dir(game_dir)
    done = []
    for region in gamesetup.VERSION_INIS:
        path = _target(game_dir, region)
        for p in (path, path + TMP):
            if os.path.isfile(p) and (p.endswith(TMP) or _ours(p)):
                os.remove(p)
                done.append(p)
    folder = os.path.join(mods, *gamesetup.VERSION_DIR)
    while os.path.normcase(folder).startswith(os.path.normcase(mods)):
        try:
            if not os.path.isdir(folder) or os.listdir(folder):
                break
            os.rmdir(folder)
        except OSError:
            break
        if os.path.normcase(folder) == os.path.normcase(mods):
            break
        folder = os.path.dirname(folder)
    return done


def apply(emu_exe, game_dir, patch_file=None, exe=None):
    """Before a start (launch.start): the tag of this start written, or an old one taken away when there is none.
    Returns (the tag written or None, inputs). TagError only when neither could be done: a stale tag must not go out."""
    inp = start_inputs(emu_exe, game_dir, patch_file, exe)
    value = tag(inp)
    try:
        if value:
            return (value if write(game_dir, value) else None), inp
        remove(game_dir)
        return None, inp
    except (OSError, TagError) as err:
        try:
            remove(game_dir)
        except OSError as again:
            raise TagError(f'The matchmaking tag in {gamefiles.mods_dir(game_dir)} could not be written ({err}) nor '
                           f'taken away ({again}). Check that folder, then start again.') from again
        return None, inp
