import os
import shutil
import struct

import pytest

from overtime_core import eb, gamefiles, textpack


def make_eb(path, files):
    """Minimal EB v3 archive: `files` = [(folder, name, data)], one folder table, 16-byte aligned data."""
    folders = sorted({f for f, _, _ in files})
    fnl, dnl = max(32, (max(len(n) for _, n, _ in files) + 2 + 15) // 16 * 16), 64   # a name field fits its longest name
    names = b''.join(struct.pack('>H', folders.index(f)) + n.encode().ljust(fnl - 2, b'\0') for f, n, _ in files)
    names = names.ljust((len(names) + 15) // 16 * 16, b'\0') + b''.join(f.encode().ljust(dnl, b'\0') for f in folders)
    names_off = (0x30 + 20 * len(files) + 15) // 16 * 16
    pos = (names_off + len(names) + 15) // 16 * 16
    table, blobs = b'', b''
    for _, _, data in files:
        table += struct.pack('>IIIQ', pos // 16, 0, len(data), 0)
        blob = data.ljust((len(data) + 15) // 16 * 16, b'\0')
        blobs += blob
        pos += len(blob)
    head = b'EB' + struct.pack('>HIIIIBBHII', 3, len(files), 0, names_off, len(names), fnl, dnl, len(folders), 0, pos)
    body = head.ljust(0x30, b'\0') + table
    body = body.ljust(names_off, b'\0') + names
    body = body.ljust((len(body) + 15) // 16 * 16, b'\0') + blobs
    with open(path, 'wb') as f:
        f.write(body)
    return body


def test_append_and_restore_entry(tmp_path):
    p = str(tmp_path / 'a.big')
    original = make_eb(p, [('x/y', 'one.db', b'first'), ('x/y', 'two.db', b'second!')])
    rec = eb.append_entry(p, 'x/y/one.db', b'replaced and longer')
    with eb.EbArchive(p) as arc:
        assert arc.read('x/y/one.db') == b'replaced and longer'
        assert arc.read('x/y/two.db') == b'second!'
    size = os.path.getsize(p)
    with open(p, 'rb') as f:
        assert struct.unpack_from('>I', f.read(0x30), 0x1c)[0] == size and size % 16 == 0
    eb.restore_entry(p, rec)
    with open(p, 'rb') as f:
        assert f.read() == original


def test_append_refuses_mismatched_header(tmp_path):
    p = str(tmp_path / 'a.big')
    make_eb(p, [('d', 'f', b'abc')])
    with open(p, 'ab') as f:
        f.write(b'\0' * 16)
    with pytest.raises(ValueError):
        eb.append_entry(p, 'd/f', b'x')


def test_pack_strings_fit_their_field():
    pack = textpack.load_pack()
    for sid, text in pack['strings'].items():
        assert len(text.encode('utf-8')) <= 32000 // 8, sid


@pytest.mark.game
def test_apply_and_undo_on_a_copy(game_dir, tmp_path):
    db_path, _ = textpack.loc_paths('eng_us')
    src = textpack._winner(game_dir, db_path)
    game = tmp_path / 'game'
    (game / 'databigs').mkdir(parents=True)
    copy = str(game / 'databigs' / os.path.basename(src))
    shutil.copyfile(src, copy)
    meta_path = textpack.loc_paths('eng_us')[1]
    folder, name = meta_path.rsplit('/', 1)
    make_eb(str(game / 'databigs' / 'inxp_00.big'), [(folder, name, gamefiles.read_latest(game_dir, meta_path)[0])])
    if os.path.exists(src + textpack.STATE_SUFFIX):  # an old in-place edit: the overlay starts from the original
        shutil.copyfile(src + textpack.STATE_SUFFIX, copy + textpack.STATE_SUFFIX)
    before = open(copy, 'rb').read()
    pack = textpack.load_pack()
    idle = {'running': lambda: False}  # the overlay is never written while shadPS4 runs
    out = textpack.apply(str(game), pack, **idle)
    assert out['overlay'] == str(tmp_path / 'game-mods' / 'databigs' / os.path.basename(src))
    size = os.path.getsize(out['overlay'])
    textpack.apply(str(game), pack, **idle)
    assert os.path.getsize(out['overlay']) == size
    assert open(copy, 'rb').read() == before  # the game folder is never written
    st = textpack.status(str(game), pack)
    assert st['applied'] and st['not_current'] == []
    in_place = os.path.exists(copy + textpack.STATE_SUFFIX)
    textpack.undo(str(game), **idle)
    assert not os.path.exists(out['overlay'])
    assert in_place or textpack.status(str(game), pack)['not_current']


def _loc_game(root, names, bigs=None):
    """A game folder whose inxp_00.big holds the loc files `names` (b'' each); `bigs` adds {archive: [(folder, name,
    data)]}."""
    (root / 'databigs').mkdir(parents=True)
    make_eb(str(root / 'databigs' / 'inxp_00.big'),
            [(textpack.LOC_DIR.rstrip('/'), n, b'x') for n in names] or [('nhl', 'readme.txt', b'x')])
    for big, files in (bigs or {}).items():
        make_eb(str(root / 'databigs' / big), files)
    return str(root)


def test_the_text_file_is_eng_us_else_another_english_else_none(tmp_path):
    """CUSA11116, 2026-11-03: the patch read eng_us whatever the game had ("eng_us-meta.xml not in ...")."""
    assert textpack.game_language(_loc_game(tmp_path / 'a', ['ger_de.db', 'eng_gb.db', 'eng_us.db'])) == 'eng_us'
    assert textpack.game_language(_loc_game(tmp_path / 'b', ['ger_de.db', 'eng_gb.db', 'eng_gb-meta.xml'])) == 'eng_gb'
    assert textpack.game_language(_loc_game(tmp_path / 'c', ['ger_de.db', 'fre_fr.db'])) is None
    assert textpack.load_pack(lang='eng_gb') == textpack.load_pack()     # the English pack serves every English
    with pytest.raises(FileNotFoundError):
        textpack.load_pack(lang='ger_de')


def test_a_text_file_without_its_own_meta_reads_with_another(tmp_path):
    """The update holds every language's text file, the base only its own metas: the table is the same in each."""
    loc = textpack.LOC_DIR.rstrip('/')
    game = _loc_game(tmp_path / 'g', ['eng_us.db'], {'boot.big': [(loc, 'ger_de-meta.xml', b'<de/>')]})
    assert textpack.loc_meta(game, 'eng_us') == b'<de/>'
    with pytest.raises(FileNotFoundError):
        textpack.loc_meta(_loc_game(tmp_path / 'h', ['eng_us.db']), 'eng_us')


@pytest.mark.game
def test_another_english_and_a_borrowed_meta_take_the_text_layers(game_dir, tmp_path):
    """The real loc files under another English name (eng_gb), and eng_us with only German's meta: both layers fit and
    apply; a pack with a string the file lacks does not fit."""
    from overtime_core import overlay
    loc = textpack.LOC_DIR.rstrip('/')
    db_path, meta_path = textpack.loc_paths('eng_us')
    raw = gamefiles.read_latest(game_dir, db_path)[0]
    meta = gamefiles.read_latest(game_dir, meta_path)[0]
    gb = tmp_path / 'gb'
    _loc_game(gb, [], {'patch_inxp_56.big': [(loc, 'eng_gb.db', raw)],
                       'boot.big': [(loc, 'eng_gb-meta.xml', meta.replace(b'"eng_us"', b'"eng_gb"'))]})
    assert textpack.game_language(str(gb)) == 'eng_gb'
    assert overlay.layer_fits(str(gb), 'text', 'eng_gb') and overlay.layer_fits(str(gb), 'names', 'eng_gb')
    state = overlay.apply(str(gb), ['text', 'names'], lang='eng_gb', running=lambda: False)
    assert state['layers']['text']['file'] == state['layers']['names']['file'] == 'eng_gb'
    with eb.EbArchive(os.path.join(overlay.overlay_dir(str(gb)), 'databigs', 'patch_inxp_56.big')) as arc:
        pack = textpack.load_pack()
        got = textpack.read_strings(arc.read('nhl/data/kettle/loc/eng_gb.db'), meta, pack['strings'])
    assert got == pack['strings']
    overlay.undo(str(gb), running=lambda: False)
    de = tmp_path / 'de'
    de_meta = gamefiles.read_latest(game_dir, textpack.loc_paths('ger_de')[1])[0]
    _loc_game(de, [], {'patch_inxp_56.big': [(loc, 'eng_us.db', raw)], 'boot.big': [(loc, 'ger_de-meta.xml', de_meta)]})
    assert textpack.game_language(str(de)) == 'eng_us' and overlay.layer_fits(str(de), 'text', 'eng_us')
    bad = dict(textpack.load_pack(), strings={'NOT_A_STRING_OF_NHL_19': 'x'})
    import unittest.mock
    with unittest.mock.patch.object(textpack, 'load_pack', lambda *a, **kw: bad):
        assert not overlay.layer_fits(str(gb), 'text', 'eng_gb')
