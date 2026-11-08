"""The clubs' 2026 logos and centre ice, made on the player's PC (NHL Legacy's way: a small pack of source pictures,
the game's textures made on the player's own files).

NHL 19's clubs wear their 2018 logos, many clubs have rebranded since, and Update gives club slots another club
(rosterupdate: the AHL's moves, Allsvenskan, take-overs by name). The source pack (tools/build_clubart.py,
packs/clubart.zip, a core download) holds NHL 27's logo of every club of the other leagues as pictures, one lossless
WebP per kind of logo (colour, mono, the small one, the card; the folders that are only resizes of these share one),
and its centre ice where NHL 27 has one:

    pack.json  {"format": 1, "kind": "clubart", "name", "built", "source", "members": {member: sha256},
                "clubs": [{"key", "name", "league", "art", "logos": {folder: member}, "ice": member or null}]}

After an Update is saved (overtime_roster.app.update_ctl) each club slot is matched to a club of the pack by its name
as Update left it (rosterupdate._team_key, the same league first), and the club's pictures are made into the files of
the slot's own art id with gnf.make, on the game's own file as template (size, mips, format; only its header is read):
- every logo folder the game has for that art id;
- the centre ice, when the club's NHL 27 art id is another one: the slot took another club, and the ice_all pack holds
  NHL 27's ice of the art id, not of this club. A club NHL 27 has no centre ice for gets its logo on the slot's own ice
  (the ring kept, the old logo and name gone). A slot that kept its club keeps the ice the other packs give it.
The files go into the app's cache as one more art pack, LOCAL_PACK, which the patch serves after the downloaded packs
(patch.art_packs), so they win there. A second Update with the same pack, matches and game writes nothing (`made`).

Pillow is imported inside the functions only: the server imports overtime_core and stays stdlib.
"""
import collections
import datetime
import difflib
import hashlib
import io
import json
import os
import re
import zipfile

from . import art, eb, gamefiles, gnf, rosterupdate as R, workers

PACK = 'clubart.zip'
LOCAL_PACK = 'clubart_local.zip'
LOCAL_NAME = 'clubart_local'
KIND, FORMAT = 'clubart', 1
SOURCE = "NHL 27's club logos and centre ice, made on this PC"
LOGO = 'nhl/ui/kettle_assets/teamlogos/{}/t{}.gnf'
ICE = 'nhl/data/kettle/rendering/stadiums/common/ice_centerlogo_{}_cm.gnf'
# the logo folders NHL 19 has for its clubs (hutcardfreeagency, a banner with the club's name, is left alone, as
# tools/build_looks.py does for the NHL)
FOLDERS = ('extralargemono', 'extrasmall', 'extrasmallmono', 'hutcardbw', 'hutcardmedium', 'hutcardsmalllogo', 'large',
           'largemono', 'medium', 'mediumglossy', 'smallglossy')
LEAGUES = R.CLUB_LEAGUES - {0}
HEAD = 0x100                    # a GNF's header: all gnf.make needs of its template
ICE_LOGO = 0.56                 # the logo drawn on a slot's own ice: the share of the texture it fills (inside the ring)
RING = (40, 20)                 # a ring pixel: blue over red and over green by these
ICE_WHITE = (233, 235, 233)     # NHL 19's ice colour in its centre ice textures
# a slot no name matches (matches): how alike two names' keys must be (difflib ratio). Two different clubs of one
# league come to 0.67 at most (HC Lugano / HC Lausanne), the same club misspelt to 0.92 and more
SAME_ART, SPELT = 0.4, 0.85
WORD = 5                        # the shortest word of a name that tells a club apart (kloten, pinguins)


class Source:
    """The source pack: its clubs and members, read without the pictures; picture() reads and checks one."""

    def __init__(self, path):
        self.path = path
        try:
            with zipfile.ZipFile(path) as z:
                info = json.loads(z.read(art.MANIFEST).decode('utf-8'))
        except (zipfile.BadZipFile, KeyError, OSError, ValueError) as err:
            raise art.ArtError(f'{path}: {err}') from err
        if info.get('kind') != KIND or info.get('format') != FORMAT:
            raise art.ArtError(f'{path}: not a club art pack of format {FORMAT}')
        self.info = info
        self.clubs = info.get('clubs') or []
        self.members = info.get('members') or {}
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for block in iter(lambda: f.read(1 << 20), b''):
                h.update(block)
        self.sha256 = h.hexdigest()

    def picture(self, member):
        from PIL import Image
        data = art._zip_member(self.path, member)
        if hashlib.sha256(data).hexdigest() != self.members.get(member):
            raise art.ArtError(f'{self.path}: {member} does not match its checksum')
        img = Image.open(io.BytesIO(data))
        img.load()
        return img.convert('RGBA')


