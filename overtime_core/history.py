"""Match history: pure rules shared by the server (which stores the matches) and the app (which draws them).

A match is the pairing of two players. Each player may *claim* a result: their team and the score for / against, from the
game's own report or typed in the app. Two claims that mirror each other confirm the match; only confirmed matches count
in the standings. Plan docs/plans/m4-match-history.md, facts docs/notes/match-history.md.

A match here is a plain dict (what `overtime_server.matches.MatchBook` returns):
  {id, started, code, rules, players: [{pid, name}, {pid, name}],
   claims: {pid: {team, opp_team, for, against, source}}}
`pid` is a salted hash of the ShadNet account id, so the public history never shows an id one could play as.
"""
import hashlib
import re

from . import calendar

CONFIRMED, DISPUTED, WAITING, OPEN = 'confirmed', 'disputed', 'waiting', 'open'
LEFT_AFTER = 3600       # seconds a game's own report waits for the other side before it counts alone (Legacy's rule)
FORFEIT_SCORE = (1, 0)  # a match the other player quit on the ice: the one who stayed wins 1-0 (rating margin 1)
MAX_SCORE = 99
TEAM_TEXT = re.compile(r'^[A-Z]{2,4}$')
STAT_KEYS = ('shots', 'shotsa', 'hits', 'pims', 'ppg', 'ppo', 'ppga', 'fow', 'fol', 'passc', 'passa', 'toa', 'bs', 'bag', 'bao')
STAT_MAX = 100000      # time on attack is in seconds; nothing else comes near
# Live match 1 of 2026-11-07 (docs/notes/game-report-fields.md): the game's `pims` is penalty time in seconds (480 with
# four minors, matching the opponent's 4 power plays), and its `shotsa` and `fol` were 0 on both sides. So pims is kept
# in minutes, and shots against / faceoffs lost come from the opponent's report (its shots / fow) instead.
SECONDS_TO_MINUTES = ('pims',)
NOT_SENT = ('shotsa', 'fol')
TEAMS = sorted(calendar.SLOTS)        # the codes the app offers; the game's own abbreviation is accepted too


def pid(ext, salt):
    """The public id of a player: 10 hex characters of sha256(salt, ext)."""
    return hashlib.sha256(('%s:%d' % (salt, int(ext))).encode()).hexdigest()[:10]


def clean_stats(raw):
    """The game's own per-player numbers (docs/notes/game-report-fields.md): only the allowlisted names, whole numbers
    0..STAT_MAX, penalty time in minutes, without the numbers the game leaves at 0 (NOT_SENT). None when nothing usable
    is left."""
    if not isinstance(raw, dict):
        return None
    out = {k: raw[k] for k in STAT_KEYS if k not in NOT_SENT and isinstance(raw.get(k), int)
           and not isinstance(raw.get(k), bool) and 0 <= raw[k] <= STAT_MAX}
    for k in SECONDS_TO_MINUTES:
        if k in out:
            out[k] = round(out[k] / 60)
    return out or None


def with_opponent(mine, theirs):
    """His stats with shots against and faceoffs lost taken from the opponent's report (its shots and fow), when it
    sent them; a copy."""
    out = dict(mine or {})
    if theirs:
        for k, src in (('shotsa', 'shots'), ('fol', 'fow')):
            if theirs.get(src) is not None:
                out[k] = theirs[src]
    return out


# How a player played: the game's own numbers (STAT_KEYS) as a box score and as totals over his games. Each is one side's
# report, so a game's box score lines his report up with the opponent's (his shots against stand in for the other's
# shots when the opponent sent none).
BOX = (('shots', 'Shots'), ('hits', 'Hits'), ('pims', 'Penalty minutes'), ('ppg', 'Power play goals'),
       ('ppo', 'Power play chances'), ('fow', 'Faceoffs won'), ('passc', 'Passes completed'),
       ('passa', 'Passes tried'), ('toa', 'Time on attack'), ('bs', 'Blocked shots'), ('bag', 'Breakaway goals'),
       ('bao', 'Breakaways'))
