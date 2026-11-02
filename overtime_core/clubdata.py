"""The club rosters of the data pack (NHL Legacy's `leagues` part, the leagues' own feeds) in the shape of the NHL 27 pack
(nhl27.py), for rosterupdate.rebuild_league: who plays where comes from the feeds, ratings and contracts stay NHL 27's.

The pack's team slots and league numbers are another game's: a club is only ever taken by its name. Its CHL is one
league of three parts (its league_id 9 OHL, 10 QMJHL, 11 WHL). The AHL, the ECHL, the ICE Hockey League, HockeyAllsvenskan
and the rest of Europe stay NHL 27's: the pack has no feed of its own for them (its AHL is NHL 27's source too, and its
`norway` is a league NHL 19 does not have).
"""
import re
import unicodedata

CHL_PARTS = {9: 'ohl', 10: 'qmjhl', 11: 'whl'}
LEAGUES = ('liiga', 'extraliga', 'shl', 'del', 'nl')
POSITIONS = {'L': 'LW', 'R': 'RW', 'C': 'C', 'D': 'D', 'G': 'G', 'F': 'C'}
TAGS = (*LEAGUES, *CHL_PARTS.values())


def _key(*names):
    text = ' '.join(n or '' for n in names)
    return re.sub('[^a-z]', '', unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower())


def club_players(pack):
    """{league tag: [(club name, player)]} of the pack's `leagues` (slotted clubs and the `extra` ones the pack's game
    has no slot for: NHL 19 may have)."""
    out = {}
    for name, league in ((pack or {}).get('leagues') or {}).items():
        if name not in LEAGUES and name != 'chl':
            continue
        for team in (league.get('teams') or []) + (league.get('extra') or []):
            tag = name if name != 'chl' else CHL_PARTS.get(team.get('league_id'))
            if tag:
                out.setdefault(tag, []).extend((team['full'], p) for p in team.get('players') or [] if p.get('birth'))
    return out


def club_towns(pack):
    """{club name: (town, abbreviation)} of the pack's clubs."""
    return {team['full']: (team['short'], team.get('abbr')) for name, league in ((pack or {}).get('leagues') or {}).items()
            if name in LEAGUES or name == 'chl' for team in (league.get('teams') or []) + (league.get('extra') or [])
            if team.get('full') and team.get('short')}


def merged(pack, nhl27):
    """A copy of the NHL 27 pack `nhl27` whose rows of the leagues TAGS are the data pack's rosters: a player NHL 27
    has keeps its row (its rating orders a club, its position stands) on the feed's club; anyone else gets a row
    without ratings. A row of NHL 27's those leagues no longer list is kept with no league: he still plays somewhere,
    so he is no retirement. None without both packs."""
    if not pack or not nhl27 or not nhl27.get('players'):
        return None
    clubs = club_players(pack)
    if not clubs:
        return None
    fields = nhl27['fields']
    known, by_name = {}, {}
    for row in nhl27['players']:
        if row.get('birth'):
            known[(_key(row['first'], row['last']), tuple(row['birth']))] = row
            by_name.setdefault((row.get('league'), _key(row['first'], row['last'])), []).append(row)
    used, seen, rows = set(), set(), []
    for tag, players in sorted(clubs.items()):
        for club, p in players:
            name = _key(p['first'], p['last'])
            if (name, tuple(p['birth'])) in seen:   # a feed can list a player twice, or on two clubs: the first stands
                continue
            seen.add((name, tuple(p['birth'])))
            row = known.get((name, tuple(p['birth'])))
            if row is None:     # NHL 27's birthdates have typos: the only one of that name in that league
                same = by_name.get((tag, name)) or []
                row = same[0] if len(same) == 1 else None
            pos = POSITIONS.get(p.get('pos'))
            if row is not None and id(row) not in used:
                used.add(id(row))
                rows.append(dict(row, league=tag, team=club))
            elif row is None and pos:
                rows.append({'first': p['first'], 'last': p['last'], 'birth': list(p['birth']), 'pos': pos,
                             'hand': p.get('shoots'), 'league': tag, 'team': club,
                             'height': p['height_cm'] / 2.54 if p.get('height_cm') else None,
                             'weight': p['weight_kg'] * 2.20462 if p.get('weight_kg') else None,
                             'v': [0] * len(fields['goalie' if pos == 'G' else 'skater'])})
    for row in nhl27['players']:
        if id(row) in used:
            continue
        rows.append(dict(row, league=None, team=None) if row.get('league') in clubs else row)
    return dict(nhl27, players=rows, towns=club_towns(pack))
