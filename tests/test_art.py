"""The art layer: packs, routing into new archives per family, apply / re-apply / undo byte-exact."""
import hashlib
import json
import os
import zipfile

import pytest

from overtime_core import art, clubdata, eb, overlay

IDLE = {'running': lambda: False}
LOGO = 'nhl/ui/kettle_assets/teamlogos/large/t22.gnf'
NEW_LOGO = 'nhl/ui/kettle_assets/teamlogos/large/t10499.gnf'
KIT = 'nhl/data/kettle/rendering/characters/player/jersey_adidas_arizona_home_cm.gnf'
PORTRAIT = 'nhl/ui/kettle_assets/playerportraits/p1.gnf'


def gnf(tag):
    return b'GNF ' + tag.encode().ljust(60, b'.')


def tree(top):
    out = {}
    for d, _dirs, files in os.walk(top):
        for n in files:
            with open(os.path.join(d, n), 'rb') as f:
                out[os.path.relpath(os.path.join(d, n), top)] = hashlib.sha256(f.read()).hexdigest()
    return out


@pytest.fixture
def game(tmp_path):
    """A game folder with two archives per family: the stock logo and portrait in the UI family (the portrait in the
    3D family too), the stock kit in the 3D family."""
    big = tmp_path / 'NHL 19' / 'databigs'
    big.mkdir(parents=True)
    eb.new_archive(str(big / 'inxp_10.big'), {LOGO: gnf('stock logo'), PORTRAIT: gnf('stock face'),
                                              'nhl/ui/kettle_assets/teamlogos/large/t1.gnf': gnf('t1')})
    eb.new_archive(str(big / 'patch_inxp_56.big'), {'nhl/data/common/x.db': b'db'})
    eb.new_archive(str(big / 'game_90.big'), {KIT: gnf('stock kit'), PORTRAIT: gnf('stock face 3d')})
    eb.new_archive(str(big / 'patch_game_96.big'), {'nhl/data/y.bin': b'y'})
    eb.new_archive(str(big / 'boot.big'), {'nhl/ui/z.lua': b'z'})
    return str(tmp_path / 'NHL 19')


def pack(tmp_path, name, files):
    path = str(tmp_path / f'{name}.zip')
    art.write_pack(path, name, files, source='test', built='2026-10-18')
    return art.load_pack(path)


def test_pack_round_trip_and_checks(tmp_path):
    files = {LOGO: gnf('utah'), KIT: gnf('utah kit')}
    p = pack(tmp_path, 'looks', files)
    assert p.files == files and p.name == 'looks' and p.info['source'] == 'test'
    again = str(tmp_path / 'again.zip')
    art.write_pack(again, 'looks', dict(reversed(list(files.items()))), source='test', built='2026-10-18')
    with open(again, 'rb') as a, open(p.path, 'rb') as b:
        assert a.read() == b.read()  # the same files make the same zip
    with pytest.raises(art.ArtError):
        art.write_pack(str(tmp_path / 'bad.zip'), 'x', {'NHL/UPPER.gnf': gnf('x')})
    with pytest.raises(art.ArtError):
        art.write_pack(str(tmp_path / 'bad.zip'), 'x', {LOGO: b'DDS not a gnf'})
    bad = str(tmp_path / 'tampered.zip')
    with zipfile.ZipFile(bad, 'w') as z:
        z.writestr(art.MANIFEST, json.dumps({'format': 1, 'files': {LOGO: '0' * 64}}))
        z.writestr(LOGO, gnf('utah'))
    with pytest.raises(art.ArtError, match='checksum'):
        art.load_pack(bad)


def test_route_into_new_archives_per_family(game):
    files = {LOGO: gnf('utah'), NEW_LOGO: gnf('seattle'), KIT: gnf('utah kit'), PORTRAIT: gnf('face')}
    assert art.targets(game) == {'inxp': 'databigs/patch_inxp_57.big', 'game': 'databigs/patch_game_97.big'}
    edits, record = art.edits(game, files)
    inxp = os.path.join(game, 'databigs', 'patch_inxp_57.big')
    gam = os.path.join(game, 'databigs', 'patch_game_97.big')
    assert set(edits[inxp]) == {LOGO, NEW_LOGO, PORTRAIT}  # the new logo goes where its folder is
    assert set(edits[gam]) == {KIT, PORTRAIT}  # a texture in both families goes into both
    assert record == {'game': {'archive': 'databigs/patch_game_97.big', 'archives': ['databigs/patch_game_97.big'],
                               'textures': 2},
                      'inxp': {'archive': 'databigs/patch_inxp_57.big', 'archives': ['databigs/patch_inxp_57.big'],
                               'textures': 3}}
    with pytest.raises(art.ArtError, match='unknown'):
        art.edits(game, {'nhl/ui/kettle_assets/nowhere/t1.gnf': gnf('x')})
    assert art.family('patch_inxp_56.big') == 'inxp' and art.family('game_90.big') == 'game'
    assert art.family('boot.big') == 'boot'


