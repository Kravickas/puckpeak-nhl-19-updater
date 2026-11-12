"""The encoder's faster functions (2026-11-12) make byte for byte the textures the ones before them made: each is checked
against its earlier form, kept here word for word (overtime_core.bcn at 6eb651d), on random and adversarial inputs, and
whole textures are made both ways. Compared on this PC (the float32 products are the PC's own both times), so the test
never depends on which CPU runs it. A change to the encoder that alters a texture fails here: then it is a new encoder
(gnf.ENCODER), not a speed-up."""
import numpy as np
import pytest

from overtime_core import bcn


# --- the functions as they were (6eb651d) -------------------------------------------------------------------------
def nearest_before(x, pal, valid, xx=None):
    d = (pal * pal).sum(2)[:, None, :] - 2 * np.matmul(x, pal.transpose(0, 2, 1))
    idx = d.argmin(2)
    best = np.take_along_axis(d, idx[..., None], 2)[..., 0] + ((x * x).sum(2) if xx is None else xx)
    err = np.where(valid, np.maximum(best, 0), 0).sum(1)
    return idx, err


def weighted_before(weights):
    def palette(d0, d1):
        w = weights[None, :, None]
        e0, e1 = d0.astype(np.int32)[:, None, :], d1.astype(np.int32)[:, None, :]
        return (((64 - w) * e0 + w * e1 + 32) >> 6).astype(np.float32)
    return palette


def partition_guess_before(x):
    if x.shape[2] != 3:
        return bcn._partition_guess_any(x)
    n = len(x)
    x = (x - x.mean(1, keepdims=True)).astype(np.float32)
    m = bcn._SUB1.astype(np.float32)
    xx = (x[:, :, :, None] * x[:, :, None, :]).reshape(n, 16, 9)
    s1, q1, c1 = np.matmul(m, x), np.matmul(m, xx).reshape(n, 64, 3, 3), m.sum(1)
    s0, q0, c0 = x.sum(1)[:, None] - s1, xx.sum(1).reshape(n, 1, 3, 3) - q1, 16 - c1
    resid = 0
    for s, q, c in ((s0, q0, c0), (s1, q1, c1)):
        sc = q - (s[..., :, None] * s[..., None, :]) / c[None, :, None, None]
        a, b_, c_ = sc[..., 0, 0], sc[..., 1, 1], sc[..., 2, 2]
        d, e, f = sc[..., 0, 1], sc[..., 0, 2], sc[..., 1, 2]
        vx, vy, vz = np.ones_like(a), np.ones_like(a), np.ones_like(a)
        for _ in range(4):
            vx, vy, vz = a * vx + d * vy + e * vz, d * vx + b_ * vy + f * vz, e * vx + f * vy + c_ * vz
            norm = np.maximum(np.sqrt(vx * vx + vy * vy + vz * vz), 1e-12)
            vx, vy, vz = vx / norm, vy / norm, vz / norm
        top = (vx * (a * vx + d * vy + e * vz) + vy * (d * vx + b_ * vy + f * vz) + vz * (e * vx + f * vy + c_ * vz))
        resid = resid + a + b_ + c_ - top
    return np.argsort(resid, 1, kind='stable')[:, :bcn.TOP]


# --- inputs ----------------------------------------------------------------------------------------------------------
def values(rng, shape, kind):
    if kind == 0:
        return rng.integers(0, 256, shape).astype(np.float32)          # pixels
    if kind == 1:
        return (rng.random(shape) * 255).astype(np.float32)             # fractions
    if kind == 2:
        return rng.choice(np.array([0.0, -0.0, 1.0, 255.0, 127.5], np.float32), shape)   # ties and signed zeros
    if kind == 3:
        return (rng.standard_normal(shape) * 1e4).astype(np.float32)   # wide, negative
    return np.repeat(rng.integers(0, 256, shape[:-2] + (1, shape[-1])), shape[-2], -2).astype(np.float32)   # flat


