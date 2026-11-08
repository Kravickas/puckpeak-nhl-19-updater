"""The app's side of the lobby API (`docs/notes/lobby.md`): small JSON calls over HTTP with the standard library.

`LobbyClient(base_url, opener)`: `opener(request, timeout)` is `net.urlopen` (Windows' certificates plus Mozilla's list)
unless a test passes its own.
A server answer that is an error becomes `LobbyRefused(status, text)` with the server's `{error}` text; no answer
(refused connection, timeout, a page that is not JSON) is `LobbyDown`. Names and codes are sent as JSON, never put in a
URL query; the secret `token` goes in the body of the POST that needs it.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from overtime_core import net

TIMEOUT = 8
CODE = re.compile(r'^[A-Za-z0-9]{3,12}$')


class LobbyError(Exception):
    pass


class LobbyDown(LobbyError):
    """The lobby service did not answer (or did not speak JSON). `certificate`: this PC could not check its certificate
    (net.certificate_failed), so the internet is fine and the PC's list of trusted certificates is not."""

    def __init__(self, text, certificate=False):
        super().__init__(text)
        self.certificate = certificate


class LobbyRefused(LobbyError):
    def __init__(self, status, text):
        super().__init__(text)
        self.status, self.text = status, text


def lab_url(url):
    """True for a lab URL (this PC): http on 127.0.0.1 / localhost / [::1]."""
    p = urllib.parse.urlsplit(url or '')
    return p.scheme == 'http' and p.hostname in ('127.0.0.1', 'localhost', '::1')


def _code(code):
    code = str(code or '').strip().upper()
    if not CODE.match(code):
        raise LobbyRefused(422, 'That is not a lobby code.')
    return code


class LobbyClient:
    def __init__(self, base_url, opener=None, timeout=TIMEOUT):
        self.base = base_url.rstrip('/')
        self._open = opener or net.urlopen
        self.timeout = timeout

    def _call(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
        try:
            with self._open(req, timeout=self.timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as err:
            raise self._refused(err.code, err.read()) from None
        except (urllib.error.URLError, OSError, ValueError) as err:
            raise LobbyDown(f'the lobby service did not answer ({err})', net.certificate_failed(err)) from None
        return self._json(raw)

    @staticmethod
    def _json(raw):
        try:
            return json.loads(raw or b'null')
        except ValueError:
            raise LobbyDown('the lobby service did not send JSON') from None

    @staticmethod
    def _refused(status, raw):
        try:
            text = (json.loads(raw) or {}).get('error')
        except (ValueError, AttributeError):
            text = None
        return LobbyRefused(status, text or f'the lobby service answered {status}')

    # --- the API ----------------------------------------------------------------------------------------------------
    def create(self, name, ext, public=False, roster_crc=None, mode=None):
        return self._call('POST', '/api/lobby', {'name': name, 'ext': ext, 'public': bool(public),
                                                  **({'roster_crc': roster_crc} if roster_crc else {}),
                                                  **({'mode': mode} if mode else {})})

    def join(self, code, name, ext, roster_crc=None):
        return self._call('POST', f'/api/lobby/{_code(code)}/join',
                          {'name': name, 'ext': ext, **({'roster_crc': roster_crc} if roster_crc else {})})

    def ready(self, code, token, value=True, patch=None, game=None, caps=None):
        """Ready on or off. `caps` (0.80: ['match_setup']) tells the server what this app can do; it keeps them until
        sent again, so an app announces them right after create/join (docs/notes/lobby.md "Match recipe")."""
        return self._call('POST', f'/api/lobby/{_code(code)}/ready', {'token': token, 'ready': bool(value),
                                                                      **({'patch': patch} if patch else {}),
                                                                      **({'game': game} if game else {}),
                                                                      **({'caps': list(caps)} if caps else {})})

    def match(self, code, token, recipe):
        """The host's match recipe (matchsetup.recipe), or None to clear it."""
        return self._call('POST', f'/api/lobby/{_code(code)}/match', {'token': token, 'match': recipe})

    def mode(self, code, token, mode):
        """The host picks the game, 'versus', 'shootout' or 'threes' (a server before 0.71 has no such call: 404)."""
        return self._call('POST', f'/api/lobby/{_code(code)}/mode', {'token': token, 'mode': mode})

    def roster_mode(self, code, token, mode):
        return self._call('POST', f'/api/lobby/{_code(code)}/roster_mode', {'token': token, 'mode': mode})

    def upload_roster(self, code, token, blob):
        """The host's own roster_h2h bytes for a lobby on 'host' (overtime_server/http/appupdate.py _host_roster)."""
        q = urllib.parse.urlencode({'token': token})
        req = urllib.request.Request(f'{self.base}/api/lobby/{_code(code)}/roster?{q}', data=bytes(blob), method='POST',
                                     headers={'Content-Type': 'application/octet-stream', 'Accept': 'application/json'})
        try:
            with self._open(req, timeout=max(self.timeout, 60)) as r:
                raw = r.read()
        except urllib.error.HTTPError as err:
            raise self._refused(err.code, err.read()) from None
        except (urllib.error.URLError, OSError, ValueError) as err:
            raise LobbyDown(f'the lobby service did not answer ({err})', net.certificate_failed(err)) from None
        return self._json(raw)

    def settings(self, code, token, rules):
        """The host sets match rules ({key: value}); the lobby comes back (both ready flags cleared on a change)."""
        return self._call('POST', f'/api/lobby/{_code(code)}/settings', {'token': token, 'rules': rules})

    def say(self, code, token, text):
        """A chat line to the lobby (in the body); the lobby comes back with the chat so far."""
        return self._call('POST', f'/api/lobby/{_code(code)}/say', {'token': token, 'text': text})

    def state(self, code, token):
        return self._call('POST', f'/api/lobby/{_code(code)}/state', {'token': token})

    def leave(self, code, token):
        return self._call('POST', f'/api/lobby/{_code(code)}/leave', {'token': token})

    def lobbies(self):
        return self._call('GET', '/api/lobbies')

    def history(self, ext=None, pid=None, limit=None):
        """The match history: {me, matches, players, detail}. `ext` only tells the server which pid is mine; `pid` asks
        for that player's detail. Both go in the body, like every id."""
        body = {k: v for k, v in (('ext', ext), ('pid', pid), ('limit', limit)) if v}
        return self._call('POST', '/api/history', body)

    def review(self, ext, match=None):
        """How I did in my latest (or the given) confirmed match: {review: {...} | None}."""
        body = {'ext': ext}
        if match is not None:
            body['match'] = match
        return self._call('POST', '/api/history/review', body)

    def privacy(self, ext, hidden):
        """Hide me from (or show me on) the public web board; my games still rate."""
        return self._call('POST', '/api/history/privacy', {'ext': ext, 'hidden': bool(hidden)})

    def result(self, ext, match, team, score_for, score_against):
        """I say how match `match` ended (my team, my score, theirs); the match comes back with its result."""
        return self._call('POST', '/api/history/result', {'ext': ext, 'match': match, 'team': team,
                                                          'score_for': score_for, 'score_against': score_against})