def test_art_layer_apply_reapply_undo_byte_exact(game, tmp_path):
    before_game = tree(game)
    files = {LOGO: gnf('utah'), NEW_LOGO: gnf('seattle'), KIT: gnf('utah kit')}
    looks = pack(tmp_path, 'looks', files)
    st = overlay.apply(game, ('art',), art=[looks], **IDLE)
    mods = overlay.overlay_dir(game)
    assert sorted(st['files']) == ['databigs/patch_game_97.big', 'databigs/patch_inxp_57.big']
    assert all(r['new'] for r in st['files'].values())
    assert st['layers']['art']['packs'][0]['name'] == 'looks' and st['layers']['art']['textures'] == 3
    with eb.EbArchive(os.path.join(mods, 'databigs', 'patch_inxp_57.big')) as arc:
        assert sorted(arc.entries) == sorted([LOGO, NEW_LOGO])
        assert arc.read(NEW_LOGO) == files[NEW_LOGO]
    with eb.EbArchive(os.path.join(mods, 'databigs', 'patch_game_97.big')) as arc:
        assert list(arc.entries) == [KIT] and arc.read(KIT) == files[KIT]
    assert overlay.status(game)['problems'] == []
    served = tree(mods)
    same = lambda a, b: {**a, 'overtime-patch.json': 0} == {**b, 'overtime-patch.json': 0}  # it holds the time, to the second

    # another apply without packs keeps the served art, byte for byte
    st2 = overlay.apply(game, ('art',), **IDLE)
    assert same(tree(mods), served) and st2['layers']['art']['packs'] == st['layers']['art']['packs']

    # a later pack wins on a shared path
    faces = pack(tmp_path, 'faces', {LOGO: gnf('utah v2')})
    overlay.apply(game, ('art',), art=[looks, faces], **IDLE)
    with eb.EbArchive(os.path.join(mods, 'databigs', 'patch_inxp_57.big')) as arc:
        assert arc.read(LOGO) == gnf('utah v2')

    # dropping the layer removes its archives
    overlay.apply(game, ('art',), art=[looks], **IDLE)
    assert same(tree(mods), served)

    assert sorted(overlay.undo(game, **IDLE)) == sorted(
        os.path.join(mods, 'databigs', n) for n in ('patch_game_97.big', 'patch_inxp_57.big'))
    assert not os.path.exists(mods)
    assert tree(game) == before_game


def test_art_layer_without_pack_is_refused(game):
    with pytest.raises(overlay.PatchError, match='no art pack'):
        overlay.apply(game, ('art',), **IDLE)


def test_status_flags_a_game_archive_of_the_same_name(game, tmp_path):
    overlay.apply(game, ('art',), art=[pack(tmp_path, 'looks', {LOGO: gnf('utah')})], **IDLE)
    eb.new_archive(os.path.join(game, 'databigs', 'patch_inxp_57.big'), {'nhl/a.bin': b'a'})
    assert any('has an archive of this name' in p for p in overlay.status(game)['problems'])
    st = overlay.apply(game, ('art',), **IDLE)  # the art moves one number up
    assert list(st['files']) == ['databigs/patch_inxp_58.big']
    assert not os.path.exists(os.path.join(overlay.overlay_dir(game), 'databigs', 'patch_inxp_57.big'))
    overlay.undo(game, **IDLE)


