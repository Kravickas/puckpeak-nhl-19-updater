"""Moving the cache folder (Setup, Folders: Downloads and cache) to the folder the player picks, and back (Auto).

The cache holds the downloaded packs and what Patch and Update make on this PC (the jerseys, the club logos, the photos
drawn here): hundreds of MB to several GB. The move never leaves the app without a whole cache:
  - on the same drive each file is renamed (instant); a rename that fails puts the ones done back;
  - on another drive every file is copied (to <name>.part, on the disk, then renamed) and checked by size first. The
    app keeps using the old folder until all are there; only then does the setting change (`switch`), and only then
    are the old files removed. A copy that fails leaves the old folder in use and takes its partial copies away.
A file the new folder already has is replaced: the old folder's is the one the app has been using.

A move takes every file of the old folder, so the cache always has a folder of its own: a folder the player picks that
already holds other files gets one inside it (`pick`, SUBFOLDER), and every cache folder carries MARKER. Files are only
moved out of a folder with MARKER or the program's own folder (`default`): a folder without it (picked before the
marker existed) may hold the player's own files, so they stay where they are and only the setting changes.
"""
import os
import shutil

from overtime_core import durable

SPARE = 1 << 30         # free bytes left on the new drive after the copy
SKIP = ('.part', '.tmp')    # leftovers of a write a crash stopped: not copied, removed with the old folder
MARKER = '.overtime-cache'  # in every cache folder: its files are the program's, a move may take them all
SUBFOLDER = 'OvertimeRoster cache'  # the cache's own folder inside a picked folder that holds other files
MARKER_TEXT = (b'This folder is the downloads and cache of Overtime Roster (Puck Peak Overtime for NHL 19). '
               b'Setup, Folders, Downloads and cache moves every file in it.\r\n')


class CacheMoveError(Exception):
    pass


def same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def inside(path, folder):
    """`path` is `folder` or under it."""
    path, folder = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:      # another drive
        return False


def is_cache(folder):
    """`folder` carries MARKER: a cache folder of this program, all its files are the program's."""
    return os.path.isfile(os.path.join(folder, MARKER))


def mark(folder):
    with open(os.path.join(folder, MARKER), 'wb') as f:
        f.write(MARKER_TEXT)


def _unmark(folder):
    try:
        os.remove(os.path.join(folder, MARKER))
    except OSError:
        pass


def pick(path):
    """The folder the cache goes in when the player picks `path`: `path` itself when it is new, empty or already a
    cache folder of this program, else SUBFOLDER inside it, so the player's files never mix with the cache.
    CacheMoveError when that one holds other files too."""
    for folder in (path, os.path.join(path, SUBFOLDER)):
        if not os.path.exists(folder) or is_cache(folder) or (os.path.isdir(folder) and not os.listdir(folder)):
            return folder
    raise CacheMoveError(f'{path} holds other files, and so does its {SUBFOLDER} folder. Pick an empty folder.')


def files_of(folder):
    """[(path relative to `folder`, size)] of every file under it, leftovers (SKIP) and MARKER apart."""
    out = []
    for top, _dirs, names in os.walk(folder):
        for name in names:
            if name.endswith(SKIP) or name == MARKER:
                continue
            full = os.path.join(top, name)
            out.append((os.path.relpath(full, folder), os.path.getsize(full)))
    return sorted(out)


def _same_drive(src, dst):
    return os.stat(src).st_dev == os.stat(dst).st_dev


