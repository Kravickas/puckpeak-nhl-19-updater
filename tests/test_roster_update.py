"""'Update to today's NHL' groundwork: the NHL.com client (no network: a fake fetcher) and name+birthdate matching."""
import json

import pytest

from overtime_core import nhlcom
from overtime_core.matching import Matcher, Person, norm


class Fake:
    def __init__(self, bodies):
        self.bodies, self.urls = bodies, []

    def __call__(self, url):
        self.urls.append(url)
        body = self.bodies[url[len(nhlcom.BASE):]]
        if isinstance(body, Exception):
            raise body
        return json.dumps(body).encode() if not isinstance(body, bytes) else body


class Clock:
    def __init__(self):
        self.t, self.slept = 1000.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


ROSTER = {'forwards': [{'id': 8478402, 'firstName': {'default': 'Connor'}, 'lastName': {'default': 'McDavid'},
                        'birthDate': '1997-01-13', 'sweaterNumber': 97, 'positionCode': 'C', 'shootsCatches': 'L',
                        'heightInCentimeters': 185, 'weightInKilograms': 88, 'birthCountry': 'CAN',
                        'birthCity': {'default': 'Richmond Hill'}}],
          'defensemen': [], 'goalies': [{'id': 1, 'firstName': {'default': 'Stuart'},
                                         'lastName': {'default': 'Skinner'}, 'positionCode': 'G'}]}


def test_client_caches_for_ttl():
    clock = Clock()
    fake = Fake({'/roster/EDM/current': ROSTER})
    c = nhlcom.Client(fetch=fake, clock=clock, sleep=clock.sleep, ttl=600)
    assert c.roster('EDM') == ROSTER
    clock.t += 599
    assert c.roster('EDM') == ROSTER
    assert c.requests == 1
    clock.t += 2
    c.roster('EDM')
    assert c.requests == 2


def test_client_disk_cache(tmp_path):
    clock = Clock()
    fake = Fake({'/roster/EDM/current': ROSTER})
    nhlcom.Client(cache_dir=str(tmp_path), fetch=fake, clock=clock, sleep=clock.sleep).roster('EDM')
    again = nhlcom.Client(cache_dir=str(tmp_path), fetch=fake, clock=clock, sleep=clock.sleep)
    assert again.roster('EDM') == ROSTER and again.requests == 0
    clock.t += nhlcom.ROSTER_TTL + 1
    again.roster('EDM')
    assert again.requests == 1


def test_client_spaces_requests():
    clock = Clock()
    fake = Fake({'/roster/EDM/current': ROSTER, '/roster/CGY/current': ROSTER})
    c = nhlcom.Client(fetch=fake, clock=clock, sleep=clock.sleep, min_interval=1.0)
    c.roster('EDM')
    clock.t += 0.25
    c.roster('CGY')
    assert clock.slept == [pytest.approx(0.75)]


def test_client_errors():
    clock = Clock()
    fake = Fake({'/player/5/landing': OSError('offline'), '/standings/now': b'<html>'})
    c = nhlcom.Client(fetch=fake, clock=clock, sleep=clock.sleep, min_interval=0)
    with pytest.raises(nhlcom.NhlComError, match='offline'):
        c.player(5)
    with pytest.raises(nhlcom.NhlComError, match='not JSON'):
        c.standings()


def test_team_abbrevs_and_roster_players():
    clock = Clock()
    fake = Fake({'/standings/now': {'standings': [{'teamAbbrev': {'default': 'EDM'}}, {'teamAbbrev': {'default': 'ANA'}},
                                                  {'teamAbbrev': {'default': 'EDM'}}]}})
    assert nhlcom.Client(fetch=fake, clock=clock, sleep=clock.sleep).team_abbrevs() == ['ANA', 'EDM']
    players = nhlcom.roster_players(ROSTER, 'EDM')
    assert [p['last'] for p in players] == ['McDavid', 'Skinner']
    assert players[0] == {'id': 8478402, 'first': 'Connor', 'last': 'McDavid', 'birth': '1997-01-13', 'number': 97,
                          'position': 'C', 'shoots': 'L', 'height': 185, 'weight': 88, 'country': 'CAN',
                          'birthplace': 'Richmond Hill', 'team': 'EDM'}
    assert players[1]['birthplace'] == ''


def test_norm():
    assert norm('Pierre-Luc Dubois') == 'pierreluc dubois'
    assert norm('Tim Stützle') == 'tim stutzle'
    assert norm("Ryan O'Reilly") == 'ryan oreilly'
    assert norm('Martin St. Louis Jr.') == 'martin st louis'
    assert norm('Mats Zuccarello-Aasen') == norm('Mats Zuccarelloaasen')


GAME = [Person(1, 'Connor', 'McDavid', '1997-01-13'), Person(2, 'Mitch', 'Marner', '1997-05-05'),
        Person(3, 'Sebastian', 'Aho', '1997-07-26'), Person(4, 'Sebastian', 'Aho', '1996-02-17'),
        Person(5, 'Leon', 'Draisaitl', '1995-10-27')]


def test_match_levels():
    m = Matcher(GAME)
    assert m.match(Person('a', 'Connor', 'McDavid', '1997-01-13')).level == 'exact'
    hit = m.match(Person('b', 'Mitchell', 'Marner', '1997-05-05'))
    assert (hit.level, hit.game.key) == ('date', 2)
    assert m.match(Person('c', 'Leon', 'Draisaitl', '1995-10-28')).level == 'name'  # birth date typo
    assert m.match(Person('d', 'Sebastian', 'Aho', '1996-02-17')).game.key == 4  # namesakes split by date
    assert m.match(Person('e', 'Sebastian', 'Aho', '')).level == 'none'  # two namesakes, no date: no guess
    assert m.match(Person('f', 'Macklin', 'Celebrini', '2006-06-13')).level == 'none'


def test_match_all_gives_each_game_player_once():
    m = Matcher(GAME)
    out = m.match_all([Person('x', 'Leon', 'Draisaitl', ''), Person('y', 'Leon', 'Draisaitl', '1995-10-27')])
    assert [(r.level, r.game.key if r.game else None) for r in out] == [('none', None), ('exact', 5)]
