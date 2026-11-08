"""BCn block compression of pictures for the textures made on the player's PC (gnf.make): BC1, BC3, BC5 and BC7.

Pillow's own BCn writer (libImaging/BcnEncode.c, the same in 12.1.1 and 13.0) takes a block's colour ends as the
smallest and largest 5:6:5 numbers (red first, so green and blue barely count), cuts them down instead of rounding,
picks each pixel's step from per-channel distances, never gives BC3 alpha its own ends (a block's lowest and highest
alpha come out a fifth of the way in) and has no BC7, so the BC7 art of the game came out as BC3. Here:

- colour (BC1, the colour half of BC3): the ends on the block's main axis (principal component), rounded to 5:6:5, each
  pixel the nearest of the 4 colours the block decodes to, the ends fitted again by least squares on those choices
  (twice), the best kept. BC1 blocks with a pixel under alpha 128 use the 3-colour + clear mode.
- alpha (BC3) and the two channels of BC5: both modes tried (8 steps, and 6 steps + 0 + 255), ends fitted the same
  way, each pixel the nearest step, the better mode kept.
- BC7, three modes, the lowest decoded error kept per block:
  - mode 6 (one subset, RGBA 7.7.7.7 ends with a p-bit each, 16 steps) on the block's RGBA axis, every p-bit pair
    tried; a block that is wholly opaque keeps both p-bits 1, so its alpha decodes to exactly 255;
  - opaque blocks: mode 1 (two subsets of RGB 6.6.6 + a shared p-bit, 8 steps), on the TOP partitions whose subsets
    lie closest to a line each;
  - blocks with alpha: mode 5 (RGB 7.7.7 and alpha 8 with their own ends and 2-bit steps), every rotation, so an alpha
    edge keeps its alpha whatever colour its clear pixels hold; and mode 7 (two subsets of RGBA 5.5.5.5 + a p-bit per
    end), so a soft edge's clear and opaque pixels get a subset each.
  Modes 1, 5 and 7 are tried only where mode 6 leaves an error above GOOD.
- Ends that round to the same code are also tried as the two codes either side of them (_rounded): a flat colour no
  code holds lands on a step between them.
- Then the ends kept are searched one code step at a time (_search, SEARCH passes; BC7 modes 6 and 1: SEARCH7): what
  rounding the fitted ends leaves (on a real 1024 jersey 40.9 -> 41.8 dB, most of it on flat fabric).
- A texture made on its own splits its blocks over the cores (workers.shared); on a pool's thread it does not.

Every choice is checked against the colours the block decodes to (BC7: the spec's integer weights), so what is kept is
what the GPU shows. Input: an (H, W, C) uint8 array, H and W multiples of 4; output: the blocks row by row (what
gnf.retile takes). numpy is imported by gnf's picture functions only: the server imports overtime_core and stays stdlib.
"""
import numpy as np

from . import workers

CHUNK = 4096                    # blocks per pass: bounds the memory of each texture (the jerseys run on every core)
ROUNDS = 2                      # least-squares refits after the first choice of ends
SEARCH7 = 0                     # BC7 modes 6 and 1: the search gains 0.1 dB there for 60 % more time
SEARCH_MIN = 0                  # the summed squared error a block needs for the search to try it
SEARCH = 1                      # passes of the one-code-step search over the kept ends (0: none)

# weight of end 0 for each index
_W4 = np.array([1, 0, 2 / 3, 1 / 3], np.float32)                     # BC1 4-colour
_W3 = np.array([1, 0, 1 / 2], np.float32)                            # BC1 3-colour (index 3: clear)
_W8 = np.array([1, 0] + [(8 - k) / 7 for k in range(2, 8)], np.float32)   # alpha a0 > a1
_W6 = np.array([1, 0] + [(6 - k) / 5 for k in range(2, 6)], np.float32)   # alpha a0 <= a1 (6: 0, 7: 255)
BC7_WEIGHTS = np.array([0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64], np.int32)
_W16 = ((64 - BC7_WEIGHTS) / 64).astype(np.float32)


