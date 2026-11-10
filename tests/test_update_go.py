"""The Update tab's Go (update_ctl.update_go): one job from NHL.com to the saved roster. Most tests run on a made-up
roster with NHL.com, the plan, the change and the save replaced (jobs run inline; nothing is written outside the test's
temp folder): busy never drops between the steps, errors in the check write nothing and Undo takes the update back,
Go uses Check first's data again, and the Save card's targets reach the save pipeline as they should. The last test
runs Go for real on the game's roster into a temp saves folder."""
import json
import os
import threading
import types

import pytest

from overtime_core import rosterupdate as U, savefile, sfo, tdb
from overtime_core.roster import Issue
from overtime_roster.app import controller as C, install, jobs, patch, paths, savegame, sources, update
from overtime_roster.app import office, update_ctl as UC
from overtime_roster.app.session import Change, RosterSession

DATA = os.path.join(os.path.dirname(__file__), 'data')


class Host:
    """Records what the page would be told: every push with whether the app was busy then, and every Help bar text."""

    def __init__(self):
        self.snaps, self.lines, self.pushes, self.said, self.opened = {}, [], [], [], []
        self.ctl = None

    def register(self, name, fn):
        self.snaps[name] = fn

    def changed(self, *names):
        if self.ctl is not None:
            self.pushes.append((names, bool(self.ctl.busy)))
            if 'status' in names:
                self.said.append((dict(self.ctl.status), bool(self.ctl.busy)))

    def log(self, msg):
        self.lines.append(msg)

    def send(self, *a):
        pass

    def open_path(self, path):
        self.opened.append(path)

    def snap(self, name):
        return self.snaps[name]()


def lock_free(lock):
    """Whether another thread can take the lock now (the test's own thread may hold it: an RLock lets it in again)."""
    got = []
    t = threading.Thread(target=lambda: got.append(lock.acquire(timeout=0.2) and (lock.release() or True)))
    t.start()
    t.join()
    return got == [True]


class Session:
    """What Go reads of a RosterSession."""

    def __init__(self, name='My roster'):
        self.history, self.source_name, self.db, self.problems = [], name, object(), []

    def verify(self):
        return list(self.problems)

    def undo(self):
        return self.history.pop() if self.history else None

    def team_name(self, team):
        return f'Team {team}'

    def summary(self, pi):
        return {'pos': 'C'}

    def change_lines(self):
        return []


class Plan:
    moves = [(1, 'Ann Moves', (U.ROSTER, 1), (U.ROSTER, 2))]
    new = [({'first': 'Ned', 'last': 'New', 'position': 'C', 'number': 9}, (U.ROSTER, 3))]
    releases = [(2, 'Rob Leaves', (U.ROSTER, 4))]

    def summary(self):
        return {'players': 3, 'stay': 0, 'moves': 1, 'new': 1, 'releases': 1}


def report(problems=()):
    return U.Report(plan={}, teams=[1, 2], lines=['ANA', 'BOS'], ratings=10, calendar={
        'nhl32schedule': {'games': 1344, 'per_team': (84, 84), 'first': '2026-10-07', 'last': '2027-04-15'}},
        problems=list(problems), created=[], skipped_lines=[], signed=[], retired=[(5, 'Old Guy', 41)],
        nhl27={'rated': 700})


def save_source(folder, name):
    return sources.Source(f'save:{folder}', 'save', name, os.path.join('saves', folder),
                          meta=f'{folder} · custom · 2026-10-20 21:14 · 900 KB', info={'folder': folder})


