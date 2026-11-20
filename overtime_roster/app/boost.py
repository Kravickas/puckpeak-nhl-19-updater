"""The shadPS4 builds the app plays with (Setup's Boost performance card, the header's Play NHL 19 button). Three builds,
each a pack pinned by its sha256 (the release host's latest.json; Kravickas's: his GitHub's), never in the exe (owner
2026-11-11, 0.90.2; order, default and packs from 0.92.0, owner 2026-11-13; v2 from 2026-11-16):
- 'native2', shown as "Overtime Native v2" (the default, first in the dropdown, the lobby build): v1's commits on
  Kravickas's nhl-perf-test plus six speed items (fork branch overtime-native-v2, docs/notes/native-v2.md)
  (packdownload.NATIVE2_PACK);
- 'nightly', shown as "Overtime Native v1" (the default and lobby build from 0.92.0 to 0.97.0): Overtime's
  build of upstream nightly 4788f0b + lazy RAM commit, the input poll thread, Kravickas's flip fix and the texture
  collector by seconds (fork branch overtime-nightly, docs/notes/perf-ram.md, native-port.md)
  (packdownload.NIGHTLY_PACK). Overtime publishes it with its releases; the id, folder and pack name keep "nightly"
  (prefs, installed folders and the server's pin URL name them);
- 'kravickas': Kravickas's own CI build of his NHL19-Build branch, the newest release his GitHub publishes
  (kravbuild.py: the API's sha256 of the file, no release host in between), with Kravickas's yes (owner, 2026-11-01)
  (packdownload.KRAVICKAS_PACK). Play takes a newer one by itself; the card's Update gets it now.
Each one's shadPS4.exe goes into the app's own folder (a player's own exe is never touched); every shadPS4 there uses
%APPDATA%\\shadPS4, so saves, patch and ShadNet login stay what they are. QtLauncher is not changed (0.90.2; the
"NHL 19 Boost" entry older apps added stays). Standard library only.
"""
import os
import sys

from overtime_core import overlay

from . import emufile, gamesetup, kravbuild, packdownload, paths

NATIVE2, NIGHTLY, KRAVICKAS = 'native2', 'nightly', 'kravickas'
DEFAULT = NATIVE2   # 2026-11-16 (owner): Overtime Native v2 is the default and what every lobby plays on
BUILDS = {      # GPL-2.0: each build's source code; the card's dropdown shows them in this order
    # Overtime Native v2 (docs/notes/native-v2.md): Kravickas's nhl-perf-test + Overtime's v1 commits + six speed
    # items, each with an OVERTIME_* off switch
    NATIVE2: {'pack': packdownload.NATIVE2_PACK, 'label': 'Overtime Native v2', 'folder': ('boost', 'native2'),
              'source': 'https://github.com/MatusRiedl/shadPS4/tree/overtime-native-v2'},
    NIGHTLY: {'pack': packdownload.NIGHTLY_PACK, 'label': 'Overtime Native v1', 'folder': ('boost', 'nightly'),
              'source': 'https://github.com/MatusRiedl/shadPS4/tree/overtime-nightly'},
    KRAVICKAS: {'pack': packdownload.KRAVICKAS_PACK, 'label': 'Kravickas', 'folder': ('boost',),
                'source': f'https://github.com/{kravbuild.REPO}/tree/{kravbuild.BRANCH}'},
}
if sys.platform != 'win32':     # Linux and macOS (0.97.0): Overtime Native v2 is the one build made for them
    BUILDS = {NATIVE2: BUILDS[NATIVE2]}
# the card's Update button: Overtime Native v1/v2 come with Overtime's releases (Play gets them)
UPDATABLE = tuple(b for b in (KRAVICKAS,) if b in BUILDS)
PACK = packdownload.KRAVICKAS_PACK      # the Kravickas pack (from GitHub)
LOBBY_PACK = BUILDS[DEFAULT]['pack']    # the lobby build when the server names none (onlineemu), online_boost's
SOURCE = BUILDS.get(KRAVICKAS, BUILDS[DEFAULT])['source']
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
    """pack's shadPS4 as `target`, in one step (Windows: the exe; Linux: the AppImage, then unpacked beside itself;
    macOS: the program and its libraries, emufile.unpack)."""
    try:
        emufile.unpack(pack, target)
    except emufile.EmuFileError as err:
        raise BoostError(str(err)) from err


def published(build, max_age=kravbuild.REMEMBER):
    """Where `build` is published: the release host's latest.json (None: read it) or, for Kravickas, his GitHub's
    newest release ({PACK: Release}, {} when there is none). BoostError when GitHub cannot be read or has none."""
    if name_of(build) != KRAVICKAS:
        return None
    table = kravbuild.table(max_age)
    if table is None:
        raise BoostError(kravbuild.OFFLINE)
    if PACK not in table:
        raise BoostError(kravbuild.NONE)
    return table


def install(build, cache_dir, progress=None, cancelled=None):
    """Download the published `build` (when not in the cache yet) and put its exe in place. Returns (exe, sha256 of
    its pack)."""
    pack_name = BUILDS[name_of(build)]['pack']
    release = published(build, max_age=0)
    (_name, ok, message), = packdownload.download([pack_name], cache_dir, progress, release=release,
                                                  cancelled=cancelled)
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
