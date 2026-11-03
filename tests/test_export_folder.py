"""Export to a folder (install.TARGET_FOLDER): a shadPS4-layout save folder built under the exports folder, with a
HOW-TO, for another PC. Needs no save on this PC. Nothing is written outside tmp_path."""
import datetime
import os

import pytest

from overtime_core import sfo, tdb
from overtime_roster.app import howto, install, savegame, sources
from overtime_roster.app.session import RosterSession

from test_roster_app import _template_save


# --- pure helpers (no game data) -------------------------------------------------------------------
def test_default_sfo_has_the_games_layout():
    raw = savegame.default_sfo('RosterCustom3', 'Mine')
    assert sfo.build(sfo.parse(raw)) == raw and len(raw) == 1596       # the size of the ones the game writes
    vals = sfo.values(raw)
    assert vals['SAVEDATA_DIRECTORY'] == 'RosterCustom3' and vals['TITLE_ID'] == 'CUSA11126'
    assert vals['MAINTITLE'] == 'Custom Roster' and vals['SUBTITLE'] == 'Mine'
    assert vals['DETAIL'] == 'Mine (Overtime Roster)' and vals['SAVEDATA_BLOCKS'] == b'\xe0' + bytes(7)
    # install.run relabels it the way it relabels a template
    out = sfo.patch(raw, {'SUBTITLE': 'Another name', 'SAVEDATA_DIRECTORY': 'RosterCustom4'})
    assert sfo.values(out)['SUBTITLE'] == 'Another name' and len(out) == len(raw)


def test_default_trailer_holds_the_constant_word():
    assert savegame.trailer_for(10, savegame.DEFAULT_TRAILER) == savegame.TRAILER.pack(0x58b72ed9, 0, 10, 0, 1)


def test_unique_dir(tmp_path):
    base = str(tmp_path / 'x')
    assert install.unique_dir(base) == base
    os.mkdir(base)
    assert install.unique_dir(base) == base + ' (2)'
    os.mkdir(base + ' (2)')
    assert install.unique_dir(base) == base + ' (3)'


def test_howto_names_the_folder_and_the_game_slot():
    t = howto.text('RosterCustom4', 'My roster')
    assert 'Custom Roster 5' in t and 'RosterCustom4' in t and '%APPDATA%' in t and 'Library/Application Support' in t
    assert 'do not' in t and 'rename' in t and 'Slot on the other PC' in t       # a renamed copy does not load


# --- with the user's game files ----------------------------------------------------------------------
@pytest.fixture(scope='module')
def game(game_dir):
    return sources.GameData(game_dir)


@pytest.fixture
def session(game):
    return RosterSession(game.default_db(), 'NHL 19 default roster')


def _folder(session, game, tmp_path, save_dir='', name='For my other PC', now=None, steps=None):
    return install.run(session, game, install.TARGET_FOLDER, name, save_dir, str(tmp_path / 'home' / 'exports'),
                       step=lambda k, s, t='': steps.append((k, s)) if steps is not None else None,
                       log=lambda *a: None, now=now)


def test_folder_export_without_a_save_on_this_pc(session, game, tmp_path):
    steps = []
    out = _folder(session, game, tmp_path, str(tmp_path / 'no-saves'), steps=steps)
    assert out.ok, out.lines
    assert out.title == 'Folder exported' and ('backup', 'skip') in steps and ('install', 'ok') in steps
    root = out.folder
    assert os.path.commonpath([root, str(tmp_path / 'home' / 'exports')]) == str(tmp_path / 'home' / 'exports')
    save = os.path.join(root, howto.DATA_DIR, *howto.SAVE_PARTS, 'RosterCustom0')
    assert sorted(os.listdir(save)) == ['DATA', 'INDEX', 'NAME', 'sce_sys']
    assert sorted(os.listdir(os.path.join(save, 'sce_sys'))) == ['param.sfo']
    vals = sfo.values(open(os.path.join(save, 'sce_sys', 'param.sfo'), 'rb').read())
    assert vals['SUBTITLE'] == 'For my other PC' and vals['SAVEDATA_DIRECTORY'] == 'RosterCustom0'
    rs = savegame.read(save)
    db = tdb.Database.parse(rs.db_bytes, game.schema())
    assert len(db.tables) == 54 and rs.meta['FileDisplayName'] == 'For my other PC' and len(rs.meta['CRCValue']) == 54
    assert rs.trailer[:4] == savegame.DEFAULT_TRAILER[:4]
    assert 'Custom Roster 1' in open(os.path.join(root, howto.FILE), encoding='utf-8').read()
    assert os.path.isfile(out.report)
    assert not os.path.exists(tmp_path / 'home' / 'backups') and not os.path.exists(tmp_path / 'no-saves')


