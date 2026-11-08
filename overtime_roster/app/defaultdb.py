"""The default roster the one click serves, and the NHL 27 data pack's numbers-only check.

The exe carries the verified default nhl_game.db (packaging/build.ps1 takes re/captures/v0100-default/nhl_game.db, the
bytes the in-game tests ran, never a variant) with a build-time record of its sha256. The one click serves those bytes,
unless the user has run Update (Check) in this app: then the default rebuilt from that is served, and kept in the
cache so later patches serve it too, until a new exe brings another verified default."""
import hashlib
import json
import os
import re
import time

from overtime_core import durable

from . import sources

DB_NAME = 'nhl_game.db'
RECORD = 'default.json'                 # {"sha256", "bytes", "source", "fix"}: written by build.ps1
SHIPPED = os.path.join(sources.PACKAGE, 'defaults')       # in the exe
REPO = os.path.join(os.path.dirname(sources.PACKAGE), 're', 'captures', 'v0100-default')   # a source run
REPO_RECORD = 'db.json'
CACHE_DB = 'default_roster.db'          # the default rebuilt after an Update, in the app cache
CACHE_RECORD = 'default_roster.json'    # {"sha256", "base", "season", "made"}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _read_json(path):
    try:
        with open(path, encoding='utf-8-sig') as f:     # build.ps1 writes a BOM
            value = json.load(f)
            return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def embedded_place():
    """(db path, record path) of the verified default: the exe's own, else the repository's (a source run)."""
    for folder, record in ((SHIPPED, RECORD), (REPO, REPO_RECORD)):
        if os.path.isfile(os.path.join(folder, DB_NAME)):
            return os.path.join(folder, DB_NAME), os.path.join(folder, record)
    return None, None


def embedded():
    """(bytes, sha256) of the verified default when its bytes match its record, else (None, None)."""
    path, record = embedded_place()
    if not path:
        return None, None
    want = str(_read_json(record).get('sha256') or '').lower()
    with open(path, 'rb') as f:
        data = f.read()
    return (data, want) if want and _sha(data) == want else (None, None)


def check():
    """For --selftest: (ok, text) about the verified default."""
    path, record = embedded_place()
    if not path:
        return False, 'no default roster (nhl_game.db) in the exe'
    rec = _read_json(record)
    want = str(rec.get('sha256') or '').lower()
    with open(path, 'rb') as f:
        got = _sha(f.read())
    if not want:
        return False, f'default roster {got[:8]}: no build-time record'
    if got != want:
        return False, f'default roster {got[:8]} is not the recorded {want[:8]}'
    return True, f'default roster {got[:8]} matches the build record ({os.path.getsize(path)} bytes)'


PHOTOS = 'photos.zip'


def photos_check(packs_dir):
    """For --selftest: (ok, text) about photos.zip, which is keyed by the verified default's artids: the build
    record names the one published with it (the app downloads it, packdownload); it is not inside the exe. None
    in a source run (no build record)."""
    path, record = embedded_place()
    if not path or os.path.dirname(path) != SHIPPED:
        return None
    want = _read_json(record).get('photos') or {}
    if os.path.isfile(os.path.join(packs_dir, PHOTOS)):
        return False, f'{PHOTOS} is inside the exe: since beta2 it is downloaded'
    if not want.get('sha256'):
        return False, f'the build record names no {PHOTOS}: the default roster has no portraits to download'
    return True, (f'{PHOTOS} {want["sha256"][:8]} is published with the default roster '
                  f'({want.get("portraits", "?")} portraits)')


def remember(cache_dir, data, base, season):
    """Keep the default rebuilt after an Update (made from the verified default `base`)."""
    os.makedirs(cache_dir, exist_ok=True)
    tmp = os.path.join(cache_dir, CACHE_DB + '.part')
    with open(tmp, 'wb') as f:
        f.write(data)
    durable.replace(tmp, os.path.join(cache_dir, CACHE_DB))
    record = os.path.join(cache_dir, CACHE_RECORD)
    with open(record + '.part', 'w', encoding='utf-8') as f:
        json.dump({'sha256': _sha(data), 'base': base, 'season': season, 'made': time.time()}, f, indent=1)
    durable.replace(record + '.part', record)


def cached(cache_dir, base):
    """The kept rebuilt default when it was made against the verified default `base` and is intact, else None."""
    rec = _read_json(os.path.join(cache_dir, CACHE_RECORD))
    if not base or rec.get('base') != base:
        return None
    try:
        with open(os.path.join(cache_dir, CACHE_DB), 'rb') as f:
            data = f.read()
    except OSError:
        return None
    return data if _sha(data) == rec.get('sha256') else None


def pick(cache_dir, rebuild=None, season=None):
    """The default roster's bytes for the one click and where they come from ('update' / 'cache' / 'embedded' /
    'fresh'). `rebuild`: a function that builds the default from the Update tab's gathered data, or None when no
    Update was run in this app session."""
    base_data, base = embedded()
    if rebuild is not None:
        data = rebuild()
        if base:
            remember(cache_dir, data, base, season)
        return data, 'update'
    kept = cached(cache_dir, base)
    if kept is not None:
        return kept, 'cache'
    if base_data is not None:
        return base_data, 'embedded'
    return None, 'fresh'


# --- the NHL 27 data pack: numbers and names only ----------------------------------------------------
TEXT = re.compile(r"^[\w .'’\-,()/:+]{0,64}$")
MAX_PACK = 4 << 20


def numbers_only(data, size=None):
    """Problems (a list of text) when the pack holds more than numbers and short names / codes: no long text, no
    binary, no embedded files (textures, audio, EA text blobs)."""
    problems = []
    if size is not None and size > MAX_PACK:
        problems.append(f'{size} bytes: larger than {MAX_PACK}')

    def walk(x, where):
        if len(problems) > 20:
            return
        if isinstance(x, dict):
            for k, v in x.items():
                if not isinstance(k, str) or not TEXT.fullmatch(k):
                    problems.append(f'{where}: key {str(k)[:40]!r}')
                walk(v, f'{where}/{k}')
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f'{where}[{i}]')
        elif isinstance(x, str):
            if not TEXT.fullmatch(x):
                problems.append(f'{where}: text {x[:40]!r} ({len(x)} chars)')
        elif x is not None and not isinstance(x, (int, float, bool)):
            problems.append(f'{where}: {type(x).__name__}')
    walk(data, '')
    return problems
