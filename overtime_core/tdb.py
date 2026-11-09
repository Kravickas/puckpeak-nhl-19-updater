"""EA t3db database codec for NHL 19 (PS4). All integers are little-endian.

File layout:
  0x00 "DB" 00 08, u32 0, u32 file size, u32 0, u32 table count, u32 CRC of bytes 0..0x14
  0x18 table index: per table a 4-character tag and a u32 offset (from the end of the index)
  tables, in index order; the file ends with a u32 CRC of the last table's bytes from +0x28.

Table: 40-byte header, 16-byte field definitions, then `max records x record length` bytes.
  +0x00 chain CRC: of the index for the first table, else of the previous table from its +0x28
  +0x04 u32 2, +0x08 record length (bytes), +0x0C record length in bits - 1, +0x10 u32 0,
  +0x14 u16 max records, +0x16 u16 current records, +0x18 u32 (0xFFFF0000 in the game's DB),
  +0x1C u8 field count, +0x1D u8 index count, +0x20 u32 0, +0x24 CRC of header bytes 4..0x24.
Field definition: u32 type (0 string, 3 unsigned int, 13/14 compressed string), u32 bit offset, 4-char tag,
u32 bit count. Records are bit-packed LSB-first over the record's bytes; strings are byte-aligned, NUL-padded
UTF-8. Integers are stored as value - rangelow (from the schema). All CRCs are CRC-32/MPEG-2.

Compressed strings (the loc databases): header +0x04 has bit 0x40 and +0x10 holds the size of a string area
that follows the records. The area starts with a Huffman tree (4 bytes per node, root = node 0; each half is
`child, 0` or `0, byte` for a leaf; bit 0 = first half), then the strings. The record field is a u32 offset
into the area; there a string is a big-endian length (u8 for type 13, u16 for type 14, in bytes) followed by
the codes MSB-first, written as bits // 8 + 1 bytes. Offset 0xFFFFFFFF = no string (reads as "").

Indexes (league tables of Franchise / Season / Be a Pro saves, e.g. leaguerostertable): their definitions follow the
records (and string area); kept as read, as in Legacy's PS3 codec (`stock.INDEXES`).
"""
import heapq
import struct

from .crc import crc32_mpeg2

MAGIC = b'DB\x00\x08'
FREE_BYTE = b'\xdb'  # the bytes of the records past `count` in the game's files
TYPE_STRING, TYPE_INT, TYPE_HUFF8, TYPE_HUFF16 = 0, 3, 13, 14
_HUFF_PREFIX = {TYPE_HUFF8: 1, TYPE_HUFF16: 2}
HUFF_FLAG = 0x40
HUFF_NULL = 0xFFFFFFFF  # offset of a missing compressed string


class FormatError(ValueError):
    pass


class Field:
    __slots__ = ('tag', 'type', 'bit', 'depth', 'name', 'low')

    def __init__(self, tag, ftype, bit, depth, name=None, low=0):
        self.tag, self.type, self.bit, self.depth, self.name, self.low = tag, ftype, bit, depth, name or tag, low

    @property
    def is_string(self):
        return self.type == TYPE_STRING

    @property
    def is_huff(self):
        return self.type in _HUFF_PREFIX

    @property
    def width(self):
        """Bits the field takes in the record: a compressed string is a u32 offset, its depth is the max length."""
        return 32 if self.is_huff else self.depth

    def __repr__(self):
        return f"Field({self.name}/{self.tag} t{self.type} bit {self.bit} depth {self.depth})"


