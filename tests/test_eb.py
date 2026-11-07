"""EB v3 writer: name hash, new archives, rebuild identity, entries replaced and added."""
import os

import pytest

from overtime_core import eb, gamefiles


def test_name_hash_is_djb2_64_of_lowercase_path():
    assert eb.name_hash('') == 5381
    assert eb.name_hash('a') == 5381 * 33 + ord('a')
    assert eb.name_hash('Nhl/UI/T22.gnf') == eb.name_hash('nhl/ui/t22.gnf')
    assert 0 <= eb.name_hash('x' * 200) < 1 << 64


def test_new_archive_reads_back_sorted_by_hash(tmp_path):
    files = {'nhl/ui/kettle_assets/teamlogos/large/t10499.gnf': b'logo' * 100,
             'nhl/ui/kettle_assets/teamlogos/medium/t10499.gnf': b'small',
             'nhl/data/kettle/rendering/x.gnf': b''}
    out = str(tmp_path / 'patch_inxp_57.big')
    sha = eb.new_archive(out, files)
    assert len(sha) == 64 and os.path.getsize(out) % 16 == 0
    with open(out, 'rb') as f:
        assert f.read() == eb.archive_bytes(files)
    with eb.EbArchive(out) as arc:
        assert {p: arc.read(p) for p in arc.entries} == files
    folders, entries = eb._parse(out)
    with open(out, 'rb') as f:
        head = f.read(0x30 + 20 * len(files))
    hashes = [int.from_bytes(head[0x30 + 20 * i + 12:0x30 + 20 * i + 20], 'big') for i in range(len(files))]
    assert hashes == sorted(eb.name_hash(p) for p in files)
    assert int.from_bytes(head[0x18:0x20], 'big') == os.path.getsize(out)


def test_rebuild_identity_and_changes(tmp_path):
    src = str(tmp_path / 'a.big')
    eb.new_archive(src, {'x/one.db': b'first', 'x/two.db': b'second!', 'y/three.db': b'3' * 33})
    same = str(tmp_path / 'same.big')
    eb.rebuild(src, same)
    assert open(same, 'rb').read() == open(src, 'rb').read() and eb.verify_rebuild(src) is None
    out = str(tmp_path / 'b.big')
    eb.rebuild(src, out, {'x/two.db': b'replaced and longer', 'z/new/four.gnf': b'new'})
    with eb.EbArchive(out) as arc:
        assert arc.read('x/one.db') == b'first' and arc.read('x/two.db') == b'replaced and longer'
        assert arc.read('y/three.db') == b'3' * 33 and arc.read('z/new/four.gnf') == b'new'
        assert len(arc.entries) == 4
    eb.add_entry(src, out, 'X/Five.gnf', b'5')
    with eb.EbArchive(out) as arc:
        assert arc.read('x/five.gnf') == b'5'
    with pytest.raises(ValueError):
        eb.rebuild(src, src)
    assert not os.path.exists(out + '.tmp')


@pytest.mark.game
def test_stock_patch_archives_rebuild_byte_identical(game_dir):
    small = [b for b in gamefiles.archives(game_dir)
             if os.path.basename(b) in ('patch_inxp_56.big', 'patch_game_96.big', 'boot.big')]
    assert len(small) == 3
    for big in small:
        assert eb.verify_rebuild(big) is None, big
        with eb.EbArchive(big) as arc:
            folders, entries = eb._parse(big)
            assert {e.path for e in entries} == set(arc.entries)


def test_cached_tocs_parse_each_archive_once_and_see_a_changed_one(tmp_path, monkeypatch):
    out = str(tmp_path / 'boot.big')
    eb.new_archive(out, {'a/x.bin': b'x'})
    parsed = []
    real = eb.EbArchive._parse
    monkeypatch.setattr(eb.EbArchive, '_parse', lambda self, h: (parsed.append(1), real(self, h))[1])
    with eb.cached_tocs():
        for _ in range(3):
            with eb.EbArchive(out) as arc:
                assert list(arc.entries) == ['a/x.bin']
        assert len(parsed) == 1
        eb.new_archive(out, {'a/x.bin': b'x', 'a/y.bin': b'y' * 40})      # another size: read again
        with eb.EbArchive(out) as arc:
            assert sorted(arc.entries) == ['a/x.bin', 'a/y.bin'] and arc.read('a/y.bin') == b'y' * 40
        assert len(parsed) == 2
    with eb.EbArchive(out) as arc:      # outside the block: parsed each time
        pass
    assert len(parsed) == 3
