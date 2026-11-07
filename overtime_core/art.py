"""Overtime game patch, art part: team art (logos, menu jerseys, 3D kits, centre ice) and player portraits from art
packs, served as new archives that the game mounts after its own (overlay layer `art`).

The game's patch loader lists `<root>/databigs/patch_<family>_*.big` and mounts them sorted by name, so the last one
wins. It does this for the UI family (`inxp`) and the 3D family (`game`) separately, and shadPS4's mods overlay merges
the directory listing of `<game folder>-mods/` into the game's. So the art goes into new archives one number above the
game's highest of each family (`patch_inxp_57.big` and `patch_game_97.big` for v1.60), written into the overlay. The
overlay's copies of the game's own archives are never touched.
- A texture the game already has goes into every family that holds a copy, because which family wins over the other
  is not known.
- A new texture (Seattle's t10499) goes into the family that holds its folder's other files.

An art pack is a zip, built on the owner's PC from their own NHL 27 dump and from NHL.com (tools/build_looks.py,
tools/build_photopack.py, tools/build_people.py). Packs are never committed. One pack is made on the player's PC:
the photos the people pack lacks, drawn at Update (overtime_core.photos, people_local.zip in the app's cache).

    pack.json   {"format": 1, "name", "built", "source", "files": {game path: sha256}}
    <path>      each texture as a ready GNF file, stored at its game path (nhl/...)

A delta pack (format 2, the all-team 3D kits: most of a kit's normal / coeff maps is the game's own) also lists
    "deltas": {game path: {"base": sha256 of the game's own file, "sha256": of the result, "size": its length}}
    <path>.delta  the result's 16-byte blocks that differ from the game's file (DELTA_MAGIC, then runs of
                  u32 offset, u32 length, bytes)
and is read with the game folder (load_pack(path, game_dir)): each delta is laid on the game's winning copy of its
path, and a pack whose base does not match that copy (another game version, a modded file) is refused.

Stdlib only: the textures are made when the pack is built, never here (overtime_core.photos draws with Pillow).
"""
import collections
import contextlib
import hashlib
import json
import os
import re
import shutil
import threading
import zipfile
from functools import partial

from . import clubdata, eb, gamefiles

FORMAT = 1
DELTA_FORMAT = 2
MANIFEST = 'pack.json'
DELTA_MAGIC = b'OTD1'
BLOCK = 16
FAMILIES = ('inxp', 'game')
GNF_MAGIC = b'GNF '
DDS_MAGIC = b'DDS '   # the kits' name_adidas_* plates carry a .gnf name but hold a DDS
_PATH = re.compile(r'^nhl/[a-z0-9_./-]+\.gnf$')
_ARCHIVE = re.compile(r'^(patch_)?([a-z]+)_(\d+)\.big$')
# NHL 19 draws a player's portrait from p<artid> (the bio's artid, not its game_id: ws8 run pk), when his bio has
# hasportrait set
PORTRAIT = 'nhl/ui/kettle_assets/playerportraits/p{}.gnf'
YEAR_BASE = 1900
BIOS = 'exhibitionplayerbiotable'
PEOPLE_ARTIDS = range(40000, 65536)     # the art ids of the people pack's players the game does not have (below: stock
                                        # art ids, then rosterupdate.NEW_ARTIDS)


class ArtError(Exception):
    pass


def family(archive):
    """'inxp' (UI) / 'game' (3D) / 'boot' / 'overlays' / 'other' of an archive file name."""
    m = _ARCHIVE.match(os.path.basename(archive).lower())
    if m and m.group(2) in FAMILIES + ('boot', 'overlays'):
        return m.group(2)
    name = os.path.basename(archive).lower()
    return 'boot' if name.startswith('boot') else 'other'


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def check_file(path, data):
    """Raise ArtError unless `path` is a lower-case game texture path and `data` a GNF file (a DDS for name_*)."""
    if not _PATH.match(path) or '..' in path.split('/'):
        raise ArtError(f'not a game texture path: {path}')
    magic = DDS_MAGIC if path.rsplit('/', 1)[-1].startswith('name_') else GNF_MAGIC
    if data[:4] != magic:
        raise ArtError(f'{path}: not a {"DDS" if magic == DDS_MAGIC else "GNF"} texture')


