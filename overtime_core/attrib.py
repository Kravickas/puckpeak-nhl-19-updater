"""Read EA 'Attrib' vaults (NHL 19 boot.big: nhl/data/common/database/attrib/gc*.vlt + .bin). Read-only so far.

What is parsed (docs/notes/attrib-vlt.md has the facts and the open questions):
  .vlt  chunks: 8-byte header (4-byte tag stored reversed, u32 size incl. header), 16-byte aligned.
        Vers, StrN, DepN, DatN (blocks), ExpN (collection table), PtrN (fixups), EndC.
  .bin  StrE (NUL-separated strings from file offset 8), TofC ((u32 type, u32 key) table), EndC, then a raw
        blob region with no chunk header (texpack records, pointers, floats).

Not done: writing and the kit -> texpack link. Nothing here changes a vault. `lookup2` is the eboot's name hash (class
names, `default`); the collection keys of kit texpacks are not a plain hash of their names (docs/notes/attrib-vlt.md).
"""
import struct

CHUNK_HDR = 8
_M = 0xffffffff


def _mix(a, b, c):
    a = (a - b - c) & _M; a ^= c >> 13
    b = (b - c - a) & _M; b ^= (a << 8) & _M
    c = (c - a - b) & _M; c ^= b >> 13
    a = (a - b - c) & _M; a ^= c >> 12
    b = (b - c - a) & _M; b ^= (a << 16) & _M
    c = (c - a - b) & _M; c ^= b >> 5
    a = (a - b - c) & _M; a ^= c >> 3
    b = (b - c - a) & _M; b ^= (a << 10) & _M
    c = (c - a - b) & _M; c ^= b >> 15
    return a, b, c


def lookup2(data, init=0xabcdef00):
    """Jenkins lookup2 as the eboot's FUN_033390d0 (init 0xabcdef00): class and attribute name keys."""
    n = len(data)
    a = b = 0x9e3779b9
    c = init
    i = 0
    while n - i >= 12:
        a = (a + struct.unpack_from('<I', data, i)[0]) & _M
        b = (b + struct.unpack_from('<I', data, i + 4)[0]) & _M
        c = (c + struct.unpack_from('<I', data, i + 8)[0]) & _M
        a, b, c = _mix(a, b, c)
        i += 12
    c = (c + n) & _M
    rest = data[i:] + bytes(12)
    m = n - i
    if m >= 9:
        c = (c + (rest[8] << 8) + (rest[9] << 16) + (rest[10] << 24)) & _M
    if m >= 5:
        b = (b + sum(rest[4 + j] << (8 * j) for j in range(min(4, m - 4)))) & _M
    if m >= 1:
        a = (a + sum(rest[j] << (8 * j) for j in range(min(4, m)))) & _M
    return _mix(a, b, c)[2]


def _tag(raw):
    return raw[::-1].decode('latin1')


def chunks(data):
    """[(tag, file offset, size)] of the chunks of a .vlt or .bin file, in file order."""
    out, off = [], 0
    while off + CHUNK_HDR <= len(data):
        size = struct.unpack_from('<I', data, off + 4)[0]
        if size < CHUNK_HDR:
            break
        out.append((_tag(data[off:off + 4]), off, size))
        off += size
    return out


def chunk(data, tag):
    """(offset, size) of the first chunk with this tag (e.g. 'ExpN'), or None."""
    for t, off, size in chunks(data):
        if t == tag:
            return off, size
    return None


def expn(vlt):
    """Collection table: [(key, cls, size, off)]. `off` is measured from the DatN chunk start (its file offset)."""
    off, _ = chunk(vlt, 'ExpN')
    count = struct.unpack_from('<I', vlt, off + CHUNK_HDR)[0]
    base = off + CHUNK_HDR + 4
    return [struct.unpack_from('<IIII', vlt, base + 16 * i) for i in range(count)]


def ptrn(vlt):
    """Fixups: [(slot offset, type | dep << 16, target)]. The header record (0, 0x10002, 0) is included."""
    off, size = chunk(vlt, 'PtrN')
    n = (size - CHUNK_HDR) // 12
    return [struct.unpack_from('<III', vlt, off + CHUNK_HDR + 12 * i) for i in range(n)]


