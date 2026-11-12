"""This season's jerseys made on this PC (overtime_core.kitcompose): the steps (make, cover, flat, pants), the colours
of a picture, compose on a game's own files (made, kept, rows relabelled only for jerseys made, a step that fails), the
layer pack's checks, and the app's side (patch.make_kits, art_packs, packdownload's check). No game, no network:
synthetic GNF templates in a temp game folder, a layer pack written here."""
import hashlib
import io
import json
import os
import zipfile

import pytest

from overtime_core import art, eb, gnf, kitcompose as K
from overtime_roster.app import packdownload, patch, sources
from test_gnf import template

JERSEY = 'nhl/rendering/jersey_rbk_test_three_cm.gnf'
NORMAL = 'nhl/rendering/jersey_rbk_test_three_nm.gnf'
FONT_NM = 'nhl/rendering/font_rbk_test_three_nm.gnf'
PANT = 'nhl/rendering/pant_rbk_test_three_cm.gnf'
GONE = 'nhl/rendering/jersey_rbk_test_four_cm.gnf'
WHITE, BLACK = (235, 235, 235), (20, 20, 20)


@pytest.fixture
def pil():
    return pytest.importorskip('PIL.Image')


def near(colour, want, slack=12):
    return all(abs(a - b) <= slack for a, b in zip(colour, want))


def webp(img):
    out = io.BytesIO()
    img.save(out, 'WEBP', lossless=True, exact=True)
    return out.getvalue()


def png(img):
    out = io.BytesIO()
    img.save(out, 'PNG')
    return out.getvalue()


def layer_pack(path, files, pictures, family='nhl', alternates=()):
    """A layer pack as tools/build_kitlayers.py writes it: `pictures` {member: bytes}."""
    info = {'format': K.FORMAT, 'kind': K.KIND, 'name': f'kitlayers-{family}', 'family': family, 'built': '2026-11-03',
            'source': 'test', 'members': {m: hashlib.sha256(d).hexdigest() for m, d in pictures.items()},
            'files': files, 'alternates': list(alternates)}
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(art.MANIFEST, json.dumps(info))
        for member, data in pictures.items():
            z.writestr(member, data)
    return str(path)


def striped(pil, size=64, rows=range(20, 28)):
    """White fabric with a black stripe on block rows (BC keeps it sharp)."""
    img = pil.new('RGB', (size, size), WHITE)
    for y in rows:
        for x in range(size):
            img.putpixel((x, y), BLACK)
    return img


# --- the steps -------------------------------------------------------------------------------------------------------
def test_make_takes_the_games_size_and_format(pil):
    out = K.make(template(64, 64, 'BC3'), pil.new('RGBA', (256, 256), (200, 30, 40, 255)))
    t = gnf.Gnf(out).texture
    assert (t.width, t.height, t.fmt) == (64, 64, 'BC3')
    assert near(gnf.to_image(out).getpixel((10, 10)), (200, 30, 40, 255))


def test_cover_copies_plain_fabric_over_the_old_crest(pil):
    raw = template(64, 64, 'BC1')
    mask = pil.new('L', (K.SIZE, K.SIZE), 0)
    mask.paste(255, (0, 800, K.SIZE, 900))      # block rows 12 and 13 (centres 800 and 864): below MIRROR_Y
    before = gnf.detile(gnf.Gnf(raw).texture, gnf.Gnf(raw).data())[0]
    out = K.cover(raw, mask)
    after = gnf.detile(gnf.Gnf(out).texture, gnf.Gnf(out).data())[0]
    row = 16 * 8                                # 16 blocks of 8 bytes
    assert after[12 * row:13 * row] == before[3 * row:4 * row]     # mirrored: 1023 - 800 = 223 -> block row 3
    assert after[13 * row:14 * row] == before[2 * row:3 * row]
    assert after[:12 * row] == before[:12 * row] and after[14 * row:] == before[14 * row:]
    assert len(out) == len(raw) and out[:0x100] == raw[:0x100]
    with pytest.raises(gnf.GnfError):
        K.cover(raw, pil.new('L', (64, 64), 255))