_local = threading.local()


@contextlib.contextmanager
def reading():
    """Keep each pack zip and game archive that Stored files read from open until the block ends: reopening one per
    texture re-parses the zip's whole central directory (or the archive's whole table) every time, which made the
    art layer quadratic in its texture count. Nests; per thread; the handles close when the outer block ends, so no
    file stays locked (Windows) after it."""
    if getattr(_local, 'handles', None) is not None:
        yield
        return
    _local.handles = {}
    try:
        yield
    finally:
        handles, _local.handles = _local.handles, None
        for h in handles.values():
            h.close()


def release():
    """Close the reading() block's handles now (the block goes on, opening again on the next read): before a file one
    of them holds is replaced, which Windows refuses while it is open."""
    handles = getattr(_local, 'handles', None)
    if handles:
        for h in handles.values():
            h.close()
        handles.clear()


@contextlib.contextmanager
def _opened(kind, path):
    """`kind(path)` (zipfile.ZipFile / eb.EbArchive), the reading() block's shared one when inside a block."""
    handles = getattr(_local, 'handles', None)
    if handles is None:
        with kind(path) as h:
            yield h
        return
    key = (kind, os.path.abspath(path))
    if key not in handles:
        handles[key] = kind(path)
    yield handles[key]


class Stored:
    """A file of a pack, read only when it is written: with every jersey pack on the art layer is over 10 GB, more than
    a PC can hold in memory. Stands for its bytes: `len`, `==` and read()."""
    __slots__ = ('size', 'read', 'sha')
    __hash__ = None

    def __init__(self, size, read, sha=None):
        self.size, self.read, self.sha = size, read, sha

    def __len__(self):
        return self.size

    def __eq__(self, other):
        if isinstance(other, Stored):
            if self.sha and other.sha:
                return self.size == other.size and self.sha == other.sha
            return self.read() == other.read()
        if self.sha and isinstance(other, (bytes, bytearray, memoryview)):
            return len(other) == self.size and _sha(other) == self.sha     # read() checks this same sha256
        return self.read() == other


class Pack:
    """One art pack: `name`, `info` (pack.json without the file list) and `files` {game path: bytes or Stored}, with
    `shas` {game path: sha256} of the files it knows without reading them."""

    def __init__(self, name, info, files, path=None, shas=None):
        self.name, self.info, self.files, self.path, self.shas = name, info, files, path, shas or {}

    @property
    def sha256(self):
        h = hashlib.sha256()
        for p in sorted(self.files):
            sha = self.shas.get(p) or _sha(self.files[p])
            h.update(p.encode() + b'\0' + sha.encode())
        return h.hexdigest()

    def record(self):
        return {'name': self.name, 'files': len(self.files), 'sha256': self.sha256,
                'built': self.info.get('built'), 'source': self.info.get('source')}


def make_delta(base, data):
    """The delta that turns `base` into `data` (same length): the differing BLOCK-byte blocks, adjacent ones joined."""
    if len(base) != len(data):
        raise ArtError('a delta needs a base of the same length')
    runs, start = [], None
    for o in range(0, len(data), BLOCK):
        if data[o:o + BLOCK] != base[o:o + BLOCK]:
            if start is None:
                start = o
        elif start is not None:
            runs.append((start, o))
            start = None
    if start is not None:
        runs.append((start, len(data)))
    out = bytearray(DELTA_MAGIC)
    for a, b in runs:
        out += a.to_bytes(4, 'little') + (b - a).to_bytes(4, 'little') + data[a:b]
    return bytes(out)


def apply_delta(base, delta):
    """`base` with `delta` (make_delta) laid on it."""
    if delta[:4] != DELTA_MAGIC:
        raise ArtError('not an art delta')
    out, i = bytearray(base), 4
    while i < len(delta):
        if i + 8 > len(delta):
            raise ArtError('a cut-off art delta')
        off, n = int.from_bytes(delta[i:i + 4], 'little'), int.from_bytes(delta[i + 4:i + 8], 'little')
        i += 8
        if off + n > len(out) or i + n > len(delta):
            raise ArtError('an art delta that runs past its file')
        out[off:off + n] = delta[i:i + n]
        i += n
    return bytes(out)


