"""This season's jerseys, made on the player's PC (NHL Legacy's way: a small pack of source pictures, the game's
textures made on the player's own files).

NHL 27's kits reach NHL 19 by making each kit texture of a jersey row anew (tools/build_kitlayers.py: NHL 27's kits on
NHL 19's rows, tools/nhl27/warp19.py: the layouts). The textures used to be served whole (the alts_* packs, 3.7 GB, the
game's own normal maps in them). Now a layer pack holds only NHL 27's pictures, already in NHL 19's layout, and a step
per texture, one pack per family (FAMILIES):

    pack.json  {"format": 1, "kind": "kitlayers", "name", "family", "built", "source", "members": {member: sha256},
                "files": {game path: step}, "alternates": [{teamid, style, variant, locstring, ...}]}

    step  {"op": "make", "picture": member}      the picture made into the game's file (gnf.make: its size, mips, format)
          {"op": "cover", "mask": member}        the game's own normal / coeff map with its old crest covered (cover)
          {"op": "flat"}                         the game's own number sheet normals made flat
          {"op": "pants", "main": rgb, "trim": rgb or null}   the game's own pants in NHL 27's colours (pants)

compose() runs the steps on the game's own files into one more art pack in the app's cache, served as `alts-<family>`
(overlay: the same name the whole packs had), with the pack's `alternates` (art.alternate_rows relabels those rows).
A second Patch with the same pack and game writes nothing (`made`). The NHL teams' own kits (kits.zip) keep the game's
2018 pants; PANTS gives the teams whose pants changed colour since then theirs, the same way (compose of `Pants`).

Pillow is imported inside the functions only: the server imports overtime_core and stays stdlib.
"""
import collections
import datetime
import hashlib
import io
import json
import os
import zipfile

from . import art, eb, gamefiles, gnf

KIND, FORMAT = 'kitlayers', 1
# family: the source pack (a download with its own switch), the switch (patch_ctl), the pack served (its name)
# hometown (the owner's Hometown Remix photos, tools/build_hometown.py) comes last: where it and NHL 27's alternate
# take the same row it wins, and the patch serves it after looks.zip too (patch.art_packs)
FAMILIES = ('nhl', 'intl', 'clubs', 'hometown')
SOURCE = "NHL 27's jerseys, made on this PC"
DRAWING = '1'                   # bump when a step draws differently: every composed pack is made again
HEAD = 0x100                    # a GNF's header: all gnf.make needs of its template
SIZE = 1024                     # the masks' size (warp19.SIZE)
MIRROR_Y, LIFT = 640, 130       # cover: below MIRROR_Y a block comes from the mirrored row (the back), above from LIFT higher
SHADE = (0.7, 1.3)              # pants: the fabric's shading kept as a factor in this range
TRIM_GAP = (60, 120)            # pants: a pixel this far from the main colour (sum of the channels) is trim (soft between)
PANTS_KIT = 'kits-pants'
PANTS_LOCAL = 'kits_pants_local.zip'
STAMP = (2026, 1, 1, 0, 0, 0)


def source_pack(family):
    return f'kitlayers_{family}.zip'


def switch(family):
    """The Game patch tab's switch of a family (the keys the alts_* packs had)."""
    return f'alts_{family}'


def served_name(family):
    return f'alts-{family}'


def local_pack(family):
    return f'alts_{family}_local.zip'


class Source:
    """A layer pack: its steps and members, read without the pictures; picture() reads and checks one."""

    def __init__(self, path):
        self.path = path
        try:
            with zipfile.ZipFile(path) as z:
                info = json.loads(z.read(art.MANIFEST).decode('utf-8'))
        except (zipfile.BadZipFile, KeyError, OSError, ValueError) as err:
            raise art.ArtError(f'{path}: {err}') from err
        if info.get('kind') != KIND or info.get('format') != FORMAT:
            raise art.ArtError(f'{path}: not a jersey layer pack of format {FORMAT}')
        self.info = info
        self.family = info.get('family') or ''
        self.files = info.get('files') or {}
        self.members = info.get('members') or {}
        for p, step in self.files.items():
            for member in (step.get('picture') or step.get('mask'), step.get('plain_mask')):
                if member is not None and member not in self.members:
                    raise art.ArtError(f'{path}: {p} names {member}, which the pack lacks')
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for block in iter(lambda: f.read(1 << 20), b''):
                h.update(block)
        self.sha256 = h.hexdigest()
        self._zip = None

    def close(self):
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    def picture(self, member):
        from PIL import Image
        try:
            if self._zip is None:
                self._zip = zipfile.ZipFile(self.path)
            data = self._zip.read(member)
        except (zipfile.BadZipFile, KeyError, OSError) as err:
            raise art.ArtError(f'{self.path}: {err}') from err
        if hashlib.sha256(data).hexdigest() != self.members.get(member):
            raise art.ArtError(f'{self.path}: {member} does not match its checksum')
        img = Image.open(io.BytesIO(data))
        img.load()
        return img


