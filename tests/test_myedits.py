"""My edits (app/myedits.py): the Roster tab's saved player edits kept in edits.json and put back after an update.
The first tests use the file and the person keys alone; the game tests edit Edmonton on the game's roster, save it
into a temp saves folder, run Go with the fixture NHL.com data and find every kept edit back (a renamed player is
moved, not released), a refused one skipped with its reason, and one Undo taking the update and the edits back."""
import dataclasses
import json
import os

import pytest

from overtime_core import equipment as EQ, faces as F
from overtime_roster.app import controller as C, jobs, myedits, roster_card as RC, sources, update

from test_update_go import DATA, Host, _template_save, view

TEAM = 11   # Edmonton


def test_person_keys_ignore_case_accents_and_spaces():
    assert myedits.person_key('Tim', 'Stützle', '2002-01-15') == 'tim stutzle|2002-01-15'
    assert myedits.person_key(' Tim ', 'STUTZLE', '2002-01-15') == myedits.person_key('Tim', 'Stützle', '2002-01-15')
    assert myedits.person_key('', 'Ovechkin', None) == 'ovechkin|'


def test_a_renamed_player_has_every_mix_of_his_names():
    e = {'id': {'first': 'Leon', 'last': 'Draisaitl', 'born': '1995-10-27'},
         'card': {'last': 'Draisaitlx', 'born': '1995-10-28'}}
    keys = myedits.keys_of(e)
    assert keys[0] == 'leon draisaitlx|1995-10-28' and keys[-1] == 'leon draisaitl|1995-10-27' and len(keys) == 4
    data = {'version': myedits.VERSION, 'players': {'k': e}}
    assert myedits.find(data, {'first': 'Leon', 'last': 'Draisaitlx', 'born': '1995-10-27'}) == 'k'
    assert myedits.find(data, {'first': 'Leon', 'last': 'Draisait', 'born': '1995-10-27'}) is None


def test_the_file_round_trips_and_a_bad_one_reads_as_empty(tmp_path):
    path = str(tmp_path / 'edits.json')
    assert myedits.load(path) == myedits.empty()
    data = myedits.empty()
    data['players']['a|1990-01-01'] = {'id': {'first': '', 'last': 'A', 'born': '1990-01-01'}, 'label': 'A',
                                       'card': {'num': 7, 'ratings': {'speed': 90}}, 'gear': {'jersey_tuck': 1}}
    data['players']['bad'] = {'label': 'no id'}
    myedits.save(data, path)
    back = myedits.load(path)
    assert list(back['players']) == ['a|1990-01-01'] and not os.path.exists(path + '.tmp')
    assert myedits.words(back['players']['a|1990-01-01']) == ['number #7', '1 rating', 'equipment']
    assert myedits.rows(back) == [{'key': 'a|1990-01-01', 'label': 'A', 'team': '',
                                   'words': ['number #7', '1 rating', 'equipment']}]
    for raw in ('{', json.dumps({'version': 99, 'players': {}}), json.dumps({'version': 1, 'players': []})):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(raw)
        assert myedits.load(path) == myedits.empty()


# --- on the game's roster --------------------------------------------------------------------------------------------
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
    host = Host()
    c = C.Controller(host, game_dir=game_dir, save_dir=saves)
    host.ctl = c
    c.load_source(sources.GAME_ID)
    c.calls['tab']('roster')
    c.calls['rail_team'](TEAM)
    return c


def who(c, last):
    s = c.session
    return next(p for p in s.players_of(TEAM) if s.bio(p)[1]['lastname'] == last)


def by_name(c, first, last):
    """Every main card of a player with this name (any team, the free agents)."""
    s = c.session
    keys, names = myedits.index(s, c.parts['roster'].clock(s))
    return names.get(myedits.plain_name(first, last), [])


def raw(s):
    return {t: bytes(s.db[t].data) for t in ('exhibitionplayerbiotable', 'exhibitionrostertable', 'exhibitionskaterai',
                                             EQ.SKATER_TABLE)}