def game_reader(game_dir, paths):
    """A function reading the winning copy (last mounted) of each of `paths` from the game's own archives, which are
    listed once for all of them."""
    want, where = set(paths), {}
    for big in gamefiles.archives(game_dir):
        with eb.EbArchive(big) as arc:
            for p in want.intersection(arc.entries):
                where[p] = big

    def read(p):
        if p not in where:
            raise ArtError(f'{p} is not in the game, so its delta has no base')
        with _opened(eb.EbArchive, where[p]) as arc:
            return arc.read(p)
    return read


def _zip_member(path, name):
    try:
        with _opened(zipfile.ZipFile, path) as z:
            return z.read(name)
    except (zipfile.BadZipFile, KeyError, OSError) as err:
        raise ArtError(f'{path}: {err}') from err


def _read_zipped(path, name, sha):
    """A pack's file again (load_pack checked it; the pack may have changed since)."""
    data = _zip_member(path, name)
    if _sha(data) != sha:
        raise ArtError(f'{path}: {name} does not match its checksum')
    return data


def _read_delta(path, name, sha, base):
    data = apply_delta(base(name), _zip_member(path, name + '.delta'))
    if _sha(data) != sha:
        raise ArtError(f'{path}: {name} does not match its checksum')
    return data


def load_pack(path, game_dir=None):
    """Read and check an art pack zip, keeping none of it in memory (Stored); a delta pack needs `game_dir` (its bases).
    Raises ArtError when anything is off."""
    try:
        with reading(), zipfile.ZipFile(path) as z:
            try:
                info = json.loads(z.read(MANIFEST).decode('utf-8'))
            except KeyError:
                raise ArtError(f'{path}: no {MANIFEST}') from None
            if info.get('format') not in (FORMAT, DELTA_FORMAT):
                raise ArtError(f'{path}: pack format {info.get("format")} (this app reads {FORMAT}, {DELTA_FORMAT})')
            listed = info.get('files') or {}
            files, shas = {}, {}
            for p, sha in listed.items():
                try:
                    data = z.read(p)
                except KeyError:
                    raise ArtError(f'{path}: {p} is listed but missing') from None
                if _sha(data) != sha:
                    raise ArtError(f'{path}: {p} does not match its checksum')
                check_file(p, data)
                files[p], shas[p] = Stored(len(data), partial(_read_zipped, path, p, sha), sha), sha
            deltas = info.get('deltas') or {}
            if deltas and game_dir is None:
                raise ArtError(f'{path}: a delta pack is read with the game folder')
            read = game_reader(game_dir, deltas) if deltas else None
            for p, rec in deltas.items():
                if not _PATH.match(p) or '..' in p.split('/'):
                    raise ArtError(f'{path}: not a game texture path: {p}')
                base = read(p)
                if _sha(base) != rec.get('base') or len(base) != rec.get('size'):
                    raise ArtError(f"{path}: the game's {p} is not the file this pack was made on "
                                   '(another game version, or a modded file)')
                try:
                    data = apply_delta(base, z.read(p + '.delta'))
                except KeyError:
                    raise ArtError(f'{path}: {p}.delta is listed but missing') from None
                if _sha(data) != rec.get('sha256'):
                    raise ArtError(f'{path}: {p} does not match its checksum')
                check_file(p, data)
                files[p] = Stored(len(data), partial(_read_delta, path, p, rec['sha256'], read), rec['sha256'])
                shas[p] = rec['sha256']
    except (zipfile.BadZipFile, OSError, ValueError) as err:
        raise ArtError(f'{path}: {err}') from err
    if not files:
        raise ArtError(f'{path}: the pack holds no textures')
    meta = {k: v for k, v in info.items() if k not in ('files', 'deltas')}
    return Pack(info.get('name') or os.path.splitext(os.path.basename(path))[0], meta, files, path, shas)