# A Shootout's report (NHLSOReportBase::PlayerReport, lab 2026-11-07) holds gf, ga, shots and shotsa: the goals are the
# score, so its box score is the attempts alone, and its numbers stay out of the Versus totals.
SHOOTOUT_BOX = (('shots', 'Attempts'),)


def _pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else None


def box_score(mine, theirs, mode='versus'):
    """The rows of one game's box score, [{key, label, me, them}]: a side with no number shows None. `mine`, `theirs`:
    the two claims' stats (clean_stats) or None; a Shootout shows its attempts only."""
    mine, theirs = mine or {}, theirs or {}
    out = []
    for key, label in (SHOOTOUT_BOX if mode == 'shootout' else BOX):
        me, them = mine.get(key), theirs.get(key)
        if key == 'shots' and them is None:
            them = mine.get('shotsa')
        if key == 'fow':
            them = theirs.get('fow', mine.get('fol'))
        if me is not None or them is not None:
            out.append({'key': key, 'label': label, 'me': me, 'them': them})
    return out


def stat_summary(games):
    """Totals, per-game averages and rates over `games` ([{'stats': his claim's stats, 'for': goals, 'against': goals}],
    the games that have stats): {games, totals, avg, rates}. None for no game."""
    if not games:
        return None
    totals, counted = {}, {}
    for g in games:
        for k, v in g['stats'].items():
            totals[k] = totals.get(k, 0) + v
            counted[k] = counted.get(k, 0) + 1
    t = totals.get
    faceoffs = [g['stats'] for g in games if g['stats'].get('fow') is not None and g['stats'].get('fol') is not None]
    goals_for = sum(g['for'] for g in games if g['stats'].get('shots'))
    goals_against = sum(g['against'] for g in games if g['stats'].get('shotsa'))
    return {'games': len(games), 'totals': totals,
            'avg': {k: round(v / counted[k], 1) for k, v in totals.items()},
            'rates': {'shooting': _pct(goals_for, sum(g['stats'].get('shots', 0) for g in games if g['stats'].get('shots'))),
                      'saving': None if not t('shotsa') else _pct(max(0, t('shotsa') - goals_against), t('shotsa')),
                      'faceoffs': _pct(sum(s['fow'] for s in faceoffs), sum(s['fow'] + s['fol'] for s in faceoffs)),
                      'passing': _pct(t('passc', 0), t('passa', 0)),
                      'power_play': _pct(t('ppg', 0), t('ppo', 0))}}


def shootout_summary(games):
    """A player's Shootout numbers over `games` (as stat_summary's, Shootout games only): {games, shots, goals, faced,
    allowed, rates: {shooting, saving}}. None for no game."""
    if not games:
        return None
    shot = [g for g in games if g['stats'].get('shots')]
    faced = [g for g in games if g['stats'].get('shotsa')]
    shots, goals = sum(g['stats']['shots'] for g in shot), sum(g['for'] for g in shot)
    seen, allowed = sum(g['stats']['shotsa'] for g in faced), sum(g['against'] for g in faced)
    return {'games': len(games), 'shots': shots, 'goals': goals, 'faced': seen, 'allowed': allowed,
            'rates': {'shooting': _pct(goals, shots), 'saving': _pct(max(0, seen - allowed), seen)}}


def team_code(value):
    """`value` as a team abbreviation (upper case, 2-4 letters), or None when it is not one."""
    text = str(value or '').strip().upper()
    return text if TEAM_TEXT.match(text) else None


