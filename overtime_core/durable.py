"""Writes that survive a power cut.

Every file the app writes goes to a temporary name first and is renamed over the old one, so a crash of the app never
leaves half a file. A power cut is different: Windows (NTFS) journals the rename but not the file's data, so after
one the new name can hold a file of the right size full of zeros. `replace` pushes the data to the disk (fsync /
FlushFileBuffers) before the rename, so the name only ever points at the old file or the whole new one. `flush_tree`
does the same for a folder written whole before it is renamed in (a save folder).

The cost is waiting for the disk once per file, at the end of writing it: small for the app's own files, and for the
large archives most of their data is already on the disk by then.
"""
import os


def flush(path):
    """Push a written file's data to the disk."""
    with open(path, 'rb+') as f:     # Windows flushes a file only through a handle that may write it
        os.fsync(f.fileno())


def flush_dir(folder):
    """Push a folder's entries (a rename into it) to the disk where the system allows it: Linux and macOS. Windows
    cannot open a folder for this and needs no more: NTFS journals the rename itself."""
    if os.name == 'nt':
        return
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def replace(src, dst):
    """os.replace(src, dst) once src's data is on the disk."""
    flush(src)
    os.replace(src, dst)
    flush_dir(os.path.dirname(os.path.abspath(dst)))


def flush_tree(folder):
    """Push every file under `folder` (written whole before it is renamed in) and its folders to the disk."""
    for top, _dirs, names in os.walk(folder):
        for name in names:
            flush(os.path.join(top, name))
        flush_dir(top)