def write_pack(path, name, files, source='', built='', bases=None, extra=None):
    """Write an art pack zip ({game path: GNF bytes}); the same files make the same zip. Returns its sha256.
    `bases` ({game path: the game's own bytes}) makes it a delta pack: each file with a base of the same length is
    stored as a delta to it. `extra` adds keys to pack.json (e.g. `alternates`)."""
    for p, data in files.items():
        check_file(p, data)
    bases = bases or {}
    whole = {p: d for p, d in files.items() if len(bases.get(p, b'')) != len(d)}
    deltas = {p: make_delta(bases[p], d) for p, d in files.items() if p not in whole}
    info = {'format': DELTA_FORMAT if deltas else FORMAT, 'name': name, 'built': built, 'source': source,
            'files': {p: _sha(whole[p]) for p in sorted(whole)}}
    if deltas:
        info['deltas'] = {p: {'base': _sha(bases[p]), 'sha256': _sha(files[p]), 'size': len(files[p])}
                          for p in sorted(deltas)}
    info.update(extra or {})
    stored = dict(whole, **{p + '.delta': d for p, d in deltas.items()})
    tmp = path + '.tmp'
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        stamp = (2026, 1, 1, 0, 0, 0)
        z.writestr(zipfile.ZipInfo(MANIFEST, stamp), json.dumps(info, indent=1, sort_keys=True))
        for p in sorted(stored):
            zi = zipfile.ZipInfo(p, stamp)
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, stored[p])
    os.replace(tmp, path)
    with open(path, 'rb') as f:
        return _sha(f.read())


def merge(packs):
    """{game path: bytes} of several packs; a later pack wins where two hold the same path."""
    out = {}
    for pack in packs:
        out.update(pack.files)
    return out


def game_index(game_dir):
    """({path: {family}}, {folder: {family}}) of the game's own archives, for the families the art can go to."""
    where, folders = {}, {}
    for big in gamefiles.archives(game_dir):
        fam = family(big)
        if fam not in FAMILIES:
            continue
        with eb.EbArchive(big) as arc:
            seen = set()
            for p in arc.entries:
                where.setdefault(p, set()).add(fam)
                folder = p.rsplit('/', 1)[0]
                while folder and folder not in seen:     # the folder and every folder above it
                    seen.add(folder)
                    folders.setdefault(folder, set()).add(fam)
                    folder = folder.rsplit('/', 1)[0] if '/' in folder else ''
    return where, folders


def targets(game_dir):
    """{family: game-relative path of the new archive}: one number above the game's highest archive of the family."""
    top = {}
    for big in gamefiles.archives(game_dir):
        m = _ARCHIVE.match(os.path.basename(big).lower())
        if m and m.group(2) in FAMILIES:
            top[m.group(2)] = max(top.get(m.group(2), -1), int(m.group(3)))
    missing = [f for f in FAMILIES if f not in top]
    if missing:
        raise ArtError(f'no {", ".join(missing)} archives in {game_dir}')
    return {f: f'databigs/patch_{f}_{top[f] + 1}.big' for f in FAMILIES}


def _family_of_folder(folder, folders):
    """The families of `folder`, else of its nearest parent folder the game has. CUSA11116 (EU) lays its archives out
    differently from CUSA11126: two testers' art stopped on teamlogos/hutcardheritage, a folder their game does not
    have, though teamlogos is there (docs/notes/cusa11116-network.md)."""
    while folder:
        if folder in folders:
            return folders[folder]
        folder = folder.rsplit('/', 1)[0] if '/' in folder else ''
    return None


def route(files, where, folders):
    """{family: {path: bytes}}: each path into every family whose archives hold it, a new path into the family that
    holds its folder (both, when both do), or its nearest parent folder."""
    out = {}
    for p, data in files.items():
        fams = where.get(p) or _family_of_folder(p.rsplit('/', 1)[0], folders)
        if not fams:
            raise ArtError(f'{p}: neither the texture nor any of its folders is in the game, so its archive is unknown')
        for fam in fams:
            out.setdefault(fam, {})[p] = data
    return out


