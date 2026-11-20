"""NHL.com public JSON API client (`https://api-web.nhle.com/v1`) with a TTL cache. Standard library only.

Used by the "Update to today's NHL" pipeline (skeleton): team rosters (`/roster/{TEAM}/current`), player pages
(`/player/{id}/landing`), the current standings (`/standings/now`, for the list of teams) and club schedules
(`/club-schedule-season/{TEAM}/{season}`, for the calendar).
Up to WORKERS requests run at once (`each`), each starting at least `min_interval` seconds after the one before (0:
none). NHL.com saying "too many" (429) or failing for a moment (5xx) makes every request wait what it asks (Retry-After,
else BACKOFF doubling) and that one is asked again, TRIES times in all. Answers are cached in memory and, when
`cache_dir` is given, on disk as JSON files, for `ttl` seconds (rosters change at most a few times a day).
"""
import concurrent.futures
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request

from . import durable, net

BASE = 'https://api-web.nhle.com/v1'
ROSTER_TTL = 20 * 60
# All at once (a first update: 32 rosters, 32 schedules, the player pages it reads), backing off when NHL.com asks.
# Before, one request at a time, each a second after the one before had answered: the 64 club requests alone were over
# a minute.
MIN_INTERVAL = 0.0
WORKERS = 64
TRIES = 4                   # a request answered 429 / 5xx is asked again up to 3 times
BACKOFF = 1.0               # seconds before the first try again without a Retry-After: 1, 2, 4
MAX_WAIT = 30.0             # the longest Retry-After waited for
RETRY_CODES = (429, 500, 502, 503, 504)
USER_AGENT = 'OvertimeRoster/0.1 (+offline NHL 19 roster editor)'


class NhlComError(RuntimeError):
    pass


def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    with net.urlopen(req, timeout=timeout) as r:
        return r.read()


class Client:
    def __init__(self, cache_dir=None, ttl=ROSTER_TTL, fetch=None, clock=time.time, min_interval=MIN_INTERVAL,
                 sleep=time.sleep):
        self.cache_dir = cache_dir
        self.ttl = ttl
        self._fetch = fetch or _http_get
        self._clock = clock
        self._sleep = sleep
        self.min_interval = min_interval
        self._mem = {}
        self._last = None       # when the last request started (or is due to)
        self._resume = 0.0      # no request starts before this (NHL.com said 429 / 5xx)
        self._lock = threading.Lock()
        self.requests = 0  # network requests made (tests, report)

    # --- cache -----------------------------------------------------------------------------------
    def _path(self, url):
        return os.path.join(self.cache_dir, hashlib.sha1(url.encode()).hexdigest()[:20] + '.json')

    def _cached(self, url):
        now = self._clock()
        hit = self._mem.get(url)
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        if self.cache_dir:
            try:
                with open(self._path(url), encoding='utf-8') as f:
                    rec = json.load(f)
                if rec.get('url') == url and now - rec['at'] < self.ttl:
                    self._mem[url] = (rec['at'], rec['body'])
                    return rec['body']
            except (OSError, ValueError, KeyError):
                pass
        return None

    def _store(self, url, body):
        at = self._clock()
        self._mem[url] = (at, body)
        if self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)
            tmp = self._path(url) + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({'url': url, 'at': at, 'body': body}, f)
            durable.replace(tmp, self._path(url))

    # --- requests --------------------------------------------------------------------------------
    def get(self, path):
        """The answer to `path`, cached or asked for (any thread: the lock covers the cache and the start times, not
        the request itself, so requests of several threads overlap while they still start `min_interval` apart)."""
        url = BASE + path
        with self._lock:
            body = self._cached(url)
            if body is not None:
                return body
        for attempt in range(TRIES):
            with self._lock:
                now = self._clock()
                start = max(now, self._resume)
                if self._last is not None:
                    start = max(start, self._last + self.min_interval)
                self._last = start
                self.requests += 1
            if start > now:
                self._sleep(start - now)
            try:
                raw = self._fetch(url)
                break
            except urllib.error.HTTPError as err:
                if err.code not in RETRY_CODES or attempt == TRIES - 1:
                    raise NhlComError(f"NHL.com: {path}: {err}") from err
                pause = _retry_after(err)
                pause = BACKOFF * 2 ** attempt if pause is None else min(pause, MAX_WAIT)
                with self._lock:            # every request waits, not only this one
                    self._resume = max(self._resume, self._clock() + pause)
            except Exception as err:  # network errors
                raise NhlComError(f"NHL.com: {path}: {err}") from err
        try:
            body = json.loads(raw)
        except ValueError as err:
            raise NhlComError(f"NHL.com: {path}: not JSON") from err
        with self._lock:
            self._store(url, body)
        return body

    def standings(self):
        return self.get('/standings/now')

    def team_abbrevs(self):
        """Current NHL team abbreviations (from the standings)."""
        rows = self.standings().get('standings', [])
        return sorted({(r.get('teamAbbrev') or {}).get('default') for r in rows} - {None})

    def roster(self, team, season='current'):
        return self.get(f'/roster/{team}/{season}')

    def player(self, player_id):
        return self.get(f'/player/{int(player_id)}/landing')

    def club_schedule(self, team, season):
        """Every game of a club in a season (`season` as '20262027'), all game types."""
        return self.get(f'/club-schedule-season/{team}/{season}')