def test_patch_switch_finds_packs_and_keeps_the_layer(game, tmp_path, monkeypatch):
    from overtime_roster.app import patch
    folder = tmp_path / 'packs'
    folder.mkdir()
    monkeypatch.setenv(patch.ART_ENV, str(folder))
    from overtime_roster.app import packdownload  # the photos' fit to the roster: test_packdownload
    monkeypatch.setattr(packdownload, 'photos_fit', lambda path, game_dir=None: {'fits': None})
    assert patch.art_packs() == ([], [])
    art.write_pack(str(folder / 'looks.zip'), 'looks', {LOGO: gnf('utah')})
    (folder / 'looks32.zip').write_bytes(b'not a zip')
    art.write_pack(str(folder / 'photos.zip'), 'photos', {PORTRAIT: gnf('nhl.com face'), LOGO: gnf('not this')})
    assert patch.art_found() == ['looks32.zip', 'photos.zip', 'looks.zip']
    packs, problems = patch.art_packs()
    assert [p.name for p in packs] == ['photos', 'looks'] and len(problems) == 1
    assert art.merge(packs)[LOGO] == gnf('utah')   # looks.zip is laid last, so it wins
    assert 'art' not in patch.layers_for(game)
    assert patch.layers_for(game, art=True)[-1] == 'art'
    overlay.apply(game, ('art',), art=packs, **IDLE)
    assert 'art' in patch.layers_for(game)  # served: kept
    assert 'art' not in patch.layers_for(game, no_art=True)
    monkeypatch.setenv(patch.ART_ENV, 'off')
    assert patch.art_places() == []
    overlay.undo(game, **IDLE)


def test_kits_download_pack_has_its_own_switch(game, tmp_path, monkeypatch):
    from overtime_roster.app import patch
    folder = tmp_path / 'packs'
    folder.mkdir()
    monkeypatch.setenv(patch.ART_ENV, str(folder))
    art.write_pack(str(folder / 'looks.zip'), 'looks', {LOGO: gnf('utah')})
    base = gnf('stock kit')
    art.write_pack(str(folder / 'kits.zip'), 'kits', {KIT: base[:16] + b'K' * 16 + base[32:]}, bases={KIT: base})
    assert patch.art_found() == ['kits.zip', 'looks.zip']
    layers = []
    packs = patch.art_layer({'art': True}, layers, game_dir=game)
    assert [p.name for p in packs] == ['kits', 'looks'] and layers == ['art']
    assert [p.name for p in patch.art_layer({'art': True, 'kits': False}, [], game_dir=game)] == ['looks']
    problems = []
    packs = patch.art_layer({'art': True}, [], log=problems.append)   # no game folder: the delta pack is skipped
    assert [p.name for p in packs] == ['looks'] and 'game folder' in problems[0]


def test_art_switch_on_off_and_unpatch_byte_exact(game, tmp_path, monkeypatch):
    from overtime_roster.app import patch
    folder = tmp_path / 'packs'
    folder.mkdir()
    monkeypatch.setenv(patch.ART_ENV, str(folder))
    before_game, layers = tree(game), ['text']
    assert patch.art_layer({}, layers) is None and layers == ['text']  # on, no packs: nothing to add
    assert patch.art_found() == []
    art.write_pack(str(folder / 'looks.zip'), 'looks', {LOGO: gnf('utah'), KIT: gnf('kit')})
    assert patch.art_found() == ['looks.zip']
    packs = patch.art_layer({'art': True}, layers)
    assert layers == ['text', 'art'] and [p.name for p in packs] == ['looks']
    overlay.apply(game, ('art',), art=packs, **IDLE)
    mods = overlay.overlay_dir(game)
    assert os.path.isfile(os.path.join(mods, 'databigs', 'patch_inxp_57.big'))

    # on without packs: the served art stays (None lets overlay keep it)
    monkeypatch.setenv(patch.ART_ENV, str(tmp_path / 'empty'))
    layers = ['art']
    assert patch.art_layer({'art': True}, layers) is None and layers == ['art']

    # off: the layer leaves, and Apply with the rest takes its archives away
    layers = ['art']
    assert patch.art_layer({'art': False}, layers) is None and layers == []
    overlay.apply(game, ('art',), art=packs, **IDLE)
    assert overlay.undo(game, **IDLE)
    assert not os.path.exists(mods) and tree(game) == before_game


class _Bios:
    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.count = len(self.rows)

    def get(self, i, f):
        return self.rows[i][f]

    def set(self, i, f, v):
        self.rows[i][f] = v


