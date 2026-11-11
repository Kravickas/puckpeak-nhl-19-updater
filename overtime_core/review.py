"""The post-match review (pure): how a player did in a confirmed match, from the result and, when the game sent them, the stats.

`facts` come from results alone (rating change, streak, record against this opponent and with this team, the margin).
`tips` come from a few rules over the game's own numbers (docs/notes/game-report-fields.md); with no stats there are none,
and the app says the detailed tips need the game's report. Deterministic, no clock, no network.
"""
from . import history as H
from . import rating as R

CLOSE, BLOWOUT = 1, 4               # goal difference
OUTSHOT, OUTSHOOT = 0.42, 0.58      # shot share below / above which the shots tell a story
LOW_CONVERSION, MIN_SHOTS = 0.06, 20
PENALTY_MIN, PENALTY_GAP = 6, 2     # penalty minutes, and how many more than the opponent
FACEOFF_LOW, MIN_FACEOFFS = 0.40, 15
PASS_LOW, MIN_PASSES = 0.60, 20
MAX_TIPS = 4


def _pct(a, b):
    return round(100 * a / (a + b)) if a + b else None


def tips(mine, theirs, won, goals_for):
    """Up to MAX_TIPS lines from the two players' stats (`theirs` may be missing; the opponent's shots and faceoffs won
    stand for his shots against and faceoffs lost, `mine['shotsa']` / `mine['fol']` only when it sent none)."""
    if not mine:
        return []
    theirs = theirs or {}
    mine = H.with_opponent(mine, theirs)
    out = []
    shots, shots_a = mine.get('shots'), mine.get('shotsa')
    if shots is not None and shots_a is not None and shots + shots_a:
        share = shots / (shots + shots_a)
        if share < OUTSHOT:
            out.append('You were outshot %d-%d, so you spent the game defending. Clean breakouts help: short passes up the '
                       'boards and a forward kept high.' % (shots, shots_a))
        elif share > OUTSHOOT and not won:
            out.append('You outshot them %d-%d and still lost. Chase better shots (one-timers, screens, rebounds) rather '
                       'than more shots.' % (shots, shots_a))
        if shots >= MIN_SHOTS and goals_for / shots < LOW_CONVERSION:
            out.append('%d goals on %d shots (%d%%). Look for rebounds and traffic in front instead of long shots.'
                       % (goals_for, shots, round(100 * goals_for / shots)))
    pims, opp_pims = mine.get('pims'), theirs.get('pims', 0)
    if pims is not None and pims >= PENALTY_MIN and pims >= opp_pims + PENALTY_GAP:
        out.append('%d penalty minutes against %d. Fewer hooks and trips: every penalty gives away the power play.' % (pims, opp_pims))
    ppo, ppg = mine.get('ppo'), mine.get('ppg')
    if ppo is not None and ppo >= 3 and not ppg:
        out.append('0 for %d on the power play. Move the puck to a one-timer spot before shooting.' % ppo)
    if mine.get('ppga'):
        out.append('You allowed %d power-play goal%s. Keep a tight box and pressure the points.' % (mine['ppga'], '' if mine['ppga'] == 1 else 's'))
    fow, fol = mine.get('fow'), mine.get('fol')
    if fow is not None and fol is not None and fow + fol >= MIN_FACEOFFS and fow / (fow + fol) < FACEOFF_LOW:
        out.append('You won %d%% of faceoffs. Pick your best taker for the key draws and back him up with a winger.' % _pct(fow, fol))
    passc, passa = mine.get('passc'), mine.get('passa')
    if passc is not None and passa is not None and passa >= MIN_PASSES and passc / passa < PASS_LOW:
        out.append('%d%% of your passes found a teammate. Shorter, safer passes under pressure.' % round(100 * passc / passa))
    return out[:MAX_TIPS]


def _games_before(timeline, deltas, pid, match_id):
    return sum(1 for _, mid, _ in timeline.get(pid, []) if mid != match_id and mid < match_id
               and deltas.get(mid, {}).get(pid, {}).get('weight', 0) > 0)


