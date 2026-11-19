"""The opt-in first-run report of a Linux PC or a Mac (overtime_roster/app/firstrun.py), up to the server's check."""
import gzip
import json

import pytest

from overtime_roster.app import crashreport, firstrun, preflight

SHA = 'ab' * 32
LOG = '\n'.join(['[Loader] shadPS4 starts', '[Render.Vulkan] GPU_Vendor: AMD', '[Render.Vulkan] Vulkan gpuId: 0',
                 '[Core] static pass: 4321 patches', '[Kernel] /home/deckard/.local/share/shadPS4', 'frame 1'])
ROWS = [{'key': 'cpu', 'ok': True, 'text': 'The CPU has what shadPS4 needs.', 'fix': None},
        {'key': 'vulkan', 'ok': None, 'text': 'A Vulkan driver is installed.', 'fix': None}]


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'home'))
    monkeypatch.setattr(crashreport, 'collect', lambda emu, game_dir, log_text='', **kw: {
        'app_version': '0.97.0', 'emu_sha256': SHA, 'cpu': 'AMD Custom APU 0405', 'gpu_id': 0})
    monkeypatch.setattr(crashreport, 'own_secrets', lambda emu: [])
    monkeypatch.setenv('HOME', '/home/deckard')
    monkeypatch.setenv('USERPROFILE', '/home/deckard')
    return tmp_path / 'home'


def sender(got, rid='abcdefghij'):
    def send(base, body):
        got.append((base, body))
        return rid
    return send


def test_windows_sends_none():
    assert firstrun.wanted(SHA, 'win32') is False
    assert firstrun.run('shadPS4.exe', 'game', LOG, 'https://x', system='win32', send=None) is None


def test_the_first_game_sends_one_report_the_server_takes(home):
    got = []
    rid = firstrun.run('/x/shadps4.AppImage', '/games/nhl19', LOG, 'https://srv', system='linux', send=sender(got),
                       rows=ROWS)
    assert rid == 'abcdefghij' and got[0][0] == 'https://srv'
    reports = pytest.importorskip('overtime_server.reports')       # the public copy has the app, not the server
    doc = reports.parse(got[0][1])                  # the server's own check of a report body
    assert doc['reason'] == 'first_run' and doc['meta']['system'] == 'linux' and doc['meta']['emu_sha256'] == SHA
    assert doc['meta']['pre_cpu'].startswith('ok - ') and doc['meta']['pre_vulkan'].startswith('unknown - ')
    assert 'static pass: 4321 patches' in doc['log'] and '/home/deckard' not in doc['log'] and '<home>' in doc['log']
    assert firstrun.state() == {SHA: 'abcdefghij'} and firstrun.wanted(SHA, 'linux') is False
    assert firstrun.run('/x/shadps4.AppImage', '/games/nhl19', LOG, 'https://srv', system='linux', send=None) is None


def test_only_the_first_lines_of_the_log_go(home):
    got = []
    long = '\n'.join(f'line {n}' for n in range(firstrun.HEAD + 500))
    firstrun.run('/x/shadps4', '/g', long, 'https://srv', system='darwin', send=sender(got), rows=[])
    lines = json.loads(gzip.decompress(got[0][1]))['log'].splitlines()
    assert len(lines) == firstrun.HEAD and lines[-1] == f'line {firstrun.HEAD - 1}'


def test_no_log_is_no_first_game(home):
    assert firstrun.run('/x/shadps4', '/g', 'one line', 'https://srv', system='linux', send=None, rows=ROWS) is None
    assert firstrun.state() == {} and firstrun.wanted(SHA, 'linux') is True


def test_a_refusing_server_is_tried_three_times(home):
    def refuse(base, body):
        raise crashreport.ReportError('The server did not take the report.')
    for n in range(firstrun.TRIES):
        with pytest.raises(crashreport.ReportError):
            firstrun.run('/x/shadps4', '/g', LOG, 'https://srv', system='linux', send=refuse, rows=ROWS)
        assert firstrun.state() == {SHA: n + 1}
    assert firstrun.wanted(SHA, 'linux') is False
    assert firstrun.run('/x/shadps4', '/g', LOG, 'https://srv', system='linux', send=refuse, rows=ROWS) is None


def test_an_unknown_build_or_a_broken_file_never_raises(home, monkeypatch):
    home.mkdir(parents=True, exist_ok=True)
    (home / firstrun.FILE).write_text('[not a map')
    assert firstrun.state() == {} and firstrun.wanted('?', 'linux') is False and firstrun.wanted('', 'linux') is False
    assert firstrun.meta(preflight.report('linux', {'machine': lambda: 'aarch64'}), 'linux')['pre_cpu'].startswith(
        'MISSING - ')
