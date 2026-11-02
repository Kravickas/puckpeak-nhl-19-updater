"""logs/start.log: what each of the last starts did, for a window that stayed blank (players send this file). The page's
signals live here too: `ready_called` when it asked for its data, `page_up` when it drew them (window/watchdog.py)."""
import threading
import time

from ..app import paths

FILE = 'start.log'
HEAD = '=== start '
KEEP = 20           # starts

ready_called = threading.Event()
page_up = threading.Event()


def path():
    return paths.app_dir('logs', FILE)


def begin(version):
    """A new start in the log; only the newest KEEP stay."""
    try:
        with open(path(), encoding='utf-8', errors='replace') as f:
            old = f.read()
    except OSError:
        old = ''
    starts = [HEAD + part for part in old.split(HEAD)[1:]][-(KEEP - 1):]
    try:
        with open(path(), 'w', encoding='utf-8') as f:
            f.write(''.join(starts) + f'{HEAD}{time.strftime("%Y-%m-%d %H:%M:%S")}  version {version}\n')
    except OSError:
        pass


def note(text):
    try:
        with open(path(), 'a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%H:%M:%S")}  {text}\n')
    except OSError:
        pass
