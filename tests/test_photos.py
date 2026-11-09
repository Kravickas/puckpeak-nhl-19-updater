"""Player photos the people pack lacks: drawn on this PC (overtime_core.photos, Legacy's portrait), kept in the app's
cache as a local pack and served by the patch (patch.LOCAL_PEOPLE_PACK); Update counts them once the patch has them."""
import datetime
import io

import pytest

from overtime_core import art, clubdata, gnf, photos
from overtime_roster.app import patch
from test_gnf import template

Image = pytest.importorskip('PIL.Image')
ImageDraw = pytest.importorskip('PIL.ImageDraw')

DAY = datetime.date(2026, 11, 3)
ANN, BOB, CY, DEE = (('Ann', 'Alpha', (2000, 1, 2)), ('Bob', 'Beta', (2001, 3, 4)), ('Cy', 'Gamma', (2002, 5, 6)),
                     ('Dee', 'Delta', (2003, 7, 8)))


def person(who, artid):
    first, last, birth = who
    return [clubdata._key(first, last), *birth, artid]


def link(who):
    return (*who, f'https://pics.example/{who[1].lower()}.png')


def headshot(backdrop=None, colours=((224, 172, 140), (200, 20, 30))):
    """PNG bytes of a head and shoulders: on a clear backdrop (NHL.com's cut-outs) or a plain colour (a league's)."""
    skin, shirt = (c + (255,) for c in colours)
    img = Image.new('RGBA', (400, 400), (backdrop + (255,)) if backdrop else (0, 0, 0, 0))
    pen = ImageDraw.Draw(img)
    pen.rectangle((60, 260, 340, 400), fill=shirt)
    pen.ellipse((140, 60, 260, 230), fill=skin)
    pen.rectangle((180, 210, 220, 270), fill=skin)
    out = io.BytesIO()
    img.save(out, 'PNG')
    return out.getvalue()


def picture(webp):
    img = Image.open(io.BytesIO(webp))
    img.load()
    return img.convert('RGBA')


