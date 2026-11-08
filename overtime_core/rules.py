"""The match rules of an Online Versus game (period length, penalties, ...): the table the lobby and the app share, and
the byte edit of the game's own rules file.

The game reads these from `nhl/data/common/gamemodes/matchmaking/online_playnow_casual_h2h.json` (`rules.custom.game[]`,
`defaultvalue` per rule; docs/notes/matchmaking.md) and sends them as SA_GAMEATTRIBUTE_<KEY> when it searches. Values
and defaults here are ids the game's files use; the labels follow the words the game's own menus show for each value
(docs/notes/match-rules.md "Labels"). Nothing of the game's file is kept in this module.
"""
import re

RULES_PATH = 'nhl/data/common/gamemodes/matchmaking/online_playnow_casual_h2h.json'
SHOOTOUT_PATH = 'nhl/data/common/gamemodes/matchmaking/online_shootout_competitive.json'
THREES_PATH = 'nhl/data/common/gamemodes/matchmaking/gm_3on3_vs_timedperiods_otp.json'
# The Online modes of the Multiplayer tab. Shootout searches with its own scenario (online_shootout_competitive:
# NHL_GameType 25) and a shorter list of rules (docs/notes/online-shootout.md). Threes (NHL Threes online, scenario
# online_vs_threeonthree_tp_otp, NHL_GameType 18) has no rules to pick: the ranked file holds only its game type
# (docs/notes/threes-otp.md), so the game plays its own (Pro, timed periods) and every row of the card is greyed.
VERSUS, SHOOTOUT, THREES = 'versus', 'shootout', 'threes'
MODES = (VERSUS, SHOOTOUT, THREES)
NAMES = 'versus, shootout or threes'   # for the texts that name the choices


class RulesError(ValueError):
    pass


def _opts(*pairs):
    return tuple((str(v), label) for v, label in pairs)


# (key, label, ((value, label), ...), default). The order is the card's.
RULES = (
    ('periodlength', 'Period length', _opts((4, '4 min'), (5, '5 min'), (10, '10 min'), (15, '15 min'), (20, '20 min')), '4'),
    ('skilllevel', 'Skill level', _opts((0, 'Rookie'), (1, 'Semi-pro'), (2, 'Pro'), (3, 'All-Star'), (4, 'Superstar')), '3'),
    ('gamestyle', 'Game style', _opts((0, 'Arcade'), (1, 'Traditional'), (2, 'Competitive'), (3, 'Full sim')), '2'),
    ('leaguerules', 'Rule set', _opts((1, 'NHL'), (2, 'International'), (3, 'CHL')), '1'),
    ('penalties', 'Penalties', _opts((0, 'Off'), (3, 'On')), '3'),
    ('fighting', 'Fighting', _opts((0, 'Off'), (2, 'On')), '2'),
    ('injuries', 'Injuries', _opts((0, 'Off'), (3, 'On')), '3'),
    ('icing', 'Icing', _opts((0, 'Off'), (1, 'On'), (2, 'No touch'), (3, 'Hybrid')), '3'),
    ('offsides', 'Offsides', _opts((0, 'Off'), (1, 'On'), (2, 'Delayed')), '2'),
    ('tiebreaker', 'Tie break', _opts((0, 'Continuous OT'), (1, 'Shootout'), (2, '5 min 3 on 3, then shootout'),
                                      (3, '5 min 4 on 4, then shootout'), (4, 'Single OT 4 on 4'),
                                      (5, 'Single OT 5 on 5')), '0'),
    ('goaliecontrol', 'Goalie in shootout', _opts((0, 'Off'), (1, 'On')), '1'),
)
# The rules of an Online Shootout game: the game's file also holds shootoutrules (1) and shootoutshots (5), which stay as
# the game ships them (their other values and labels are not known). Skill level, game style and goalie control are the
# same rules as Versus', so one row means the same in both tables.
_SHOOTOUT_KEYS = ('skilllevel', 'gamestyle', 'goaliecontrol')
SHOOTOUT_RULES = tuple(r for k in _SHOOTOUT_KEYS for r in RULES if r[0] == k)
THREES_RULES = ()
TABLES = {VERSUS: RULES, SHOOTOUT: SHOOTOUT_RULES, THREES: THREES_RULES}
PATHS = {VERSUS: RULES_PATH, SHOOTOUT: SHOOTOUT_PATH, THREES: THREES_PATH}
KEYS = tuple(r[0] for r in RULES)
DEFAULTS = {key: default for key, _label, _options, default in RULES}
SHOOTOUT_DEFAULTS = {key: default for key, _label, _options, default in SHOOTOUT_RULES}
_BY_KEY = {r[0]: r for r in RULES}


