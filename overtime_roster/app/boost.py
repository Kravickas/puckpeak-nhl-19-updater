"""Boost performance (Setup): Kravickas's NHL 19 build of shadPS4, with Kravickas's yes (owner, 2026-11-01). The build
is the pack packdownload.EMULATOR_PACK on the release host, pinned by its sha256 in latest.json, never in the exe. On:
its shadPS4.exe goes into the app's own folder (a player's own exe is never touched), QtLauncher lists and selects it,
and the app plays with it. Off: the player's own shadPS4 comes back, in the app and in QtLauncher. Every shadPS4 shares
%APPDATA%\\shadPS4, so saves, patch and ShadNet login stay what they are. Standard library only.
"""
import os
import zipfile

from overtime_core import overlay

from . import gamesetup, packdownload, paths

PACK = packdownload.EMULATOR_PACK
SOURCE = 'https://github.com/Kravickas/shadPS4/tree/NHL19-Build'    # GPL-2.0: the build's source code
ENTRY = 'NHL 19 Boost'      # its name in QtLauncher's Version Manager


class BoostError(RuntimeError):
    pass


def exe_path():
    return os.path.join(paths.app_dir('boost'), packdownload.EMULATOR_EXE)


def same(a, b):
    return bool(a and b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def refused(current, on):
    """Why the switch cannot change now, or None. `current`: the shadPS4 the app uses."""
    if overlay.emulator_running():
        return 'Close shadPS4 first.'
    if overlay.launcher_running():
        return 'Close QtLauncher first: it writes its version list back when it closes.'
    if on and current and gamesetup.emu_user_dir(current) != gamesetup.emu_user_dir(exe_path()):
        return ('Your shadPS4 keeps its saves and settings in its own user folder, so the Kravickas build would not '
                'find them.')
    return None


def unpack(pack, target):
    """pack's shadPS4.exe as `target`, in one step."""
    part = target + '.part'
    try:
        with zipfile.ZipFile(pack) as z, z.open(packdownload.emulator_entry(z)) as src, open(part, 'wb') as out:
            for block in iter(lambda: src.read(1 << 20), b''):
                out.write(block)
        os.replace(part, target)
    except zipfile.BadZipFile as err:
        raise BoostError(f'The Kravickas build does not read: {err}') from err
    finally:
        if os.path.exists(part):
            os.remove(part)


def enable(cache_dir, progress=None, cancelled=None):
    """Download the published build and put it in place. Returns (exe, sha256 of its pack, what QtLauncher had
    selected, or None without QtLauncher)."""
    (_name, ok, message), = packdownload.download([PACK], cache_dir, progress, cancelled=cancelled)
    if not ok:
        raise BoostError(message)
    pack, sha = packdownload.located(PACK, cache_dir)
    exe = exe_path()
    unpack(pack, exe)
    return exe, sha, gamesetup.launcher_add(exe, ENTRY)


def disable(selected):
    """QtLauncher goes back to `selected` and forgets the build; the exe stays in the app's folder."""
    gamesetup.launcher_remove(exe_path(), selected)
