"""Player photos the people pack lacks, drawn on the player's PC (NHL Legacy's one-by-one photos, install.prefetch).

The people pack (tools/build_people.py, packs/people.zip) holds everyone the data pack had a photo of when the owner built
it. A player the data pack lists later (a call-up, a signing) has a photo link there but no portrait in the pack. Update
(overtime_roster.app.update_ctl) downloads those photos, draws them as the pack's are drawn (Legacy's portrait: the head
found, the backdrop off, the shoulders fading out; ported here) and keeps them in the app's cache as one more art pack,
LOCAL_PACK, laid out like the people pack (`people` rows: name key, birth date, art id). The patch serves it next to the
people pack, and the next Update gives the bios those art ids (art.player_portraits) once it is served: a photo is never
flagged before the patch has it in the game.

- Art ids come from the top of art.PEOPLE_ARTIDS down (the people pack takes them from the bottom up) and are kept in the
  cache's index: rosters saved earlier keep pointing at the same picture. A person the people pack has now is left out.
- A photo that fails (no link, no head, NHL.com's grey stand-in) is not tried again for RETRY_DAYS.
- Pillow is imported inside the functions only: the server imports overtime_core and stays stdlib.
"""
import concurrent.futures
import datetime
import hashlib
import io
import json
import os
import re
import urllib.request

from . import art, clubdata, gnf, net, nhlcom

LOCAL_PACK = 'people_local.zip'
LOCAL_NAME = 'people_local'
SOURCE = "NHL.com and the leagues' sites, drawn on this PC"
TEMPLATE = art.PORTRAIT.format(1)       # the game's own portrait: size, mips and tiling of every new one
NHL_HEADSHOT = re.compile(r'assets\.nhle\.com/mugs/.*/(\d+)\.png')
INDEX = 'index.json'
RETRY_DAYS = 7
LIMIT = 400             # photos drawn in one Update at most (the rest come with the next one)
WORKERS = 8
TIMEOUT = 20

# Legacy's portrait (art/images.py), drawn on 512 x 512 and its top half kept, as the people pack's: where the head sits
# in NHL Legacy's own portraits (top of the hair, middle of the head, head width, last row with picture), the rows the
# shoulders fade out over
SIZE = (512, 512)
SPOT = (26, 235, 144, 247)
FADE = 26
KEEP = 256
HEADSHOT = (0.05, 0.5, 0.47)    # where a league's square headshot has the head (shares): when the backdrop stays
STAND_IN = 3.0                  # mean colour spread below which a portrait is a grey stand-in (NHL.com's silhouette)


# --- who has a photo ----------------------------------------------------------------------------------------------

def picture_key(url):
    """The name of a picture: its link, or the NHL id of a headshot (the link names the season)."""
    m = NHL_HEADSHOT.search(url or '')
    return f'nhl:{m.group(1)}' if m else url


def file_name(key):
    return hashlib.sha1(key.encode('utf-8')).hexdigest()[:20]


def headshot(player, season):
    """NHL.com's link for a last-season row without one, from its id and club."""
    if player.get('photo') or not (player.get('nhl_id') and player.get('team')):
        return player.get('photo')
    return f"https://assets.nhle.com/mugs/nhl/{season}{season + 1}/{player['team']}/{player['nhl_id']}.png"


