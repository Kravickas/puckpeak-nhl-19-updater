"""Work that takes a while runs in a thread of its own; the window stays responsive."""
import datetime
import os
import threading
import traceback

from .. import APP_NAME, VERSION
from . import paths

LOG_MAX = 2 << 20   # bytes: a longer error.log is moved to error.old.log first
_context = None     # () -> [(label, value, is_folder)]: what the Controller adds to every error-log block
_log_lock = threading.Lock()    # two jobs failing at once: one rotates error.log, each block is written whole


def set_context(fn):
    """The app's state for the error log (the Controller sets it; None in tests and tools)."""
    global _context
    _context = fn


def log_block(err, step=''):
    """One error-log block per failure (Legacy 0.51.1): the time, the version, the step, the roster, the folders it
    uses (each marked missing when it is gone) and the traceback. Returns the log's path."""
    lines = [f'=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {APP_NAME} {VERSION} ===']
    try:
        context = list(_context()) if _context else []
    except Exception as bad:  # noqa: BLE001 (the block is written all the same)
        context = [('Context', f'not read ({bad})', False)]
    if step:
        context.insert(0, ('Step', step, False))
    for label, value, folder in context:
        if folder:
            value = '(not set)' if not value else value if os.path.isdir(value) else f'{value}  (missing)'
        lines.append(f'{label + ":":<10}{value}')
    lines.append(''.join(traceback.format_exception(type(err), err, err.__traceback__)).rstrip())
    path = paths.app_dir('logs', 'error.log')
    with _log_lock:
        try:
            if os.path.getsize(path) > LOG_MAX:     # the older half goes to error.old.log
                os.replace(path, path[:-4] + '.old.log')
        except OSError:
            pass
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n\n')
        except OSError:
            pass
    return path


def log_unexpected(err, step=''):
    """Keep the details of an unexpected error for a bug report; returns what to tell the user."""
    path = log_block(err, step)
    return f'Something went wrong: {err}. The details were saved to {path}'


def run(work, done=None, failed=None, expected=()):
    """work() in a background thread; then done(result), or failed(message) when it raised. `expected` errors
    are told as they are; anything else is logged first. Every failure gets its block in the error log."""
    def body():
        try:
            result = work()
        except expected as err:
            log_block(err)
            if failed:
                failed(str(err))
            return
        except Exception as err:
            message = log_unexpected(err)
            if failed:
                failed(message)
            return
        if done:
            try:
                done(result)
            except Exception as err:    # a broken result view still leaves a block behind for the bug report
                log_block(err, 'Showing the result')
                raise
    t = threading.Thread(target=body, daemon=True, name='job')
    t.start()
    return t
