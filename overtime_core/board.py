"""The leaderboard view over the rated matches (pure): rows with rank and tier, highlights, recent matches, a player card.

Input is what `overtime_core.rating.rate` returned plus the matches (any order, voided ones already left out) and a set of
hidden pids. Nothing here carries a ShadNet id; a hidden player keeps their place and rating (the others' numbers stay right)
but shows as HIDDEN_NAME with no pid, so the web page cannot open their card.
"""
from . import history as H
from . import rating as R

DAY = 24 * 3600
WEEK = 7 * DAY
HIDDEN_NAME = 'Hidden player'
HOT_STREAK = 3          # wins in a row before the board calls it a streak
ACTIVE_MIN = 3          # games in a week before "most active"
UPSET_BELOW = 0.4       # the winner's chance before the game, below which a win is an upset
FORM = 10               # results in a player's form string
CURVE = 30              # points in a rating curve


def shown(pid, name, hidden):
    return (None, HIDDEN_NAME) if pid in hidden else (pid, name)


def _at(timeline, pid, cutoff):
    """The player's rating just before `cutoff` (START when they had no rated game then)."""
    before = [r for t, _, r in timeline.get(pid, []) if t < cutoff]
    return before[-1] if before else R.START


def _rows(rated, now):
    """Every player with a confirmed result: ranked ones first (rank 1..n by rating), then those still placing (rank None)."""
    state, timeline = rated['ratings'], rated['timeline']
    rows = []
    for pid, s in state.items():
        if s['w'] + s['l'] == 0:
            continue
        t = R.tier(s['rating'], s['games'])
        week = [x for x in timeline.get(pid, []) if x[0] >= now - WEEK]
        rows.append({'pid': pid, 'name': s['name'], 'rating': round(s['rating']), 'tier': t['name'], 'tier_index': t['index'],
                     'placing': t['placing'], 'games': s['games'], 'w': s['w'], 'l': s['l'], 'streak': s['streak'],
                     'peak': round(s['peak']), 'last': s['last'], 'week_games': len(week),
                     'delta7': round(s['rating'] - _at(timeline, pid, now - WEEK)) if week else 0})
    ranked = sorted((r for r in rows if r['tier_index'] is not None),
                    key=lambda r: (-r['rating'], -r['games'], r['name'].lower(), r['pid']))
    placing = sorted((r for r in rows if r['tier_index'] is None), key=lambda r: (-r['rating'], r['name'].lower(), r['pid']))
    for i, r in enumerate(ranked, 1):
        r['rank'] = i
    for r in placing:
        r['rank'] = None
    return ranked + placing


table = _rows


def _highlights(rows, matches, rated, now, hidden):
    out = []

    def who(r):
        pid, name = shown(r['pid'], r['name'], hidden)
        return {'pid': pid, 'name': name}
    climbers = [r for r in rows if r['delta7'] > 0]
    if climbers:
        r = max(climbers, key=lambda r: (r['delta7'], r['rating']))
        out.append({'kind': 'climber', 'title': 'Climber of the week', **who(r), 'value': '+%d' % r['delta7']})
    streaks = [r for r in rows if r['streak'] >= HOT_STREAK]
    if streaks:
        r = max(streaks, key=lambda r: (r['streak'], r['rating']))
        out.append({'kind': 'streak', 'title': 'Hot streak', **who(r), 'value': '%d wins in a row' % r['streak']})
    best = None
    for m in matches:
        res = H.resolve(m)
        d = rated['deltas'].get(m['id'])
        if res['status'] != H.CONFIRMED or d is None or m['started'] < now - WEEK or H.is_team(m):
            continue
        win = res['winner']
        if d[win]['weight'] > 0 and d[win]['expected'] < UPSET_BELOW and (best is None or d[win]['expected'] < best[0]):
            best = (d[win]['expected'], m, win, res)
    if best:
        exp, m, win, res = best
        names = {p['pid']: p for p in m['players']}
        lose = next(p for p in names if p != win)
        wp, wn = shown(win, names[win]['name'], hidden)
        _, ln = shown(lose, names[lose]['name'], hidden)
        out.append({'kind': 'upset', 'title': 'Upset of the week', 'pid': wp, 'name': wn,
                    'value': '%s beat %s %d-%d (%d%% chance)' % (wn, ln, res['scores'][win], res['scores'][lose], round(exp * 100))})
    busy = [r for r in rows if r['week_games'] >= ACTIVE_MIN]
    if busy:
        r = max(busy, key=lambda r: (r['week_games'], r['rating']))
        out.append({'kind': 'active', 'title': 'Most active', **who(r), 'value': '%d games this week' % r['week_games']})
    return out