def card(c, pi):
    c.calls['roster_player'](pi, None)
    return c.host.snap('roster_card')['values']


@pytest.mark.game
def test_saved_edits_come_back_after_the_update(app):
    c = app
    s = c.session
    mcdavid, leon, nurse = who(c, 'McDavid'), who(c, 'Draisaitl'), who(c, 'Nurse')

    # McDavid: cap hit and a rating on the card, his face & type, his equipment
    va = card(c, mcdavid)
    rating = next(iter(va['ratings']))
    mine = va['ratings'][rating] - 7 if va['ratings'][rating] > 50 else va['ratings'][rating] + 7
    salary = 13.5 if va['salary'] != 13.5 else 14.0
    reply = c.calls['roster_apply']({**va, 'salary': salary, 'ratings': {**va['ratings'], rating: mine}})
    assert reply == {'ok': True, 'changes': 2}
    assert c.calls['roster_face_open']() == {'ok': True}
    f = c.host.snap('roster_face')
    style = next(t['value'] for t in f['type']['choices'] if t['value'] != f['type']['current'])
    hair = next(h for h in f['parts']['hair'] if h != f['current']['hair'])
    assert c.calls['roster_face_type'](style) == {'ok': True}
    assert c.calls['roster_face_pick']('hair', hair) == {'ok': True}
    assert c.calls['roster_face_apply']() == {'ok': True}
    assert c.calls['roster_gear_open']() == {'ok': True}
    g = {r['key']: r for r in c.host.snap('roster_gear')['rows']}
    tuck = next(n for n, _l in g['jersey_tuck']['options'] if n != g['jersey_tuck']['current'])
    assert c.calls['roster_gear_pick']('jersey_tuck', tuck) == {'ok': True}
    assert c.calls['roster_gear_apply'](False)['ok']
    # Draisaitl renamed; Nurse's new number taken back before the save (not kept)
    card(c, leon)
    assert c.calls['roster_apply']({'last': 'Draisaitlx'}) == {'ok': True, 'changes': 1}
    vn = card(c, nurse)
    used = {x['num'] for x in c.host.snap('roster')['rows']}
    assert c.calls['roster_apply']({'num': next(n for n in range(1, 100) if n not in used)})['ok']
    assert c.calls['roster_undo']('applied')['ok']
    assert card(c, nurse)['num'] == vn['num']

    c.calls['save_name']('Mine')
    assert c.calls['save'](None) is None and c.parts['save'].unsaved() == 0
    kept = myedits.load()
    assert len(kept['players']) == 2, kept
    bar = c.host.snap('save')
    assert bar['kept_count'] == 2 and [r['label'] for r in bar['kept']] == ['Leon Draisaitlx', 'Connor McDavid']
    mc = next(e for e in kept['players'].values() if e['id']['last'] == 'McDavid')
    assert mc['team'] == 'EDM' and mc['card'] == {'salary': salary, 'ratings': {rating: mine}}
    assert mc['face']['style'] == style and mc['face']['parts'] == {'hair': hair} and mc['gear'] == {'jersey_tuck': tuck}
    assert myedits.words(mc) == [f"{RC.WORDS['salary']} {RC.shown('salary', salary)}", '1 rating', 'player type',
                                 'face', 'equipment']
    dr = next(e for e in kept['players'].values() if e['id']['last'] == 'Draisaitl')
    assert dr['card'] == {'last': 'Draisaitlx'} and dr['label'] == 'Leon Draisaitlx'

    u = view(c.host)
    me = next(x for x in u['switches'] if x['key'] == 'myedits')
    assert me['on'] and me['sub'].startswith('2 players kept')
    before = raw(s)
    assert c.calls['update_go']() is None
    r = view(c.host)['result']
    assert r['kind'] == 'good', (r, c.host.lines[-30:])
    assert {x['part']: x['text'] for x in r['lines']}['My edits'] == '4 put back.'
    assert any(line == 'My edits: 4 applied, 0 skipped' for line in c.host.lines)

    # every kept edit is back; the renamed Draisaitl was moved, not released (no second Leon Draisaitl)
    mcdavid = by_name(c, 'Connor', 'McDavid')[0]
    v = card(c, mcdavid)
    assert v['salary'] == salary and v['ratings'][rating] == mine
    b = s.bio(mcdavid)[1]
    assert s.ai(b)[2][F.STYLE] == style and F.read(b)['hair'] == hair
    kind = EQ.kind_of(b['position'])
    assert EQ.read(s.db, EQ.row_of(s.db, b['game_id'], kind), kind)['jersey_tuck'] == tuck
    assert len(by_name(c, 'Leon', 'Draisaitlx')) == 1 and by_name(c, 'Leon', 'Draisaitl') == []
    assert RC.rail_team(s, by_name(c, 'Leon', 'Draisaitlx')[0]) == TEAM

    # one Undo takes the update and the edits put back together
    change = s.history[-1]
    assert any(d[0].startswith('My edits: Connor McDavid') for d in change.details)
    assert c.calls['update_result']('undo') is None
    assert view(c.host)['result']['title'] == 'The update was taken back'
    assert s.history[-1] is not change and raw(s) == before        # the roster as saved, his edits in it


