"""The picture packs the exe does not carry (beta2, the owner's decision of 2026-10-21, like Legacy's packs.py): NHL 27
looks of all 32 teams, Utah's and Seattle's whole look, NHL.com player photos and the all-team 3D kits (PACKS). They
are published on the release host next to latest.json (selfupdate; uploaded by the maintainer,
overtime_server/http/appupdate.py) and downloaded into the app's cache folder, the first place the art layer looks
(patch.art_places): the Photos, logos pack card on Game patch fetches all four at once (v0.10.0: the patch never
downloads; missing_core is the selftest's list). Standard library only.

latest.json names each pack, its sha256 and size:
    "packs": {"photos.zip": {"file": "packs/photos.zip", "sha256": "...", "size": 24117600}, ...}
("file" defaults to packs/<name>, relative to latest.json; without "sha256" the pack's line in SHA256SUMS.txt gives
it, and when both are there they must agree). A file that is not the one published is deleted, never used.

photos.zip is p<artid>.gnf of the default roster's bios (tools/build_photopack.py --database), so it is used only when
every portrait is on a bio of the default roster the app serves (defaultdb's verified default; packaging/
check_photos.py runs the same check at build time). One made for another roster (an older or newer exe's) is deleted
and remembered, so it is not downloaded again for this roster.

What is in the cache is remembered in <cache>/packs.json ({name: {sha256, size, mtime}}, photos.zip also {roster,
fits}; WRONG: the photos made for another roster), so a status does not hash a hundred megabytes each time.
"""
import hashlib
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from overtime_core import art, clubart, kitcompose

from . import defaultdb, paths, selfupdate, sources
from .patch import ART_ENV, CLUBART_PACK, EXTRA_PACKS, KITLAYER_PACKS, KITS_PACK, PEOPLE_PACK, PHOTOS_PACK

# name -> what a player reads, and whether the patch needs it for the art (core; until v0.10.0 the one click fetched those)
EMULATOR_PACK = 'shadps4_nhl19.zip'     # not art: Kravickas's NHL 19 build of shadPS4 (boost.py), so not in PACKS
EMULATOR_EXE = 'shadPS4.exe'
PACKS = {
    'looks32.zip': {'title': 'NHL 27 looks for all 32 teams', 'core': True},
    'looks.zip': {'title': 'Utah and Seattle looks', 'core': True},
    PHOTOS_PACK: {'title': 'Player photos from NHL.com', 'core': True},
    PEOPLE_PACK: {'title': 'Player photos of every league', 'core': True},
    # not served by the patch itself: Update makes the clubs' logos and centre ice of it on this PC (overtime_core.clubart)
    CLUBART_PACK: {'title': 'Club logos and centre ice of every league', 'core': True},
    KITS_PACK: {'title': 'NHL 27 3D kits for 30 teams', 'core': False},
    **{name: {'title': title, 'core': False} for name, title in EXTRA_PACKS.items()},
}
CORE = tuple(name for name, pack in PACKS.items() if pack['core'])
STATES = ('here', 'missing', 'newer', 'offline', 'wrong_roster', 'not_served')
DEFAULT_FILE = 'packs/' + KITS_PACK
RECORD = 'packs.json'
WRONG = 'photos.wrong'          # the record's {sha256, roster} of photos made for another roster
TIMEOUT = 10                    # seconds for reading latest.json
REMEMBER = 300                  # seconds a read release is reused by status() (a failed read: FORGET)
FORGET = 30
CHUNK = 256 * 1024

WRONG_FILE = 'The downloaded file is not the one that was published, so it was not used.'
OFFLINE = 'The Overtime server does not answer. Check your internet connection, then try again.'
NOT_OFFERED = 'The Overtime server does not offer this pack yet. Try again later.'
NOT_SERVED_TEXT = 'Not available for download yet: the Overtime server does not list it.'   # Legacy 0.80.0
NETWORK = 'The download stopped. Check your internet connection, then try again.'
WRONG_ROSTER = ('These player photos were made for another roster, so they are not used. Update Overtime Roster, '
                'then download them again.')