def links(pack):
    """[(first, last, (y, m, d), link)] of everyone the data pack has a photo of: NHL.com first, then the leagues, then
    who left them, then the same people under the other first names NHL 27 and last season give them (Matt and Matthew
    Rempe). The people pack is built from the same list."""
    out = []
    pack = pack or {}
    season = pack.get('season') or 2026
    for club in (pack.get('nhl') or {}).values():
        for group in ('forwards', 'defensemen', 'goalies'):
            for p in club.get(group) or ():
                birth = [int(x) for x in (p.get('birthDate') or '').split('-') if x]
                if p.get('headshot') and len(birth) == 3:
                    out.append(((p.get('firstName') or {}).get('default', ''), (p.get('lastName') or {}).get('default', ''),
                                tuple(birth), p['headshot']))
    out += [(p['first'], p['last'], tuple(p['birth']), headshot(p, season)) for p in pack.get('nhl_last') or ()
            if headshot(p, season) and p.get('birth')]
    leagues = (pack.get('leagues') or {}).values()
    for league in leagues:
        for team in (league.get('teams') or []) + (league.get('extra') or []):
            out += [(p['first'], p['last'], tuple(p['birth']), p['photo']) for p in team.get('players') or ()
                    if p.get('photo') and p.get('birth')]
    for league in leagues:
        out += [(p['first'], p['last'], tuple(p['birth']), p['photo']) for p in league.get('former') or ()
                if p.get('photo') and p.get('birth')]
    link = {}
    for first, last, birth, url in out:
        link.setdefault((clubdata._key(last), birth), url)
    rated = ((pack.get('ratings_full') or {}).get('players') or []) + (pack.get('nhl_last') or [])
    have = {(clubdata._key(f, la), b) for f, la, b, _u in out}
    for p in rated:
        birth = tuple(p['birth']) if p.get('birth') else None
        hit = link.get((clubdata._key(p['last']), birth))
        if hit and (clubdata._key(p['first'], p['last']), birth) not in have:
            have.add((clubdata._key(p['first'], p['last']), birth))
            out.append((p['first'], p['last'], birth, hit))
    return out


# --- drawing (Legacy's portrait) ----------------------------------------------------------------------------------

def _rows(alpha):
    """[(opaque pixels, their mean x)] per row: counting pixels, not the span, keeps a speck of backdrop from counting."""
    w, h = alpha.size
    data = alpha.tobytes()
    out = []
    for y in range(h):
        xs = [x for x, v in enumerate(data[y * w:(y + 1) * w]) if v > 128]
        out.append((len(xs), sum(xs) / len(xs) if xs else 0))
    return out


