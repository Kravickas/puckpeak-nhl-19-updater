"""Match history rules (overtime_core.history): claims, confirmation, standings, a player's detail."""
from overtime_core import history as H


def claim(team, sf, sa, opp=None):
    return {'team': team, 'opp_team': opp, 'for': sf, 'against': sa, 'source': 'app'}


def match(mid, a, b, ca=None, cb=None, started=1000.0):
    claims = {}
    if ca:
        claims[a[0]] = ca
    if cb:
        claims[b[0]] = cb
    return {'id': mid, 'started': started, 'code': None, 'rules': None,
            'players': [{'pid': a[0], 'name': a[1]}, {'pid': b[0], 'name': b[1]}], 'claims': claims}


ANN, BO, CY = ('a1', 'Ann'), ('b2', 'Bo'), ('c3', 'Cy')


def test_pid_is_salted_and_stable():
    assert H.pid(5, 's') == H.pid('5', 's') != H.pid(5, 't') != H.pid(6, 's')
    assert len(H.pid(5, 's')) == 10 and '5' != H.pid(5, 's')


def test_team_and_score_checks():
    assert H.team_code(' pit ') == 'PIT' and H.team_code('NHLX9') is None and H.team_code('A') is None
    assert H.team_code(None) is None and H.team_code(7) is None
    assert H.score('3') == 3 and H.score(0) == 0 and H.score(100) is None and H.score(-1) is None
    assert H.score(True) is None and H.score(2.5) is None and H.score('x') is None


def test_no_claim_is_open():
    r = H.resolve(match(1, ANN, BO))
    assert r['status'] == H.OPEN and r['winner'] is None and r['scores'] == {'a1': None, 'b2': None}


def test_one_claim_is_waiting_for_the_other_and_shows_the_provisional_score():
    r = H.resolve(match(1, ANN, BO, ca=claim('PIT', 3, 2, 'BOS')))
    assert (r['status'], r['waiting_for'], r['winner']) == (H.WAITING, 'b2', None)
    assert r['scores'] == {'a1': 3, 'b2': 2} and r['teams'] == {'a1': 'PIT', 'b2': 'BOS'}


def test_mirroring_claims_confirm_and_name_the_winner():
    r = H.resolve(match(1, ANN, BO, ca=claim('PIT', 3, 2), cb=claim('BOS', 2, 3)))
    assert (r['status'], r['winner']) == (H.CONFIRMED, 'a1')
    assert r['scores'] == {'a1': 3, 'b2': 2} and r['teams'] == {'a1': 'PIT', 'b2': 'BOS'}
    r = H.resolve(match(2, ANN, BO, ca=claim('PIT', 1, 4), cb=claim('BOS', 4, 1)))
    assert r['winner'] == 'b2'


def test_claims_that_differ_are_disputed_and_nobody_wins():
    r = H.resolve(match(1, ANN, BO, ca=claim('PIT', 3, 2), cb=claim('BOS', 3, 2)))
    assert r['status'] == H.DISPUTED and r['winner'] is None
    assert H.resolve(match(1, ANN, BO, ca=claim('PIT', 3, 2), cb=claim('BOS', 2, 4)))['status'] == H.DISPUTED


def test_a_missing_team_is_taken_from_the_other_claim():
    r = H.resolve(match(1, ANN, BO, ca=claim(None, 3, 2, 'BOS'), cb=claim('BOS', 2, 3)))
    assert r['teams'] == {'a1': None, 'b2': 'BOS'}
    r = H.resolve(match(1, ANN, BO, ca=claim('PIT', 3, 2), cb=claim(None, 2, 3)))
    assert r['teams']['b2'] is None


def games():
    """Newest first: Ann beat Bo (PIT vs BOS) twice, lost to Cy once, one match still unplayed, one disputed."""
    return [
        match(5, ANN, BO, started=5000.0),
        match(4, ANN, CY, ca=claim('PIT', 1, 2), cb=claim('TOR', 2, 1), started=4000.0),
        match(3, ANN, BO, ca=claim('PIT', 4, 0), cb=claim('BOS', 0, 4), started=3000.0),
        match(2, BO, CY, ca=claim('BOS', 3, 4), cb=claim('TOR', 3, 4), started=2000.0),
        match(1, ANN, BO, ca=claim('PIT', 5, 3), cb=claim('BOS', 3, 5), started=1000.0),
    ]


