"""Elo rating and rank tiers over the confirmed matches (pure; no clock, no storage).

The rating is never stored: `rate()` folds the confirmed matches in order, so a voided match, a late confirmation or a new
season just re-folds. Only matches `overtime_core.history.resolve` calls confirmed count. Hockey is noisy and the pool is
small, so the numbers move slowly and a player is "placing" until PLACEMENT games. The same two players meeting again and
again within PAIR_WINDOW are damped (win-trading with a spoofable id gains little).
"""
import math

from . import history as H

START = 1000.0                                  # a new player is a Rookie
SCALE = 400.0
K_NEW, K_SETTLED, K_GAMES = 40.0, 24.0, 10      # a player's first K_GAMES rated games move more
MARGIN_STEP, MARGIN_MAX = 0.1, 1.5              # 1.0 for a one-goal win, +0.1 per extra goal, capped
PAIR_WINDOW = 24 * 3600                         # the same two within this many seconds are damped:
PAIR_WEIGHTS = (1.0, 1.0, 0.5, 0.25, 0.0)       # 1st, 2nd, 3rd, 4th, 5th and later game
PLACEMENT = 5                                   # rated games before a rank shows

# (name, lowest rating, line for the legend): a ladder in steps of 100 up to 1700
TIERS = (('Minor League', 0, 'Grinding in the AHL.'),
         ('Rookie', 1000, 'Cracking the main NHL roster.'),
         ('Pro', 1100, 'An established, everyday NHL regular.'),
         ('Top 6', 1200, "A core contributor driving the team's success."),
         ('Alternate Captain', 1300, 'A trusted veteran and secondary locker-room leader.'),
         ('Captain', 1400, 'The ultimate team leader and franchise anchor.'),
         ('All-Star', 1500, 'Recognized across the league as premium talent.'),
         ('Superstar', 1600, 'A generational talent and MVP contender.'),
         ('Hall of Fame', 1700, 'Legendary, immortalized status.'))
UNRANKED = 'Unranked'


def expected(rating, other):
    """The chance `rating` beats `other`."""
    return 1.0 / (1.0 + 10 ** ((other - rating) / SCALE))


def margin(goal_diff):
    return min(MARGIN_MAX, 1.0 + MARGIN_STEP * (max(1, goal_diff) - 1))


def tier(rating, games):
    """{name, index, placing}: `index` is the position in TIERS (None while unranked), `placing` the rated games to go."""
    if games < PLACEMENT:
        return {'name': UNRANKED, 'index': None, 'placing': PLACEMENT - games}
    idx = max(i for i, (_, low, _blurb) in enumerate(TIERS) if rating >= low)
    return {'name': TIERS[idx][0], 'index': idx, 'placing': 0}


def _blank(name):
    return {'name': name, 'rating': START, 'games': 0, 'w': 0, 'l': 0, 'streak': 0, 'peak': START, 'last': None}


def rate(matches, season_start=0.0):
    """Fold the confirmed, un-voided matches of this season in time order.

    Returns {ratings: {pid: {name, rating, games, w, l, streak, peak, last}},
             deltas: {match_id: {pid: {before, after, delta, expected, weight}}},
             timeline: {pid: [(started, match_id, rating after)]}}.
    `games` counts rated games (a fully damped game is a result but not a rated game); `streak` is wins (+) or losses (-)
    in a row over every confirmed result."""
    state, deltas, timeline, pair_times = {}, {}, {}, {}
    order = sorted((m for m in matches if not m.get('voided') and m['started'] >= season_start),
                   key=lambda m: (m['started'], m['id']))
    for m in order:
        res = H.resolve(m)
        for p in m['players']:                                  # newest name wins (the order is oldest first)
            state.setdefault(p['pid'], _blank(p['name']))['name'] = p['name']
        if res['status'] != H.CONFIRMED:
            continue
        if H.is_team(m) and m.get('mode') == H.ONES:
            _rate_ones(m, res, state, deltas, timeline, pair_times)
            continue
        if H.is_team(m):
            _rate_team(m, res, state, deltas, timeline, pair_times)
            continue
        a, b = (p['pid'] for p in m['players'])
        sa, sb = res['scores'][a], res['scores'][b]
        pair = tuple(sorted((a, b)))
        seen = [t for t in pair_times.setdefault(pair, []) if m['started'] - t < PAIR_WINDOW]
        weight = PAIR_WEIGHTS[min(len(seen), len(PAIR_WEIGHTS) - 1)]
        pair_times[pair] = seen + [m['started']]
        ra, rb = state[a]['rating'], state[b]['rating']
        mult = margin(abs(sa - sb))
        got = {}
        for me, other, won, r_me, r_other in ((a, b, sa > sb, ra, rb), (b, a, sb > sa, rb, ra)):
            row = state[me]
            exp = expected(r_me, r_other)
            k = K_NEW if row['games'] < K_GAMES else K_SETTLED
            delta = k * mult * weight * ((1.0 if won else 0.0) - exp)
            got[me] = {'before': r_me, 'after': r_me + delta, 'delta': delta, 'expected': exp, 'weight': weight}
        for me, won in ((a, sa > sb), (b, sb > sa)):
            row = state[me]
            row['rating'] = got[me]['after']
            row['peak'] = max(row['peak'], row['rating'])
            row['w' if won else 'l'] += 1
            row['games'] += 1 if weight > 0 else 0
            row['streak'] = (max(row['streak'], 0) + 1) if won else (min(row['streak'], 0) - 1)
            row['last'] = m['started']
            timeline.setdefault(me, []).append((m['started'], m['id'], row['rating']))
        deltas[m['id']] = got
    return {'ratings': state, 'deltas': deltas, 'timeline': timeline}


