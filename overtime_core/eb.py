"""Read NHL 19 (PS4) EB v3 archives (databigs/*.big).

Layout (big-endian), as observed in NHL 19 v1.60:
  0x00 "EB", u16 version (3), u32 file count, u32 flags, u32 names offset, u32 names size,
       u8 file-name record length, u8 folder-name record length, u16 folder count, u32 ?, u32 file size
  0x30 file table, 20 bytes per file: u32 offset (16-byte units), u32 0, u32 size, u64 name hash
  names: per file u16 folder index + name (fixed-length records), then the folder names
         starting at the next 16-byte boundary.

Writing (`rebuild`, `add_entry`, `new_archive`; docs/notes/eb-archive.md): the header's archive size is a u64 at 0x18;
the table is sorted by name hash = 64-bit djb2 (5381, h*33 + c) of the lowercase "folder/name", then one zero byte
per entry; names_off = a16(a16(0x30 + 20n) + n); names = n x fnl records (fnl = longest name + 3), padded to 16, then
the folders (dnl = longest folder + 1), padded to 16; data from names_off + names_size, every blob on a 16-byte
boundary, identical source blobs stored once. A rebuild without changes is byte-identical to every stock archive.

Entries are stored raw or as "chunkzip" (EA chunked raw-deflate):
  "chunkzip", u32 version (2), u32 unpacked size, u32 chunk size, u32 chunk count, u32 alignment,
  then per chunk (16-byte aligned so the data starts aligned): u32 packed size, u32 method, data.
  Method 1 = raw deflate. A chunk whose packed size equals its unpacked size is stored.
"""
import hashlib
import os
import struct
import zlib

M64 = (1 << 64) - 1
FLAGS = 0x00110400


class EbArchive:
    def __init__(self, path):
        self.f = open(path, 'rb')
        h = self.f.read(0x30)
        if h[:2] != b'EB' or struct.unpack_from('>H', h, 2)[0] != 3:
            raise ValueError(f"{path}: not an EB v3 archive")
        count = struct.unpack_from('>I', h, 4)[0]
        names_off, names_size = struct.unpack_from('>II', h, 12)
        fnl, dnl, ndirs = h[20], h[21], struct.unpack_from('>H', h, 22)[0]
        table = self._at(0x30, count * 20)
        names = self._at(names_off, names_size)
        d0 = (count * fnl + 15) // 16 * 16
        dirs = [names[d0 + i * dnl:d0 + (i + 1) * dnl].split(b'\0')[0].decode('latin1') for i in range(ndirs)]
        self.entries = {}  # path -> (offset, size)
        for i in range(count):
            rec = names[i * fnl:(i + 1) * fnl]
            off, _zero, size, _hash = struct.unpack_from('>IIIQ', table, i * 20)
            folder = dirs[struct.unpack_from('>H', rec, 0)[0]]
            name = rec[2:].split(b'\0')[0].decode('latin1')
            self.entries[f"{folder}/{name}" if folder else name] = (off * 16, size)

    def _at(self, off, n):
        self.f.seek(off)
        return self.f.read(n)

    def close(self):
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def raw(self, name):
        off, size = self.entries[name]
        return self._at(off, size)

    def read(self, name):
        return unchunk(self.raw(name))

    def head(self, name, n):
        """The first `n` bytes of entry `name` (a texture's header), reading and unpacking only the chunks they are in."""
        off, size = self.entries[name]
        start = self._at(off, min(size, 0x1c))
        if start[:8] != b'chunkzip':
            return self._at(off, min(size, n))
        csize = struct.unpack_from('>I', start, 16)[0]
        chunks = n // max(csize, 1) + 1
        return unchunk(self._at(off, min(size, 0x30 + chunks * (csize + 0x20))), n)[:n]


def _entry_index(path, name):
    with EbArchive(path) as arc:
        names = list(arc.entries)
    if name not in names:
        raise KeyError(f"{name} not in {path}")
    return names.index(name)


