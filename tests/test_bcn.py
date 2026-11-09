"""bcn, the BCn encoder of the textures made on the player's PC, checked against Pillow's decoder (the spec's)."""
import pytest

np = pytest.importorskip('numpy')
Image = pytest.importorskip('PIL.Image')

from overtime_core import bcn  # noqa: E402

N = {'BC1': 1, 'BC3': 3, 'BC5': 5, 'BC7': 7}


def picture(w=64, h=64, seed=1):
    """A deterministic test picture: gradients, stripes, a disc, noise; alpha a ramp with clear and opaque parts."""
    rnd = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    r = 128 + 100 * np.sin(x / 5) * np.cos(y / 7)
    g = 255 * x / w
    b = np.where((x - w / 2) ** 2 + (y - h / 2) ** 2 < (w / 4) ** 2, 230, 30)
    a = np.clip((x - w / 4) * 255 / (w / 2), 0, 255)
    px = np.stack([r, g, b, a], -1) + rnd.normal(0, 3, (h, w, 4)) * [1, 1, 1, 0]
    return np.clip(np.rint(px), 0, 255).astype(np.uint8)


def decode(fmt, data, w, h):
    return np.asarray(Image.frombytes('RGB' if fmt == 'BC5' else 'RGBA', (w, h), data, 'bcn', N[fmt]), np.float64)


def psnr(a, b):
    m = ((np.asarray(a, np.float64) - b) ** 2).mean()
    return 99.0 if m == 0 else 10 * np.log10(255 ** 2 / m)


@pytest.mark.parametrize('fmt,chans,floor', [('BC1', slice(0, 3), 33), ('BC3', slice(0, 4), 34),
                                             ('BC5', slice(0, 2), 43), ('BC7', slice(0, 4), 35)])
def test_decodes_close_to_the_picture_and_beats_pillow(fmt, chans, floor):
    px = picture()
    src = px[..., :3] if fmt == 'BC5' else px
    data = bcn.encode(fmt, src)
    assert len(data) == 16 * 16 * (8 if fmt == 'BC1' else 16)
    seen = src[..., 3] >= 128 if fmt == 'BC1' else np.ones(src.shape[:2], bool)   # BC1's clear pixels decode black
    ours = psnr(src[seen][..., chans], decode(fmt, data, 64, 64)[seen][..., chans])
    assert ours > floor
    if fmt != 'BC7':        # Pillow has no BC7 writer
        img = Image.fromarray(src, 'RGB' if fmt == 'BC5' else 'RGBA')
        theirs = psnr(src[seen][..., chans], decode(fmt, img.tobytes('bcn', N[fmt]), 64, 64)[seen][..., chans])
        assert ours > theirs + 1


def test_flat_and_two_level_blocks_are_exact():
    px = np.zeros((8, 8, 4), np.uint8)
    px[...] = (200, 30, 40, 255)
    px[4:, :, 3] = 128                       # BC3: alpha 255 over 128 (Pillow gave 230 / 153)
    out = decode('BC3', bcn.encode('BC3', px), 8, 8)
    assert (out[..., 3] == px[..., 3]).all()
    px[..., 3] = 255
    assert (decode('BC7', bcn.encode('BC7', px), 8, 8) == px).all()


def test_bc1_leaves_clear_pixels_clear():
    px = picture(16, 16)
    out = decode('BC1', bcn.encode('BC1', px), 16, 16)
    assert ((out[..., 3] == 0) == (px[..., 3] < 128)).all()
    assert set(np.unique(out[..., 3])) <= {0, 255}


def test_bc7_opaque_blocks_stay_opaque():
    px = picture()
    px[..., 3] = 255
    assert (decode('BC7', bcn.encode('BC7', px), 64, 64)[..., 3] == 255).all()


def test_bc7_partition_tables_match_the_decoder():
    """Each mode 1 partition and subset 1 anchor as Pillow's decoder reads them (see bcn.PARTITIONS2)."""
    def block(part, ends, idx_bits):
        fields = [(np.array([2]), 2), (np.array([part]), 6)]
        for c in range(3):
            fields += [(np.array([ends[e]]), 6) for e in range(4)]
        fields += [(np.array([0]), 1), (np.array([1]), 1)]
        fields.append(((np.array([idx_bits], np.int64)[:, None] >> np.arange(46)) & 1).astype(np.uint8))
        return bcn._bits(fields).tobytes()
    for part, (mask, anchor) in enumerate(zip(bcn.PARTITIONS2, bcn.ANCHOR2)):
        lit = decode('BC7', block(part, (0, 0, 63, 63), 0), 4, 4).reshape(16, 4)[:, 0] > 128
        assert sum(1 << i for i in range(16) if lit[i]) == mask
        ramp = decode('BC7', block(part, (0, 0, 0, 63), (1 << 46) - 1), 4, 4).reshape(16, 4)[:, 0]
        assert [i for i in range(16) if lit[i] and ramp[i] < 200] == [anchor]


def test_needs_whole_blocks_and_a_known_format():
    with pytest.raises(ValueError):
        bcn.encode('BC1', np.zeros((6, 8, 4), np.uint8))
    with pytest.raises(ValueError):
        bcn.encode('BC2', np.zeros((8, 8, 4), np.uint8))