def test_folder_export_picks_a_slot_beside_this_pcs_saves_and_leaves_them(session, game, tmp_path):
    saves = tmp_path / 'saves'
    _template_save(str(saves))
    (saves / 'RosterCustom0').mkdir()
    before = sorted(os.listdir(saves))
    out = _folder(session, game, tmp_path, str(saves))
    assert out.ok, out.lines
    assert os.path.isdir(os.path.join(out.folder, howto.DATA_DIR, *howto.SAVE_PARTS, 'RosterCustom1'))
    assert sorted(os.listdir(saves)) == before
    vals = sfo.values(open(os.path.join(out.folder, howto.DATA_DIR, *howto.SAVE_PARTS, 'RosterCustom1', 'sce_sys',
                                        'param.sfo'), 'rb').read())
    assert vals['ACCOUNT_ID'] == b'\x01' * 8       # this PC's own save lends its template


def test_folder_export_for_a_chosen_slot(session, game, tmp_path):
    saves = tmp_path / 'saves'
    _template_save(str(saves))
    out = install.run(session, game, install.TARGET_FOLDER, 'Slot nine', str(saves), str(tmp_path / 'home' / 'exports'),
                      log=lambda *a: None, folder_slot='RosterCustom9')
    assert out.ok, out.lines
    save = os.path.join(out.folder, howto.DATA_DIR, *howto.SAVE_PARTS, 'RosterCustom9')
    assert os.path.isdir(save) and sfo.values(open(os.path.join(save, 'sce_sys', 'param.sfo'), 'rb').read())[
        'SAVEDATA_DIRECTORY'] == 'RosterCustom9'
    assert 'Custom Roster 10' in open(os.path.join(out.folder, howto.FILE), encoding='utf-8').read()


def test_folder_export_refuses_a_slot_the_game_does_not_list(session, game, tmp_path):
    out = install.run(session, game, install.TARGET_FOLDER, 'x', '', str(tmp_path / 'home' / 'exports'),
                      log=lambda *a: None, folder_slot='RosterCustom15')
    assert not out.ok and not (tmp_path / 'home' / 'exports').exists()


def test_second_export_gets_its_own_folder(session, game, tmp_path):
    now = datetime.datetime(2030, 1, 1, 12, 0, 0)
    a = _folder(session, game, tmp_path, now=now)
    b = _folder(session, game, tmp_path, now=now)
    assert a.ok and b.ok and a.folder != b.folder and b.folder.endswith('(2)')
    assert os.path.isdir(a.folder)


def test_folder_export_writes_nothing_when_verify_fails(session, game, tmp_path):
    session.set_slot(11, 'l1c', None)                        # the game plays this: a warning, not a stop
    row = session.entry(session.players_of(11)[0])[0]
    nobody = max(p['index'] for p in session.rows['exhibitionplayers']) + 1
    session.db['exhibitionrostertable'].set(row, 'playerindex', nobody)     # a place for a player who is not there
    out = _folder(session, game, tmp_path)
    assert not out.ok and 'nothing was written' in out.lines[0]
    assert not (tmp_path / 'home' / 'exports').exists()


def test_two_saves_in_one_second_say_so_instead_of_crashing(session, game, tmp_path):
    saves = tmp_path / 'saves'
    _template_save(str(saves))
    now = datetime.datetime(2030, 1, 1, 12, 0, 0)
    args = (session, game, install.TARGET_SAVE, 'One', str(saves), str(tmp_path / 'home' / 'exports'))
    assert install.run(*args, log=lambda *a: None, now=now).ok
    out = install.run(*args, log=lambda *a: None, now=now)
    assert not out.ok and 'Nothing was written' in out.lines[0]
    assert sorted(os.listdir(saves)) == ['Profile0', 'RosterCustom0']


def test_folder_export_for_the_european_game(session, game, tmp_path):
    """CUSA11116 (Europe) keeps its saves under its own title id: the folder, PARAM.SFO and the how-to follow it."""
    out = _folder(session, game, tmp_path, str(tmp_path / 'savedata' / 'CUSA11116'))
    assert out.ok, out.lines
    parts = howto.save_parts('CUSA11116')
    assert parts[-1] == 'CUSA11116' and parts[:-1] == howto.SAVE_PARTS[:-1]
    save = os.path.join(out.folder, howto.DATA_DIR, *parts, 'RosterCustom0')
    assert sfo.values(open(os.path.join(save, 'sce_sys', 'param.sfo'), 'rb').read())['TITLE_ID'] == 'CUSA11116'
    assert '/savedata/CUSA11116/RosterCustom0' in open(os.path.join(out.folder, howto.FILE), encoding='utf-8').read()
