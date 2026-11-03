"""Real lines and captains: the lines and letters each NHL team played in its last games, from the data pack's
`lines` part (NHL Legacy's `tools/build_datapack.py --refresh lines`: Daily Faceoff's announced lines, else NHL.com's
last 5 game reports; Legacy `builder.lines_from_games`). docs/notes/real-lines.md.

The pack names 52 slots with lines.py's own names: even strength, the goalies, both power plays and both penalty kills.
They are laid over the team's lines group by group. A group that misses a player (traded since the lines were published)
or names one twice is completed when at most GAP_SHARE of its slots are open (fill_gaps, as Legacy does for clubs; Legacy
deals such an NHL group, here its other 17 players still play where they played); with more open it is dealt. A goalie
goes in a goalie slot only. The 20 who hold the even-strength and goalie slots dress; a power-play or penalty-kill unit
of the pack is kept only when all its players dress, else it is dealt.
Overtime, the shootout, the extra attackers and Threes are dealt from the dressed 20 (lines.deal_groups). A team
whose result lines.check_lineup finds fault with keeps the lines it had.

Letters: skaters only, one C at most, three letters in all (the pack's, then As for the best dressed skaters).
"""
from dataclasses import dataclass, field

from . import lines
from .roster import ALTERNATE, CAPTAIN, ES_SLOTS, GOALIE, NOT_SLOTS, POSITIONS

GOALIE_PAIR = ('g1', 'g2')
REAL_GROUPS = {
    'Lines': tuple(s for s in ES_SLOTS if s not in GOALIE_PAIR),
    'Goalies': GOALIE_PAIR,
    'Power play': lines.GROUPS['Power play'],
    'Power play 4 on 3': lines.GROUPS['Power play 4 on 3'],
    'Penalty kill': lines.GROUPS['Penalty kill'],
    'Penalty kill 3 on 5': lines.GROUPS['Penalty kill 3 on 5'],
}
SPECIAL = ('Power play', 'Power play 4 on 3', 'Penalty kill', 'Penalty kill 3 on 5')
GAP_SHARE = 0.4     # Legacy builder.GAP_SHARE: a group with more of its slots open is dealt
LETTERS = 3
CAPTAIN_FIELD = 'captain'


@dataclass
class Result:
    lined: list = field(default_factory=list)      # club codes that play (some of) their real lines
    full: list = field(default_factory=list)       # club codes every group of the pack was laid for, no slot open
    partly: dict = field(default_factory=dict)     # club code -> [the groups dealt or completed]: real lines, in part
    refused: dict = field(default_factory=dict)    # club code -> [reason]: the team kept its lines
    lettered: list = field(default_factory=list)   # club codes whose letters were set
    date: str = ''                                 # the newest date of the lines laid

    def as_dict(self):
        return {'lined': self.lined, 'full': self.full, 'partly': self.partly, 'refused': self.refused,
                'lettered': self.lettered, 'date': self.date}


def part(pack, season):
    """The pack's `lines` part ({club code: entry}) when it is for `season` (the year the season starts), else None."""
    real = (pack or {}).get('lines')
    if not isinstance(real, dict) or not real or (pack or {}).get('season') != season:
        return None
    return real


def apply(db, real, pis, target_of, setter=None, log=lambda msg: None):
    """Lay `real` (part()) on every club it names. `pis` {NHL.com id: exhibitionplayers index} (the update's placed
    players), `target_of(code)` -> (roster table, team) (rosterupdate.target_of; raises ValueError for a club the game
    does not have). Returns a Result."""
    out = Result()
    for code in sorted(real):
        entry = real[code] or {}
        try:
            table, team = target_of(code)
        except ValueError as err:
            out.refused[code] = [str(err)]
            continue
        if table not in db:
            continue
        if entry.get('slots'):
            gaps = []
            problems = line_up(db, table, team, entry['slots'], pis, setter, gaps)
            if problems:
                out.refused[code] = problems
                log(f'real lines {code}: kept the lines it had ({problems[0]})')
            else:
                out.lined.append(code)
                out.date = max(out.date, str(entry.get('date') or ''))
                if gaps:
                    out.partly[code] = gaps
                else:
                    out.full.append(code)
        if entry.get('letters') and letter(db, table, team, entry['letters'], pis, setter):
            out.lettered.append(code)
    return out