@pytest.mark.parametrize('backdrop', [None, (40, 90, 200)])
def test_a_photo_is_drawn_with_the_head_where_legacys_portraits_have_it(backdrop):
    img = picture(photos.draw(headshot(backdrop)))
    top, cx, width, _last = photos.SPOT
    assert img.size == (512, 256)
    skin = img.getpixel((cx, top + width // 2))
    assert skin[3] == 255 and all(abs(a - b) < 24 for a, b in zip(skin, (224, 172, 140)))
    assert img.getpixel((10, 10))[3] == 0 and img.getpixel((500, 10))[3] == 0       # the backdrop is off
    found = photos.head(img.getchannel('A').point(lambda v: 255 if v > 128 else 0))
    assert abs(found[0] - top) <= 3 and abs(found[1] - cx) <= 3 and abs(found[2] - width) <= 6


def test_hairs_standing_up_above_the_head_do_not_hide_it():
    img = Image.open(io.BytesIO(headshot()))
    pen = ImageDraw.Draw(img)
    pen.rectangle((195, 40, 207, 62), fill=(60, 40, 30, 255))     # a tuft of hair, 13 wide, 20 rows above the head
    top, cx, width = photos.head(img.getchannel('A'))
    assert 60 <= top <= 64 and abs(cx - 200) < 4 and abs(width - 121) <= 2
    assert photos.draw(img_bytes(img)) is not None


def img_bytes(img):
    out = io.BytesIO()
    img.save(out, 'PNG')
    return out.getvalue()


def test_a_grey_silhouette_or_a_broken_file_is_no_photo():
    assert photos.draw(headshot(colours=((128, 128, 128), (128, 128, 128)))) is None
    with pytest.raises(Exception):
        photos.draw(b'not a picture')


def test_a_portrait_fills_the_games_own_size():
    raw = template(512, 340, 'BC3')
    out = photos.to_gnf(raw, photos.draw(headshot()))
    t = gnf.Gnf(out).texture
    assert (t.width, t.height, len(out)) == (512, 340, len(raw))


def test_only_whom_the_people_pack_lacks_is_drawn_and_each_keeps_his_art_id(tmp_path):
    raw = template(512, 340, 'BC3')
    asked = []

    def get(url):
        asked.append(url)
        if 'gamma' in url:
            return headshot(colours=((128, 128, 128), (128, 128, 128)))      # a stand-in: no photo
        return headshot()
    links = [link(ANN), link(BOB), link(CY)]
    people = [person(ANN, 40000)]
    files, rows, counts = photos.supplement(links, people, tmp_path, raw, get=get, today=DAY)
    top = art.PEOPLE_ARTIDS[-1]
    assert rows == [person(BOB, top)] and set(files) == {art.PORTRAIT.format(top)}
    assert counts == {'drawn': 1, 'failed': 1, 'kept': 0} and len(asked) == 2

    # the same day again: nothing downloaded (Bob is drawn, Cy's stand-in waits RETRY_DAYS), the same pack
    again = photos.supplement(links, people, tmp_path, raw, get=get, today=DAY)
    assert again[:2] == (files, rows) and again[2] == {'drawn': 0, 'failed': 0, 'kept': 1} and len(asked) == 2
    photos.supplement(links, people, tmp_path, raw, get=get, today=DAY + datetime.timedelta(days=photos.RETRY_DAYS))
    assert len(asked) == 3                                                     # Cy is tried again a week on

    # Bob is in the people pack now: he leaves the local one, and Dee does not take his art id (saved rosters hold it)
    files, rows, _counts = photos.supplement(links + [link(DEE)], people + [person(BOB, 40001)], tmp_path, raw,
                                             get=get, today=DAY)
    assert rows == [person(DEE, top - 1)] and set(files) == {art.PORTRAIT.format(top - 1)}


def test_the_local_pack_goes_when_no_photo_is_missing(tmp_path):
    path = str(tmp_path / photos.LOCAL_PACK)
    rows = [person(BOB, 65535)]
    photos.write_local(path, {art.PORTRAIT.format(65535): template(64, 64)}, rows, built='2026-11-03')
    pack = art.load_pack(path)
    assert pack.name == photos.LOCAL_NAME and pack.info['people'] == rows
    photos.write_local(path, {}, [])
    assert not (tmp_path / photos.LOCAL_PACK).exists()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """A cache with the people pack (Ann) and a local pack (Bob; Ann too, as when the people pack took her in later)."""
    monkeypatch.delenv(patch.ART_ENV, raising=False)
    monkeypatch.setattr(patch.sources, 'BUILD_PACKS', str(tmp_path / 'exe'))
    monkeypatch.setattr(patch.sources, 'REPO_PACKS', str(tmp_path / 'repo'))
    folder = tmp_path / 'cache'
    folder.mkdir()
    art.write_pack(str(folder / patch.PEOPLE_PACK), 'people', {art.PORTRAIT.format(40000): template(64, 64)},
                   built='2026-11-02', extra={'people': [person(ANN, 40000)]})
    photos.write_local(str(folder / patch.LOCAL_PEOPLE_PACK), {art.PORTRAIT.format(65535): template(64, 64),
                                                              art.PORTRAIT.format(65534): template(64, 64)},
                       [person(BOB, 65535), person(ANN, 65534)], built='2026-11-03')
    return str(folder)


def serve(monkeypatch, packs):
    records = [p.record() for p in packs]
    monkeypatch.setattr(patch.overlay, 'status', lambda game_dir: {'layers': {'art': {'packs': records}}})
    return records


def test_the_patch_serves_the_local_pack_with_the_photos(cache):
    names = [p.name for p in patch.art_packs(cache)[0]]
    assert names == ['people', photos.LOCAL_NAME]
    assert [p.name for p in patch.art_packs(cache, photos=False)[0]] == []
    assert patch.people_rows(cache) == [person(ANN, 40000)]


def test_update_counts_the_local_photos_only_as_the_patch_served_them(cache, monkeypatch, tmp_path):
    packs = patch.art_packs(cache)[0]
    serve(monkeypatch, packs)
    files, people = patch.served_portraits('game', cache)
    assert files == {art.PORTRAIT.format(n) for n in (40000, 65535, 65534)}
    assert people == [person(ANN, 40000), person(BOB, 65535)]      # Ann's people-pack art id wins

    # Update drew a new photo after this Patch: the local pack changed, its photos wait for the next Patch
    photos.write_local(f'{cache}/{patch.LOCAL_PEOPLE_PACK}', {art.PORTRAIT.format(65535): template(64, 64),
                                                             art.PORTRAIT.format(65533): template(64, 64)},
                       [person(BOB, 65535), person(DEE, 65533)], built='2026-11-04')
    files, people = patch.served_portraits('game', cache)
    assert files == {art.PORTRAIT.format(40000)} and people == [person(ANN, 40000)]

    # nothing served, nothing counted; a packs folder named alone (OVERTIME_ART_PACKS) leaves the cache unread
    serve(monkeypatch, [])
    assert patch.served_portraits('game', cache) == (set(), [])
    monkeypatch.setenv(patch.ART_ENV, str(tmp_path / 'elsewhere'))
    assert patch.local_people(cache) is None and patch.art_packs(cache)[0] == []


def test_a_made_portrait_is_kept_and_made_again_only_when_its_inputs_change(tmp_path, monkeypatch):
    raw = template(512, 340, 'BC7')
    links = [link(ANN)]
    files, _rows, _c = photos.supplement(links, [], tmp_path, raw, get=lambda url: headshot(), today=DAY)
    made = sorted(p.name for p in tmp_path.glob('*.gnf'))
    assert len(made) == 1 and gnf.Gnf(next(iter(files.values()))).texture.fmt == 'BC7'
    calls = []
    real = photos.to_gnf
    monkeypatch.setattr(photos, 'to_gnf', lambda *a: calls.append(1) or real(*a))
    again, _rows, _c = photos.supplement(links, [], tmp_path, raw, get=lambda url: headshot(), today=DAY)
    assert again == files and not calls                                     # read back, not made again
    monkeypatch.setattr(gnf, 'ENCODER', gnf.ENCODER + 'x')
    photos.supplement(links, [], tmp_path, raw, get=lambda url: headshot(), today=DAY)
    assert calls == [1] and sorted(p.name for p in tmp_path.glob('*.gnf')) != made   # a new encoder: made again
    assert len(list(tmp_path.glob('*.gnf'))) == 1                                      # the old one gone
