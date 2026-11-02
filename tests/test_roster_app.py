"""Overtime Roster app: session edits / undo / lines, save folders, the save pipeline (game data tests use the
user's own game files through the game_dir fixture; nothing is written outside tmp_path)."""
import os
import shutil
import struct
import threading
import types

import pytest

from overtime_core import lz4f, savefile, sfo, tdb
from overtime_roster.app import install, labels, rosters_ctl, savegame, sources
from overtime_roster.app.session import EditError, RosterSession

SAVE_DIR = os.environ.get('OVERTIME_SAVE_DIR', os.path.expandvars(
    r'%APPDATA%\shadPS4\home\1000\savedata\CUSA11126'))


# --- pure helpers (no game data) -------------------------------------------------------------------
def _sfo():
    return sfo.build([sfo.Entry('ACCOUNT_ID', sfo.FMT_BYTES, b'\x01' * 8, 8),
                      sfo.Entry('MAINTITLE', sfo.FMT_UTF8, 'Official Roster', 128),
                      sfo.Entry('SAVEDATA_DIRECTORY', sfo.FMT_UTF8, 'RosterOnline0', 32),
                      sfo.Entry('SAVEDATA_LIST_PARAM', sfo.FMT_U32, 0, 4)])


def test_sfo_roundtrip_and_patch():
    raw = _sfo()
    assert sfo.build(sfo.parse(raw)) == raw
    out = sfo.patch(raw, {'SAVEDATA_DIRECTORY': 'RosterCustom0', 'SAVEDATA_LIST_PARAM': 7})
    assert len(out) == len(raw)
    assert sfo.values(out) == {'ACCOUNT_ID': b'\x01' * 8, 'MAINTITLE': 'Official Roster',
                               'SAVEDATA_DIRECTORY': 'RosterCustom0', 'SAVEDATA_LIST_PARAM': 7}
    with pytest.raises(sfo.SfoError):
        sfo.patch(raw, {'SAVEDATA_DIRECTORY': 'x' * 40})
    with pytest.raises(KeyError):
        sfo.patch(raw, {'NOPE': 'x'})


def test_lz4_compressed_frame_roundtrip():
    data = bytes(200000) + os.urandom(70000) + b'roster' * 9000 + b'end'
    frame = lz4f.encode_compressed(data)
    assert len(frame) < len(data)
    out, n = lz4f.decode(frame)
    assert out == data and n == len(frame)
    for small in (b'', b'a', b'abcdefghijklm' * 2):
        assert lz4f.decode(lz4f.encode_compressed(small))[0] == small


def _fake_db_bytes(size=5000):
    head = bytearray(b'DB\x00\x08' + bytes(0x14))
    struct.pack_into('<I', head, 8, size)
    return bytes(head) + bytes(size - len(head))


def test_container_roundtrip_and_layout():
    blob = _fake_db_bytes()
    index, data = savegame.build_container('RosterCustom0', blob, {'FileDisplayName': 'Mine', 'CRCValue': 'x'},
                                           stamp_ns=1792077081000000000)
    entries = savegame.check_container('RosterCustom0', index, data, blob)
    names = [index[i:i + 32].split(b'\0')[0].decode() for i in range(0, len(index), 80)]
    assert names == ['RosterCustom0', '__SaveLoadFileInfo', '__SaveLoadMetaData', '__SaveloadVer']
    by = {e.name: e for e in entries}
    assert by['__SaveLoadFileInfo'].payload == savegame.FILE_INFO
    assert by['__SaveLoadMetaData'].payload == b'{\n"FileDisplayName":"Mine",\n"CRCValue":"x"\n}'
    assert by['__SaveloadVer'].payload[8:12] == b'1.60' and len(by['__SaveloadVer'].payload) == 72
    assert struct.unpack('<d', by['__SaveloadVer'].payload[:8])[0] == 46.0  # 45.0 lists as corrupt (run 2026-10-16c)
    assert struct.unpack('<Q', by['RosterCustom0'].stamp)[0] == 1792077081000000000
    unpacked = savefile.unpack(by['RosterCustom0'].payload)
    assert unpacked[len(blob):] == struct.pack('<IIIIH', 0x58b72ed9, 0, len(blob), 0, 1)