def test_portrait_flags_follow_the_art_served():
    stock = {art.BIOS: _Bios([{'game_id': 3109, 'artid': 1082, 'hasportrait': 1},
                              {'game_id': 7, 'artid': 500, 'hasportrait': 0}])}
    rows = [{'game_id': 3109, 'artid': 1082, 'hasportrait': 1},    # stock face, the pack's NHL.com photo over it
            {'game_id': 7, 'artid': 500, 'hasportrait': 0},        # stock without a portrait, the pack has one
            {'game_id': 20641, 'artid': 20641, 'hasportrait': 0},  # a new player (NEW_ARTIDS), the pack has one
            {'game_id': 20700, 'artid': 20700, 'hasportrait': 1}]  # a new player without a photo: no flag
    db = {art.BIOS: _Bios(rows)}
    files = {art.PORTRAIT.format(a): b'' for a in (1082, 500, 20641)}
    assert art.portrait_flags(db, stock, files) == 3
    assert [r['hasportrait'] for r in db[art.BIOS].rows] == [1, 1, 1, 0]
    assert art.portrait_flags(db, stock, files) == 0
    # the art layer off: stock flags back, new players off
    assert art.portrait_flags(db, stock, {}) == 2
    assert [r['hasportrait'] for r in db[art.BIOS].rows] == [1, 0, 0, 0]
    assert art.portrait_flags({}, stock, files) == 0  # no bio table: nothing to do


def test_player_portraits_give_each_person_his_art_id():
    name = lambda first, last: clubdata._key(first, last)
    people = [[name('Gavin', 'McKenna'), 2007, 12, 20, 40001], [name('Nick', 'Suzuki'), 1999, 8, 10, 1500],
              [name('Late', 'Feed'), 2005, 1, 1, 40002], [name('One', 'Name'), 2004, 3, 3, 40003],
              [name('Two', 'Same'), 2000, 2, 2, 40004], [name('Mitch', 'Marner'), 1997, 5, 5, 40005]]
    shift = 8
    bio = lambda first, last, y, m, d, artid: {'firstname': first, 'lastname': last, 'year': y - 1900 - shift, 'month': m - 1,
                                               'day': d - 1, 'artid': artid, 'hasportrait': 0}
    rows = [bio('Gavin', 'McKenna', 2007, 12, 20, 20641),   # a new player: his art id was a free one
            bio('Nick', 'Suzuki', 1999, 8, 10, 1500),        # a stock art id stays
            bio('Late', 'Feed', 2006, 1, 1, 20700),          # the feed's year is off by one: the same day
            bio('One', 'Name', 2004, 9, 9, 20701),           # another day: the only bio and the only person of that name
            bio('Two', 'Same', 1990, 9, 9, 20702), bio('Two', 'Same', 1991, 9, 9, 20703),    # two bios: which one is not known
            bio('No', 'Photo', 2000, 1, 1, 20704),
            bio('Mitchell', 'Marner', 1997, 5, 5, 20705)]    # another first name, the same last name and birth date
    db = {art.BIOS: _Bios(rows)}
    assert art.player_portraits(db, people, shift) == 5
    assert [r['artid'] for r in db[art.BIOS].rows] == [40001, 1500, 40002, 40003, 20702, 20703, 20704, 40005]
    assert art.player_portraits({}, people) == 0


def test_delta_pack_round_trip_and_refusals(tmp_path, game):
    # a kit that differs from the game's in one block: stored as a delta, read back whole against the game's copy
    base = gnf('stock kit')
    kit = base[:16] + b'X' * 16 + base[32:]
    path = str(tmp_path / 'kits.zip')
    art.write_pack(path, 'kits', {KIT: kit, NEW_LOGO: gnf('sea')}, bases={KIT: base})
    with zipfile.ZipFile(path) as z:
        info = json.loads(z.read('pack.json'))
        assert info['format'] == 2 and set(info['files']) == {NEW_LOGO} and set(info['deltas']) == {KIT}
        assert KIT not in z.namelist() and len(z.read(KIT + '.delta')) == 4 + 8 + 16
    loaded = art.load_pack(path, game)
    assert loaded.files == {KIT: kit, NEW_LOGO: gnf('sea')} and 'deltas' not in loaded.info
    assert art.apply_delta(base, art.make_delta(base, base)) == base
    with pytest.raises(art.ArtError, match='game folder'):
        art.load_pack(path)
    # another game whose kit is not the one the pack was made on: refused
    other = tmp_path / 'other' / 'databigs'
    other.mkdir(parents=True)
    eb.new_archive(str(other / 'game_90.big'), {KIT: gnf('modded kit')})
    with pytest.raises(art.ArtError, match='not the file this pack was made on'):
        art.load_pack(path, str(tmp_path / 'other'))
    # a game without the file at all: refused too
    eb.new_archive(str(other / 'game_90.big'), {'nhl/data/y.bin': b'y'})
    with pytest.raises(art.ArtError, match='no base'):
        art.load_pack(path, str(tmp_path / 'other'))
    # a delta that runs past its file
    with pytest.raises(art.ArtError, match='runs past'):
        art.apply_delta(base, art.DELTA_MAGIC + (60).to_bytes(4, 'little') + (16).to_bytes(4, 'little') + b'Z' * 16)