class Fakes:
    """NHL.com, the plan, the change and the save pipeline, replaced; each call is written down."""

    def __init__(self, c, listed):
        self.c, self.listed = c, listed
        self.gathered, self.planned, self.ran, self.saved = [], [], [], []
        self.problems = []      # rosterupdate's own problems for the next run
        self.fail_gather = None

    def gather(self, client, season, pack_dir, fetch=None, offline=False, step=None, log=None, schedule=True):
        assert lock_free(self.c.lock), 'NHL.com is read without ctl.lock'
        assert self.c.busy
        self.gathered.append((season, offline, schedule))
        if self.fail_gather:
            raise update.UpdateError(self.fail_gather)
        for k in update.GATHER_STEPS:
            step(k, 'ok', 'fixture')
        return update.Gathered(season, [{'team': 'ANA'}], [('2026-10-07', 'ANA', 'BOS')], [], [],
                               {'rosters': 'data pack 2026-10-18' if offline else 'NHL.com', 'calendar': 'NHL.com'})

    def plan(self, db, gathered, aliases=None):
        assert not lock_free(self.c.lock), 'the plan is made under ctl.lock'
        self.planned.append(gathered)
        return Plan()

    def run(self, session, game, gathered, todo, per32=None, names=None, log=None, nhl27=True, schedule=True,
            retire=True, expansion=False, lines=False, portraits=None, served=True):
        assert not lock_free(self.c.lock), 'the roster changes under ctl.lock'
        self.ran.append({'per32': per32, 'nhl27': nhl27, 'schedule': schedule, 'retire': retire,
                         'expansion': expansion, 'lines': lines, 'served': served})
        session.history.append(Change("Update to today's NHL (2026-27)", kept=()))
        return report(self.problems)

    def install(self, session, game, target, name, save_dir, out_root, step=None, log=None, now=None,
                overwrite=None, folder_slot=None):
        assert not lock_free(self.c.lock), 'the roster is written under ctl.lock'
        self.saved.append({'target': target, 'name': name, 'overwrite': overwrite})
        self.folder_slot = folder_slot
        for key, _label in install.STEPS:
            if target != install.TARGET_SAVE and key == 'backup':
                step(key, 'skip', 'nothing in the save folder changes')
                continue
            step(key, 'run')
            assert self.c.busy
            step(key, 'ok', key)
        if target != install.TARGET_SAVE:
            folder = os.path.join(out_root, '20261021-120000')
        else:
            used = {s.info['folder'] for s in self.listed if s.kind == 'save'}
            slot = overwrite or next(n for n in savegame.slot_names() if n not in used)
            folder = os.path.join(save_dir, slot)
            if slot not in used:
                self.listed.append(save_source(slot, name))
        return install.Outcome(True, 'Saved', [], [], folder, os.path.join(out_root, 'report.html'), '5E1A93C4')


NOT_ACTIVE = UC.not_active


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'home'))

    def inline(work, done=None, failed=None, expected=()):
        try:
            out = work()
        except expected as err:
            return failed and failed(str(err))
        return done and done(out)
    monkeypatch.setattr(jobs, 'run', inline)
    listed = [sources.Source(sources.GAME_ID, 'game', 'NHL 19 default roster', str(tmp_path / 'game'))]
    monkeypatch.setattr(sources, 'find', lambda game, save_dir: list(listed))
    host = Host()
    c = C.Controller(host, game_dir=str(tmp_path / 'game'), save_dir=str(tmp_path / 'saves'))
    fakes = Fakes(c, listed)
    monkeypatch.setattr(update, 'gather', fakes.gather)
    monkeypatch.setattr(update, 'plan', fakes.plan)
    monkeypatch.setattr(update, 'run', fakes.run)
    monkeypatch.setattr(update, 'retirees', lambda db, gathered, nhl27=True: 3)
    monkeypatch.setattr(update, 'team_count', lambda db: 32)
    monkeypatch.setattr(install, 'run', fakes.install)
    monkeypatch.setattr(UC, 'not_active', lambda c, folder: None)
    host.ctl = c
    return c, host, fakes


def open_roster(c, fakes, folder=None, name='My roster', saves=None):
    """Open a made-up roster: the game's (folder None) or a save; `saves`: the saves listed ([(folder, name)]; the
    open one alone when None)."""
    for f, n in ([(folder, name)] if saves is None and folder else saves or []):
        fakes.listed.append(save_source(f, n))
    c.sources = list(fakes.listed)
    c.session = Session(name)
    c.parts['rosters'].open_id = sources.GAME_ID if folder is None else f'save:{folder}'
    c.parts['save'].roster_changed()
    c.parts['update'].roster_changed()


def view(host):
    v = host.snap('update')
    json.dumps(v)
    json.dumps(host.snap('update_list'))
    return v


