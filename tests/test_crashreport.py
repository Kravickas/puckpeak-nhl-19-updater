"""Opt-in crash and early-end reports, the app side (overtime_roster/app/crashreport.py, docs/notes/reports.md): the
scrubber, the log cap, the body's shape against the server's contract, the HTTP calls against a local server, and
what counts as a crash."""
import gzip
import http.server
import json
import threading

import pytest

from overtime_roster.app import crashreport as CR


# --- scrubbing -----------------------------------------------------------------------------------------------------

@pytest.fixture
def pc(monkeypatch):
    monkeypatch.setenv('USERPROFILE', 'C:\\Users\\jdoe')
    monkeypatch.setenv('USERNAME', 'jdoe')
    monkeypatch.setenv('COMPUTERNAME', 'GAMING-PC')


@pytest.mark.parametrize('text, want', [
    ('C:\\Users\\jdoe\\AppData\\Roaming\\shadPS4\\log', '<home>\\AppData\\Roaming\\shadPS4\\log'),
    ('c:/users/JDOE/Documents/x.json', '<home>/Documents/x.json'),
    ('C:\\\\Users\\\\jdoe\\\\log', '<home>\\\\log'),
    ('user jdoe signed in', 'user <user> signed in'),
    ('host GAMING-PC ready', 'host <pc> ready'),
    ('connect 91.98.195.150:17502', 'connect <ip>:17502'),
    ('loopback 127.0.0.1', 'loopback <ip>'),
    ('addr 2001:db8::1 ok', 'addr <ip> ok'),
    ('link fe80::1 up', 'link <ip> up'),
    ('mail matus.riedl+x@example.com now', 'mail <email> now'),
])
def test_scrub_takes_out_the_players_own_details(pc, text, want):
    assert CR.scrub(text) == want


@pytest.mark.parametrize('text', [
    '0x56ea4b0 and 0x809a91a5',
    'NHL19_1.60-spike1 and 0.81.0 and 1.60',
    'at 19:11:44 and 12:34:56.789',
    'Foo::Bar and std::string',
    'Applied patch: Cross-vendor exact math, Offset: 0x1d61423',
])
def test_scrub_leaves_hex_versions_and_times_alone(pc, text):
    assert CR.scrub(text) == text


def test_scrub_skips_very_short_names(monkeypatch):
    monkeypatch.setenv('USERPROFILE', 'C:\\Users\\ab')
    monkeypatch.setenv('USERNAME', 'ab')
    monkeypatch.setenv('COMPUTERNAME', 'PC')
    assert CR.scrub('ab on PC') == 'ab on PC'


def test_scrub_of_empty_text_is_empty():
    assert CR.scrub('') == ''
    assert CR.scrub(None) == ''


def test_scrub_takes_out_the_shadnet_details_it_is_given(pc):
    extra = [('Skater_99', '<npid>'), ('hunter2!', '<secret>'), ('tok123', '<secret>')]
    text = "signed in npid='skater_99' pw=hunter2! token tok123 and Skater_990"
    assert CR.scrub(text, extra) == "signed in npid='<npid>' pw=<secret> token <secret> and Skater_990"


def test_scrub_skips_too_short_extras(pc):
    assert CR.scrub('pw abc id ab', [('abc', '<secret>'), ('ab', '<npid>')]) == 'pw abc id ab'


def test_the_body_scrubs_the_shadnet_details_in_the_log_and_the_meta(pc):
    extra = [('skater', '<npid>'), ('hunter22', '<secret>')]
    doc = json.loads(gzip.decompress(CR.build('crash', "npid='skater' pass hunter22\n", {'note': 'skater'}, extra)))
    assert doc['log'] == "npid='<npid>' pass <secret>\n" and doc['meta']['note'] == '<npid>'


