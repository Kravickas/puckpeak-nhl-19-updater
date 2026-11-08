"""Writes that survive a power cut (overtime_core.durable) and what leans on them: a save swap a power cut stopped is
put back, a damaged patch record says so. A real power cut cannot be made in a test; these hold the order of the
steps and the recovery paths."""
import json
import os

import pytest

from overtime_core import durable, overlay
from overtime_roster.app import savegame


def test_replace_puts_the_whole_new_file_in_and_leaves_no_temporary(tmp_path):
    path, tmp = tmp_path / 'a.json', tmp_path / 'a.json.tmp'
    path.write_text('old')
    tmp.write_text('new')
    durable.replace(str(tmp), str(path))
    assert path.read_text() == 'new' and not tmp.exists()


def test_flush_tree_reaches_every_file(tmp_path, monkeypatch):
    (tmp_path / 'sce_sys').mkdir()
    for rel in ('INDEX', 'DATA', os.path.join('sce_sys', 'param.sfo')):
        (tmp_path / rel).write_bytes(b'x')
    flushed = []
    monkeypatch.setattr(durable, 'flush', lambda p: flushed.append(os.path.relpath(p, tmp_path)))
    durable.flush_tree(str(tmp_path))
    assert sorted(flushed) == sorted(['INDEX', 'DATA', os.path.join('sce_sys', 'param.sfo')])


def test_a_save_swap_stopped_between_its_renames_is_put_back(tmp_path):
    other = tmp_path / '.overtime-old-RosterCustom0-999999'      # another run's, its slot gone
    other.mkdir()
    (other / 'INDEX').write_bytes(b'old')
    mine = tmp_path / f'.overtime-old-RosterCustom1-{os.getpid()}'  # this run may be between its renames: left alone
    mine.mkdir()
    kept = tmp_path / '.overtime-old-RosterCustom2-999999'       # its slot is there: left alone
    kept.mkdir()
    (tmp_path / 'RosterCustom2').mkdir()
    assert savegame.recover_swaps(str(tmp_path)) == ['RosterCustom0']
    assert (tmp_path / 'RosterCustom0' / 'INDEX').read_bytes() == b'old'
    assert mine.exists() and kept.exists()
    assert 'RosterCustom0' in savegame.used_slots(str(tmp_path))


def test_a_damaged_patch_record_is_named_not_a_crash(tmp_path, monkeypatch):
    state = tmp_path / 'state.json'
    state.write_bytes(bytes(64))                                 # what a power cut can leave: zeros
    monkeypatch.setattr(overlay, 'state_path', lambda game_dir: str(state))
    monkeypatch.setattr(overlay, 'overlay_dir', lambda game_dir: str(tmp_path))
    with pytest.raises(overlay.PatchError, match='is damaged'):
        overlay._load_state('game')
    state.write_text(json.dumps({'files': {}}))
    assert overlay._load_state('game') == {'files': {}}