def blocks(px):
    """(H, W, C) -> (H/4 * W/4, 16, C): the 4 x 4 blocks row by row, each block's pixels row by row."""
    h, w, c = px.shape
    if h % 4 or w % 4:
        raise ValueError(f'{w} x {h} is not whole 4 x 4 blocks')
    return px.reshape(h // 4, 4, w // 4, 4, c).transpose(0, 2, 1, 3, 4).reshape(-1, 16, c)


def encode(fmt, px):
    """The BCn blocks of `px` ((H, W, C) uint8: RGBA for BC1 / BC3 / BC7, R and G read for BC5) as bytes."""
    enc = {'BC1': _bc1, 'BC3': _bc3, 'BC5': _bc5, 'BC7': _bc7}.get(fmt)
    if enc is None:
        raise ValueError(f'cannot encode {fmt}')
    b = blocks(np.ascontiguousarray(px, np.uint8))

    def one(i):
        part = enc(b[i:i + CHUNK].astype(np.float32))
        return (part.astype('<u8') if part.dtype == np.uint64 else part).tobytes()
    starts = range(0, len(b), CHUNK)
    if len(starts) > 1 and not workers.in_worker() and workers.count() > 1:
        # a texture made on its own: its chunks on every core (on a pool's thread, the pool already uses them)
        return b''.join(workers.shared().map(one, starts))
    return b''.join(one(i) for i in starts)


# --- shared --------------------------------------------------------------------------------------------------------

def _axis_ends(x, valid):
    """The ends of each block's pixels along their principal axis: (e0, e1), e0 at the high end."""
    w = valid[..., None].astype(np.float32)
    n = np.maximum(w.sum(1), 1)
    mean = (x * w).sum(1) / n
    d = (x - mean[:, None]) * w
    cov = np.einsum('nki,nkj->nij', d, d)
    v = cov[np.arange(len(x)), np.argmax(np.einsum('nii->ni', cov), 1)]     # the row of the widest channel
    for _ in range(8):
        v = np.einsum('nij,nj->ni', cov, v)
        v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)
    flat = np.linalg.norm(v, axis=1) < 0.5
    v[flat] = 1 / np.sqrt(x.shape[2])
    t = np.einsum('nki,ni->nk', x - mean[:, None], v)
    hi = np.where(valid, t, -np.inf).max(1)
    lo = np.where(valid, t, np.inf).min(1)
    hi, lo = np.where(np.isfinite(hi), hi, 0), np.where(np.isfinite(lo), lo, 0)
    return mean + hi[:, None] * v, mean + lo[:, None] * v


def _nearest(x, pal, valid):
    """Each pixel's nearest palette entry and each block's summed squared error over its valid pixels."""
    # |x - p|^2 = |x|^2 - 2 x.p + |p|^2: one batched matrix product instead of every difference
    d = (pal * pal).sum(2)[:, None, :] - 2 * np.matmul(x, pal.transpose(0, 2, 1))
    idx = d.argmin(2)
    best = np.take_along_axis(d, idx[..., None], 2)[..., 0] + (x * x).sum(2)
    err = np.where(valid, np.maximum(best, 0), 0).sum(1)
    return idx, err


def _rounded(v0, v1, top, fixed=None):
    """Two ways to put float ends (in steps of the stored code) on codes 0..top: each rounded; and, where both round
    to the same code and their middle is not on a code, the two codes on either side of it instead, so the steps between
    them (a third, a seventh, a 64th) can land on a colour no code holds (a flat block of 200 with 7-bit + p-bit ends:
    199 and 201).
    -> [(q0, q1, rows)]: rows, the blocks a way is for (None: all; the second way only where it differs). `fixed`
    (n, C): channels left out of the second way (an opaque block's alpha)."""
    q0 = np.clip(np.rint(v0), 0, top).astype(np.int32)
    q1 = np.clip(np.rint(v1), 0, top).astype(np.int32)
    out = [(q0, q1, None)]
    mid = (v0 + v1) / 2
    # only a channel between two codes: one a code holds stays on it (the index is shared by every channel, so a
    # channel spread for nothing would lose the colour it had exactly)
    same = (q0 == q1) & (np.abs(mid - np.rint(mid)) > 0.25)
    if fixed is not None:
        same &= ~fixed
    rows = same.any(1)
    if rows.any():
        lo = np.clip(np.floor(mid), 0, top - 1).astype(np.int32)
        out.append((np.where(same, lo, q0), np.where(same, lo + 1, q1), rows))
    return out


def _least_squares(x, valid, w0, e0, e1):
    """The ends minimising sum |w0 * e0 + (1 - w0) * e1 - x|^2 over the valid pixels (w0: each pixel's weight of end 0);
    blocks whose system is singular keep e0, e1."""
    w0 = np.where(valid, w0, 0)
    w1 = np.where(valid, 1 - w0, 0)
    a, b, c = (w0 * w0).sum(1), (w0 * w1).sum(1), (w1 * w1).sum(1)
    sx, sy = np.einsum('nk,nkc->nc', w0, x), np.einsum('nk,nkc->nc', w1, x)
    det = a * c - b * b
    ok = det > 1e-6
    det = np.where(ok, det, 1)[:, None]
    n0 = (c[:, None] * sx - b[:, None] * sy) / det
    n1 = (a[:, None] * sy - b[:, None] * sx) / det
    return np.where(ok[:, None], n0, e0), np.where(ok[:, None], n1, e1)