# bytes of one art archive. The game's own game_90.big is 13.5 GB, but a tester saw crashes "when the big files become too
# big" (docs/notes/art.md, item 14), so more art goes in more archives instead of a larger one
ARCHIVE_LIMIT = 4 << 30
ARCHIVE_ROOM = ARCHIVE_LIMIT - (64 << 20)   # filled up to this: the rest is for its table and the 16-byte alignment
SPARE = 1 << 30           # free bytes left on the drive after the archives are written


def check_size(out, free=None):
    """ArtError when an art archive of `out` ({archive path: {path: bytes}}) would be 4 GB or more, or when the drive
    of the first lacks room for all of them plus SPARE. `free`: the free bytes (the drive of the archives by default)."""
    sizes = {a: sum(len(d) for d in entries.values()) for a, entries in out.items()}
    for archive, size in sizes.items():
        if size >= ARCHIVE_LIMIT:
            raise ArtError(f'{os.path.basename(archive)} would be {size / 2 ** 30:.1f} GB, more than an archive can '
                           'hold: switch off some of the jersey packs')
    if sizes:
        if free is None:
            where = os.path.dirname(next(iter(sizes)))
            while where and not os.path.isdir(where) and os.path.dirname(where) != where:
                where = os.path.dirname(where)
            free = shutil.disk_usage(where).free
        need = sum(sizes.values())
        if free < need + SPARE:
            raise ArtError(f'not enough free space for the art: {need / 2 ** 30:.1f} GB needed, '
                           f'{free / 2 ** 30:.1f} GB free')


def split(entries):
    """[{path: bytes}] of `entries` in path order, each with at most ARCHIVE_ROOM bytes."""
    parts, used = [{}], 0
    for p in sorted(entries):
        size = len(entries[p])
        if used + size > ARCHIVE_ROOM and parts[-1]:
            parts.append({})
            used = 0
        parts[-1][p] = entries[p]
        used += size
    return parts


def archive_names(first):
    """The art archives' names from `first` on, in the game's mount order: it sorts by name (strncmp) and the last wins,
    so _99 is followed by _990, never _100, which would mount before the game's own _97 (docs/notes/eb-archive.md)."""
    head, n, tail = re.match(r'(.*_)(\d+)(\.big)$', first).groups()
    n = int(n)
    while True:
        yield f'{head}{n}{tail}'
        n = 990 if n == 99 else n + 1


def edits(game_dir, files, free=None):
    """{absolute path of a new archive (not in the game folder): {path: bytes}} for the overlay, and the record: a family
    with more art than one archive holds gets several. ArtError when the drive is too full (check_size)."""
    routed = route(files, *game_index(game_dir))
    names = targets(game_dir)
    out, record = {}, {}
    for fam, entries in sorted(routed.items()):
        used = []
        for part, name in zip(split(entries), archive_names(names[fam])):
            archive = gamefiles.locate(game_dir, name)
            if os.path.exists(archive):
                raise ArtError(f'{archive} is a game file: the art archive name is taken')
            out[archive] = part
            used.append(name)
        record[fam] = {'archive': used[0], 'archives': used, 'textures': len(entries)}
    check_size(out, free)
    return out, record


STOCK_JERSEYS = 'stockteamjerseys'


def alternate_rows(db, packs):
    """Relabel the stockteamjerseys rows the packs' `alternates` name ({teamid, style, variant, locstring}): a throwback
    row whose textures a pack made into an NHL 27 alternate. With no such pack the rows keep the stock label (the same
    database serves both ways). Returns how many rows changed."""
    if STOCK_JERSEYS not in db:
        return 0
    t, changed = db[STOCK_JERSEYS], 0
    want = {(a['teamid'], a['style'], a['variant']): a['locstring'] for p in packs for a in p.info.get('alternates', [])}
    if not want:
        return 0
    for i in range(t.count):
        loc = want.get((t.get(i, 'teamid'), t.get(i, 'style'), t.get(i, 'variant')))
        if loc is not None and t.get(i, 'locstring') != loc:
            t.set(i, 'locstring', loc)
            changed += 1
    return changed


