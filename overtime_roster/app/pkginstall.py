"""NHL 19 from its PKG files, for a player with no extracted game (Setup, Find game picks a .pkg; owner 2026-11-10:
"they point to a game iso and the app will do the rest"). docs/notes/pkg-extractors.md.

The tool is shadPS4Plus's pkg_extractor 1.1 (GPL-2.0), downloaded from its GitHub release and checked by sha256, never
re-hosted by Overtime, and run as a program of its own. The base game goes into a new folder next to the PKG
(`<pkg folder>\\CUSA11126`); the update goes into a new folder beside the game, named after it (`<game>-patch`), the
layout shadPS4 mounts over the base and Overtime reads (gamefiles.roots). Nothing in an existing folder is changed:
each PKG is extracted into a fresh scratch folder on the target drive, then moved to its place in one rename.
Standard library only.
"""
import hashlib
import http.client
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import zipfile

from overtime_core import gamefiles, overlay

from . import gamesetup, packdownload, paths

TOOL_URL = ('https://github.com/AzaharPlus/shadPS4Plus/releases/download/PKG_EXTRACTOR_1_1/'
            'ShadPs4Plus-PkgExtractor-1.1-windows.zip')
TOOL_SHA256 = 'a6a6dee84c1283949245c868e580ff8d0049d0e73df9de3096460ee26c6f04d7'
TOOL_SIZE = 1026861
TOOL_EXE = 'pkg_extractor.exe'
SOURCE = 'https://github.com/AzaharPlus/shadPS4Plus/tree/PKG_EXTRACTOR_1_1/extractor'     # GPL-2.0, its source
BASE, UPDATE, DLC = 101, 102, 103      # pkg_extractor --check-type's exit codes; 0 = not a PKG it reads
MAGIC = b'\x7fCNT'                     # a PS4 PKG's first four bytes; the content id is at 0x40 (36 bytes)
SPARE = 1.05                           # free space wanted: the PKG's size and 5 %
SCRATCH = '.overtime-pkg-'
KINDS = 'NHL 19 PKG (*.pkg)'
_FILE_LINE = re.compile(r'Extracting file (\d+) of (\d+)')


class PkgError(RuntimeError):
    pass


def title_of(pkg):
    """The title id in a PKG's header (CUSA11126 from UP0006-CUSA11126_00-...), or PkgError."""
    try:
        with open(pkg, 'rb') as f:
            head = f.read(0x64)
    except OSError as err:
        raise PkgError(f'The PKG does not open: {err.strerror or err}') from err
    if len(head) < 0x64 or head[:4] != MAGIC:
        raise PkgError(f'{os.path.basename(pkg)} is not a PS4 PKG.')
    content = head[0x40:0x64].split(b'\0', 1)[0].decode('ascii', 'replace')
    m = re.fullmatch(r'[A-Z]{2}\d{4}-([A-Z]{4}\d{5})_\d\d-.*', content)
    if not m:
        raise PkgError(f'{os.path.basename(pkg)} names no game ({content or "no content id"}).')
    return m.group(1)


# --- the tool ---------------------------------------------------------------------------------------------------------
def tool_dir():
    return paths.app_dir('pkgtool')


def tool_exe():
    return os.path.join(paths.app_home(), 'pkgtool', TOOL_EXE)


def _stamp():
    return os.path.join(paths.app_home(), 'pkgtool', 'sha256.txt')