def _fit(x, valid, weights, candidates, palette, lsq_valid=None, rounds=None, decode=None, top=None, frozen=None,
         search=None):
    """Ends and indices of each block: the principal axis' ends, then ROUNDS least-squares refits, each tried as every
    candidate quantisation (candidates(e0, e1) -> [(code, decoded e0, decoded e1, allowed or None, rows or None)]);
    the lowest decoded error kept. With `decode(code) -> (decoded e0, decoded e1)` and `top` (each channel's highest
    code), the kept ends are then searched one code step at a time (_search); `frozen` (n, C): channels not moved.
    -> (code, idx, err)."""
    rounds = ROUNDS if rounds is None else rounds
    e0, e1 = _axis_ends(x, valid)
    best = None
    for r in range(rounds + 1):
        for code, d0, d1, allowed, rows in candidates(e0, e1):
            if rows is None:
                idx, err = _nearest(x, palette(d0, d1), valid)
            else:                                   # tried on those blocks only
                idx, err = np.zeros(x.shape[:2], np.int64), np.full(len(x), np.inf, np.float32)
                idx[rows], err[rows] = _nearest(x[rows], palette(d0[rows], d1[rows]), valid[rows])
            if allowed is not None:
                err = np.where(allowed, err, np.inf)
            if best is None:
                best = [code, idx, err]
                continue
            better = err < best[2]
            best[0] = {k: np.where(better.reshape((-1,) + (1,) * (v.ndim - 1)), v, best[0][k]) for k, v in code.items()}
            best[1] = np.where(better[:, None], idx, best[1])
            best[2] = np.where(better, err, best[2])
        if r < rounds:
            ok = valid if lsq_valid is None else valid & lsq_valid(best[1])
            e0, e1 = _least_squares(x, ok, weights[np.minimum(best[1], len(weights) - 1)], e0, e1)
    search = SEARCH if search is None else search
    if decode is not None and search:
        best = _search(x, valid, palette, best, decode, top, frozen, search)
    return best


def _search(x, valid, palette, best, decode, top, frozen, passes):
    """`passes` passes over every end channel, one code up and one down, each move kept where it lowers the decoded
    error: what rounding the fitted ends leaves on the table (the fit is in floats, the block decodes from codes)."""
    code, idx, err = best
    rows = np.flatnonzero(err > SEARCH_MIN)         # a block that decodes (nearly) exactly has little to gain
    if not len(rows):
        return best
    sub = {k: v[rows] for k, v in code.items()}
    i_s, e_s, x_s, v_s = idx[rows], err[rows], x[rows], valid[rows]
    f_s = None if frozen is None else frozen[rows]
    top = np.broadcast_to(np.asarray(top), (sub['q0'].shape[1],))
    for _ in range(passes):
        moved = np.zeros(len(rows), bool)
        for key in ('q0', 'q1'):
            for c in range(sub[key].shape[1]):
                if f_s is not None and f_s[:, c].all():
                    continue
                for step in (-1, 1):
                    q = sub[key].copy()
                    q[:, c] = np.clip(q[:, c] + step, 0, top[c])
                    trial = dict(sub)
                    trial[key] = q
                    i, e = _nearest(x_s, palette(*decode(trial)), v_s)
                    better = e < e_s
                    if f_s is not None:
                        better &= ~f_s[:, c]
                    if not better.any():
                        continue
                    sub = {k: np.where(better.reshape((-1,) + (1,) * (v.ndim - 1)), trial[k], v)
                           for k, v in sub.items()}
                    i_s = np.where(better[:, None], i, i_s)
                    e_s = np.where(better, e, e_s)
                    moved |= better
        if not moved.any():
            break
    code = {k: v.copy() for k, v in code.items()}
    for k in code:
        code[k][rows] = sub[k]
    idx, err = idx.copy(), err.copy()
    idx[rows], err[rows] = i_s, e_s
    return [code, idx, err]


# --- BC1 colour ------------------------------------------------------------------------------------------------------

_SCALE565 = np.array([31, 63, 31], np.float32) / 255


def _expand565(q):
    r, g, b = q[..., 0], q[..., 1], q[..., 2]
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1).astype(np.float32)


_TOP565 = np.array([31, 63, 31], np.int32)


def _candidates565(e0, e1):
    return [({'q0': q0, 'q1': q1}, _expand565(q0), _expand565(q1), None, rows)
            for q0, q1, rows in _rounded(e0 * _SCALE565, e1 * _SCALE565, _TOP565)]


def _palette(weights):
    w = weights[None, :, None]
    return lambda d0, d1: w * d0[:, None, :] + (1 - w) * d1[:, None, :]


def _pack565(q):
    return (q[..., 0] << 11) | (q[..., 1] << 5) | q[..., 2]


def _color(rgb, clear=None):
    """BC1 colour halves ((n,) uint64) of rgb (n, 16, 3); `clear` (n, 16): pixels to leave clear (3-colour mode)."""
    n = len(rgb)
    out_c0, out_c1 = np.zeros(n, np.uint32), np.zeros(n, np.uint32)
    out_idx = np.zeros((n, 16), np.int64)
    punch = np.zeros(n, bool) if clear is None else clear.any(1)
    for three, sel in ((False, ~punch), (True, punch)):
        if not sel.any():
            continue
        x = rgb[sel]
        valid = np.ones(x.shape[:2], bool) if not three else ~clear[sel]
        w = _W3 if three else _W4
        code, idx, _err = _fit(x, valid, w, _candidates565, _palette(w),
                               decode=lambda k: (_expand565(k['q0']), _expand565(k['q1'])), top=_TOP565)
        c0, c1 = _pack565(code['q0']).astype(np.uint32), _pack565(code['q1']).astype(np.uint32)
        if three:       # 3-colour mode wants c0 <= c1
            swap = c0 > c1
            idx = np.where(swap[:, None], np.array([1, 0, 2])[idx], idx)
            idx = np.where(valid, idx, 3)
        else:           # 4-colour mode wants c0 > c1; equal ends: every pixel is that colour
            swap = c0 < c1
            idx = np.where(swap[:, None], np.array([1, 0, 3, 2])[idx], idx)
            idx = np.where((c0 == c1)[:, None], 0, idx)
        c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
        if three:
            none = ~valid.any(1)            # all clear
            c0, c1 = np.where(none, 0, c0), np.where(none, 0, c1)
        out_c0[sel], out_c1[sel], out_idx[sel] = c0, c1, idx
    bits = (out_idx.astype(np.uint64) << (2 * np.arange(16, dtype=np.uint64))).sum(1, dtype=np.uint64)
    return out_c0.astype(np.uint64) | (out_c1.astype(np.uint64) << np.uint64(16)) | (bits << np.uint64(32))


