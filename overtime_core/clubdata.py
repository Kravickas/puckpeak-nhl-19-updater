"""The club rosters of the data pack (NHL Legacy's `leagues` part, the leagues' own feeds) in the shape of the NHL 27 pack
(nhl27.py), for rosterupdate.rebuild_league: who plays where comes from the feeds, ratings stay NHL 27's where it has
the player (the pack's `ratings_full` is the same list).

The pack's team slots and league numbers are another game's: a club is only ever taken by its name. Its CHL is one
league of three parts (its league_id 9 OHL, 10 QMJHL, 11 WHL). The ECHL, the ICE Hockey League, HockeyAllsvenskan and the
rest of Europe stay NHL 27's: the pack has no feed for them (its `norway` is a league NHL 19 does not have).
"""
import collections
import re
import unicodedata

from .matching import norm

CHL_PARTS = {9: 'ohl', 10: 'qmjhl', 11: 'whl'}
LEAGUES = ('ahl', 'liiga', 'extraliga', 'shl', 'del', 'nl')
POSITIONS = {'L': 'LW', 'R': 'RW', 'C': 'C', 'D': 'D', 'G': 'G', 'F': 'C'}
TAGS = (*LEAGUES, *CHL_PARTS.values())
ORDER = ('liiga', 'extraliga', 'shl', 'del', 'nl', 'ahl', 'ohl', 'qmjhl', 'whl')    # a player two leagues list plays in the
                                                                                    # first (Legacy's league order)


def _key(*names):
    text = ' '.join(n or '' for n in names)
    return re.sub('[^a-z]', '', unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower())


def _same_first(a, b):
    """Could these be one person's first names (Sam / Samuel, Will / William, Viliam / Jozef Viliam)? A last name and a
    birth date are shared by twins, whose names part sooner."""
    return any(x[:2] == y[:2] for x in norm(a).split() for y in norm(b).split())


def _spare(league):
    """A league's `extra` clubs. The CHL lists Rouyn-Noranda and Val-d'Or twice, as `extra` under the OHL's number too."""
    named = {team['full'] for team in league.get('teams') or []}
    return [team for team in league.get('extra') or [] if team['full'] not in named]


def club_players(pack):
    """{league tag: [(club name, player)]} of the pack's `leagues` (slotted clubs and the `extra` ones the pack's game
    has no slot for: NHL 19 may have)."""
    out = {}
    for name, league in ((pack or {}).get('leagues') or {}).items():
        if name not in LEAGUES and name != 'chl':
            continue
        for team in (league.get('teams') or []) + _spare(league):
            tag = name if name != 'chl' else CHL_PARTS.get(team.get('league_id'))
            if tag:
                out.setdefault(tag, []).extend((team['full'], p) for p in team.get('players') or [] if p.get('birth'))
    return out


def listed(pack):
    """Everyone a league's feed lists, as name keys and as (last name key, birth date): NHL.com and the leagues win over a
    contract (Legacy contract_keeps, by name: a feed's birth date can be an estimate, and NHL.com's Alexander Petrovic is
    the AHL's Alex)."""
    out = set()
    for name, league in ((pack or {}).get('leagues') or {}).items():
        if name in LEAGUES or name == 'chl':
            for team in (league.get('teams') or []) + _spare(league):
                for p in team.get('players') or []:
                    out.add(_key(p['first'], p['last']))
                    if p.get('birth'):
                        out.add((_key(p['last']), tuple(p['birth'])))
    return frozenset(out)


def farm_clubs(pack):
    """{NHL club code: (its AHL club's name, players its list holds)}: the club that holds most of the organisation's
    players (`org` in the AHL's feed)."""
    ahl = ((pack or {}).get('leagues') or {}).get('ahl') or {}
    best = {}
    for team in (ahl.get('teams') or []) + (ahl.get('extra') or []):
        players = team.get('players') or []
        orgs = collections.Counter(p['org'] for p in players if p.get('org'))
        for org, n in orgs.items():
            if n > best.get(org, (0,))[0]:
                best[org] = (n, team['full'], len(players))
    return {org: (club, size) for org, (_n, club, size) in best.items()}


def spare_clubs(pack):
    """The names of the clubs the pack's game has no slot for (`extra`): the last to take a slot here, so a league short
    of slots leaves out the same clubs."""
    return frozenset(team['full'] for league in ((pack or {}).get('leagues') or {}).values() for team in _spare(league))