def test_trailer_keeps_template_word():
    t = savegame.trailer_for(10, struct.pack('<IIIIH', 0x12345678, 0, 99, 0, 1))
    assert struct.unpack('<IIIIH', t) == (0x12345678, 0, 10, 0, 1)


def test_trailer_never_takes_a_zero_word():
    want = struct.pack('<IIIIH', 0x58b72ed9, 0, 10, 0, 1)
    assert savegame.trailer_for(10) == want
    assert savegame.trailer_for(10, struct.pack('<IIIIH', 0, 0, 99, 0, 1)) == want


def _zero_word_save(saves, name='RosterCustom0'):
    """A roster folder as 0.20.0 wrote it on a PC with no Roster save: trailer word 0."""
    blob = _fake_db_bytes()
    unpacked = blob + struct.pack('<IIIIH', 0, 0, len(blob), 0, 1)
    meta = {'FileDisplayName': 'Mine', 'CRCValue': 'x'}
    stamp = bytes(8)
    index, data = savefile.build([
        savefile.SaveEntry('__SaveLoadFileInfo', stamp, savegame.FILE_INFO),
        savefile.SaveEntry('__SaveloadVer', stamp, savegame.CUSTOM_VER_PAYLOAD),
        savefile.SaveEntry('__SaveLoadMetaData', stamp, savegame.meta_json(meta)),
        savefile.SaveEntry(name, stamp, savefile.pack(unpacked))])
    return blob, savegame.write_new_folder(str(saves), name, index, data, savegame.default_sfo(name))


def test_check_container_refuses_a_zero_word(tmp_path):
    blob, folder = _zero_word_save(tmp_path)
    with open(os.path.join(folder, 'INDEX'), 'rb') as f, open(os.path.join(folder, 'DATA'), 'rb') as g:
        index, data = f.read(), g.read()
    with pytest.raises(savegame.SaveError):
        savegame.check_container('RosterCustom0', index, data, blob)


def test_repair_trailer_changes_only_the_word(tmp_path):
    blob, folder = _zero_word_save(tmp_path)
    _zero_word_save(tmp_path, 'RosterCustom1')
    index, data = savegame.build_container('RosterCustom2', blob, {'FileDisplayName': 'ok'})
    savegame.write_new_folder(str(tmp_path), 'RosterCustom2', index, data, savegame.default_sfo('RosterCustom2'))
    assert savegame.zero_trailers(str(tmp_path)) == ['RosterCustom0', 'RosterCustom1']
    before = savegame.read(folder)
    savegame.repair_trailer(folder)
    after = savegame.read(folder)
    assert after.db_bytes == blob and after.meta == before.meta
    assert after.trailer == struct.pack('<IIIIH', 0x58b72ed9, 0, len(blob), 0, 1)
    assert sorted(os.listdir(folder)) == ['DATA', 'INDEX', 'NAME', 'sce_sys']
    assert savegame.zero_trailers(str(tmp_path)) == ['RosterCustom1']


def test_app_repairs_zero_word_saves_once_with_a_backup(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'home'))
    saves = tmp_path / 'saves'
    saves.mkdir()
    blob, folder = _zero_word_save(saves)
    said, kept = [], {}
    ctl = types.SimpleNamespace(save_dir=str(saves), prefs=kept, lock=threading.RLock(), remember=kept.update,
                                say=lambda *a: said.append(a[0]), host=types.SimpleNamespace(log=lambda *a: None))
    part = rosters_ctl.RostersCtl.__new__(rosters_ctl.RostersCtl)
    part.ctl, part.refresh_sources = ctl, lambda quiet=False: None

    def run():
        part.repair_saves()
        for t in threading.enumerate():
            if t.name == 'save-repair':
                t.join()
    monkeypatch.setattr(rosters_ctl.overlay, 'emulator_running', lambda: True)
    run()                                       # never under a running game: left for the next start
    assert savegame.read(folder).trailer[:4] == bytes(4) and 'trailers_checked' not in kept
    assert not os.path.exists(tmp_path / 'home' / 'backups')
    monkeypatch.setattr(rosters_ctl.overlay, 'emulator_running', lambda: False)
    run()
    assert savegame.read(folder).trailer[:4] == bytes.fromhex('d92eb758') and savegame.read(folder).db_bytes == blob
    backup = os.listdir(tmp_path / 'home' / 'backups')
    assert len(backup) == 1 and said and kept['trailers_checked'] == str(saves)
    kept_copy = savegame.read(str(tmp_path / 'home' / 'backups' / backup[0] / 'RosterCustom0'))
    assert kept_copy.trailer[:4] == bytes(4)    # the backup holds the save as it was
    first = (saves / 'RosterCustom0' / 'DATA').read_bytes()
    run()                                       # checked already: nothing is read or written again
    assert (saves / 'RosterCustom0' / 'DATA').read_bytes() == first and os.listdir(tmp_path / 'home' / 'backups') == backup


