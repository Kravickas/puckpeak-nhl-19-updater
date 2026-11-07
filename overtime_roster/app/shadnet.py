"""Talk to ShadNet directly: check an Online ID + password and learn the account id, and make a new account.

So a player can sign in (and sign up) in the app and play at once, without starting NHL 19 first to find out their
account id. Written from the protocol facts in docs/notes/shadnet-protocol.md (TCP login: header, protobuf fields,
error codes; sign-up: the shadps4.net form's JSON endpoint)."""
import json
import socket
import struct
import urllib.error
import urllib.request

HOST = 'srv.shadps4.net'
PORT = 31313
REGISTER_URL = 'https://www.shadps4.net/scripts/register.php'
TIMEOUT = 15

PROTOCOL = 1
HEADER = struct.Struct('<BHIQ')          # type, command, size (whole packet), packet id
REQUEST, REPLY, NOTIFICATION, SERVER_INFO = 0, 1, 2, 3
LOGIN, TERMINATE = 0, 1
TITLE_ID, TITLE_NAME = 'CUSA11126', 'NHL 19'
MAX_REPLY = 1 << 20

# the server's error byte, in the player's words
ERRORS = {
    1: 'ShadNet did not understand the app. Update Overtime.',
    3: 'ShadNet refused that Online ID or password.',
    5: 'ShadNet refused this account (it may be banned).',
    6: ('This account is signed in on another PC right now. Close shadPS4 everywhere and try again. If that is not '
        'you, someone else has your password: change it on the ShadNet site.'),
    8: ('Wrong Online ID or password. Capitals count (Skater_2 is not skater_2). New account? Confirm the e-mail '
        'ShadNet sent first.'),
    9: 'ShadNet refused the sign-in. Type the password again.',
}
PLAYER = {3, 5, 6, 8, 9}                 # codes that mean the account or password is no good


class ShadNetError(Exception):
    """ShadNet said the Online ID / password is no good; str() is the player's sentence, .code the error byte."""

    def __init__(self, text, code=None):
        super().__init__(text)
        self.code = code


class ShadNetDown(ShadNetError):
    """No usable answer: ShadNet unreachable, or a reply this client does not understand (not the player's fault)."""


# --- protobuf, just what these messages need ---------------------------------------------------------------------
def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(num, value):
    if isinstance(value, bool):
        return _varint(num << 3) + _varint(int(value))
    data = value.encode('utf-8')
    return _varint(num << 3 | 2) + _varint(len(data)) + data


def _read_varint(buf, i):
    n = shift = 0
    while True:
        if i >= len(buf) or shift > 63:
            raise ShadNetDown('ShadNet sent a reply the app cannot read.')
        b = buf[i]
        i += 1
        n |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return n, i


def _fields(buf):
    """{field number: first value} of a protobuf message (varints as int, length-delimited as bytes)."""
    out, i = {}, 0
    while i < len(buf):
        key, i = _read_varint(buf, i)
        num, kind = key >> 3, key & 7
        if kind == 0:
            value, i = _read_varint(buf, i)
        elif kind == 2:
            size, i = _read_varint(buf, i)
            value, i = bytes(buf[i:i + size]), i + size
        elif kind == 1:
            value, i = buf[i:i + 8], i + 8
        elif kind == 5:
            value, i = buf[i:i + 4], i + 4
        else:
            raise ShadNetDown('ShadNet sent a reply the app cannot read.')
        out.setdefault(num, value)
    return out


# --- TCP ---------------------------------------------------------------------------------------------------------
def _recv(sock, n):
    data = b''
    while len(data) < n:
        part = sock.recv(n - len(data))
        if not part:
            raise ShadNetDown('ShadNet closed the connection. Try again in a minute.')
        data += part
    return data