def test_photos_switch_is_a_part_with_its_own_restore(game, tmp_path, monkeypatch):
    """Looks + photos + kits laid, photos switched off and Patch again: the same files as looks + kits laid fresh; all
    off: the stock game, byte for byte."""
    from overtime_roster.app import packdownload, patch
    folder = tmp_path / 'packs'
    folder.mkdir()
    monkeypatch.setenv(patch.ART_ENV, str(folder))
    monkeypatch.setattr(packdownload, 'photos_fit', lambda path, game_dir=None: {'fits': None})
    art.write_pack(str(folder / 'looks.zip'), 'looks', {LOGO: gnf('utah')})
    art.write_pack(str(folder / 'photos.zip'), 'photos', {PORTRAIT: gnf('nhl.com face')})
    stock, mods = tree(game), overlay.overlay_dir(game)
    on = patch.art_layer({'art': True}, [], game_dir=game)
    assert [p.name for p in on] == ['photos', 'looks']
    off = patch.art_layer({'art': True, 'photos': False}, [], game_dir=game)
    assert [p.name for p in off] == ['looks'] and patch.art_found() == ['photos.zip', 'looks.zip']
    overlay.apply(game, ('art',), art=on, **IDLE)
    with_photos = tree(mods)
    overlay.apply(game, ('art',), art=off, **IDLE)
    after = tree(mods)
    assert after != with_photos
    overlay.undo(game, **IDLE)
    overlay.apply(game, ('art',), art=off, **IDLE)
    assert tree(mods) == after                   # the same files as a fresh patch without the photos
    assert overlay.undo(game, **IDLE) and not os.path.exists(mods) and tree(game) == stock


def test_more_art_than_one_archive_holds_goes_in_several_mounted_after_the_game(monkeypatch):
    monkeypatch.setattr(art, 'ARCHIVE_ROOM', 100)
    entries = {f'nhl/data/t{i:02}.gnf': b'x' * 40 for i in range(7)}
    parts = art.split(entries)
    assert [len(p) for p in parts] == [2, 2, 2, 1] and {k for p in parts for k in p} == set(entries)
    names = art.archive_names('databigs/patch_game_97.big')
    got = [next(names) for _ in range(5)]
    assert got == [f'databigs/patch_game_{n}.big' for n in (97, 98, 99, 990, 991)]
    assert got == sorted(got) and got[0] > 'databigs/patch_game_96.big'     # the game sorts by name, the last wins


def test_a_pack_keeps_no_file_in_memory_and_says_when_it_changed(tmp_path):
    path, data = str(tmp_path / 'p.zip'), gnf('a')
    art.write_pack(path, 'p', {LOGO: data})
    pack = art.load_pack(path)
    stored = pack.files[LOGO]
    assert isinstance(stored, art.Stored) and len(stored) == len(data) and stored == data and stored.read() == data
    assert data == stored and not data != stored and pack.sha256
    art.write_pack(path, 'p', {LOGO: gnf('b')})
    with pytest.raises(art.ArtError, match='does not match'):
        stored.read()


def test_name_plates_are_dds_and_the_rest_gnf():
    plate = 'nhl/data/kettle/rendering/characters/player/name_adidas_anaheim_home.gnf'
    jersey = 'nhl/data/kettle/rendering/characters/player/jersey_adidas_anaheim_home_cm.gnf'
    art.check_file(plate, b'DDS ' + bytes(60))
    art.check_file(jersey, b'GNF ' + bytes(60))
    with pytest.raises(art.ArtError, match='DDS'):
        art.check_file(plate, b'GNF ' + bytes(60))
    with pytest.raises(art.ArtError, match='GNF'):
        art.check_file(jersey, b'DDS ' + bytes(60))