def cached_alternates(cache_dir, families=None):
    """The jersey layer packs in `cache_dir` (kitlayers_<family>.zip, read for their pack.json only) as Packs that carry
    `alternates`, for alternate_rows: the roster a save holds takes the labels too (v0.60.0). []: none downloaded. With
    `families` only those (the ones whose switch is on: a downloaded pack that is switched off draws nothing, so its rows
    keep their labels; the order is theirs, the last wins a row)."""
    out = []
    try:
        names = sorted((n for n in os.listdir(cache_dir) if n.startswith('kitlayers_') and n.endswith('.zip')
                        and (families is None or n[len('kitlayers_'):-4] in families)),
                       key=lambda n: families.index(n[len('kitlayers_'):-4]) if families else 0)
    except OSError:
        return out
    for name in names:
        try:
            with zipfile.ZipFile(os.path.join(cache_dir, name)) as z:
                info = json.loads(z.read(MANIFEST).decode('utf-8'))
        except (zipfile.BadZipFile, KeyError, OSError, ValueError):
            continue
        if info.get('alternates'):
            out.append(Pack(name[:-4], {'alternates': info['alternates']}, {}))
    return out


def player_portraits(db, people, shift=0):
    """Give each bio in `db` the art id of its photo in the people pack (tools/build_people.py). `people` is the pack's
    `people` list, [name key (clubdata._key), year, month, day, artid]: a bio is that person by name and birth date, else
    by name and day when a feed's year is off, else by last name and birth date (Mitch and Mitchell Marner), else by a
    name only one bio and one person have. `shift` is
    teams.year_shift: an updated roster's birth years sit that far behind. Returns how many bios have a photo."""
    if BIOS not in db:
        return 0
    exact, by_day, by_name, by_date = {}, collections.defaultdict(set), collections.defaultdict(set), collections.defaultdict(list)
    for name, y, m, d, artid in people:
        exact[name, y, m, d] = artid
        by_day[name, m, d].add(artid)
        by_name[name].add(artid)
        by_date[y, m, d].append((name, artid))
    t = db[BIOS]
    rows = [(i, clubdata._key(t.get(i, 'firstname'), t.get(i, 'lastname'))) for i in range(t.count)]
    names = collections.Counter(name for _i, name in rows)
    found = 0
    for i, name in rows:
        y, m, d = YEAR_BASE + t.get(i, 'year') + shift, t.get(i, 'month') + 1, t.get(i, 'day') + 1
        artid = exact.get((name, y, m, d))
        if artid is None and len(by_day[name, m, d]) == 1:
            artid = next(iter(by_day[name, m, d]))
        if artid is None:
            last = clubdata._key(t.get(i, 'lastname'))
            same = {a for n, a in by_date[y, m, d] if last and n.endswith(last)}
            artid = same.pop() if len(same) == 1 else None
        if artid is None and names[name] == 1 and len(by_name[name]) == 1:
            artid = next(iter(by_name[name]))
        if artid is not None:
            t.set(i, 'artid', artid)
            found += 1
    return found


def portrait_flags(db, stock, files):
    """Set each bio's hasportrait in `db` (a tdb.Database) for the portraits served: on where `files` (the art
    layer's {game path: bytes}, empty with the layer off) holds p<artid>, else what the stock database `stock` has for
    that player (game_id), off for a player stock does not have (a new one: his artid has no stock portrait). So
    the flag is the same whichever database the layer starts from, and taking the art away puts the stock flags back.
    Returns how many bios changed."""
    if BIOS not in db or BIOS not in stock:
        return 0
    s = stock[BIOS]
    stocked = {s.get(i, 'game_id'): s.get(i, 'hasportrait') for i in range(s.count)}
    t, changed = db[BIOS], 0
    for i in range(t.count):
        want = 1 if PORTRAIT.format(t.get(i, 'artid')) in files else stocked.get(t.get(i, 'game_id'), 0)
        if t.get(i, 'hasportrait') != want:
            t.set(i, 'hasportrait', want)
            changed += 1
    return changed
