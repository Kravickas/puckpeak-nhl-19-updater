"""A split install: shadPS4 keeps the 1.60 update in `CUSA11126-patch` (or `-UPDATE`) beside the base game. Either
folder picked, the app reads, patches and checks the pair as the emulator serves it (player report 2026-10-29)."""
import json
import os
import shutil

import pytest

from overtime_core import eb, gamefiles, overlay, textpack
from overtime_roster.app import gamesetup
from test_gamesetup import _sfo
from test_textpack import make_eb


def tree(top):
    out = {}
    for d, _dirs, files in os.walk(top):
        for n in files:
            with open(os.path.join(d, n), 'rb') as f:
                out[os.path.relpath(os.path.join(d, n), top)] = f.read()
    return out


def _folder(root, name, app_ver, archives):
    g = root / name
    (g / 'sce_sys').mkdir(parents=True)
    (g / 'sce_sys' / 'param.sfo').write_bytes(_sfo(app_ver=app_ver))
    (g / 'eboot.bin').write_bytes(b'\x7fELF ' + app_ver.encode())
    (g / 'databigs').mkdir()
    for n, entries in archives.items():
        eb.new_archive(str(g / 'databigs' / n), entries)
    return g


@pytest.fixture
def split(tmp_path):
    base = _folder(tmp_path, 'CUSA11126', '01.00', {'inxp_00.big': {'nhl/a.xml': b'base meta'},
                                                     'patch_inxp_51.big': {'nhl/b.db': b'base db'}})
    update = _folder(tmp_path, 'CUSA11126-patch', '01.60', {'patch_inxp_51.big': {'nhl/b.db': b'update db'},
                                                           'patch_inxp_56.big': {'nhl/b.db': b'newest db'}})
    return base, update


@pytest.mark.parametrize('pick', ['base', 'update'])
def test_either_folder_is_the_pair(split, pick):
    base, update = split
    game = str(base if pick == 'base' else update)
    assert gamefiles.roots(game) == (str(base), str(update))
    assert gamefiles.mods_dir(game) == str(base) + '-mods'
    names = [os.path.relpath(p, os.path.dirname(str(base))) for p in gamefiles.archives(game)]
    assert names == [os.path.join('CUSA11126', 'databigs', 'inxp_00.big'),         # base only
                     os.path.join('CUSA11126-patch', 'databigs', 'patch_inxp_51.big'),  # same name: the update's
                     os.path.join('CUSA11126-patch', 'databigs', 'patch_inxp_56.big')]
    assert gamefiles.read_latest(game, 'nhl/a.xml') == (b'base meta', 'inxp_00.big')   # the player's error
    assert gamefiles.read_latest(game, 'nhl/b.db') == (b'newest db', 'patch_inxp_56.big')
    assert gamefiles.rel(game, str(update / 'databigs' / 'patch_inxp_56.big')) == 'databigs/patch_inxp_56.big'
    assert gamefiles.locate(game, 'databigs/inxp_00.big') == str(base / 'databigs' / 'inxp_00.big')
    assert gamefiles.locate(game, 'databigs/patch_inxp_51.big') == str(update / 'databigs' / 'patch_inxp_51.big')
    info = gamesetup.read_game(game)
    assert info['ok'] and info['app_ver'] == '01.60' and info['update'] == str(update)


def test_served_reads_the_base_mods_folder(split):
    base, update = split
    mods = base.parent / 'CUSA11126-mods' / 'databigs'
    mods.mkdir(parents=True)
    eb.new_archive(str(mods / 'patch_inxp_56.big'), {'nhl/b.db': b'modded db'})
    assert gamefiles.read_latest(str(update), 'nhl/b.db', mods=True) == (b'modded db', 'patch_inxp_56.big')
    assert gamefiles.read_latest(str(base), 'nhl/b.db', mods=False) == (b'newest db', 'patch_inxp_56.big')


@pytest.mark.parametrize('pick', ['base', 'patch', 'update'])
def test_both_update_folders_resolve_to_the_one_shadps4_mounts(tmp_path, pick):
    """-UPDATE and -patch beside the base: shadPS4 mounts -UPDATE, so every pick resolves to it (0.30.0)."""
    base = _folder(tmp_path, 'CUSA11126', '01.00', {'inxp_00.big': {'nhl/a.xml': b'a'}})
    patch = _folder(tmp_path, 'CUSA11126-patch', '01.60', {'patch_inxp_56.big': {'nhl/b.db': b'patch'}})
    update = _folder(tmp_path, 'CUSA11126-UPDATE', '01.60', {'patch_inxp_56.big': {'nhl/b.db': b'update'}})
    game = str({'base': base, 'patch': patch, 'update': update}[pick])
    assert gamefiles.roots(game) == (str(base), str(update))
    assert gamefiles.read_latest(game, 'nhl/b.db') == (b'update', 'patch_inxp_56.big')
    assert gamesetup.read_game(game)['update'] == str(update)


