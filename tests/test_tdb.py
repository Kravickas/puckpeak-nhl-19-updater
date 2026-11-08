import struct

import pytest

from overtime_core.crc import crc32_mpeg2
from overtime_core.schema import parse_schema
from overtime_core.tdb import (HUFF_FLAG, HUFF_NULL, TYPE_HUFF8, TYPE_HUFF16, TYPE_INT, TYPE_STRING, Database, Field,
                                FormatError, HuffmanTree, Table)

SCHEMA = parse_schema(b"""<?xml version="1.0" encoding="utf-8"?>
<database name="test" shortname="test" version="1">
  <table name="players" shortname="PLYR" savegroups="rosters,rosterupdate">
    <fields>
      <field name="index" shortname="indx" type="FIELDTYPE_INTEGER" depth="10" rangelow="0" rangehigh="1023" key="True" />
      <field name="team" shortname="team" type="FIELDTYPE_INTEGER" depth="6" rangelow="-1" rangehigh="62" />
      <field name="lastname" shortname="lnam" type="FIELDTYPE_STRING" depth="64" rangelow="0" rangehigh="0" />
    </fields>
  </table>
  <table name="teams" shortname="TEAM" savegroups="rosters">
    <fields>
      <field name="index" shortname="indx" type="FIELDTYPE_INTEGER" depth="8" rangelow="0" rangehigh="255" key="True" />
    </fields>
  </table>
</database>""")


def make_table(tag, fields, reclen, maxn, count, meta=None):
    h = bytearray(0x28)
    struct.pack_into('<IIII', h, 4, 2, reclen, reclen * 8 - 1, 0)
    struct.pack_into('<HHII', h, 0x14, maxn, count, 0xFFFF0000, len(fields))
    return Table(tag, h, fields, bytes(reclen * maxn), meta)


def make_db():
    players = make_table('PLYR', [Field('indx', TYPE_INT, 0, 10, 'index'), Field('team', TYPE_INT, 10, 6, 'team', -1),
                                  Field('lnam', TYPE_STRING, 16, 64, 'lastname')], 12, 4, 2, SCHEMA.tables['PLYR'])
    teams = make_table('TEAM', [Field('indx', TYPE_INT, 0, 8, 'index')], 4, 3, 3, SCHEMA.tables['TEAM'])
    return Database([players, teams])


def test_build_parse_roundtrip():
    db = make_db()
    p = db['players']
    p.set(0, 'index', 1)
    p.set(0, 'team', -1)
    p.set(0, 'lastname', 'Kesler')
    p.set(1, 'index', 1023)
    p.set(1, 'team', 62)
    raw = db.to_bytes()
    db2 = Database.parse(raw, SCHEMA)
    assert db2.to_bytes() == raw
    assert db2['PLYR'].rows() == [{'index': 1, 'team': -1, 'lastname': 'Kesler'},
                                  {'index': 1023, 'team': 62, 'lastname': ''}]


def test_layout_matches_format():
    raw = make_db().to_bytes()
    assert raw[:4] == b'DB\x00\x08'
    assert struct.unpack_from('<I', raw, 8)[0] == len(raw)
    assert struct.unpack_from('<I', raw, 0x14)[0] == crc32_mpeg2(raw[:0x14])
    base = 0x18 + 2 * 8
    assert struct.unpack_from('<I', raw, base)[0] == crc32_mpeg2(raw[0x18:base])  # chain starts at the index


def test_stored_value_is_offset_by_rangelow():
    db = make_db()
    db['players'].set(0, 'team', -1)
    rec = int.from_bytes(db['players'].data[:12], 'little')
    assert (rec >> 10) & 0x3F == 0


def test_value_range_and_string_length_checked():
    p = make_db()['players']
    with pytest.raises(ValueError):
        p.set(0, 'team', 63)
    with pytest.raises(ValueError):
        p.set(0, 'team', -2)
    with pytest.raises(ValueError):
        p.set(0, 'lastname', 'x' * 8)  # 8 bytes leave no room for the terminator
    p.set(0, 'lastname', 'x' * 7)