def test_write_new_folder_never_overwrites(tmp_path):
    blob = _fake_db_bytes()
    index, data = savegame.build_container('RosterCustom0', blob, {'FileDisplayName': 'a'})
    (tmp_path / 'RosterCustom0').mkdir()
    assert savegame.next_free_name(str(tmp_path)) == 'RosterCustom1'
    with pytest.raises(savegame.SaveError):
        savegame.write_new_folder(str(tmp_path), 'RosterCustom0', index, data, _sfo())
    index, data = savegame.build_container('RosterCustom1', blob, {'FileDisplayName': 'a'})
    path = savegame.write_new_folder(str(tmp_path), 'RosterCustom1', index, data, _sfo(), b'png',
                                     labels={'MAINTITLE': 'Custom Roster'})
    assert sorted(os.listdir(path)) == ['DATA', 'INDEX', 'NAME', 'sce_sys']
    assert (tmp_path / 'RosterCustom1' / 'NAME').read_bytes() == b'RosterCustom1'
    vals = sfo.values((tmp_path / 'RosterCustom1' / 'sce_sys' / 'param.sfo').read_bytes())
    assert vals['SAVEDATA_DIRECTORY'] == 'RosterCustom1' and vals['MAINTITLE'] == 'Custom Roster'
    assert savegame.read(path).db_bytes == blob
    assert not [n for n in os.listdir(tmp_path) if n.startswith('.overtime-tmp')]


def test_slot_labels_cover_the_roster_table_fields():
    slots = labels.all_slots()
    assert len(slots) == len(set(slots)) == 87


# --- with the user's game files ----------------------------------------------------------------------
@pytest.fixture(scope='module')
def game(game_dir):
    return sources.GameData(game_dir)


@pytest.fixture
def session(game):
    return RosterSession(game.default_db(), 'NHL 19 default roster')


def _find(session, last):
    for pi in session.entry_row:
        _, b = session.bio(pi)
        if b and b['lastname'] == last:
            return pi
    raise LookupError(last)


def test_labels_cover_schema(game):
    schema = game.schema()
    sk = schema.by_name('exhibitionskaterai')
    gk = schema.by_name('exhibitiongoalieai')
    sk_names = {f.name for f in sk.fields.values()}
    gk_names = {f.name for f in gk.fields.values()}
    for groups, names in ((labels.SKATER_GROUPS, sk_names), (labels.GOALIE_GROUPS, gk_names)):
        for _, items in groups:
            for f, _ in items:
                assert f in names, f
    rt = {f.name for f in schema.by_name('exhibitionrostertable').fields.values()}
    assert set(labels.all_slots()) == rt - {'key', 'team', 'playerindex', 'jersey', 'captain', 'rosterstatus',
                                             'playerstyle'}


def test_default_roster_views(session):
    nhl = session.teams(0)
    assert len(nhl) >= 31 and nhl[0]['name'].startswith('Anaheim')
    pi = _find(session, 'McDavid')
    s = session.summary(pi)
    assert (s['pos'], s['num'], s['shoots'], s['team']) == ('C', 97, 'L', 'EDM')
    card = session.card(pi)
    assert card['values']['birth'] == '1997-01-13' and card['values']['height'] == 185
    assert card['values']['salary'] == 12.5 and 'c_speed' in card['values']['ratings']
    assert session.verify() == [] or not [i for i in session.verify() if i.level == 'error']
    assert session.search('ovechkin') and session.leagues()[0][1] == 'NHL'