STOPPED = 'Stopped. Nothing was changed.'


class PackError(RuntimeError):
    pass


class Stopped(Exception):
    """download(): cancelled() said stop."""


_lock = threading.RLock()       # the record (status, a download and missing_core may run in different threads)
_releases = {}                  # latest.json URL -> (when read, {name: Release} or None)
_hashes = {}                    # (path, size, mtime) -> {sha256, ...} of a pack outside the cache (exe, repository)
_artids = {}                    # (roster sha256, game folder) -> {artid}


def megabytes(n):
    """'73 MB': decimal megabytes, as the approved mockup's kits row says."""
    mb = n / 1e6
    return f'{mb:.1f} MB' if mb < 10 else f'{mb:.0f} MB'


# --- what is published --------------------------------------------------------------------------------------------
def _release(name, entry, url, sums):
    """A selfupdate.Release for one pack entry of latest.json (its download URL, size, sha256)."""
    file = entry.get('file') if isinstance(entry.get('file'), str) else 'packs/' + name
    named = entry.get('sha256').lower() if isinstance(entry.get('sha256'), str) else None
    listed = (selfupdate.digest_from_sums(sums, file) or selfupdate.digest_from_sums(sums, name)) if sums else None
    digest = named or listed
    if named and listed and named != listed:
        digest = None
    try:
        size = int(entry.get('size') or 0)
    except (TypeError, ValueError):
        size = 0
    return selfupdate.Release((0, 0, 0), exe_url=urllib.parse.urljoin(url, file), size=size, digest=digest,
                              asset=name)


def _read(url, fetch_text):
    try:
        data = json.loads(fetch_text(url))
    except Exception:           # offline, not published yet, a broken file
        return None
    if not isinstance(data, dict):
        return None
    listed = data.get('packs') if isinstance(data.get('packs'), dict) else {}
    sums = None
    if any(isinstance(listed.get(name), dict) for name in (*PACKS, EMULATOR_PACK)):
        try:
            sums = fetch_text(urllib.parse.urljoin(url, data.get('sums') or selfupdate.SUMS_ASSET))
        except Exception:
            sums = None
    return {name: _release(name, listed[name], url, sums) for name in (*PACKS, EMULATOR_PACK)
            if isinstance(listed.get(name), dict)}


def published(url=None, fetch_text=None, max_age=REMEMBER):
    """{pack name: selfupdate.Release} of the packs latest.json names (PACKS' and EMULATOR_PACK only), or None when the release
    cannot be read (offline). The release host is read again after `max_age` seconds (after a failed read: FORGET);
    with `fetch_text` (tests: a local fixture) it is always read."""
    url = url or selfupdate.release_url()
    if fetch_text is None:
        with _lock:
            hit = _releases.get(url)
        if hit and time.time() - hit[0] < (max_age if hit[1] is not None else min(max_age, FORGET)):
            return hit[1]
    table = _read(url, fetch_text or (lambda u: selfupdate.http_text(u, timeout=TIMEOUT)))
    if fetch_text is None:
        with _lock:
            _releases[url] = (time.time(), table)
    return table


def forget():
    """Read the release host again at the next status() (Setup's Check again)."""
    with _lock:
        _releases.clear()


def _table(release, fetch_text, max_age=REMEMBER):
    """`release` as status() and download() take it: published()'s table, a latest.json URL, or None (the release
    host)."""
    if isinstance(release, dict):
        return release
    return published(release if isinstance(release, str) else None, fetch_text, max_age)