def table(mode=VERSUS):
    """The rows ((key, label, options, default)) of one mode's rules."""
    try:
        return TABLES[mode]
    except KeyError:
        raise RulesError('The game mode is %s.' % NAMES) from None


def defaults(mode=VERSUS):
    return {key: default for key, _label, _options, default in table(mode)}


def path(mode=VERSUS):
    table(mode)
    return PATHS[mode]


def validate(settings, partial=False, mode=VERSUS):
    """The rules of `mode` as {key: value string}, every key present (missing ones take the default unless `partial`, which
    returns only the given ones). Values may be numbers or strings; an unknown key (one the mode does not have) or value
    is refused with a text."""
    if not isinstance(settings, dict):
        raise RulesError('The match rules are a list of choices.')
    rows = {r[0]: r for r in table(mode)}
    out = {} if partial else defaults(mode)
    for key, value in settings.items():
        rule = rows.get(key)
        if rule is None:
            raise RulesError(f'Unknown match rule: {str(key)[:30]}.')
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise RulesError(f'{rule[1]}: pick one of the choices.')
        value = str(value)
        if value not in {v for v, _ in rule[2]}:
            raise RulesError(f'{rule[1]}: pick one of the choices.')
        out[key] = value
    return out


def label(key, value):
    """The words for one choice ('10 min'), or the raw value for one the table does not know."""
    for v, text in _BY_KEY[key][2]:
        if v == str(value):
            return text
    return str(value)


def summary(settings, mode=VERSUS):
    """'10 min · Full sim · Fighting off' in the card's words: only what differs from the defaults, 'Default rules' else."""
    parts = []
    for key, name, _options, default in table(mode):
        value = str(settings.get(key, default))
        if value == default:
            continue
        text = label(key, value)
        parts.append(text if key in ('periodlength', 'skilllevel', 'gamestyle', 'leaguerules', 'tiebreaker')
                     else f'{name} {text.lower()}')
    return ' · '.join(parts) or 'Default rules'


def _pattern(key):
    return re.compile(rb'("rulename"\s*:\s*"' + key.encode() + rb'"\s*,\s*"attributename"\s*:\s*"[^"]*"\s*,\s*'
                      rb'"sagameattributetag"\s*:\s*"[^"]*"\s*,\s*"defaultvalue"\s*:\s*")(\d{1,3})(")')


def read(raw):
    """{key: value string} the rules file holds now, for the keys of the table (a rule the file lacks is left out)."""
    out = {}
    for key in KEYS:
        found = _pattern(key).findall(raw)
        if len(found) == 1:
            out[key] = found[0][1].decode()
    return out


def edit(raw, settings, mode=VERSUS):
    """The rules file (of `mode`) with each given rule's `defaultvalue` set; every other byte stays. A rule missing from
    the file or present twice, or a value the table does not know, is refused: the game's file is not the one this edit
    knows."""
    wanted = validate(settings, partial=True, mode=mode)
    for key, value in wanted.items():
        found = _pattern(key).findall(raw)
        if len(found) != 1:
            raise RulesError(f'the game\'s rules file has the rule "{key}" {len(found)} times: not the file this patch knows')
        raw = _pattern(key).sub(lambda m, v=value.encode(): m.group(1) + v + m.group(3), raw, count=1)
    return raw