def test_edit_and_undo_is_byte_exact(session):
    before = session.db.to_bytes()
    pi = _find(session, 'McDavid')
    used = {session.entry(p)[1]['jersey'] for p in session.players_of(11)}
    free = next(n for n in range(99, 0, -1) if n not in used)
    session.apply(pi, {'first': 'Connör', 'num': free,'shoots': 'R', 'birth': '1997-02-14', 'height': 190,
                       'weight': 90, 'ratings': {'c_speed': 80, 'c_passing': 70}, 'captain': 1})
    card = session.card(pi)
    assert card['values']['first'] == 'Connör' and card['values']['num'] == free
    assert card['values']['shoots'] == 'R' and card['values']['birth'] == '1997-02-14'
    assert card['values']['ratings']['c_speed'] == 80 and card['values']['captain'] == 1
    edm = session.players_of(11)
    assert sum(1 for p in edm if session.entry(p)[1]['captain'] == 1) == 1
    assert not [i for i in session.verify() if i.level == 'error']
    blob = session.db.to_bytes()
    assert tdb.Database.parse(blob).to_bytes() == blob
    assert len(session.change_lines()) >= 8
    while session.undo():
        pass
    assert session.db.to_bytes() == before


def test_rejected_edit_changes_nothing(session):
    before = session.db.to_bytes()
    pi = _find(session, 'McDavid')
    with pytest.raises(EditError):
        session.apply(pi, {'pos': 'G'})          # a goalie's ratings live in another table
    with pytest.raises(EditError):
        session.apply(pi, {'ratings': {'c_speed': 150}})
    assert session.db.to_bytes() == before and session.history == []


def test_shared_number_and_fourth_letter(session):
    before = session.db.to_bytes()
    pi = _find(session, 'McDavid')
    other = next(p for p in session.players_of(11) if p != pi and session.entry(p)[1]['captain'] == 0)
    taken = session.entry(other)[1]['jersey']
    session.apply(pi, {'num': taken})            # a teammate's number: the game shows both
    assert session.entry(pi)[1]['jersey'] == taken
    session.apply(other, {'captain': 2})         # a fourth letter
    assert sum(1 for p in session.players_of(11) if session.entry(p)[1]['captain']) == 4
    assert {'jersey', 'captains'} <= {i.rule for i in session.verify() if i.level == 'warning'}
    assert not [i for i in session.verify() if i.level == 'error']
    assert {'jersey', 'captains'} <= {i.rule for i in session.verify(strict=True) if i.level == 'error'}
    while session.undo():
        pass
    assert session.db.to_bytes() == before


def test_lines_edit_and_verify(session):
    pi = _find(session, 'McDavid')
    holders = session.slot_holders(11)
    l4c = holders['l4c'][0]
    session.set_slot(11, 'l4c', pi)
    h = session.slot_holders(11)
    assert h['l4c'] == [pi]
    assert not [i for i in session.verify() if i.level == 'error']
    session.set_slot(11, 'l4c', None)
    # an empty place: a warning for a player's own roster (the game plays it), an error for the roster we ship
    assert 'lines' in {i.rule for i in session.verify() if i.level == 'warning'}
    assert 'lines' in {i.rule for i in session.verify(strict=True) if i.level == 'error'}
    assert not [i for i in session.verify() if i.level == 'error']
    with pytest.raises(EditError):              # a skater in goal: the game crashes loading it
        session.set_slot(11, 'g1', pi)
    session.undo()
    session.undo()
    assert session.slot_holders(11)['l4c'] == [l4c]