def club_towns(pack):
    """{club name: (town, abbreviation)} of the pack's clubs."""
    return {team['full']: (team['short'], team.get('abbr')) for name, league in ((pack or {}).get('leagues') or {}).items()
            if name in LEAGUES or name == 'chl' for team in (league.get('teams') or []) + _spare(league)
            if team.get('full') and team.get('short')}


def club_lines(pack):
    """{club name: {slot: [first, last, birth year]}} of the pack's `club_lines` (keyed by its game's team slots)."""
    part = (pack or {}).get('club_lines') or {}
    return {team['full']: part[str(team['slot'])]['slots'] for league in ((pack or {}).get('leagues') or {}).values()
            for team in (league.get('teams') or []) + (league.get('extra') or [])
            if (part.get(str(team.get('slot'))) or {}).get('slots')}


def _countries(pack):
    """{league tag: its one country} of the pack's leagues."""
    leagues = pack.get('leagues') or {}
    out = {tag: (leagues.get(tag) or {}).get('country') for tag in LEAGUES}
    out.update({tag: (leagues.get('chl') or {}).get('country') for tag in CHL_PARTS.values()})
    return {tag: country for tag, country in out.items() if country}


def merged(pack, nhl27, farmed=()):
    """A copy of the NHL 27 pack `nhl27` whose rows of the leagues TAGS are the data pack's rosters: a player NHL 27
    has keeps its row (its rating orders a club) on the feed's club; anyone else gets a row without ratings. `feed` on a
    row is the list's own entry for him (rosterupdate._feed_facts). A row of NHL 27's those leagues no longer list is
    kept with no league: he still plays somewhere, so he is no retirement. `farmed` [(AHL club, player)]: the deals on
    nobody's list (rosterupdate.with_absent) play there. None without both packs."""
    if not pack or not nhl27 or not nhl27.get('players'):
        return None
    clubs = club_players(pack)
    if not clubs:
        return None
    if farmed:
        clubs.setdefault('ahl', []).extend(farmed)
    fields = nhl27['fields']
    known, by_name, by_birth = {}, {}, {}
    for row in nhl27['players']:
        if row.get('birth'):
            known[(_key(row['first'], row['last']), tuple(row['birth']))] = row
            by_birth.setdefault((_key(row['last']), tuple(row['birth'])), []).append(row)
            by_name.setdefault((row.get('league'), _key(row['first'], row['last'])), []).append(row)
    used, seen, rows = set(), set(), []
    for tag in ORDER:
        for club, p in clubs.get(tag) or ():
            name = _key(p['first'], p['last'])
            if (name, tuple(p['birth'])) in seen:   # a feed can list a player twice, or on two clubs: the first stands
                continue
            seen.add((name, tuple(p['birth'])))
            row = known.get((name, tuple(p['birth'])))
            if row is None:     # NHL 27's birthdates have typos: the only one of that name in that league
                same = by_name.get((tag, name)) or []
                # another form of his name (NHL 27's Samuel, the list's Sam): one person, not a second bio
                twin = [r for r in by_birth.get((_key(p['last']), tuple(p['birth']))) or ()
                        if _same_first(r['first'], p['first'])]
                row = same[0] if len(same) == 1 else twin[0] if len(twin) == 1 else None
            pos = POSITIONS.get(p.get('pos'))
            if row is not None and id(row) not in used:
                used.add(id(row))
                rows.append(dict(row, league=tag, team=club, feed=p))
            elif row is None and pos:
                rows.append({'first': p['first'], 'last': p['last'], 'birth': list(p['birth']), 'pos': pos,
                             'hand': p.get('shoots'), 'league': tag, 'team': club, 'feed': p,
                             'height': p['height_cm'] / 2.54 if p.get('height_cm') else None,
                             'weight': p['weight_kg'] * 2.20462 if p.get('weight_kg') else None,
                             'v': [0] * len(fields['goalie' if pos == 'G' else 'skater'])})
    for row in nhl27['players']:
        if id(row) in used:
            continue
        rows.append(dict(row, league=None, team=None) if row.get('league') in clubs else row)
    return dict(nhl27, players=rows, towns=club_towns(pack), spare=spare_clubs(pack), club_lines=club_lines(pack),
                equipment=(pack.get('equipment') or {}).get('players'), countries=_countries(pack))