def _team_rows(db, table, team):
    roster = db[table]
    return [i for i in range(roster.count) if roster.get(i, 'team') == team]


def _kind(slot):
    """'G', 'D' or 'F': who an open slot takes."""
    return 'G' if slot in GOALIE_PAIR else 'D' if slot.endswith(('ld', 'rd')) else 'F'


def _kind_of(player):
    pos = POSITIONS[player.pos]
    return pos if pos in 'GD' else 'F'


def fill_gaps(got, holder, players):
    """Complete a group ({slot: player or None}) in place: each open slot goes to who holds it now, else to the best of
    `players` of that kind not yet in the group (a goalie in a skater's slot, or a skater in a goalie's, is an open
    slot; so is a player's second slot). Returns the slots filled, None when more than GAP_SHARE are open or one can't
    be filled: the group is dealt."""
    seen = set()
    for s, p in got.items():
        if p is not None and (id(p) in seen or (p.pos == GOALIE) != (s in GOALIE_PAIR)):
            got[s] = None
        elif p is not None:
            seen.add(id(p))
    empty = [s for s, p in got.items() if p is None]
    if len(empty) > GAP_SHARE * len(got):
        return None
    pool = {id(p) for p in players}
    best = sorted(players, key=lambda p: (-p.q, p.index))
    for s in empty:
        now = holder.get(s)
        if now is None or id(now) not in pool or id(now) in seen or _kind_of(now) != _kind(s):
            now = next((p for p in best if id(p) not in seen and _kind_of(p) == _kind(s)), None)
        if now is None:
            return None
        got[s] = now
        seen.add(id(now))
    return empty


def line_up(db, table, team, wanted, pis, setter=None, gaps=None):
    """Write `wanted` ({slot: NHL.com id}) on one team's lines. Returns [] when written, else what was wrong (the team
    keeps what it had). `gaps`, a list, receives what fell short of the pack: 'Lines (1 of 18 filled)', 'Lines dealt'."""
    roster = db[table]
    set_ = setter or (lambda table, row, f, v: db[table].set(row, f, v))
    rows = _team_rows(db, table, team)
    fields = [f.name for f in roster.fields if f.name not in NOT_SLOTS] + [lines.DRESSED]
    before = {i: {f: roster.get(i, f) for f in fields} for i in rows}
    if lines.check_lineup(db, team, table):
        try:
            lines.build(db, team, setter, table)
        except lines.NotEnoughPlayers as err:
            return [str(err)]
    players = lines.players_of(db, team, table)
    by_pi = {p.index: p for p in players}
    holder = {s: next((p for p in players if roster.get(p.row, s)), None) for s in lines.SLOTS}
    new, applied = {}, []
    for name, slots in REAL_GROUPS.items():
        got = {s: by_pi.get(pis.get(wanted.get(s))) for s in slots}
        dressed = {id(new.get(s, holder[s])) for s in ES_SLOTS}
        filled = fill_gaps(got, holder, [p for p in players if name not in SPECIAL or id(p) in dressed])
        if filled is None:
            if gaps is not None:
                gaps.append(f'{name} dealt')
            continue
        if filled and gaps is not None:
            gaps.append(f'{name} ({len(filled)} of {len(slots)} filled)')
        new.update(got)
        applied.append(name)
    if not applied:
        return ['no group of the real lines has all its players on the team']
    for s in list(new):                                  # a defence pair: the right shot on the right
        if s in ES_SLOTS and s.endswith('ld') and s[:-2] + 'rd' in new:
            ld, rd = new[s], new[s[:-2] + 'rd']
            if ld.right and not rd.right:
                new[s], new[s[:-2] + 'rd'] = rd, ld
    lineup = {s: new.get(s, holder[s]) for s in ES_SLOTS}
    dressed = {id(p) for p in lineup.values()}
    for p in players:                                    # even strength, goalies and who dresses
        for s in ES_SLOTS:
            v = int(lineup[s] is p)
            if roster.get(p.row, s) != v:
                set_(table, p.row, s, v)
        v = int(id(p) in dressed)
        if roster.get(p.row, lines.DRESSED) != v:
            set_(table, p.row, lines.DRESSED, v)
    special = [g for g in SPECIAL if g in applied and all(id(new[s]) in dressed for s in REAL_GROUPS[g])]
    lines.deal_groups(db, team, [g for g in lines.GROUPS if g != 'Lines' and g not in special], setter, table)
    for g in special:
        for p in players:
            for s in REAL_GROUPS[g]:
                v = int(new[s] is p)
                if roster.get(p.row, s) != v:
                    set_(table, p.row, s, v)
    problems = lines.check_lineup(db, team, table)
    if problems:
        for i, values in before.items():
            for f, v in values.items():
                if roster.get(i, f) != v:
                    set_(table, i, f, v)
    return problems