# --- alpha / one channel ----------------------------------------------------------------------------------------------

def _candidates_byte(e0, e1):
    q0 = np.clip(np.rint(e0), 0, 255).astype(np.int32)
    q1 = np.clip(np.rint(e1), 0, 255).astype(np.int32)
    return [({'q0': q0, 'q1': q1}, q0.astype(np.float32), q1.astype(np.float32), None, None)]


def _palette6(d0, d1):
    w = _W6[None, :, None]
    inner = w * d0[:, None, :] + (1 - w) * d1[:, None, :]
    ends = np.broadcast_to(np.array([0, 255], np.float32)[None, :, None], (len(d0), 2, 1))
    return np.concatenate([inner, ends], 1)


def _bytes(code):
    return code['q0'].astype(np.float32), code['q1'].astype(np.float32)


def _channel(v):
    """BC4-style blocks ((n,) uint64) of one channel v (n, 16): the better of the 8-step and the 6-step mode."""
    x = v[..., None]
    valid = np.ones(v.shape, bool)
    c8, i8, e8 = _fit(x, valid, _W8, _candidates_byte, _palette(_W8), decode=_bytes, top=255)
    a0, a1 = c8['q0'][:, 0], c8['q1'][:, 0]
    swap = a0 < a1                                  # 8-step mode wants a0 > a1
    i8 = np.where(swap[:, None], np.array([1, 0, 7, 6, 5, 4, 3, 2])[i8], i8)
    a0, a1 = np.where(swap, a1, a0), np.where(swap, a0, a1)
    i8 = np.where((a0 == a1)[:, None], 0, i8)       # equal ends decode as the 6-step mode: index 0 is still a0
    # 6-step mode: the ends over the pixels 0 and 255 do not take
    inner = (v > 0) & (v < 255)
    c6, i6, e6 = _fit(x, inner | ~inner.any(1, keepdims=True), _W6, _candidates_byte, _palette6,
                      lsq_valid=lambda idx: idx < 6, decode=_bytes, top=255)
    i6, e6 = _nearest(x, _palette6(c6['q0'].astype(np.float32), c6['q1'].astype(np.float32)), valid)
    b0, b1 = c6['q0'][:, 0], c6['q1'][:, 0]
    swap = b0 > b1                                  # 6-step mode wants a0 <= a1
    i6 = np.where(swap[:, None], np.array([1, 0, 5, 4, 3, 2, 6, 7])[i6], i6)
    b0, b1 = np.where(swap, b1, b0), np.where(swap, b0, b1)
    six = e6 < e8
    a0, a1, idx = np.where(six, b0, a0), np.where(six, b1, a1), np.where(six[:, None], i6, i8)
    bits = (idx.astype(np.uint64) << (3 * np.arange(16, dtype=np.uint64))).sum(1, dtype=np.uint64)
    return a0.astype(np.uint64) | (a1.astype(np.uint64) << np.uint64(8)) | (bits << np.uint64(16))


# --- formats ----------------------------------------------------------------------------------------------------------

def _bc1(b):
    clear = b[..., 3] < 128 if b.shape[2] > 3 else None
    return _color(b[..., :3], clear)


def _bc3(b):
    alpha = _channel(b[..., 3]) if b.shape[2] > 3 else np.full(len(b), 0xffff, np.uint64)   # a0 = a1 = 255
    return np.stack([alpha, _color(b[..., :3])], 1)


def _bc5(b):
    return np.stack([_channel(b[..., 0]), _channel(b[..., 1])], 1)


