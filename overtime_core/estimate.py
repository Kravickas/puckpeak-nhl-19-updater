"""Ratings of a club player no list rates, by the rule NHL Legacy's update uses (docs/notes/parity-v050.md): the median
attributes of the dressed NHL players of his position, moved to a level made from his league, age, letter, whether he
came from abroad and whether he is a rookie, with small differences of his own that follow from his name alone, so two
runs give the same player the same numbers.
"""
import zlib

from . import ratings as R

# points below the NHL, by league and forward, defence or goalie (measured on Legacy's rated players)
LEAGUE_GAP = {'ahl': (-6.1, -5.6, -6.9), 'shl': (-7.4, -7.1, -8.0), 'liiga': (-8.8, -7.7, -9.3),
              'del': (-7.9, -9.4, -8.9), 'extraliga': (-5.9, -6.0, -10.7), 'nl': (-4.8, -5.8, -6.6),
              'chl': (-13.5, -13.0, -15.7)}
AGE_CURVE = ((19, -4.0), (21, -2.5), (23, -1.4), (27, 0.0), (31, 1.0), (34, 1.6), (99, 2.2))
YOUTH_AGE = {'chl': 18}     # junior leagues: the gap was measured on teenagers
LETTER = {'C': 2.0, 'A': 1.0}
IMPORT = 1.5
ROOKIE = -1.0
LOWEST, HIGHEST = 36, 99    # the ratings Legacy's table can hold
# each attribute's salt for its small difference (Legacy's field tags)
SKATER = {'c_acceleration': 'ckxF', 'c_aggression': 'oskO', 'c_agility': 'pyYq', 'c_balance': 'YqOX',
          'c_bodychecking': 'oisw', 'c_defawareness': 'OTvp', 'c_deking': 'iCvN', 'c_discipline': 'ShqX',
          'c_durability': 'seUB', 'c_endurance': 'kIjD', 'c_faceoffs': 'KrwV', 'c_fightingskill': 'gUBy',
          'c_handeye': 'ujcW', 'c_offawareness': 'VlLd', 'c_passing': 'oRUd', 'c_poise': 'fRaZ',
          'c_puckcontrol': 'YqXz', 'c_shotblocking': 'zRrS', 'c_slapaccuracy': 'KQBB', 'c_slapshotpower': 'DCvJ',
          'c_speed': 'bEdA', 'c_stickchecking': 'TUty', 'c_strength': 'POYr', 'c_wristaccuracy': 'ObeE',
          'c_wristshotpower': 'Hvje'}
GOALIE = {'c_5hole': 'nMNR', 'c_aggression': 'oskO', 'c_agility': 'pyYq', 'c_breakaway': 'Nhuq', 'c_durability': 'seUB',
          'c_endurance': 'kIjD', 'c_gsh': 'DTrq', 'c_gsl': 'ejux', 'c_passing': 'oRUd', 'c_pokecheck': 'UqhP',
          'c_poise': 'fRaZ', 'c_positioning': 'fdgB', 'c_puckplayfrequency': 'LMNx', 'c_reboundcontrol': 'SiKH',
          'c_shotrecover': 'oLxj', 'c_speed': 'bEdA', 'c_ssh': 'vcIl', 'c_ssl': 'mshm', 'c_vision': 'miXH'}
GROUP = {0: 'C', 1: 'W', 2: 'W', 3: 'D', 4: 'G'}    # by bio position
# a national team's player no list rates: these attributes (measured on Legacy's), moved by his country and age
NATIONAL_LEVEL = {'AUT': 0, 'NOR': 0, 'BLR': 0, 'GBR': -2, 'KAZ': -2, 'POL': -3, 'UKR': -3, 'JPN': -3, 'DEU': 1, 'CHE': 1,
                  'SVK': 1, 'LVA': 0, 'DNK': 0, 'FRA': -1, 'ITA': -2}
