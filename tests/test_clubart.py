"""The clubs' 2026 logos and centre ice made on this PC (overtime_core.clubart): matching club slots by name, which
files are made, the slot's own ice with another club's logo, the local pack the patch serves last, and eb.head (a
texture's header without unpacking the whole file). No game, no network: synthetic GNF templates in a temp game
folder, a source pack written here."""
import hashlib
import io
import json
import os
import struct
import zipfile
import zlib

import pytest

from overtime_core import art, clubart, eb, gnf, rosterupdate as R
from overtime_roster.app import patch, sources
from test_gnf import template

LEAGUE, OTHER, THIRD = sorted(clubart.LEAGUES)[:3]
LOGO, ICE = clubart.LOGO, clubart.ICE


def team(index, art_id, name, league=LEAGUE, active=1):
    return {'index': index, 'league': league, 'active': active, 'artid': art_id, 'teamname': name}


def club(name, art_id, league=LEAGUE, logos=('large',), ice=True):
    return {'key': R._team_key(name), 'name': name, 'league': league, 'art': art_id,
            'logos': {f: f'c/{art_id}/{f}.webp' for f in logos}, 'ice': f'c/{art_id}/ice.webp' if ice else None}


def source_pack(path, clubs, pictures):
    """A club art source pack as tools/build_clubart.py writes it: `pictures` {member: Pillow picture}."""
    members = {}
    for member, img in pictures.items():
        out = io.BytesIO()
        img.save(out, 'WEBP', lossless=True)
        members[member] = out.getvalue()
    info = {'format': clubart.FORMAT, 'kind': clubart.KIND, 'name': 'clubart', 'built': '2026-11-03', 'source': 'test',
            'clubs': clubs, 'members': {m: hashlib.sha256(d).hexdigest() for m, d in members.items()}}
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(art.MANIFEST, json.dumps(info))
        for member, data in members.items():
            z.writestr(member, data)
    return str(path)


def chunkzip(data, csize):
    """`data` as the game's chunkzip blob (eb.py's layout), every chunk deflated."""
    chunks = [data[i:i + csize] for i in range(0, len(data), csize)]
    out = bytearray(b'chunkzip' + struct.pack('>5I', 2, len(data), csize, len(chunks), 16))
    for chunk in chunks:
        z = zlib.compressobj(9, zlib.DEFLATED, -15)
        packed = z.compress(chunk) + z.flush()
        while (len(out) + 8) % 16:
            out += b'\0'
        out += struct.pack('>II', len(packed), 1) + packed
    return bytes(out)


@pytest.fixture
def pil():
    return pytest.importorskip('PIL.Image')