# --- the steps ---------------------------------------------------------------------------------------------------------

def make(template, img):
    return gnf.make(template, img)


def cover(raw, mask, plain_mask=None, plain=None):
    """The GNF `raw` with the blocks under `mask` (an L picture, SIZE x SIZE, not 0 = cover) copied from plain fabric:
    below MIRROR_Y from the mirrored row (SIZE - 1 - y, the back), above it from LIFT rows higher. Every mip of 8 blocks
    across or more; blocks are copied as stored (a SNORM normal map is never re-encoded). `plain_mask` (same kind) with
    `plain` = (front row, back row): the blocks under it come from those rows of the same column instead (the old kit's
    stripes, whose mirrored row is another stripe), `mask` first."""
    g = gnf.Gnf(raw)
    t = g.texture
    bpe, blk = gnf.FMT_BPE[t.fmt]
    px = mask.convert('L').tobytes()
    if len(px) != SIZE * SIZE:
        raise gnf.GnfError(f'a cover mask is {SIZE} x {SIZE}')
    if plain_mask is not None:
        flat_px = plain_mask.convert('L').tobytes()
        px = bytes(a if a else (2 if b else 0) for a, b in zip(px, flat_px))     # 2 = from the plain rows
    out = []
    for lvl, data in enumerate(gnf.detile(t, g.data())):
        w, h = max(1, t.width >> lvl), max(1, t.height >> lvl)
        bw, bh = (w + blk - 1) // blk, (h + blk - 1) // blk
        if bw < 8:
            out.append(data)
            continue
        cols = [min(SIZE - 1, int((bx + 0.5) * SIZE / bw)) for bx in range(bw)]
        row = bw * bpe
        arr = bytearray(data)
        for by in range(bh):
            yy = (by + 0.5) * SIZE / bh
            line = min(SIZE - 1, int(yy)) * SIZE
            hits = [bx for bx, x in enumerate(cols) if px[line + x]]
            if not hits:
                continue
            sy = SIZE - 1 - yy if yy >= MIRROR_Y else yy - LIFT
            src = min(bh - 1, max(0, int(sy * bh / SIZE))) * row
            if plain_mask is not None:
                py = plain[0] if yy >= MIRROR_Y else plain[1]
                src_plain = min(bh - 1, max(0, int(py * bh / SIZE))) * row
            for bx in hits:
                from_plain = plain_mask is not None and px[line + cols[bx]] == 2
                o, s = by * row + bx * bpe, (src_plain if from_plain else src) + bx * bpe
                arr[o:o + bpe] = arr[s:s + bpe]
        out.append(bytes(arr))
    return gnf.from_mips(raw, out)


def flat(raw):
    """A BC5 SNORM normal map shaped like `raw` (its header is enough), all flat (x = y = 0)."""
    t = gnf.Gnf(raw).texture
    if (t.fmt, t.num) != ('BC5', 'SNORM'):
        raise gnf.GnfError(f'flat normals need BC5 SNORM, not {t.describe()}')
    bpe, _ = gnf.FMT_BPE[t.fmt]
    return gnf.from_mips(raw, [bytes(ew * eh * bpe) for _lvl, ew, eh, *_ in gnf.mip_layout(t)])


def _bins(img):
    from PIL import Image
    small = img.convert('RGB').resize((128, 128), Image.BOX)
    return small, small.point(lambda v: v & 0xF0)


def _median_of(small, bins, colour):
    from PIL import Image, ImageChops, ImageStat
    same = ImageChops.difference(bins, Image.new('RGB', bins.size, colour)).convert('L', (1, 1, 1, 0))
    return tuple(int(v) for v in ImageStat.Stat(small, same.point(lambda v: 255 if v == 0 else 0)).median)