def score(value):
    """`value` as a score 0..99, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        n = int(value)
    except ValueError:
        return None
    return n if 0 <= n <= MAX_SCORE else None


GAME_DRIFT = 1   # goals the two game reports of one match may differ by, each side's own score kept (match 75, 2026-11-10)


def _own_scores_agree(x, y):
    """Threes: each game's report has its own goals right and the opponent's wrong (match 79 of 2026-11-10, lost 14-2:
    the winner reported 14-1, the loser 2-10; match 78 8-3 and 2-6; match 75 8-5 and 4-8). The two own scores decide:
    they must differ and each report must name the winner they name."""
    return (x['for'] != y['for'] and (x['for'] > x['against']) == (x['for'] > y['for'])
            and (y['for'] > y['against']) == (y['for'] > x['for']))


def _agree(x, y, mode=None):
    """Two claims of one match say the same thing: they mirror, or both are the game's own reports with the same winner
    and scores within GAME_DRIFT of each other (the game itself gave 8-5 to one side and 4-8 to the other for one match, an
    opponent score off by one while the winner and the own scores agreed), or, in Threes, two game reports whose own
    scores agree on the winner (_own_scores_agree). Entries typed in the app must mirror exactly."""
    if (x['for'], x['against']) == (y['against'], y['for']):
        return True
    if x.get('source') != 'game' or y.get('source') != 'game':
        return False
    if mode in OWN_SCORE_MODES and _own_scores_agree(x, y):
        return True
    return ((x['for'] > x['against']) == (y['against'] > y['for'])
            and abs(x['for'] - y['against']) <= GAME_DRIFT and abs(y['for'] - x['against']) <= GAME_DRIFT)


OWN_SCORE_MODES = ('threes', 'chel_gm3on3')   # GM3on3 is the Threes game in WoC: assumed to share its report quirk (0.90.0)


# --- team matches (0.90.0): a World of Chel row with more than one human on a side, or more than two sides ----------
# Such a match carries `sides` (the number of sides) and each player its seat `side` and `left` (left the game before
# its end). A claim may carry the `side` the game's own report put the player on (teamSide); it wins over the seat.

def is_team(match):
    return bool(match.get('sides'))


def _side_map(match):
    """{pid: side}: the side each player's own report names, else the seat."""
    claims = match.get('claims') or {}
    out = {}
    for p in match['players']:
        c = claims.get(p['pid']) or {}
        out[p['pid']] = c['side'] if isinstance(c.get('side'), int) else p.get('side', 0)
    return out


def _same(x, y, mode):
    """Two claims of one side say the same thing (each from that side's view)."""
    return _agree(x, {**y, 'for': y['against'], 'against': y['for']}, mode)


def _resolve_team(match):
    """A team match: confirmed when every side that has a human still in the game reported, the claims within each side
    agree and the two sides mirror (`_agree`). Only two-sided matches confirm here (Ones has its own placements). A player
    who left is neither credited nor rated; the rest stands. Lone sides, disputes and no reports count for no one."""
    claims = match.get('claims') or {}
    side_of = _side_map(match)
    present = [p['pid'] for p in match['players'] if not p.get('left')]
    by_side = {}
    for pid in present:
        by_side.setdefault(side_of[pid], []).append(pid)
    teams = {p['pid']: (claims.get(p['pid']) or {}).get('team') for p in match['players']}
    out = {'status': OPEN, 'teams': teams, 'scores': {}, 'against': {}, 'winner': None, 'winners': [],
           'waiting_for': None, 'left': None, 'forfeit': False, 'side_of': side_of, 'sides': []}
    said = {s: [claims[p] for p in pids if p in claims] for s, pids in by_side.items()}
    if not any(said.values()):
        return out
    if len(by_side) != 2 or not all(said.values()):
        out['status'] = WAITING if all(_side_agrees(c, match.get('mode')) for c in said.values() if c) else DISPUTED
        return out
    (s0, c0), (s1, c1) = sorted(said.items())
    if not (_side_agrees(c0, match.get('mode')) and _side_agrees(c1, match.get('mode'))
            and _agree(c0[0], c1[0], match.get('mode'))):
        out['status'] = DISPUTED
        return out
    score = {s0: c0[0]['for'], s1: c1[0]['for']}            # each side's own score
    win = s0 if c0[0]['for'] > c0[0]['against'] else s1
    out['status'] = CONFIRMED
    for s, other in ((s0, s1), (s1, s0)):
        out['sides'].append({'side': s, 'pids': by_side[s], 'score': score[s], 'won': s == win})
        for pid in by_side[s]:
            out['scores'][pid], out['against'][pid] = score[s], score[other]
    out['winners'] = list(by_side[win])
    out['winner'] = out['winners'][0]
    return out


ONES = 'chel_ones'