def test_busy_never_drops_between_steps(app):
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom0')
    host.pushes.clear()
    host.said.clear()
    assert c.calls['update_go']() is None
    busy = [b for _names, b in host.pushes]
    assert busy[0] and not busy[-1]
    first_free = busy.index(False)
    assert all(busy[:first_free]) and not any(busy[first_free:]), busy   # set once, dropped once: at the end
    texts = [s['text'] for s, b in host.said if b]
    order = ["Checking NHL.com for today's rosters...", 'Planning', 'Changing the roster', 'Checking that the roster',
             'Backing up My roster...', 'Saving My roster...', 'Writing the list of changes...']
    at = [next(i for i, t in enumerate(texts) if t.startswith(want)) for want in order]
    assert at == sorted(at), texts      # the Help bar says every step, in order
    v = view(host)
    assert v['busy'] is False and v['run'] is None and v['go']['enabled']
    r = v['result']
    assert r['kind'] == 'good' and r['title'] == 'Updated and saved' and not r['can_undo']
    assert dict(r['items'])['Saved over'] == 'My roster' and dict(r['items'])['In the game'] == 'Custom Roster 1'
    assert [l['part'] for l in r['lines']] == ['NHL rosters', 'Real lines', 'Ratings', 'Calendar',
                                               'Retirements', 'Checked']
    assert fakes.ran[-1]['lines'] is True       # the switch is on unless the player turns it off
    assert r['lines'][-1]['text'] == 'The roster opens in NHL 19 with 32 teams.'
    assert c.status['text'] == 'Updated: My roster is saved. Start NHL 19 to play.'
    assert c.parts['save'].unsaved() == 0          # what Go saved is the saved roster now
    assert view(host)['from']['tag']['text'].startswith('Overtime ')
    c.calls['update_list'](True)
    lst = host.snap('update_list')
    assert lst['open'] and lst['title'] == 'List of changes' and lst['report'].endswith('report.html')
    assert lst['moves'][0]['name'] == 'Ann Moves' and lst['moves'][0]['pos'] == 'C' and lst['summary']['teams'] == 4


def test_go_says_saved_when_a_step_after_the_save_fails(app, monkeypatch):
    """Legacy 0.51.1: the roster is saved, so the result says so and adds what failed after it in red."""
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom0')
    real = fakes.install

    def install_then_fail(*a, **k):
        out = real(*a, **k)
        out.after, out.report = ['The list of changes (report.html) was not written: disk full'], ''
        return out
    monkeypatch.setattr(install, 'run', install_then_fail)
    c.calls['update_go']()
    r = view(host)['result']
    assert r['kind'] == 'good' and r['title'] == 'Updated and saved' and r['log'] and not r['report']
    assert r['lines'][-1] == {'part': 'Not done', 'tone': 'bad',
                              'text': 'The list of changes (report.html) was not written: disk full'}
    assert c.status['tone'] == 'caution' and c.status['text'].startswith('Updated: My roster is saved.')
    assert 'Not done: The list of changes' in c.status['text']
    assert c.parts['save'].unsaved() == 0


def test_error_log_block_names_the_folders(app, tmp_path):
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom0')
    try:
        raise OSError('[WinError 3] The system cannot find the path specified')
    except OSError as err:
        path = jobs.log_block(err, 'Restore')
    text = open(path, encoding='utf-8').read()
    assert text.startswith('=== ') and 'Overtime' in text.splitlines()[0]
    assert 'Step:     Restore' in text and 'Roster:   My roster' in text
    assert f"Game:     {tmp_path / 'game'}  (missing)" in text
    assert 'OSError: [WinError 3]' in text


def test_busy_while_running_refuses_and_go_is_off(app):
    c, host, fakes = app
    open_roster(c, fakes)
    with c.lock:
        c.busy = 'Saving...'
    assert c.calls['update_go']() is None and fakes.gathered == []
    assert view(host)['go']['enabled'] is False
    assert c.calls['update_option']('nhl27', False) == {'error': 'Wait for the update to finish.'}
    with c.lock:
        c.busy = None


def test_check_errors_write_nothing_and_undo_takes_it_back(app):
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom2')
    c.session.problems = [Issue('error', 'lines', 'Not enough centres.', team=7), Issue('warning', 'x', 'Fine.')]
    assert c.calls['update_go']() is None
    assert fakes.saved == [] and len(c.session.history) == 1    # changed, checked, not written
    v = view(host)
    r = v['result']
    assert r['kind'] == 'bad' and r['can_undo'] and r['issues'] == ['Team 7: Not enough centres.']
    assert dict(r['items'])['Saved'] == 'Nothing.'
    assert v['run'] == {'kind': 'go', 'at': 3, 'failed': True, 'steps': v['run']['steps']}
    assert not c.busy and c.status['tone'] == 'bad' and 'Nothing was saved' in c.status['text']
    assert c.parts['save'].unsaved() == 1
    assert c.calls['update_result']('undo') is None
    assert c.session.history == [] and c.parts['save'].unsaved() == 0
    r = view(host)['result']
    assert r['title'] == 'The update was taken back' and not r['can_undo']
    # rosterupdate's own problems stop it the same way
    fakes.problems = ['ANA: a roster key the game cannot load']
    c.session.problems = []
    c.calls['update_go']()
    assert fakes.saved == [] and view(host)['result']['issues'] == ['ANA: a roster key the game cannot load']


def test_undo_only_while_the_update_is_the_newest_change(app):
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom2')
    c.session.problems = [Issue('error', 'lines', 'Not enough centres.')]
    c.calls['update_go']()
    c.session.history.append(Change('Edited a player'))
    assert view(host)['result']['can_undo'] is False
    assert c.calls['update_result']('undo') == {
        'error': 'The update is not the newest change any more: take it back on the Roster tab.'}
    assert len(c.session.history) == 2