def test_cover_plain_rows_copy_the_given_row_of_the_same_columns(pil):
    raw = template(64, 64, 'BC1')
    mask = pil.new('L', (K.SIZE, K.SIZE), 0)
    plain = pil.new('L', (K.SIZE, K.SIZE), 0)
    plain.paste(255, (0, 800, K.SIZE, 900))     # block rows 12 and 13: below MIRROR_Y, from row 100 -> block row 1
    before = gnf.detile(gnf.Gnf(raw).texture, gnf.Gnf(raw).data())[0]
    out = K.cover(raw, mask, plain, (100, 40))
    after = gnf.detile(gnf.Gnf(out).texture, gnf.Gnf(out).data())[0]
    row = 16 * 8
    assert after[12 * row:13 * row] == before[1 * row:2 * row] and after[13 * row:14 * row] == before[1 * row:2 * row]
    assert after[:12 * row] == before[:12 * row] and after[14 * row:] == before[14 * row:]


def test_flat_normals_are_zero_and_keep_the_shape():
    raw = template(64, 64, 'BC5', 'SNORM', mips=3)
    out = K.flat(raw[:K.HEAD])                  # the header is enough
    assert out[:0x100] == raw[:0x100] and len(out) == len(raw) and not any(gnf.Gnf(out).data())
    with pytest.raises(gnf.GnfError, match='BC5 SNORM'):
        K.flat(template(64, 64, 'BC1'))


def test_colours_finds_the_main_colour_and_a_trim_far_from_it(pil):
    main, trim = K.colours(striped(pil))
    assert near(main, WHITE, 4) and near(trim, BLACK, 4)
    assert K.colours(pil.new('RGB', (64, 64), (10, 40, 120))) == ((10, 40, 120), None)


def test_pants_take_the_new_main_and_trim_colours(pil):
    raw = gnf.make(template(64, 64, 'BC1'), striped(pil))
    out = gnf.to_image(K.pants(raw, (10, 40, 120), (200, 150, 0))).convert('RGB')
    assert near(out.getpixel((5, 5)), (10, 40, 120)) and near(out.getpixel((5, 60)), (10, 40, 120))
    assert near(out.getpixel((5, 24)), (200, 150, 0))
    one = gnf.to_image(K.pants(raw, (10, 40, 120))).convert('RGB')        # no trim: the stripe takes the main colour
    assert near(one.getpixel((5, 24)), (10, 40, 120))


def _number_sheet(pil):
    """A 64 x 64 RGBA sheet: a glyph on clear ground, 3 inks: fill (black) inside, a white ring, a red rim."""
    img = pil.new('RGBA', (64, 64), (0, 0, 0, 0))
    for box, colour in (((8, 8, 56, 56), (220, 40, 20, 255)), ((12, 12, 52, 52), (230, 230, 230, 255)),
                        ((16, 16, 48, 48), (20, 20, 20, 255))):
        img.paste(pil.new('RGBA', (box[2] - box[0], box[3] - box[1]), colour), box[:2])
    return img


def test_font_recolours_the_sheets_three_inks_and_keeps_its_shape(pil):
    raw = gnf.make(template(64, 64, 'BC3'), _number_sheet(pil))
    out = gnf.to_image(K.font(raw, (245, 188, 79), (20, 22, 20), (56, 45, 89))).convert('RGBA')
    assert near(out.getpixel((32, 32)), (245, 188, 79, 255), 20)          # the glyph's body: fill
    assert near(out.getpixel((14, 32)), (56, 45, 89, 255), 20)            # the ring inside the rim: mid
    assert near(out.getpixel((10, 32)), (20, 22, 20, 255), 20)            # the outer rim: edge
    assert out.getpixel((2, 2))[3] == 0                                    # clear ground stays clear
    two = gnf.to_image(K.font(raw, (245, 188, 79), (20, 22, 20))).convert('RGBA')       # no mid: the edge colour
    assert near(two.getpixel((14, 32)), (20, 22, 20, 255), 20)
    assert K.run({'op': 'font', 'fill': [1, 2, 3], 'edge': [4, 5, 6]}, raw, None)
    assert 'font' in K.WHOLE


def test_font_shape_takes_the_digits_from_another_sheet_in_the_same_colours(pil):
    """On a 64 px sheet the digits start at row 13 (215 / 1024): above it the sheet's own glyphs stay."""
    other = pil.new('RGBA', (64, 64), (0, 0, 0, 0))
    other.paste(pil.new('RGBA', (20, 20), (220, 40, 20, 255)), (22, 40))        # a glyph only the other sheet has
    raw, shape = gnf.make(template(64, 64, 'BC3'), _number_sheet(pil)), gnf.make(template(64, 64, 'BC3'), other)
    args = ((245, 188, 79), (20, 22, 20), (56, 45, 89))
    out = gnf.to_image(K.font(raw, *args, shape)).convert('RGBA')
    plain = gnf.to_image(K.font(raw, *args)).convert('RGBA')
    assert out.getpixel((32, 10))[3] == 255 and plain.getpixel((32, 10))[3] == 255     # the letters' rows stay the sheet's own
    assert out.getpixel((10, 30))[3] == 0 and plain.getpixel((10, 30))[3] == 255       # the digits' rows: the other's shapes
    assert out.getpixel((32, 50))[3] == 255
    assert K.run({'op': 'font', 'fill': [1, 2, 3], 'edge': [4, 5, 6], 'shape': 'x'}, raw, None, lambda q: shape)


