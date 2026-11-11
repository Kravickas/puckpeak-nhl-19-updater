"""The shadPS4 builds the app plays with (Setup's Boost performance card, the header's Play NHL 19 button). Two builds,
each a pack on the release host pinned by its sha256 in latest.json, never in the exe (owner 2026-11-11, 0.90.2):
- 'nightly' (the default): upstream shadPS4's official nightly zip as is (packdownload.NIGHTLY_PACK);
- 'kravickas': our smooth build on Kravickas's NHL 19 branch, with Kravickas's yes (owner, 2026-11-01)
  (packdownload.EMULATOR_PACK, also the lobby build of onlineemu.py).
Each one's shadPS4.exe goes into the app's own folder (a player's own exe is never touched); every shadPS4 there uses
%APPDATA%\\shadPS4, so saves, patch and ShadNet login stay what they are. QtLauncher is not changed (0.90.2; the
"NHL 19 Boost" entry older apps added stays). Standard library only.
"""
import os
import zipfile

from overtime_core import durable, overlay

from . import gamesetup, packdownload, paths

NIGHTLY, KRAVICKAS = 'nightly', 'kravickas'
DEFAULT = NIGHTLY
BUILDS = {      # GPL-2.0: each build's source code
    NIGHTLY: {'pack': packdownload.NIGHTLY_PACK, 'label': 'Nightly', 'folder': ('boost', 'nightly'),
              'source': 'https://github.com/shadps4-emu/shadPS4/releases'},
    KRAVICKAS: {'pack': packdownload.EMULATOR_PACK, 'label': 'Kravickas', 'folder': ('boost',),
                'source': 'https://github.com/MatusRiedl/shadPS4/tree/overtime-ship-1'},
}
PACK = packdownload.EMULATOR_PACK       # the Kravickas pack (onlineemu, online_boost)
SOURCE = BUILDS[KRAVICKAS]['source']
ENTRY = 'NHL 19 Boost'      # its name in QtLauncher's Version Manager (apps before 0.90.2)


class BoostError(RuntimeError):
    pass


def name_of(build):
    return build if build in BUILDS else DEFAULT


def exe_path(build=KRAVICKAS):
    return os.path.join(paths.app_dir(*BUILDS[name_of(build)]['folder']), packdownload.EMULATOR_EXE)


def same(a, b):
    return bool(a and b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def build_of(exe):
    """'nightly' / 'kravickas' when `exe` is one of the app's builds, else None."""
    return next((b for b in BUILDS if same(exe, exe_path(b))), None)


def here(build):
    """The build's exe when it is on this PC, else ''."""
    exe = exe_path(build)
    return exe if os.path.isfile(exe) else ''


def own_portable(own):
    """True when the player's own shadPS4 keeps its data in another folder than the app's builds would use (a portable
    one with `user\\` beside it, or a data folder set by hand): the builds would not find its saves and sign-in."""
    return bool(own) and gamesetup.emu_user_dir(own) != gamesetup.emu_user_dir(exe_path(DEFAULT))


def refused(current, on=True):
    """Why the build cannot change now, or None. `current`: the shadPS4 the app uses."""
    if overlay.emulator_running():
        return 'Close shadPS4 first.'
    if on and current and build_of(current) is None and own_portable(current):
        return ('Your shadPS4 keeps its saves and settings in its own user folder, so the Overtime build would not '
                'find them.')
    return None


def unpack(pack, target):
    """pack's shadPS4.exe as `target`, in one step."""
    part = target + '.part'
    try:
        with zipfile.ZipFile(pack) as z, z.open(packdownload.emulator_entry(z)) as src, open(part, 'wb') as out:
            for block in iter(lambda: src.read(1 << 20), b''):
                out.write(block)
        durable.replace(part, target)
    except zipfile.BadZipFile as err:
        raise BoostError(f'The shadPS4 build does not read: {err}') from err
    finally:
        if os.path.exists(part):
            os.remove(part)


def install(build, cache_dir, progress=None, cancelled=None):
    """Download the published `build` (when not in the cache yet) and put its exe in place. Returns (exe, sha256 of
    its pack)."""
    pack_name = BUILDS[name_of(build)]['pack']
    (_name, ok, message), = packdownload.download([pack_name], cache_dir, progress, cancelled=cancelled)
    if not ok:
        raise BoostError(message)
    found = packdownload.located(pack_name, cache_dir)
    if not found:
        raise BoostError('The shadPS4 build did not download.')
    pack, sha = found
    exe = exe_path(build)
    unpack(pack, exe)
    return exe, sha


def enable(cache_dir, progress=None, cancelled=None):
    """The Kravickas build (lobby play before 0.80 pairs): install(KRAVICKAS). Returns (exe, sha256 of its pack)."""
    return install(KRAVICKAS, cache_dir, progress, cancelled)