def test_nhl_com_down_stops_before_any_change(app):
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom2')
    fakes.fail_gather = 'No rosters: NHL.com could not be reached and there is no data pack.'
    c.calls['update_go']()
    assert fakes.planned == [] and fakes.ran == [] and fakes.saved == [] and not c.busy
    v = view(host)
    assert v['run']['failed'] and v['run']['at'] == 0
    assert v['result']['lines'][0]['part'] == 'NHL.com' and v['result']['lines'][1]['part'] == 'Nothing changed'
    assert not v['result']['can_undo']
    c.calls['update_result']('close')
    v = view(host)
    assert v['result'] is None and v['run'] is None


def test_check_first_is_used_again(app):
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom0')
    assert c.calls['update_check']() is None
    r = view(host)['result']
    assert r['kind'] == 'plan' and r['title'] == 'What Go would change' and not c.busy
    assert r['lines'][4]['text'] == '3 free agents would retire.'
    assert fakes.ran == [] and c.session.history == []          # Check first changes nothing
    c.calls['update_go']()
    assert len(fakes.gathered) == 1 and len(fakes.planned) == 1     # its data and plan, used again
    assert len(fakes.saved) == 1
    # another season (or data source) is gathered again
    c.calls['update_check']()
    assert len(fakes.gathered) == 2
    c.calls['update_option']('season', 2025)
    c.calls['update_go']()
    assert len(fakes.gathered) == 3 and fakes.gathered[-1][0] == 2025
    c.calls['update_check']()
    c.calls['update_option']('offline', True)
    c.calls['update_go']()
    assert len(fakes.gathered) == 5 and fakes.gathered[-1][1] is True
    assert dict(view(host)['result']['items'])['Data'] == 'Offline copy from 2026-10-18'


def test_check_first_plan_is_made_again_after_an_edit(app):
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom0')
    c.calls['update_check']()
    c.session.history.append(Change('Edited a player'))
    c.parts['save'].saved = list(c.session.history)     # saved since: nothing to ask
    c.calls['update_go']()
    assert len(fakes.gathered) == 1 and len(fakes.planned) == 2


def test_switches_reach_the_update(app):
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom0')
    for key in ('lines', 'nhl27', 'calendar', 'retire'):
        assert c.calls['update_option'](key, False) is None
    assert c.calls['update_option']('per32', 82) is None
    assert c.calls['update_option']('rosters', False) is None and c.status['text'] == UC.LOCKED['rosters']
    c.calls['update_go']()
    assert fakes.gathered[-1][2] is False       # no calendar needed
    assert fakes.ran[-1] == {'per32': 82, 'nhl27': False, 'schedule': False, 'retire': False, 'expansion': True,
                             'lines': False, 'served': False}     # no patch record: NHL 19's own salary cap
    lines = {l['part']: l['text'] for l in view(host)['result']['lines']}
    assert lines['Ratings'] == 'Left as they were.' and lines['Calendar'] == 'Left as it was.'
    assert lines['Retirements'] == 'Nobody retired.' and lines['Real lines'] == 'Off: lines by rating.'
    assert c.prefs['update']['nhl27'] is False and c.prefs['update']['lines'] is False     # remembered


def test_real_lines_show_in_the_result(app, monkeypatch):
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom0')
    gather = fakes.gather

    def with_lines(*a, **k):
        g = gather(*a, **k)
        g.lines = {'TOR': {'date': '2026-10-23'}, 'SEA': {'date': '2026-10-24'}}
        return g
    monkeypatch.setattr(update, 'gather', with_lines)
    real = report()
    real.real = {'lined': ['SEA', 'TOR'], 'full': ['TOR'], 'partly': {'SEA': ['Lines (1 of 18 filled)']},
                 'refused': {'UTA': ['no group of the real lines has all its players on the team']},
                 'lettered': ['SEA', 'TOR', 'UTA'], 'date': '2026-10-24'}
    monkeypatch.setattr(fakes, 'run', lambda *a, **k: (fakes.ran.append(k), a[0].history.append(
        Change("Update to today's NHL (2026-27)", kept=())), real)[-1])
    monkeypatch.setattr(update, 'run', fakes.run)
    assert c.calls['update_check']() is None
    lines = {l['part']: l['text'] for l in view(host)['result']['lines']}
    assert lines['Real lines'] == '2 teams would play their real lines and captains (games to 2026-10-24).'
    c.calls['update_go']()
    lines = {l['part']: l['text'] for l in view(host)['result']['lines']}
    assert lines['Real lines'] == ('1 teams play their real lines (games to 2026-10-24), 3 have their real captains. '
                                   '1 in part: a player left, or the source has no lines. 1 kept lines by rating. '
                                   'Details lists them.')
    assert fakes.ran[-1]['lines'] is True