def test_exe_bundle_guard_flags_pictures_and_archives(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'check_bundle', os.path.join(os.path.dirname(__file__), '..', 'packaging', 'check_bundle.py'))
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    (tmp_path / 'img').mkdir()
    (tmp_path / 'img' / 'logo.png').write_bytes(b'x')
    (tmp_path / 'app.js').write_bytes(b'x')
    assert guard.stray([str(tmp_path)]) == []
    (tmp_path / 'looks32.zip').write_bytes(b'x')
    (tmp_path / 'img' / 'jersey.GNF').write_bytes(b'x')
    assert sorted(os.path.basename(p) for p in guard.stray([str(tmp_path)])) == ['jersey.GNF', 'looks32.zip']


def test_alternate_rows_relabel_only_while_a_pack_names_them():
    rows = [{'teamid': 0, 'style': 1, 'variant': 4, 'locstring': 6},
            {'teamid': 0, 'style': 1, 'variant': 3, 'locstring': 6},
            {'teamid': 1, 'style': 1, 'variant': 4, 'locstring': 6}]
    db = {art.STOCK_JERSEYS: _Bios(rows)}
    pack = art.Pack('alts', {'alternates': [{'teamid': 0, 'style': 1, 'variant': 4, 'locstring': 2}]}, {}, '')
    assert art.alternate_rows(db, [pack]) == 1
    assert [r['locstring'] for r in db[art.STOCK_JERSEYS].rows] == [2, 6, 6]
    assert art.alternate_rows(db, [pack]) == 0
    assert art.alternate_rows(db, []) == 0   # no pack: the stock labels stay (the database is built without them)
    assert art.alternate_rows({}, [pack]) == 0


def test_check_size_refuses_a_4_gb_archive_and_a_full_drive(tmp_path):
    big = {str(tmp_path / 'patch_x_9.big'): {'a': b'x' * 10}}
    art.check_size(big, free=art.SPARE + 10)                       # exactly enough
    with pytest.raises(art.ArtError, match='not enough free space'):
        art.check_size(big, free=art.SPARE + 9)
    huge = {str(tmp_path / 'patch_x_9.big'): {'a': _Sized(art.ARCHIVE_LIMIT)}}
    with pytest.raises(art.ArtError, match='more than an archive can hold'):
        art.check_size(huge, free=1 << 50)


class _Sized:
    def __init__(self, n):
        self.n = n

    def __len__(self):
        return self.n


def test_cached_alternates_read_the_jersey_layer_packs_pack_json(tmp_path):
    import json
    import zipfile
    alt = {'teamid': 0, 'style': 1, 'variant': 4, 'locstring': 2}
    for name, info in (('kitlayers_nhl.zip', {'alternates': [alt]}), ('kitlayers_intl.zip', {'alternates': []}),
                       ('other.zip', {'alternates': [alt]})):
        with zipfile.ZipFile(tmp_path / name, 'w') as z:
            z.writestr(art.MANIFEST, json.dumps(info))
    (tmp_path / 'kitlayers_bad.zip').write_bytes(b'not a zip')
    packs = art.cached_alternates(str(tmp_path))
    assert [p.name for p in packs] == ['kitlayers_nhl']
    db = {art.STOCK_JERSEYS: _Bios([{'teamid': 0, 'style': 1, 'variant': 4, 'locstring': 6}])}
    assert art.alternate_rows(db, packs) == 1
    assert art.cached_alternates(str(tmp_path / 'nothing')) == []


def test_cached_alternates_only_count_the_families_switched_on(tmp_path):
    import json
    import zipfile
    for fam, variant in (('nhl', 4), ('hometown', 3)):
        with zipfile.ZipFile(tmp_path / f'kitlayers_{fam}.zip', 'w') as z:
            z.writestr(art.MANIFEST, json.dumps({'alternates': [
                {'teamid': 0, 'style': 1, 'variant': variant, 'locstring': 2}]}))
    assert [p.name for p in art.cached_alternates(str(tmp_path))] == ['kitlayers_hometown', 'kitlayers_nhl']
    assert [p.name for p in art.cached_alternates(str(tmp_path), ['nhl'])] == ['kitlayers_nhl']
    assert [p.name for p in art.cached_alternates(str(tmp_path), ['nhl', 'hometown'])] == [
        'kitlayers_nhl', 'kitlayers_hometown']                  # the family order: the last wins a row
    assert art.cached_alternates(str(tmp_path), []) == []
