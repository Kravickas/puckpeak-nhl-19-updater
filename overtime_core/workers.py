"""The textures made on the player's PC, on every core: the jerseys (kitcompose), the club logos (clubart), the photos
(photos) and the blocks of one texture (bcn). Standard library only.

Safe by construction:
- ordered(): the caller's generator reads the game's archives and the packs on the calling thread only (a zip or
  archive handle is never shared between threads); the workers get their own copies of what they need and only
  compute; the results come back in the jobs' order, so a pack is byte for byte the one a single thread writes.
- At most workers + AHEAD jobs wait at once: memory grows with the cores, not with the number of textures.
- A thread of these pools is marked: work it starts runs on that thread (bcn does not split a texture's blocks there),
  so pools never nest and the cores are never oversubscribed.
- The heavy parts (numpy, Pillow's resize, hashlib, zlib) let other threads run meanwhile; nothing is shared but
  read-only module tables.
"""
import collections
import concurrent.futures
import os
import queue
import threading

AHEAD = 4               # jobs read beyond the ones being made (a texture is a few MB)

_local = threading.local()


def count():
    """The cores this program may use."""
    return max(1, (getattr(os, 'process_cpu_count', None) or os.cpu_count)() or 1)


def in_worker():
    """True on a thread of one of these pools."""
    return getattr(_local, 'worker', False)


def _mark():
    _local.worker = True


def pool(workers=None):
    """A thread pool whose threads are marked (in_worker)."""
    return concurrent.futures.ThreadPoolExecutor(workers or count(), initializer=_mark)


class _ThreadsWith:
    """A pool whose every thread runs inside `context()` from its first job to the end (art.reading: each thread
    keeps its own pack zips open, closed by the thread that opened them when the pool ends). Futures as an
    executor's."""

    def __init__(self, n, context):
        self.q = queue.Queue()
        self.threads = [threading.Thread(target=self._run, args=(context,), daemon=True) for _ in range(n)]
        for t in self.threads:
            t.start()

    def _run(self, context):
        _mark()
        with context():
            while True:
                item = self.q.get()
                if item is None:
                    return
                fut, fn, args = item
                if not fut.set_running_or_notify_cancel():      # cancelled before it started
                    continue
                try:
                    fut.set_result(fn(*args))
                except BaseException as err:     # noqa: BLE001 (handed to the caller through the future)
                    fut.set_exception(err)

    def submit(self, fn, *args):
        fut = concurrent.futures.Future()
        self.q.put((fut, fn, args))
        return fut

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for _t in self.threads:
            self.q.put(None)
        for t in self.threads:
            t.join()


def _ping():
    return True


def processes_on():
    """Processes may be used (OVERTIME_NO_PROCESSES=1 turns them off: the tests, where each pool's start costs more
    than its tiny jobs)."""
    return os.environ.get('OVERTIME_NO_PROCESSES') != '1'


def _process_pool(workers):
    """A pool of `workers` processes (marked: in_worker), started and answered once, or None when processes cannot
    start here (the caller then uses threads). Processes run the pure-Python parts (the BCn encoder) on every core,
    which threads cannot (the GIL: a jersey patch used under 3 of 16 cores, 2026-11-10)."""
    import multiprocessing
    try:
        ex = concurrent.futures.ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context('spawn'),
                                                    initializer=_mark)
    except (OSError, ValueError, RuntimeError, ImportError):
        return None
    try:
        ex.submit(_ping).result(timeout=120)
    except Exception:     # noqa: BLE001 (any failure to start means threads instead)
        ex.shutdown(wait=False, cancel_futures=True)
        return None
    return ex


def ordered(jobs, make, errors=(Exception,), workers=None, context=None, processes=False):
    """(key, result, error) of make(*args) for each (key, args) of `jobs`, in the jobs' order. `args` may be an
    exception instead (the job could not be read): it comes back as that job's error. An exception of `errors` raised
    by make is returned as the error; any other is raised. One thread (no pool) when workers is 1 or on a pool's thread
    already. `context`: a context manager factory each pool thread runs in (_ThreadsWith); the calling thread is
    assumed to be in one already when it does the jobs itself. `processes`: make runs in processes when they start
    (make, its args and results must pickle; make must be a module-level function), else threads."""
    workers = workers or count()
    if workers == 1 or in_worker():
        for key, args in jobs:
            if isinstance(args, BaseException):
                yield key, None, args
                continue
            try:
                yield key, make(*args), None
            except errors as err:
                yield key, None, err
        return
    ex = None
    if processes and context is None and processes_on():
        ex = _process_pool(workers)
    if ex is None:
        ex = pool(workers) if context is None else _ThreadsWith(workers, context)
    with ex:
        pending = collections.deque()

        def done():
            key, fut = pending.popleft()
            if isinstance(fut, BaseException):
                return key, None, fut
            try:
                return key, fut.result(), None
            except errors as err:
                return key, None, err
        try:
            for key, args in jobs:
                pending.append((key, args if isinstance(args, BaseException) else ex.submit(make, *args)))
                while len(pending) > workers + AHEAD:
                    yield done()
            while pending:
                yield done()
        finally:
            for _key, fut in pending:           # the caller stopped early: what has not started never starts
                if not isinstance(fut, BaseException):
                    fut.cancel()


_shared = None
_shared_lock = threading.Lock()


def shared():
    """One pool for work split from a thread outside the pools (bcn's blocks of a texture made on its own)."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = pool()
        return _shared
