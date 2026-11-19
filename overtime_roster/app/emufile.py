"""shadPS4's program file on each system, and how the app's own builds are put in place and started there
(docs/notes/linux-support.md, macos-support.md).

    Windows   shadPS4.exe          the pack holds that one file
    Linux     shadps4.AppImage     the pack holds that one file (the fork's CI build, with its libraries inside)
    macOS     shadps4              the pack holds it and the files beside it (the Vulkan libraries it loads)

The program file is what the matchmaking tag hashes (onlinetag.exe_sha) on every system. On Linux the AppImage is
unpacked beside itself once, with its own `--appimage-extract`, and the game starts from the unpacked AppRun: an
AppImage started as it is needs FUSE, which a Steam Deck's Game Mode and many containers lack. A player's own
AppImage is started as it is, with APPIMAGE_EXTRACT_AND_RUN where FUSE is missing. Standard library only.
"""
import os
import shutil
import subprocess
import sys
import zipfile

from overtime_core import durable

from . import selfupdate

NAMES = {'win32': 'shadPS4.exe', 'linux': 'shadps4.AppImage', 'darwin': 'shadps4'}
SUFFIX = {'win32': '', 'linux': '_linux', 'darwin': '_macos'}       # in a pack's name: shadps4_native2_linux.zip
MAGIC = {'win32': (b'MZ',),
         'linux': (bytes([0x7F]) + b'ELF',),
         'darwin': (bytes([0xCF, 0xFA, 0xED, 0xFE]), bytes([0xCA, 0xFE, 0xBA, 0xBE]))}     # 64-bit, universal
KIND = {'win32': 'a Windows program', 'linux': 'a Linux program', 'darwin': 'a macOS program'}
WITH_FILES = ('darwin',)        # systems whose pack carries files beside the program
ROOT, STAMP = 'squashfs-root', 'unpacked.txt'      # the unpacked AppImage, and which file it was unpacked from
EXTRACT_TIMEOUT = 300


class EmuFileError(RuntimeError):
    pass


def system_of(system=None):
    system = system or sys.platform
    return system if system in NAMES else 'linux'       # another Unix: the Linux names


def name(system=None):
    """The program file's name in the app's own folders and in a pack."""
    return NAMES[system_of(system)]


def pack_name(windows_name, system=None):
    """A program pack's name on this system: shadps4_native2.zip -> shadps4_native2_linux.zip (Windows: as it is)."""
    stem, ext = os.path.splitext(windows_name)
    return stem + SUFFIX[system_of(system)] + ext


def is_program(head, system=None):
    """`head` (a file's first bytes) starts a program of this system."""
    return any(head.startswith(m) for m in MAGIC[system_of(system)])


def entry(z, system=None, exe_name=None):
    """The one program file in the ZipFile z (any folder, any case). EmuFileError otherwise."""
    want = (exe_name or name(system)).lower()
    found = [n for n in z.namelist() if n.rsplit('/', 1)[-1].lower() == want]
    if len(found) != 1:
        raise EmuFileError(f'not one {exe_name or name(system)} in it')
    return found[0]


def check(path, system=None, exe_name=None):
    """The pack at `path` holds one program file and that reads as a program of this system. EmuFileError otherwise."""
    try:
        with zipfile.ZipFile(path) as z, z.open(entry(z, system, exe_name)) as f:
            if not is_program(f.read(4), system):
                raise EmuFileError(f'{exe_name or name(system)} is not {KIND[system_of(system)]}')
    except (zipfile.BadZipFile, OSError) as err:
        raise EmuFileError(str(err)) from err


def _safe(rel):
    parts = rel.split('/')
    return bool(rel) and ':' not in rel and chr(92) not in rel and all(p not in ('', '.', '..') for p in parts)


def _write(z, info, target, executable):
    part = target + '.part'
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        with z.open(info) as src, open(part, 'wb') as out:
            for block in iter(lambda: src.read(1 << 20), b''):
                out.write(block)
        if executable:
            os.chmod(part, 0o755)
        durable.replace(part, target)
    finally:
        if os.path.exists(part):
            os.remove(part)


def unpack(pack, target, system=None, run=subprocess.run):
    """The pack's program as `target`, in one step; on macOS the files beside it in the pack go beside `target`, and on
    Linux the AppImage is unpacked beside itself (extract). EmuFileError when the pack does not read."""
    system = system_of(system)
    folder = os.path.dirname(target)
    try:
        with zipfile.ZipFile(pack) as z:
            main = entry(z, system)
            base = main.rsplit('/', 1)[0] + '/' if '/' in main else ''
            if system in WITH_FILES:
                for info in z.infolist():
                    rel = info.filename[len(base):] if info.filename.startswith(base) else ''
                    if info.is_dir() or info.filename == main or not _safe(rel):
                        continue
                    _write(z, info, os.path.join(folder, *rel.split('/')), bool((info.external_attr >> 16) & 0o111))
            _write(z, z.getinfo(main), target, system != 'win32')
    except zipfile.BadZipFile as err:
        raise EmuFileError(f'The shadPS4 build does not read: {err}') from err
    if system == 'linux':
        extract(target, run)


def _identity(path):
    st = os.stat(path)
    return f'{st.st_size}:{st.st_mtime_ns}'


def extract(appimage, run=subprocess.run):
    """Unpack the AppImage beside itself (ROOT) and note which file it was (STAMP). True when its AppRun is there. An
    older unpacked build goes first. A failure is not an error: the AppImage is then started as it is (program)."""
    folder = os.path.dirname(os.path.abspath(appimage))
    root, stamp = os.path.join(folder, ROOT), os.path.join(folder, STAMP)
    try:
        if os.path.exists(stamp):
            os.remove(stamp)
        if os.path.isdir(root) and not os.path.islink(root):
            shutil.rmtree(root)
        done = run([os.path.abspath(appimage), '--appimage-extract'], cwd=folder, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=EXTRACT_TIMEOUT,
                   env=selfupdate.clean_environment()).returncode == 0
        if not done or not os.path.isfile(os.path.join(root, 'AppRun')):
            return False
        with open(stamp, 'w', encoding='utf-8') as f:
            f.write(_identity(appimage))
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def unpacked(appimage):
    """The AppRun of the AppImage's unpacked copy when that copy is of this very file, else None."""
    folder = os.path.dirname(os.path.abspath(appimage))
    run = os.path.join(folder, ROOT, 'AppRun')
    try:
        with open(os.path.join(folder, STAMP), encoding='utf-8') as f:
            same = f.read().strip() == _identity(appimage)
    except OSError:
        return None
    return run if same and os.path.isfile(run) else None


def fuse_here(which=shutil.which, exists=os.path.exists):
    """This Linux can start an AppImage as it is (FUSE and its helper are there)."""
    return exists('/dev/fuse') and bool(which('fusermount') or which('fusermount3'))


def program(path, fuse=None):
    """(the file to start, environment to add) for the shadPS4 at `path`: an AppImage's unpacked AppRun when there is
    one; an AppImage as it is, told to unpack itself for the run where FUSE is missing; any other file as it is."""
    if not str(path).lower().endswith('.appimage'):
        return path, {}
    run = unpacked(path)
    if run:
        return run, {}
    return path, ({} if (fuse_here() if fuse is None else fuse) else {'APPIMAGE_EXTRACT_AND_RUN': '1'})
