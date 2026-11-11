"""The online emulator for lobby matches (0.80.0): one shadPS4 build for everyone in a lobby, kept in the app's own
folder by its pack's sha256 and started for lobby matches only. The player's own shadPS4, the Boost switch and
QtLauncher are never changed by it.

It runs on the player's own data (saves, ShadNet sign-in, custom config): shadPS4 takes `user\\` in the folder it starts
from, else %APPDATA%\\shadPS4, so the copy is started from gamesetup.start_dir(the player's own shadPS4)
(docs/notes/match-setup.md 0e). Standard library only.
"""
import os

from . import boost, gamesetup, packdownload, paths

PACK = packdownload.EMULATOR_PACK
# the builds a lobby may name (0.90.2): the server pins one by its pack's sha256, the app fetches the published pack that
# has it. Kravickas when the release does not say (offline, an older release), as before.
PACKS = (packdownload.EMULATOR_PACK, packdownload.NIGHTLY_PACK)
KEEP = 2            # builds kept: the current one and the one before (a server switch mid-update still finds it)


class OnlineEmuError(RuntimeError):
    pass


def exe_path(sha):
    if not (isinstance(sha, str) and len(sha) == 64 and all(c in '0123456789abcdef' for c in sha)):
        raise OnlineEmuError('the online shadPS4 is named by a sha256 the app does not read')
    return os.path.join(paths.app_dir('online-emu', sha[:16]), packdownload.EMULATOR_EXE)


def start_dir(own_emu):
    """The folder to start the online copy from, so it plays on the player's own data; OnlineEmuError when none."""
    if not own_emu:
        raise OnlineEmuError('Choose your shadPS4 in Setup first.')
    folder = gamesetup.start_dir(own_emu)
    if not folder:
        raise OnlineEmuError('Your shadPS4 keeps its data in a folder not named "user", so the online shadPS4 would not '
                             'find your saves and sign-in. Rename that folder to "user" or move it next to shadPS4.')
    return folder


def ready(sha):
    """The online copy's exe when it is here, else None."""
    exe = exe_path(sha)
    return exe if os.path.isfile(exe) else None


def pack_for(want, table=None):
    """The pack name of the build `want` (a pack sha256): the published one of PACKS with that sha256, else PACK."""
    if want:
        table = packdownload.published() if table is None else table
        for name in PACKS:
            rel = (table or {}).get(name)
            if rel is not None and str(rel.digest or '').lower() == want:
                return name
    return PACK


def ensure(cache_dir, want=None, progress=None, cancelled=None):
    """The online copy for the build the lobby names (`want`, a sha256; None: the release's Kravickas pack),
    downloaded once. Returns (exe, sha). OnlineEmuError when the release serves another build (the app or the server
    is behind)."""
    if want and ready(want):
        return exe_path(want), want
    name = pack_for(want)
    (_name, ok, message), = packdownload.download([name], cache_dir, progress, cancelled=cancelled)
    if not ok:
        raise OnlineEmuError(message)
    found = packdownload.located(name, cache_dir)
    if not found:
        raise OnlineEmuError('The online shadPS4 did not download.')
    pack, sha = found
    if want and sha != want:
        raise OnlineEmuError('The lobby plays with another shadPS4 build than this app has: update the app.')
    exe = exe_path(sha)
    if not os.path.isfile(exe):
        try:
            boost.unpack(pack, exe)
        except boost.BoostError as err:
            raise OnlineEmuError(str(err)) from err
    _prune(sha)
    return exe, sha


def _prune(current):
    """Drop builds beyond KEEP (oldest first), never the current one."""
    root = paths.app_dir('online-emu')
    try:
        names = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)) and n != current[:16]]
    except OSError:
        return
    names.sort(key=lambda n: os.path.getmtime(os.path.join(root, n)), reverse=True)
    for name in names[KEEP - 1:]:
        exe = os.path.join(root, name, packdownload.EMULATOR_EXE)
        try:
            if os.path.isfile(exe):
                os.remove(exe)
            os.rmdir(os.path.join(root, name))
        except OSError:
            pass        # in use (a match still runs on it): next time
