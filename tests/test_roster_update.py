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


class Slow:
    """A fetcher that takes `delay` seconds of real time per request and notes how many run at once and when each
    started."""
    def __init__(self, body, delay=0.05):
        import threading
        self.body, self.delay, self.lock = body, delay, threading.Lock()
        self.now = self.peak = 0
        self.starts, self.urls = [], []

    def __call__(self, url):
        import time
        with self.lock:
            self.now += 1
            self.peak = max(self.peak, self.now)
            self.starts.append(time.monotonic())
            self.urls.append(url)
        time.sleep(self.delay)
        with self.lock:
            self.now -= 1
        return json.dumps(self.body(url) if callable(self.body) else self.body).encode()


def test_rosters_of_the_clubs_are_asked_for_at_once_and_come_back_in_club_order():
    """32 clubs one after another, each waiting a second after the one before had answered, was over a minute of
    every first update: they are asked for a few at a time now, spaced by their start, and the list is the same."""
    from overtime_core import calendar, rosterupdate as U
    fetch = Slow(lambda url: {'forwards': [{'id': 1, 'firstName': {'default': url.split('/')[-2]},
                                            'lastName': {'default': 'X'}, 'positionCode': 'C'}]})
    c = nhlcom.Client(fetch=fetch, min_interval=0)
    got = U.gather_rosters(c, 2026)
    assert fetch.peak > 1
    assert [p['team'] for p in got] == sorted(calendar.SLOTS) and [p['first'] for p in got] == sorted(calendar.SLOTS)
    assert c.requests == len(calendar.SLOTS)


def test_club_schedules_are_asked_for_at_once_and_give_the_same_calendar():
    from overtime_core import calendar
    games = lambda url: {'games': [{'id': 7, 'gameDate': '2026-10-07', 'homeTeam': {'abbrev': 'TOR'},   # noqa: E731
                                    'awayTeam': {'abbrev': 'MTL'}, 'gameType': 2},
                                   {'id': 5, 'gameDate': '2026-10-07', 'homeTeam': {'abbrev': 'EDM'},
                                    'awayTeam': {'abbrev': 'CGY'}, 'gameType': 2}]}
    fetch = Slow(games)
    got = calendar.season_games(nhlcom.Client(fetch=fetch, min_interval=0), 2026)
    assert fetch.peak > 1
    assert got == [('2026-10-07', 'EDM', 'CGY'), ('2026-10-07', 'TOR', 'MTL')]


def test_requests_asked_for_at_once_still_start_min_interval_apart():
    """Several threads ask at once: NHL.com still gets at most one request per `min_interval`."""
    from concurrent.futures import ThreadPoolExecutor
    fetch = Slow({}, delay=0.01)
    c = nhlcom.Client(fetch=fetch, min_interval=0.05)
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(c.player, range(8)))
    starts = sorted(fetch.starts)
    assert c.requests == 8 and min(b - a for a, b in zip(starts, starts[1:])) >= 0.045


def _http(code, after=None):
    import email.message
    import urllib.error
    headers = email.message.Message()
    if after is not None:
        headers['Retry-After'] = str(after)
    return urllib.error.HTTPError('https://api-web.nhle.com/v1/x', code, 'no', headers, None)


class Answers:
    """A fetcher answering each path from a list, in turn (an exception is raised)."""
    def __init__(self, answers):
        self.answers, self.urls = answers, []

    def __call__(self, url):
        self.urls.append(url)
        got = self.answers[url[len(nhlcom.BASE):]].pop(0)
        if isinstance(got, Exception):
            raise got
        return json.dumps(got).encode()


def test_too_many_requests_waits_what_nhl_com_asks_and_asks_again():
    clock = Clock()
    fake = Answers({'/roster/EDM/current': [_http(429, 2), ROSTER]})
    c = nhlcom.Client(fetch=fake, clock=clock, sleep=clock.sleep)
    assert c.roster('EDM') == ROSTER
    assert clock.slept == [pytest.approx(2.0)] and c.requests == 2


def test_a_moment_of_server_trouble_backs_off_doubling_then_gives_up():
    clock = Clock()
    fake = Answers({'/roster/EDM/current': [_http(503), _http(502), ROSTER],
                    '/roster/CGY/current': [_http(503)] * nhlcom.TRIES})
    c = nhlcom.Client(fetch=fake, clock=clock, sleep=clock.sleep)
    assert c.roster('EDM') == ROSTER and clock.slept == [pytest.approx(1.0), pytest.approx(2.0)]
    with pytest.raises(nhlcom.NhlComError, match='503'):
        c.roster('CGY')
    assert len([u for u in fake.urls if 'CGY' in u]) == nhlcom.TRIES


def test_a_missing_page_is_not_asked_again():
    clock = Clock()
    fake = Answers({'/player/5/landing': [_http(404)]})
    with pytest.raises(nhlcom.NhlComError, match='404'):
        nhlcom.Client(fetch=fake, clock=clock, sleep=clock.sleep).player(5)
    assert clock.slept == [] and len(fake.urls) == 1


def test_one_too_many_answer_holds_back_the_other_requests_too():
    """Asked all at once: one 429 makes every request wait, not only the one it answered."""
    import threading
    import time
    starts, first = {}, threading.Event()

    def fetch(url):
        name = url.rsplit('/', 2)[-2]
        starts.setdefault(name, []).append(time.monotonic())
        if name == 'EDM' and len(starts[name]) == 1:
            first.set()
            raise _http(429, 0.3)
        return json.dumps(ROSTER).encode()
    c = nhlcom.Client(fetch=fetch)
    t = threading.Thread(target=c.roster, args=('EDM',))
    t.start()
    first.wait(5)
    time.sleep(0.05)
    c.roster('CGY')
    t.join()
    assert starts['CGY'][0] - starts['EDM'][0] >= 0.28 and len(starts['EDM']) == 2
