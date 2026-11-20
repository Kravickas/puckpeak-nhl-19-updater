"""GNF textures: tiling round trip, new textures shaped like a template, the game's own textures read back."""
import os
import random
import struct

import pytest

from overtime_core import eb, gamefiles, gnf


def template(w, h, fmt='BC1', num='UNORM', mips=1, pitch=None):
    """A GNF file like the game's (thin 1D tiling, data at 0x100) with random data."""
    words = [0] * 8
    words[1] = (gnf.DFMT[fmt] << 20) | (gnf.NFMT[num] << 26)
    words[2] = (w - 1) | ((h - 1) << 14)
    words[3] = ((mips - 1) << 16) | (gnf.TILE_THIN_1D << 20) | (9 << 28)
    words[4] = ((pitch or w) - 1) << 13
    t = gnf.Texture(words)
    size = sum(n for *_, n in gnf.mip_layout(t))
    words[7] = size
    head = bytearray(0x100)
    head[:4] = gnf.MAGIC
    struct.pack_into('<I', head, 4, 0xf8)
    head[8:12] = bytes((2, 1, 8, 0))
    struct.pack_into('<I', head, 12, 0x100 + size)
    struct.pack_into('<8I', head, 16, *words)
    rnd = random.Random(w * h + mips)
    return bytes(head) + bytes(rnd.getrandbits(8) for _ in range(size))


@pytest.mark.parametrize('w,h,fmt,mips,pitch', [(64, 64, 'BC1', 1, None), (200, 120, 'BC7', 1, 224),
                                                 (256, 256, 'BC3', 9, None), (48, 16, '8_8_8_8', 1, 64)])