def recent(matches, rated, hidden, limit=10):
    """The newest confirmed matches with the rating each side gained or lost."""
    out = []
    for m in sorted(matches, key=lambda m: (m['started'], m['id']), reverse=True):
        res = H.resolve(m)
        if res['status'] != H.CONFIRMED:
            continue
        d = rated['deltas'].get(m['id'], {})
        sides = []
        for p in m['players']:
            pid, name = shown(p['pid'], p['name'], hidden)
            row = {'pid': pid, 'name': name, 'team': res['teams'][p['pid']], 'score': res['scores'].get(p['pid']),
                   'delta': round(d[p['pid']]['delta']) if p['pid'] in d else 0, 'won': H.won(res, p['pid'])}
            if H.is_team(m):   # every human, with the side the result put them on (a/b order kept for pairs)
                row.update(side=res['side_of'][p['pid']], left=bool(p.get('left')))
            sides.append(row)
        item = {'id': m['id'], 'started': m['started'], 'sides': sides}
        if H.is_team(m):
            item.update(mode=m.get('mode'), team=True,
                        score=[s['score'] for s in sorted(res['sides'], key=lambda s: s['side'])])
            # the first player of each side leads, so a page that reads sides[0] and sides[1] still shows the two sides
            leads = [next(r for r in sides if r['side'] == s['side'] and not r['left']) for s in
                     sorted(res['sides'], key=lambda s: s['side'])]
            item['sides'] = leads + [r for r in sides if all(r is not x for x in leads)]
        out.append(item)
        if len(out) >= limit:
            break
    return out


def board(matches, rated, now, hidden=frozenset()):
    """{players, ranked, highlights, recent, tiers, placement, updated}: the public leaderboard. Ranked players first (rank
    1..n), then those still placing (rank None). Hidden players are masked (name, no pid) but keep their place."""
    rows = _rows(rated, now)
    players = []
    for r in rows:
        pid, name = shown(r['pid'], r['name'], hidden)
        players.append({**{k: v for k, v in r.items() if k not in ('pid', 'name', 'tier_index', 'week_games')},
                        'pid': pid, 'name': name})
    return {'players': players, 'ranked': len([r for r in rows if r['rank']]),
            'highlights': _highlights(rows, matches, rated, now, hidden), 'recent': recent(matches, rated, hidden),
            'tiers': [{'name': n, 'min': low, 'blurb': b} for n, low, b in R.TIERS], 'placement': R.PLACEMENT, 'updated': now}


def card(matches, rated, pid, now, hidden=frozenset()):
    """A player's public card: rating, rank, form, the rating curve, the opponents and teams. None for an unknown or hidden
    player. `matches` newest first."""
    if pid in hidden:
        return None
    rows = _rows(rated, now)
    row = next((r for r in rows if r['pid'] == pid), None)
    detail = H.player_detail(matches, pid, limit=FORM)
    if row is None or detail is None:
        return None
    results = [m['result'] for m in detail['recent'] if m['result']]

    def opp(o):
        return {'name': HIDDEN_NAME if o['pid'] in hidden else o['name'], 'w': o['w'], 'l': o['l']}
    return {'pid': pid, 'name': row['name'], 'rating': row['rating'], 'tier': row['tier'], 'placing': row['placing'],
            'rank': row['rank'], 'of': len([r for r in rows if r['rank']]), 'w': row['w'], 'l': row['l'],
            'streak': row['streak'], 'peak': row['peak'], 'delta7': row['delta7'], 'form': ''.join(results[:FORM]),
            'gf': detail['gf'], 'ga': detail['ga'],
            'curve': [[t, round(r)] for t, _, r in rated['timeline'].get(pid, [])][-CURVE:],
            'opponents': [opp(o) for o in detail['opponents'][:5]], 'teams': detail['teams'][:5]}
