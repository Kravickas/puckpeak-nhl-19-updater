"""What a Linux PC or a Mac must have before the first Play (overtime_roster/app/preflight.py)."""
import subprocess

from overtime_roster.app import preflight

V3 = set('fpu sse sse2 avx avx2 bmi1 bmi2 fma movbe f16c abm xsave'.split())
GOOD = {'machine': lambda: 'x86_64', 'cpu_flags': lambda: V3, 'glibc': lambda: ('glibc', '2.39'),
        'vulkan_summary': lambda: 'GPU0:\n\tapiVersion         = 1.3.290\nGPU1:\n\tapiVersion = 1.2.0\n',
        'vulkan_drivers': lambda: ['/usr/share/vulkan/icd.d/radeon_icd.x86_64.json'], 'free': lambda: 50 << 30}
MAC = {'machine': lambda: 'arm64', 'mac_ver': lambda: '26.1', 'rosetta': lambda: True, 'free': lambda: 50 << 30}


def _by_key(rows):
    return {r['key']: r for r in rows}


def test_windows_has_no_rows():
    assert preflight.report('win32') == []


def test_a_steam_deck_like_pc_passes():
    rows = preflight.report('linux', GOOD)
    assert [r['key'] for r in rows] == ['cpu', 'system', 'vulkan', 'disk'] and all(r['ok'] for r in rows)
    assert preflight.worst(rows) is None
    assert _by_key(rows)['vulkan']['text'] == 'Vulkan 1.3.'           # the best device counts


def test_an_old_cpu_is_named_with_what_it_lacks():
    row = _by_key(preflight.report('linux', {**GOOD, 'cpu_flags': lambda: V3 - {'avx2', 'bmi2'}}))['cpu']
    assert row['ok'] is False and 'AVX2, BMI2' in row['text'] and '4th generation' in row['text']
    arm = _by_key(preflight.report('linux', {**GOOD, 'machine': lambda: 'aarch64'}))['cpu']
    assert arm['ok'] is False and 'aarch64' in arm['text']
    assert _by_key(preflight.report('linux', {**GOOD, 'cpu_flags': lambda: None}))['cpu']['ok'] is None


def test_an_older_linux_is_told_which_systems_work():
    row = _by_key(preflight.report('linux', {**GOOD, 'glibc': lambda: ('glibc', '2.35')}))['system']
    assert row['ok'] is False and 'glibc 2.35' in row['text'] and 'Ubuntu 24.04' in row['text']
    assert _by_key(preflight.report('linux', {**GOOD, 'glibc': lambda: ('glibc', '2.41')}))['system']['ok'] is True
    assert _by_key(preflight.report('linux', {**GOOD, 'glibc': lambda: ('', '')}))['system']['ok'] is None   # musl


def test_vulkan_from_the_tool_or_from_the_drivers_there():
    old = _by_key(preflight.report('linux', {**GOOD, 'vulkan_summary': lambda: 'apiVersion = 1.2.131'}))['vulkan']
    assert old['ok'] is False and 'Vulkan 1.2' in old['text'] and 'Update the graphics driver' in old['text']
    none = {**GOOD, 'vulkan_summary': lambda: None, 'vulkan_drivers': lambda: []}
    row = _by_key(preflight.report('linux', none))['vulkan']
    assert row['ok'] is False and 'No Vulkan graphics driver' in row['text']
    unknown = _by_key(preflight.report('linux', {**GOOD, 'vulkan_summary': lambda: None}))['vulkan']
    assert unknown['ok'] is None                      # a driver is there, no vulkaninfo: the game's start shows it
    assert preflight.vulkan_version('') is None and preflight.vulkan_version('apiVersion = 1.4.3') == (1, 4)


def test_a_full_disk_is_said_in_gigabytes():
    row = _by_key(preflight.report('linux', {**GOOD, 'free': lambda: 1 << 30}))['disk']
    assert row['ok'] is False and 'Only 1.0 GB free' in row['text']
    assert _by_key(preflight.report('linux', {**GOOD, 'free': lambda: None}))['disk']['ok'] is None


def test_a_mac_needs_macos_26_and_rosetta_on_an_apple_chip():
    rows = preflight.report('darwin', MAC)
    assert [r['key'] for r in rows] == ['system', 'rosetta', 'disk'] and all(r['ok'] for r in rows)
    old = _by_key(preflight.report('darwin', {**MAC, 'mac_ver': lambda: '15.6.1'}))['system']
    assert old['ok'] is False and 'macOS 15.6' in old['text'] and 'macOS 26' in old['text']
    bare = _by_key(preflight.report('darwin', {**MAC, 'rosetta': lambda: False}))['rosetta']
    assert bare['ok'] is False and bare['fix'] == 'install_rosetta'
    intel = preflight.report('darwin', {**MAC, 'machine': lambda: 'x86_64', 'rosetta': lambda: False})
    assert [r['key'] for r in intel] == ['system', 'disk']             # an Intel Mac needs no Rosetta
    assert _by_key(preflight.report('darwin', {**MAC, 'mac_ver': lambda: ''}))['system']['ok'] is None


def test_the_worst_row_and_the_report_lines():
    rows = preflight.report('linux', {**GOOD, 'glibc': lambda: ('glibc', '2.31'), 'vulkan_summary': lambda: None})
    assert preflight.worst(rows)['key'] == 'system'
    lines = preflight.summary(rows)
    assert lines[0].startswith('cpu: ok - ') and lines[1].startswith('system: MISSING - ')
    assert lines[2].startswith('vulkan: unknown - ')


def test_rosetta_is_installed_with_apples_own_command():
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)
    assert preflight.install_rosetta(run) is True and seen == [preflight.ROSETTA_COMMAND]

    def fails(cmd, **kw):
        raise OSError('no such tool')
    assert preflight.install_rosetta(fails) is False


def test_the_real_probes_answer_on_this_system():
    """Whatever the system: the rows come back and nothing raises."""
    for system in ('linux', 'darwin'):
        rows = preflight.report(system)
        assert rows and all(set(r) == {'key', 'ok', 'text', 'fix'} for r in rows)


def test_setups_line_says_what_the_computer_lacks_first(monkeypatch):
    from overtime_roster.app import setup_controller
    rows = preflight.report('linux', {**GOOD, 'glibc': lambda: ('glibc', '2.35')})
    monkeypatch.setattr(preflight, 'cached', lambda system=None: rows)
    line = setup_controller.SetupController._state(None, True, [], False)
    assert line['tone'] == 'bad' and 'glibc 2.35' in line['text'] and line['get'] is False
    monkeypatch.setattr(preflight, 'cached', lambda system=None: [])        # Windows: Setup's own first line
    assert 'Find game' in setup_controller.SetupController._state(None, True, [], False)['text']


def test_cached_looks_once(monkeypatch):
    calls = []
    monkeypatch.setattr(preflight, 'report', lambda system=None, probes=None: calls.append(system) or [])
    preflight.refresh()
    assert preflight.cached('linux') == [] and preflight.cached('linux') == [] and calls == ['linux']
    preflight.refresh()
    preflight.cached('linux')
    assert calls == ['linux', 'linux']
    preflight.refresh()