def _template_save(dst):
    """A save folder like the game's: Profile0 with a param.sfo, enough for the pipeline's template."""
    os.makedirs(os.path.join(dst, 'Profile0', 'sce_sys'))
    with open(os.path.join(dst, 'Profile0', 'sce_sys', 'param.sfo'), 'wb') as f:
        f.write(_sfo())
    index, data = savefile.build([savefile.SaveEntry('Profile0', bytes(8), savefile.pack(b'{}'))])
    for n, b in (('INDEX', index), ('DATA', data)):
        with open(os.path.join(dst, 'Profile0', n), 'wb') as f:
            f.write(b)


def test_pipeline_installs_new_save(session, game, tmp_path):
    saves = tmp_path / 'saves'
    _template_save(str(saves))
    pi = _find(session, 'Crosby')
    session.apply(pi, {'num': 88})
    steps = []
    out = install.run(session, game, install.TARGET_SAVE, 'My roster', str(saves), str(tmp_path / 'home' / 'exports'),
                      step=lambda k, s, t='': steps.append((k, s)), log=lambda *a: None)
    assert out.ok, out.lines
    assert ('install', 'ok') in steps and os.path.basename(out.folder) == 'RosterCustom0'
    assert savegame.read(out.folder).trailer[:4] == bytes.fromhex('d92eb758')   # no Roster save here to copy it from
    rs = savegame.read(out.folder)
    db = tdb.Database.parse(rs.db_bytes, game.schema())
    assert len(db.tables) == 54 and rs.meta['FileDisplayName'] == 'My roster' and len(rs.meta['CRCValue']) == 54
    back = RosterSession(db)
    assert back.summary(pi)['num'] == 88
    assert os.path.isfile(out.report)
    assert os.listdir(tmp_path / 'home' / 'backups')
    # a second save goes to a new folder; the first is untouched
    first = (saves / 'RosterCustom0' / 'DATA').read_bytes()
    out2 = install.run(session, game, install.TARGET_SAVE, 'Again', str(saves), str(tmp_path / 'home' / 'exports'),
                       log=lambda *a: None, now=__import__('datetime').datetime(2030, 1, 1))
    assert out2.ok and os.path.basename(out2.folder) == 'RosterCustom1'
    assert (saves / 'RosterCustom0' / 'DATA').read_bytes() == first


@pytest.mark.parametrize('layout', ['no folder', 'empty folder', 'only a roster slot'])
def test_first_save_builds_what_it_needs(session, game, tmp_path, layout):
    """A player who never ran the game has no Profile0 (or no save folder): param.sfo and trailer are built."""
    saves = tmp_path / 'CUSA11126'
    if layout != 'no folder':
        saves.mkdir()
    if layout == 'only a roster slot':      # a slot with no param.sfo: nothing to copy either
        (saves / 'RosterCustom0' / 'sce_sys').mkdir(parents=True)
    out = install.run(session, game, install.TARGET_SAVE, 'First', str(saves), str(tmp_path / 'home' / 'exports'),
                      log=lambda *a: None)
    assert out.ok, out.lines
    want = 'RosterCustom1' if layout == 'only a roster slot' else 'RosterCustom0'
    assert os.path.basename(out.folder) == want
    rs = savegame.read(out.folder)
    assert rs.trailer[:4] == bytes.fromhex('d92eb758') and rs.meta['FileDisplayName'] == 'First'
    values = sfo.values((saves / want / 'sce_sys' / 'param.sfo').read_bytes())
    assert values['SAVEDATA_DIRECTORY'] == want and values['TITLE_ID'] == savegame.TITLE_ID


def test_save_refused_while_shadps4_runs(session, game, tmp_path, monkeypatch):
    saves = tmp_path / 'saves'
    _template_save(str(saves))
    monkeypatch.setattr(install.overlay, 'emulator_running', lambda: True)
    out = install.run(session, game, install.TARGET_SAVE, 'Held', str(saves), str(tmp_path / 'home' / 'exports'),
                      log=lambda *a: None)
    assert not out.ok and 'shadPS4 is running' in out.lines[0] and 'Nothing was written' in out.lines[0]
    assert sorted(os.listdir(saves)) == ['Profile0'] and not (tmp_path / 'home').exists()
    # an export touches no save: it goes on while the game runs
    assert install.run(session, game, install.TARGET_EXPORT, 'Export', '', str(tmp_path / 'x'), log=lambda *a: None).ok