def test_own_secrets_reads_every_users_shadnet_details(tmp_path, monkeypatch):
    users = {'Users': {'user': [
        {'user_name': 'shadPS4', 'shadnet_npid': 'skater', 'shadnet_email': 'a@b.cd', 'shadnet_password': 'hunter2',
         'shadnet_token': ''},
        {'user_name': 'Matus', 'shadnet_npid': '', 'shadnet_password': ''}, 'junk']}}
    (tmp_path / 'users.json').write_text(json.dumps(users), encoding='utf-8')
    monkeypatch.setattr(CR.gamesetup, 'emu_user_dir', lambda emu: str(tmp_path))
    assert CR.own_secrets('shadPS4.exe') == [('skater', '<npid>'), ('a@b.cd', '<email>'), ('hunter2', '<secret>'),
                                             ('Matus', '<name>')]


def test_own_secrets_never_raises(monkeypatch):
    def boom(emu):
        raise OSError('no folder')
    monkeypatch.setattr(CR.gamesetup, 'emu_user_dir', boom)
    assert CR.own_secrets('shadPS4.exe') == [] and CR.own_secrets(None) == []


# --- the log cap ---------------------------------------------------------------------------------------------------

def test_cap_keeps_the_first_and_the_last_lines_with_a_marker():
    text = ''.join(f'line {i}\n' for i in range(25000))
    out = CR.cap_log(text).splitlines()
    assert out[0] == 'line 0' and out[CR.HEAD_LINES - 1] == f'line {CR.HEAD_LINES - 1}'
    assert out[CR.HEAD_LINES] == '--- 2000 lines left out (the log had 25000) ---'
    assert out[-1] == 'line 24999' and len(out) == CR.HEAD_LINES + 1 + CR.TAIL_LINES


def test_a_short_log_is_kept_whole():
    assert CR.cap_log('a\nb\n') == 'a\nb\n'


def test_the_body_stays_under_two_mebibytes(pc):
    # 23,000 lines of random hex do not compress: the tail has to shrink to fit the limit
    import os
    text = '\n'.join(os.urandom(150).hex() for _ in range(23000))
    body = CR.build('crash', text, {})
    assert len(body) <= CR.MAX_BODY
    doc = json.loads(gzip.decompress(body))
    assert 'lines left out' in doc['log']


# --- the body against the contract ---------------------------------------------------------------------------------

def test_the_body_is_gzip_of_the_v1_json_the_server_checks(pc, monkeypatch):
    monkeypatch.setenv('USERPROFILE', 'C:\\Users\\jdoe')
    log = 'start\nC:\\Users\\jdoe\\AppData\\shadPS4\\log\nend\n'
    meta = {'cpu': 'Intel-Core-i5', 'ext': 16349, 'amd_math': False, 'dmem': None, 'ratio': 1.5, 'list': [1],
            'x' * 41: 'key too long', 'emu_sha256': 'ab' * 32}
    body = CR.build('early_end', log, meta)
    assert body[:2] == b'\x1f\x8b'
    doc = json.loads(gzip.decompress(body).decode('utf-8'))
    assert doc['v'] == 1 and type(doc['v']) is int
    assert doc['reason'] == 'early_end'
    assert '<home>' in doc['log'] and 'C:\\Users' not in doc['log']
    m = doc['meta']
    assert len(m) <= CR.META_KEYS and all(len(k) <= CR.META_KEY for k in m)
    assert 'x' * 40 in m and 'x' * 41 not in m               # the key is cut to 40 chars, its value kept
    assert m['ratio'] == '1.5' and isinstance(m['ratio'], str)
    assert m['list'] == '[1]' and isinstance(m['list'], str)
    assert m['ext'] == 16349 and type(m['ext']) is int
    assert m['amd_math'] is False and type(m['amd_math']) is bool
    assert m['dmem'] is None
    assert all(type(v) in (str, int, bool, type(None)) for v in m.values())


def test_meta_strings_are_scrubbed_and_cut(pc):
    body = CR.build('manual', '', {'cpu': 'user jdoe ' + 'x' * 500})
    value = json.loads(gzip.decompress(body))['meta']['cpu']
    assert value.startswith('user <user> ') and len(value) <= CR.META_TEXT


def test_the_reason_must_be_a_known_one(pc):
    with pytest.raises(ValueError):
        CR.build('because', '', {})