def _words(name):
    return {w for w in (R._team_key(p) for p in re.split(r'[\s\-/]+', name)) if len(w) >= WORD}


def _like(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def matches(teams, clubs):
    """({art id: club} of the club slots of `teams` (the saved roster's team rows: db[teams.TEAMS].rows()) a club of
    the pack names, [names of the club slots none names]). A slot's name is matched within its league first, else to
    the one club of that name in any league. A slot no name matches takes a club of its league the pack names
    otherwise, when no other slot took it (checked on a real Update: 12 slots, no wrong one):
    - the club of its own art id, the names alike (SAME_ART): NHL 27 kept most of NHL 19's art ids and renamed or
      misspelt the club (Djurgården Hockey, Malmӧ with a Cyrillic letter, KooKoo Kouvala, Fischtown Pinguins);
    - else the one club whose name is spelt nearly the same (SPELT), its art id moved (CEZ Motor Ceske Budejovice);
    - else the one club sharing a word of the slot's name that no other club of the pack has (a take-over: Update's
      EHC Kloten on Rapperswil's slot, Kloten Flyers in NHL 27)."""
    by_key = collections.defaultdict(list)
    for club in clubs:
        by_key[club['key']].append(club)
    common = collections.Counter(w for club in clubs for w in _words(club['name']))
    found, rest = {}, []
    for r in teams:
        if r['league'] not in LEAGUES or not r['active'] or r['artid'] in found:
            continue
        hits = by_key.get(R._team_key(r['teamname']), [])
        same = [c for c in hits if c['league'] == r['league']]
        club = same[0] if len(same) == 1 else hits[0] if len(hits) == 1 else None
        if club is None:
            rest.append(r)
        else:
            found[r['artid']] = club
    taken = {id(c) for c in found.values()}
    missing = []
    for r in rest:
        if r['artid'] in found:
            continue
        key = R._team_key(r['teamname'])
        free = [c for c in clubs if c['league'] == r['league'] and id(c) not in taken]
        own = [c for c in free if c['art'] == r['artid'] and _like(key, c['key']) >= SAME_ART]
        spelt = [c for c in free if _like(key, c['key']) >= SPELT]
        words = _words(r['teamname'])
        shared = [c for c in free if any(common[w] == 1 for w in words & _words(c['name']))]
        club = next((cs[0] for cs in (own, spelt, shared) if len(cs) == 1), None)
        if club is None:
            missing.append(r['teamname'])
        else:
            found[r['artid']] = club
            taken.add(id(club))
    return found, missing


def plan(found, have):
    """{game path: (club, member or None)} of the files to make: the logo folders the game has (`have`) for each slot's
    art id, and its centre ice when the club's NHL 27 art id is another (member None: the logo drawn on the slot's
    own ice)."""
    out = {}
    for art_id, club in sorted(found.items()):
        for folder, member in sorted((club.get('logos') or {}).items()):
            path = LOGO.format(folder, art_id)
            if folder in FOLDERS and path in have:
                out[path] = (club, member)
        path = ICE.format(art_id)
        if club['art'] != art_id and path in have and club.get('logos', {}).get('large'):
            out[path] = (club, club.get('ice'))
    return out


def fit(img, w, h):
    """`img` (RGBA) inside w x h, aspect kept, centred on a clear ground (tools/build_looks.fit)."""
    from PIL import Image
    img = img.convert('RGBA')
    if abs(img.width / img.height - w / h) < 0.01:
        return img.resize((w, h), Image.LANCZOS)
    s = min(w / img.width, h / img.height)
    small = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    out.alpha_composite(small, ((w - small.width) // 2, (h - small.height) // 2))
    return out


def on_ice(ice, logo):
    """The slot's own centre ice with another club's logo: the blue ring kept, everything else the ice's white (its
    alpha kept: the clear corners stay clear), the logo fitted in the ring."""
    from PIL import Image, ImageChops
    ice = ice.convert('RGBA')
    r, g, b, a = ice.split()
    ring = ImageChops.multiply(ImageChops.subtract(b, r).point(lambda v: 255 if v > RING[0] else 0),
                               ImageChops.subtract(b, g).point(lambda v: 255 if v > RING[1] else 0))
    plain = Image.new('RGBA', ice.size, ICE_WHITE + (255,))
    plain.putalpha(a)
    out = Image.composite(ice, plain, ring)
    side = round(min(ice.size) * ICE_LOGO)
    small = fit(logo, side, side)
    out.alpha_composite(small, ((ice.width - side) // 2, (ice.height - side) // 2))
    return out


_ERRORS = (art.ArtError, gnf.GnfError, OSError, ValueError)


def _make(ice, raw, pic):
    """One file (on a worker): the centre ice with the logo on it, or the logo fitted to the game's own size."""
    if ice:
        return gnf.make(raw, on_ice(gnf.to_image(raw), pic))
    t = gnf.Gnf(raw).texture
    return gnf.make(raw, fit(pic, t.width, t.height))


def _key(source, targets, game_dir):
    from PIL import __version__ as pillow
    arcs = []
    for big in gamefiles.archives(game_dir):
        try:
            arcs.append((os.path.basename(big), os.path.getsize(big)))
        except OSError:
            arcs.append((os.path.basename(big), None))
    text = json.dumps([source.sha256, pillow, gnf.ENCODER, arcs,
                       sorted((p, c['art'], m) for p, (c, m) in targets.items())])
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _made(path):
    try:
        with zipfile.ZipFile(path) as z:
            return json.loads(z.read(art.MANIFEST).decode('utf-8')).get('made')
    except (zipfile.BadZipFile, KeyError, OSError, ValueError):
        return None


def compose(source, teams, game_dir, out_path, log=None, today=None):
    """Make the club art of the saved roster's team rows `teams` from `source` (a Source) on the game's own files into
    the local pack `out_path` (removed when no file is to be made). {'clubs', 'files', 'drawn', 'missing', 'kept'}:
    clubs matched, files made, centre ices drawn from a logo, club slots no club of the pack names, and whether the
    pack as it was is kept (nothing changed since the last Update)."""
    say = log or (lambda m: None)
    found, missing = matches(teams, source.clubs)
    where = gamefiles.winning(game_dir)
    targets = plan(found, where)
    counts = {'clubs': len(found), 'files': len(targets), 'drawn': sum(1 for _c, m in targets.values() if m is None),
              'missing': missing, 'kept': False}
    if not targets:
        if os.path.isfile(out_path):
            os.remove(out_path)
        return counts
    key = _key(source, targets, game_dir)
    if os.path.isfile(out_path) and _made(out_path) == key:
        counts['kept'] = True
        return counts
    pictures, files = {}, {}

    def picture(member):
        if member not in pictures:
            pictures[member] = source.picture(member)
        return pictures[member]

    by_arc = collections.defaultdict(list)
    for p in targets:
        by_arc[where[p]].append(p)

    def jobs():
        """(path, (ice?, the game's file, the picture)) of each file, read here in order (workers.ordered)."""
        for big, ps in sorted(by_arc.items()):
            with eb.EbArchive(big) as arc:
                for p in sorted(ps):
                    club, member = targets[p]
                    try:
                        if member is None:
                            yield p, (True, arc.read(p), picture(club['logos']['large']).copy())
                        else:
                            head = arc.head(p, HEAD)
                            if gnf.Gnf(head).data_off > len(head):
                                head = arc.read(p)
                            yield p, (False, head, picture(member).copy())
                    except _ERRORS as err:
                        yield p, err
    for p, data, err in workers.ordered(jobs(), _make, _ERRORS):
        if err is not None:
            say(f'club art: {p} not made ({err})')
        else:
            files[p] = data
    if not files:
        return counts
    built = (today or datetime.date.today()).isoformat()
    art.write_pack(out_path, LOCAL_NAME, files, source=SOURCE, built=built,
                   extra={'made': key, 'clubs': {str(a): c['name'] for a, c in sorted(found.items())}})
    counts['files'] = len(files)
    return counts