class HuffmanTree:
    """The byte-level Huffman tree of a compressed-string area."""

    def __init__(self, nodes):
        self.nodes = nodes  # [(left, right)]; an entry is ('n', index) or ('c', byte)
        self.codes = {}
        stack = [(0, 0, 0)]
        while stack:
            i, bits, n = stack.pop()
            for v, (kind, x) in enumerate(self.nodes[i]):
                if kind == 'c':
                    self.codes[x] = ((bits << 1) | v, n + 1)
                else:
                    stack.append((x, (bits << 1) | v, n + 1))
        self._steps = [None] * (256 * len(self.nodes))  # node << 8 | byte: (symbols, next node), made when first met

    def _step(self, key):
        """Walk the 8 bits of one input byte from a node: the symbols it finishes and the node it ends on."""
        i, byte, out = key >> 8, key & 0xff, bytearray()
        for k in range(7, -1, -1):
            kind, x = self.nodes[i][(byte >> k) & 1]
            if kind == 'c':
                out.append(x)
                i = 0
            else:
                i = x
        self._steps[key] = step = (bytes(out), i)
        return step

    @classmethod
    def parse(cls, area):
        nodes, todo = {}, [0]
        while todo:
            i = todo.pop()
            if i in nodes:
                continue
            e = area[4 * i:4 * i + 4]
            pair = tuple(('c', e[k + 1]) if e[k] == 0 else ('n', e[k]) for k in (0, 2))
            nodes[i] = pair
            todo += [x for kind, x in pair if kind == 'n']
        if sorted(nodes) != list(range(len(nodes))):
            raise FormatError('Huffman tree nodes are not contiguous')
        return cls([nodes[k] for k in range(len(nodes))])

    @classmethod
    def build(cls, counts):
        """A tree for the byte frequencies in `counts` (dict byte -> count)."""
        syms = [b for b, c in counts.items() if c]
        while len(syms) < 2:  # a tree needs two leaves
            syms.append(next(b for b in range(256) if b not in syms))
        heap = [(counts.get(b, 0), k, ('c', b)) for k, b in enumerate(sorted(syms))]
        heapq.heapify(heap)
        k = len(heap)
        while len(heap) > 1:
            c1, _, a = heapq.heappop(heap)
            c2, _, b = heapq.heappop(heap)
            heapq.heappush(heap, (c1 + c2, k, ('t', a, b)))
            k += 1
        # number the internal nodes breadth-first so that the root is node 0
        root = heap[0][2]
        nodes, queue, count = [], [root], 1
        while queue:
            t = queue.pop(0)
            pair = []
            for child in t[1:]:
                if child[0] == 'c':
                    pair.append(child)
                else:
                    queue.append(child)
                    pair.append(('n', count))
                    count += 1
            nodes.append(tuple(pair))
        if len(nodes) > 255:
            raise ValueError('too many symbols for a byte-indexed Huffman tree')
        return cls(nodes)

    def to_bytes(self):
        return b''.join(bytes([0, x]) if kind == 'c' else bytes([x, 0]) for pair in self.nodes for kind, x in pair)

    def decode(self, area, off, prefix):
        """A byte at a time (_step): the bits after the n-th symbol are padding, so the last byte's extra symbols
        are cut off."""
        n = int.from_bytes(area[off:off + prefix], 'big')
        pos, node, out, steps = off + prefix, 0, bytearray(), self._steps
        while len(out) < n:
            key = (node << 8) | area[pos]
            got, node = steps[key] or self._step(key)
            out += got
            pos += 1
        return bytes(out[:n])

    def decode_bits(self, area, off, prefix):
        """decode, a bit at a time (the reference the tests hold decode to)."""
        n = int.from_bytes(area[off:off + prefix], 'big')
        pos, bit, out = off + prefix, 0, bytearray()
        for _ in range(n):
            i = 0
            while True:
                v = (area[pos + (bit >> 3)] >> (7 - (bit & 7))) & 1
                bit += 1
                kind, x = self.nodes[i][v]
                if kind == 'c':
                    out.append(x)
                    break
                i = x
        return bytes(out)

    def encode(self, raw, prefix):
        if len(raw) >= 1 << (8 * prefix):
            raise ValueError(f"string of {len(raw)} bytes does not fit a {prefix}-byte length")
        acc = n = 0
        for b in raw:
            code, k = self.codes[b]
            acc, n = (acc << k) | code, n + k
        nbytes = n // 8 + 1
        return len(raw).to_bytes(prefix, 'big') + (acc << (8 * nbytes - n)).to_bytes(nbytes, 'big')


