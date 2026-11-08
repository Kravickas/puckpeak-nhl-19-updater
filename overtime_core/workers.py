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


def ordered(jobs, make, errors=(Exception,), workers=None):
    """(key, result, error) of make(*args) for each (key, args) of `jobs`, in the jobs' order. `args` may be an
    exception instead (the job could not be read): it comes back as that job's error. An exception of `errors` raised
    by make is returned as the error; any other is raised. One thread (no pool) when workers is 1 or on a pool's thread
    already."""
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
    with pool(workers) as ex:
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
