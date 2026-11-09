"""The match rules table and the byte edit of the game's rules file (a synthetic file in the game's shape: no game data)."""
import pytest

from overtime_core import rules


def fake(**values):
    """A rules file in the game's shape: CRLF, 4-space indent, one block per rule, plus a gametype rule."""
    body = []
    for key in ('gametype',) + rules.KEYS:
        value = values.get(key, rules.stock().get(key, '23'))
        body.append('                {\r\n'
                    f'                    "rulename": "{key}",\r\n'
                    f'                    "attributename": "NHL_{key.title()}",\r\n'
                    f'                    "sagameattributetag": "SA_GAMEATTRIBUTE_{key.upper()}",\r\n'
                    f'                    "defaultvalue": "{value}"\r\n'
                    '                }')
    return ('{\r\n    "rules":\r\n    {\r\n        "custom":\r\n        {\r\n            "game":\r\n            [\r\n'
            + ',\r\n'.join(body) + '\r\n            ]\r\n        }\r\n    }\r\n}\r\n').encode()


def test_table_is_consistent():
    assert len(rules.RULES) == 11 and len(set(rules.KEYS)) == 11
    for key, name, options, default in rules.RULES:
        assert name and default in dict(options), key
        assert len({v for v, _ in options}) == len(options), key


def test_validate_fills_defaults_and_stringifies():
    out = rules.validate({'periodlength': 10, 'fighting': '0'})
    assert out['periodlength'] == '10' and out['fighting'] == '0' and out['icing'] == rules.DEFAULTS['icing']
    assert set(out) == set(rules.KEYS)
    assert rules.validate({'periodlength': 10}, partial=True) == {'periodlength': '10'}


@pytest.mark.parametrize('bad', [{'periodlength': 7}, {'nope': 1}, {'fighting': True}, {'icing': None}, {'gamestyle': '9'},
                                 {'periodlength': [10]}, 'periodlength=10'])
def test_validate_refuses(bad):
    with pytest.raises(rules.RulesError):
        rules.validate(bad)


def test_lobbies_start_at_three_minute_periods_and_the_game_ships_four():
    assert rules.DEFAULTS['periodlength'] == '3' and rules.RULES[0][2][0] == ('3', '3 min')
    stock = rules.stock()
    assert stock == dict(rules.DEFAULTS, periodlength='4')          # the game's file: match-rules.md "Stock defaults"
    assert rules.stock(rules.SHOOTOUT) == rules.SHOOTOUT_DEFAULTS and rules.stock(rules.THREES) == {}
    stock['periodlength'] = '20'
    assert rules.stock()['periodlength'] == '4'                     # a copy each time
    assert rules.read(rules.edit(fake(), {'periodlength': 3}))['periodlength'] == '3'
    assert rules.summary(rules.stock()) == '4 min'


def test_summary_names_only_what_differs():
    assert rules.summary(rules.DEFAULTS) == 'Default rules'
    assert rules.summary({'periodlength': '10', 'gamestyle': '3', 'fighting': '0'}) == '10 min · Full sim · Fighting off'


def test_edit_changes_only_the_given_default_values():
    raw = fake()
    new = rules.edit(raw, {'periodlength': 10, 'gamestyle': 3, 'fighting': 0})
    assert rules.read(new)['periodlength'] == '10' and rules.read(new)['gamestyle'] == '3' and rules.read(new)['fighting'] == '0'
    assert new.count(b'\r\n') == raw.count(b'\r\n') and len(new) == len(raw) + 1  # '4' -> '10' is the one longer value
    assert new == fake(periodlength='10', gamestyle='3', fighting='0')
    assert rules.edit(raw, {}) == raw
    assert rules.edit(raw, rules.read(raw)) == raw           # the file's own values are a no-op