def test_standings_count_only_confirmed_matches_best_first():
    rows = H.standings(games())
    assert [(r['name'], r['w'], r['l'], r['played']) for r in rows] == [('Ann', 2, 1, 3), ('Cy', 1, 0, 1), ('Bo', 0, 2, 2)]
    ann = rows[0]
    assert (ann['gf'], ann['ga'], ann['last']) == (10, 5, 4000.0)


def test_standings_skip_players_without_a_confirmed_match():
    assert H.standings([match(1, ANN, BO)]) == []


def test_player_detail_lists_opponents_teams_and_recent_matches():
    d = H.player_detail(games(), 'a1')
    assert (d['name'], d['w'], d['l'], d['played']) == ('Ann', 2, 1, 3)
    assert [(o['name'], o['w'], o['l']) for o in d['opponents']] == [('Bo', 2, 0), ('Cy', 0, 1)]
    assert [(t['team'], t['w'], t['l']) for t in d['teams']] == [('PIT', 2, 1)]
    assert [(t['team'], t['w'], t['l']) for t in d['against']] == [('BOS', 2, 0), ('TOR', 0, 1)]
    assert [m['id'] for m in d['recent']] == [5, 4, 3, 1]
    assert [m['result'] for m in d['recent']] == [None, 'L', 'W', 'W']
    last = d['recent'][1]
    assert (last['opponent']['name'], last['team'], last['opp_team'], last['for'], last['against']) == ('Cy', 'PIT', 'TOR', 1, 2)


def test_player_detail_unknown_player_and_limit():
    assert H.player_detail(games(), 'zz') is None
    assert len(H.player_detail(games(), 'a1', limit=2)['recent']) == 2


def test_a_forfeit_is_a_1_0_loss_for_the_player_who_quit_whatever_a_lone_claim_says():
    m = match(1, ANN, BO, cb=claim('BOS', 0, 4))                 # Bo's own (unfinished) score
    m['forfeit'] = ANN[0]
    r = H.resolve(m)
    assert (r['status'], r['winner'], r['left'], r['forfeit']) == (H.CONFIRMED, BO[0], ANN[0], True)
    assert r['scores'] == {ANN[0]: 0, BO[0]: 1} and r['waiting_for'] is None
    assert H.resolve(match(2, ANN, BO))['forfeit'] is False


def test_two_mirroring_reports_stand_over_a_forfeit_a_dispute_does_not():
    m = match(1, ANN, BO, ca=claim('PIT', 3, 2), cb=claim('BOS', 2, 3))
    m['forfeit'] = ANN[0]
    r = H.resolve(m)
    assert (r['status'], r['winner'], r['forfeit']) == (H.CONFIRMED, ANN[0], False)
    m['claims'][BO[0]] = claim('BOS', 5, 3)                       # the two differ: the quit decides
    r = H.resolve(m)
    assert (r['status'], r['winner'], r['forfeit']) == (H.CONFIRMED, BO[0], True)
    rows = H.standings([m])
    assert [(x['name'], x['w'], x['l'], x['gf'], x['ga']) for x in rows] == [('Bo', 1, 0, 1, 0), ('Ann', 0, 1, 0, 1)]


def test_game_stats_keep_penalty_minutes_and_drop_the_numbers_the_game_leaves_at_0():
    # live match 1 of 2026-11-07: pims 480 with four minors (the opponent had 4 power plays); shotsa / fol 0 on both sides
    raw = {'shots': 26, 'shotsa': 0, 'pims': 480, 'ppo': 3, 'fow': 8, 'fol': 0, 'toa': 230}
    assert H.clean_stats(raw) == {'shots': 26, 'pims': 8, 'ppo': 3, 'fow': 8, 'toa': 230}
    assert H.clean_stats({'shotsa': 0, 'fol': 0}) is None and H.clean_stats({'pims': 300})['pims'] == 5


def test_the_opponents_report_gives_shots_against_and_faceoffs_lost():
    mine = {'shots': 26, 'fow': 8}
    assert H.with_opponent(mine, {'shots': 34, 'fow': 24}) == {'shots': 26, 'fow': 8, 'shotsa': 34, 'fol': 24}
    assert H.with_opponent(mine, None) == mine and H.with_opponent(mine, {}) is not mine
    s = H.stat_summary([{'stats': {'fow': 8}, 'for': 2, 'against': 4}])
    assert s['rates']['faceoffs'] is None and s['rates']['saving'] is None   # no opponent numbers: no rate