def test_update_suffix_and_lone_folders(tmp_path):
    lone = _folder(tmp_path, 'NHL19-patch', '01.60', {'inxp_00.big': {'nhl/a.xml': b'a'}})
    assert gamefiles.roots(str(lone)) == (str(lone), None)          # no base beside it: a whole game
    assert gamefiles.mods_dir(str(lone)) == str(lone) + '-mods'
    merged = _folder(tmp_path, 'NHL 19', '01.60', {'inxp_00.big': {'nhl/a.xml': b'a'}})
    assert gamefiles.roots(str(merged)) == (str(merged), None)
    up = _folder(tmp_path, 'CUSA11126-UPDATE', '01.60', {'patch_inxp_56.big': {'nhl/b.db': b'b'}})
    _folder(tmp_path, 'CUSA11126', '01.00', {'inxp_00.big': {'nhl/a.xml': b'a'}})
    assert gamefiles.roots(str(tmp_path / 'CUSA11126')) == (str(tmp_path / 'CUSA11126'), str(up))
    old = _folder(tmp_path, 'Old', '01.00', {'inxp_00.big': {'nhl/a.xml': b'a'}})
    assert gamesetup.read_game(str(old))['problem'].startswith('NHL 19 version 01.00')


@pytest.fixture
def split_game(game_dir, tmp_path):
    """The real archives split as shadPS4 installs them: the schemas in the base's inxp_00.big, the archive that wins
    for both databases in the update folder."""
    base, update = tmp_path / 'CUSA11126', tmp_path / 'CUSA11126-patch'
    for folder, ver in ((base, '01.00'), (update, '01.60')):
        (folder / 'sce_sys').mkdir(parents=True)
        (folder / 'sce_sys' / 'param.sfo').write_bytes(_sfo(app_ver=ver))
        (folder / 'databigs').mkdir()
    src = textpack._winner(game_dir, gamefiles.DB_PATH)
    shutil.copyfile(src, update / 'databigs' / os.path.basename(src))
    metas = [(*path.rsplit('/', 1), gamefiles.read_latest(game_dir, path)[0])
             for path in (gamefiles.META_PATH, textpack.loc_paths('eng_us')[1])]
    make_eb(str(base / 'databigs' / 'inxp_00.big'), metas)
    return base, update


@pytest.mark.game
@pytest.mark.parametrize('pick', ['base', 'update'])
def test_text_layer_on_a_split_install(split_game, pick):
    base, update = split_game
    game = str(base if pick == 'base' else update)
    before = tree(str(base.parent))
    name = os.path.basename(textpack._winner(game, gamefiles.DB_PATH))
    st = overlay.apply(game, ('text',), running=lambda: False)
    assert list(st['files']) == [f'databigs/{name}']
    assert os.path.isfile(base.parent / 'CUSA11126-mods' / 'databigs' / name)
    assert not os.path.exists(str(update) + '-mods')
    s = overlay.status(game)
    assert s['applied'] and s['problems'] == []
    assert textpack.status(game, textpack.load_pack())['not_current'] == []
    overlay.undo(game, running=lambda: False)
    assert tree(str(base.parent)) == before          # both folders as they were, the overlay gone


def test_setup_lists_the_pair_once_and_launches_the_base(split, tmp_path, monkeypatch):
    from overtime_roster.app import launch
    base, update = split
    user = tmp_path / 'shadPS4'
    user.mkdir()
    (user / 'config.json').write_text(json.dumps({'General': {'install_dirs': [{'enabled': True, 'path': str(tmp_path)}]}}))
    games = gamesetup.find_games(str(user), extra=[str(tmp_path)])
    assert [g['path'] for g in games] == [str(base)] and games[0]['ok'] and games[0]['update'] == str(update)
    emu = tmp_path / 'shadPS419.exe'
    for pick in (base, update):    # shadPS4 lays the update and <base>-mods over the base it is started from
        assert launch.command(str(emu), str(pick))[1:] == ['-g', str(base / 'eboot.bin')]