@pytest.mark.parametrize('offset', [0x14, 0x30, -1])
def test_corruption_is_detected(offset):
    raw = bytearray(make_db().to_bytes())
    raw[offset] ^= 0xFF
    with pytest.raises(FormatError):
        Database.parse(bytes(raw), SCHEMA)


def test_neighbouring_fields_untouched():
    p = make_db()['players']
    p.set(0, 'index', 1023)
    p.set(0, 'team', 5)
    p.set(0, 'index', 0)
    assert p.get(0, 'team') == 5


def test_subset_by_savegroup_and_order():
    db = make_db()
    sub = db.subset('rosterupdate')
    assert [t.name for t in sub.tables] == ['players']
    both = db.subset('rosters', order=['TEAM', 'PLYR'])
    assert [t.tag for t in both.tables] == ['TEAM', 'PLYR']
    assert Database.parse(both.to_bytes(), SCHEMA)['players'].count == 2
    with pytest.raises(ValueError):
        db.subset('rosters', order=['TEAM'])


@pytest.mark.game
def test_game_database_roundtrip_byte_exact(game_db):
    raw, schema = game_db
    db = Database.parse(raw, schema)
    assert db.to_bytes() == raw
    assert len(db.tables) == 111


@pytest.mark.game
def test_game_database_edit_survives_reparse(game_db):
    raw, schema = game_db
    db = Database.parse(raw, schema)
    bio = db['exhibitionplayerbiotable']
    row = next(r for r in range(bio.count) if bio.get(r, 'lastname') == 'Getzlaf')
    bio.set(row, 'jersey', 97)
    again = Database.parse(db.to_bytes(), schema)
    assert again['exhibitionplayerbiotable'].get(row, 'jersey') == 97
    assert again['exhibitionplayerbiotable'].get(row, 'firstname') == 'Ryan'


def make_huff_table(texts):
    """A table of (u8-prefixed id, u16-prefixed text) compressed strings, like the loc databases."""
    counts = {}
    for row in texts:
        for t in row:
            for b in t.encode():
                counts[b] = counts.get(b, 0) + 1
    tree = HuffmanTree.build(counts)
    area, recs = bytearray(tree.to_bytes()), bytearray()
    for sid, text in texts:
        offs = []
        for t, prefix in ((text, 2), (sid, 1)):
            if t:
                offs.append(len(area))
                area += tree.encode(t.encode(), prefix)
            else:
                offs.append(HUFF_NULL)
        recs += struct.pack('<IiI4x', offs[0], 7, offs[1])
    h = bytearray(0x28)
    struct.pack_into('<IIII', h, 4, 2 | HUFF_FLAG, 16, 127, len(area))
    struct.pack_into('<HHII', h, 0x14, len(texts), len(texts), 0xFFFF0000, 3)
    fields = [Field('text', TYPE_HUFF16, 0, 32000), Field('hash', TYPE_INT, 32, 32), Field('stid', TYPE_HUFF8, 64, 800)]
    return Table('LOCS', h, fields, bytes(recs), None, bytes(area))


def test_huffman_tree_roundtrip():
    tree = HuffmanTree.build({ord(c): n for c, n in zip('abcdef', (45, 13, 12, 16, 9, 5))})
    again = HuffmanTree.parse(tree.to_bytes() + b'\xff' * 8)
    for s in (b'', b'a', b'fade', b'cafebabe' * 40):
        enc = again.encode(s, 2)
        assert len(enc) == 2 + sum(tree.codes[b][1] for b in s) // 8 + 1
        assert tree.decode(enc, 0, 2) == s