# --- what is here -------------------------------------------------------------------------------------------------
def _load(cache_dir):
    try:
        with open(os.path.join(cache_dir, RECORD), encoding='utf-8') as f:
            rec = json.load(f)
        return rec if isinstance(rec, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(cache_dir, rec):
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, RECORD)
    with open(path + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(rec, f, indent=1, sort_keys=True)
    os.replace(path + '.tmp', path)


class _Record:
    """The cache's record, read under the lock and written back when it changed."""

    def __init__(self, cache_dir):
        self.cache_dir = cache_dir

    def __enter__(self):
        _lock.acquire()
        self.rec = _load(self.cache_dir)
        self.before = json.dumps(self.rec, sort_keys=True)
        return self.rec

    def __exit__(self, *exc):
        try:
            if json.dumps(self.rec, sort_keys=True) != self.before:
                _save(self.cache_dir, self.rec)
        except OSError:
            pass                # a read-only cache: the hashes are made again next time
        finally:
            _lock.release()


def _hash(path):
    sha = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            sha.update(block)
    return sha.hexdigest()


def _entry(store, key, path, st):
    """{sha256, size, mtime} of the file at `path`, hashed again only when it changed since `store[key]`."""
    entry = store.get(key)
    if not isinstance(entry, dict) or entry.get('size') != st.st_size or entry.get('mtime') != st.st_mtime_ns \
            or not entry.get('sha256'):
        entry = {'sha256': _hash(path), 'size': st.st_size, 'mtime': st.st_mtime_ns}
        store[key] = entry
    return entry


def _places(cache_dir):
    """Where the patch finds a pack, first wins (patch.art_places without OVERTIME_ART_PACKS): the cache, the exe's
    own packs, the repository's packs/ (a source run)."""
    return [cache_dir, sources.BUILD_PACKS, sources.REPO_PACKS]


def _found(cache_dir, name, rec, game_dir):
    """(path, entry, in cache) of the pack the patch would read, or None. A photos.zip in the cache that was made for
    another roster is deleted here and remembered under WRONG."""
    for folder in _places(cache_dir):
        path = os.path.join(folder, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        mine = folder == cache_dir
        entry = _entry(rec, name, path, st) if mine else _entry(_hashes, (path, st.st_size, st.st_mtime_ns), path, st)
        if name == PHOTOS_PACK and _fits(entry, path, game_dir) is False and mine:
            try:
                os.remove(path)
            except OSError:
                return path, entry, mine        # held open: it goes next time
            rec[WRONG] = {'sha256': entry['sha256'], 'roster': entry['roster']}
            rec.pop(name, None)
            continue
        return path, entry, mine
    return None


def _wrong(rec):
    """The sha256 of the photos known to be made for another roster than the one served now, or None."""
    wrong = rec.get(WRONG)
    sha, _photos = default_roster()
    return wrong.get('sha256') if isinstance(wrong, dict) and sha and wrong.get('roster') == sha else None


# --- photos.zip and the default roster ---------------------------------------------------------------------------
def default_roster():
    """(sha256, sha256 of the photos.zip built for it) of the default roster the app serves (defaultdb's verified
    default, from its build record; a source run's db.json), or (None, None) when there is none."""
    path, record = defaultdb.embedded_place()
    if not path:
        return None, None
    try:
        with open(record, encoding='utf-8-sig') as f:      # build.ps1 writes a BOM
            rec = json.load(f)
    except (OSError, ValueError):
        return None, None
    if not isinstance(rec, dict) or not isinstance(rec.get('sha256'), str):
        return None, None
    photos = rec.get('photos') if isinstance(rec.get('photos'), dict) else {}
    made = photos.get('sha256') or rec.get('photos_sha256')
    return rec['sha256'].lower(), made.lower() if isinstance(made, str) else None


def artids(db_bytes, game_dir):
    """{artid} of the bios of a roster database (the schema comes from the game files, only read)."""
    from overtime_core import gamefiles, tdb
    from overtime_core.schema import parse_schema
    sch = parse_schema(gamefiles.schema_xml(game_dir)[0])
    t = tdb.Database.parse(db_bytes, sch)[sch.by_name(art.BIOS).short]
    return {t.get(i, 'artid') for i in range(t.count)}


def roster_artids(game_dir=None):
    """{artid} of the default roster the app serves, or None when there is none or the game cannot be read."""
    data, sha = defaultdb.embedded()
    if data is None:
        return None
    game_dir = game_dir or paths.default_game_dir()
    key = (sha, os.path.normcase(os.path.abspath(game_dir)))
    with _lock:
        if key not in _artids:
            try:
                _artids[key] = artids(data, game_dir)
            except Exception:   # no game folder, an unreadable schema: cannot tell now
                return None
        return _artids[key]


_PORTRAIT = re.compile('^' + re.escape(art.PORTRAIT).replace(r'\{\}', r'(\d+)') + '$')


def portraits(names):
    """({artid} of the portraits among `names` (game paths), [the other paths])."""
    ids, other = set(), []
    for name in names:
        m = _PORTRAIT.match(name)
        (ids.add(int(m.group(1))) if m else other.append(name))
    return ids, other


def fit(ids, other, have):
    """(fits, [artids on no bio]): every portrait on a bio of the roster (`have`), nothing else in the pack."""
    missing = sorted(ids - have)
    return bool(ids) and not missing and not other, missing


def pack_names(path):
    """The game paths an art pack holds (its manifest; the files themselves are not read)."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            info = json.loads(z.read(art.MANIFEST).decode('utf-8'))
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as err:
        raise art.ArtError(f'{os.path.basename(path)}: {err}') from err
    return list(info.get('files') or {}) + list(info.get('deltas') or {})


def photos_fit(path, game_dir=None):
    """{'fits': True / False / None (cannot tell now: no default roster, or no game to read its schema from),
    'portraits', 'missing': [artids on no bio], 'other': [other files]} of a photos pack against the default roster."""
    try:
        ids, other = portraits(pack_names(path))
    except art.ArtError as err:
        return {'fits': False, 'portraits': 0, 'missing': [], 'other': [str(err)]}
    have = roster_artids(game_dir)
    if have is None:
        return {'fits': None, 'portraits': len(ids), 'missing': [], 'other': other}
    ok, missing = fit(ids, other, have)
    return {'fits': ok, 'portraits': len(ids), 'missing': missing, 'other': other}


def _fits(entry, path, game_dir):
    """True / False / None for the photos.zip `entry` describes, remembered in it against the roster served now."""
    sha, made = default_roster()
    if not sha:
        return None
    if entry.get('roster') == sha and isinstance(entry.get('fits'), bool):
        return entry['fits']
    fits = True if made and entry.get('sha256') == made else photos_fit(path, game_dir)['fits']
    if fits is not None:
        entry.update(roster=sha, fits=fits)
    return fits


# --- the interface: status, download, remove, missing_core ---------------------------------------------------------
def _text(name, state, size, local):
    """One line for players about a pack (Setup's Downloads row; the mockup's kits row)."""
    if state == 'here':
        return f'Downloaded, ready ({megabytes(local)}). Patch the game to put them in.'
    if state == 'newer':
        return 'A newer version is out. Download it, then patch the game again.'
    if state == 'offline':
        return 'Not downloaded. The Overtime server does not answer: check your internet connection.'
    if state == 'wrong_roster':
        return 'Made for another roster, so not used. Update Overtime Roster, then download them again.'
    if state == 'not_served':
        return NOT_SERVED_TEXT
    size = f' ({megabytes(size)})' if size else ''
    if name == KITS_PACK:
        return f"Not downloaded{size}. Until then the teams wear the game's own kits."
    return f'Not downloaded{size}. Press Download.'


def status(cache_dir, release=None, fetch_text=None, game_dir=None):
    """[{name, title, core, size, state, local_size, sha256, removable, text}] in PACKS order. size: the published
    size, or None; local_size and sha256: the file the patch would read (the cache's, else the exe's or the
    repository's), or None; removable: it is in the cache (remove() deletes it); text: one line for players.
    state: 'here', 'missing', 'newer' (another sha256 is published), 'offline' (the release cannot be read and the
    pack is not here), 'not_served' (the release does not list it, and it is not here) or 'wrong_roster' (photos.zip
    does not fit the default roster: it is not used).
    `release`: published()'s table, a latest.json URL, or None (the release host, read at most every REMEMBER s).
    It may wait for the release host (up to TIMEOUT s) and hash a pack it has not seen yet: call it outside ctl.lock."""
    table = _table(release, fetch_text)
    out = []
    with _Record(cache_dir) as rec:
        for name, pack in PACKS.items():
            pub = (table or {}).get(name)
            found = _found(cache_dir, name, rec, game_dir)
            wrong = _wrong(rec) if name == PHOTOS_PACK else None
            _path, entry, mine = found if found else (None, {}, False)
            digest = pub.digest if pub else None
            if found and name == PHOTOS_PACK and entry.get('fits') is False:
                state = 'wrong_roster'          # the exe's or the repository's own (never deleted), or held open
            elif found:
                state = 'newer' if digest and digest not in (entry['sha256'], wrong) else 'here'
            elif name == PHOTOS_PACK and wrong and digest in (None, wrong):
                state = 'wrong_roster'
            else:       # read, but not listed: no Download that cannot work (Legacy's "Downloaded automatically")
                state = 'offline' if table is None else 'missing' if pub else 'not_served'
            size = (pub.size or None) if pub else None
            local = entry.get('size') if found else None
            out.append({'name': name, 'title': pack['title'], 'core': pack['core'], 'size': size, 'state': state,
                        'local_size': local, 'sha256': entry.get('sha256') if found else None, 'removable': mine,
                        'text': _text(name, state, size, local)})
    return out


def missing_core(cache_dir, game_dir=None):
    """The core packs (PACKS order) the patch would lack: in neither the cache nor the exe nor the repository (a
    photos.zip made for another roster counts as missing, and is deleted from the cache). The one-click patch passes
    them to download(), which says why when one cannot be had (offline, made for another roster). [] when
    OVERTIME_ART_PACKS names the only packs folder (or 'off'): the patch reads nothing else. No network."""
    if os.environ.get(ART_ENV):
        return []
    out = []
    with _Record(cache_dir) as rec:
        for name in CORE:
            found = _found(cache_dir, name, rec, game_dir)
            if not found or (name == PHOTOS_PACK and found[1].get('fits') is False):
                out.append(name)
    return out


def _open(url):
    req = urllib.request.Request(url, headers={'User-Agent': selfupdate.AGENT, 'Cache-Control': 'no-cache'})
    return urllib.request.urlopen(req, timeout=60,
                                  context=selfupdate.tls_context() if url.startswith('https:') else None)


def _fetch(release, part, report=None, cancelled=None):
    """Download `release` to `part`; delete it and raise PackError unless it is the file that was published (its
    sha256, and latest.json's size: nothing larger is written) and reads as an art pack. report(done, total) after
    each block; cancelled() True raises Stopped."""
    sha, got = hashlib.sha256(), 0
    limit = release.size or selfupdate.MAX_BYTES
    try:
        r = _open(release.exe_url)
    except (OSError, ValueError, http.client.HTTPException) as err:     # no connection, no server; 404: not uploaded
        gone = isinstance(err, urllib.error.HTTPError) and err.code == 404
        raise PackError(NOT_OFFERED if gone else NETWORK) from err
    try:
        with r, open(part, 'wb') as out:
            try:
                announced = int(r.headers.get('Content-Length') or 0)
            except ValueError:
                announced = 0
            if announced and (announced > limit or (release.size and announced != release.size)):
                raise PackError(WRONG_FILE)
            total = release.size or announced
            while True:
                if cancelled and cancelled():
                    raise Stopped()
                try:
                    block = r.read(CHUNK)
                except (OSError, http.client.HTTPException) as err:    # the line dropped
                    raise PackError(NETWORK) from err
                if not block:
                    break
                if got + len(block) > limit:
                    raise PackError(WRONG_FILE)
                out.write(block)
                sha.update(block)
                got += len(block)
                if report:
                    report(got, total)
        if sha.hexdigest() != release.digest or (release.size and got != release.size):
            raise PackError(WRONG_FILE)
        try:
            CHECKS.get(release.asset, check_zip)(part)
        except art.ArtError as err:
            raise PackError(f'The pack does not read: {err}') from err
    except OSError as err:              # the cache folder: full, read only
        _drop(part)
        raise PackError(f'The pack could not be saved: {err}') from err
    except BaseException:
        _drop(part)
        raise


def _drop(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _get(name, release, cache_dir, report=None, cancelled=None, game_dir=None):
    """Download one pack into the cache and return its path; PackError (with a text for players) or Stopped."""
    if release is None or not release.can_install():
        raise PackError(NOT_OFFERED)
    os.makedirs(cache_dir, exist_ok=True)
    target = os.path.join(cache_dir, name)
    part = target + '.part'
    _fetch(release, part, report, cancelled)
    st = os.stat(part)
    entry = {'sha256': release.digest, 'size': st.st_size}
    if name == PHOTOS_PACK:
        roster, _made = default_roster()
        fits = _fits(entry, part, game_dir)
        if fits is False:
            _drop(part)
            with _Record(cache_dir) as rec:
                rec[WRONG] = {'sha256': release.digest, 'roster': roster}
            raise PackError(WRONG_ROSTER)
    with _Record(cache_dir) as rec:
        try:
            os.replace(part, target)
        except OSError as err:          # Windows: the old pack is open (a patch reads it)
            _drop(part)
            raise PackError(f'The old pack is in use, so the new one was not put in. Try again in a moment. '
                            f'({err})') from err
        entry['mtime'] = os.stat(target).st_mtime_ns
        rec[name] = entry
        if name == PHOTOS_PACK:
            rec.pop(WRONG, None)
    return target


def download(names, cache_dir, progress=None, release=None, game_dir=None, cancelled=None):
    """Download the packs `names` into the cache, one after the other, each checked (the published size and sha256,
    a readable pack; photos.zip also against the default roster) before it is put in place. A pack already here as
    published is not downloaded again. progress(name, done bytes, total bytes); cancelled() True stops (the pack
    being downloaded is dropped, the rest are not started). Returns [(name, ok, message)], messages for players.
    `release`: published()'s table, a latest.json URL, or None (the release host, read now)."""
    names = list(dict.fromkeys(names))
    table = _table(release, None, max_age=0)
    out = []
    for name in names:
        if name not in PACKS and name != EMULATOR_PACK:
            out.append((name, False, 'Overtime Roster does not know this pack.'))
            continue
        if table is None:
            out.append((name, False, OFFLINE))
            continue
        if out and out[-1][2] == STOPPED:
            out.append((name, False, STOPPED))
            continue
        pub = table.get(name)
        with _Record(cache_dir) as rec:
            found = _found(cache_dir, name, rec, game_dir)
            wrong = {_wrong(rec)} if name == PHOTOS_PACK else set()
            if found and found[1].get('fits') is False:
                wrong.add(found[1]['sha256'])   # the exe's or the repository's photos, made for another roster
            same = found and pub is not None and found[1]['sha256'] == pub.digest and pub.digest not in wrong
            refused = pub is not None and pub.digest and pub.digest in wrong
        if same:
            out.append((name, True, 'Already downloaded.'))
            continue
        if refused:
            out.append((name, False, WRONG_ROSTER))
            continue
        step = max(1, (pub.size if pub else 0) // 100)
        last = [-step]

        def report(done, total, name=name, last=last):
            if progress and (done - last[0] >= step or done == total):
                last[0] = done
                progress(name, done, total)
        try:
            _get(name, pub, cache_dir, report, cancelled, game_dir)
            out.append((name, True, 'Downloaded.'))
        except Stopped:
            out.append((name, False, STOPPED))
        except PackError as err:
            out.append((name, False, str(err)))
    return out


def summary(results):
    """(text, tone) for players about download()'s results."""
    if not results:
        return 'Every pack is here already.', 'good'
    failed = [(PACKS.get(n, {}).get('title', n), msg) for n, ok, msg in results if not ok]
    if not failed:
        return ('Downloaded: ' + ', '.join(PACKS[n]['title'] for n, _ok, _m in results) + '.'), 'good'
    title, why = failed[0]
    return f'{title}: {why}', 'bad' if len(failed) == len(results) else 'caution'


def remove(name, cache_dir):
    """Delete the downloaded pack `name` from the cache; True when there was one. (A pack the exe or the repository
    carries stays.) PackError when Windows does not let it go (a patch reads it)."""
    if name not in PACKS:
        return False
    path = os.path.join(cache_dir, name)
    with _Record(cache_dir) as rec:
        _drop(path + '.part')
        try:
            os.remove(path)
        except FileNotFoundError:
            rec.pop(name, None)
            return False
        except OSError as err:
            raise PackError(f'The pack is in use, so it was not deleted. Try again in a moment. ({err})') from err
        rec.pop(name, None)
    return True


def check_zip(path):
    """The manifest reads and names files or deltas (a delta pack's bases are checked against the game when the layer
    is applied). ArtError otherwise."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            info = json.loads(z.read(art.MANIFEST).decode('utf-8'))
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as err:
        raise art.ArtError(str(err)) from err
    if not isinstance(info, dict) or info.get('format') not in (art.FORMAT, art.DELTA_FORMAT) \
            or not (info.get('files') or info.get('deltas')):
        raise art.ArtError('not an art pack')


def emulator_entry(z):
    """The one shadPS4.exe in the ZipFile z. ArtError otherwise."""
    exes = [n for n in z.namelist() if n.rsplit('/', 1)[-1].lower() == EMULATOR_EXE.lower()]
    if len(exes) != 1:
        raise art.ArtError(f'not one {EMULATOR_EXE} in it')
    return exes[0]


def check_emulator(path):
    """The emulator pack holds one shadPS4.exe and that reads as a Windows program. ArtError otherwise."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z, z.open(emulator_entry(z)) as exe:
            if exe.read(2) != b'MZ':
                raise art.ArtError(f'{EMULATOR_EXE} is not a Windows program')
    except (zipfile.BadZipFile, OSError) as err:
        raise art.ArtError(str(err)) from err


def check_clubart(path):
    """The club art source pack's manifest reads (clubart.Source). ArtError otherwise."""
    clubart.Source(path)


def check_kitlayers(path):
    """A jersey layer pack's manifest reads (kitcompose.Source) and every picture it lists is in it. ArtError otherwise."""
    import zipfile
    pack = kitcompose.Source(path)
    try:
        with zipfile.ZipFile(path) as z:
            missing = sorted(set(pack.members) - set(z.namelist()))
    except (zipfile.BadZipFile, OSError) as err:
        raise art.ArtError(str(err)) from err
    if missing:
        raise art.ArtError(f'{len(missing)} pictures missing, {missing[0]} first')


CHECKS = {EMULATOR_PACK: check_emulator, CLUBART_PACK: check_clubart,     # the packs that are not art packs
          **{name: check_kitlayers for name in KITLAYER_PACKS}}


def located(name, cache_dir):
    """(path, sha256) of the pack `name` where it was found, or None."""
    with _Record(cache_dir) as rec:
        found = _found(cache_dir, name, rec, None)
    return (found[0], found[1]['sha256']) if found else None


# --- beta1's kits-only names (Setup's kits row, window.main --download-kits) ----------------------------------------
def kits_release(url=None, fetch_text=None):
    """A selfupdate.Release for the kits pack (its download URL, size, sha256), or None when the release names none
    or cannot be read. `fetch_text` reads a URL (tests: a local fixture)."""
    table = published(url, fetch_text, max_age=0)
    return (table or {}).get(KITS_PACK)


def kits_path(cache_dir):
    return os.path.join(cache_dir, KITS_PACK)


def download_kits(cache_dir, release=None, progress=None):
    """Download the kits pack into `cache_dir` (checked: sha256, size, a readable art pack) and return its path.
    progress(share 0..1). Raises PackError when the release names no pack or the file is not the one published."""
    release = release or kits_release()
    if release is None or not release.can_install():
        raise PackError('The release names no kits pack (or no checksum for it): nothing was downloaded.')
    report = (lambda done, total: progress(min(1.0, done / total) if total else 0.0)) if progress else None
    return _get(KITS_PACK, release, cache_dir, report)


def remove_kits(cache_dir):
    """Delete the downloaded kits pack; True when there was one."""
    return remove(KITS_PACK, cache_dir)