def _download(part, progress=None, opener=None):
    sha, got = hashlib.sha256(), 0
    try:
        r = (opener or packdownload._open)(TOOL_URL)
    except (OSError, ValueError, http.client.HTTPException) as err:
        gone = isinstance(err, urllib.error.HTTPError) and err.code == 404
        raise PkgError('The PKG tool is not on GitHub any more.' if gone else packdownload.NETWORK) from err
    with r, open(part, 'wb') as out:
        while True:
            try:
                block = r.read(packdownload.CHUNK)
            except (OSError, http.client.HTTPException) as err:
                raise PkgError(packdownload.NETWORK) from err
            if not block:
                break
            got += len(block)
            if got > TOOL_SIZE:
                raise PkgError('The PKG tool downloaded is not the one Overtime knows, so it was not used.')
            out.write(block)
            sha.update(block)
            if progress:
                progress(got, TOOL_SIZE)
    if got != TOOL_SIZE or sha.hexdigest() != TOOL_SHA256:
        raise PkgError('The PKG tool downloaded is not the one Overtime knows, so it was not used.')


def ensure_tool(progress=None, opener=None):
    """pkg_extractor.exe in the app's folder, downloaded (the first time) from the shadPS4Plus release and checked."""
    exe, stamp = tool_exe(), _stamp()
    try:
        with open(stamp, encoding='ascii') as f:
            if f.read().strip() == TOOL_SHA256 and os.path.isfile(exe):
                return exe
    except OSError:
        pass
    folder = tool_dir()
    part = os.path.join(folder, 'tool.zip.part')
    try:
        _download(part, progress, opener)
        with zipfile.ZipFile(part) as z:
            for info in z.infolist():
                name = os.path.basename(info.filename.replace('\\', '/'))
                if info.is_dir() or not name or name in ('.', '..'):
                    continue
                with z.open(info) as src, open(os.path.join(folder, name), 'wb') as out:
                    shutil.copyfileobj(src, out, 1 << 20)
        if not os.path.isfile(exe):
            raise PkgError(f'The PKG tool has no {TOOL_EXE}.')
        with open(stamp, 'w', encoding='ascii') as f:
            f.write(TOOL_SHA256 + '\n')
    except zipfile.BadZipFile as err:
        raise PkgError(f'The PKG tool does not unpack: {err}') from err
    except OSError as err:
        raise PkgError(f'The PKG tool could not be saved: {err}') from err
    finally:
        if os.path.exists(part):
            os.remove(part)
    return exe


def _popen(args, popen=subprocess.Popen):
    try:
        return popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     cwd=os.path.dirname(args[0]), text=True, encoding='utf-8', errors='replace',
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError as err:
        raise PkgError(f'The PKG tool did not start ({err.strerror or err}). Your antivirus may have stopped it.') \
            from err


def kind(exe, pkg, popen=subprocess.Popen):
    """BASE, UPDATE or DLC (the tool's --check-type), or PkgError."""
    proc = _popen([exe, pkg, '--check-type'], popen)
    out = proc.communicate()[0] or ''
    if proc.returncode in (BASE, UPDATE, DLC):
        return proc.returncode
    said = _why(out.splitlines()) or 'it may be cut short or damaged: download it again'     # the tool crashes on those
    raise PkgError(f'The PKG tool cannot read {os.path.basename(pkg)}{f" ({said})" if said else ""}.')


# --- installing --------------------------------------------------------------------------------------------------------
def _gigabytes(n):
    return f'{n / 1e9:.1f} GB'


def _room(folder, need):
    free = shutil.disk_usage(folder).free
    if free < need:
        drive = os.path.splitdrive(os.path.abspath(folder))[0] or folder
        raise PkgError(f'{drive} has {_gigabytes(free)} free, the game needs about {_gigabytes(need)}. Free some space, '
                       'or move the PKG to a drive with room, then try again.')


def _size(folder):
    total = 0
    for top, _dirs, names in os.walk(folder):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(top, name))
            except OSError:
                pass
    return total


def _free_name(path):
    """`path`, or `path-2`, `path-3`... the first that does not exist (an existing folder is never written into)."""
    if not os.path.exists(path):
        return path
    n = 2
    while os.path.exists(f'{path}-{n}'):
        n += 1
    return f'{path}-{n}'


