"""The app update server with a release per system: latest.json's "linux" / "macos" keys pass through, the cross-play
switch file decides "crossplay", and the Linux and macOS files are served with their types
(overtime_server/http/appupdate.py; the app's side is tests/test_release_systems.py)."""
import http.client
import json

import pytest

from overtime_roster.app import crossplay, selfupdate

AppUpdateServer = pytest.importorskip('overtime_server.http.appupdate').AppUpdateServer   # not in the public copy

IMAGE = bytes([0x7F]) + b'ELF new app ' * 800
LIN, WIN = 'aa' * 32, 'bb' * 32
WINDOWS = {'version': '0.97.0', 'exe': 'OvertimeNHL19.exe', 'size': 14, 'sha256': 'cc' * 32, 'notes': 'Seattle',
           'page': 'https://ot.example/'}
OTHERS = {'linux': {'version': '0.97.1', 'exe': selfupdate.LINUX_ASSET, 'size': len(IMAGE), 'sha256': 'dd' * 32}}


@pytest.fixture
def srv(tmp_path):
    app = tmp_path / 'app'
    (app / 'packs').mkdir(parents=True)
    (app / 'latest.json').write_text(json.dumps({**WINDOWS, 'linux': OTHERS['linux'], 'crossplay': {LIN: WIN}}))
    s = AppUpdateServer(str(app)).serve('127.0.0.1', 0)
    s.dir = app
    yield s
    s.shutdown()
    s.server_close()


def get(s, path, method='GET'):
    conn = http.client.HTTPConnection('127.0.0.1', s.server_address[1], timeout=5)
    conn.request(method, path)
    r = conn.getresponse()
    out = r.read()
    conn.close()
    return r.status, r.getheader('Content-Type'), out


def test_the_server_serves_the_release_file_as_it_is_without_a_switch_file(srv):
    code, ctype, out = get(srv, '/app/latest.json')
    data = json.loads(out)
    assert code == 200 and data['linux'] == OTHERS['linux'] and data['crossplay'] == {LIN: WIN}
    assert data['version'] == '0.97.0'


def test_the_switch_file_decides_cross_play(srv, tmp_path, monkeypatch):
    (srv.dir / 'crossplay.json').write_text(json.dumps({LIN.upper(): WIN, 'short': WIN, WIN: WIN, 'ee' * 32: 7}))
    data = json.loads(get(srv, '/app/latest.json')[2])
    assert data['crossplay'] == {LIN: WIN} and data['linux'] == OTHERS['linux']       # only the well-formed pair
    (srv.dir / 'crossplay.json').write_text('{}')
    assert json.loads(get(srv, '/app/latest.json')[2])['crossplay'] == {}             # off, whatever the release says
    (srv.dir / 'crossplay.json').write_text('{broken')
    assert json.loads(get(srv, '/app/latest.json')[2])['crossplay'] == {}
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'home'))
    (srv.dir / 'crossplay.json').write_text(json.dumps({LIN: WIN}))
    crossplay.remember(json.loads(get(srv, '/app/latest.json')[2]).get('crossplay'))   # what the app does on a read
    assert crossplay.stands_for(LIN, 'linux') == WIN and crossplay.stands_for(LIN, 'win32') is None


def test_the_linux_and_macos_files_are_served_with_their_types(srv):
    for name, ctype in (('OvertimeNHL19-linux.tar.gz', 'application/gzip'),
                        (selfupdate.MACOS_ASSET, 'application/x-apple-diskimage'),
                        (selfupdate.LINUX_ASSET, 'application/octet-stream')):
        (srv.dir / name).write_bytes(IMAGE)
        code, got, out = get(srv, '/app/' + name)
        assert (code, got, out) == (200, ctype, IMAGE)
        assert get(srv, '/app/' + name, 'HEAD')[:2] == (200, ctype)