def test_save_button_asks_to_close_shadps4_first(tmp_path, monkeypatch):
    from overtime_roster.app import save_ctl
    asked = []
    ctl = types.SimpleNamespace(session=object(), target=install.TARGET_SAVE, busy=None,
                                shell=types.SimpleNamespace(ask=lambda *a: asked.append(a[0])))
    part = save_ctl.SaveCtl.__new__(save_ctl.SaveCtl)
    part.ctl = ctl
    monkeypatch.setattr(save_ctl.overlay, 'emulator_running', lambda: True)
    part.save_start()
    assert asked == ['Close shadPS4 first'] and ctl.busy is None


def test_pipeline_says_saved_when_the_list_of_changes_fails(session, game, tmp_path, monkeypatch):
    """Legacy 0.51.1: a step after the save that fails must not turn a good save into "Not saved"."""
    saves = tmp_path / 'saves'
    _template_save(str(saves))
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'home'))

    def broken(path, **kw):
        raise PermissionError(13, 'Access is denied', path)
    monkeypatch.setattr(install.report, 'write', broken)
    steps = []
    out = install.run(session, game, install.TARGET_SAVE, 'Kept', str(saves), str(tmp_path / 'home' / 'exports'),
                      step=lambda k, s, t='': steps.append((k, s)), log=lambda *a: None)
    assert out.ok and out.title == 'Saved as RosterCustom0' and out.report == ''
    assert savegame.read(out.folder).meta['FileDisplayName'] == 'Kept'
    assert ('install', 'ok') in steps and ('report', 'fail') in steps
    assert len(out.after) == 1 and out.after[0].startswith('The list of changes (report.html) was not written')
    assert 'Access is denied' in (tmp_path / 'home' / 'logs' / 'error.log').read_text(encoding='utf-8')


def test_pipeline_writes_nothing_when_verify_fails(session, game, tmp_path):
    saves = tmp_path / 'saves'
    _template_save(str(saves))
    session.set_slot(11, 'l1c', None)                        # the game plays this: a warning, not a stop
    row = session.entry(_find(session, 'McDavid'))[0]
    nobody = max(p['index'] for p in session.rows['exhibitionplayers']) + 1
    session.db['exhibitionrostertable'].set(row, 'playerindex', nobody)     # a roster place for a player who is not there
    assert 'dangling_player' in {i.rule for i in session.verify() if i.level == 'error'}
    out = install.run(session, game, install.TARGET_SAVE, 'Broken', str(saves), str(tmp_path / 'exports'),
                      log=lambda *a: None)
    assert not out.ok and 'nothing was written' in out.lines[0]
    assert sorted(os.listdir(saves)) == ['Profile0'] and not (tmp_path / 'exports').exists()


def test_export_matches_server_format(session, game, tmp_path):
    out = install.run(session, game, install.TARGET_EXPORT, 'Export', '', str(tmp_path), log=lambda *a: None)
    assert out.ok
    blob = open(os.path.join(out.folder, 'roster_h2h.db'), 'rb').read()
    db = tdb.Database.parse(blob, game.schema())
    assert [t.tag for t in db.tables] == game.roster_order()
    assert open(os.path.join(out.folder, 'roster_h2h.crc.txt')).read().strip() == out.crc


def test_reads_real_online_roster_save(game):
    folder = os.path.join(SAVE_DIR, 'RosterOnline0')
    if not os.path.isdir(folder):
        pytest.skip('no RosterOnline0 save on this PC')
    rs = savegame.read(folder)
    db = tdb.Database.parse(rs.db_bytes, game.schema())
    assert db.to_bytes() == rs.db_bytes and len(rs.trailer) == 18
    s = RosterSession(db, rs.name)
    assert not [i for i in s.verify() if i.level == 'error']
    raw = open(os.path.join(folder, 'sce_sys', 'param.sfo'), 'rb').read()
    assert sfo.build(sfo.parse(raw)) == raw
    found = sources.find(game, SAVE_DIR)
    assert any(x.id == 'save:RosterOnline0' and x.usable for x in found)
