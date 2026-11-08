"""Auto lines: deal all 87 line slots of a team from scratch, by rating and position (idea from PS3 Legacy `lines.py`).

Used for teams whose players changed (the Update pipeline) and for teams the game left without lines (Seattle). The
rules are what every NHL team of the game's default roster satisfies (tests/test_lines.py):
  * 20 players dress (exhibitionrostertable.rosterstatus 1): 12 forwards on four lines, 6 defencemen in three pairs,
    2 goalies; the others 0;
  * each of the 87 slots has exactly one holder, goalies only goalie slots;
  * only dressed players hold slots, except NHL Threes' (the mode picks its own team: 9 stock holders do not dress);
  * inside one group of units (power play, penalty kill, overtime, Threes, ...) a player holds one slot at most (the
    seven Threes slots are seven players).
Slots: even strength l1-l4 (lw c rw), l1-l3 (ld rd), g1 g2; power play pp1 pp2 (lw c rw ld rd), pp4_1 pp4_2 (lw c ld rd);
penalty kill pk4_1 pk4_2 (lw c ld rd), pk3_1 pk3_2 (c ld rd); overtime ot_1-3 (lw c ld rd), 3-on-3 ot3_1-3 (c ld rd);
shootout s1-s5; extra attackers x1 x2; NHL Threes three_c three_w three_d three_g1 three_g2 three_s1 three_s2.

The Lines tab edits one slot at a time (`place`, Legacy's swap rules), re-deals one group of units (`deal_groups`)
and lists what the game would refuse (`check_lineup`).
"""
from .roster import ES_SLOTS, GOALIE, NOT_SLOTS

ROSTER, PLAYERS, BIOS = 'exhibitionrostertable', 'exhibitionplayers', 'exhibitionplayerbiotable'
SKATERS, GOALIES = 'exhibitionskaterai', 'exhibitiongoalieai'
C, LW, RW, D = 0, 1, 2, 3
DRESSED = 'rosterstatus'

OFFENCE = ('c_offawareness', 'c_passing', 'c_puckcontrol', 'c_deking', 'c_wristaccuracy')
DEFENCE = ('c_defawareness', 'c_stickchecking', 'c_shotblocking')
SHOOTOUT = ('c_deking', 'c_wristaccuracy', 'c_puckcontrol')

GROUPS = {
    'Lines': ES_SLOTS,
    'Power play': tuple(f'pp{k}{s}' for k in (1, 2) for s in ('lw', 'c', 'rw', 'ld', 'rd')),
    'Power play 4 on 3': tuple(f'pp4_{k}{s}' for k in (1, 2) for s in ('lw', 'c', 'ld', 'rd')),
    'Penalty kill': tuple(f'pk4_{k}{s}' for k in (1, 2) for s in ('lw', 'c', 'ld', 'rd')),
    'Penalty kill 3 on 5': tuple(f'pk3_{k}{s}' for k in (1, 2) for s in ('c', 'ld', 'rd')),
    'Overtime': tuple(f'ot_{k}{s}' for k in (1, 2, 3) for s in ('lw', 'c', 'ld', 'rd')),
    'Overtime 3 on 3': tuple(f'ot3_{k}{s}' for k in (1, 2, 3) for s in ('c', 'ld', 'rd')),
    'Shootout': tuple(f's{k}' for k in range(1, 6)),
    'Extra attackers': ('x1', 'x2'),
    'Threes': ('three_c', 'three_w', 'three_d', 'three_g1', 'three_g2', 'three_s1', 'three_s2'),
}
SLOTS = tuple(s for group in GROUPS.values() for s in group)
assert len(SLOTS) == 87 and len(set(SLOTS)) == 87
GROUP_OF = {s: name for name, group in GROUPS.items() for s in group}
THREES = 'Threes'  # the one group whose holders need not dress


class NotEnoughPlayers(ValueError):
    pass


class NotDressed(ValueError):
    """A scratched player picked for a special-teams place: he first needs a place in the lineup."""


class _Player:
    def __init__(self, row, entry, bio, ai):
        self.row, self.index = row, entry['playerindex']
        self.pos = bio['position'] if bio else (GOALIE if ai is None else C)
        self.right = bool(bio and bio['handedness'] == 1)
        self.ai = ai or {}
        self.q = self.ai.get('skill_overall', self.ai.get('c_overall', 0))

    def score(self, fields):
        values = [self.ai[f] for f in fields if f in self.ai]
        return sum(values) / len(values) if values else self.q