@pytest.mark.game
def test_a_refused_edit_is_skipped_with_its_reason_and_the_switch_turns_it_off(app):
    c = app
    mcdavid = who(c, 'McDavid')
    card(c, mcdavid)
    free = next(n for n in range(1, 100) if n not in {x['num'] for x in c.host.snap('roster')['rows']})
    assert c.calls['roster_apply']({'num': free, 'height': 198})['ok']
    c.calls['save_name']('Mine')
    assert c.calls['save'](None) is None
    # the kept number is one the game cannot hold: the number is skipped, the height (NHL.com: 188 cm) goes in
    data = c.parts['roster'].kept()
    e = next(iter(data['players'].values()))
    e['card']['num'] = 0
    myedits.save(data)
    c.parts['roster']._kept = None
    assert c.calls['update_go']() is None
    r = view(c.host)['result']
    assert r['kind'] == 'good', (r, c.host.lines[-30:])
    assert {x['part']: x['text'] for x in r['lines']}['My edits'] == '1 put back, 1 skipped: see the warnings.'
    texts = json.dumps(r)
    assert 'My edits skipped: Connor McDavid (card): ' in texts
    v = card(c, by_name(c, 'Connor', 'McDavid')[0])
    assert v['height'] == 198 and v['num'] != 0

    # Remove on the Save bar's list: out of edits.json, the roster keeps what it has
    key = c.host.snap('save')['kept'][0]['key']
    assert c.calls['myedits_remove'](key) == {'ok': True}
    assert myedits.load()['players'] == {} and c.host.snap('save')['kept_count'] == 0
    assert c.calls['myedits_remove'](key) == {'ok': False}

    # the switch off: nothing is put back
    myedits.save(data)
    c.parts['roster']._kept = None
    c.calls['update_option']('myedits', False)
    assert c.calls['update_go']() is None
    r = view(c.host)['result']
    assert r['kind'] == 'good' and 'My edits' not in {x['part'] for x in r['lines']}