def _rate_team(m, res, state, deltas, timeline, pair_times):
    """A confirmed two-sided team match (0.90.0): each side's chance is `expected` of the two sides' average ratings, and
    each player still in at the end moves by his own K (his game count, as 1v1) times the margin and the damping. The
    damping is keyed on the opposing pairs (every player against every opponent), sharing the 1v1 history: the weight is
    the smallest over those pairs, so swapping one teammate does not dodge it. Players who left are not rated."""
    sides = res['sides']
    if len(sides) != 2 or not all(s['pids'] for s in sides):
        return
    x, y = sides
    pairs = [tuple(sorted((p, q))) for p in x['pids'] for q in y['pids']]
    weight = 1.0
    for pair in pairs:
        seen = [t for t in pair_times.get(pair, []) if m['started'] - t < PAIR_WINDOW]
        weight = min(weight, PAIR_WEIGHTS[min(len(seen), len(PAIR_WEIGHTS) - 1)])
    for pair in pairs:
        pair_times[pair] = [t for t in pair_times.get(pair, []) if m['started'] - t < PAIR_WINDOW] + [m['started']]
    avg = [sum(state[p]['rating'] for p in s['pids']) / len(s['pids']) for s in sides]
    mult = margin(abs(x['score'] - y['score']))
    got = {}
    for s, mine, theirs in ((x, avg[0], avg[1]), (y, avg[1], avg[0])):
        exp = expected(mine, theirs)
        for p in s['pids']:
            row = state[p]
            k = K_NEW if row['games'] < K_GAMES else K_SETTLED
            delta = k * mult * weight * ((1.0 if s['won'] else 0.0) - exp)
            got[p] = {'before': row['rating'], 'after': row['rating'] + delta, 'delta': delta, 'expected': exp,
                      'weight': weight}
    for s in sides:
        for p in s['pids']:
            row = state[p]
            row['rating'] = got[p]['after']
            row['peak'] = max(row['peak'], row['rating'])
            row['w' if s['won'] else 'l'] += 1
            row['games'] += 1 if weight > 0 else 0
            row['streak'] = (max(row['streak'], 0) + 1) if s['won'] else (min(row['streak'], 0) - 1)
            row['last'] = m['started']
            timeline.setdefault(p, []).append((m['started'], m['id'], row['rating']))
    deltas[m['id']] = got


def _rate_ones(m, res, state, deltas, timeline, pair_times):
    """A confirmed Ones game (0.90.0 M8, GUESSED): every pair of players is a 1v1 between them, worth K/(n-1) each so a
    game moves a player about as much as one 1v1 (n players). The better place scores 1 (a shared place 0.5) against
    `expected`, times the margin of their goal difference and the pair's own damping. The winners (most goals) get a win,
    the rest a loss."""
    goals = res['scores']
    pids = [p for p in goals if goals[p] is not None]
    if len(pids) < 2:
        return
    n = len(pids)
    before = {p: state[p]['rating'] for p in pids}
    change = {p: 0.0 for p in pids}
    weights = {p: [] for p in pids}
    for i, p in enumerate(pids):
        for q in pids[i + 1:]:
            pair = tuple(sorted((p, q)))
            seen = [t for t in pair_times.get(pair, []) if m['started'] - t < PAIR_WINDOW]
            weight = PAIR_WEIGHTS[min(len(seen), len(PAIR_WEIGHTS) - 1)]
            pair_times[pair] = seen + [m['started']]
            s_p = 1.0 if goals[p] > goals[q] else 0.0 if goals[p] < goals[q] else 0.5
            mult = margin(abs(goals[p] - goals[q]))
            for me, other, score in ((p, q, s_p), (q, p, 1.0 - s_p)):
                k = K_NEW if state[me]['games'] < K_GAMES else K_SETTLED
                change[me] += k / (n - 1) * mult * weight * (score - expected(before[me], before[other]))
                weights[me].append(weight)
    got = {}
    for p in pids:
        row = state[p]
        weight = max(weights[p])
        won = p in res['winners']
        got[p] = {'before': before[p], 'after': before[p] + change[p], 'delta': change[p],
                  'expected': sum(expected(before[p], before[q]) for q in pids if q != p) / (n - 1), 'weight': weight,
                  'place': res.get('places', {}).get(p)}
        row['rating'] = got[p]['after']
        row['peak'] = max(row['peak'], row['rating'])
        row['w' if won else 'l'] += 1
        row['games'] += 1 if weight > 0 else 0
        row['streak'] = (max(row['streak'], 0) + 1) if won else (min(row['streak'], 0) - 1)
        row['last'] = m['started']
        timeline.setdefault(p, []).append((m['started'], m['id'], row['rating']))
    deltas[m['id']] = got