def test_older_settings_turn_real_lines_on(app):
    c, host, fakes = app
    assert c.parts['update'].opts['lines'] is True
    assert 'lines' in UC.OPTIONS and next(s for s in UC.SWITCHES if s[0] == 'lines')[1] == 'Real lines and captains'


def test_targets_game_roster_saves_new(app):
    c, host, fakes = app
    open_roster(c, fakes)      # the game's own roster
    v = view(host)
    assert v['save']['mode'] == 'new' and v['save']['why'] == UC.CANNOT_UPDATE['game']
    assert c.calls['update_save_mode']('update') == {'error': UC.CANNOT_UPDATE['game']}
    c.calls['update_name']('Season 26')
    c.calls['update_go']()
    assert fakes.saved == [{'target': install.TARGET_SAVE, 'name': 'Season 26', 'overwrite': None}]
    r = view(host)['result']
    assert dict(r['items'])['Saved as'] == 'Season 26' and dict(r['items'])['In the game'] == 'Custom Roster 1'
    assert c.status['text'] == 'Updated: saved as Season 26. Start NHL 19 and load Custom Roster 1.'
    # the new save is the open roster now: the next Go updates it
    assert c.parts['rosters'].open_roster()['id'] == 'RosterCustom0'
    assert view(host)['save']['mode'] == 'update' and c.parts['save'].unsaved() == 0


def test_targets_online_roster_cannot_be_updated(app):
    c, host, fakes = app
    open_roster(c, fakes, 'RosterOnline0', name='Official Roster')
    assert view(host)['save']['mode'] == 'new'
    assert c.calls['update_save_mode']('update') == {'error': UC.CANNOT_UPDATE['online']}


def test_targets_full_slots_pick_one_to_write_over(app):
    c, host, fakes = app
    saves = [(f'RosterCustom{n}', f'Roster {n}') for n in range(savegame.SLOTS)]
    open_roster(c, fakes, 'RosterCustom0', name='Roster 0', saves=saves)
    c.calls['update_save_mode']('new')
    sv = view(host)['save']
    assert sv['full'] and sv['block'] == 'Pick the save to write over first.' and len(sv['slots']) == savegame.SLOTS
    assert c.calls['update_go']() == {'error': 'Pick the save to write over first.'} and fakes.saved == []
    c.calls['update_slot']('RosterCustom20')
    assert view(host)['save']['slot'] is None and c.status['text'] == 'That save is not there any more.'
    c.calls['update_slot']('RosterCustom5')
    c.calls['update_name']('Fresh')
    c.calls['update_go']()
    assert fakes.saved == [{'target': install.TARGET_SAVE, 'name': 'Fresh', 'overwrite': 'RosterCustom5'}]
    items = dict(view(host)['result']['items'])
    assert items['Wrote over'] == 'Roster 5 (backed up first)' and items['In the game'] == 'Custom Roster 6'


def test_targets_online_file(app):
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom0')
    c.calls['update_save_mode']('online')
    c.calls['update_go']()
    assert fakes.saved == [{'target': install.TARGET_EXPORT, 'name': 'Online roster', 'overwrite': None}]
    r = view(host)['result']
    assert r['title'] == 'Updated: online roster file written' and dict(r['items'])['Check code'] == 'CRC 5E1A93C4'
    assert not r['can_play'] and r['folder']
    assert c.parts['save'].unsaved() == 1       # the file is written; the roster itself is not saved


def test_unsaved_edits_ask_first(app):
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom0')
    c.session.history.append(Change('Edited a player'))
    reply = c.calls['update_go']()
    assert 'asked' in reply and fakes.gathered == []
    c.calls['answer'](reply['asked'], 'cancel')
    assert fakes.gathered == [] and len(c.session.history) == 1
    reply = c.calls['update_go']()
    c.calls['answer'](reply['asked'], 'lose')       # the edit is dropped, then Go runs on the roster as saved
    assert len(fakes.saved) == 1 and [ch.label for ch in c.session.history] == ["Update to today's NHL (2026-27)"]
    assert c.parts['save'].unsaved() == 0


def test_no_roster(app):
    c, host, fakes = app
    v = view(host)
    assert v['ready'] is False and v['tip'] == 'Pick a roster in Setup first.'
    assert c.calls['update_go']() == {'error': 'Pick a roster in Setup first.'}