# BC7 modes 1 and 7: the pixels of subset 1 in each of the 64 two-subset partitions (bit i: pixel i) and subset 1's
# anchor pixel (subset 0's is pixel 0). Read off two decoders (Pillow's and texture2ddecoder's, which agree): a block
# with subset 0 black and subset 1 white shows the partition, one with every index bit set shows the anchor (its index
# is 2 bits).
PARTITIONS2 = (
    0xcccc, 0x8888, 0xeeee, 0xecc8, 0xc880, 0xfeec, 0xfec8, 0xec80, 0xc800, 0xffec, 0xfe80, 0xe800, 0xffe8, 0xff00,
    0xfff0, 0xf000, 0xf710, 0x008e, 0x7100, 0x08ce, 0x008c, 0x7310, 0x3100, 0x8cce, 0x088c, 0x3110, 0x6666, 0x366c,
    0x17e8, 0x0ff0, 0x718e, 0x399c, 0xaaaa, 0xf0f0, 0x5a5a, 0x33cc, 0x3c3c, 0x55aa, 0x9696, 0xa55a, 0x73ce, 0x13c8,
    0x324c, 0x3bdc, 0x6996, 0xc33c, 0x9966, 0x0660, 0x0272, 0x04e4, 0x4e40, 0x2720, 0xc936, 0x936c, 0x39c6, 0x639c,
    0x9336, 0x9cc6, 0x817e, 0xe718, 0xccf0, 0x0fcc, 0x7744, 0xee22)
ANCHOR2 = (
    15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 2, 8, 2, 2, 8, 8, 15, 2, 8, 2, 2, 8, 8, 2, 2,
    15, 15, 6, 8, 2, 8, 15, 15, 2, 8, 2, 2, 2, 15, 15, 6, 6, 2, 6, 8, 15, 15, 2, 2, 15, 15, 15, 15, 15, 2, 2, 15)
_SUB1 = np.array([[(m >> i) & 1 for i in range(16)] for m in PARTITIONS2], bool)
_ANCHOR2 = np.array(ANCHOR2)
BC7_WEIGHTS3 = np.array([0, 9, 18, 27, 37, 46, 55, 64], np.int32)
_W8_7 = ((64 - BC7_WEIGHTS3) / 64).astype(np.float32)
TOP = 2                         # modes 1, 7: partitions per block fitted in full (the best guesses: line residual)
ROUNDS1 = 1                     # mode 1's least-squares refits
GOOD = 16                       # mode 1 is tried on the opaque blocks mode 6 leaves a summed squared error above this


def _bits(fields):
    """Bit fields [(values (n,), width) or bits (n, k) of 0 / 1] LSB first into (n, 16) bytes."""
    cols = []
    for f in fields:
        if isinstance(f, tuple):
            v, w = f
            cols.append((np.asarray(v, np.int64)[:, None] >> np.arange(w)) & 1)
        else:
            cols.append(f)
    bits = np.concatenate(cols, 1).astype(np.uint8)
    assert bits.shape[1] == 128, bits.shape
    return np.packbits(bits, axis=1, bitorder='little')


def _weighted(weights):
    def palette(d0, d1):
        """The colours a BC7 subset decodes to (spec: ((64 - w) * e0 + w * e1 + 32) >> 6)."""
        w = weights[None, :, None]
        e0, e1 = d0.astype(np.int32)[:, None, :], d1.astype(np.int32)[:, None, :]
        return (((64 - w) * e0 + w * e1 + 32) >> 6).astype(np.float32)
    return palette


def _candidates6(opaque):
    """Mode 6 ends: 7 bits a channel and a p-bit per end ((q << 1) | p), every p-bit pair; opaque blocks only 1, 1 with
    alpha 127 (255)."""
    fixed = np.zeros((len(opaque), 4), bool)
    fixed[:, 3] = opaque

    def make(e0, e1):
        out = []
        for p0 in (0, 1):
            for p1 in (0, 1):
                for q0, q1, rows in _rounded((e0 - p0) / 2, (e1 - p1) / 2, 127, fixed):
                    if p0 and p1:
                        q0[opaque, 3] = q1[opaque, 3] = 127
                    code = {'q0': q0, 'q1': q1, 'p0': np.full(len(e0), p0, np.int32),
                            'p1': np.full(len(e0), p1, np.int32)}
                    allowed = None if (p0 and p1) else ~opaque
                    out.append((code, (q0 * 2 + p0).astype(np.float32), (q1 * 2 + p1).astype(np.float32), allowed,
                                rows))
        return out
    return make


def _expand7(c7):
    return ((c7 << 1) | (c7 >> 6)).astype(np.float32)


def _candidates1(e0, e1):
    """Mode 1 ends of one subset: 6 bits a channel and the subset's one p-bit (7 bits, widened to 8), both p-bits."""
    out = []
    for p in (0, 1):
        for q0, q1, rows in _rounded((e0 * 127 / 255 - p) / 2, (e1 * 127 / 255 - p) / 2, 63):
            code = {'q0': q0, 'q1': q1, 'p': np.full(len(e0), p, np.int32)}
            out.append((code, _expand7(q0 * 2 + p), _expand7(q1 * 2 + p), None, rows))
    return out