def test_collect_gives_typed_values_and_reads_the_log_gpu(pc):
    meta = CR.collect(None, None, 'Run: Vulkan gpuId: 2\n', ext=16349, match=7)
    assert meta['ext'] == 16349 and meta['match'] == 7 and meta['gpu_id'] == 2
    assert meta['app_version'] and meta['emu_sha256'] == '?'
    assert all(type(v) in (str, int, bool, type(None)) for v in meta.values())


# --- what counts as a crash ----------------------------------------------------------------------------------------

@pytest.mark.parametrize('text, code, want', [
    ('', None, False),
    ('all fine\n', None, False),
    ('all fine\n', 0, False),
    ('all fine\n', 3221225477, True),           # 0xC0000005 as the exit code
    ('SignalHandler: Unhandled Exception code 0xc0000005 at 0x809a91a5', None, True),
    ('[Lib] <Critical> (SimThread) semaphore.h:51 release: Assertion Failed!', None, True),
])
def test_a_crash_is_an_abnormal_exit_or_a_crash_line(text, code, want):
    assert CR.crashed(text, code) is want


# --- the server, against a local HTTP server -----------------------------------------------------------------------

class Server:
    """A local stand-in for POST /app/report and GET /app/report/wanted: `reply` is (status, body dict, headers)."""

    def __init__(self):
        self.posts, self.gets = [], []
        self.reply = (200, {'id': 'abcdefghij'}, {})
        self.wanted = {'wanted': False, 'match': None}
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, doc, headers):
                raw = json.dumps(doc).encode()
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                n = int(self.headers.get('Content-Length') or 0)
                outer.posts.append((self.path, self.headers.get('Content-Type'), self.rfile.read(n)))
                status, doc, headers = outer.reply
                self._send(status, doc, headers)

            def do_GET(self):
                outer.gets.append(self.path)
                self._send(200, outer.wanted, {})

        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.base = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = Server()
    yield s
    s.close()


BODY = b'\x1f\x8b' + b'0' * 20


def test_send_posts_the_body_as_gzip_and_returns_the_id(server):
    assert CR.send(server.base, BODY) == 'abcdefghij'
    path, ctype, body = server.posts[0]
    assert path == '/app/report' and ctype == 'application/gzip' and body == BODY


@pytest.mark.parametrize('status, headers, text', [
    (413, {}, 'too big'),
    (429, {'Retry-After': '1800'}, 'Too many reports'),
    (404, {}, 'does not take reports yet'),
    (400, {}, 'refused'),
    (500, {}, 'error 500'),
])
def test_send_refusals_say_why_in_plain_words(server, status, headers, text):
    server.reply = (status, {'error': 'x'}, headers)
    with pytest.raises(CR.ReportError) as err:
        CR.send(server.base, BODY)
    assert text in str(err.value)


def test_a_rate_limit_says_when_to_try_again(server):
    server.reply = (429, {'error': 'slow down'}, {'Retry-After': '1800'})
    with pytest.raises(CR.ReportError, match='Try again in 30 minutes'):
        CR.send(server.base, BODY)


def test_a_server_that_does_not_answer_is_a_report_error():
    with pytest.raises(CR.ReportError, match='Could not reach'):
        CR.send('http://127.0.0.1:1', BODY, timeout=2)


def test_an_answer_without_an_id_is_refused(server):
    server.reply = (200, {'ok': True}, {})
    with pytest.raises(CR.ReportError, match='did not confirm'):
        CR.send(server.base, BODY)


def test_wanted_reads_the_servers_answer(server):
    server.wanted = {'wanted': True, 'match': 16}
    assert CR.wanted(server.base, 16349) == (True, 16)
    assert server.gets == ['/app/report/wanted?ext=16349']


def test_wanted_without_a_match_is_true_and_none(server):
    server.wanted = {'wanted': True, 'match': None}
    assert CR.wanted(server.base, 16349) == (True, None)


def test_wanted_is_false_when_the_server_says_no(server):
    assert CR.wanted(server.base, 16349) == (False, None)


@pytest.mark.parametrize('base, ext', [('http://127.0.0.1:1', 16349), ('http://127.0.0.1:1', 'abc')])
def test_wanted_never_raises(base, ext):
    assert CR.wanted(base, ext, timeout=2) == (False, None)