def append_entry(path, name, data):
    """Point entry `name` at a new copy of `data` appended at the end of the archive (in place).

    Nothing already in the file is overwritten except the entry's offset/size and the header's file size
    (u32 at 0x1c), so the change is undone by `restore_entry` with the returned record."""
    i = _entry_index(path, name)
    with open(path, 'r+b') as f:
        h = f.read(0x30)
        file_size = struct.unpack_from('>I', h, 0x1c)[0]
        f.seek(0, 2)
        if f.tell() != file_size:
            raise ValueError(f"{path}: header size {file_size:#x} != file size {f.tell():#x}")
        f.seek(0x30 + i * 20)
        off, _zero, size = struct.unpack('>III', f.read(12))
        start = (file_size + 15) // 16 * 16
        end = (start + len(data) + 15) // 16 * 16
        f.seek(file_size)
        f.write(b'\0' * (start - file_size) + data + b'\0' * (end - start - len(data)))
        f.seek(0x30 + i * 20)
        f.write(struct.pack('>I', start // 16))
        f.seek(0x30 + i * 20 + 8)
        f.write(struct.pack('>I', len(data)))
        f.seek(0x1c)
        f.write(struct.pack('>I', end))
    return {'name': name, 'offset': off * 16, 'size': size, 'file_size': file_size}


def restore_entry(path, record):
    """Undo `append_entry`: restore the entry and the header size, cut the appended bytes."""
    i = _entry_index(path, record['name'])
    with open(path, 'r+b') as f:
        f.seek(0x30 + i * 20)
        f.write(struct.pack('>I', record['offset'] // 16))
        f.seek(0x30 + i * 20 + 8)
        f.write(struct.pack('>I', record['size']))
        f.seek(0x1c)
        f.write(struct.pack('>I', record['file_size']))
        f.truncate(record['file_size'])


def unchunk(data, limit=None):
    """Return the unpacked bytes of a chunkzip blob (or `data` unchanged if it is not one). With `limit` it stops once
    that many bytes are unpacked (the rest of the blob need not be there)."""
    if data[:8] != b'chunkzip':
        return data
    _ver, usize, csize, nchunks, _align = struct.unpack_from('>5I', data, 8)
    out = bytearray()
    pos = 0x1c
    for _ in range(nchunks):
        if limit is not None and len(out) >= limit:
            return bytes(out)
        pos = (pos + 8 + 15) // 16 * 16 - 8  # chunk data starts on a 16-byte boundary
        packed, method = struct.unpack_from('>II', data, pos)
        pos += 8
        chunk = data[pos:pos + packed]
        pos += packed
        want = min(csize, usize - len(out))
        if method == 1 and packed != want:
            out += zlib.decompressobj(-15).decompress(chunk)
        elif packed == want:
            out += chunk
        else:
            raise NotImplementedError(f"chunkzip method {method}")
    if len(out) != usize:
        raise ValueError(f"chunkzip: got {len(out)} bytes, expected {usize}")
    return bytes(out)


# --- writing -----------------------------------------------------------------------------------------------------

def name_hash(path):
    """The TOC hash of an entry: 64-bit djb2 of its lowercase "folder/name" path."""
    h = 5381
    for c in path.lower().encode('latin1'):
        h = (h * 33 + c) & M64
    return h


def _a16(n):
    return (n + 15) & ~15


class _Entry:
    __slots__ = ('path', 'src', 'off', 'size', 'data')

    def __init__(self, path, src=None, off=0, size=0, data=None):
        self.path, self.src, self.off, self.size, self.data = path, src, off, size, data
        if data is not None:
            self.size = len(data)

    def chunks(self, bs=1 << 22):
        if self.data is not None:
            yield self.data.read() if hasattr(self.data, 'read') else self.data
            return
        with open(self.src, 'rb') as f:
            f.seek(self.off)
            left = self.size
            while left:
                b = f.read(min(bs, left))
                if not b:
                    raise ValueError(f'{self.src}: {self.path} runs past the end of the file')
                left -= len(b)
                yield b


def _parse(path):
    """(folders in archive order, entries in data order) of an archive."""
    with open(path, 'rb') as f:
        h = f.read(0x30)
        if h[:2] != b'EB' or struct.unpack_from('>H', h, 2)[0] != 3:
            raise ValueError(f"{path}: not an EB v3 archive")
        count, _flags, names_off, names_size = struct.unpack_from('>IIII', h, 4)
        fnl, dnl, ndirs = h[20], h[21], struct.unpack_from('>H', h, 22)[0]
        table = f.read(count * 20)
        f.seek(names_off)
        names = f.read(names_size)
    d0 = _a16(count * fnl)
    folders = [names[d0 + i * dnl:d0 + (i + 1) * dnl].split(b'\0')[0].decode('latin1') for i in range(ndirs)]
    entries = []
    for i in range(count):
        rec = names[i * fnl:(i + 1) * fnl]
        off, _z, size, _h = struct.unpack_from('>IIIQ', table, i * 20)
        folder = folders[struct.unpack_from('>H', rec, 0)[0]]
        name = rec[2:].split(b'\0')[0].decode('latin1')
        entries.append(_Entry(f"{folder}/{name}" if folder else name, path, off * 16, size))
    entries.sort(key=lambda e: (e.off, e.size))  # a zero-size entry sits before the one sharing its offset
    return folders, entries


def _layout(folders, entries):
    """Header + TOC bytes, the stored blobs [(offset, entry)] and the archive size (entries in data order)."""
    split = [e.path.rsplit('/', 1) if '/' in e.path else ('', e.path) for e in entries]
    folders = list(folders)
    for d, _ in split:
        if d not in folders:
            folders.append(d)
    fidx = {d: i for i, d in enumerate(folders)}
    n = len(entries)
    fnl = max(len(nm) for _, nm in split) + 3
    dnl = max(len(d) for d in folders) + 1
    if fnl > 255 or dnl > 255:
        raise ValueError("name too long for EB v3")
    names_off = _a16(_a16(0x30 + 20 * n) + n)
    names_size = _a16(_a16(n * fnl) + len(folders) * dnl)
    pos = names_off + names_size
    offs, slots, placed = [], [], {}
    for e in entries:  # entries with the same source bytes share one blob (as in EA's own archives)
        key = (e.src, e.off, e.size) if e.data is None else id(e)
        if key in placed:
            offs.append(placed[key])
            continue
        pos = _a16(pos)
        placed[key] = pos
        offs.append(pos)
        slots.append((pos, e))
        pos += e.size
    total = _a16(pos)
    hashes = [name_hash(e.path) for e in entries]
    if len(set(hashes)) != n:
        raise ValueError('two entries with the same name hash')
    table, recs = bytearray(), bytearray()
    for i in sorted(range(n), key=lambda i: hashes[i]):
        d, nm = split[i]
        table += struct.pack('>IIIQ', offs[i] // 16, 0, entries[i].size, hashes[i])
        recs += struct.pack('>H', fidx[d]) + nm.encode('latin1').ljust(fnl - 2, b'\0')
    head = struct.pack('>2sHIIIIBBHQ', b'EB', 3, n, FLAGS, names_off, names_size, fnl, dnl, len(folders), total)
    toc = bytearray(head + bytes(0x30 - len(head)) + table)
    toc += bytes(_a16(len(toc)) - len(toc)) + bytes(n)
    toc += bytes(names_off - len(toc))
    toc += recs + bytes(_a16(len(recs)) - len(recs))
    toc += b''.join(d.encode('latin1').ljust(dnl, b'\0') for d in folders)
    toc += bytes(names_off + names_size - len(toc))
    return bytes(toc), slots, total


def _stream(folders, entries):
    toc, slots, total = _layout(folders, entries)
    yield toc
    pos = len(toc)
    for o, e in slots:
        if o > pos:
            yield bytes(o - pos)
        yield from e.chunks()
        pos = o + e.size
    if total > pos:
        yield bytes(total - pos)


def _write(out, folders, entries):
    """Write the archive through `out`.tmp (renamed at the end); returns its sha256."""
    h = hashlib.sha256()
    tmp = out + '.tmp'
    try:
        with open(tmp, 'wb') as f:
            for b in _stream(folders, entries):
                f.write(b)
                h.update(b)
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return h.hexdigest()


def _changed(folders, entries, changes):
    """Entries with `changes` ({path: bytes}) applied: replaced ones keep their data slot, new ones go last."""
    entries = list(entries)
    at = {e.path: i for i, e in enumerate(entries)}
    for p, data in changes.items():
        p = p.replace('\\', '/').lower()
        new = _Entry(p, data=data if hasattr(data, 'read') else bytes(data))   # art.Stored: read when it is written
        if p in at:
            entries[at[p]] = new
        else:
            at[p] = len(entries)
            entries.append(new)
    return folders, entries


def rebuild(src, out, changes=None):
    """Write archive `src` again to `out` with `changes` ({path: bytes}: entries replaced or added). Without changes
    the copy is byte-identical. Returns the sha256 of `out`."""
    if os.path.abspath(src) == os.path.abspath(out):
        raise ValueError('rebuild writes a new file: out must differ from src')
    return _write(out, *_changed(*_parse(src), changes or {}))


def add_entry(src, out, path, data):
    """`rebuild` with one entry added (or replaced)."""
    return rebuild(src, out, {path: data})


def new_archive(out, files):
    """A new archive holding only `files` ({path: bytes}, stored raw). Returns its sha256."""
    if not files:
        raise ValueError('an archive needs at least one entry')
    return _write(out, *_changed([], [], files))


def archive_bytes(files):
    """The bytes `new_archive` would write."""
    return b''.join(_stream(*_changed([], [], files)))


def verify_rebuild(src):
    """None when a rebuild of `src` is byte-identical to it, else the first differing offset."""
    with open(src, 'rb') as f:
        pos = 0
        for b in _stream(*_parse(src)):
            o = f.read(len(b))
            if o != b:
                return pos + next((i for i in range(min(len(o), len(b))) if o[i] != b[i]), min(len(o), len(b)))
            pos += len(b)
        if f.read(1):
            return pos
    return None