def test_compressed_strings_roundtrip_and_edit():
    rows = [('TXT_A', 'Hello'), ('TXT_B', ''), ('TXT_C', 'Connect to EA servers')]
    raw = Database([make_huff_table(rows)]).to_bytes()
    t = Database.parse(raw)['LOCS']
    assert [(t.get(r, 'stid'), t.get(r, 'text')) for r in range(3)] == rows
    assert Database.parse(raw).to_bytes() == raw
    t.set(2, 'text', 'Connect to Overtime — community servers')  # new symbols: the tree is rebuilt
    t2 = Database.parse(Database([t]).to_bytes())['LOCS']
    assert t2.get(2, 'text') == 'Connect to Overtime — community servers'
    assert [t2.get(r, 'stid') for r in range(3)] == ['TXT_A', 'TXT_B', 'TXT_C']
    assert t2.get(1, 'text') == '' and t2._raw(16, 16, t2.by_name['text']) == HUFF_NULL
    assert t2.get(0, 'hash') == 7
    with pytest.raises(ValueError):
        t2.set(0, 'stid', 'x' * 101)


@pytest.mark.game
def test_game_loc_database_roundtrip_and_rebuild(game_dir):
    from overtime_core import gamefiles
    raw = gamefiles.read_latest(game_dir, 'nhl/data/kettle/loc/eng_us.db')[0]
    schema = parse_schema(gamefiles.read_latest(game_dir, 'nhl/data/kettle/loc/eng_us-meta.xml')[0])
    db = Database.parse(raw, schema)
    assert db.to_bytes() == raw
    t = db['LanguageStrings']
    t.set(1000, 'sourcetext', t.get(1000, 'sourcetext'))  # forces a rebuild with the game's tree
    assert db.to_bytes() == raw


def test_append_copies_template_and_keeps_other_records():
    db = make_db()
    p = db['players']
    p.set(0, 'index', 5)
    p.set(0, 'lastname', 'Kesler')
    p.set(1, 'index', 6)
    before = bytes(p.data[:24])
    row = p.append({'index': 7, 'team': 3}, like=0)
    assert row == 2 and p.count == 3
    assert p.row(2) == {'index': 7, 'team': 3, 'lastname': 'Kesler'}
    assert bytes(p.data[:24]) == before
    assert p.row(p.append()) == {'index': 0, 'team': -1, 'lastname': ''}
    with pytest.raises(ValueError):
        p.append()
    raw = db.to_bytes()
    assert Database.parse(raw, SCHEMA).to_bytes() == raw


def test_clear_fills_free_records():
    db = make_db()
    p = db['players']
    p.clear()
    assert p.count == 0 and bytes(p.data) == b'\xdb' * 48
    p.append({'index': 9})
    assert p.rows() == [{'index': 9, 'team': -1, 'lastname': ''}]


def test_insert_and_delete_keep_order():
    db = make_db()
    p = db['players']  # 12-byte records, room for 4
    p.clear()
    p.append({'index': 1, 'lastname': 'A'})
    p.append({'index': 3, 'lastname': 'C'})
    assert p.insert(1, {'index': 2}, like=0) == 1
    assert [(r['index'], r['lastname']) for r in p.rows()] == [(1, 'A'), (2, 'A'), (3, 'C')]
    p.insert(3, {'index': 4})
    with pytest.raises(ValueError):
        p.insert(0)
    p.delete(0)
    assert [r['index'] for r in p.rows()] == [2, 3, 4] and bytes(p.data[36:48]) == b'\xdb' * 12
    with pytest.raises(IndexError):
        p.delete(3)
    raw = db.to_bytes()
    assert Database.parse(raw, SCHEMA).to_bytes() == raw