# --- for real, on the game's roster ----------------------------------------------------------------------------------
def _template_save(dst):
    """A save folder like the game's: Profile0 with a param.sfo, enough for the pipeline's template."""
    os.makedirs(os.path.join(dst, 'Profile0', 'sce_sys'))
    raw = sfo.build([sfo.Entry('ACCOUNT_ID', sfo.FMT_BYTES, b'\x01' * 8, 8),
                     sfo.Entry('MAINTITLE', sfo.FMT_UTF8, 'Official Roster', 128),
                     sfo.Entry('SAVEDATA_DIRECTORY', sfo.FMT_UTF8, 'RosterOnline0', 32),
                     sfo.Entry('SAVEDATA_LIST_PARAM', sfo.FMT_U32, 0, 4)])
    with open(os.path.join(dst, 'Profile0', 'sce_sys', 'param.sfo'), 'wb') as f:
        f.write(raw)
    index, data = savefile.build([savefile.SaveEntry('Profile0', bytes(8), savefile.pack(b'{}'))])
    for n, b in (('INDEX', index), ('DATA', data)):
        with open(os.path.join(dst, 'Profile0', n), 'wb') as f:
            f.write(b)


@pytest.mark.game
def test_go_for_real_saves_a_new_roster(game_dir, tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'home'))

    def inline(work, done=None, failed=None, expected=()):
        try:
            out = work()
        except expected as err:
            return failed and failed(str(err))
        return done and done(out)
    monkeypatch.setattr(jobs, 'run', inline)
    with open(os.path.join(DATA, 'nhl_rosters_20262027.json'), encoding='utf-8') as f:
        real = json.load(f)
    with open(os.path.join(DATA, 'nhl_schedule_20262027.json'), encoding='utf-8') as f:
        games = [tuple(g) for g in json.load(f)]

    def gather(client, season, pack_dir, fetch=None, offline=False, step=None, log=None, schedule=True):
        for k in update.GATHER_STEPS:
            step(k, 'ok', 'fixture')
        return update.Gathered(season, real, games, [], [], {'rosters': 'NHL.com', 'calendar': 'NHL.com'})
    monkeypatch.setattr(update, 'gather', gather)
    saves = str(tmp_path / 'saves')
    _template_save(saves)
    host = Host()
    c = C.Controller(host, game_dir=game_dir, save_dir=saves)
    host.ctl = c
    c.load_source(sources.GAME_ID)
    assert c.session is not None
    c.calls['update_name']('Season 26')
    assert c.calls['update_go']() is None
    r = view(host)['result']
    assert r['kind'] == 'good', (r, host.lines[-30:])
    assert os.path.isfile(os.path.join(saves, 'RosterCustom0', 'INDEX'))
    assert dict(r['items'])['Saved as'] == 'Season 26' and r['report'] and os.path.isfile(r['report'])
    assert r['lines'][-1]['text'] == 'The roster opens in NHL 19 with 32 teams.'
    mine = c.parts['rosters'].open_roster()
    assert mine['id'] == 'RosterCustom0' and mine['kind'] == 'save'
    assert c.parts['save'].unsaved() == 0 and not c.busy
    assert os.listdir(os.path.join(paths.app_home(), 'backups'))     # the saves were backed up first
    f = view(host)['from']
    assert f['tag'] == {'text': f'Overtime {UC.VERSION}', 'tone': 'good'} and f['note'].startswith('Updated from NHL.com')


@pytest.mark.game
def test_update_with_nhl27_gives_the_expansion_season_once(game_db):
    """The app's Update (expansion=True) adds the expansion career's season to NHL 27's plain deals, as the patched
    default carries it: exactly the plain result plus rosterupdate.expansion_contracts. On a roster that carries it
    already every such deal is written again first (no deal gets two). NHL 27 off keeps the deals and adds none."""
    from test_nhl27 import fake_pack
    raw, schema = game_db
    with open(os.path.join(DATA, 'nhl_rosters_20262027.json'), encoding='utf-8') as f:
        reals = json.load(f)
    game = types.SimpleNamespace(schema=lambda: schema, default_db=lambda: raw)
    gathered = update.Gathered(2026, reals, [], active=[], nhl27=fake_pack(reals, schema))

    def updated(data, **kw):
        s = RosterSession(tdb.Database.parse(data, schema), 'test')
        return s, update.run(s, game, gathered, update.plan(s.db, gathered), **kw)

    once, rep = updated(raw, expansion=True)
    plain, rep0 = updated(raw)
    assert 'expansion' not in rep0.nhl27 and rep.nhl27['expansion'] == U.expansion_contracts(plain.db) >= 0.9 * len(reals)
    assert once.db.to_bytes() == plain.db.to_bytes()
    assert ('Contracts one season longer (expansion career)', '-', f"{rep.nhl27['expansion']} deal(s)") in         once.history[-1].details
    deals = [b for b in once.db[U.BIOS].rows() if office.counts(b)]
    assert office.carries_expansion(deals)

    marked = tdb.Database.parse(once.db.to_bytes(), schema)      # every deal it lengthens marked 13 long
    bios = marked[U.BIOS]
    for brow in range(bios.count):
        if office.lengthened(bios.row(brow)):
            bios.set(brow, 'contractlength', 13)
    again, rep2 = updated(marked.to_bytes(), expansion=True)
    lengths = [b['contractlength'] for b in again.db[U.BIOS].rows() if office.lengthened(b)]
    assert rep2.nhl27['expansion'] == len(lengths) and 13 not in lengths and 14 not in lengths
    assert 2 <= min(lengths) and max(lengths) <= 9

    off, rep3 = updated(raw, nhl27=False, expansion=True)
    assert 'expansion' not in rep3.nhl27
    assert not office.carries_expansion([b for b in off.db[U.BIOS].rows() if office.counts(b)])