def players_of(db, team, table=ROSTER):
    """[_Player] of the team's rows of roster `table` (customrostertable for custom teams), with position,
    handedness and ratings."""
    roster, players, bios = db[table], db[PLAYERS], db[BIOS]
    prow = {pi: i for i, pi in enumerate(players.column('index'))}
    brow = {gid: i for i, gid in enumerate(bios.column('game_id'))}
    ai_rows = {name: {gid: i for i, gid in enumerate(db[name].column('game_id'))} for name in (SKATERS, GOALIES)}
    out = []
    for i, on in enumerate(roster.column('team')):
        if on != team:
            continue
        e = roster.row(i)
        bio = ai = None
        p = prow.get(e['playerindex'])
        if p is not None and players.get(p, 'table') == 0:
            b = brow.get(players.get(p, 'playerid'))
            if b is not None:
                bio = bios.row(b)
                name = GOALIES if bio['position'] == GOALIE else SKATERS
                a = ai_rows[name].get(bio['game_id'])
                ai = db[name].row(a) if a is not None else None
        out.append(_Player(i, e, bio, ai))
    return out


def deal(players):
    """{slot: _Player} for every slot. Deterministic: ties go by the player's index."""
    by_q = lambda group: sorted(group, key=lambda p: (-p.q, p.index))
    best = lambda group, fields: sorted(group, key=lambda p: (-p.score(fields), -p.q, p.index))
    goalies = by_q(p for p in players if p.pos == GOALIE)
    defence = by_q(p for p in players if p.pos == D)
    forwards = by_q(p for p in players if p.pos in (C, LW, RW))
    if len(goalies) < 2 or len(defence) + len(forwards) < 18:
        raise NotEnoughPlayers(f"{len(goalies)} goalies, {len(defence)} defencemen, {len(forwards)} forwards: "
                               "20 cannot dress")
    while len(defence) < 6:  # short at one position: the best spare of the other fills in
        defence.append(forwards.pop(12) if len(forwards) > 12 else forwards.pop())
    while len(forwards) < 12:
        forwards.append(defence.pop(6) if len(defence) > 6 else defence.pop())
    d6, f12 = defence[:6], forwards[:12]
    centres = [p for p in f12 if p.pos == C][:4]
    wings = [p for p in f12 if p not in centres]
    while len(centres) < 4:  # too few natural centres: the best remaining forward plays centre
        centres.append(wings.pop(0))
    centres = by_q(centres)

    def wing_pairs(group):
        left = by_q(p for p in group if p.pos == LW)
        right = by_q(p for p in group if p.pos == RW)
        rest = by_q(p for p in group if p.pos not in (LW, RW))
        pairs = []
        for _ in range(len(group) // 2):
            lw = (left or rest or right).pop(0)
            rw = (right or rest or left).pop(0)
            pairs.append((lw, rw))
        return pairs

    def sides(x, y):  # each winger on his own side where possible
        return (y, x) if (x.pos == RW and y.pos != RW) or (y.pos == LW and x.pos != LW) else (x, y)

    def pair(x, y):  # a right shot on the right when the pair has one of each
        return (y, x) if x.right and not y.right else (x, y)

    s = {}
    for k, (lw, rw) in enumerate(wing_pairs(wings), 1):
        s[f'l{k}lw'], s[f'l{k}c'], s[f'l{k}rw'] = lw, centres[k - 1], rw
    pairs = [pair(d6[2 * k], d6[2 * k + 1]) for k in range(3)]
    for k, (ld, rd) in enumerate(pairs, 1):
        s[f'l{k}ld'], s[f'l{k}rd'] = ld, rd
    s['g1'], s['g2'] = goalies[0], goalies[1]

    pp_c = best(centres, OFFENCE)[:2]
    pp_w = best([p for p in f12 if p not in pp_c], OFFENCE)[:4]
    pp_d = best(d6, OFFENCE)[:4]
    for k in (1, 2):
        lw, rw = sides(pp_w[2 * k - 2], pp_w[2 * k - 1])
        ld, rd = pair(pp_d[2 * k - 2], pp_d[2 * k - 1])
        s[f'pp{k}lw'], s[f'pp{k}c'], s[f'pp{k}rw'], s[f'pp{k}ld'], s[f'pp{k}rd'] = lw, pp_c[k - 1], rw, ld, rd
        s[f'pp4_{k}lw'], s[f'pp4_{k}c'], s[f'pp4_{k}ld'], s[f'pp4_{k}rd'] = pp_w[2 * k - 2], pp_c[k - 1], ld, rd
    pk_c = best(centres, DEFENCE)[:2]
    pk_w = best([p for p in f12 if p not in pk_c], DEFENCE)[:2]
    pk_d = best(d6, DEFENCE)[:4]
    for k in (1, 2):
        ld, rd = pair(pk_d[2 * k - 2], pk_d[2 * k - 1])
        s[f'pk4_{k}lw'], s[f'pk4_{k}c'], s[f'pk4_{k}ld'], s[f'pk4_{k}rd'] = pk_w[k - 1], pk_c[k - 1], ld, rd
        s[f'pk3_{k}c'], s[f'pk3_{k}ld'], s[f'pk3_{k}rd'] = pk_c[k - 1], ld, rd
    ot_w = best([p for p in f12 if p not in centres[:3]], OFFENCE)[:3]
    ot_d = best(d6, OFFENCE)
    ot_pairs = [pair(ot_d[2 * k], ot_d[2 * k + 1]) for k in range(3)]
    for k in (1, 2, 3):
        ld, rd = ot_pairs[k - 1]
        s[f'ot_{k}lw'], s[f'ot_{k}c'], s[f'ot_{k}ld'], s[f'ot_{k}rd'] = ot_w[k - 1], centres[k - 1], ld, rd
        s[f'ot3_{k}c'], s[f'ot3_{k}ld'], s[f'ot3_{k}rd'] = centres[k - 1], ld, rd
    for k, p in enumerate(best(f12, SHOOTOUT)[:5], 1):
        s[f's{k}'] = p
    s['x1'], s['x2'] = by_q(f12)[:2]
    s['three_c'] = centres[0]
    s['three_w'] = by_q(p for p in f12 if p is not centres[0])[0]
    s['three_d'] = d6[0]
    s['three_g1'], s['three_g2'] = goalies[0], goalies[1]
    s['three_s1'], s['three_s2'] = best([p for p in f12 if p not in (s['three_c'], s['three_w'])], SHOOTOUT)[:2]
    assert set(s) == set(SLOTS)
    return s


def build(db, team, setter=None, table=ROSTER):
    """Clear and re-deal every line slot and the dressed flag of `team`. `setter(table, row, field, value)` writes
    one value (default: straight into `db`; the roster app passes its undoable one); only values that change are
    written. Returns {slot: exhibitionplayers index}."""
    players = players_of(db, team, table)
    slots = deal(players)
    holds = {}
    for slot, p in slots.items():
        holds.setdefault(p.row, set()).add(slot)
    roster = db[table]
    fields = [f.name for f in roster.fields if f.name not in NOT_SLOTS]
    set_ = setter or (lambda table, row, field, value: db[table].set(row, field, value))
    for p in players:
        mine = holds.get(p.row, set())
        want = {f: int(f in mine) for f in fields}
        want[DRESSED] = int(bool(mine))
        for f, v in want.items():
            if roster.get(p.row, f) != v:
                set_(table, p.row, f, v)
    return {slot: p.index for slot, p in slots.items()}


def deal_groups(db, team, names, setter=None, table=ROSTER):
    """Re-deal only the slots of the named groups (GROUPS keys) the way `build` deals them, from the players who
    dress; the dressed flags and every other group stay. 'Lines' (even strength) decides who dresses, so it re-deals
    the whole team (`build`). Returns {slot: exhibitionplayers index} of the dealt slots."""
    unknown = [n for n in names if n not in GROUPS]
    if unknown:
        raise KeyError(f"no group of units {unknown[0]!r}")
    if 'Lines' in names:
        return build(db, team, setter, table)
    roster = db[table]
    everyone = players_of(db, team, table)
    dealt = deal([p for p in everyone if roster.get(p.row, DRESSED)])
    want = {s for n in names for s in GROUPS[n]}
    set_ = setter or (lambda table, row, field, value: db[table].set(row, field, value))
    for p in everyone:
        for s in want:
            v = int(dealt[s] is p)
            if roster.get(p.row, s) != v:
                set_(table, p.row, s, v)
    return {s: p.index for s, p in dealt.items() if s in want}


def place(db, team, slot, pi, setter=None, table=ROSTER):
    """Put the team's player `pi` (exhibitionplayers index; None: nobody) in one line slot, as the Lines tab does
    (Legacy's rules):
      * whoever held the slot leaves it;
      * a player who already has a place in the slot's group of units (a power-play unit, the shootout, ...) swaps
        places with the one he displaces, so nobody holds two places of one group;
      * a scratched player who comes into the lineup (an even-strength or goalie slot) takes over every place of the
        one he replaces, who sits out; the dressed flags follow (only players with a place outside Threes dress);
      * a scratched player cannot take a special-teams place before he has one in the lineup (NotDressed).
    Returns [(slot, old holder or None, new holder or None)] for the slots that changed."""
    if slot not in GROUP_OF:
        raise KeyError(f"unknown line slot {slot!r}")
    roster = db[table]
    set_ = setter or (lambda table, row, field, value: db[table].set(row, field, value))
    rows = {roster.get(i, 'playerindex'): i for i in range(roster.count) if roster.get(i, 'team') == team}
    if pi is not None and pi not in rows:
        raise ValueError('that player is not on this team')
    held = {s: [p for p, i in rows.items() if roster.get(i, s)] for s in SLOTS}
    dressed = lambda p: bool(roster.get(rows[p], DRESSED))
    plays = lambda p: any(p in held[s] for s in SLOTS if GROUP_OF[s] != THREES)
    changes = []

    def put(s, p):
        want = [p] if p is not None else []
        if held[s] == want:
            return
        for q in held[s]:
            if q != p:
                set_(table, rows[q], s, 0)
        if p is not None and p not in held[s]:
            set_(table, rows[p], s, 1)
        changes.append((s, held[s][0] if held[s] else None, p))
        held[s] = want

    had = held[slot][0] if held[slot] else None
    if pi is None or pi == had:
        put(slot, pi)
        return changes
    group = GROUP_OF[slot]
    if group != THREES and slot not in ES_SLOTS and not dressed(pi):
        raise NotDressed('a scratched player first needs a place in the lineup (even strength) before he can '
                         'play on special teams')
    mine = next((s for s in GROUPS[group] if s != slot and pi in held[s]), None)
    if mine is not None:
        put(mine, had)
    elif slot in ES_SLOTS and not dressed(pi) and had is not None:
        for s in SLOTS:
            if s != slot and GROUP_OF[s] != THREES and had in held[s]:
                put(s, pi)
    put(slot, pi)
    for p in (pi, had):
        if p is not None and dressed(p) != plays(p):
            set_(table, rows[p], DRESSED, int(plays(p)))
    return changes


def check_lineup(db, team, table=ROSTER):
    """Problems of one team's lines, as sentences: an even-strength or goalie slot not held by exactly one player,
    a player twice inside one group of units or holding slots without dressing (`check_groups`)."""
    roster = db[table]
    rows = [i for i in range(roster.count) if roster.get(i, 'team') == team]
    problems = []
    for s in ES_SLOTS:
        n = sum(1 for i in rows if roster.get(i, s))
        if n != 1:
            problems.append(f"{s} is held by {n} players (the game needs exactly one)")
    return problems + check_groups(db, team, table)


def check_groups(db, team, table=ROSTER):
    """Problems: a player twice inside one group of units, or a slot holder who does not dress."""
    roster = db[table]
    problems = []
    for i in range(roster.count):
        if roster.get(i, 'team') != team:
            continue
        r = roster.row(i)
        held = [s for s in SLOTS if r.get(s)]
        for name, group in GROUPS.items():
            n = sum(1 for s in held if s in group)
            if n > 1 and name != 'Lines':
                problems.append(f"player {r['playerindex']} holds {n} {name} slots")
        if any(s not in GROUPS['Threes'] for s in held) and not r[DRESSED]:
            problems.append(f"player {r['playerindex']} holds slots but does not dress")
    return problems
