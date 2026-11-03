"""Reading the organisations' contracts from the open roster for the Front office tab (office_ctl), read only.
docs/ui/office.md, "How Python reads one organisation".

An organisation is an NHL club (the rail's id; Seattle 399, whose players are on the custom team 499) with three
groups of exhibitionplayerbiotable rows (game_id < rosterupdate.SPECIAL_IDS):

    nhl         the bios on the club with a deal (contractstatus 0); only these count toward the cap
    farm        the AHL club that holds most of the organisation's other players (`proteam`; exhibitionteams'
                ahlaffiliate is stale for six clubs in NHL 19's own roster, Update relinks it: teams.FARMS_2026),
                and those players on it
    prospects   the organisation's other `proteam` bios (rights, juniors, Europe, free agents)

Money is in dollars (contractdollars and extensiondollars x labels.CONTRACT_UNIT) and comes out as text: $12.5M,
$850K. The cap and the lowest payroll are the league layer's (overlay.CAP_2026 / ROWS_2026) when Game patch serves
it, else NHL 19's own (CAP_STOCK / ROWS_STOCK). Years are the seasons a deal has left: a roster that carries the
expansion career's extra season (rosterupdate.expansion_contracts: contractlength + 1, the patch's default roster,
the online roster, an Update with NHL 27) shows one less; such a roster is known by having no one-season NHL deal at all.
"""
import collections
import datetime
import json
import unicodedata

from overtime_core import overlay, rosterupdate, teams as T

from . import labels as L

BIOS = 'exhibitionplayerbiotable'
PLAYERS = 'exhibitionplayers'
TEAMS = 'exhibitionteams'
SEASONS = 5                                     # the cap view's seasons, 2026-27 first
GROUPS = ('nhl', 'farm', 'prospects', 'free')
SORTS = ('name', 'pos', 'age', 'ovr', 'cap', 'years', 'ext')
ORDER = {'C': 0, 'LW': 1, 'RW': 2, 'F': 3, 'D': 4, 'G': 5}   # the Pos column's order
AHL = 1                                         # labels.LEAGUES
SEATTLE = T.SEATTLE_PLAY_NOW                    # the rail's Seattle; its players are on the custom team 499
SEATTLE_FARM = 'Coachella Valley Firebirds'     # customteams 498: Update fills it (customrostertable), not listed here
TIGHT = 2_000_000                               # cap space under this shows caution
MARKER = 20                                     # NHL deals a roster needs before its lengths tell the extra season
CONTRACT = 'Change his cap hit, years and one-way or two-way. Save writes it; My edits keeps it for every update.'
NO_DEAL = 'He has no contract (his rights belong to a team): only free agents can sign here, from the Free agents group.'
SIGN = ('Sign him with this club: cap hit, years and one-way or two-way. Save writes it. He joins as a spare: Edit lines '
        'puts him in a line. A roster update rebuilds the free agents, so sign after updating.')
PICK_FIRST = 'Click a player with a contract first.'
CAP_MIN = 0.1                                   # $M: a deal's lowest cap hit here
NOTE = 'Real dollars, as the game shows them with Game patch on. The cap counts the NHL roster.'
NOTE_STOCK = "Real dollars against NHL 19's own cap: Game patch is off. The cap counts the NHL roster."
UNREAD = "This roster's contracts could not be read. Open the roster again in Setup."


# --- money in the player's words ---------------------------------------------------------------------------------
def money(dollars):
    """$12.5M (three decimals at most, trailing zeros dropped), $850K under $999,500, a minus sign below zero."""
    sign, d = ('-' if dollars < 0 else ''), abs(int(dollars))
    if d < 999500:
        return f'{sign}${round(d / 1000):,}K'
    text = f'{d / 1e6:.3f}'.rstrip('0').rstrip('.')
    return f'{sign}${text}M'


def short(dollars):
    """The rail's cap space: one decimal ($9.8M, -$0.1M)."""
    return f"{'-' if dollars < 0 else ''}${abs(dollars) / 1e6:.1f}M"


def tone(space):
    """A season's cap space: 'bad' over the cap, 'caution' under $2M left, else 'good'."""
    return 'bad' if space < 0 else 'caution' if space < TIGHT else 'good'


def plural(n, one, many):
    return f'{n} {one if n == 1 else many}'


# --- one bio ---------------------------------------------------------------------------------------------------------
def cap_hit(bio):
    """A bio's cap hit in dollars (0: no contract)."""
    return int(bio.get('contractdollars') or 0) * L.CONTRACT_UNIT


def counts(bio):
    """Whether a bio is a real player the office lists (not one of the game's special ids)."""
    return int(bio.get('game_id', rosterupdate.SPECIAL_IDS)) < rosterupdate.SPECIAL_IDS


