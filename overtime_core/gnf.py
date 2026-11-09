"""PS4 GNF textures of NHL 19 (CUSA11126 v1.60): header, GCN tiling (detile / retile), new textures shaped like a
stock one. Header and tiling are stdlib; making BCn data from a picture uses Pillow (resizing) and bcn (numpy: the
blocks), decoding to a picture Pillow; both are imported inside those functions only. Facts: docs/notes/gnf-format.md.

GNF (little-endian): "GNF " | u32 contents size (0xf8: data at 8 + that = 0x100) | u8 version 2 | u8 texture count |
u8 log2 alignment | u8 0 | u32 file size | count x sce::Gnm::Texture (8 dwords, GCN T# image resource; dword 7 holds
the texture's data size in GNF files) | zero padding | data.

T# fields (AMD Sea Islands SQ_IMG_RSRC_WORD0-7, as in shadPS4 video_core/amdgpu/resource.h):
  w1 [25:20] data format, [29:26] number format; w2 [13:0] width-1, [27:14] height-1;
  w3 [2:0..11:9] dst_sel xyzw, [15:12] base level, [19:16] last level, [24:20] tiling index, [25] pow2pad, [31:28] type;
  w4 [12:0] depth-1, [26:13] pitch-1; w5 [12:0] base array, [25:13] last array.

Every GNF of the game uses tiling index 13 (thin 1D): 8x8-element micro tiles (an element is a 4x4 BCn block or one
pixel), row by row across the padded pitch, the 64 elements of a tile in Morton order (x0 y0 x1 y1 x2 y2). Mips follow
each other, largest first, each whole micro tiles. A texture made from a template keeps its format: bcn writes BC1, BC3,
BC5 and BC7 (the UI art), Pillow's own BCn writer is not used (bcn's docstring says why).
"""
import functools
import struct
from array import array

MAGIC = b'GNF '
DATA_FORMATS = {1: '8', 2: '16', 3: '8_8', 4: '32', 5: '16_16', 10: '8_8_8_8', 12: '16_16_16_16', 14: '32_32_32_32',
                16: '5_6_5', 35: 'BC1', 36: 'BC2', 37: 'BC3', 38: 'BC4', 39: 'BC5', 40: 'BC6', 41: 'BC7'}
DFMT = {v: k for k, v in DATA_FORMATS.items()}
NUM_FORMATS = {0: 'UNORM', 1: 'SNORM', 4: 'UINT', 5: 'SINT', 7: 'FLOAT', 9: 'SRGB'}
NFMT = {v: k for k, v in NUM_FORMATS.items()}
TILE_THIN_1D = 13
# bytes per element and element size in pixels (BCn elements are 4x4 blocks)
FMT_BPE = {'BC1': (8, 4), 'BC4': (8, 4), 'BC2': (16, 4), 'BC3': (16, 4), 'BC5': (16, 4), 'BC6': (16, 4), 'BC7': (16, 4),
           '8_8_8_8': (4, 1), '8': (1, 1), '8_8': (2, 1), '16': (2, 1), '32': (4, 1), '5_6_5': (2, 1),
           '16_16_16_16': (8, 1)}
BCN = {'BC1': 1, 'BC2': 2, 'BC3': 3, 'BC4': 4, 'BC5': 5, 'BC6': 6, 'BC7': 7}
ENCODABLE = ('BC1', 'BC3', 'BC5', 'BC7')  # what bcn writes
ENCODER = '6'   # in the keys of the textures made on the player's PC: a new one makes them again (1: Pillow's)


class GnfError(ValueError):
    pass


def _bits(v, lo, n):
    return (v >> lo) & ((1 << n) - 1)