def _resolve_ones(match):
    """Ones (0.90.0 M8, GUESSED: the lab never reached a Ones game): 2-4 players, each on a side of his own. A claim carries
    `places` {pid: goals}, every player's goals from that game's own report. Confirmed when two reports of players still in
    the game name the same players with each one's goals within GAME_DRIFT; the first of those reports gives the goals.
    The most goals win (ties share a place). A lone report waits, reports that disagree dispute the game."""
    claims = match.get('claims') or {}
    side_of = _side_map(match)
    present = [p['pid'] for p in match['players'] if not p.get('left')]
    out = {'status': OPEN, 'teams': {p['pid']: None for p in match['players']}, 'scores': {}, 'against': {},
           'winner': None, 'winners': [], 'waiting_for': None, 'left': None, 'forfeit': False, 'side_of': side_of,
           'sides': [], 'places': {}}
    said = [claims[p]['places'] for p in present if (claims.get(p) or {}).get('places')]
    if not said:
        return out

    def same(x, y):
        return set(x) == set(y) and all(abs(x[k] - y[k]) <= GAME_DRIFT for k in x)
    agreed = next((x for i, x in enumerate(said) for y in said[i + 1:] if same(x, y)), None)
    if agreed is None:
        out['status'] = WAITING if len(said) == 1 else DISPUTED
        return out
    goals = {pid: agreed[pid] for pid in present if pid in agreed}
    if len(goals) < 2:
        out['status'] = WAITING
        return out
    best = max(goals.values())
    out['status'] = CONFIRMED
    for pid, g in goals.items():
        out['scores'][pid] = g
        out['against'][pid] = max(v for q, v in goals.items() if q != pid)
        out['places'][pid] = 1 + sum(1 for v in goals.values() if v > g)
        out['sides'].append({'side': side_of[pid], 'pids': [pid], 'score': g, 'won': g == best})
    out['winners'] = [pid for pid, g in goals.items() if g == best]
    out['winner'] = out['winners'][0]
    return out


def _resolve_any_team(match):
    return _resolve_ones(match) if match.get('mode') == ONES else _resolve_team(match)


def _side_agrees(claims, mode):
    return all(_same(claims[0], c, mode) for c in claims[1:])


def won(result, pid):
    """`pid` was on the winning side of a resolved match."""
    return pid in result['winners'] if 'winners' in result else result['winner'] == pid


def credited(match, result):
    """The pids a confirmed result counts for: both players of a pair, the players still in at the end of a team match."""
    return [p['pid'] for p in match['players'] if result['scores'].get(p['pid']) is not None]


def goals_against(match, result, pid):
    if 'against' in result:
        return result['against'].get(pid)
    return result['scores'][next(p['pid'] for p in match['players'] if p['pid'] != pid)]


def opponents(match, pid, result=None):
    """The players on the other side(s) from `pid`."""
    if not is_team(match):
        return [p for p in match['players'] if p['pid'] != pid]
    side_of = (result or {}).get('side_of') or _side_map(match)
    return [p for p in match['players'] if side_of.get(p['pid']) != side_of.get(pid)]


def mates(match, pid, result=None):
    """`pid`'s teammates (never itself); [] in a pair."""
    if not is_team(match):
        return []
    side_of = (result or {}).get('side_of') or _side_map(match)
    return [p for p in match['players'] if p['pid'] != pid and side_of.get(p['pid']) == side_of.get(pid)]


def full(match):
    """A fully played match: both sides reported and the two results agree (`_agree`). Only these are shown and rated
    (MatchBook._snapshot); a forfeit, a lone report, a dispute and a match with no result are left out (2026-11-10)."""
    if is_team(match):
        return _resolve_any_team(match)['status'] == CONFIRMED
    claims = match.get('claims') or {}
    if len(claims) != 2:
        return False
    x, y = claims.values()
    return _agree(x, y, match.get('mode'))