def tofc(binary):
    """TofC table of a .bin: (first 8 bytes as u64, [(type, key)] for the rest). Count is the chunk's u32 at +8."""
    off, _ = chunk(binary, 'TofC')
    count = struct.unpack_from('<I', binary, off + 8)[0]
    head = struct.unpack_from('<Q', binary, off + 16)[0]
    pairs = [struct.unpack_from('<II', binary, off + 24 + 8 * i) for i in range(count - 1)]
    return head, pairs


def strings(binary):
    """The StrE strings (NUL-separated, from file offset 8), as a list of bytes."""
    off, size = chunk(binary, 'StrE')
    return binary[off + CHUNK_HDR:off + size].split(b'\0')


GE_TEXTURE_TAG = 0xed5e8a2c
JERSEY_TEXPACK_CLASS = 0xe410320e
COLLECTION_STRIDE = 96
TEXPACK_SIZE = 216


def class_keys(binary, cls_name):
    """Collection keys listed under one class in the TofC (cls_name as the eboot spells it, e.g. 'ge_texture')."""
    want = lookup2(cls_name.encode() if isinstance(cls_name, str) else cls_name)
    return [key for typ, key in tofc(binary)[1] if typ == want]


def texpack_records(vlt, binary):
    """{texpack name: offset of its 216-byte record in the .bin} for every name slot in PtrN (10,828 names).

    A name slot is a PtrN type-3 fixup whose slot lies in the .bin and whose target is a NUL-terminated string ending
    in '_texpack'. The record starts at the slot (its first 8 bytes are the zero-filled name pointer)."""
    out = {}
    for slot, typ, target in ptrn(vlt):
        if typ != 0x10003 or slot >= len(binary) or target >= len(binary):
            continue
        end = binary.find(b'\0', target)
        name = binary[target:end]
        if name.endswith(b'_texpack'):
            out[name.decode('latin1')] = slot
    return out


def texpack_texture_refs(binary, off):
    """The ge_texture collection keys a 216-byte texpack record refers to, in record order (10 for jersey texpacks).

    Each reference is a (0xed5e8a2c, key) pair at 8-byte stride inside the record, from +0x18."""
    refs = []
    for pos in range(off + 0x18, off + TEXPACK_SIZE - 4, 4):
        if struct.unpack_from('<I', binary, pos)[0] == GE_TEXTURE_TAG:
            refs.append(struct.unpack_from('<I', binary, pos + 4)[0])
    return refs


def jersey_collection_offsets(vlt, binary):
    """{collection key: DatN offset} of the 96-byte jersey texpack collection records (1,318 in NHL 19).

    Keys come from the TofC rows of class ge_nhl_skaterjerseytexturepack; each record starts with its key, then its
    class (0xe410320e). The DatN order equals the TofC order. Records are 96 bytes apart in one run."""
    datn, _ = chunk(vlt, 'DatN')
    out = {}
    for key in class_keys(binary, 'ge_nhl_skaterjerseytexturepack'):
        pos = vlt.find(struct.pack('<I', key), datn)
        if pos >= 0 and struct.unpack_from('<I', vlt, pos + 4)[0] == JERSEY_TEXPACK_CLASS:
            out[key] = pos
    return out


ATTRIB_LOAD_CLASS = 0x8e112eb7   # lookup2('Attrib::CollectionLoadData'): the ExpN class of every collection entry


def expn_rows_at(vlt, positions):
    """{vlt offset: ExpN row (key, cls, size, off)} for the ExpN rows whose record starts at one of `positions`.

    ExpN `off` is measured from the DatN chunk start, so the record start is DatN + off."""
    datn, _ = chunk(vlt, 'DatN')
    want = set(positions)
    return {datn + row[3]: row for row in expn(vlt) if datn + row[3] in want}


def texpack_index_word(binary, off):
    """The u32 at +8 of a 216-byte texpack record. For jersey texpacks it equals the kit index in
    1,158 of 1,318 records: home 0, away 1, two 2, three 3, four 4 (docs/notes/attrib-vlt.md)."""
    return struct.unpack_from('<I', binary, off + 8)[0]