def test_font_mix_matrix_sends_the_inks_and_their_mixtures_to_the_new_inks():
    ink = ((224, 224, 224), (16, 16, 16), (160, 144, 96))            # a stock sheet's near-degenerate inks
    target = ((245, 188, 79), (20, 22, 20), (57, 45, 88))
    m = K._mix_matrix(ink, target)
    assert m is not None

    def apply(c):
        return [sum(m[r * 4 + k] * c[k] for k in range(3)) + m[r * 4 + 3] for r in range(3)]
    for i, t in zip(ink, target):
        assert all(abs(x - y) < 0.5 for x, y in zip(apply(i), t))
    half = [(x + y) / 2 for x, y in zip(ink[0], ink[2])]                # a soft edge between fill and rim stays between
    assert all(abs(x - (y + z) / 2) < 0.5 for x, y, z in zip(apply(half), target[0], target[2]))
    assert K._mix_matrix(((9, 9, 9), (9, 9, 9), (200, 0, 0)), target) is None


def test_an_unknown_step_is_refused():
    with pytest.raises(art.ArtError, match='unknown step'):
        K.run({'op': 'paint'}, b'', None)


# --- compose on the game's own files ---------------------------------------------------------------------------------
@pytest.fixture
def world(tmp_path, pil):
    """A game with a jersey, its normals, a number sheet's normals and pants, and a layer pack making them (and a jersey
    the game lacks); its two alternate rows name the jersey made and the one the game lacks."""
    big = tmp_path / 'NHL 19' / 'databigs'
    big.mkdir(parents=True)
    eb.new_archive(str(big / 'inxp_10.big'), {
        JERSEY: template(64, 64, 'BC3'), NORMAL: template(64, 64, 'BC5', 'SNORM'),
        FONT_NM: template(64, 64, 'BC5', 'SNORM'), PANT: gnf.make(template(64, 64, 'BC1'), striped(pil))})
    red = webp(pil.new('RGB', (64, 64), (200, 30, 40)))
    mask = png(pil.new('1', (K.SIZE, K.SIZE), 0))
    pictures = {hashlib.sha256(red).hexdigest()[:20] + '.webp': red, 'm.png': mask}
    member = next(iter(pictures))
    files = {JERSEY: {'op': 'make', 'picture': member}, NORMAL: {'op': 'cover', 'mask': 'm.png'},
             FONT_NM: {'op': 'flat'}, PANT: {'op': 'pants', 'main': [10, 40, 120], 'trim': [200, 150, 0]},
             GONE: {'op': 'make', 'picture': member}}
    rows = [{'teamid': 1, 'style': 1, 'variant': 3, 'locstring': 2, 'jersey': JERSEY},
            {'teamid': 1, 'style': 1, 'variant': 4, 'locstring': 2, 'jersey': GONE}]
    path = layer_pack(tmp_path / K.source_pack('nhl'), files, pictures, alternates=rows)
    return {'game': str(tmp_path / 'NHL 19'), 'pack': path, 'rows': rows,
            'out': str(tmp_path / 'cache' / K.local_pack('nhl'))}


def test_compose_makes_the_textures_and_relabels_only_the_rows_made(world):
    counts = K.compose(K.Source(world['pack']), world['game'], world['out'], K.served_name('nhl'))
    assert counts == {'files': 4, 'failed': 0, 'missing': 1, 'kept': False}
    pack = art.load_pack(world['out'])
    assert pack.name == 'alts-nhl' and set(pack.files) == {JERSEY, NORMAL, FONT_NM, PANT}
    assert pack.info['alternates'] == world['rows'][:1]                     # the jersey the game lacks: no relabel
    assert near(gnf.to_image(pack.files[JERSEY].read()).getpixel((8, 8)), (200, 30, 40, 255))
    assert not any(gnf.Gnf(pack.files[FONT_NM].read()).data())
    assert near(gnf.to_image(pack.files[PANT].read()).convert('RGB').getpixel((5, 24)), (200, 150, 0))