def _mode6(b, opaque):
    """(error, (n, 16) bytes) of mode 6 on RGBA blocks."""
    frozen = np.zeros((len(b), 4), bool)
    frozen[:, 3] = opaque                           # an opaque block's alpha stays 255
    code, idx, err = _fit(b, np.ones(b.shape[:2], bool), _W16, _candidates6(opaque), _weighted(BC7_WEIGHTS),
                          decode=lambda k: ((k['q0'] * 2 + k['p0'][:, None]).astype(np.float32),
                                            (k['q1'] * 2 + k['p1'][:, None]).astype(np.float32)),
                          top=127, frozen=frozen, search=SEARCH7)
    q0, q1, p0, p1 = code['q0'], code['q1'], code['p0'], code['p1']
    swap = idx[:, 0] >= 8                           # the first pixel's index has no top bit: its MSB must be 0
    idx = np.where(swap[:, None], 15 - idx, idx)
    q0, q1 = np.where(swap[:, None], q1, q0), np.where(swap[:, None], q0, q1)
    p0, p1 = np.where(swap, p1, p0), np.where(swap, p0, p1)
    fields = [(np.full(len(b), 1 << 6), 7)]         # mode 6: six 0 bits, then 1
    for c in range(4):                              # R0 R1 G0 G1 B0 B1 A0 A1
        fields += [(q0[:, c], 7), (q1[:, c], 7)]
    fields += [(p0, 1), (p1, 1), (idx[:, 0], 3)] + [(idx[:, i], 4) for i in range(1, 16)]
    return err, _bits(fields)


def _partition_guess(x):
    """(n, TOP) partitions whose two subsets lie closest to a line each (the scatter left off each one's main axis)."""
    if x.shape[2] != 3:
        return _partition_guess_any(x)
    n = len(x)
    x = (x - x.mean(1, keepdims=True)).astype(np.float32)   # centred: float32 keeps the scatter's precision
    m = _SUB1.astype(np.float32)
    xx = (x[:, :, :, None] * x[:, :, None, :]).reshape(n, 16, 9)
    s1, q1, c1 = np.matmul(m, x), np.matmul(m, xx).reshape(n, 64, 3, 3), m.sum(1)
    s0, q0, c0 = x.sum(1)[:, None] - s1, xx.sum(1).reshape(n, 1, 3, 3) - q1, 16 - c1
    resid = 0
    for s, q, c in ((s0, q0, c0), (s1, q1, c1)):
        sc = q - (s[..., :, None] * s[..., None, :]) / c[None, :, None, None]
        a, b_, c_ = sc[..., 0, 0], sc[..., 1, 1], sc[..., 2, 2]         # the 6 numbers of each 3 x 3 scatter
        d, e, f = sc[..., 0, 1], sc[..., 0, 2], sc[..., 1, 2]
        vx, vy, vz = np.ones_like(a), np.ones_like(a), np.ones_like(a)  # its main axis by power iteration
        for _ in range(4):
            vx, vy, vz = a * vx + d * vy + e * vz, d * vx + b_ * vy + f * vz, e * vx + f * vy + c_ * vz
            norm = np.maximum(np.sqrt(vx * vx + vy * vy + vz * vz), 1e-12)
            vx, vy, vz = vx / norm, vy / norm, vz / norm
        top = (vx * (a * vx + d * vy + e * vz) + vy * (d * vx + b_ * vy + f * vz) + vz * (e * vx + f * vy + c_ * vz))
        resid = resid + a + b_ + c_ - top
    return np.argsort(resid, 1, kind='stable')[:, :TOP]


def _partition_guess_any(x):
    """_partition_guess for any channel count (mode 7's RGBA)."""
    n, _k, ch = x.shape
    x = (x - x.mean(1, keepdims=True)).astype(np.float32)
    m = _SUB1.astype(np.float32)
    xx = (x[:, :, :, None] * x[:, :, None, :]).reshape(n, 16, ch * ch)
    s1, q1, c1 = np.matmul(m, x), np.matmul(m, xx).reshape(n, 64, ch, ch), m.sum(1)
    s0, q0, c0 = x.sum(1)[:, None] - s1, xx.sum(1).reshape(n, 1, ch, ch) - q1, 16 - c1
    resid = 0
    for s, q, c in ((s0, q0, c0), (s1, q1, c1)):
        sc = q - (s[..., :, None] * s[..., None, :]) / c[None, :, None, None]
        v = np.ones(sc.shape[:3], np.float32)
        for _ in range(4):
            v = np.matmul(sc, v[..., None])[..., 0]
            v /= np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)
        top = (v * np.matmul(sc, v[..., None])[..., 0]).sum(-1)
        resid = resid + np.einsum('npii->np', sc) - top
    return np.argsort(resid, 1, kind='stable')[:, :TOP]


def _decode1(code):
    p = code['p'][:, None]
    return _expand7(code['q0'] * 2 + p), _expand7(code['q1'] * 2 + p)