# --- eb.head: a texture's header without the rest ---------------------------------------------------------------------
def test_head_unpacks_only_the_chunks_it_needs(tmp_path):
    data = bytes((i * 7 + i // 300) % 251 for i in range(3 * 0x1000 + 100))
    blob = chunkzip(data, 0x1000)
    big = str(tmp_path / 'inxp_10.big')
    eb.new_archive(big, {'nhl/packed.gnf': blob, 'nhl/raw.gnf': data})
    with eb.EbArchive(big) as arc:
        assert arc.read('nhl/packed.gnf') == data
        assert arc.head('nhl/packed.gnf', 0x100) == data[:0x100]
        assert arc.head('nhl/packed.gnf', 0x1800) == data[:0x1800]          # over a chunk's end
        assert arc.head('nhl/raw.gnf', 0x100) == data[:0x100]
    assert len(eb.unchunk(blob, 0x100)) == 0x1000                           # the first chunk only
    assert eb.unchunk(blob) == data


# --- matching club slots to the pack's clubs ---------------------------------------------------------------------------
def test_slots_are_matched_by_name_in_their_league_first():
    clubs = [club('Henderson Silver Knights', 101), club('HC Davos', 300, league=OTHER),
             club('Lions', 400, league=OTHER), club('Lions', 401, league=THIRD)]
    teams = [team(0, 0, 'Anaheim Ducks', league=0),                    # the NHL: never
             team(1, 101, 'Henderson Silver Knights'),
             team(2, 102, 'HC Davos'),                                  # in another league, the only one of that name
             team(3, 103, 'Lions'),                                     # two in other leagues: none
             team(4, 104, 'Lions', league=OTHER),                       # the one of its own league
             team(5, 105, 'Henderson Silver Knights', active=0),        # not active
             team(6, 101, 'Somebody Else')]                             # its art id is matched already
    found, missing = clubart.matches(teams, clubs)
    assert {a: c['art'] for a, c in found.items()} == {101: 101, 102: 300, 104: 400}
    assert missing == ['Lions']


def test_a_slot_no_name_matches_takes_its_own_art_id_a_spelling_or_a_word_of_its_name():
    # names as a real Update leaves them and as NHL 27 has the clubs
    clubs = [club('Djurgården Hockey', 71), club('CEZ Motor Ceske Budejovice', 297), club('Kloten Flyers', 327),
             club('Rapperswil-Jona Lakers', 328), club('HC Lugano', 326), club('Krefeld Pinguine', 191),
             club('Kölner Haie', 190, league=OTHER)]
    teams = [team(1, 71, 'Djurgårdens IF'),                 # its own art id, the names alike
             team(2, 292, 'Motor České Budějovice'),         # the art id moved, the same club spelt nearly the same
             team(3, 328, 'EHC Kloten'),                     # Update's take-over: Rapperswil's art id, a word of its own
             team(4, 330, 'HC Lausanne'),                    # near HC Lugano, but two clubs are never that alike
             team(5, 191, 'Cardiff Devils'),                 # another club's art id, nothing alike
             team(6, 190, 'Kölner Haie'),                    # by name, in another league
             team(7, 192, 'Krefeld Pinguine Lakers')]        # a word of two clubs: none (Krefeld Pinguine is free
    found, missing = clubart.matches(teams, clubs)          # but Lakers is Rapperswil's too, and two hits are none)
    assert {a: c['name'] for a, c in found.items()} == {
        71: 'Djurgården Hockey', 292: 'CEZ Motor Ceske Budejovice', 328: 'Kloten Flyers', 190: 'Kölner Haie'}
    assert missing == ['HC Lausanne', 'Cardiff Devils', 'Krefeld Pinguine Lakers']


def test_plan_makes_the_logos_the_game_has_and_the_ice_of_a_slot_that_took_another_club():
    same = club('Henderson Silver Knights', 101, logos=('large', 'extrasmall', 'hutcardfreeagency'))
    took = club('HC Davos', 300, ice=False)
    far = club('Lions', 400)
    have = {LOGO.format('large', 101), LOGO.format('extrasmall', 101), LOGO.format('hutcardfreeagency', 101),
            ICE.format(101), LOGO.format('large', 102), ICE.format(102), LOGO.format('large', 104)}
    got = clubart.plan({101: same, 102: took, 104: far}, have)
    assert got == {LOGO.format('large', 101): (same, 'c/101/large.webp'),
                   LOGO.format('extrasmall', 101): (same, 'c/101/extrasmall.webp'),
                   LOGO.format('large', 102): (took, 'c/300/large.webp'),
                   ICE.format(102): (took, None),                     # no ice in the pack: its logo on the slot's ice
                   LOGO.format('large', 104): (far, 'c/400/large.webp')}   # the game has no ice for 104


def test_the_slots_own_ice_keeps_its_ring_and_loses_the_old_logo(pil):
    from PIL import ImageDraw
    ice = pil.new('RGBA', (64, 64), (0, 0, 0, 0))
    pen = ImageDraw.Draw(ice)
    pen.ellipse((1, 1, 63, 63), fill=(240, 241, 240, 255))
    pen.ellipse((9, 9, 55, 55), fill=(20, 60, 200, 255))                # the ring: radius 20-23
    pen.ellipse((12, 12, 52, 52), fill=(240, 241, 240, 255))
    ice.putpixel((59, 32), (200, 20, 20, 255))                         # the old club's name outside the ring
    ice.putpixel((51, 32), (200, 20, 20, 255))                         # its old logo inside the ring
    out = clubart.on_ice(ice, pil.new('RGBA', (40, 40), (10, 200, 10, 255)))
    assert out.getpixel((32, 32)) == (10, 200, 10, 255)                # the new logo
    assert out.getpixel((10, 32)) == (20, 60, 200, 255)                # the ring
    assert out.getpixel((59, 32)) == clubart.ICE_WHITE + (255,)
    assert out.getpixel((51, 32)) == clubart.ICE_WHITE + (255,)
    assert out.getpixel((0, 0))[3] == 0                                # the corners stay clear


# --- compose: the local pack ----------------------------------------------------------------------------------------
@pytest.fixture
def world(tmp_path, pil):
    """A game with logos of art 101 (large in both archives: the patch archive's, 128 px, wins) and 102 (large and a
    centre ice), and a source pack: Henderson (art 101, its own slot) and Davos (NHL 27 art 300, on slot 102, no ice)."""
    big = tmp_path / 'NHL 19' / 'databigs'
    big.mkdir(parents=True)
    ice = pil.new('RGBA', (64, 64), (240, 241, 240, 255))
    eb.new_archive(str(big / 'inxp_10.big'), {
        LOGO.format('large', 101): template(64, 64, 'BC7'), LOGO.format('extrasmall', 101): template(32, 32, 'BC3'),
        LOGO.format('large', 102): template(64, 64, 'BC7'), ICE.format(102): gnf.make(template(64, 64, 'BC3'), ice)})
    eb.new_archive(str(big / 'patch_inxp_56.big'), {LOGO.format('large', 101): template(128, 128, 'BC7')})
    henderson = club('Henderson Silver Knights', 101, logos=('large', 'extrasmall'))
    davos = club('HC Davos', 300, league=OTHER, ice=False)
    pictures = {'c/101/large.webp': pil.new('RGBA', (256, 256), (180, 20, 30, 255)),
                'c/101/extrasmall.webp': pil.new('RGBA', (64, 64), (180, 20, 30, 255)),
                'c/101/ice.webp': pil.new('RGBA', (64, 64), (240, 241, 240, 255)),
                'c/300/large.webp': pil.new('RGBA', (256, 256), (230, 200, 20, 255))}
    source = clubart.Source(source_pack(tmp_path / clubart.PACK, [henderson, davos], pictures))
    teams = [team(1, 101, 'Henderson Silver Knights'), team(2, 102, 'HC Davos')]
    return {'game': str(tmp_path / 'NHL 19'), 'source': source, 'teams': teams,
            'out': str(tmp_path / 'cache' / clubart.LOCAL_PACK)}


def near(colour, want, slack=12):
    return all(abs(a - b) <= slack for a, b in zip(colour, want))


def test_compose_makes_the_files_on_the_games_own_templates(world):
    os.makedirs(os.path.dirname(world['out']))
    counts = clubart.compose(world['source'], world['teams'], world['game'], world['out'])
    assert counts == {'clubs': 2, 'files': 4, 'drawn': 1, 'missing': [], 'kept': False}
    files = {k: v.read() for k, v in art.load_pack(world['out']).files.items()}
    assert set(files) == {LOGO.format('large', 101), LOGO.format('extrasmall', 101), LOGO.format('large', 102),
                          ICE.format(102)}
    assert gnf.Gnf(files[LOGO.format('large', 101)]).texture.width == 128       # the archive that wins
    assert gnf.Gnf(files[LOGO.format('large', 101)]).texture.fmt == 'BC3'       # BC7 is written as BC3
    assert near(gnf.to_image(files[LOGO.format('large', 102)]).getpixel((32, 32)), (230, 200, 20, 255))
    assert near(gnf.to_image(files[ICE.format(102)]).getpixel((32, 32)), (230, 200, 20, 255))   # Davos on the ice
    assert near(gnf.to_image(files[ICE.format(102)]).getpixel((2, 32)), clubart.ICE_WHITE + (255,))


def test_compose_again_keeps_the_pack_and_follows_the_roster(world):
    os.makedirs(os.path.dirname(world['out']))
    clubart.compose(world['source'], world['teams'], world['game'], world['out'])
    before = open(world['out'], 'rb').read()
    again = clubart.compose(world['source'], world['teams'], world['game'], world['out'])
    assert again['kept'] and open(world['out'], 'rb').read() == before
    teams = [world['teams'][0], team(2, 102, 'Nobody Known')]
    counts = clubart.compose(world['source'], teams, world['game'], world['out'])
    assert counts['missing'] == ['Nobody Known'] and counts['files'] == 2 and not counts['kept']
    assert set(art.load_pack(world['out']).files) == {LOGO.format('large', 101), LOGO.format('extrasmall', 101)}
    gone = clubart.compose(world['source'], [team(1, 101, 'Nobody'), team(2, 102, 'Nobody Known')], world['game'],
                           world['out'])
    assert gone['clubs'] == 0 and not os.path.exists(world['out'])          # nothing to make: no pack left


def test_a_source_pack_member_that_was_changed_is_refused(world, tmp_path):
    path = world['source'].path
    with zipfile.ZipFile(path) as z:
        items = {n: z.read(n) for n in z.namelist()}
    items['c/300/large.webp'] = items['c/101/large.webp']
    bad = tmp_path / 'bad.zip'
    with zipfile.ZipFile(bad, 'w') as z:
        for n, d in items.items():
            z.writestr(n, d)
    with pytest.raises(art.ArtError, match='checksum'):
        clubart.Source(str(bad)).picture('c/300/large.webp')
    with zipfile.ZipFile(tmp_path / 'other.zip', 'w') as z:
        z.writestr(art.MANIFEST, json.dumps({'format': 1, 'files': {}}))
    with pytest.raises(art.ArtError, match='club art'):
        clubart.Source(str(tmp_path / 'other.zip'))


# --- the app: Update and Patch make it, the patch serves it last ------------------------------------------------------
@pytest.fixture
def places(tmp_path, monkeypatch):
    monkeypatch.delenv(patch.ART_ENV, raising=False)
    monkeypatch.setattr(sources, 'BUILD_PACKS', str(tmp_path / 'exe-packs'))
    monkeypatch.setattr(sources, 'REPO_PACKS', str(tmp_path / 'repo-packs'))
    cache = tmp_path / 'cache'
    cache.mkdir()
    return cache


def test_the_patch_serves_the_club_logos_last(places, monkeypatch, tmp_path):
    def fake(tag):
        return b'GNF ' + tag.encode().ljust(60, b'.')
    path = LOGO.format('large', 101)
    art.write_pack(str(places / patch.LOOKS32_PACK), 'looks32', {path: fake('2018')})
    art.write_pack(str(places / patch.ICE_PACK), 'ice_all', {ICE.format(102): fake('ice of art 102')})
    art.write_pack(str(places / patch.LOCAL_CLUBART_PACK), clubart.LOCAL_NAME, {path: fake('2026')})
    packs, problems = patch.art_packs(str(places), photos=False)
    assert [p.name for p in packs] == ['looks32', 'ice_all', clubart.LOCAL_NAME] and not problems
    assert patch.local_clubart(str(places)) == str(places / patch.LOCAL_CLUBART_PACK)
    assert patch.CLUBART_PACK not in patch.ART_PACKS                    # the source pack is never served itself
    monkeypatch.setenv(patch.ART_ENV, str(tmp_path / 'elsewhere'))     # the packs come from another folder alone
    assert patch.local_clubart(str(places)) is None


def test_make_clubart_never_stops_an_update(places, world):
    said = []
    assert patch.make_clubart(world['teams'], world['game'], str(places), log=said.append) is None   # no pack: nothing
    (places / patch.CLUBART_PACK).write_bytes(open(world['source'].path, 'rb').read())
    counts = patch.make_clubart(world['teams'], world['game'], str(places), log=said.append)
    assert counts['clubs'] == 2 and os.path.isfile(places / patch.LOCAL_CLUBART_PACK) and not said
    (places / patch.CLUBART_PACK).write_bytes(b'PK broken')
    assert patch.make_clubart(world['teams'], world['game'], str(places), log=said.append) is None
    assert said and said[-1].startswith('club logos: not made')


# --- v0.50.1: Update never skips the logos without a word --------------------------------------------------------------
def test_update_downloads_the_missing_club_logo_pack_or_says_it_skipped(places, monkeypatch):
    import types
    from overtime_roster.app import packdownload, update_ctl
    said, logs, got = [], [], []
    me = types.SimpleNamespace(ctl=types.SimpleNamespace(say=lambda t, tone='info': said.append(t),
                                                         host=types.SimpleNamespace(log=logs.append), game_dir='G'))
    run = lambda rec: update_ctl.UpdateCtl._clubart_pack(me, str(places), rec) or rec   # noqa: E731

    def download(names, cache, game_dir=None, **kw):
        got.append(names)
        (places / patch.CLUBART_PACK).write_bytes(b'PK')
        return [(names[0], True, 'Downloaded.')]
    monkeypatch.setattr(packdownload, 'download', download)
    assert run({'offline': True}) == {'offline': True, 'clubart_skipped': 'the club logo pack is not downloaded and '
                                                                          'the update ran offline'} and not got
    assert 'clubart_skipped' not in run({}) and got == [[patch.CLUBART_PACK]]            # online: downloaded first
    assert said == ['Downloading the club logo pack...'] and logs == ['club logo pack: Downloaded.']
    assert run({}) == {} and len(got) == 1                                              # here: no download
    (places / patch.CLUBART_PACK).unlink()
    monkeypatch.setattr(packdownload, 'download', lambda names, cache, game_dir=None, **kw: [
        (names[0], False, packdownload.OFFLINE)])
    assert run({})['clubart_skipped'] == f'the club logo pack is not downloaded ({packdownload.OFFLINE})'
    monkeypatch.setenv(patch.ART_ENV, str(places / 'elsewhere'))                       # the packs of that folder alone
    assert run({})['clubart_skipped'] == 'the club logo pack is not in the packs folder'
    monkeypatch.setenv(patch.ART_ENV, 'off')                                            # no art: nothing to say
    assert run({}) == {}


def test_audit_tells_name_matches_from_fallbacks_and_slots_that_keep_the_game_logo():
    pytest.importorskip('tools.audit_clubart')    # not in the public tree
    from tools import audit_clubart
    clubs = [club('Djurgården Hockey', 71), club('HC Lugano', 326)]
    slots = [team(1, 71, 'Djurgårdens IF'), team(2, 326, 'HC Lugano'), team(3, 191, 'Cardiff Devils')]
    done, lost = audit_clubart.audit(slots, clubs)
    assert [(r['teamname'], c['name'], how) for r, c, how in done] == [
        ('Djurgårdens IF', 'Djurgården Hockey', 'fallback'), ('HC Lugano', 'HC Lugano', 'name')]
    assert [r['teamname'] for r in lost] == ['Cardiff Devils']
