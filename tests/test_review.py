"""The post-match review (overtime_core.review): facts from the result, tips only from the game's own numbers."""
from overtime_core import rating as R
from overtime_core import review as V

DAY = 24 * 3600


def mk(mid, a, b, sa, sb, started, ta='SEA', tb='UTA', stats_a=None, stats_b=None):
    ca = {'team': ta, 'opp_team': tb, 'for': sa, 'against': sb, 'source': 'app', 'stats': stats_a}
    cb = {'team': tb, 'opp_team': ta, 'for': sb, 'against': sa, 'source': 'app', 'stats': stats_b}
    return {'id': mid, 'started': float(started), 'code': None, 'rules': None, 'voided': False,
            'players': [{'pid': a[0], 'name': a[1]}, {'pid': b[0], 'name': b[1]}], 'claims': {a[0]: ca, b[0]: cb}}


ANN, BO = ('a1', 'Ann'), ('b2', 'Bo')


def run(games, pid, match_id=None):
    games = sorted(games, key=lambda m: (m['started'], m['id']))
    rated = R.rate(games)
    return V.review(list(reversed(games)), rated, pid, match_id)


def test_a_first_win_has_headline_rating_and_placement_facts():
    r = run([mk(1, ANN, BO, 4, 1, 1000)], 'a1')
    assert r['won'] and r['headline'] == 'Win over Bo, +24'
    assert r['rating'] == {'before': 1000, 'after': 1024, 'delta': 24, 'chance': 50, 'weight': 1.0}
    assert r['facts'][0] == 'You beat Bo 4-1 with SEA against UTA.'
    assert any('4 more rated games' in f for f in r['facts'])
    assert r['tier'] == {'before': 'Unranked', 'after': 'Unranked'} and r['tips'] == [] and not r['has_stats']


def test_the_loser_sees_the_loss_and_the_review_picks_a_given_match_or_the_latest():
    games = [mk(1, ANN, BO, 4, 1, 1000), mk(2, BO, ANN, 3, 2, 1000 + 2 * DAY)]
    assert run(games, 'a1')['match'] == 2 and run(games, 'a1', 1)['match'] == 1
    r = run(games, 'a1')
    assert not r['won'] and r['headline'].startswith('Loss to Bo, -') and 'Close game' in r['tags']
    assert run(games, 'a1', 99) is None and run(games, 'zz') is None


def test_streak_head_to_head_and_team_facts_and_tags():
    games = [mk(i, ANN, BO, 3, 1, 1000 + i * 2 * DAY) for i in range(1, 5)]
    r = run(games, 'a1')
    assert '4 wins in a row' in r['tags'] and 'Against Bo you are now 4-0.' in r['facts'] and 'With SEA you are 4-0.' in r['facts']
    assert 'Rank unlocked' not in r['tags']
    five = run(games + [mk(5, ANN, BO, 3, 1, 1000 + 10 * DAY)], 'a1')
    assert 'Rank unlocked' in five['tags'] and five['tier']['before'] == 'Unranked' and five['tier']['after'] != 'Unranked'


def test_a_repeat_game_within_a_day_says_it_counted_for_less():
    games = [mk(i, ANN, BO, 3, 1, 1000 + i * 600) for i in range(1, 6)]
    r = run(games, 'a1')
    assert r['rating']['weight'] == 0.0 and any('counted for none' in f for f in r['facts'])


def test_blowout_and_an_upset_are_tagged():
    games = [mk(i, ANN, BO, 3, 1, 1000 + i * 2 * DAY) for i in range(1, 8)]
    games.append(mk(9, BO, ANN, 7, 1, 1000 + 20 * DAY))
    r = run(games, 'b2')
    assert r['won'] and 'Upset' in r['tags'] and 'Blowout' in r['tags'] and r['headline'].startswith('Upset win over Ann')


def test_no_stats_no_tips_and_the_flag_says_so():
    assert V.tips(None, None, True, 3) == [] and V.tips({}, {}, True, 3) == []


def test_tips_come_from_the_numbers_only():
    mine = {'shots': 14, 'shotsa': 33, 'pims': 10, 'ppo': 4, 'ppg': 0, 'ppga': 2, 'fow': 6, 'fol': 14, 'passc': 20, 'passa': 40}
    theirs = {'pims': 2}
    got = V.tips(mine, theirs, False, 1)
    assert len(got) == V.MAX_TIPS
    assert 'outshot 14-33' in got[0] and any('10 penalty minutes against 2' in t for t in got)
    assert V.tips({'shots': 36, 'shotsa': 15}, None, False, 3)[0].startswith('You outshot them 36-15 and still lost')
    assert V.tips({'shots': 36, 'shotsa': 15}, None, True, 3) == []                      # winning with the shots: nothing to fix
    low = V.tips({'shots': 30, 'shotsa': 28}, None, False, 1)
    assert low == ['1 goals on 30 shots (3%). Look for rebounds and traffic in front instead of long shots.']


def test_the_review_uses_the_players_own_stats_and_the_opponents_for_penalties():
    games = [mk(1, ANN, BO, 1, 3, 1000, stats_a={'shots': 12, 'shotsa': 30, 'pims': 8}, stats_b={'shots': 30, 'pims': 2})]
    r = run(games, 'a1')
    assert r['has_stats'] and len(r['tips']) == 2 and 'outshot 12-30' in r['tips'][0] and '8 penalty minutes against 2' in r['tips'][1]
    other = run(games, 'b2')
    assert other['tips'] == [] and other['has_stats']                                     # Bo won the shots: nothing to fix


def test_the_opponents_shots_and_faceoffs_stand_in_for_the_zeros_the_game_sends():
    # live match 1 of 2026-11-07: the review said "outshot them 26-0" from the game's shotsa 0
    got = V.tips({'shots': 26, 'shotsa': 0, 'pims': 8, 'fow': 8, 'fol': 0}, {'shots': 34, 'fow': 24, 'pims': 6}, False, 2)
    assert got == ['8 penalty minutes against 6. Fewer hooks and trips: every penalty gives away the power play.',
                   'You won 25% of faceoffs. Pick your best taker for the key draws and back him up with a winger.']
    assert V.tips({'shots': 20, 'shotsa': 0}, {'shots': 34}, False, 2)[0].startswith('You were outshot 20-34')