def club_letters(db, table, team, listed):
    """A club's one C and two As among its dressed skaters: its own where `listed` ({exhibitionplayers index: 'C' | 'A'}),
    else its best."""
    roster = db[table]
    players = lines.players_of(db, team, table)
    dressed = [p for p in players if p.pos != GOALIE and roster.get(p.row, lines.DRESSED)]
    best = sorted(dressed, key=lambda p: (-p.q, p.index))
    captain = next((p for p in dressed if listed.get(p.index) == 'C'), None) or (best[0] if best else None)
    alternates = [p for p in dressed if listed.get(p.index) == 'A' and p is not captain][:2]
    alternates += [p for p in best if p is not captain and p not in alternates][:2 - len(alternates)]
    want = {p.row: ALTERNATE for p in alternates}
    if captain is not None:
        want[captain.row] = CAPTAIN
    for p in players:
        if roster.get(p.row, CAPTAIN_FIELD) != want.get(p.row, 0):
            roster.set(p.row, CAPTAIN_FIELD, want.get(p.row, 0))


def letter(db, table, team, letters, pis, setter=None):
    """The team's C and As from `letters` ({"NHL.com id": 'C' | 'A'}): skaters only, one C at most, topped up to three
    letters with As for the best dressed skaters. A team none of whose lettered players it has keeps its letters.
    Returns whether the letters were set."""
    roster = db[table]
    set_ = setter or (lambda table, row, f, v: db[table].set(row, f, v))
    players = [p for p in lines.players_of(db, team, table) if p.pos != GOALIE]
    by_pi = {p.index: p for p in players}
    want = {}
    for nhl_id, mark in sorted(letters.items(), key=lambda kv: (kv[1] != 'C', str(kv[0]))):
        try:
            p = by_pi.get(pis.get(int(nhl_id)))
        except (TypeError, ValueError):
            p = None
        if p is None or p.row in want or len(want) >= LETTERS:
            continue
        want[p.row] = CAPTAIN if mark == 'C' and CAPTAIN not in want.values() else ALTERNATE
    if not want:
        return False
    for p in sorted(players, key=lambda p: (-bool(roster.get(p.row, lines.DRESSED)), -p.q, p.index)):
        if len(want) >= LETTERS:
            break
        want.setdefault(p.row, ALTERNATE)
    for i in _team_rows(db, table, team):
        v = want.get(i, 0)
        if roster.get(i, CAPTAIN_FIELD) != v:
            set_(table, i, CAPTAIN_FIELD, v)
    return True