def pending_until(match):
    """When a match that is not full stops being shown, or None for one never shown (a forfeit, a dispute). A match with
    no report yet shows for LEFT_AFTER seconds from its start, a lone report for LEFT_AFTER from the report, so the two
    can still enter or confirm the result (the app's form); after that it is gone without a trace."""
    claims = match.get('claims') or {}
    if is_team(match):   # shown while its sides still report: LEFT_AFTER from the latest report
        if _resolve_any_team(match)['status'] == DISPUTED:
            return None
        return max([c['at'] for c in claims.values()] + [match['started']]) + LEFT_AFTER
    if match.get('forfeit') or len(claims) > 1:
        return None
    since = next(iter(claims.values()))['at'] if claims else match['started']
    return since + LEFT_AFTER


def resolve(match):
    """What the claims of a match add up to:
    {status, teams: {pid: team|None}, scores: {pid: score|None}, winner: pid|None, waiting_for: pid|None, left: pid|None,
     forfeit: bool}.
    confirmed = both claimed and mirror (A for == B against, A against == B for); disputed = both claimed, they differ;
    waiting = one claim (its scores are shown as provisional); open = none. A lone claim marked `lapsed` (the game's own
    report, LEFT_AFTER seconds old: matches.py marks it) is confirmed, with `left` the player who never reported: the
    one who left pays for it, and a report of his own, however late, puts the two claims to the normal test.
    `match['forfeit']` (pid) quit the match on the ice (the server saw him leave it in play): confirmed, a FORFEIT_SCORE
    loss for him, whatever single or disputed claims say; only two mirroring claims (both games reported a finished
    match) stand over it. A team match (`is_team`) follows `_resolve_team` and adds winners, against, side_of, sides."""
    if is_team(match):
        return _resolve_any_team(match)
    a, b = (p['pid'] for p in match['players'])
    claims = match.get('claims') or {}
    ca, cb = claims.get(a), claims.get(b)
    teams = {a: (ca or {}).get('team') or (cb or {}).get('opp_team'),
             b: (cb or {}).get('team') or (ca or {}).get('opp_team')}
    scores = {a: None, b: None}
    out = {'status': OPEN, 'teams': teams, 'scores': scores, 'winner': None, 'waiting_for': None, 'left': None,
           'forfeit': False}
    if ca and cb:
        if _agree(ca, cb, match.get('mode')):
            out['status'] = CONFIRMED
            scores[a], scores[b] = ca['for'], cb['for']     # each side's own score
            out['winner'] = a if ca['for'] > ca['against'] else b
        else:
            out['status'] = DISPUTED
    elif ca or cb:
        who, c = (a, ca) if ca else (b, cb)
        other = b if who == a else a
        out['status'], out['waiting_for'] = WAITING, other
        scores[who], scores[other] = c['for'], c['against']
        if c.get('lapsed'):
            out['status'], out['waiting_for'], out['left'] = CONFIRMED, None, other
            out['winner'] = who if c['for'] > c['against'] else other
    gone = match.get('forfeit')
    if gone in (a, b) and not (ca and cb and out['status'] == CONFIRMED):
        stay = b if gone == a else a
        scores[stay], scores[gone] = FORFEIT_SCORE
        out.update(status=CONFIRMED, winner=stay, waiting_for=None, left=gone, forfeit=True)
    return out


def mode_records(matches, pid):
    """{mode: {w, l}} of the confirmed matches of `pid` in each game mode (versus, shootout, threes): the numbers the game's own
    hubs show per mode, while the rating is one over all of them."""
    out = {'versus': {'w': 0, 'l': 0}, 'shootout': {'w': 0, 'l': 0}, 'threes': {'w': 0, 'l': 0}}
    for m in matches:
        r = m.get('result') or resolve(m)
        if r['status'] != CONFIRMED or r['scores'].get(pid) is None:
            continue
        rec = out.setdefault(m.get('mode') or 'versus', {'w': 0, 'l': 0})
        rec['w' if won(r, pid) else 'l'] += 1
    return out


def _blank(name):
    return {'name': name, 'w': 0, 'l': 0, 'gf': 0, 'ga': 0}


