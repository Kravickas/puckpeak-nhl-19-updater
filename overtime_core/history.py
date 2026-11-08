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
    match) stand over it."""
    a, b = (p['pid'] for p in match['players'])
    claims = match.get('claims') or {}
    ca, cb = claims.get(a), claims.get(b)
    teams = {a: (ca or {}).get('team') or (cb or {}).get('opp_team'),
             b: (cb or {}).get('team') or (ca or {}).get('opp_team')}
    scores = {a: None, b: None}
    out = {'status': OPEN, 'teams': teams, 'scores': scores, 'winner': None, 'waiting_for': None, 'left': None,
           'forfeit': False}
    if ca and cb:
        if (ca['for'], ca['against']) == (cb['against'], cb['for']):
            out['status'] = CONFIRMED
            scores[a], scores[b] = ca['for'], cb['for']
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
        if r['status'] != CONFIRMED or pid not in r['scores']:
            continue
        rec = out.setdefault(m.get('mode') or 'versus', {'w': 0, 'l': 0})
        rec['w' if r['winner'] == pid else 'l'] += 1
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
        for p in m['players']:
            row, mine = table[p['pid']], p['pid']
            other = next(q['pid'] for q in m['players'] if q['pid'] != mine)
            row['w' if r['winner'] == mine else 'l'] += 1
            row['gf'] += r['scores'][mine]
            row['ga'] += r['scores'][other]
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
    opponents, with_team, against_team, recent, played, shootouts = {}, {}, {}, [], [], []
    for m in matches:
        mine = next((p for p in m['players'] if p['pid'] == who), None)
        if mine is None:
            continue
        theirs = next(p for p in m['players'] if p['pid'] != who)
        name = name or mine['name']
        r = resolve(m)
        won = r['winner'] == who if r['status'] == CONFIRMED else None
        if won is not None:
            record['w' if won else 'l'] += 1
            record['gf'] += r['scores'][who]
            record['ga'] += r['scores'][theirs['pid']]
            _bump(opponents, (theirs['pid'], theirs['name']), won)
            if r['teams'][who]:
                _bump(with_team, r['teams'][who], won)
            if r['teams'][theirs['pid']]:
                _bump(against_team, r['teams'][theirs['pid']], won)
        mine_stats = ((m.get('claims') or {}).get(who) or {}).get('stats')
        their_stats = ((m.get('claims') or {}).get(theirs['pid']) or {}).get('stats')
        mode = m.get('mode') or 'versus'
        if won is not None and mine_stats and mode != 'threes':   # Threes' report class is not known: no totals yet
            (shootouts if mode == 'shootout' else played).append(
                {'stats': with_opponent(mine_stats, their_stats), 'for': r['scores'][who],
                 'against': r['scores'][theirs['pid']]})
        if len(recent) < limit:
            recent.append({'id': m['id'], 'started': m['started'], 'status': r['status'], 'rules': m.get('rules'),
                           'mode': mode, 'box': box_score(mine_stats, their_stats, mode),
                           'opponent': theirs, 'team': r['teams'][who], 'opp_team': r['teams'][theirs['pid']],
                           'for': r['scores'][who], 'against': r['scores'][theirs['pid']],
                           'result': None if won is None else 'W' if won else 'L'})
    if name is None:
        return None
    return {'pid': who, 'name': name, 'w': record['w'], 'l': record['l'], 'played': record['w'] + record['l'],
            'gf': record['gf'], 'ga': record['ga'],
            'opponents': _by_games({'pid': k[0], 'name': k[1], **v} for k, v in opponents.items()),
            'teams': _by_games({'team': k, **v} for k, v in with_team.items()),
            'against': _by_games({'team': k, **v} for k, v in against_team.items()),
            'recent': recent, 'stats': stat_summary(played), 'shootout': shootout_summary(shootouts)}