class Texture:
    """One T# (8 dwords) and the fields this module uses."""

    def __init__(self, words):
        w = self.w = tuple(words)
        self.dfmt = _bits(w[1], 20, 6)
        self.nfmt = _bits(w[1], 26, 4)
        self.width = _bits(w[2], 0, 14) + 1
        self.height = _bits(w[2], 14, 14) + 1
        self.base_level, self.last_level = _bits(w[3], 12, 4), _bits(w[3], 16, 4)
        self.tile = _bits(w[3], 20, 5)
        self.pow2pad = _bits(w[3], 25, 1)
        self.type = _bits(w[3], 28, 4)
        self.pitch = _bits(w[4], 13, 14) + 1
        self.size = w[7]

    @property
    def fmt(self):
        return DATA_FORMATS.get(self.dfmt, f'fmt{self.dfmt}')

    @property
    def num(self):
        return NUM_FORMATS.get(self.nfmt, f'num{self.nfmt}')

    @property
    def mips(self):
        return self.last_level - self.base_level + 1

    def with_format(self, fmt=None, num=None):
        """The same T# with another data and / or number format."""
        w = list(self.w)
        if fmt is not None:
            w[1] = (w[1] & ~(0x3f << 20)) | (DFMT[fmt] << 20)
        if num is not None:
            w[1] = (w[1] & ~(0xf << 26)) | (NFMT[num] << 26)
        return Texture(w)

    def describe(self):
        return (f'{self.width}x{self.height} pitch {self.pitch} {self.fmt}/{self.num} mips {self.mips} '
                f'tile {self.tile} size {self.size}')


class Gnf:
    def __init__(self, data):
        if data[:4] != MAGIC:
            raise GnfError('not a GNF file')
        self.raw = bytes(data)
        self.contents, = struct.unpack_from('<I', data, 4)
        self.version, self.count, self.align = data[8], data[9], data[10]
        self.file_size, = struct.unpack_from('<I', data, 12)
        self.data_off = 8 + self.contents
        self.textures = [Texture(struct.unpack_from('<8I', data, 16 + 32 * i)) for i in range(self.count)]

    @property
    def texture(self):
        return self.textures[0]

    def data(self):
        t = self.texture
        return self.raw[self.data_off:self.data_off + t.size]


def info(data):
    """{width, height, format, num, mips, size} of a GNF file's first texture."""
    t = Gnf(data).texture
    return {'width': t.width, 'height': t.height, 'format': t.fmt, 'num': t.num, 'mips': t.mips, 'size': t.size}


# --- tiling ---------------------------------------------------------------------------------------------------------

def _morton8():
    out = []
    for i in range(64):
        x = (i & 1) | ((i >> 1) & 2) | ((i >> 2) & 4)
        y = ((i >> 1) & 1) | ((i >> 2) & 2) | ((i >> 3) & 4)
        out.append((x, y))
    return tuple(out)


MORTON8 = _morton8()


def _a(n, m):
    return (n + m - 1) // m * m