def extract(exe, pkg, scratch, progress=None, popen=subprocess.Popen, poll=1.0):
    """Run the tool into `scratch`; its output lines. progress(done bytes, total bytes) from the folder's size against
    the PKG's (the tool only says which file it is on)."""
    total = os.path.getsize(pkg)
    proc = _popen([exe, pkg, scratch], popen)
    stop = threading.Event()

    def watch():
        while not stop.wait(poll):
            if progress:
                progress(min(_size(scratch), total), total)
    watcher = threading.Thread(target=watch, daemon=True, name='pkg-extract')
    watcher.start()
    lines = []
    try:
        for raw in proc.stdout:
            lines.append(raw.rstrip())
        proc.wait()
    finally:
        stop.set()
        watcher.join(5)
    return lines


def _why(lines):
    """The tool's reason from its output, without the file's path: 'Cannot open PKG file : <why>', 'Could not read
    SFO.', '"<path>" doesn't appear to be a valid PKG file'."""
    for x in reversed(lines):
        x = x.strip()
        if x.startswith('Cannot ') and ':' in x:
            return x.split(':', 1)[1].strip()
        if x.startswith('Could not'):
            return x.rstrip('.')
        if "doesn't appear" in x:
            return re.sub(r'^"[^"]*"\s*', '', x).replace("doesn't appear", 'does not appear', 1).rstrip('.')
    return ''


def install(pkg, game_dir=None, progress=None, running=None, popen=subprocess.Popen, opener=None):
    """Install one NHL 19 PKG. The base: a new folder next to the PKG. The update: a new `<game>-patch` folder beside
    `game_dir` (the base must be there). Returns (folder of the game to use, BASE | UPDATE, read_game's dict).
    progress(stage 'tool' | 'extract', done, total). PkgError in words for everything that stops it."""
    pkg = os.path.abspath(pkg)
    title = title_of(pkg)
    if title not in gamesetup.TITLE_IDS:
        raise PkgError(f'This PKG is {title}, not NHL 19 ({" or ".join(gamesetup.TITLE_IDS)}).')
    gamesetup._refuse_while_running(running)
    if overlay.launcher_running():
        raise PkgError('Close the shadPS4 launcher first.')
    exe = ensure_tool((lambda d, t: progress('tool', d, t)) if progress else None, opener)
    k = kind(exe, pkg, popen)
    if k == DLC:
        raise PkgError('This PKG is DLC. NHL 19 needs only the game and its update 1.60.')
    if k == UPDATE:
        game = gamesetup.read_game(game_dir) if game_dir else None
        base = gamefiles.roots(game_dir)[0] if game_dir else None
        if not game or game.get('title_id') not in gamesetup.TITLE_IDS or not base:
            raise PkgError('Install the game PKG first, then its update.')
        parent, target = os.path.dirname(base), base + '-patch'
        if os.path.isdir(base + '-UPDATE'):
            raise PkgError(f'An update is already in {base}-UPDATE, and shadPS4 uses that one first. Move it out of '
                           'that folder, then install the update again.')
    else:
        parent = os.path.dirname(pkg)
        target = _free_name(os.path.join(parent, title))
    _room(parent, int(os.path.getsize(pkg) * SPARE))
    scratch = os.path.join(parent, SCRATCH + str(os.getpid()) + '-' + str(int(time.time())))
    os.makedirs(scratch)
    try:
        lines = extract(exe, pkg, scratch, (lambda d, t: progress('extract', d, t)) if progress else None, popen)
        made = os.path.join(scratch, title + ('-patch' if k == UPDATE else ''))
        if not os.path.isfile(os.path.join(made, 'sce_sys', 'param.sfo')):
            why = _why(lines)
            raise PkgError(f'The PKG did not extract{f": {why}" if why else ""}.')
        if k == UPDATE and os.path.isdir(target):
            os.replace(target, _free_name(target + '.old'))     # an earlier update is kept, not deleted
        os.replace(made, target)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    use = base if k == UPDATE else target
    return use, k, gamesetup.read_game(use)