@pytest.mark.game
def test_update_deals_match_the_patched_default(game_dir):
    """An Update with NHL 27 on the game's roster writes the very deals patch.updated_default ships (run6 in game:
    the stars stay past an expansion Franchise's first July 1): length, money, type, status and club alike."""
    from test_nhl27 import fake_pack
    game = sources.GameData(game_dir)
    with open(os.path.join(DATA, 'nhl_rosters_20262027.json'), encoding='utf-8') as f:
        reals = json.load(f)
    gathered = update.Gathered(2026, reals, [], active=[], nhl27=fake_pack(reals, game.schema()))
    raw, _rep = patch.updated_default(game, gathered)
    s = RosterSession(game.default_db(), 'test')
    update.run(s, game, gathered, update.plan(s.db, gathered), expansion=True)
    fields = ('contractlength', 'contractdollars', 'contractis2way', 'contractstatus', 'contractismultiyear',
              'proteam', 'team')

    def deals(db):
        return {b['game_id']: tuple(b[f] for f in fields) for b in db[U.BIOS].rows() if office.counts(b)}
    assert deals(s.db) == deals(tdb.Database.parse(raw, game.schema()))


def test_targets_folder_for_another_pc(app):
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom0')
    c.calls['update_save_mode']('folder')
    sv = view(host)['save']
    assert sv['mode'] == 'folder' and sv['block'] is None and 'folder' in {m['value'] for m in sv['modes']}
    c.calls['update_name']('Steam Deck')
    c.calls['update_go']()
    assert fakes.saved == [{'target': install.TARGET_FOLDER, 'name': 'Steam Deck', 'overwrite': None}]
    r = view(host)['result']
    assert r['title'] == 'Updated: folder ready' and dict(r['items'])['Roster'] == 'Steam Deck'
    assert not r['can_play'] and r['folder']
    assert c.parts['save'].unsaved() == 1       # the folder is written; the roster itself is not saved
    assert c.calls['update_save_mode']('folder') is None and view(host)['save']['mode'] == 'folder'
    c.calls['update_name']('  ')
    assert view(host)['save']['block'] == 'Type a name for the new roster first.'


def test_folder_slot_is_chosen_and_passed_on(app):
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom0')
    c.calls['update_save_mode']('folder')
    sv = view(host)['save']
    assert sv['folder_slot'] is None and len(sv['folder_slots']) == 15 and sv['folder_slots'][0]['label'] == 'Custom Roster 1'
    c.calls['update_folder_slot']('RosterCustom9')
    assert view(host)['save']['folder_slot'] == 'RosterCustom9'
    c.calls['update_folder_slot']('RosterCustom99')         # not a slot the game lists: back to automatic
    assert view(host)['save']['folder_slot'] is None
    c.calls['update_folder_slot']('RosterCustom9')
    c.calls['update_name']('Slot nine')
    c.calls['update_go']()
    assert fakes.folder_slot == 'RosterCustom9'
    c.calls['update_save_mode']('update')
    assert view(host)['save']['folder_slots'] is None


# --- the patch bar (v0.10.0 S6): Update says when the game is not patched, broken or patched by an older Overtime ---
def _patched(c, applied=True, problems=(), by=None):
    c.patch_status = {'applied': applied, 'layers': {}, 'problems': list(problems)}
    c.parts['patch'].eboot = {'installed': applied, 'problems': []}
    if by is not None:
        c.prefs['patched_by'] = by