@pytest.mark.game
def test_a_contract_from_front_office_comes_back_in_years_left(app, monkeypatch):
    """The contract window's change is kept like a card edit and put back after the update, in years left: an
    update with NHL 27's deals gives the roster the expansion season, so one more is stored there."""
    from test_nhl27 import fake_pack
    c = app
    s = c.session
    plain = update.gather
    monkeypatch.setattr(update, 'gather', lambda *a, **kw: dataclasses.replace(
        g := plain(*a, **kw), nhl27=fake_pack(g.real, c.game.schema())))
    nurse = who(c, 'Nurse')
    c.calls['tab']('office')
    gid = s.bio(nurse)[1]['game_id']
    assert c.calls['office_contract'](gid) == {'ok': True}
    assert c.calls['office_contract_apply']({'cap': '7.25', 'years': 3, 'twoway': True})['ok']
    assert s.history[-1].tab == 'Front office'
    c.calls['save_name']('Mine')
    assert c.calls['save'](None) is None
    kept = myedits.load()['players']
    assert [e['card'] for e in kept.values()] == [{'salary': 7.25, 'years': 3, 'twoway': 1}]

    assert c.calls['update_go']() is None
    r = view(c.host)['result']
    assert r['kind'] == 'good', (r, c.host.lines[-30:])
    assert {x['part']: x['text'] for x in r['lines']}['My edits'] == '1 put back.'
    pi = by_name(c, 'Darnell', 'Nurse')[0]
    v = card(c, pi)
    assert (v['salary'], v['years'], v['twoway']) == (7.25, 3, 1)
    b = s.bio(pi)[1]
    assert RC.expansion(s) and b['contractlength'] == 4 and b['contractis2way'] == 1
    c.parts['rail'].pick_team(next(t for t in s.team_entries if pi in s.players_of(t)))   # his club now
    row = next(r for g in c.parts['office'].view()['groups'] for r in g['rows'] if r['key'] == b['game_id'])
    assert (row['cap_text'], row['years'], row['type']) == ('$7.25M', 3, 'Two-way')


@pytest.mark.game
def test_hand_set_lines_come_back_over_the_dealt_ones(app):
    """My line always wins: a team's places and letters the player set and saved are put back after the update deals
    its lines again (by rating, or the real ones), a player who left is skipped with his reason."""
    from overtime_core import lines as LN
    c = app
    s = c.session
    c.pick_team(TEAM)
    start = s.slot_holders(TEAM)
    a, b = start['l1lw'][0], start['l2lw'][0]
    assert c.calls['set_slot']('l1lw', b) == {'ok': True}
    assert c.calls['set_captain'](b, 1) == {'ok': True}
    assert c.calls['lines_apply']() == {'ok': True}
    mine = s.slot_holders(TEAM)
    assert mine['l1lw'] == [b] and mine['l2lw'] == [a]
    c.calls['save_name']('Mine')
    assert c.calls['save'](None) is None and c.parts['save'].unsaved() == 0
    kept = myedits.load()
    assert list(kept['lines']) == ['0:EDM'] and kept['players'] == {}
    e = kept['lines']['0:EDM']
    assert set(e['slots']) == {'l1lw', 'l2lw'} and e['slots']['l1lw']['last'] == s.bio(b)[1]['lastname']
    assert myedits.count(kept) == 1
    bar = c.host.snap('save')
    assert bar['kept_count'] == 1 and bar['kept'][0]['key'] == 'lines|0:EDM' and bar['kept'][0]['words'][0] == '2 places'

    # the update deals the team again (by rating): the stock lines come back, then mine go over them
    s.edit('deal again', lambda setter: LN.build(s.db, TEAM, setter))
    s.edit('letters off', lambda setter: [setter('exhibitionrostertable', i, 'captain', 0)
                                          for i in s.team_entries[TEAM]])
    assert s.slot_holders(TEAM)['l1lw'] != [b]
    clock = c.parts['roster'].clock(s)
    out = myedits.replay_lines(s, clock, kept)
    assert out == {'applied': 1, 'skipped': []}, out
    now = s.slot_holders(TEAM)
    assert now['l1lw'] == [b] and now['l2lw'] == [a]
    assert s.rows['exhibitionrostertable'][s.entry_row[b]]['captain'] == 1
    assert [i.text for i in s.verify() if i.level == 'error'] == []

    # a player who left the team is skipped with his reason; the rest still goes in
    s.edit('he left', lambda setter: setter('exhibitionrostertable', s.entry_row[b], 'team', 12))
    out = myedits.replay_lines(s, clock, kept)
    assert out['skipped'] and all('is not on' in x['why'] for x in out['skipped']), out