def bits(a):
    return np.ascontiguousarray(a).view(np.uint32) if a.dtype == np.float32 else a


@pytest.mark.parametrize('seed', range(3))
def test_nearest_is_the_same_numbers_to_the_bit(seed):
    rng = np.random.default_rng(seed)
    for it in range(120):
        kind = it % 5
        n, palette, ch = int(rng.integers(1, 200)), int(rng.choice([4, 6, 8, 16])), int(rng.choice([1, 2, 3, 4]))
        x, pal = values(rng, (n, 16, ch), kind), values(rng, (n, palette, ch), (kind + it) % 5)
        if it % 7 == 0:
            pal[:, 1] = pal[:, 0]                                       # two equal entries: argmin's tie
        valid = rng.random((n, 16)) < 0.6 if it % 3 else rng.integers(0, 3, (n, 16))
        xx = None if it % 2 else (x * x).sum(2)
        (i0, e0), (i1, e1) = nearest_before(x, pal, valid, xx), bcn._nearest(x, pal, valid, xx)
        assert np.array_equal(i0, i1) and i0.dtype == i1.dtype
        assert e0.dtype == e1.dtype and np.array_equal(bits(e0), bits(e1))


def test_the_bc7_palettes_are_the_same_numbers_to_the_bit():
    rng = np.random.default_rng(5)
    for name in ('BC7_WEIGHTS', 'BC7_WEIGHTS3', 'BC7_WEIGHTS2'):
        w = getattr(bcn, name)
        for _ in range(50):
            n = int(rng.integers(1, 300))
            d0 = (rng.integers(0, 256, (n, 4)) + rng.choice([0, 0.5, 0.25], (n, 4))).astype(np.float32)
            d1 = rng.integers(0, 256, (n, 4)).astype(np.float32)
            a, b = weighted_before(w)(d0, d1), bcn._weighted(w)(d0, d1)
            assert a.dtype == b.dtype and np.array_equal(bits(a), bits(b))


@pytest.mark.parametrize('seed', range(3))
def test_the_partition_guess_is_the_same(seed):
    rng = np.random.default_rng(10 + seed)
    for it in range(120):
        kind = it % 5
        x = values(rng, (int(rng.integers(1, 300)), 16, 3), kind)
        if kind != 3:
            x = np.clip(x, 0, 255)
        assert np.array_equal(partition_guess_before(x), bcn._partition_guess(x))


def pictures():
    rng = np.random.default_rng(21)
    for size in (4, 12, 64, 132):
        h, w = size, size + 8
        yield rng.integers(0, 256, (h, w, 4), np.uint8)                               # noise
        g = np.zeros((h, w, 4), np.uint8)
        g[..., 0], g[..., 1] = np.linspace(0, 255, w)[None], np.linspace(255, 0, h)[:, None]
        g[..., 2], g[..., 3] = rng.integers(100, 110, (h, w)), 255
        yield g                                                                         # a gradient with grain
        a = g.copy()
        a[..., 3] = np.clip(np.arange(w)[None] * 5 - 60, 0, 255)
        a[h // 3:h // 2, :, 3] = 0
        yield a                                                                         # soft and hard alpha edges
        f = np.zeros((h, w, 4), np.uint8)
        f[:] = (7, 200, 199, 255)
        f[:h // 2, :w // 2] = 0
        yield f                                                                         # flat, clear corner


@pytest.mark.parametrize('fmt', ('BC1', 'BC3', 'BC5', 'BC7'))
def test_whole_textures_are_the_same_bytes(fmt, monkeypatch):
    now = [bcn.encode(fmt, px) for px in pictures()]
    monkeypatch.setattr(bcn, '_nearest', nearest_before)
    monkeypatch.setattr(bcn, '_weighted', weighted_before)
    monkeypatch.setattr(bcn, '_partition_guess', partition_guess_before)
    assert [bcn.encode(fmt, px) for px in pictures()] == now