def test_compose_again_keeps_the_pack_and_a_new_pack_makes_it_again(world, tmp_path, pil):
    K.compose(K.Source(world['pack']), world['game'], world['out'], 'alts-nhl')
    before = open(world['out'], 'rb').read()
    again = K.compose(K.Source(world['pack']), world['game'], world['out'], 'alts-nhl')
    assert again == {'files': 4, 'failed': 0, 'missing': 1, 'kept': True} and open(world['out'], 'rb').read() == before
    blue = webp(pil.new('RGB', (64, 64), (20, 40, 200)))
    other = layer_pack(tmp_path / 'other.zip', {JERSEY: {'op': 'make', 'picture': 'b.webp'}}, {'b.webp': blue})
    counts = K.compose(K.Source(other), world['game'], world['out'], 'alts-nhl')
    assert counts['files'] == 1 and not counts['kept'] and set(art.load_pack(world['out']).files) == {JERSEY}
    none = layer_pack(tmp_path / 'none.zip', {GONE: {'op': 'flat'}}, {})
    assert K.compose(K.Source(none), world['game'], world['out'], 'alts-nhl')['missing'] == 1
    assert not os.path.exists(world['out'])                                 # nothing the game has: no pack left


def test_a_step_that_fails_is_logged_and_the_rest_made(world, tmp_path):
    with zipfile.ZipFile(world['pack']) as z:
        info = json.loads(z.read(art.MANIFEST))
        items = {n: z.read(n) for n in z.namelist() if n != art.MANIFEST}
    info['files'][PANT] = {'op': 'flat'}                                    # pants are BC1: no flat normals
    path = layer_pack(tmp_path / 'bad_step.zip', info['files'], items, alternates=info['alternates'])
    said = []
    counts = K.compose(K.Source(path), world['game'], world['out'], 'alts-nhl', log=said.append)
    assert counts['failed'] == 1 and counts['files'] == 3 and len(said) == 1
    assert said[0].startswith(f'jerseys: {PANT} not made (flat normals need BC5 SNORM')
    assert PANT not in art.load_pack(world['out']).files


def test_the_teams_own_pants_from_the_table(world):
    counts = K.compose(K.Pants({PANT: ((10, 40, 120), None), GONE: ((1, 2, 3), None)}), world['game'],
                       world['out'], K.PANTS_KIT)
    assert counts == {'files': 1, 'failed': 0, 'missing': 1, 'kept': False}
    pack = art.load_pack(world['out'])
    assert pack.name == K.PANTS_KIT and near(gnf.to_image(pack.files[PANT].read()).convert('RGB').getpixel((5, 24)),
                                             (10, 40, 120))


def test_a_layer_pack_that_does_not_hold_together_is_refused(world, tmp_path):
    with zipfile.ZipFile(world['pack']) as z:
        info = json.loads(z.read(art.MANIFEST))
        items = {n: z.read(n) for n in z.namelist() if n != art.MANIFEST}
    member = info['files'][JERSEY]['picture']
    with zipfile.ZipFile(tmp_path / 'changed.zip', 'w') as z:                 # another picture under the member's name
        z.writestr(art.MANIFEST, json.dumps(info))
        for n, d in items.items():
            z.writestr(n, items['m.png'] if n == member else d)
    with pytest.raises(art.ArtError, match='checksum'):
        K.Source(str(tmp_path / 'changed.zip')).picture(member)
    lacking = layer_pack(tmp_path / 'lacking.zip', {JERSEY: {'op': 'make', 'picture': 'x.webp'}}, {})
    with pytest.raises(art.ArtError, match='lacks'):
        K.Source(lacking)
    art.write_pack(str(tmp_path / 'plain.zip'), 'plain', {JERSEY: template(64, 64, 'BC3')})
    with pytest.raises(art.ArtError, match='not a jersey layer pack'):
        K.Source(str(tmp_path / 'plain.zip'))
    with pytest.raises(art.ArtError):
        packdownload.check_kitlayers(str(tmp_path / 'plain.zip'))
    packdownload.check_kitlayers(world['pack'])
    with zipfile.ZipFile(tmp_path / 'short.zip', 'w') as z:                   # a member the manifest lists is gone
        z.writestr(art.MANIFEST, json.dumps(info))
    with pytest.raises(art.ArtError, match='pictures missing'):
        packdownload.check_kitlayers(str(tmp_path / 'short.zip'))