def _mode1(x):
    """(error, (n, 16) bytes) of mode 1 (two subsets of RGB, alpha 255) on opaque blocks x (n, 16, 3)."""
    n = len(x)
    guess = _partition_guess(x)
    best = None
    pal = _weighted(BC7_WEIGHTS3)
    for k in range(guess.shape[1]):
        part = guess[:, k]
        sub1 = _SUB1[part]
        c0, i0, e0 = _fit(x, ~sub1, _W8_7, _candidates1, pal, rounds=ROUNDS1, decode=_decode1, top=63, search=SEARCH7)
        c1, i1, e1 = _fit(x, sub1, _W8_7, _candidates1, pal, rounds=ROUNDS1, decode=_decode1, top=63, search=SEARCH7)
        err = e0 + e1
        cand = {'part': part, 'sub1': sub1, 'idx': np.where(sub1, i1, i0),
                'q': np.stack([c0['q0'], c0['q1'], c1['q0'], c1['q1']], 1), 'p': np.stack([c0['p'], c1['p']], 1)}
        if best is None:
            best, best_err = cand, err
            continue
        better = err < best_err
        best = {key: np.where(better.reshape((-1,) + (1,) * (v.ndim - 1)), v, best[key]) for key, v in cand.items()}
        best_err = np.where(better, err, best_err)
    part, sub1, idx, q, p = best['part'], best['sub1'], best['idx'], best['q'], best['p']
    rows = np.arange(n)
    anchor = _ANCHOR2[part]
    for s, at in ((0, np.zeros(n, int)), (1, anchor)):  # an anchor's index has no top bit: its MSB must be 0
        flip = idx[rows, at] >= 4
        mine = (sub1 if s else ~sub1) & flip[:, None]
        idx = np.where(mine, 7 - idx, idx)
        e0, e1 = q[:, 2 * s].copy(), q[:, 2 * s + 1].copy()
        q[:, 2 * s] = np.where(flip[:, None], e1, e0)
        q[:, 2 * s + 1] = np.where(flip[:, None], e0, e1)
    fields = [(np.full(n, 2), 2), (part, 6)]        # mode 1: 0, then 1
    for c in range(3):                              # R0 R1 R2 R3 G0 .. B3
        fields += [(q[:, e, c], 6) for e in range(4)]
    fields += [(p[:, 0], 1), (p[:, 1], 1)]
    ibits = (idx[:, :, None] >> np.arange(3)) & 1   # (n, 16, 3); the anchors lose their top bit
    keep = np.ones((n, 16, 3), bool)
    keep[:, 0, 2] = False
    keep[rows, anchor, 2] = False
    fields.append(ibits[keep].reshape(n, 46))
    return best_err, _bits(fields)


BC7_WEIGHTS2 = np.array([0, 21, 43, 64], np.int32)
_W4_7 = ((64 - BC7_WEIGHTS2) / 64).astype(np.float32)


def _candidates7bit(e0, e1):
    """Mode 5 colour ends: 7 bits a channel, widened to 8."""
    return [({'q0': q0, 'q1': q1}, _expand7(q0), _expand7(q1), None, rows)
            for q0, q1, rows in _rounded(e0 * 127 / 255, e1 * 127 / 255, 127)]


def _candidates8bit(e0, e1):
    return [({'q0': q0, 'q1': q1}, q0.astype(np.float32), q1.astype(np.float32), None, rows)
            for q0, q1, rows in _rounded(e0, e1, 255)]


ROTATIONS = ((0, 1, 2, 3), (3, 1, 2, 0), (0, 3, 2, 1), (0, 1, 3, 2))    # mode 5's channel order per rotation 0..3


def _mode5(b):
    """(error, (n, 16) bytes) of mode 5 on RGBA blocks: three channels and the fourth (alpha, or with a rotation R, G
    or B, alpha taking its place) each with their own ends and 2-bit indices, so an alpha edge keeps its alpha whatever
    colour its clear pixels hold. Every rotation tried, the lowest error kept."""
    best = None
    for rot, order in enumerate(ROTATIONS):
        err, fields = _mode5_rotated(b[..., list(order)], rot)
        if best is None:
            best_err, best = err, fields
            continue
        better = err < best_err
        best = [np.where(better.reshape((-1,) + (1,) * (f.ndim - 1)), f, g) for f, g in zip(fields, best)]
        best_err = np.where(better, err, best_err)
    return best_err, _bits([(f, w) for f, w in zip(best, _MODE5_WIDTHS)])


_MODE5_WIDTHS = [6, 2] + [7] * 6 + [8, 8, 1] + [2] * 15 + [1] + [2] * 15


def _mode5_rotated(b, rot):
    n = len(b)
    valid = np.ones(b.shape[:2], bool)
    pal = _weighted(BC7_WEIGHTS2)
    cc, ci, ce = _fit(b[..., :3], valid, _W4_7, _candidates7bit, pal,
                      decode=lambda k: (_expand7(k['q0']), _expand7(k['q1'])), top=127)
    ac, ai, ae = _fit(b[..., 3:], valid, _W4_7, _candidates8bit, pal, decode=_bytes, top=255)
    q0, q1, a0, a1 = cc['q0'], cc['q1'], ac['q0'][:, 0], ac['q1'][:, 0]
    swap = ci[:, 0] >= 2                            # each first index has no top bit: its MSB must be 0
    ci = np.where(swap[:, None], 3 - ci, ci)
    q0, q1 = np.where(swap[:, None], q1, q0), np.where(swap[:, None], q0, q1)
    swap = ai[:, 0] >= 2
    ai = np.where(swap[:, None], 3 - ai, ai)
    a0, a1 = np.where(swap, a1, a0), np.where(swap, a0, a1)
    fields = [np.full(n, 1 << 5), np.full(n, rot)]  # mode 5: five 0 bits, then 1; the rotation
    for c in range(3):                              # R0 R1 G0 G1 B0 B1, then A0 A1 (the channels as rotated)
        fields += [q0[:, c], q1[:, c]]
    fields += [a0, a1] + [ci[:, i] for i in range(16)] + [ai[:, i] for i in range(16)]
    return ce + ae, fields