def test_sort_by_moves_whole_records():
    db = make_db()
    p = db['players']
    p.clear()
    for index, name in ((3, 'C'), (1, 'A'), (2, 'B'), (1, 'Z')):
        p.append({'index': index, 'lastname': name})
    recs = {p.get(i, 'lastname'): bytes(p.data[i * 12:(i + 1) * 12]) for i in range(4)}
    assert p.sort_by('index')
    assert [(r['index'], r['lastname']) for r in p.rows()] == [(1, 'A'), (1, 'Z'), (2, 'B'), (3, 'C')]
    assert [bytes(p.data[i * 12:(i + 1) * 12]) for i in range(4)] == [recs[k] for k in 'AZBC']
    assert not p.sort_by('index')
    raw = db.to_bytes()
    assert Database.parse(raw, SCHEMA).to_bytes() == raw


def test_index_definitions_kept():
    """League tables of Franchise saves: +0x1D = index count, definitions after the records (run x1-20261016)."""
    t = make_table('PLYR', [Field('indx', TYPE_INT, 0, 10, 'index')], 4, 2, 1, SCHEMA.tables['PLYR'])
    t._header[0x1D] = 1
    t._indexes = bytes.fromhex('70724365010100000000000200000001')
    t.set(0, 'index', 3)
    raw = Database([t]).to_bytes()
    t2 = Database.parse(raw, SCHEMA)['PLYR']
    assert t2._indexes == t._indexes and t2.get(0, 'index') == 3
    assert Database([t2]).to_bytes() == raw
    bad = bytearray(raw)
    tab = 0x18 + 8
    bad[tab + 0x1D] = 0  # an index tail without an index count is refused
    struct.pack_into('<I', bad, tab + 0x24, crc32_mpeg2(bytes(bad[tab + 4:tab + 0x24])))
    with pytest.raises(FormatError):
        Database.parse(bytes(bad), SCHEMA, verify=False)


def test_keep_and_put_back_restore_every_table():
    db = make_db()
    p = db['players']
    p.set(0, 'lastname', 'Kesler')
    raw = db.to_bytes()
    kept = db.keep()
    p.clear()
    p.append({'index': 9})
    db.add(make_table('XTRA', [Field('indx', TYPE_INT, 0, 8, 'index')], 4, 1, 0))
    assert 'XTRA' in db and len(db.tables) == 3
    with pytest.raises(ValueError):
        db.add(db['players'])
    db.put_back(kept)
    assert 'XTRA' not in db and db.to_bytes() == raw and db['players'].get(0, 'lastname') == 'Kesler'


def test_huffman_decode_a_byte_at_a_time_matches_bit_by_bit():
    """decode walks whole input bytes and cuts the padding's symbols off: the same strings as the bit walk."""
    import random
    rng = random.Random(19)
    for _ in range(30):
        counts = {b: rng.randint(1, 500) for b in rng.sample(range(256), rng.randint(2, 120))}
        tree = HuffmanTree.build(counts)
        syms = sorted(counts)
        for n in (0, 1, 2, 7, 8, 9, 63, 300):
            s = bytes(rng.choice(syms) for _ in range(n))
            area = b'\x5a' * 3 + tree.encode(s, 2) + bytes(rng.randrange(256) for _ in range(4))
            assert tree.decode(area, 3, 2) == tree.decode_bits(area, 3, 2) == s


def test_column_reads_what_get_reads():
    """Table.column (one pass, rosterupdate.State and lines.players_of) gives exactly get()'s values, for fields at
    any bit position and depth, with and without an offset (low)."""
    import random
    rnd = random.Random(3)
    for _ in range(200):
        size = rnd.randint(1, 64)
        fields, bit = [], 0
        while bit < size * 8:
            depth = rnd.randint(1, min(32, size * 8 - bit))
            fields.append(Field(f'f{len(fields)}', TYPE_INT, bit, depth, low=rnd.choice((0, -1, -50))))
            bit += depth
        n = rnd.randint(0, 120)
        head = bytearray(0x40)
        struct.pack_into('<I', head, 0x08, size)
        struct.pack_into('<HH', head, 0x14, n + 5, n)
        t = Table('t', bytes(head), fields, rnd.randbytes(size * (n + 5)))
        for f in fields:
            assert t.column(f.name) == [t.get(r, f.name) for r in range(n)]