def colours(img, share=0.004):
    """(main, trim) of a picture: the colour most of it is, and the next commonest colour far from it (TRIM_GAP's upper
    bound) covering `share` of it at least, or None. Each the median of its pixels (16-step bins of a 128 x 128 copy)."""
    small, bins = _bins(img)
    counts = sorted(bins.getcolors(128 * 128), reverse=True)
    main = _median_of(small, bins, counts[0][1])
    for n, c in counts[1:]:
        if n < share * 128 * 128:
            break
        if sum(abs(a - b) for a, b in zip(c, main)) > TRIM_GAP[1]:
            return main, _median_of(small, bins, c)
    return main, None


def _shade_lut(c):
    lo, hi = SHADE
    out = []
    for v in range(256):
        s = min(hi, max(lo, 1 + (v - 128) * 2 / 255))
        out.append(min(255, max(0, round(c * s + (s - 1) * 40))))
    return out


def pants(raw, main, trim=None):
    """The game's pants `raw` in other colours: what is its main colour becomes `main`, the rest (stripes, trim; soft
    edged) `trim` (`main` when None). The fabric's shading is kept: each pixel's lightness against its zone's colour
    (SHADE)."""
    from PIL import Image, ImageChops, ImageStat
    img = gnf.to_image(raw).convert('RGB')
    own, _ = colours(img)
    lo, hi = TRIM_GAP
    gap = ImageChops.difference(img, Image.new('RGB', img.size, own)).convert('L', (1, 1, 1, 0))
    zone = gap.point(lambda v: 0 if v < lo else 255 if v >= hi else (v - lo) * 255 // (hi - lo))
    lum = img.convert('L')
    main_ref = Image.new('RGB', (1, 1), own).convert('L').getpixel((0, 0))
    solid = zone.point(lambda v: 255 if v == 255 else 0)
    trim_ref = int(ImageStat.Stat(lum, solid).median[0]) if solid.getbbox() else main_ref
    ref = Image.composite(Image.new('L', img.size, trim_ref), Image.new('L', img.size, main_ref), zone)
    dev = ImageChops.subtract(lum, ref, 2.0, 128)

    def shaded(colour):
        return Image.merge('RGB', [dev.point(_shade_lut(c)) for c in colour])
    out = Image.composite(shaded(tuple(trim or main)), shaded(tuple(main)), zone)
    return gnf.make(raw, out)


FONT_GAP = 60                   # font: a colour this far (sum of the channels) from the sheet's three inks is none of them


def _inks(img, alpha):
    """The number sheet's (fill, middle, edge) colours: the commonest colour, the commonest on the glyphs' rim, and the
    commonest of the rest far from both (the rim's when the sheet has only two). Each the median of its pixels."""
    from PIL import Image, ImageChops, ImageFilter
    opaque = alpha.point(lambda v: 255 if v > 200 else 0)
    inner = opaque.filter(ImageFilter.MinFilter(5))
    rim = ImageChops.subtract(opaque, inner)

    def bins(mask):
        ground = Image.new('RGB', img.size, (255, 0, 255))
        small = Image.composite(img, ground, mask).resize((256, 256), Image.NEAREST)
        got = [(n, c) for n, c in (small.point(lambda v: v & 0xF0)).getcolors(256 * 256) if c != (240, 0, 240)]
        return sorted(got, reverse=True)
    body, edge_bins = bins(opaque), bins(rim)
    fill, edge = body[0][1], edge_bins[0][1]
    mid = next((c for _n, c in body if sum(abs(a - b) for a, b in zip(c, fill)) > FONT_GAP
                and sum(abs(a - b) for a, b in zip(c, edge)) > FONT_GAP), edge)
    return fill, mid, edge


def _sub(u, v):
    return [x - y for x, y in zip(u, v)]


def _cross(u, v):
    return [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]


def _len(u):
    return sum(x * x for x in u) ** 0.5


def _mix_matrix(ink, target):
    """The 12 numbers of the RGB -> RGB map (3 x 3 and an offset) that sends ink[i] to target[i] (i = 0..2) and every
    mixture of the inks to the same mixture of the targets: the plane through the inks onto the plane through the
    targets, the direction across it kept as it is. None when two inks are alike (no plane)."""
    i0, i1, i2 = ([float(v) for v in c] for c in ink)
    t0, t1, t2 = ([float(v) for v in c] for c in target)
    d1, d2 = _sub(i1, i0), _sub(i2, i0)
    n = _cross(d1, d2)
    if _len(n) < 0.05 * _len(d1) * _len(d2) or _len(d1) < 1 or _len(d2) < 1:
        return None
    e1, e2 = _sub(t1, t0), _sub(t2, t0)
    m = _cross(e1, e2)
    across = [x * _len(n) / _len(m) for x in m] if _len(m) > 1e-6 else n
    cols_i, cols_t = (d1, d2, n), (e1, e2, across)          # as columns of P and Q: B = Q P^-1
    cof = [[0.0] * 3 for _ in range(3)]
    for r in range(3):
        for c in range(3):
            cof[r][c] = (cols_i[(c + 1) % 3][(r + 1) % 3] * cols_i[(c + 2) % 3][(r + 2) % 3]
                         - cols_i[(c + 1) % 3][(r + 2) % 3] * cols_i[(c + 2) % 3][(r + 1) % 3])
    det = sum(cols_i[0][r] * cof[r][0] for r in range(3))
    inv = [[cof[r][c] / det for r in range(3)] for c in range(3)]     # P^-1 (row c, column r), P[r][c] = cols_i[c][r]
    b = [[sum(cols_t[k][r] * inv[k][c] for k in range(3)) for c in range(3)] for r in range(3)]
    off = [t0[r] - sum(b[r][c] * i0[c] for c in range(3)) for r in range(3)]
    return tuple(v for r in range(3) for v in (*b[r], off[r]))


def _font_image(raw, fill, edge, mid=None):
    """`font`'s RGBA image."""
    from PIL import Image, ImageChops
    img = gnf.to_image(raw).convert('RGBA')
    rgb, alpha = img.convert('RGB'), img.getchannel('A')
    ink = _inks(rgb, alpha)
    target = (tuple(fill), tuple(mid or edge), tuple(edge))
    matrix = _mix_matrix(ink, target)
    if matrix:     # the soft edges between the inks are mixtures: a linear map keeps them mixtures of the new inks
        out = rgb.convert('RGB', matrix)
        out.putalpha(alpha)
        return out
    gaps = [ImageChops.add(ImageChops.difference(rgb, Image.new('RGB', rgb.size, c)).convert('L', (1, 1, 1, 0)),
            Image.new('L', rgb.size, k)) for k, c in enumerate(ink)]      # a tie goes to the earlier ink
    out = Image.new('RGB', rgb.size, target[0])
    for k in (1, 2):
        # this ink where it is nearer than every earlier one
        nearer = ImageChops.subtract(gaps[0], gaps[k], 1, 0)
        better = nearer
        for j in range(1, 3):
            if j != k:
                better = ImageChops.darker(better, ImageChops.subtract(gaps[j], gaps[k], 1, 0))
        out.paste(Image.new('RGB', rgb.size, target[k]), mask=better.point(lambda v: 255 if v > 0 else 0))
    out.putalpha(alpha)
    return out


SHAPE_FROM = 215        # the sheet's rows from here down hold the digits; above are the letters (on a 1024 sheet)
SHAPE_C_A = (840, 160)  # the captain's C and A stand right of the letters, from this x and y down


def font(raw, fill, edge, mid=None, shape=None):
    """The game's number sheet `raw` in other colours: its three inks (the glyph's body, its inner outline, its outer
    outline; found from the sheet itself, `_inks`) become `fill`, `mid` (`edge` when None) and `edge`; the shape and the
    soft edge (alpha) are the game's. `shape`: another sheet (same layout) whose digits replace this one's, in the same
    colours (a font whose digits carry flares the kit's own number does not)."""
    out = _font_image(raw, fill, edge, mid)
    if shape is not None:
        other = _font_image(shape, fill, edge, mid)
        if other.size != out.size:
            other = other.resize(out.size)
        cut = SHAPE_FROM * out.size[1] // 1024
        out.paste(other.crop((0, cut, out.size[0], out.size[1])), (0, cut))
        x0, y0 = SHAPE_C_A[0] * out.size[0] // 1024, SHAPE_C_A[1] * out.size[1] // 1024
        out.paste(other.crop((x0, y0, out.size[0], cut)), (x0, y0))
    return gnf.make(raw, out)


def run(step, raw, picture, read=None):
    """The GNF of one step on the game's file `raw` (its header is enough for make / flat); `picture(member)` reads the
    source's pictures, `read(path)` another of the game's files."""
    op = step.get('op')
    if op == 'make':
        return make(raw, picture(step['picture']))
    if op == 'cover':
        if step.get('plain_mask'):
            return cover(raw, picture(step['mask']), picture(step['plain_mask']), step['plain'])
        return cover(raw, picture(step['mask']))
    if op == 'flat':
        return flat(raw)
    if op == 'pants':
        return pants(raw, step['main'], step.get('trim'))
    if op == 'font':
        shape = read(step['shape']) if step.get('shape') and read else None
        return font(raw, step['fill'], step['edge'], step.get('mid'), shape)
    raise art.ArtError(f'unknown step {op!r}')


WHOLE = ('cover', 'pants', 'font')      # the steps that read the game's whole file


# --- the NHL teams' own pants -------------------------------------------------------------------------------------------

# NHL 27's pants of the NHL kits whose colour NHL 19's own pants (2018's) lack, by game path: (main, trim or None).
# Made by `python tools/build_kitlayers.py --pants` (2026-11-03, checked on a contact sheet of NHL 19's, NHL 27's and
# the result); a kit whose pants kept their colour is not listed.
_PANT = 'nhl/data/kettle/rendering/characters/player/pant_adidas_'
PANTS = {
    _PANT + 'anaheim_away_cm.gnf': ((230, 57, 24), (27, 26, 27)),
    _PANT + 'anaheim_home_cm.gnf': ((230, 57, 24), (27, 26, 27)),
    _PANT + 'buffalo_away_cm.gnf': ((24, 46, 126), (255, 178, 0)),
    _PANT + 'buffalo_home_cm.gnf': ((24, 46, 126), (255, 178, 0)),
    _PANT + 'buffalo_two_cm.gnf': ((27, 26, 27), None),
    _PANT + 'calgary_away_cm.gnf': ((159, 14, 10), (255, 176, 0)),
    _PANT + 'calgary_home_cm.gnf': ((159, 14, 10), (255, 176, 0)),
    _PANT + 'calgary_two_cm.gnf': ((27, 28, 27), (159, 14, 10)),
    _PANT + 'carolina_home_cm.gnf': ((27, 26, 27), None),
    _PANT + 'carolina_two_cm.gnf': ((159, 14, 10), None),
    _PANT + 'colorado_away_cm.gnf': ((27, 56, 112), None),
    _PANT + 'colorado_home_cm.gnf': ((27, 56, 112), None),
    _PANT + 'columbus_away_cm.gnf': ((27, 29, 46), (159, 14, 10)),
    _PANT + 'sanjose_away_cm.gnf': ((13, 85, 93), (233, 233, 233)),
    _PANT + 'sanjose_home_cm.gnf': ((13, 85, 93), (233, 233, 233)),
    _PANT + 'stlouis_away_cm.gnf': ((24, 99, 192), None),
    _PANT + 'stlouis_home_cm.gnf': ((24, 99, 192), None),
    _PANT + 'stlouis_two_cm.gnf': ((27, 29, 46), None),
    _PANT + 'toronto_two_cm.gnf': ((24, 22, 24), None),
    _PANT + 'vegas_away_cm.gnf': ((63, 60, 63), None),
    _PANT + 'vegas_home_cm.gnf': ((63, 60, 63), None),
    _PANT + 'winnipeg_two_cm.gnf': ((134, 18, 21), (24, 29, 46)),
}


class Pants:
    """PANTS as a source for compose()."""
    family = 'pants'

    def __init__(self, table=None):
        table = PANTS if table is None else table
        self.files = {p: {'op': 'pants', 'main': list(m), 'trim': list(t) if t else None}
                      for p, (m, t) in sorted(table.items())}
        self.info = {}
        self.sha256 = hashlib.sha256(json.dumps(self.files, sort_keys=True).encode('utf-8')).hexdigest()

    def picture(self, member):
        raise art.ArtError(f'no picture {member}')

    def close(self):
        pass


# --- making the pack ---------------------------------------------------------------------------------------------------

def _key(source, targets, game_dir):
    from PIL import __version__ as pillow
    arcs = []
    for big in gamefiles.archives(game_dir):
        try:
            arcs.append((os.path.basename(big), os.path.getsize(big)))
        except OSError:
            arcs.append((os.path.basename(big), None))
    text = json.dumps([source.sha256, pillow, DRAWING, arcs, sorted(targets)])
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def made(path):
    try:
        with zipfile.ZipFile(path) as z:
            return json.loads(z.read(art.MANIFEST).decode('utf-8')).get('made')
    except (zipfile.BadZipFile, KeyError, OSError, ValueError):
        return None


def compose(source, game_dir, out_path, name, log=None, progress=None, today=None):
    """Make `source`'s textures (a Source, or Pants) on the game's own files into the art pack `out_path`, served as
    `name` (removed when the game has none of them). Written as it goes: a family's files are more than fit in memory.
    {'files', 'failed', 'missing', 'kept'}: files made, steps that failed (logged), game paths the game lacks, and
    whether the pack as it was is kept (the same source and game as the last time). `progress(share)` as it goes."""
    say = log or (lambda m: None)
    where = gamefiles.winning(game_dir)
    targets = sorted(p for p in source.files if p in where)
    counts = {'files': 0, 'failed': 0, 'missing': len(source.files) - len(targets), 'kept': False}
    if not targets:
        if os.path.isfile(out_path):
            os.remove(out_path)
        return counts
    key = _key(source, targets, game_dir)
    if os.path.isfile(out_path) and made(out_path) == key:
        counts['kept'] = True
        counts['files'] = len(targets)
        return counts
    by_arc = collections.defaultdict(list)
    for p in targets:
        by_arc[where[p]].append(p)
    cache = {}

    def picture(member):
        if member not in cache:
            if len(cache) > 8:          # a kit's few pictures are used together: keep the last ones only
                cache.clear()
            cache[member] = source.picture(member)
        return cache[member]
    shas = {}
    tmp = out_path + '.tmp'
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    try:
        _write(source, by_arc, targets, picture, tmp, name, key, shas, counts, say, progress, today, where)
    finally:
        source.close()
    if not shas:
        os.remove(tmp)
        if os.path.isfile(out_path):
            os.remove(out_path)
        return counts
    os.replace(tmp, out_path)
    counts['files'] = len(shas)
    return counts


def _write(source, by_arc, targets, picture, tmp, name, key, shas, counts, say, progress, today, where):
    done = 0
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for big, ps in sorted(by_arc.items()):
            with eb.EbArchive(big) as arc:
                for p in ps:
                    step = source.files[p]
                    try:
                        raw = arc.read(p) if step.get('op') in WHOLE else arc.head(p, HEAD)
                        if gnf.Gnf(raw).data_off > len(raw):
                            raw = arc.read(p)
                        data = run(step, raw, picture, lambda q: _read_other(where, q, big, arc))
                        art.check_file(p, data)
                    except (art.ArtError, gnf.GnfError, OSError, ValueError, KeyError) as err:
                        say(f'jerseys: {p} not made ({err})')
                        counts['failed'] += 1
                        continue
                    shas[p] = hashlib.sha256(data).hexdigest()
                    zi = zipfile.ZipInfo(p, STAMP)
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    z.writestr(zi, data, compresslevel=1)
                    done += 1
                    if progress:
                        progress(done / len(targets))
        info = {'format': art.FORMAT, 'name': name, 'built': (today or datetime.date.today()).isoformat(),
                'source': SOURCE, 'files': dict(sorted(shas.items())), 'made': key,
                'alternates': [a for a in source.info.get('alternates') or [] if _rows_made(a, source, shas)]}
        z.writestr(zipfile.ZipInfo(art.MANIFEST, STAMP), json.dumps(info, indent=1, sort_keys=True))


def _read_other(where, path, big, arc):
    """The game's whole file `path` (from the archive being read, or the one that has it)."""
    if path not in where:
        raise KeyError(path)
    if where[path] == big:
        return arc.read(path)
    with eb.EbArchive(where[path]) as other:
        return other.read(path)


def _rows_made(row, source, shas):
    """An `alternates` row is relabelled only when its jersey was made (the pack's `jersey` path for it, if named)."""
    path = row.get('jersey')
    return path is None or path in shas