# --- the app: Patch makes them, the art layer serves them after the kits ---------------------------------------------
@pytest.fixture
def places(tmp_path, monkeypatch):
    monkeypatch.delenv(patch.ART_ENV, raising=False)
    monkeypatch.setattr(sources, 'BUILD_PACKS', str(tmp_path / 'exe-packs'))
    monkeypatch.setattr(sources, 'REPO_PACKS', str(tmp_path / 'repo-packs'))
    cache = tmp_path / 'cache'
    cache.mkdir(exist_ok=True)
    return cache


def test_patch_makes_the_families_switched_on_and_serves_them_after_the_kits(places, world, monkeypatch):
    monkeypatch.setattr(K, 'PANTS', {PANT: ((10, 40, 120), (200, 150, 0))})
    art.write_pack(str(places / patch.LOOKS32_PACK), 'looks32', {JERSEY.replace('three', 'one'): template(64, 64)})
    (places / K.source_pack('nhl')).write_bytes(open(world['pack'], 'rb').read())
    assert K.source_pack('nhl') in patch.art_found(str(places))
    said, steps, shares = [], [], []
    want = {'art': True, 'kits': True, 'alts_nhl': True, 'alts_intl': True}     # no national team pack here
    made = patch.make_kits(want, world['game'], str(places), log=said.append, step=steps.append,
                           progress=lambda fam, share: shares.append((fam, share)))
    assert set(made) == {'pants', 'nhl'} and made['nhl']['files'] == 4 and made['pants']['files'] == 1
    assert said == ['jerseys (pants): made 1 textures', 'jerseys (nhl): made 4 textures']
    # said every 5 % of the family's work (its textures weighed by size and step, kitcompose.weight), from 0 to 100
    pcts = [int(t.rsplit(', ', 1)[1].split(' ')[0]) for t in steps]
    assert all(t.startswith('making the jerseys on this PC: NHL alternate jerseys, ') for t in steps)
    assert pcts[0] == 0 and pcts[-1] == 100 and pcts == sorted(set(pcts))      # the pants are quick: not said
    for fam in ('pants', 'nhl'):
        got = [x for f, x in shares if f == fam]
        assert got[0] == 0.0 and got[-1] == pytest.approx(1.0) and got == sorted(got)
    layers = []
    packs = patch.art_layer(want, layers, str(places), game_dir=world['game'])
    assert [p.name for p in packs] == ['looks32', K.PANTS_KIT, 'alts-nhl'] and layers == ['art']
    assert patch.make_kits(want, world['game'], str(places))['nhl']['kept']
    off = {**want, 'alts_nhl': False, 'kits': False}
    assert [p.name for p in patch.art_layer(off, [], str(places), game_dir=world['game'])] == ['looks32']
    patch.make_kits(off, world['game'], str(places), log=said.append)
    assert not (places / K.local_pack('nhl')).exists() and (places / K.source_pack('nhl')).exists()
    assert said[-1] == 'jerseys (nhl): switched off, the textures made on this PC are removed'


def test_make_kits_never_stops_a_patch(places, world):
    (places / K.source_pack('intl')).write_bytes(b'PK broken')
    said = []
    assert patch.make_kits({'art': True, 'kits': False, 'alts_intl': True}, world['game'], str(places),
                           log=said.append) == {}
    assert said and said[-1].startswith('jerseys (intl): not made')
    assert patch.make_kits({'art': False, 'alts_intl': True}, world['game'], str(places)) == {}


def test_patch_takes_the_old_whole_jersey_packs_out_of_the_cache(places, world):
    (places / 'alts_intl.zip').write_bytes(b'PK old')      # 0.30 served it: a player who switched it on has it
    said = []
    assert patch.make_kits({'art': False}, world['game'], str(places), log=said.append) == {}
    assert not (places / 'alts_intl.zip').exists()
    assert said == ['jerseys: alts_intl.zip of 0.30 removed (the jerseys are made on this PC now)']


def test_the_layer_packs_are_switches_and_downloads_never_served_themselves():
    assert set(patch.KITLAYER_PACKS) == {K.source_pack(f) for f in K.FAMILIES} <= set(patch.EXTRA_PACKS)
    assert not set(patch.KITLAYER_PACKS) & set(patch.ART_PACKS)
    assert {patch.extra_key(n) for n in patch.KITLAYER_PACKS} == {K.switch(f) for f in K.FAMILIES}
    assert all(packdownload.CHECKS[n] is packdownload.check_kitlayers for n in patch.KITLAYER_PACKS)