NATIONAL = {
    'F': {'c_acceleration': 81, 'c_aggression': 76, 'c_agility': 81, 'c_balance': 79, 'c_bodychecking': 76,
          'c_defawareness': 75, 'c_deking': 77, 'c_discipline': 80, 'c_durability': 81, 'c_endurance': 77,
          'c_faceoffs': 67, 'c_fightingskill': 69, 'c_handeye': 77, 'c_offawareness': 77, 'c_passing': 77, 'c_poise': 72,
          'c_puckcontrol': 77, 'c_shotblocking': 74, 'c_slapaccuracy': 76, 'c_slapshotpower': 83, 'c_speed': 83,
          'c_stickchecking': 76, 'c_strength': 78, 'c_wristaccuracy': 77, 'c_wristshotpower': 83},
    'D': {'c_acceleration': 80, 'c_aggression': 76, 'c_agility': 80, 'c_balance': 78, 'c_bodychecking': 76,
          'c_defawareness': 76, 'c_deking': 70, 'c_discipline': 78, 'c_durability': 81, 'c_endurance': 78,
          'c_faceoffs': 50, 'c_fightingskill': 70, 'c_handeye': 71, 'c_offawareness': 73, 'c_passing': 73, 'c_poise': 70,
          'c_puckcontrol': 73, 'c_shotblocking': 76, 'c_slapaccuracy': 70, 'c_slapshotpower': 83, 'c_speed': 81,
          'c_stickchecking': 76, 'c_strength': 78, 'c_wristaccuracy': 70, 'c_wristshotpower': 83},
    'G': {'c_5hole': 85, 'c_aggression': 84, 'c_agility': 84, 'c_breakaway': 83, 'c_durability': 85, 'c_endurance': 85,
          'c_gsh': 86, 'c_gsl': 86, 'c_passing': 82, 'c_pokecheck': 84, 'c_poise': 84, 'c_positioning': 85,
          'c_puckplayfrequency': 82, 'c_reboundcontrol': 85, 'c_shotrecover': 85, 'c_speed': 85, 'c_ssh': 85, 'c_ssl': 87,
          'c_vision': 83}}


def spread(name, salt, low, high):
    """A fixed whole number in [low, high] for this player."""
    return low + zlib.crc32(f'{salt}:{name}'.encode()) % (high - low + 1)


def age_adjust(age):
    return next(adjust for limit, adjust in AGE_CURVE if age <= limit)


def national(pos, code, age, name):
    """{attribute: value} of a player of national team `code` and bio position `pos` whom no list rates."""
    adjust = NATIONAL_LEVEL.get(code, 0) + (-2 if age < 21 else -1 if age < 24 or age > 32 else 0)
    adjust += zlib.crc32(name.encode()) % 3 - 1
    return {f: max(LOWEST, min(HIGHEST, v + adjust)) for f, v in NATIONAL[GROUP[pos] if pos > 2 else 'F'].items()}


class Estimator:
    def __init__(self, db, dressed):
        """`dressed`: [(bio position, game_id)] of the NHL's dressed players, read from `db`."""
        rows = {name: {db[name].get(i, 'game_id'): db[name].row(i) for i in range(db[name].count)}
                for name in (R.SKATERS, R.GOALIES)}
        samples = {'C': [], 'W': [], 'D': [], 'G': []}
        for pos, gid in dressed:
            row = rows[R.GOALIES if pos == 4 else R.SKATERS].get(gid)
            if row is not None:
                samples[GROUP[pos]].append(row)
        self.shape, self.level = {}, {}
        for group, players in samples.items():
            fields = GOALIE if group == 'G' else SKATER
            self.shape[group] = {f: sorted(p[f] for p in players)[len(players) // 2] if players else 76 for f in fields}
            self.level[group] = sum(self.shape[group].values()) / len(fields)

    def target(self, league, pos, age, name, letter=None, rookie=False, from_abroad=False):
        """The level a player of this league (a key of LEAGUE_GAP), bio position and age should have."""
        group = GROUP[pos]
        gap = LEAGUE_GAP[league][2 if group == 'G' else 1 if group == 'D' else 0]
        level = self.level[group] + gap + age_adjust(age)
        if league in YOUTH_AGE:
            level -= age_adjust(YOUTH_AGE[league])
        level += LETTER.get(letter, 0.0) + (IMPORT if from_abroad else 0.0) + (ROOKIE if rookie else 0.0)
        return level + (spread(name, 'a', -2, 2) + spread(name, 'b', -2, 2)) / 2

    def values(self, pos, level, name):
        """{attribute: value} of a player of bio position `pos` at `level`."""
        group = GROUP[pos]
        delta = round(level - self.level[group])
        tags = GOALIE if group == 'G' else SKATER
        return {f: max(LOWEST, min(HIGHEST, v + delta + spread(name, tags[f], -2, 2))) for f, v in self.shape[group].items()}
