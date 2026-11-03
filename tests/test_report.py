"""The change report's list by team (overtime_roster.app.report), from the lines Update writes (update.details)."""
import datetime
import types

from overtime_core import rosterupdate as U
from overtime_roster.app import report, update

NAMES = {1: 'Boston Bruins', 2: 'Toronto Maple Leafs', 3: 'Providence Bruins'}


def lines():
    todo = U.Plan(moves=[(10, 'Mitch Marner', (0, 2), (0, 1)), (11, 'Old Guy', (0, 1), 'FA')],
                  new=[({'first': 'Ivan', 'last': 'Demidov'}, (0, 2))],
                  releases=[(12, 'Spare Part', (0, 2))])
    rep = U.Report({}, [], [], 0, {}, [], [], [], signed=[(13, 'Free Man', (0, 1))], retired=[(14, 'Grey Beard', 41)],
                   called_up=[(15, 'Young Gun', (0, 3), (0, 1))])
    return update.details(todo, rep, lambda team, table: NAMES[team])


def test_moves_are_listed_under_both_teams_and_retirements_under_the_free_agents():
    teams = report.by_team(lines())
    assert list(teams) == ['Boston Bruins', 'Providence Bruins', 'Toronto Maple Leafs', 'Free agents']
    assert teams['Boston Bruins'] == [('Joined', 'Mitch Marner', 'from Toronto Maple Leafs'),
                                      ('Signed', 'Free Man', 'a free agent'),
                                      ('Called up', 'Young Gun', 'from Providence Bruins'),
                                      ('Released', 'Old Guy', '')]
    assert teams['Providence Bruins'] == [('Called up to', 'Young Gun', 'Boston Bruins')]
    assert teams['Toronto Maple Leafs'] == [('New player', 'Ivan Demidov', ''),
                                            ('Left', 'Mitch Marner', 'to Boston Bruins'),
                                            ('Released', 'Spare Part', '')]
    assert teams['Free agents'] == [('Joined', 'Old Guy', 'from Boston Bruins'),
                                    ('Joined', 'Spare Part', 'from Toronto Maple Leafs'),
                                    ('Retired', 'Grey Beard', 'at 41')]


def test_the_report_has_the_teams_before_the_full_list(tmp_path):
    changes = lines() + [('Mitch Marner: shooting', 80, 85)]       # an edit of his own: in the full list only
    path = report.write(str(tmp_path / 'report.html'), 'My roster', 'default', 'save', 'folder', '5E1A93C4', changes,
                        [types.SimpleNamespace(level='warning', rule='r', message='m')], datetime.datetime(2026, 11, 3))
    text = open(path, encoding='utf-8').read()
    assert text.index('By team (4)') < text.index(f'Changes ({len(changes)})')
    assert '<summary>Boston Bruins<span>1 joined, 1 signed, 1 called up, 1 released</span></summary>' in text
    assert 'Mitch Marner: shooting' in text and text.count('Mitch Marner') == 4   # 2 by team, 2 in the full list


def test_a_report_without_moves_has_no_team_list(tmp_path):
    path = report.write(str(tmp_path / 'r.html'), 'Edits', 'default', 'save', 'folder', 'C', [('A: born', 1, 2)], [],
                        datetime.datetime(2026, 11, 3))
    assert 'By team' not in open(path, encoding='utf-8').read()