def test_edit_refuses_another_shape():
    raw = fake()
    with pytest.raises(rules.RulesError, match='0 times'):
        rules.edit(raw.replace(b'"rulename": "icing"', b'"rulename": "ice"'), {'icing': 1})
    block = raw[raw.index(b'                {\r\n                    "rulename": "fighting"'):]
    block = block[:block.index(b'}') + 1]
    with pytest.raises(rules.RulesError, match='2 times'):
        rules.edit(raw.replace(block, block + b',\r\n' + block), {'fighting': 0})
    with pytest.raises(rules.RulesError):
        rules.edit(raw, {'periodlength': 7})


def shootout_file(**values):
    """The Online Shootout rules file's shape: the rules the game lists, with its shootoutrules / shootoutshots too."""
    keys = ('gametype', 'shootoutrules', 'goaliecontrol', 'shootoutshots', 'skilllevel', 'gamestyle')
    base = {'gametype': '25', 'shootoutrules': '1', 'shootoutshots': '5', **rules.SHOOTOUT_DEFAULTS}
    body = [('                {\r\n'
             f'                    "rulename": "{k}",\r\n'
             f'                    "attributename": "NHL_{k.title()}",\r\n'
             f'                    "sagameattributetag": "SA_GAMEATTRIBUTE_{k.upper()}",\r\n'
             f'                    "defaultvalue": "{values.get(k, base[k])}"\r\n'
             '                }') for k in keys]
    return ('{\r\n    "rules":\r\n    {\r\n        "custom":\r\n        {\r\n            "game":\r\n            [\r\n'
            + ',\r\n'.join(body) + '\r\n            ]\r\n        }\r\n    }\r\n}\r\n').encode()


def test_shootout_table_is_the_short_one():
    assert [r[0] for r in rules.table(rules.SHOOTOUT)] == ['skilllevel', 'gamestyle', 'goaliecontrol']
    assert rules.defaults(rules.SHOOTOUT) == {'skilllevel': '3', 'gamestyle': '2', 'goaliecontrol': '1'}
    assert rules.path(rules.SHOOTOUT) != rules.path(rules.VERSUS) and 'shootout' in rules.path(rules.SHOOTOUT)
    assert rules.table() is rules.RULES and rules.defaults() == rules.DEFAULTS
    with pytest.raises(rules.RulesError):
        rules.table('hut')


def test_validate_per_mode_refuses_rules_the_mode_lacks():
    assert rules.validate({'goaliecontrol': 0}, mode=rules.SHOOTOUT) == {**rules.SHOOTOUT_DEFAULTS, 'goaliecontrol': '0'}
    assert set(rules.validate({}, mode=rules.SHOOTOUT)) == {'skilllevel', 'gamestyle', 'goaliecontrol'}
    for bad in ({'periodlength': 10}, {'icing': 0}, {'tiebreaker': 1}):
        with pytest.raises(rules.RulesError):
            rules.validate(bad, mode=rules.SHOOTOUT)
    assert rules.validate({'periodlength': 10})['periodlength'] == '10'      # Versus is as before


def test_shootout_summary_and_edit():
    assert rules.summary(rules.SHOOTOUT_DEFAULTS, rules.SHOOTOUT) == 'Default rules'
    assert rules.summary({'skilllevel': '4', 'goaliecontrol': '0'}, rules.SHOOTOUT) == 'Superstar · Goalie in shootout off'
    raw = shootout_file()
    new = rules.edit(raw, {'skilllevel': 4, 'goaliecontrol': 0}, mode=rules.SHOOTOUT)
    assert rules.read(new)['skilllevel'] == '4' and rules.read(new)['goaliecontrol'] == '0'
    assert b'"defaultvalue": "5"' in new and b'"defaultvalue": "25"' in new       # shots per round and game type stay
    assert rules.edit(raw, {}, mode=rules.SHOOTOUT) == raw
    with pytest.raises(rules.RulesError):
        rules.edit(raw, {'periodlength': 10}, mode=rules.SHOOTOUT)
