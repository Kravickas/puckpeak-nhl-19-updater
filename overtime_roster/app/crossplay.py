"""Who a Linux or macOS game meets online (docs/plans/proud-shimmying-kettle.md, docs/notes/linux-support.md).

NHL 19 online is lockstep: two games meet only when they compute the same thing. The matchmaking tag (onlinetag.py)
holds the sha256 of the shadPS4 that runs, and a Linux or macOS build of the same source is another file, so it would
get another tag by itself. Until a mixed match has been played through, that is what we want, and one step more: the
tag's first part (which open matchmaking compares, game_manager._base_version) ends in the system's letter, so a Linux
game meets Linux games and a macOS game meets macOS games, in open matchmaking and in a lobby. Windows tags are as
they were.

Cross-play is switched on from the server, without a release: latest.json's
    "crossplay": {"<sha256 of a Linux or macOS shadPS4>": "<sha256 of the Windows shadPS4 it stays in step with>"}
makes a game on the first build compute its tag as the second one's, with no letter. The last map read is kept in
the app's folder (crossplay.json), so a start right after the app opens uses it; an entry taken out of latest.json is
gone at the next read (packdownload.published reads it). Standard library only.
"""
import json
import os
import re
import sys

from overtime_core import durable

from . import paths

FILE = 'crossplay.json'
POOLS = {'linux': 'L', 'darwin': 'M'}       # sys.platform -> the letter its pool's tags end their first part with
NAMES = {'linux': 'Linux', 'darwin': 'macOS'}
_SHA = re.compile(r'[0-9a-f]{64}\Z')


def pool(system=None):
    """The letter of this system's own pool: 'L' (Linux), 'M' (macOS), '' (Windows: the pool every tag was in)."""
    return POOLS.get(system or sys.platform, '')


def pooled(base, letter, width=10):
    """`base` (the game's onlineVersion) ending in the pool's letter, `width` characters at most (onlinetag.BASE_MAX):
    NHL19_1.60 -> NHL19_1.6L. The letter takes the last place, so the tag keeps its length (the game sends 15
    characters)."""
    return base[:width - 1] + letter if letter else base


def clean(mapping):
    """The map as it may be used: {sha256: sha256}, lower case, a build never standing for itself."""
    if not isinstance(mapping, dict):
        return {}
    out = {}
    for mine, theirs in mapping.items():
        if isinstance(mine, str) and isinstance(theirs, str):
            mine, theirs = mine.strip().lower(), theirs.strip().lower()
            if _SHA.match(mine) and _SHA.match(theirs) and mine != theirs:
                out[mine] = theirs
    return out


def _path():
    return os.path.join(paths.app_home(), FILE)


def known():
    """The last map read from the server ({} before the first read)."""
    try:
        with open(_path(), encoding='utf-8') as f:
            return clean(json.load(f))
    except (OSError, ValueError):
        return {}


def remember(mapping):
    """Keep what latest.json says now (no "crossplay" in it: an empty map, so cross-play is off). Returns the map."""
    new = clean(mapping)
    if new != known():
        tmp = _path() + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(new, f, indent=1, sort_keys=True)
            durable.replace(tmp, _path())
        except OSError:
            pass
    return new


def stands_for(sha, system=None):
    """The Windows build's sha256 this system's shadPS4 `sha` is switched to, or None (its own pool). Windows: None."""
    if not pool(system):
        return None
    return known().get((sha or '').lower())