def _pairs(ew, eh, pitch_e):
    """(tiled element index, linear element index) of every element inside ew x eh."""
    tiles_x = _a(pitch_e or ew, 8) // 8
    out = []
    for ty in range(_a(eh, 8) // 8):
        for tx in range(tiles_x):
            base = (ty * tiles_x + tx) * 64
            for i, (x, y) in enumerate(MORTON8):
                px, py = tx * 8 + x, ty * 8 + y
                if px < ew and py < eh:
                    out.append((base + i, py * ew + px))
    return out


# the copy unit of the fast path: an element moves as `n` array items of `code` (bytes per element: (code, n))
_UNITS = {1: ('B', 1), 2: ('H', 1), 4: ('I', 1), 8: ('Q', 1), 16: ('Q', 2)}


@functools.lru_cache(maxsize=64)
def _order(ew, eh, pitch_e, n, retile):
    """The item gather order of the fast path, made once per mip shape (a jersey family is a few shapes over
    thousands of textures). detile: for each linear element, its tiled one. retile: for each tiled element, its linear
    one, or the zero element appended after the picture (ew * eh) for the pitch padding."""
    pairs = _pairs(ew, eh, pitch_e)
    if retile:
        src = [ew * eh] * (_a(pitch_e or ew, 8) * _a(eh, 8))
        for s, d in pairs:
            src[s] = d
    else:
        src = [0] * (ew * eh)
        for s, d in pairs:
            src[d] = s
    return array('I', [e * n + k for e in src for k in range(n)])


def _gather(data, ew, eh, bpe, pitch_e, retile):
    """detile / retile as one gather of whole elements, or None where the plain loop must run (an element size with
    no copy unit, or data not exactly the length the shape asks for, which the loop handles as it always has)."""
    unit = _UNITS.get(bpe)
    want = ew * eh if retile else _a(pitch_e or ew, 8) * _a(eh, 8)
    if unit is None or len(data) != want * bpe or array(unit[0]).itemsize * unit[1] != bpe:
        return None
    code, n = unit
    src = memoryview(bytes(data) + (bytes(bpe) if retile else b'')).cast(code)
    out = array(code)
    out.extend(map(src.__getitem__, _order(ew, eh, pitch_e, n, retile)))
    return out.tobytes()


def detile_thin1d(data, ew, eh, bpe, pitch_e=None):
    """Tiled bytes -> linear rows of ew x eh elements of bpe bytes. pitch_e = the padded pitch in elements."""
    fast = _gather(data, ew, eh, bpe, pitch_e, False)
    if fast is not None:
        return fast
    out = bytearray(ew * eh * bpe)
    for s, d in _pairs(ew, eh, pitch_e):
        out[d * bpe:d * bpe + bpe] = data[s * bpe:s * bpe + bpe]
    return bytes(out)


def retile_thin1d(lin, ew, eh, bpe, pitch_e=None):
    fast = _gather(lin, ew, eh, bpe, pitch_e, True)
    if fast is not None:
        return fast
    out = bytearray(_a(pitch_e or ew, 8) * _a(eh, 8) * bpe)
    for d, s in _pairs(ew, eh, pitch_e):
        out[d * bpe:d * bpe + bpe] = lin[s * bpe:s * bpe + bpe]
    return bytes(out)


def mip_layout(t):
    """[(level, elements w, h, padded pitch in elements, byte offset, byte size)] of a thin 1D texture."""
    if t.fmt not in FMT_BPE:
        raise GnfError(f'format {t.fmt} not supported')
    bpe, blk = FMT_BPE[t.fmt]
    out = []
    off = 0
    for lvl in range(t.base_level, t.last_level + 1):
        w, h = max(1, t.width >> lvl), max(1, t.height >> lvl)
        pitch = t.pitch if lvl == 0 else max(1, t.pitch >> lvl)
        if t.pow2pad:
            w, h, pitch = (1 << (v - 1).bit_length() for v in (w, h, pitch))
        ew, eh, pe = ((v + blk - 1) // blk for v in (w, h, pitch))
        pe = _a(pe, 8)
        size = pe * _a(eh, 8) * bpe
        out.append((lvl, ew, eh, pe, off, size))
        off += size
    return out


def detile(t, data):
    """A texture's data -> [linear bytes of each mip], largest first."""
    if t.tile != TILE_THIN_1D:
        raise GnfError(f'tile mode {t.tile} not supported')
    bpe, _ = FMT_BPE[t.fmt]
    return [detile_thin1d(data[o:o + n], ew, eh, bpe, pe) for _, ew, eh, pe, o, n in mip_layout(t)]


def retile(t, mips):
    if t.tile != TILE_THIN_1D:
        raise GnfError(f'tile mode {t.tile} not supported')
    bpe, _ = FMT_BPE[t.fmt]
    return b''.join(retile_thin1d(m, ew, eh, bpe, pe) for m, (_, ew, eh, pe, _o, _n) in zip(mips, mip_layout(t)))


def pack(template, t, data):
    """A GNF file: `template`'s header with T# `t` (its size word set to len(data)) and `data`."""
    g = Gnf(template)
    w = list(t.w)
    w[7] = len(data)
    head = bytearray(g.raw[:g.data_off])
    struct.pack_into('<8I', head, 16, *w)
    struct.pack_into('<I', head, 12, len(head) + len(data))
    return bytes(head) + data


def from_mips(template, mips, fmt=None, num=None):
    """A GNF shaped like `template` (size, mips, tiling) holding `mips` (linear BCn bytes, largest first)."""
    t = Gnf(template).texture.with_format(fmt, num)
    layout = mip_layout(t)
    if len(mips) != len(layout):
        raise GnfError(f'{len(mips)} mips given, the template has {len(layout)}')
    bpe, _ = FMT_BPE[t.fmt]
    for m, (lvl, ew, eh, _pe, _o, _n) in zip(mips, layout):
        if len(m) != ew * eh * bpe:
            raise GnfError(f'mip {lvl}: {len(m)} bytes, expected {ew * eh * bpe}')
    return pack(template, t, retile(t, mips))


# --- pictures (Pillow) ------------------------------------------------------------------------------------------------

def encode_fmt(t, fmt=None):
    """The format a new texture like `t` gets: `fmt`, else t's own."""
    fmt = fmt or t.fmt
    if fmt not in ENCODABLE:
        raise GnfError(f'cannot encode {fmt}')
    return fmt


def make(template, img, fmt=None, resample=None):
    """GNF bytes shaped like `template` from a Pillow picture: the picture is resized to the template's size, the
    mips are scaled from it the way the game's own were (_mips, MIP_FILTER). `fmt` defaults to the template's; the
    number format stays. A mip that does not fill its last blocks (2 x 2, 1 x 1) is widened by repeating its edge
    pixels, so those blocks are fitted to its colours."""
    import numpy as np
    from PIL import Image
    from . import bcn
    t = Gnf(template).texture
    fmt = encode_fmt(t, fmt)
    nt = t.with_format(fmt)
    mode = 'RGB' if fmt == 'BC5' else 'RGBA'
    img = img.convert(mode)
    if img.size != (t.width, t.height):
        img = img.resize((t.width, t.height), resample if resample is not None else Image.LANCZOS)
    layout = mip_layout(nt)
    levels = _mips(img, [(max(1, t.width >> lvl), max(1, t.height >> lvl)) for lvl, *_r in layout])
    mips = []
    for px, (_lvl, ew, eh, _pe, _o, _n) in zip(levels, layout):
        px = np.pad(px, ((0, eh * 4 - px.shape[0]), (0, ew * 4 - px.shape[1]), (0, 0)), mode='edge')
        mips.append(bcn.encode(fmt, px))
    return pack(template, nt, retile(nt, mips))


# How the game's own textures were mipped, measured on NHL 19's Czech jerseys (jersey_nineties_* and jersey_rbk_wc_*
# colour maps, 2048 BC1 sRGB): each mip of theirs is closest to its mip 0 scaled down with a bicubic filter in the
# stored (sRGB) numbers (mip 1: 40.6 to 45.9 dB), then Lanczos, then box; scaled in linear light it is 3 to 7 dB
# further off; from mip 0 or from the mip above cannot be told apart. So the mips here are made the same way.
MIP_FILTER = 'BICUBIC'


def _mips(img, sizes):
    """Each mip of `img` (RGB / RGBA, already the first mip's size) as (h, w, C) uint8, the first as it is. The others
    are scaled from it with MIP_FILTER in the stored numbers, as the game's own (see MIP_FILTER), in floats and weighted
    by alpha (a clear pixel's colour does not bleed into its neighbours)."""
    import numpy as np
    from PIL import Image
    first = np.asarray(img, np.uint8)
    out = [first]
    if len(sizes) == 1:
        return out
    a = first.astype(np.float32) / 255
    alpha = a[..., 3:] if a.shape[2] == 4 else None
    rgb = a[..., :3] if alpha is None else a[..., :3] * alpha
    planes = [rgb[..., c] for c in range(3)] + ([alpha[..., 0]] if alpha is not None else [])
    planes = [Image.fromarray(np.ascontiguousarray(p, np.float32), 'F') for p in planes]
    method = getattr(Image.Resampling, MIP_FILTER)
    for size in sizes[1:]:
        small = np.stack([np.asarray(p.resize(size, method), np.float32) for p in planes], -1)
        rgb = small[..., :3]
        if alpha is not None:
            al = np.clip(small[..., 3:], 0, 1)      # a bicubic filter overshoots at hard edges: kept in range
            rgb = np.where(al > 0, rgb / np.maximum(al, 1e-12), 0)
        mip = rgb if alpha is None else np.concatenate([rgb, al], -1)
        out.append(np.clip(np.rint(mip * 255), 0, 255).astype(np.uint8))
    return out


def to_image(data, level=0):
    """One mip of a GNF file as a Pillow picture (RGBA; L for BC4, RGB for BC5)."""
    from PIL import Image
    g = Gnf(data)
    t = g.texture
    mips = detile(t, g.data())
    _lvl, ew, eh, *_ = mip_layout(t)[level]
    w, h = max(1, t.width >> level), max(1, t.height >> level)
    if t.fmt in BCN:
        n = BCN[t.fmt]
        img = Image.frombytes({4: 'L', 5: 'RGB', 6: 'RGB'}.get(n, 'RGBA'), (ew * 4, eh * 4), mips[level], 'bcn', n)
        return img.crop((0, 0, w, h))
    if t.fmt == '8_8_8_8':
        return Image.frombytes('RGBA', (w, h), mips[level][:w * h * 4])
    raise GnfError(f'cannot decode {t.fmt}')