def _retry_after(err):
    """The seconds an HTTP error's Retry-After asks for (None: none, or a date)."""
    try:
        value = float((err.headers or {}).get('Retry-After'))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def each(fn, items, workers=WORKERS):
    """[fn(item)] in the order of `items`, up to `workers` at once (fn asks a Client: it spaces the requests). The
    first item that raises, in order, raises here, as in a loop."""
    items = list(items)
    if workers <= 1 or len(items) < 2:
        return [fn(item) for item in items]
    with concurrent.futures.ThreadPoolExecutor(min(workers, len(items)), thread_name_prefix='nhlcom') as pool:
        return list(pool.map(fn, items))


PRESEASON, REGULAR, PLAYOFFS = 1, 2, 3  # gameType


def schedule_games(body, game_type=REGULAR):
    """Flatten a `/club-schedule-season/...` answer into plain dicts: id, date (YYYY-MM-DD, as NHL.com lists the
    game), home, away (team codes), type. Only games of `game_type` (None: all)."""
    out = []
    for g in body.get('games', []) or []:
        if game_type is not None and g.get('gameType') != game_type:
            continue
        out.append({'id': g.get('id'), 'date': g.get('gameDate', ''), 'home': (g.get('homeTeam') or {}).get('abbrev'),
                    'away': (g.get('awayTeam') or {}).get('abbrev'), 'type': g.get('gameType')})
    return out


def landing_player(body):
    """A `/player/{id}/landing` answer as a roster_players row, its `team` the player's club now (None: no NHL club) and
    `active` whether he still plays."""
    return {'id': body.get('playerId'),
            'first': (body.get('firstName') or {}).get('default', ''),
            'last': (body.get('lastName') or {}).get('default', ''),
            'birth': body.get('birthDate', ''),
            'number': body.get('sweaterNumber'),
            'position': body.get('position', ''),
            'shoots': body.get('shootsCatches', ''),
            'height': body.get('heightInCentimeters'),
            'weight': body.get('weightInKilograms'),
            'country': body.get('birthCountry', ''),
            'birthplace': (body.get('birthCity') or {}).get('default', ''),
            'team': body.get('currentTeamAbbrev'),
            'active': bool(body.get('isActive'))}


def roster_players(body, team=None):
    """Flatten a `/roster/...` answer into plain dicts: id, first, last, birth (YYYY-MM-DD), number, position,
    shoots, height (cm), weight (kg), country, birthplace (the city, as NHL 19 writes it), team."""
    out = []
    for group in ('forwards', 'defensemen', 'goalies'):
        for p in body.get(group, []) or []:
            out.append({
                'id': p.get('id'),
                'first': (p.get('firstName') or {}).get('default', ''),
                'last': (p.get('lastName') or {}).get('default', ''),
                'birth': p.get('birthDate', ''),
                'number': p.get('sweaterNumber'),
                'position': p.get('positionCode', ''),
                'shoots': p.get('shootsCatches', ''),
                'height': p.get('heightInCentimeters'),
                'weight': p.get('weightInKilograms'),
                'country': p.get('birthCountry', ''),
                'birthplace': (p.get('birthCity') or {}).get('default', ''),
                'team': team,
            })
    return out