def lengthened(bio):
    """Whether rosterupdate.expansion_contracts gives this bio's deal the extra season (its own test)."""
    return (counts(bio) and bio.get('contractstatus') == 0
            and (bio.get('proteam', -1) != -1 or bio.get('team') == T.SEATTLE)
            and bool(bio.get('contractlength')) and bool(bio.get('contractdollars')))


def carries_expansion(bios):
    """Whether the roster carries the expansion career's extra season: it has NHL deals and not one of them runs a
    single season (expansion_contracts makes every one at least two; a roster without it has hundreds of one-season
    deals)."""
    deals = [b for b in bios if lengthened(b)]
    return len(deals) >= MARKER and all(int(b['contractlength']) >= 2 for b in deals)


def years_left(bio, expansion=True):
    """Seasons left on the deal. A roster the patch (or the Update) wrote carries the expansion career's extra
    season (rosterupdate.expansion_contracts: contractlength + 1), so those show one less (when 2 or more)."""
    years = int(bio.get('contractlength') or 0)
    return years - 1 if expansion and years >= 2 and lengthened(bio) else years


def age_on(born, today, shift):
    """Age on `today` of a birth date stored `shift` years back (teams.year_shift: an updated roster keeps the game's
    2018 clock), as the game shows it."""
    if born is None:
        return None
    try:
        born = born.replace(year=born.year + shift)
    except ValueError:                              # 29 February
        born = datetime.date(born.year + shift, born.month, 28)
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


# --- the league's money ----------------------------------------------------------------------------------------------
def league_served(game_dir, status=None):
    """Whether Game patch serves the league layer (the 2026-27 cap): `status` (overlay.status, when the Game patch
    tab read it), else the patch's own record. Nothing found: False."""
    if status is not None:
        return 'league' in (status.get('layers') or {})
    try:
        with open(overlay.state_path(game_dir), encoding='utf-8') as f:
            return 'league' in (json.load(f).get('layers') or {})
    except (OSError, ValueError, AttributeError, TypeError):
        return False


def league_money(season, served=True):
    """Five seasons from `season`: [{label, cap, floor}] in dollars. `served`: the league layer's numbers (cap $104M
    in 2026-27, then its rises), else NHL 19's own."""
    (floor, cap), rows = (overlay.CAP_2026, overlay.ROWS_2026) if served else (overlay.CAP_STOCK, overlay.ROWS_STOCK)
    floor, cap = floor * 100_000, cap * 100_000
    out = []
    for k in range(SEASONS):
        floor += rows[0][k] * 1000
        cap += rows[1][k] * 1000
        year = season + k
        out.append({'label': f'{year}-{(year + 1) % 100:02d}', 'cap': cap, 'floor': floor})
    return out


# --- reading the organisations -----------------------------------------------------------------------------------
def read(session, clubs, season, today):
    """Every organisation of the open roster: {'orgs': {rail id: org}, 'farm_of': {AHL id: rail id of its club},
    'expansion': bool}. `clubs`: the NHL rail's club ids (Seattle 399).
    'free' lists the free agents nobody holds (best overall first). org = {'club', 'bio_team', 'farm' (AHL team id or None), 'nhl', 'farm_rows', 'prospects'}; a row is {'key'
    (game_id), 'name', 'pos', 'age', 'ovr', 'cap' (dollars, 0: rights only), 'years', 'two_way', 'ext' ([years,
    dollars, two_way] or None), 'where' (team id, -1 free agents, or None)}."""
    s = session
    bios = [b for b in s.rows[BIOS] if counts(b)]
    expansion = carries_expansion(bios)
    shift = T.year_shift(season)
    teams = s.rows[TEAMS]
    ahl = {t['index'] for t in teams if t.get('league') == AHL}
    free = set()
    by_index = {p['index']: p for p in s.rows[PLAYERS]}
    for pi in s.free_agents:
        p = by_index.get(pi)
        if p and p.get('table') == 0:
            free.add(p['playerid'])
    by_team = collections.defaultdict(list)
    by_org = collections.defaultdict(list)
    for b in bios:
        by_team[b['team']].append(b)
        if b['proteam'] >= 0:
            by_org[b['proteam']].append(b)

    def ovr(b):
        _t, _i, ai = s.ai(b)
        return (ai.get('skill_overall', ai.get('c_overall')) if ai else None) or None

    def row(b):
        dollars = cap_hit(b) if b['contractstatus'] == 0 else 0
        ext = None
        if b.get('extensionlength') and b.get('extensiondollars'):
            ext = [int(b['extensionlength']), int(b['extensiondollars']) * L.CONTRACT_UNIT,
                   bool(b.get('extensionis2way'))]
        where = -1 if b['game_id'] in free else (b['team'] if b['team'] >= 0 else None)
        pos = L.POSITIONS[b['position']] if 0 <= b['position'] < len(L.POSITIONS) else '?'
        return {'key': b['game_id'], 'name': s.name(b), 'pos': pos, 'age': age_on(s.birth(b), today, shift),
                'ovr': ovr(b), 'cap': dollars, 'years': years_left(b, expansion) if dollars else 0,
                'two_way': bool(b.get('contractis2way')) if dollars else False, 'ext': ext, 'where': where}

    orgs, farm_of = {}, {}
    for org in clubs:
        club = T.SEATTLE if org == SEATTLE else org
        roster = [b for b in by_team.get(club, []) if b['contractstatus'] == 0]
        taken = {b['game_id'] for b in roster}
        # Seattle's players have no proteam (theirs is a custom team): its farm and prospects are empty
        mine = [b for b in by_org.get(org, []) if b['game_id'] not in taken] if org != SEATTLE else []
        votes = collections.Counter(b['team'] for b in mine if b['team'] in ahl)
        farm = votes.most_common(1)[0][0] if votes else None
        farm_rows = [b for b in mine if farm is not None and b['team'] == farm]
        taken |= {b['game_id'] for b in farm_rows}
        if farm is not None:
            farm_of.setdefault(farm, org)
        orgs[org] = {'club': org, 'bio_team': club, 'farm': farm, 'nhl': [row(b) for b in roster],
                     'farm_rows': [row(b) for b in farm_rows],
                     'prospects': [row(b) for b in mine if b['game_id'] not in taken]}
    pool = [row(b) for b in bios if b['game_id'] in free and b['team'] == -1]
    pool.sort(key=lambda r: (-(r['ovr'] or 0), r['name']))
    return {'orgs': orgs, 'farm_of': farm_of, 'expansion': expansion, 'free': pool}