def standings(matches):
    """[{pid, name, w, l, played, gf, ga, last}] of the confirmed matches, best first (wins, then fewer losses, then
    more games, then name). `matches` newest first, so a player's name is the one of its latest match."""
    table, last = {}, {}
    for m in matches:
        for p in m['players']:
            table.setdefault(p['pid'], _blank(p['name']))
    for m in matches:
        r = resolve(m)
        if r['status'] != CONFIRMED:
            continue
        for mine in credited(m, r):
            row = table[mine]
            row['w' if won(r, mine) else 'l'] += 1
            row['gf'] += r['scores'][mine]
            row['ga'] += goals_against(m, r, mine)
            last[mine] = max(last.get(mine, 0), m['started'])
    rows = [{'pid': k, **v, 'played': v['w'] + v['l'], 'last': last.get(k)} for k, v in table.items()]
    rows = [r for r in rows if r['played']]
    return sorted(rows, key=lambda r: (-r['w'], r['l'], -r['played'], r['name'].lower(), r['pid']))


def _bump(table, key, won):
    row = table.setdefault(key, {'w': 0, 'l': 0})
    row['w' if won else 'l'] += 1


def _by_games(rows):
    return sorted(rows, key=lambda x: (-(x['w'] + x['l']), -x['w'], str(x.get('name') or x.get('team'))))


def player_detail(matches, who, limit=20):
    """One player's history: the record, per opponent, per team played with / against, and the latest matches (any
    status, newest first) seen from this player's side. None when the player is in no match."""
    name = None
    record = _blank('')
    faced, with_team, against_team, recent, played, shootouts = {}, {}, {}, [], [], []
    for m in matches:
        mine = next((p for p in m['players'] if p['pid'] == who), None)
        if mine is None:
            continue
        r = resolve(m)
        them = opponents(m, who, r) or [{'pid': None, 'name': ''}]
        theirs = them[0]
        name = name or mine['name']
        gone = r['status'] == CONFIRMED and r['scores'].get(who) is None   # left a team match: not credited
        win = won(r, who) if r['status'] == CONFIRMED and not gone else None
        if win is not None:
            record['w' if win else 'l'] += 1
            record['gf'] += r['scores'][who]
            record['ga'] += goals_against(m, r, who)
            for o in them:
                _bump(faced, (o['pid'], o['name']), win)
            if r['teams'][who]:
                _bump(with_team, r['teams'][who], win)
            if r['teams'].get(theirs['pid']):
                _bump(against_team, r['teams'][theirs['pid']], win)
        mine_stats = ((m.get('claims') or {}).get(who) or {}).get('stats')
        their_stats = ((m.get('claims') or {}).get(theirs['pid']) or {}).get('stats')
        mode = m.get('mode') or 'versus'
        # Threes' report class is not known and WoC's is the club one (sk*/gl* keys): no Versus totals from either
        against = r['against'].get(who) if is_team(m) else r['scores'][theirs['pid']]
        if win is not None and mine_stats and mode in ('versus', 'shootout'):
            (shootouts if mode == 'shootout' else played).append(
                {'stats': with_opponent(mine_stats, their_stats), 'for': r['scores'][who], 'against': against})
        if len(recent) < limit:
            row = {'id': m['id'], 'started': m['started'], 'status': r['status'], 'rules': m.get('rules'),
                   'mode': mode, 'box': box_score(mine_stats, their_stats, mode),
                   'opponent': theirs, 'team': r['teams'][who], 'opp_team': r['teams'].get(theirs['pid']),
                   'for': r['scores'].get(who), 'against': against,
                   'result': None if win is None else 'W' if win else 'L'}
            if is_team(m):
                row.update(opponents=them, mates=mates(m, who, r), left=bool(mine.get('left')))
            recent.append(row)
    if name is None:
        return None
    return {'pid': who, 'name': name, 'w': record['w'], 'l': record['l'], 'played': record['w'] + record['l'],
            'gf': record['gf'], 'ga': record['ga'],
            'opponents': _by_games({'pid': k[0], 'name': k[1], **v} for k, v in faced.items()),
            'teams': _by_games({'team': k, **v} for k, v in with_team.items()),
            'against': _by_games({'team': k, **v} for k, v in against_team.items()),
            'recent': recent, 'stats': stat_summary(played), 'shootout': shootout_summary(shootouts)}