def _packet(sock):
    kind, command, size, pid = HEADER.unpack(_recv(sock, HEADER.size))
    if size < HEADER.size or size > MAX_REPLY:
        raise ShadNetDown('ShadNet sent a reply the app cannot read.')
    return kind, command, pid, _recv(sock, size - HEADER.size)


def _request(command, pid, body=b''):
    return HEADER.pack(REQUEST, command, HEADER.size + len(body), pid) + body


def login(npid, password, host=HOST, port=PORT, timeout=TIMEOUT):
    """Sign in to ShadNet as npid and out again; returns the account id (the number the game sends to Overtime).
    Signs in 'appear offline' so friends see nothing. Raises ShadNetError (a refusal) or ShadNetDown (no answer)."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError:
        raise ShadNetDown('ShadNet did not answer. Check the internet connection and try again.') from None
    try:
        with sock:
            kind, _, _, body = _packet(sock)
            if kind != SERVER_INFO or len(body) < 4:
                raise ShadNetDown('That is not a ShadNet server.')
            if struct.unpack_from('<I', body)[0] != PROTOCOL:
                raise ShadNetDown('ShadNet changed its protocol. Update Overtime.')
            msg = (_field(1, npid) + _field(2, password) + _field(4, TITLE_ID) + _field(5, TITLE_NAME)
                   + _field(6, True))
            sock.sendall(_request(LOGIN, 1, struct.pack('<I', len(msg)) + msg))
            while True:
                kind, command, pid, body = _packet(sock)
                if kind == REPLY and command == LOGIN:
                    break
            if not body:
                raise ShadNetDown('ShadNet sent a reply the app cannot read.')
            if body[0]:
                code = body[0]
                if code in PLAYER:
                    raise ShadNetError(ERRORS[code], code)
                # not the player's fault (our client, or a server change): the caller saves unchecked
                raise ShadNetDown(ERRORS.get(code, f'ShadNet answered error {code}.'), code)
            size = struct.unpack_from('<I', body, 1)[0] if len(body) >= 5 else 0
            account = _fields(body[5:5 + size]).get(2)
            try:
                sock.sendall(_request(TERMINATE, 2))
            except OSError:
                pass
    except socket.timeout:
        raise ShadNetDown('ShadNet did not answer in time. Try again in a minute.') from None
    except (OSError, struct.error):
        raise ShadNetDown('The connection to ShadNet broke. Try again in a minute.') from None
    if not isinstance(account, int) or account <= 0:
        raise ShadNetDown('ShadNet signed in but sent no account id.')
    return account


# --- sign-up (the shadps4.net form's endpoint) ---------------------------------------------------------------------
def register(npid, password, email, url=REGISTER_URL, timeout=TIMEOUT, agent='OvertimeRoster'):
    """Make a ShadNet account, as the sign-up form on shadps4.net does. Returns None; raises ShadNetError with the
    site's own reason (taken name or e-mail, ...) or ShadNetDown."""
    body = json.dumps({'npid': npid, 'password': password, 'confirm': password, 'email': email,
                       'avatar': ''}).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST',
                                 headers={'Content-Type': 'application/json', 'User-Agent': agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(MAX_REPLY)
    except urllib.error.HTTPError as err:
        raw = err.read(MAX_REPLY) if err.fp else b''
        if not raw:
            raise ShadNetDown(f'The ShadNet site answered HTTP {err.code}. Try again later.') from None
    except (urllib.error.URLError, OSError):
        raise ShadNetDown('The ShadNet site did not answer. Check the internet connection and try again.') from None
    try:
        reply = json.loads(raw.decode('utf-8', 'replace'))
    except ValueError:
        raise ShadNetDown('The ShadNet site sent an answer the app cannot read. Try again later.') from None
    if not isinstance(reply, dict) or not reply.get('success'):
        text = str((reply or {}).get('error') or 'The ShadNet site did not make the account.') if isinstance(
            reply, dict) else 'The ShadNet site did not make the account.'
        raise ShadNetError(text[:300])