def head(alpha):
    """(top, centre x, width) of the head in a cut-out's alpha, or None: going down from the top of the hair the outline
    widens to the ears; the head's width is its widest row before the jaw (the shoulders come later). When that finds
    nothing, the head starts at the first row as wide as a head: a tuft of hair standing up above it (hokej.cz's
    Jaromír Pérez Lisa) stopped Legacy's finder after 9 rows, with no head."""
    rows = _rows(alpha)
    w = alpha.size[0]
    for floor in (max(3, w // 50), w // 20):
        top = next((y for y, (n, _x) in enumerate(rows) if n > floor), None)
        if top is None:
            return None
        widest, centre, y = 0, None, top
        while y < len(rows) and (widest == 0 or y < top + 0.8 * widest):
            n, x = rows[y]
            if n > widest:
                widest, centre = n, x
            y += 1
        if widest > w // 20:
            return top, centre, widest
    return None


def _keep_player(mask):
    """The part of a mask joined to the player, who stands on the bottom edge in the middle; islands of backdrop go."""
    from PIL import ImageDraw
    w, h = mask.size
    row = mask.crop((0, h - 1, w, h)).tobytes()
    seeds = [x for x in sorted(range(w), key=lambda x: abs(x - w // 2)) if row[x] == 255]
    if not seeds:
        return mask
    marked = mask.copy()
    ImageDraw.floodfill(marked, (seeds[0], h - 1), 128)
    return marked.point(lambda v: 255 if v == 128 else 0)


def _runs(row, at_least=3):
    count = length = 0
    for v in row:
        if v > 128:
            length += 1
        else:
            count += length >= at_least
            length = 0
    return count + (length >= at_least)


def _plausible(found, w, h):
    return bool(found) and found[0] < 0.25 * h and w / 3 < found[1] < 2 * w / 3 and 0.08 * w < found[2] < 0.75 * w


def _clean(mask, found):
    """One person: the head near the top, a plausible size, and down to the shoulders one stretch per row."""
    w, h = mask.size
    if not _plausible(found, w, h):
        return False
    data = mask.tobytes()
    rows = [data[y * w:(y + 1) * w] for y in range(found[0], min(h, found[0] + int(1.3 * found[2])))]
    return sum(1 for r in rows if _runs(r) > 1) <= 0.08 * len(rows)


def _opened(mask):
    from PIL import ImageFilter
    k = max(3, (min(mask.size) // 60) | 1)
    return _keep_player(mask.filter(ImageFilter.MinFilter(k)).filter(ImageFilter.MaxFilter(k)))


def _backdrop_fill(rgb):
    """(mask, head) of a studio photo: flood fill from the top and the upper sides, where the colour is the backdrop's,
    as tolerant as the backdrop is uneven. None when the fill took most or nothing."""
    from PIL import Image, ImageChops, ImageDraw
    w, h = rgb.size
    px = rgb.load()
    edge = ([px[x, 0] for x in range(0, w, 2)] + [px[0, y] for y in range(0, h * 7 // 10, 2)]
            + [px[w - 1, y] for y in range(0, h * 7 // 10, 2)])
    mean = [sum(e[k] for e in edge) / len(edge) for k in range(3)]
    spread = sum((sum((c[k] - mean[k]) ** 2 for c in edge) / len(edge)) ** 0.5 for k in range(3)) / 3
    marker, work = (255, 0, 255), rgb.copy()
    top_row = sorted(px[x, 0] for x in range(w))
    backdrop = top_row[len(top_row) // 2]
    seeds = [(x, 0) for x in range(0, w, max(1, w // 16))] + \
        [(x, y) for x in (0, w - 1) for y in range(0, h * 2 // 5, max(1, h // 16))]
    for s in seeds:
        if work.getpixel(s) != marker and sum(abs(a - b) for a, b in zip(px[s], backdrop)) < 90:
            ImageDraw.floodfill(work, s, marker, thresh=int(min(60, max(24, 2.5 * spread + 12))))
    mask = ImageChops.difference(work, Image.new('RGB', (w, h), marker)).convert('L').point(lambda v: 255 if v else 0)
    if not 0.2 < sum(mask.histogram()[255:]) / (w * h) < 0.9:
        return None
    mask = _opened(mask)
    return mask, head(mask)


def _backdrop_grown(rgb, step=14):
    """(mask, head) of a photo on a shaded backdrop (the CHL's and AHL's): the backdrop grown pixel by pixel while each is
    close to its neighbour, so a smooth shade counts and the edge of hair or a jersey stops it."""
    from PIL import Image
    w, h = rgb.size
    px = rgb.load()
    back = bytearray(w * h)
    todo = [(x, 0) for x in range(w)] + [(x, y) for x in (0, w - 1) for y in range(h * 2 // 5)]
    for x, y in todo:
        back[y * w + x] = 1
    while todo:
        x, y = todo.pop()
        c = px[x, y]
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not back[ny * w + nx]:
                n = px[nx, ny]
                if abs(n[0] - c[0]) + abs(n[1] - c[1]) + abs(n[2] - c[2]) < step:
                    back[ny * w + nx] = 1
                    todo.append((nx, ny))
    mask = Image.frombytes('L', (w, h), bytes(0 if b else 255 for b in back))
    if not 0.2 < sum(mask.histogram()[255:]) / (w * h) < 0.9:
        return None
    mask = _opened(mask)
    return mask, head(mask)


def prepare(photo):
    """(RGBA picture, head) of a photo, or None: a cut-out as it is, a studio photo without its backdrop, else the photo
    in a soft oval around the head (the fill's head when plausible, else where headshots have it)."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    img = photo.convert('RGBA')
    if img.getchannel('A').getextrema()[0] < 200:          # already a cut-out
        found = head(img.getchannel('A'))
        return (img, found) if found else None
    w, h = img.size
    cut = _backdrop_fill(img.convert('RGB'))
    if cut is None or not _clean(*cut):
        grown = _backdrop_grown(img.convert('RGB'))
        if grown is not None and _clean(*grown):
            cut = grown
    if cut is not None and _clean(*cut):
        img.putalpha(cut[0].filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2)))
        return img, cut[1]
    if cut is not None and _plausible(cut[1], w, h):
        top, cx, width = cut[1]
    else:
        top, cx, width = HEADSHOT[0] * h, HEADSHOT[1] * w, HEADSHOT[2] * w
    oval = Image.new('L', (w, h), 0)
    ImageDraw.Draw(oval).ellipse((cx - 1.05 * width, top - 0.3 * width, cx + 1.05 * width, top + 3.2 * width), fill=255)
    edges = Image.new('L', (w, h), 0)
    ImageDraw.Draw(edges).rectangle((w * 0.05, h * 0.04, w * 0.95, h * 1.2), fill=255)
    img.putalpha(ImageChops.multiply(oval.filter(ImageFilter.GaussianBlur(width / 7)),
                                     edges.filter(ImageFilter.GaussianBlur(w * 0.03))))
    return img, (top, cx, width)


def stand_in(pic):
    """A grey silhouette a league shows while it has no photo (spread 0.0), not a photo (the greyest real one: 13.7)."""
    from PIL import ImageChops
    pic = pic.convert('RGBA')
    mask = pic.getchannel('A').point(lambda v: 255 if v > 128 else 0)
    if mask.getbbox() is None:
        return True
    r, g, b = pic.convert('RGB').split()
    spread = ImageChops.subtract(ImageChops.lighter(ImageChops.lighter(r, g), b),
                                 ImageChops.darker(ImageChops.darker(r, g), b))
    hist = spread.histogram(mask)
    return sum(v * n for v, n in enumerate(hist)) / sum(hist) < STAND_IN


def draw(data):
    """The portrait of a downloaded photo as WebP bytes (512 x 256: the head where Legacy's portraits have it,
    the shoulders fading out), or None when no head is found or it is a stand-in."""
    from PIL import Image, ImageChops, ImageDraw
    photo = Image.open(io.BytesIO(data))
    photo.load()
    top, cx, width, last = SPOT
    prepared = prepare(photo)
    if prepared is None:
        return None
    src, (s_top, s_cx, s_width) = prepared
    scale = width / s_width
    scaled = src.resize((max(1, round(src.width * scale)), max(1, round(src.height * scale))), Image.LANCZOS)
    layer = Image.new('RGBA', SIZE, (0, 0, 0, 0))
    layer.paste(scaled, (round(cx - s_cx * scale), round(top - s_top * scale)))
    ramp = Image.new('L', SIZE, 255)
    pen = ImageDraw.Draw(ramp)
    for y in range(last + 1 - FADE, SIZE[1]):
        pen.line(((0, y), (SIZE[0], y)), fill=0 if y > last else int(255 * (last + 1 - y) / (FADE + 1)))
    layer.putalpha(ImageChops.multiply(layer.getchannel('A'), ramp))
    canvas = Image.new('RGBA', SIZE, (0, 0, 0, 0))
    canvas.alpha_composite(layer)
    if stand_in(canvas):
        return None
    out = io.BytesIO()
    canvas.crop((0, 0, SIZE[0], KEEP)).save(out, 'WEBP', quality=90, method=4)
    return out.getvalue()


def to_gnf(template, picture):
    """GNF bytes of a drawn portrait (WebP bytes) shaped like the game's own `template`: scaled to its height, the
    middle kept (as tools/build_people.py does)."""
    from PIL import Image
    t = gnf.Gnf(template).texture
    img = Image.open(io.BytesIO(picture)).convert('RGBA')
    wide = round(img.width * t.height / img.height)
    img = img.resize((wide, t.height), Image.LANCZOS)
    left = (wide - t.width) // 2
    return gnf.make(template, img.crop((left, 0, left + t.width, t.height)))


# --- the local pack -----------------------------------------------------------------------------------------------

def fetch(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={'User-Agent': nhlcom.USER_AGENT})
    with net.urlopen(req, timeout=timeout) as r:
        return r.read()


def _read_index(folder):
    try:
        with open(os.path.join(folder, INDEX), encoding='utf-8') as f:
            data = json.load(f)
        return {tuple(r[:4]): (r[4], r[5]) for r in data.get('people') or ()}, dict(data.get('failed') or {})
    except (OSError, ValueError, TypeError, IndexError):
        return {}, {}


def _write(path, data):
    with open(path + '.part', 'wb') as f:
        f.write(data)
    os.replace(path + '.part', path)


def missing(pack_links, people):
    """{person (name key, y, m, d): (first, last, link)} of the data pack's photos the people pack's `people` rows lack."""
    have = {tuple(r[:4]) for r in people or ()}
    out = {}
    for first, last, birth, url in pack_links or ():
        person = (clubdata._key(first, last), *birth)
        if person not in have and len(birth) == 3:
            out.setdefault(person, (first, last, url))
    return out


def supplement(pack_links, people, folder, template, get=fetch, today=None, limit=LIMIT, log=lambda msg: None):
    """({game path: GNF bytes}, people rows, {'drawn', 'failed', 'kept'}) of the photos the people pack lacks: drawn ones
    from `folder` (the cache), the rest downloaded (`get(url) -> bytes`) and drawn, at most `limit` new ones. Each person
    keeps the art id the index gave him; a new one takes the highest free one."""
    today = today or datetime.date.today()
    os.makedirs(folder, exist_ok=True)
    index, failed = _read_index(folder)
    want = missing(pack_links, people)
    taken = {r[4] for r in people or ()} | {a for a, _k in index.values()}
    free = (n for n in reversed(art.PEOPLE_ARTIDS) if n not in taken)

    def drawn_path(key):
        return os.path.join(folder, file_name(key) + '.webp')

    def stale(key):
        when = failed.get(key)
        try:
            return when is None or (today - datetime.date.fromisoformat(when)).days >= RETRY_DAYS
        except ValueError:
            return True

    todo = [(p, url) for p, (_f, _l, url) in sorted(want.items())
            if not os.path.isfile(drawn_path(picture_key(url))) and stale(picture_key(url))][:limit]

    def one(url):
        try:
            return draw(get(url))
        except Exception:  # noqa: BLE001 - one photo's trouble (no link, a broken picture) leaves that one out
            return None
    counts = {'drawn': 0, 'failed': 0, 'kept': 0}
    if todo:
        log(f'player photos: drawing {len(todo)} the people pack lacks...')
        with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
            for (_p, url), picture in zip(todo, pool.map(lambda t: one(t[1]), todo)):
                key = picture_key(url)
                if picture:
                    _write(drawn_path(key), picture)
                    failed.pop(key, None)
                    counts['drawn'] += 1
                else:
                    failed[key] = today.isoformat()
                    counts['failed'] += 1
    files, rows = {}, []
    for person, (_f, _l, url) in sorted(want.items()):
        key = picture_key(url)
        if not os.path.isfile(drawn_path(key)):
            continue
        artid = index[person][0] if person in index else next(free)
        index[person] = (artid, key)
        with open(drawn_path(key), 'rb') as f:
            files[art.PORTRAIT.format(artid)] = to_gnf(template, f.read())
        rows.append([*person, artid])
    counts['kept'] = len(rows) - counts['drawn']
    _write(os.path.join(folder, INDEX), json.dumps(
        {'people': [[*p, a, k] for p, (a, k) in sorted(index.items())], 'failed': dict(sorted(failed.items()))},
        indent=0).encode('utf-8'))
    return files, rows, counts


def write_local(path, files, rows, built=None):
    """The local pack at `path` (art.write_pack, `people` rows), or none when no photo is missing: an empty one goes."""
    if not files:
        if os.path.isfile(path):
            os.remove(path)
        return None
    return art.write_pack(path, LOCAL_NAME, files, SOURCE, built or datetime.date.today().isoformat(),
                          extra={'people': rows})
