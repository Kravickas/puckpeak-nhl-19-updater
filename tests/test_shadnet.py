"""The app's own ShadNet client against a local fake server (never the real one)."""
import json
import socket
import struct
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from overtime_roster.app import shadnet as SN

HEADER = struct.Struct('<BHIQ')


def _pb_string(num, s):
    data = s.encode()
    return SN._varint(num << 3 | 2) + SN._varint(len(data)) + data


class FakeShadNet:
    """Accepts one connection: ServerInfo, then answers Login per `answer(npid, password)` -> (error, user_id)."""

    def __init__(self, answer, version=1):
        self.answer, self.version = answer, version
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.seen = {}
        self.terminated = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        conn, _ = self.sock.accept()
        with conn:
            conn.sendall(HEADER.pack(3, 0, 19, 0) + struct.pack('<I', self.version))
            if self.version != 1:
                return
            head = SN._recv(conn, HEADER.size)
            kind, cmd, size, pid = HEADER.unpack(head)
            body = SN._recv(conn, size - HEADER.size)
            n = struct.unpack_from('<I', body)[0]
            self.seen = SN._fields(body[4:4 + n])
            npid, pw = self.seen[1].decode(), self.seen[2].decode()
            conn.sendall(HEADER.pack(2, 0x123, HEADER.size, 0))           # a notification first: skipped
            err, user_id = self.answer(npid, pw)
            if err:
                reply = bytes([err])
            else:
                msg = _pb_string(1, 'http://avatar') + SN._varint(2 << 3) + SN._varint(user_id)
                reply = b'\x00' + struct.pack('<I', len(msg)) + msg
            conn.sendall(HEADER.pack(1, 0, HEADER.size + len(reply), pid) + reply)
            try:
                kind, cmd, _, _ = HEADER.unpack(SN._recv(conn, HEADER.size))
                self.terminated = cmd == SN.TERMINATE
            except SN.ShadNetError:
                pass

    def login(self, npid, pw):
        try:
            return SN.login(npid, pw, host='127.0.0.1', port=self.port, timeout=5)
        finally:
            self.thread.join(5)
            self.sock.close()


def test_login_returns_the_account_id_and_signs_out():
    srv = FakeShadNet(lambda npid, pw: (0, 16349) if (npid, pw) == ('Skater_2', 's3cret') else (8, 0))
    assert srv.login('Skater_2', 's3cret') == 16349
    assert srv.seen[4] == b'CUSA11126' and srv.seen[6] == 1                 # NHL 19, appear offline
    assert srv.terminated


@pytest.mark.parametrize('code, words, players', [(8, 'Capitals count', True), (6, 'another PC', True),
                                                  (5, 'banned', True), (42, 'error 42', False), (1, 'Update', False)])
def test_login_refusals_in_words(code, words, players):
    srv = FakeShadNet(lambda npid, pw: (code, 0))
    with pytest.raises(SN.ShadNetError) as err:
        srv.login('Skater_2', 'nope')
    assert words in str(err.value) and err.value.code == code
    assert isinstance(err.value, SN.ShadNetDown) is not players      # our fault: the caller saves unchecked


def test_a_new_protocol_is_refused_and_no_server_is_down():
    srv = FakeShadNet(lambda *a: (0, 1), version=2)
    with pytest.raises(SN.ShadNetDown, match='protocol'):
        srv.login('Skater_2', 'x')
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(SN.ShadNetDown):
        SN.login('Skater_2', 'x', host='127.0.0.1', port=port, timeout=2)


def test_protobuf_round_trip():
    msg = SN._field(1, 'Skater_2') + SN._field(6, True) + SN._varint(2 << 3) + SN._varint(2 ** 40 + 5)
    assert SN._fields(msg) == {1: b'Skater_2', 6: 1, 2: 2 ** 40 + 5}


class _Site(BaseHTTPRequestHandler):
    reply = (200, {'success': True})
    got = None

    def do_POST(self):
        _Site.got = (self.headers.get('Content-Type'), json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        code, body = _Site.reply
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def site():
    srv = HTTPServer(('127.0.0.1', 0), _Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{srv.server_address[1]}/scripts/register.php'
    srv.shutdown()
    srv.server_close()


def test_register_posts_the_site_form(site):
    _Site.reply = (200, {'success': True})
    assert SN.register('Skater_2', 's3cret', 'a@b.cd', url=site) is None
    assert _Site.got == ('application/json', {'npid': 'Skater_2', 'password': 's3cret', 'confirm': 's3cret',
                                              'email': 'a@b.cd', 'avatar': ''})
    _Site.reply = (400, {'success': False, 'error': 'Username already taken.'})
    with pytest.raises(SN.ShadNetError, match='already taken') as err:
        SN.register('Skater_2', 's3cret', 'a@b.cd', url=site)
    assert not isinstance(err.value, SN.ShadNetDown)
    _Site.reply = (502, b'<html>bad gateway</html>')
    with pytest.raises(SN.ShadNetDown):
        SN.register('Skater_2', 's3cret', 'a@b.cd', url=site)