def review(matches, rated, pid, match_id=None):
    """The review of `match_id` (else the player's latest confirmed match) for `pid`; None when there is none.
    `matches`: every match, newest first."""
    mine = [m for m in matches if any(p['pid'] == pid for p in m['players']) and H.resolve(m)['status'] == H.CONFIRMED]
    m = next((x for x in mine if x['id'] == match_id), None) if match_id is not None else (mine[0] if mine else None)
    d = rated['deltas'].get(m['id'], {}).get(pid) if m else None
    if m is None or d is None:
        return None
    res = H.resolve(m)
    them = H.opponents(m, pid, res)
    opp = them[0] if len(them) == 1 else {'pid': them[0]['pid'], 'name': ', '.join(p['name'] for p in them)}
    won, gf, ga = H.won(res, pid), res['scores'][pid], H.goals_against(m, res, pid)
    team, opp_team = res['teams'][pid], res['teams'].get(opp['pid'])
    rivals = {p['pid'] for p in them}
    before, after = d['before'], d['after']
    games_b = _games_before(rated['timeline'], rated['deltas'], pid, m['id'])
    games_a = games_b + (1 if d['weight'] > 0 else 0)
    t_before, t_after = R.tier(before, games_b), R.tier(after, games_a)

    older = sorted((x for x in mine if (x['started'], x['id']) <= (m['started'], m['id'])), key=lambda x: (x['started'], x['id']))
    streak, h2h, with_team = 0, [0, 0], [0, 0]
    for x in older:
        r = H.resolve(x)
        if r['scores'].get(pid) is None:   # left that team match: not credited
            continue
        w = H.won(r, pid)
        streak = (max(streak, 0) + 1) if w else (min(streak, 0) - 1)
        if {p['pid'] for p in H.opponents(x, pid, r)} == rivals:
            h2h[0 if w else 1] += 1
        if team and r['teams'][pid] == team:
            with_team[0 if w else 1] += 1

    tags, facts = [], []
    exp = d['expected']
    if won and exp < 0.4:
        tags.append('Upset')
    elif won and exp >= 0.6:
        tags.append('Expected win')
    elif not won and exp >= 0.6:
        tags.append('Upset loss')
    if abs(gf - ga) <= CLOSE:
        tags.append('Close game')
    elif abs(gf - ga) >= BLOWOUT:
        tags.append('Blowout')
    if abs(streak) >= 3:
        tags.append('%d %s in a row' % (abs(streak), 'wins' if streak > 0 else 'losses'))
    if t_after['index'] is not None and t_before['index'] is not None and t_after['index'] != t_before['index']:
        tags.append('Promoted' if t_after['index'] > t_before['index'] else 'Demoted')
    if t_before['index'] is None and t_after['index'] is not None:
        tags.append('Rank unlocked')

    facts.append('%s %s %d-%d%s.' % ('You beat' if won else 'You lost to', opp['name'], gf, ga,
                                     ' with %s against %s' % (team, opp_team) if team and opp_team else ''))
    facts.append('Rating %+d (%d to %d); you had a %d%% chance before the game.' % (round(d['after'] - d['before']), round(before),
                                                                                   round(after), round(100 * exp)))
    if d['weight'] < 1:
        facts.append('You met %s again within a day, so this game counted for %s of a normal one.'
                     % (opp['name'], 'none' if d['weight'] == 0 else '%d%%' % round(100 * d['weight'])))
    if t_after['index'] is None:
        facts.append('%d more rated game%s to get your rank.' % (t_after['placing'], '' if t_after['placing'] == 1 else 's'))
    elif 'Promoted' in tags or 'Demoted' in tags:
        facts.append('%s to %s.' % ('Promoted' if 'Promoted' in tags else 'Demoted', t_after['name']))
    if abs(streak) >= 2:
        facts.append('%d %s in a row.' % (abs(streak), 'wins' if streak > 0 else 'losses'))
    if sum(h2h) > 1:
        facts.append('Against %s you are now %d-%d.' % (opp['name'], h2h[0], h2h[1]))
    if team and sum(with_team) > 1:
        facts.append('With %s you are %d-%d.' % (team, with_team[0], with_team[1]))
    if abs(gf - ga) <= CLOSE:
        facts.append('One goal decided it.')

    claims = m.get('claims') or {}
    my_stats, their_stats = (claims.get(pid) or {}).get('stats'), (claims.get(opp['pid']) or {}).get('stats')
    advice = tips(my_stats, their_stats, won, gf)
    delta = round(d['after'] - d['before'])
    if won:
        headline = '%s over %s, %+d' % ('Upset win' if 'Upset' in tags else 'Win', opp['name'], delta)
    else:
        headline = 'Loss to %s, %+d' % (opp['name'], delta)
    return {'match': m['id'], 'started': m['started'], 'won': won, 'headline': headline, 'opponent': opp['name'],
            'team': team, 'opp_team': opp_team, 'for': gf, 'against': ga,
            'rating': {'before': round(before), 'after': round(after), 'delta': delta, 'chance': round(100 * exp),
                       'weight': d['weight']},
            'tier': {'before': t_before['name'], 'after': t_after['name']}, 'tags': tags, 'facts': facts, 'tips': advice,
            'has_stats': bool(my_stats)}