def test_bc7_alpha_edges_keep_their_alpha_whatever_the_clear_pixels_hold():
    """The game's UI art: opaque logo pixels next to nearly clear ones of any colour (alpha 1, junk RGB)."""
    rnd = np.random.default_rng(3)
    px = np.zeros((16, 16, 4), np.uint8)
    px[..., :3] = rnd.integers(0, 256, (16, 16, 3))
    px[..., 3] = 1
    px[:, :7] = (140, 150, 185, 255)
    px[:, 7] = (120, 135, 180, 128)
    out = decode('BC7', bcn.encode('BC7', px), 16, 16)
    assert np.abs(out[..., 3] - px[..., 3]).max() <= 6
    assert np.abs(out[:, :7, :3] - px[:, :7, :3]).max() <= 6


def test_blocks_of_every_kind_decode_as_the_spec_says():
    """Flat, noise, two- and three-colour, gradients, opaque, cut-out and nearly clear blocks: a flat block comes back
    exact in BC7 and a two-colour one within one step, a wholly opaque block keeps alpha 255, BC1 leaves exactly the
    pixels under alpha 128 clear and keeps every other one opaque."""
    rng = np.random.default_rng(7)
    kinds = []
    for i in range(16 * 16):
        k = i % 8
        if k == 0:
            b = np.broadcast_to(rng.integers(0, 256, 4), (4, 4, 4))
        elif k == 1:
            b = rng.integers(0, 256, (4, 4, 4))
        elif k in (2, 3):
            b = rng.integers(0, 256, (k, 4))[rng.integers(0, k, (4, 4))]
        elif k == 4:
            a, z = rng.integers(0, 256, (2, 4))
            b = a + (z - a) * np.linspace(0, 1, 16).reshape(4, 4, 1)
        else:
            b = rng.integers(0, 256, (4, 4, 4))
            b[..., 3] = 255 if k == 5 else rng.choice([0, 255] if k == 6 else [0, 1, 254, 255], (4, 4))
        kinds.append((k, np.clip(np.rint(b), 0, 255).astype(np.uint8)))
    px = np.concatenate([np.concatenate([b for _k, b in kinds[r * 16:(r + 1) * 16]], 1) for r in range(16)], 0)
    kind = np.array([k for k, _b in kinds])
    src = bcn.blocks(px).astype(int)
    out = bcn.blocks(decode('BC7', bcn.encode('BC7', px), 64, 64).astype(np.uint8)).astype(int)
    assert (out[kind == 0] == src[kind == 0]).all()
    assert np.abs(out[kind == 2] - src[kind == 2]).max() <= 1     # BC7's ends: 7 or 8 bits, one step at most
    opaque = (src[..., 3] == 255).all(1)
    assert opaque.sum() >= 32 and (out[opaque][..., 3] == 255).all()
    one = decode('BC1', bcn.encode('BC1', px), 64, 64)
    assert ((one[..., 3] == 0) == (px[..., 3] < 128)).all() and set(np.unique(one[..., 3])) <= {0, 255}


def test_a_block_of_one_colour_gets_the_best_pair_there_is():
    """A one-colour block (most of a jersey) takes the table: its colour, decoded the encoder's way (c0, c1 and the
    thirds between them, in floats), is the nearest any 5:6:5 pair can give; brute force over every pair checks it."""
    rnd = np.random.default_rng(4)
    e5 = np.array([(c << 3) | (c >> 2) for c in range(32)], float)
    e6 = np.array([(c << 2) | (c >> 4) for c in range(64)], float)
    best = {5: np.add.outer(2 * e5, e5) / 3, 6: np.add.outer(2 * e6, e6) / 3}     # (a, b) -> 2/3 a + 1/3 b
    for colour in rnd.integers(0, 256, (60, 3)):
        px = np.zeros((4, 4, 4), np.uint8)
        px[..., :3], px[..., 3] = colour, 255
        a = np.frombuffer(bcn.encode('BC1', px), '<u8')[0]
        c0, c1, bits = int(a & 0xffff), int((a >> 16) & 0xffff), int(a >> 32)
        idx = {(bits >> (2 * i)) & 3 for i in range(16)}
        assert len(idx) == 1 and (c0 > c1 or (c0 == c1 and idx == {0}))
        ex = lambda c: np.array([e5[c >> 11], e6[(c >> 5) & 63], e5[c & 31]])      # noqa: E731
        got = [ex(c0), ex(c1), 2 / 3 * ex(c0) + 1 / 3 * ex(c1), 1 / 3 * ex(c0) + 2 / 3 * ex(c1)][idx.pop()]
        floor = sum(np.min((best[b] - v) ** 2) for b, v in zip((5, 6, 5), colour))
        assert ((got - colour) ** 2).sum() <= floor + 1e-6


def test_a_channel_of_one_value_is_exact_in_bc3_and_bc5():
    px = np.zeros((8, 8, 4), np.uint8)
    px[..., :3] = (10, 200, 77)
    px[..., 3] = 133
    assert (decode('BC3', bcn.encode('BC3', px), 8, 8)[..., 3] == 133).all()
    assert (decode('BC5', bcn.encode('BC5', px[..., :3]), 8, 8)[..., :2] == (10, 200)).all()