def _expand6(c6):
    return ((c6 << 2) | (c6 >> 4)).astype(np.float32)


def _candidates7(e0, e1):
    """Mode 7 ends of one subset: RGBA 5 bits a channel and a p-bit per end (6 bits, widened to 8), every p-bit pair."""
    out = []
    for p0 in (0, 1):
        for p1 in (0, 1):
            for q0, q1, rows in _rounded((e0 * 63 / 255 - p0) / 2, (e1 * 63 / 255 - p1) / 2, 31):
                code = {'q0': q0, 'q1': q1, 'p0': np.full(len(e0), p0, np.int32), 'p1': np.full(len(e0), p1, np.int32)}
                out.append((code, _expand6(q0 * 2 + p0), _expand6(q1 * 2 + p1), None, rows))
    return out


def _mode7(b):
    """(error, (n, 16) bytes) of mode 7 (two subsets of RGBA, 2-bit indices) on blocks with alpha: a soft edge's
    clear pixels and its opaque ones get a subset each."""
    n = len(b)
    guess = _partition_guess(b)
    pal = _weighted(BC7_WEIGHTS2)
    best = None
    for k in range(guess.shape[1]):
        part = guess[:, k]
        sub1 = _SUB1[part]
        c0, i0, e0 = _fit(b, ~sub1, _W4_7, _candidates7, pal, rounds=ROUNDS1)
        c1, i1, e1 = _fit(b, sub1, _W4_7, _candidates7, pal, rounds=ROUNDS1)
        err = e0 + e1
        cand = {'part': part, 'sub1': sub1, 'idx': np.where(sub1, i1, i0),
                'q': np.stack([c0['q0'], c0['q1'], c1['q0'], c1['q1']], 1),
                'p': np.stack([c0['p0'], c0['p1'], c1['p0'], c1['p1']], 1)}
        if best is None:
            best, best_err = cand, err
            continue
        better = err < best_err
        best = {key: np.where(better.reshape((-1,) + (1,) * (v.ndim - 1)), v, best[key]) for key, v in cand.items()}
        best_err = np.where(better, err, best_err)
    part, sub1, idx, q, p = best['part'], best['sub1'], best['idx'], best['q'], best['p']
    rows = np.arange(n)
    anchor = _ANCHOR2[part]
    for s, at in ((0, np.zeros(n, int)), (1, anchor)):  # an anchor's index has no top bit: its MSB must be 0
        flip = idx[rows, at] >= 2
        mine = (sub1 if s else ~sub1) & flip[:, None]
        idx = np.where(mine, 3 - idx, idx)
        e0, e1 = q[:, 2 * s].copy(), q[:, 2 * s + 1].copy()
        q[:, 2 * s] = np.where(flip[:, None], e1, e0)
        q[:, 2 * s + 1] = np.where(flip[:, None], e0, e1)
        p0, p1 = p[:, 2 * s].copy(), p[:, 2 * s + 1].copy()   # each end keeps its own p-bit
        p[:, 2 * s], p[:, 2 * s + 1] = np.where(flip, p1, p0), np.where(flip, p0, p1)
    fields = [(np.full(n, 1 << 7), 8), (part, 6)]   # mode 7: seven 0 bits, then 1
    for c in range(4):                              # R0 R1 R2 R3 G0 .. A3
        fields += [(q[:, e, c], 5) for e in range(4)]
    fields += [(p[:, e], 1) for e in range(4)]
    ibits = (idx[:, :, None] >> np.arange(2)) & 1   # (n, 16, 2); the anchors lose their top bit
    keep = np.ones((n, 16, 2), bool)
    keep[:, 0, 1] = False
    keep[rows, anchor, 1] = False
    fields.append(ibits[keep].reshape(n, 30))
    return best_err, _bits(fields)


def _bc7(b):
    """BC7: mode 6 for every block, then mode 1 for the opaque ones and modes 5 and 7 for the others; the lowest
    decoded error kept."""
    if b.shape[2] == 3:
        b = np.concatenate([b, np.full(b.shape[:2] + (1,), 255, np.float32)], 2)
    opaque = (b[..., 3] == 255).all(1)
    err, out = _mode6(b, opaque)
    for mode, which in ((_mode1, opaque), (_mode5, ~opaque), (_mode7, ~opaque)):
        rows = np.flatnonzero(which & (err > GOOD))
        if len(rows):
            e, o = mode(b[rows][..., :3] if mode is _mode1 else b[rows])
            pick = e < err[rows]
            out[rows[pick]] = o[pick]
            err[rows[pick]] = e[pick]
    return out