def move(src, dst, switch, progress=None, log=None, default=None):
    """Move the cache from `src` to `dst` (created when missing; given MARKER). `switch()` makes the app use `dst`
    (the setting); it runs once every file is in `dst`. `progress(done bytes, total bytes)`. `default`: the program's
    own cache folder (its files are the program's even without MARKER). Returns {'files', 'bytes', 'left', 'kept'}:
    `left` the old files that could not be removed (in use: they are copies, removed by hand or the next move);
    `kept` is `src` when it has no MARKER and is not `default`, so none of its files were moved ('' otherwise)."""
    say = log or (lambda m: None)
    if same(src, dst):
        switch()
        return {'files': 0, 'bytes': 0, 'left': 0, 'kept': ''}
    if inside(dst, src) or inside(src, dst):
        raise CacheMoveError('The new cache folder cannot be inside the old one, or hold it.')
    os.makedirs(dst, exist_ok=True)
    owned = os.path.isdir(src) and (is_cache(src) or (default is not None and same(src, default)))
    kept = src if os.path.isdir(src) and not owned else ''
    if kept:
        say(f'cache move: {src} has no {MARKER}, so it may hold files that are not the cache: they stay there')
    marked_now = not is_cache(dst)
    mark(dst)
    have = files_of(src) if owned else []
    total = sum(n for _rel, n in have)
    tell = progress or (lambda done, total: None)
    tell(0, total)
    if not have:
        switch()
        if owned:
            _unmark(src)
            _prune(src)
        return {'files': 0, 'bytes': 0, 'left': 0, 'kept': kept}
    if _same_drive(src, dst):
        moved, done = [], 0
        try:
            for rel, n in have:
                target = os.path.join(dst, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(os.path.join(src, rel), target)
                moved.append(rel)
                done += n
                tell(done, total)
        except OSError as err:
            for rel in reversed(moved):     # back as it was: the app still uses `src`
                try:
                    os.replace(os.path.join(dst, rel), os.path.join(src, rel))
                except OSError:
                    say(f'cache move: {rel} stays in {dst} ({err})')
            if marked_now:
                _unmark(dst)
            raise CacheMoveError(f'The cache could not be moved: {err}. It stays in {src}.') from err
        switch()
        _unmark(src)
        _prune(src)
        return {'files': len(have), 'bytes': total, 'left': 0, 'kept': ''}
    free = shutil.disk_usage(dst).free
    if free < total + SPARE:
        if marked_now:
            _unmark(dst)
        raise CacheMoveError(f'Not enough free space in {dst}: {total / 2**30:.1f} GB to copy, '
                             f'{free / 2**30:.1f} GB free.')
    copied, existed, done = [], set(), 0
    try:
        for rel, n in have:
            target = os.path.join(dst, rel)
            if os.path.exists(target):
                existed.add(rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(os.path.join(src, rel), target + '.part')
            if os.path.getsize(target + '.part') != n:
                raise OSError(f'{rel} was copied short')
            durable.replace(target + '.part', target)
            copied.append(rel)
            done += n
            tell(done, total)
    except OSError as err:
        gone = [os.path.join(dst, r) + '.part' for r, _n in have] + \
            [os.path.join(dst, r) for r in copied if r not in existed]      # what this copy put there, nothing else
        for p in gone:
            try:
                os.remove(p)
            except OSError:
                pass
        if marked_now:
            _unmark(dst)
        _prune(dst, keep=True)
        raise CacheMoveError(f'The cache could not be copied: {err}. It stays in {src}.') from err
    switch()
    left = 0
    for rel, _n in have:
        try:
            os.remove(os.path.join(src, rel))
        except OSError:
            left += 1
    for top, _dirs, names in os.walk(src):
        for name in names:
            if name.endswith(SKIP):
                try:
                    os.remove(os.path.join(top, name))
                except OSError:
                    pass
    if not left:
        _unmark(src)
    _prune(src)
    if left:
        say(f'cache move: {left} old file(s) in {src} are in use and stay (copies; safe to delete)')
    return {'files': len(have), 'bytes': total, 'left': left, 'kept': ''}


def _prune(folder, keep=False):
    """Remove the folders left empty under `folder` (and it, when empty, unless `keep`)."""
    for top, _dirs, _names in sorted(os.walk(folder), key=lambda t: -len(t[0])):
        if keep and same(top, folder):
            continue
        try:
            os.rmdir(top)
        except OSError:
            pass