def org_of(data, team):
    """The organisation a rail team belongs to: an NHL club itself, an AHL club its parent's; else None."""
    if team in data['orgs']:
        return team
    return data['farm_of'].get(team)


# --- what the tab shows --------------------------------------------------------------------------------------------
def seasons(rows, money_rows):
    """What an organisation's NHL roster commits in each season: a deal while years > k, then its extension while
    years <= k < years + extension years. [{label, cap, floor, committed, signed, space}]."""
    out = []
    for k, m in enumerate(money_rows):
        committed = signed = 0
        for r in rows:
            ext = r['ext']
            cap = r['cap'] if r['years'] > k else ext[1] if ext and k < r['years'] + ext[0] else 0
            if cap:
                committed += cap
                signed += 1
        out.append(dict(m, committed=committed, signed=signed, space=m['cap'] - committed))
    return out


def _name_key(name):
    plain = unicodedata.normalize('NFKD', name)
    return ''.join(ch for ch in plain if not unicodedata.combining(ch)).casefold()


def first_dir(key):
    """A new sort column's order: name and position A to Z, the others high to low."""
    return 1 if key in ('name', 'pos') else -1


def sort_rows(rows, key, direction):
    """Rows by one column (`direction` 1 up, -1 down); ties by name, A to Z either way."""
    def value(r):
        if key == 'name':
            return _name_key(r['name'])
        if key == 'pos':
            return ORDER.get(r['pos'], 6)
        if key == 'ext':
            return r['ext'][1] if r['ext'] else 0
        v = r.get(key)
        return -1 if v is None else v
    by_name = sorted(rows, key=lambda r: _name_key(r['name']))
    return sorted(by_name, key=value, reverse=direction < 0)    # stable: equal values keep the names' order


def deal_text(r):
    """A deal in words: '$14M x 8 years, one-way, then 8 x $20.4M.' (Legacy's deal_text)."""
    if not r['cap']:
        return 'No contract: his rights belong to the team.'
    text = f"{money(r['cap'])} x {plural(r['years'], 'year', 'years')}, {'two-way' if r['two_way'] else 'one-way'}"
    if r['ext']:
        text += f", then {r['ext'][0]} x {money(r['ext'][1])}"
    return f'{text}.'


def contract_type(r):
    return 'Rights' if not r['cap'] else 'Two-way' if r['two_way'] else 'One-way'


def why_text(team, league):
    """Why a rail team has no front office. team: the rail's {name, extra, id} or None; league: its league's label."""
    if team is None:
        return 'Pick a team on the left.'
    if team['id'] == L.FREE_AGENTS:
        return 'Free agents belong to no NHL organisation. Pick an NHL club or its farm club.'
    if team.get('extra'):
        return 'All-Star teams have no contracts. Pick an NHL club.'
    if team['id'] == T.SEATTLE_AHL:                 # the custom team 498 (rail.COACHELLA)
        return f"The front office does not list the {team['name']} yet: they play in Season and Franchise only. " \
               'Edit their players on the Roster tab.'
    if league == 'AHL':
        return f"{team['name']} are the farm club of no NHL organisation in this roster. Pick an NHL club."
    if league == 'NHL':                             # Seattle in a roster that does not have its players
        return f"The {team['name']} have no players in this roster. Pick another NHL club."
    return (f"The front office covers the 32 NHL organisations and their farm clubs. {league or 'These'} clubs have no "
            'NHL contracts. Pick an NHL club.')
