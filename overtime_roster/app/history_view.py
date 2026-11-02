"""The `history` part of the multiplayer slice, drawn from the server's `/api/history` answer (docs/ui/multiplayer.md).

Pure functions: the answer in, plain rows out. The server did the arithmetic (overtime_core.history); this only picks
the words and puts "you" first.
"""
from overtime_core import history as H, rating as R

STATUS = {
    H.CONFIRMED: ('good', 'Confirmed'),
    H.DISPUTED: ('bad', 'The two results differ'),
    H.OPEN: ('info', 'No result yet'),
}


def ago(seconds):
    """'now', '5 min ago', '3 h ago', '2 d ago'."""
    try:
        s = max(0, int(seconds))
    except (TypeError, ValueError):
        return ''
    if s < 45:
        return 'now'
    if s < 5400:
        return f'{max(1, round(s / 60))} min ago'
    if s < 129600:
        return f'{round(s / 3600)} h ago'
    return f'{round(s / 86400)} d ago'


def _side(p, r, you):
    return {'pid': p['pid'], 'name': p['name'], 'you': p['pid'] == you, 'team': r['teams'].get(p['pid']),
            'score': r['scores'].get(p['pid']), 'won': r['winner'] == p['pid']}


def _status(r, names, you):
    if r['status'] == H.WAITING:
        who = r['waiting_for']
        if who == you:
            return 'caution', 'Result entered: confirm yours'
        return 'info', f'Waiting for {names[who]}'
    if r.get('left'):
        return 'good', f"{names[r['left']]} left: counted without a report"
    return STATUS[r['status']]


def match_row(m, you, now):
    """One match of the Recent matches list, me first when I played in it. `entry` is what the "Enter result" form
    starts with (my own claim, else the mirror of the partner's), None when I may not enter one (not mine, or confirmed)."""
    r = m['result']
    mine = next((p for p in m['players'] if p['pid'] == you), None)
    other = next((p for p in m['players'] if p is not mine), None) if mine else None
    order = [mine, other] if mine else m['players']
    names = {p['pid']: p['name'] for p in m['players']}
    tone, text = _status(r, names, you)
    entry = None
    if mine and r['status'] != H.CONFIRMED:
        c = (m.get('claims') or {}).get(you) or {}
        sf = c.get('for', r['scores'].get(you))
        sa = c.get('against', r['scores'].get(other['pid']))
        entry = {'opponent': other['name'], 'team': c.get('team') or r['teams'].get(you) or '',
                 'score_for': sf, 'score_against': sa, 'again': bool(c)}
    return {'id': m['id'], 'ago': ago(now - m['started']), 'rules': m.get('rules') or '', 'status': r['status'],
            'tone': tone, 'text': text, 'mine': bool(mine), 'players': [_side(p, r, you) for p in order], 'entry': entry,
            'delta': (m.get('deltas') or {}).get(you) if mine and r['status'] == H.CONFIRMED else None}


def player_row(row, you):
    return {'pid': row['pid'], 'name': row['name'], 'you': row['pid'] == you, 'w': row['w'], 'l': row['l'],
            'played': row['played'], 'diff': row['gf'] - row['ga'], 'rating': row.get('rating'), 'tier': row.get('tier'),
            'rank': row.get('rank'), 'placing': row.get('placing') or 0, 'streak': row.get('streak') or 0}


def next_tier(rating):
    """The next rank above `rating` as {name, at, to_go, progress} (progress 0..1 inside the current band), None at the top."""
    for i, (name, low, _blurb) in enumerate(R.TIERS):
        if low > rating:
            base = R.TIERS[i - 1][1] if i else 0
            return {'name': name, 'at': low, 'to_go': max(1, round(low - rating)),
                    'progress': round(min(1.0, max(0.0, (rating - base) / (low - base))), 3) if i > 1 else None}
    return None


def ladder(mine):
    """Every rank, the top one first: {name, min, blurb, you}; `you` marks my rank once I have one."""
    now = mine['tier'] if mine and mine['ranked'] else None
    return [{'name': n, 'min': low, 'blurb': b, 'you': n == now} for n, low, b in reversed(R.TIERS)]


def rating_view(r):
    """My rating line (the server's `rating`), None for a server without ratings or before my first confirmed match."""
    if not isinstance(r, dict):
        return None
    ranked = r.get('rank') is not None
    return {'rating': r['rating'], 'tier': r['tier'], 'ranked': ranked, 'placing': r.get('placing') or 0,
            'rank': r.get('rank'), 'of': r.get('of') or 0, 'change': r.get('last_change'), 'streak': r.get('streak') or 0,
            'record': f"{r.get('w', 0)}\u2013{r.get('l', 0)}", 'hidden': bool(r.get('hidden')), 'next': next_tier(r['rating'])}


def banner_for(matches, seen):
    """'Review ready' for my newest confirmed match that came after the last one I looked at; None otherwise."""
    if seen is None:
        return None
    row = next((m for m in matches if m['mine'] and m['status'] == H.CONFIRMED), None)
    if row is None or row['id'] <= seen:
        return None
    won = next((p['won'] for p in row['players'] if p['you']), False)
    change = f" ({row['delta']:+d})" if row.get('delta') is not None else ''
    return {'match': row['id'], 'text': ('You won' if won else 'You lost') + f" against {row['players'][1]['name']}{change}"}


def _band(rating):
    """Index in TIERS of the rank `rating` falls in (the first for anything below)."""
    return max((i for i, (_n, low, _b) in enumerate(R.TIERS) if rating >= low), default=0)


