"""Seattle fit (beta3): while the installed patch runs 32 teams, Setup marks every save without an active Seattle
("31 teams", the New Season crash) and a Patch with 32 teams asks to update the open roster when it is one of them;
"Update it now" opens the Update tab and runs Go over it. The game's roster saved into a temp saves folder, Go with
the fixture NHL.com data (nothing outside the test's temp folder is written)."""
import json
import os

import pytest

from overtime_roster.app import controller as C, jobs, patch_ctl, rosters_ctl, savegame, sources, update

from test_update_go import DATA, Host, _template_save, view

TEAM = 11


class Events(Host):
    def __init__(self):
        super().__init__()
        self.events = []

    def send(self, event, payload=None):
        self.events.append((event, payload))


@pytest.fixture
def app(game_dir, tmp_path, monkeypatch):
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
    host = Events()
    c = C.Controller(host, game_dir=game_dir, save_dir=saves)
    host.ctl = c
    c.load_source(sources.GAME_ID)
    c.calls['tab']('roster')
    c.calls['rail_team'](TEAM)
    return c


def rows(c, teams32):
    r = c.parts['rosters']
    r.view(True, False, teams32)        # the first look reads the saves (a job: inline here)
    return {x['id']: x for x in r.view(True, False, teams32)['rows']}


@pytest.mark.game
def test_a_save_without_seattle_is_marked_and_the_patch_offers_to_update_it(app):
    c = app
    s = c.session
    c.calls['roster_player'](s.players_of(TEAM)[0], None)
    assert c.calls['roster_apply']({'first': 'Ryanx'})['ok']
    c.calls['save_name']('Old roster')
    assert c.calls['save'](None) is None
    mine = rows(c, True)['RosterCustom0']
    assert {'text': '31 teams', 'tone': 'caution'} in mine['chips'] and mine['problem'] == rosters_ctl.MISFIT
    for teams32 in (False, None):           # 31 teams in the game (or no patch): nothing to mark
        plain = rows(c, teams32)['RosterCustom0']
        assert plain['problem'] is None and all(x['text'] != '31 teams' for x in plain['chips'])

    # a Patch with 32 teams asks about the open roster; Later only closes
    assert patch_ctl.offer_update(c) is True
    q = c.shell.asking
    assert q['title'] == 'Update Old roster now?' and [b['answer'] for b in q['buttons']] == ['update', 'later']
    c.calls['answer'](q['id'], 'later')
    assert c.shell.asking is None and c.host.events == []

    # Update it now: the Patch tab, the roster update over this save; then it fits and nothing is asked
    assert patch_ctl.offer_update(c) is True
    c.calls['answer'](c.shell.asking['id'], 'update')
    assert ('goto', 'patch') in c.host.events
    r = view(c.host)['result']
    assert r['kind'] == 'good', (r, c.host.lines[-30:])
    assert sorted(savegame.used_slots(c.save_dir)) == ['RosterCustom0']     # written over, no new save
    fixed = rows(c, True)['RosterCustom0']
    assert fixed['problem'] is None and all(x['text'] != '31 teams' for x in fixed['chips'])
    assert patch_ctl.offer_update(c) is False


@pytest.mark.game
def test_no_question_for_the_game_roster_or_the_default(app):
    c = app
    assert c.parts['rosters'].open_roster()['kind'] == 'start'
    assert patch_ctl.offer_update(c) is False and c.shell.asking is None
