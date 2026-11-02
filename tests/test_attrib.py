"""Attrib vault readers (overtime_core.attrib) on synthetic buffers, plus the real NHL 19 files when the scratch copies
exist (re/extract/vlt, gitignored; skipped otherwise)."""
import os
import struct

import pytest

from overtime_core import attrib


def _chunk(tag, body):
    size = 8 + len(body)
    pad = (-size) % 16
    return tag[::-1].encode('latin1') + struct.pack('<I', size + pad) + body + b'\0' * pad


def _synthetic_vlt():
    ver = _chunk('Vers', b'\0' * 8)
    dat = _chunk('DatN', b'\x11' * 64)
    exp = _chunk('ExpN', struct.pack('<I', 2) + struct.pack('<IIII', 0xAA, 0xBB, 80, 104)
                 + struct.pack('<IIII', 0xCC, 0xBB, 48, 184))
    ptr = _chunk('PtrN', struct.pack('<III', 0, 0x10002, 0) + struct.pack('<III', 16, 0x10003, 8))
    return ver + dat + exp + ptr + _chunk('EndC', b'')


def _synthetic_bin():
    strs = _chunk('StrE', b'ALPHA\0BETA\0')
    tofc_body = struct.pack('<I', 3) + b'\0' * 4 + struct.pack('<Q', 0x1122334455667788) \
        + struct.pack('<II', 0x33A6161C, 0x29E081B5) + struct.pack('<II', 0xED5E8A2C, 0x72756884)
    return strs + _chunk('TofC', tofc_body) + _chunk('EndC', b'') + b'RAWBLOB' * 4


def test_chunks_walk_tags_and_sizes():
    vlt = _synthetic_vlt()
    tags = [t for t, _, _ in attrib.chunks(vlt)]
    assert tags == ['Vers', 'DatN', 'ExpN', 'PtrN', 'EndC']
    off, size = attrib.chunk(vlt, 'ExpN')
    assert size == 48 and off % 16 == 0


def test_expn_and_ptrn_rows():
    vlt = _synthetic_vlt()
    assert attrib.expn(vlt) == [(0xAA, 0xBB, 80, 104), (0xCC, 0xBB, 48, 184)]
    rows = attrib.ptrn(vlt)
    assert rows[0] == (0, 0x10002, 0)
    assert rows[1] == (16, 0x10003, 8)


def test_bin_strings_and_tofc():
    binary = _synthetic_bin()
    assert attrib.strings(binary)[:2] == [b'ALPHA', b'BETA']
    head, pairs = attrib.tofc(binary)
    assert head == 0x1122334455667788
    assert pairs == [(0x33A6161C, 0x29E081B5), (0xED5E8A2C, 0x72756884)]


REAL = os.path.join(os.path.dirname(__file__), '..', 're', 'extract', 'vlt')


@pytest.mark.skipif(not os.path.exists(os.path.join(REAL, 'boot.big__gccollections.vlt')),
                    reason='scratch copy of the NHL 19 vault not extracted')
def test_real_vault_counts_match_notes():
    with open(os.path.join(REAL, 'boot.big__gccollections.vlt'), 'rb') as f:
        vlt = f.read()
    with open(os.path.join(REAL, 'boot.big__gccollections.bin'), 'rb') as f:
        binary = f.read()
    assert len(attrib.expn(vlt)) == 120779
    assert len(attrib.tofc(binary)[1]) == 120778
    assert len(attrib.ptrn(vlt)) == 744874


def test_lookup2_matches_eboot_names():
    # Pairs proven against gcschema.vlt ExpN keys (docs/notes/attrib-vlt.md).
    assert attrib.lookup2(b'ge_texture') == 0xed5e8a2c
    assert attrib.lookup2(b'ge_gameobject') == 0xea82c56b
    assert attrib.lookup2(b'Attrib::CollectionLoadData') == 0x8e112eb7
    assert attrib.lookup2(b'Attrib::Database') == 0xf1dfac8d


def test_texture_refs_read_pairs_after_tag():
    tex = struct.pack('<I', 0xED5E8A2C)
    rec = bytearray(216)
    rec[0x18:0x20] = tex + struct.pack('<I', 0x11111111)
    rec[0x38:0x40] = tex + struct.pack('<I', 0x22222222)
    assert attrib.texpack_texture_refs(bytes(rec), 0) == [0x11111111, 0x22222222]


@pytest.mark.skipif(not os.path.exists(os.path.join(REAL, 'boot.big__gccollections.vlt')),
                    reason='scratch copy of the NHL 19 vault not extracted')
def test_real_jersey_texpacks_match_findings():
    with open(os.path.join(REAL, 'boot.big__gccollections.vlt'), 'rb') as f:
        vlt = f.read()
    with open(os.path.join(REAL, 'boot.big__gccollections.bin'), 'rb') as f:
        binary = f.read()
    keys = attrib.class_keys(binary, 'ge_nhl_skaterjerseytexturepack')
    assert len(keys) == 1318
    offs = attrib.jersey_collection_offsets(vlt, binary)
    assert len(offs) == 1318
    spans = sorted(offs.values())
    assert all(b - a == attrib.COLLECTION_STRIDE for a, b in zip(spans, spans[1:]))
    recs = attrib.texpack_records(vlt, binary)
    assert len(recs) == 10828
    assert attrib.texpack_texture_refs(binary, recs['jersey_adidas_anaheim_two_texpack']) == [
        0x54261FCD, 0x72FD6378, 0x7FDA2A54, 0xE15FB2B2, 0x4B97F16E,
        0x0D326646, 0xA5C31E01, 0xA3FD3A11, 0x6BC9490B, 0x706D9325]
    assert attrib.texpack_texture_refs(binary, recs['jersey_adidas_toronto_three_texpack']) == [
        0x23F8AC0F, 0x1CF193AA, 0xD72E55D3, 0x0EB721A3, 0x4B97F16E,
        0x0D326646, 0x078550AC, 0x01442A32, 0x477D1079, 0xFD7A2BC0]


@pytest.mark.skipif(not os.path.exists(os.path.join(REAL, 'boot.big__gccollections.vlt')),
                    reason='scratch copy of the NHL 19 vault not extracted')
def test_real_jersey_records_have_export_rows_and_index_words():
    with open(os.path.join(REAL, 'boot.big__gccollections.vlt'), 'rb') as f:
        vlt = f.read()
    with open(os.path.join(REAL, 'boot.big__gccollections.bin'), 'rb') as f:
        binary = f.read()
    offs = attrib.jersey_collection_offsets(vlt, binary)
    found = attrib.expn_rows_at(vlt, offs.values())
    assert len(found) == 1317
    assert all(r[1] == attrib.ATTRIB_LOAD_CLASS and r[2] == 92 for r in found.values())
    recs = attrib.texpack_records(vlt, binary)
    assert attrib.texpack_index_word(binary, recs['jersey_adidas_anaheim_two_texpack']) == 2
    assert attrib.texpack_index_word(binary, recs['jersey_adidas_toronto_three_texpack']) == 3
    assert attrib.texpack_index_word(binary, recs['jersey_adidas_anaheim_home_texpack']) == 0