def result_card(raw):
    """The HUD card for my newest confirmed match: the score, the rating counting from what it was before to what it is, the
    rank and the way to the next one, a `rank_up` name when the game crossed a line. None without a rated match."""
    you, r = raw.get('me'), raw.get('rating')
    m = next((m for m in raw.get('matches') or []
              if m['result']['status'] == H.CONFIRMED and any(p['pid'] == you for p in m['players'])), None)
    delta = (m.get('deltas') or {}).get(you) if m else None
    if m is None or delta is None or not isinstance(r, dict):
        return None
    res = m['result']
    other = next(p['pid'] for p in m['players'] if p['pid'] != you)
    sf, sa = res['scores'].get(you), res['scores'].get(other)
    won = res['winner'] == you
    now = r['rating']
    before = now - delta
    ranked = r.get('rank') is not None
    nxt = next_tier(now)
    band = R.TIERS[_band(now)][1]
    crossed = ranked and delta > 0 and _band(before) < _band(now)
    rank_up = r['tier'] if crossed else None
    return {'match': m['id'], 'title': 'Final', 'sub': f"{sf} - {sa} {'win' if won else 'loss'}", 'won': won,
            'rating_from': before, 'rating_to': now, 'tier': r['tier'] if ranked else None, 'placing': r.get('placing') or 0,
            'placing_of': R.PLACEMENT, 'next_name': nxt['name'] if nxt and ranked else None, 'next_at': nxt['at'] if nxt else None, 'band_low': band,
            'rank_up': rank_up}


def latest_mine(raw):
    """The id of my newest confirmed match in a history answer, 0 when there is none."""
    you = raw.get('me')
    for m in raw.get('matches') or []:
        if m['result']['status'] == H.CONFIRMED and any(p['pid'] == you for p in m['players']):
            return m['id']
    return 0


def detail_view(d, you, now):
    if not d:
        return None
    recent = [{'id': m['id'], 'ago': ago(now - m['started']), 'status': m['status'], 'result': m['result'],
               'opponent': m['opponent']['name'], 'team': m['team'], 'opp_team': m['opp_team'], 'for': m['for'],
               'against': m['against'], 'rules': m.get('rules') or ''} for m in d['recent']]
    return {'pid': d['pid'], 'name': d['name'], 'you': d['pid'] == you, 'w': d['w'], 'l': d['l'], 'played': d['played'],
            'gf': d['gf'], 'ga': d['ga'], 'opponents': d['opponents'], 'teams': d['teams'], 'against': d['against'],
            'recent': recent}


def toa_text(seconds):
    """Time on attack as 'm:ss'."""
    s = max(0, int(seconds or 0))
    return f'{s // 60}:{s % 60:02d}'


def _shown(key, value):
    if value is None:
        return '-'
    return toa_text(value) if key == 'toa' else str(value)


RATES = (('shooting', 'Shooting'), ('saving', 'Saves'), ('faceoffs', 'Faceoffs won'), ('passing', 'Passes completed'),
         ('power_play', 'Power play'))


def games_view(d, now):
    """My games card from the server's `games` (my detail): the record, the numbers over every game that has them, and each
    game with its score and box score. None while I have no game."""
    if not d or not d['recent']:
        return None
    st = d.get('stats')
    overall = None
    if st:
        t = st['totals']
        overall = {'games': st['games'],
                   'avg': [{'key': k, 'label': label, 'value': _shown(k, st['avg'].get(k)),
                            'total': _shown(k, t.get(k))} for k, label in H.BOX if k in st['avg']],
                   'rates': [{'label': label, 'value': f"{st['rates'][k]:g}%"} for k, label in RATES
                             if st['rates'].get(k) is not None]}
    games = [{'id': m['id'], 'ago': ago(now - m['started']), 'status': m['status'], 'result': m['result'],
              'opponent': m['opponent']['name'], 'team': m['team'], 'opp_team': m['opp_team'], 'for': m['for'],
              'against': m['against'], 'rules': m.get('rules') or '',
              'box': [{'label': r['label'], 'me': _shown(r['key'], r['me']), 'them': _shown(r['key'], r['them'])}
                      for r in m.get('box') or []]} for m in d['recent']]
    return {'w': d['w'], 'l': d['l'], 'played': d['played'], 'gf': d['gf'], 'ga': d['ga'], 'overall': overall,
            'games': games, 'with_stats': sum(1 for g in games if g['box'])}


def review_view(rv):
    """The opened review (the server's, already worded), None when none is open."""
    if not isinstance(rv, dict):
        return None
    return {k: rv.get(k) for k in ('match', 'won', 'headline', 'opponent', 'team', 'opp_team', 'for', 'against', 'rating',
                                   'tier', 'tags', 'facts', 'tips', 'has_stats')}


def build(raw, now, supported=True, error='', busy=False, entering=None, form_error='', seen=None, review=None):
    """The slice's `history`: {supported, loaded, error, busy, matches, players, detail, form, rating, banner, review}."""
    out = {'supported': supported, 'loaded': raw is not None, 'error': error, 'busy': busy,
           'matches': [], 'players': [], 'detail': None, 'games': None, 'form': None, 'rating': None, 'banner': None,
           'review': review_view(review), 'ladder': ladder(None)}
    if raw is None:
        return out
    you = raw.get('me')
    out['matches'] = [match_row(m, you, now) for m in raw.get('matches') or []]
    out['players'] = [player_row(r, you) for r in raw.get('players') or []]
    out['detail'] = detail_view(raw.get('detail'), you, now)
    out['games'] = games_view(raw.get('games'), now)
    out['rating'] = rating_view(raw.get('rating'))
    out['ladder'] = ladder(out['rating'])
    out['banner'] = banner_for(out['matches'], seen)
    if entering is not None:
        row = next((m for m in out['matches'] if m['id'] == entering and m['entry']), None)
        if row:
            out['form'] = {'match': row['id'], 'teams': H.TEAMS, 'error': form_error, **row['entry']}
    return out