def test_patch_bar_waits_until_the_patch_was_looked_at(app):
    c, host, fakes = app
    open_roster(c, fakes)
    c.patch_status, c.parts['patch'].eboot = None, None
    assert view(host)['patch'] is None


def test_patch_bar_not_patched(app):
    c, host, fakes = app
    open_roster(c, fakes)
    _patched(c, applied=False)
    p = view(host)['patch']
    assert p['kind'] == 'none' and p['tone'] == 'caution' and 'not patched' in p['text']


def test_patch_bar_problem(app):
    c, host, fakes = app
    open_roster(c, fakes)
    _patched(c, problems=['data/x.big: missing from the overlay (apply again)'], by=UC.VERSION)
    assert view(host)['patch']['kind'] == 'problem' and view(host)['patch']['tone'] == 'bad'


@pytest.mark.parametrize('by', [None, '0.1.0-beta3', 'garbage', UC.VERSION, '99.0.0'])
def test_patch_bar_gone_when_patched_by_any_overtime(app, by):
    """A patch from an older Overtime gets no line either (owner 2026-11-10)."""
    c, host, fakes = app
    open_roster(c, fakes)
    _patched(c, by=by)
    assert view(host)['patch'] is None


def test_patch_bar_when_the_salary_cap_switch_changed_after_the_update(app, monkeypatch):
    """Go remembers which cap the deals were written for; when the league layer changes after, the bar says so (the
    deals no longer fit the cap the game plays) until the roster is updated again."""
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom2')
    monkeypatch.setattr(savegame, 'active_roster', lambda save_dir: 'RosterCustom2')
    _patched(c, by=UC.VERSION)
    c.calls['update_go']()
    assert fakes.ran[-1]['served'] is False and c.prefs['update_saved']['RosterCustom2']['cap'] == '2018'
    assert view(host)['patch'] is None
    c.patch_status['layers'] = {'league': {}}           # the 2026-27 cap switched on in Game patch
    p = view(host)['patch']
    assert p['kind'] == 'money' and p['tone'] == 'caution' and 'salary cap' in p['text']
    c.calls['update_go']()
    assert fakes.ran[-1]['served'] is True and view(host)['patch'] is None


def test_go_says_when_the_game_is_not_set_to_the_saved_roster(app, monkeypatch):
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom2')
    monkeypatch.setattr(UC, 'not_active', NOT_ACTIVE)
    monkeypatch.setattr(savegame, 'active_roster', lambda save_dir: None)
    c.calls['update_go']()
    r = view(host)['result']
    assert r['lines'][0]['part'] == 'Not active yet' and r['lines'][0]['tone'] == 'bad'
    assert "the game's own roster" in r['lines'][0]['text'] and 'Rosters > Active Rosters' in r['say']
    assert ['Active in NHL 19', 'No: pick it in the game'] in r['items']
    monkeypatch.setattr(savegame, 'active_roster', lambda save_dir: 'RosterCustom2')
    r = view(host)['result']
    assert r['lines'][0]['part'] != 'Not active yet' and ['Active in NHL 19', 'Yes'] in r['items']


def test_the_active_roster_comes_from_the_profile(tmp_path, monkeypatch):
    profile = b'{"Roster":\n{\n"ActiveRosterSaveSlot":2,\n"ActiveRosterType":"Download"\n}\n}'
    monkeypatch.setattr(savefile, 'read_folder', lambda path: [types.SimpleNamespace(payload=profile)])
    assert savegame.active_roster(str(tmp_path)) == 'RosterDownload2'
    profile = b'{"Roster":\n{\n"ActiveRosterSaveSlot":-1,\n"ActiveRosterType":""\n}\n}'
    assert savegame.active_roster(str(tmp_path)) is None
    assert savegame.roster_label('RosterCustom0') == 'Custom Roster 1'
    assert savegame.roster_label('RosterDownload2') == 'Online Roster 3'
    assert savegame.roster_label(None) == "the game's own roster"


def test_the_card_says_the_club_logos_were_skipped(app, monkeypatch, tmp_path):
    """v0.50.1: an Update with no club logo pack says so on the result card (v0.50.0 skipped without a word)."""
    from overtime_roster.app import patch
    monkeypatch.setenv(patch.ART_ENV, str(tmp_path / 'packs-without-clubart'))
    c, host, fakes = app
    open_roster(c, fakes, 'RosterCustom0')
    assert c.calls['update_go']() is None
    lines = {l['part']: l['text'] for l in view(host)['result']['lines']}
    assert lines['Club logos'] == 'Club logos skipped: the club logo pack is not downloaded. Press Update again.'
    assert any(line.startswith('club logos: skipped (') for line in host.lines)