def test_retile_detile_round_trip(w, h, fmt, mips, pitch):
    raw = template(w, h, fmt, mips=mips, pitch=pitch)
    g = gnf.Gnf(raw)
    t = g.texture
    assert (t.width, t.height, t.fmt, t.mips, t.tile) == (w, h, fmt, mips, 13)
    lin = gnf.detile(t, g.data())
    bpe, blk = gnf.FMT_BPE[fmt]
    assert len(lin[0]) == ((w + blk - 1) // blk) * ((h + blk - 1) // blk) * bpe
    if pitch is None and mips == 1:  # padding (pitch, small mips) is random here and not kept
        assert gnf.retile(t, lin) == g.data()
    again = gnf.from_mips(raw, lin)
    assert gnf.detile(gnf.Gnf(again).texture, gnf.Gnf(again).data()) == lin


def test_from_mips_checks_sizes():
    raw = template(64, 64, 'BC1', mips=2)
    with pytest.raises(gnf.GnfError):
        gnf.from_mips(raw, [b'\0' * 2048])
    with pytest.raises(gnf.GnfError):
        gnf.from_mips(raw, [b'\0' * 100, b'\0' * 512])


def test_make_keeps_a_bc7_template_bc7():
    pil = pytest.importorskip('PIL.Image')
    pytest.importorskip('numpy')
    raw = template(128, 128, 'BC7')
    img = pil.new('RGBA', (300, 300), (200, 30, 40, 255))
    out = gnf.make(raw, img)
    g = gnf.Gnf(out)
    assert g.texture.fmt == 'BC7' and g.texture.num == 'UNORM' and len(out) == len(raw)
    assert g.file_size == len(out)
    import numpy as np
    assert (np.asarray(gnf.to_image(out)) == (200, 30, 40, 255)).all()


def test_make_fits_the_small_mips_to_their_own_colour():
    """The 2 x 2 and 1 x 1 mips fill a quarter / a sixteenth of their block: the rest repeats the edge, not black."""
    pil = pytest.importorskip('PIL.Image')
    pytest.importorskip('numpy')
    img = pil.new('RGBA', (16, 16), (200, 120, 40, 255))
    img.paste((60, 180, 220, 255), (8, 0, 16, 16))          # the 2 x 2 mip: orange left, blue right
    out = gnf.make(template(16, 16, 'BC1', mips=5), img)
    mips = gnf._mips(img, [(16 >> lvl, 16 >> lvl) for lvl in range(5)])      # what each mip is before BC1
    two = gnf.to_image(out, 3)
    for x in (0, 1):     # orange left, blue right (black padding gave (131, 151, 131) on the left)
        assert max(abs(a - int(b)) for a, b in zip(two.getpixel((x, 0)), mips[3][0, x])) <= 4
    assert max(abs(a - int(b)) for a, b in zip(gnf.to_image(out, 4).getpixel((0, 0)), mips[4][0, 0])) <= 4


def test_make_keeps_mips_and_srgb():
    pil = pytest.importorskip('PIL.Image')
    raw = template(256, 256, 'BC1', 'SRGB', mips=9)
    out = gnf.make(raw, pil.new('RGB', (256, 256), (10, 120, 250)))
    t = gnf.Gnf(out).texture
    assert (t.fmt, t.num, t.mips, len(out)) == ('BC1', 'SRGB', 9, len(raw))
    assert gnf.to_image(out, level=8).size == (1, 1)


@pytest.mark.game
def test_game_textures_round_trip(game_dir):
    """A UI logo (BC7, 1 mip) and a 3D jersey colour map (BC1 sRGB, full mip chain) read back byte for byte."""
    want = {'nhl/ui/kettle_assets/teamlogos/large/t22.gnf',
            'nhl/data/kettle/rendering/characters/player/jersey_adidas_arizona_home_cm.gnf'}
    found = {}
    for big in gamefiles.archives(game_dir):
        with eb.EbArchive(big) as arc:
            for p in want & set(arc.entries):
                found[p] = arc.read(p)
    assert set(found) == want
    for raw in found.values():
        g = gnf.Gnf(raw)
        assert gnf.retile(g.texture, gnf.detile(g.texture, g.data())) == g.data()
        assert gnf.from_mips(raw, gnf.detile(g.texture, g.data())) == raw
    assert gnf.info(found['nhl/ui/kettle_assets/teamlogos/large/t22.gnf'])['format'] == 'BC7'
    cm = gnf.info(found['nhl/data/kettle/rendering/characters/player/jersey_adidas_arizona_home_cm.gnf'])
    assert (cm['format'], cm['num'], cm['width'], cm['mips']) == ('BC1', 'SRGB', 2048, 12)
    assert os.path.basename(game_dir)


def test_a_picture_at_the_templates_size_is_not_resampled():
    """gnf.make keeps a picture of the template's size as it is (NHL 27's 2048 jerseys on NHL 19's 2048 templates): 1 px
    black / white rows come back exact from BC1 (two colours a block). A picture of another size is scaled, and the
    same rows blur."""
    pil = pytest.importorskip('PIL.Image')
    np = pytest.importorskip('numpy')
    rows = np.zeros((64, 64, 3), np.uint8)
    rows[::2] = 255
    img = pil.fromarray(rows, 'RGB')
    out = np.asarray(gnf.to_image(gnf.make(template(64, 64, 'BC1'), img)).convert('RGB'))
    assert np.array_equal(out, rows)
    big = img.resize((100, 100), pil.Resampling.NEAREST)
    scaled = np.asarray(gnf.to_image(gnf.make(template(64, 64, 'BC1'), big)).convert('RGB'))
    assert not np.array_equal(scaled, rows)


@pytest.mark.parametrize('num', ['SRGB', 'UNORM'])
def test_mips_are_scaled_like_the_games_own(num):
    """gnf.MIP_FILTER (bicubic in the stored numbers, as NHL 19's own jerseys were mipped): a black / white checkerboard
    averages to 128 in sRGB and UNORM alike, and a picture's mips are its mip 0 scaled that way (before BCn)."""
    pil = pytest.importorskip('PIL.Image')
    np = pytest.importorskip('numpy')
    chk = (np.indices((64, 64)).sum(0) % 2 * 255).astype(np.uint8)
    img = pil.fromarray(np.stack([chk] * 3 + [np.full((64, 64), 255, np.uint8)], -1), 'RGBA')
    out = gnf.make(template(64, 64, 'BC1', num, mips=7), img)
    for level in (1, 6):
        assert all(abs(c - 128) <= 2 for c in gnf.to_image(out, level).getpixel((0, 0))[:3])
    pic = pil.fromarray(np.random.default_rng(2).integers(0, 256, (64, 64, 3), dtype=np.uint8), 'RGB')
    mips = gnf._mips(pic, [(64, 64), (32, 32), (16, 16)])
    for m in mips[1:]:
        want = np.stack([np.asarray(pil.fromarray(np.asarray(pic, np.float32)[..., c] / 255, 'F').resize(
            m.shape[1::-1], pil.Resampling.BICUBIC)) for c in range(3)], -1)
        assert np.abs(m.astype(float) - np.clip(np.rint(want * 255), 0, 255)).max() <= 1


def _loop_detile(data, ew, eh, bpe, pitch_e):
    out = bytearray(ew * eh * bpe)
    for s, d in gnf._pairs(ew, eh, pitch_e):
        out[d * bpe:d * bpe + bpe] = data[s * bpe:s * bpe + bpe]
    return bytes(out)


def _loop_retile(lin, ew, eh, bpe, pitch_e):
    out = bytearray(gnf._a(pitch_e or ew, 8) * gnf._a(eh, 8) * bpe)
    for d, s in gnf._pairs(ew, eh, pitch_e):
        out[d * bpe:d * bpe + bpe] = lin[s * bpe:s * bpe + bpe]
    return bytes(out)


@pytest.mark.parametrize('numpy', [True, False])
def test_tiling_fast_path_is_the_element_loop(numpy, monkeypatch):
    """Jersey speed: detile / retile gather whole elements in a cached order (numpy's gather, or array items where
    numpy is not installed); the bytes are the per-element loop's, for every element size, odd shapes, a padded pitch,
    and short data (which takes the loop itself)."""
    if numpy:
        pytest.importorskip('numpy')
    else:
        monkeypatch.setattr(gnf, '_numpy', lambda: None)
    rnd = random.Random(7)
    for bpe in (1, 2, 4, 8, 16, 3, 12):
        for _ in range(25):
            ew, eh = rnd.randint(1, 70), rnd.randint(1, 70)
            pitch = rnd.choice([None, ew, ew + rnd.randint(0, 20)])
            tiled = gnf._a(pitch or ew, 8) * gnf._a(eh, 8) * bpe
            for cut in (0, rnd.randint(1, 40)):
                data = rnd.randbytes(max(0, tiled - cut))
                assert gnf.detile_thin1d(data, ew, eh, bpe, pitch) == _loop_detile(data, ew, eh, bpe, pitch)
                lin = rnd.randbytes(max(0, ew * eh * bpe - cut))
                assert gnf.retile_thin1d(lin, ew, eh, bpe, pitch) == _loop_retile(lin, ew, eh, bpe, pitch)


def test_opaque_pictures_mip_the_same_without_their_alpha():
    """An opaque picture skips the alpha plane in _mips: its colours are the RGB picture's mips exactly (the alpha
    weighting and the division by a scaled alpha of exactly 1 change nothing), its alpha 255; one clear pixel takes
    the weighted path."""
    pil = pytest.importorskip('PIL.Image')
    np = pytest.importorskip('numpy')
    rgb = np.random.default_rng(5).integers(0, 256, (96, 160, 3), dtype=np.uint8)
    sizes = [(160 >> k, max(1, 96 >> k)) for k in range(8)]
    plain = gnf._mips(pil.fromarray(rgb, 'RGB'), sizes)
    opaque = gnf._mips(pil.fromarray(np.dstack([rgb, np.full((96, 160), 255, np.uint8)]), 'RGBA'), sizes)
    for a, b in zip(plain[1:], opaque[1:]):
        assert np.array_equal(a, b[..., :3]) and (b[..., 3] == 255).all()
    alpha = np.full((96, 160), 255, np.uint8)
    alpha[0, 0] = 0
    clear = gnf._mips(pil.fromarray(np.dstack([rgb, alpha]), 'RGBA'), sizes)
    assert clear[1][0, 0, 3] < 255


def test_scaled_template_is_k_times_larger():
    """gnf.scaled: a header for a texture k times the template's size (NHL 27's 2048 numbers on NHL 19's 1024 slot):
    width, height and pitch times k, a full mip chain one level longer per doubling, a partial chain kept, and
    gnf.make fills it at that size."""
    pil = pytest.importorskip('PIL.Image')
    big = gnf.scaled(template(64, 64, 'BC1', 'SRGB', mips=7), 2)
    t = gnf.Gnf(big).texture
    assert (t.width, t.height, t.pitch, t.mips, t.fmt, t.num, t.tile) == (128, 128, 128, 8, 'BC1', 'SRGB', 13)
    assert gnf.Gnf(big).file_size == len(big) and t.size == sum(n for *_, n in gnf.mip_layout(t))
    out = gnf.make(big, pil.new('RGB', (128, 128), (10, 120, 250)))
    assert gnf.to_image(out).size == (128, 128) and gnf.to_image(out, 7).size == (1, 1)
    odd = gnf.Gnf(gnf.scaled(template(200, 120, 'BC7', pitch=224), 4)).texture
    assert (odd.width, odd.height, odd.pitch, odd.mips) == (800, 480, 896, 1)
    with pytest.raises(gnf.GnfError):
        gnf.scaled(template(64, 64), 3)