class Table:
    def __init__(self, tag, header, fields, data, meta=None, strings=b'', indexes=b''):
        self.tag = tag
        self.meta = meta
        self.name = meta.name if meta else tag
        self._header = bytearray(header)  # kept for the bytes we don't interpret
        self.fields = fields  # in file order
        self.by_name = {f.name: f for f in fields}
        self.data = bytearray(data)
        self._strings = bytes(strings)  # compressed-string area, as read
        self._indexes = bytes(indexes)  # index definitions after the records, as read
        self._tree = HuffmanTree.parse(self._strings) if self._strings else None
        self._edits = {}  # (row, field name) -> new text of a compressed string

    record_length = property(lambda self: struct.unpack_from('<I', self._header, 0x08)[0])
    max_records = property(lambda self: struct.unpack_from('<H', self._header, 0x14)[0])

    @property
    def count(self):
        return struct.unpack_from('<H', self._header, 0x16)[0]

    @count.setter
    def count(self, n):
        if not 0 <= n <= self.max_records:
            raise ValueError(f"{self.name}: {n} records, max {self.max_records}")
        struct.pack_into('<H', self._header, 0x16, n)

    @property
    def flags(self):
        return struct.unpack_from('<I', self._header, 0x18)[0]

    def _field(self, name):
        try:
            return self.by_name[name]
        except KeyError:
            raise KeyError(f"{self.name}: no field {name!r}") from None

    def _rec(self, row):
        if not 0 <= row < self.max_records:
            raise IndexError(f"{self.name}: row {row} out of range")
        n = self.record_length
        return row * n, n

    def _raw(self, start, n, f):
        v = int.from_bytes(self.data[start:start + n], 'little')
        return (v >> f.bit) & ((1 << f.width) - 1)

    def _huff_get(self, row, f, start, n):
        if (row, f.name) in self._edits:
            return self._edits[(row, f.name)]
        off = self._raw(start, n, f)
        if off == HUFF_NULL:
            return ''
        return self._tree.decode(self._strings, off, _HUFF_PREFIX[f.type]).decode('utf-8', 'replace')

    def get(self, row, name):
        f = self._field(name)
        start, n = self._rec(row)
        if f.is_huff:
            return self._huff_get(row, f, start, n)
        if f.is_string:
            raw = bytes(self.data[start + f.bit // 8:start + (f.bit + f.depth) // 8])
            return raw.split(b'\0', 1)[0].decode('utf-8', 'replace')
        v = int.from_bytes(self.data[start:start + n], 'little')
        return ((v >> f.bit) & ((1 << f.depth) - 1)) + f.low

    def set(self, row, name, value):
        f = self._field(name)
        start, n = self._rec(row)
        if f.is_huff:
            raw = str(value).encode('utf-8')
            if len(raw) > f.depth // 8 or len(raw) >= 1 << (8 * _HUFF_PREFIX[f.type]):
                raise ValueError(f"{self.name}.{name}: {len(raw)} bytes, max {f.depth // 8}")
            self._edits[(row, f.name)] = str(value)
            return
        if f.is_string:
            size = f.depth // 8
            raw = str(value).encode('utf-8')
            if len(raw) >= size:
                raise ValueError(f"{self.name}.{name}: {value!r} is longer than {size - 1} bytes")
            a = start + f.bit // 8
            self.data[a:a + size] = raw.ljust(size, b'\0')
            return
        stored = int(value) - f.low
        if not 0 <= stored < (1 << f.depth):
            raise ValueError(f"{self.name}.{name}: {value} does not fit ({f.depth} bits from {f.low})")
        v = int.from_bytes(self.data[start:start + n], 'little')
        mask = ((1 << f.depth) - 1) << f.bit
        v = (v & ~mask) | (stored << f.bit)
        self.data[start:start + n] = v.to_bytes(n, 'little')

    def column(self, name):
        """[value of field `name` for each record], the same as [get(r, name) for r in range(count)] in one pass:
        the header, the field and the record length are read once, and only the bytes the field sits in are
        unpacked (a whole-table scan with get() re-reads them per row)."""
        f = self._field(name)
        count, n = self.count, self.record_length
        if f.is_huff or f.is_string:
            return [self.get(r, name) for r in range(count)]
        b0, b1 = f.bit // 8, (f.bit + f.depth + 7) // 8
        shift, mask, low = f.bit - 8 * b0, (1 << f.depth) - 1, f.low
        view, fb = memoryview(self.data), int.from_bytes
        return [((fb(view[o + b0:o + b1], 'little') >> shift) & mask) + low for o in range(0, count * n, n)]

    def row(self, row):
        """All fields of one record as a dict (field name -> value)."""
        start, n = self._rec(row)
        rec = bytes(self.data[start:start + n])
        v = int.from_bytes(rec, 'little')
        out = {}
        for f in self.fields:
            if f.is_huff:
                out[f.name] = self._huff_get(row, f, start, n)
            elif f.is_string:
                out[f.name] = rec[f.bit // 8:(f.bit + f.depth) // 8].split(b'\0', 1)[0].decode('utf-8', 'replace')
            else:
                out[f.name] = ((v >> f.bit) & ((1 << f.depth) - 1)) + f.low
        return out

    def rows(self):
        return [self.row(r) for r in range(self.count)]

    def append(self, values=None, like=None):
        """Add a record after the last one and return its row: a copy of row `like` (else all bits zero), then
        `values` (field name -> value) set on it. The other records stay byte for byte."""
        if self._strings:
            raise NotImplementedError(f"{self.name}: append to a table with compressed strings")
        row = self.count
        if row >= self.max_records:
            raise ValueError(f"{self.name}: full ({self.max_records} records)")
        start, n = self._rec(row)
        if like is None:
            self.data[start:start + n] = bytes(n)
        else:
            a, _ = self._rec(like)
            self.data[start:start + n] = self.data[a:a + n]
        self.count = row + 1
        for name, value in (values or {}).items():
            self.set(row, name, value)
        return row

    def insert(self, at, values=None, like=None):
        """Add a record at row `at` (the records from `at` on move down one): a copy of row `like` (numbered before
        the move; else all bits zero), then `values` set on it. Returns `at`. For tables the game keeps sorted."""
        if self._strings:
            raise NotImplementedError(f"{self.name}: insert into a table with compressed strings")
        count = self.count
        if not 0 <= at <= count:
            raise IndexError(f"{self.name}: row {at} out of range")
        if count >= self.max_records:
            raise ValueError(f"{self.name}: full ({self.max_records} records)")
        n = self.record_length
        rec = bytes(self.data[like * n:(like + 1) * n]) if like is not None else bytes(n)
        self.data[(at + 1) * n:(count + 1) * n] = self.data[at * n:count * n]
        self.data[at * n:(at + 1) * n] = rec
        self.count = count + 1
        for name, value in (values or {}).items():
            self.set(at, name, value)
        return at

    def delete(self, row):
        """Remove the record at `row` (the ones after it move up one; the freed last record gets 0xDB bytes)."""
        if self._strings:
            raise NotImplementedError(f"{self.name}: delete from a table with compressed strings")
        count = self.count
        if not 0 <= row < count:
            raise IndexError(f"{self.name}: row {row} out of range")
        n = self.record_length
        self.data[row * n:(count - 1) * n] = self.data[(row + 1) * n:count * n]
        self.data[(count - 1) * n:count * n] = FREE_BYTE * n
        self.count = count - 1

    def sort_by(self, *names):
        """Put the records in order of the fields `names` (stable: equal keys keep their order). The records move
        whole, byte for byte; returns True if any moved. For the tables the game keeps sorted, after append()."""
        if self._strings:
            raise NotImplementedError(f"{self.name}: sort a table with compressed strings")
        order = sorted(range(self.count), key=lambda r: tuple(self.get(r, f) for f in names))
        if order == list(range(self.count)):
            return False
        n = self.record_length
        old = bytes(self.data[:self.count * n])
        self.data[:self.count * n] = b''.join(old[r * n:(r + 1) * n] for r in order)
        return True

    def clear(self):
        """Remove every record; free records hold 0xDB bytes, as in the game's files."""
        if self._strings:
            raise NotImplementedError(f"{self.name}: clear a table with compressed strings")
        self.data[:] = FREE_BYTE * len(self.data)
        self.count = 0

    def state(self):
        """Everything an edit can change (records, count, compressed strings), for restore()."""
        return bytes(self._header), bytes(self.data), self._strings, self._tree, dict(self._edits)

    def restore(self, state):
        header, data, self._strings, self._tree, edits = state
        self._header[:] = header
        self.data[:] = data
        self._edits = dict(edits)

    def _pack_strings(self):
        """Rebuild the compressed-string area after edits; strings keep their original order."""
        hf = [f for f in self.fields if f.is_huff]
        if not hf or not self._edits:
            return
        n = self.record_length
        entries = sorted(((self._raw(row * n, n, f), row, f) for row in range(self.count) for f in hf),
                         key=lambda e: e[0])
        texts = {}
        for off, row, f in entries:
            key = (row, f.name)
            if key in self._edits:
                texts[key] = self._edits[key].encode('utf-8')
            else:
                texts[key] = b'' if off == HUFF_NULL else self._tree.decode(self._strings, off, _HUFF_PREFIX[f.type])
        tree = self._tree
        if any(b not in tree.codes for t in texts.values() for b in set(t)):
            counts = {}
            for t in texts.values():
                for b in t:
                    counts[b] = counts.get(b, 0) + 1
            tree = HuffmanTree.build(counts)
        out, placed = bytearray(tree.to_bytes()), {}
        for off, row, f in entries:
            key = (row, f.name)
            if off == HUFF_NULL and not texts[key]:
                new = HUFF_NULL
            elif key not in self._edits and off in placed:
                new = placed[off]
            else:
                new = len(out)
                out += tree.encode(texts[key], _HUFF_PREFIX[f.type])
                if key not in self._edits:
                    placed[off] = new
            start = row * n
            v = int.from_bytes(self.data[start:start + n], 'little')
            mask = ((1 << f.width) - 1) << f.bit
            self.data[start:start + n] = ((v & ~mask) | (new << f.bit)).to_bytes(n, 'little')
        self._strings, self._tree, self._edits = bytes(out), tree, {}

    def header_bytes(self, chain_crc):
        self._pack_strings()
        h = bytearray(self._header)
        struct.pack_into('<I', h, 0x00, chain_crc)
        if self._strings:
            struct.pack_into('<I', h, 0x10, len(self._strings))
        h[0x1C] = len(self.fields)
        struct.pack_into('<I', h, 0x24, crc32_mpeg2(h[4:0x24]))
        return bytes(h)

    def body_bytes(self):
        """Everything after the 40-byte header: field definitions, records and the compressed-string area."""
        self._pack_strings()
        defs = b''.join(struct.pack('<II4sI', f.type, f.bit, f.tag.encode('ascii'), f.depth) for f in self.fields)
        return defs + bytes(self.data) + self._strings + self._indexes


class Database:
    def __init__(self, tables, header=b''):
        self.tables = tables  # list, file order
        self._by = {}
        for t in tables:
            self._by[t.tag] = t
            self._by[t.name] = t
        self._header = header

    def __getitem__(self, name):
        return self._by[name]

    def __contains__(self, name):
        return name in self._by

    def add(self, table):
        """Add a table at the end (e.g. a copy of another database's)."""
        if table.tag in self._by or table.name in self._by:
            raise ValueError(f"{table.name}: already in the database")
        self.tables.append(table)
        self._by[table.tag] = self._by[table.name] = table

    def keep(self):
        """Which tables there are and the state of each, for put_back()."""
        return list(self.tables), [t.state() for t in self.tables]

    def put_back(self, kept):
        tables, states = kept
        self.tables[:] = tables
        self._by = {}
        for t, st in zip(tables, states):
            t.restore(st)
            self._by[t.tag] = self._by[t.name] = t

    def subset(self, savegroup, order=None):
        """A database of this one's tables in `savegroup` (the shape of a roster file), sharing their data.

        `order` lists table tags in the order to write them, e.g. copied from one of the game's own
        files of that group; the game's files don't follow the full database's order.
        """
        tables = [t for t in self.tables if t.meta and savegroup in t.meta.savegroups]
        if order is not None:
            rank = {tag: i for i, tag in enumerate(order)}
            if set(rank) != {t.tag for t in tables}:
                raise ValueError(f"order does not list exactly the {savegroup!r} tables")
            tables.sort(key=lambda t: rank[t.tag])
        return Database(tables, self._header)

    @classmethod
    def parse(cls, data, schema=None, verify=True):
        data = bytes(data)
        if data[:4] != MAGIC:
            raise FormatError('not a t3db database')
        size, ntab, hcrc = struct.unpack_from('<I', data, 8)[0], *struct.unpack_from('<II', data, 0x10)
        if size != len(data):
            raise FormatError(f"size field {size} != file size {len(data)}")
        if verify and hcrc != crc32_mpeg2(data[:0x14]):
            raise FormatError('header CRC mismatch')
        base = 0x18 + ntab * 8
        index = [(data[0x18 + i * 8:0x1C + i * 8].decode('ascii'), struct.unpack_from('<I', data, 0x1C + i * 8)[0])
                 for i in range(ntab)]
        tables = []
        prev = data[0x18:base]
        for i, (tag, off) in enumerate(index):
            t = base + off
            end = base + index[i + 1][1] if i + 1 < ntab else len(data) - 4
            h = data[t:t + 0x28]
            if verify:
                if struct.unpack_from('<I', h, 0)[0] != crc32_mpeg2(prev):
                    raise FormatError(f"{tag}: checksum chain broken")
                if struct.unpack_from('<I', h, 0x24)[0] != crc32_mpeg2(h[4:0x24]):
                    raise FormatError(f"{tag}: header CRC mismatch")
            reclen, nf, nidx = struct.unpack_from('<I', h, 0x08)[0], h[0x1C], h[0x1D]
            maxn = struct.unpack_from('<H', h, 0x14)[0]
            tmeta = schema.tables.get(tag) if schema else None
            fields = []
            for k in range(nf):
                ftype, bit, ftag, depth = struct.unpack_from('<II4sI', data, t + 0x28 + k * 16)
                ftag = ftag.decode('ascii')
                fm = tmeta.fields.get(ftag) if tmeta else None
                fields.append(Field(ftag, ftype, bit, depth, fm.name if fm else None, fm.low if fm and not fm.is_string else 0))
            d0 = t + 0x28 + nf * 16
            strsize = struct.unpack_from('<I', h, 0x10)[0] if struct.unpack_from('<I', h, 4)[0] & HUFF_FLAG else 0
            rec_end = d0 + reclen * maxn
            extra = end - rec_end - strsize
            if extra < 0 or (extra > 0) != (nidx > 0):
                raise FormatError(f"{tag}: {end - d0} data bytes, expected {reclen * maxn + strsize}"
                                  f" plus {nidx} index definitions")
            tables.append(Table(tag, h, fields, data[d0:rec_end], tmeta, data[rec_end:rec_end + strsize],
                                data[rec_end + strsize:end]))
            prev = data[t + 0x28:end]
        if verify and struct.unpack_from('<I', data, len(data) - 4)[0] != crc32_mpeg2(prev):
            raise FormatError('end CRC mismatch')
        return cls(tables, data[:0x18])

    def to_bytes(self):
        bodies = [t.body_bytes() for t in self.tables]
        offsets, off = [], 0
        for b in bodies:
            offsets.append(off)
            off += 0x28 + len(b)
        ntab = len(self.tables)
        index = b''.join(t.tag.encode('ascii') + struct.pack('<I', o) for t, o in zip(self.tables, offsets))
        size = 0x18 + len(index) + off + 4
        head = bytearray(self._header or MAGIC + bytes(0x14))
        head[:4] = MAGIC
        struct.pack_into('<III', head, 8, size, struct.unpack_from('<I', head, 0x0C)[0], ntab)
        struct.pack_into('<I', head, 0x14, crc32_mpeg2(head[:0x14]))
        out = [bytes(head), index]
        prev = index
        for t, b in zip(self.tables, bodies):
            out += [t.header_bytes(crc32_mpeg2(prev)), b]
            prev = b
        out.append(struct.pack('<I', crc32_mpeg2(prev)))
        return b''.join(out)
