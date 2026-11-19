"""What this computer must have for NHL 19 to start, looked at before the first Play on Linux and macOS
(docs/plans/proud-shimmying-kettle.md "it just works": the app says what is missing in words, the player never reads a
terminal). Windows has no rows here: its checks are Setup's tiles.

Each row: {'key', 'ok': True | False | None (could not tell), 'text', 'fix': an action's name or None}. Facts behind
the limits (docs/notes/linux-support.md, macos-support.md):
  - shadPS4 is built for x86-64-v3 (CMakeLists.txt): a CPU with AVX2, BMI1/2, FMA, MOVBE, F16C and LZCNT;
  - it asks Vulkan for version 1.3 (renderer_vulkan, TargetVulkanApiVersion);
  - the fork's Linux build is made on Ubuntu 24.04, so it needs glibc 2.39 or newer (a Steam Deck on SteamOS 3.6 and
    Ubuntu 24.04 have it; Ubuntu 22.04 has 2.35);
  - the macOS build is x86_64 for macOS 26 (CMAKE_OSX_DEPLOYMENT_TARGET): an Apple-chip Mac runs it through Rosetta.
Standard library only; every look at the system can be replaced (`probes`) so the rows are tested on any system.
"""
import glob
import os
import platform
import re
import shutil
import subprocess
import sys

from . import paths, selfupdate

V3_FLAGS = ('avx', 'avx2', 'bmi1', 'bmi2', 'fma', 'movbe', 'f16c', 'abm')      # /proc/cpuinfo's names (abm: LZCNT)
GLIBC_FLOOR = (2, 39)
MACOS_FLOOR = 26
VULKAN_FLOOR = (1, 3)
DISK_FLOOR = 3 << 30        # the emulator, the picture packs and the files Patch makes
ICD_DIRS = ('/usr/share/vulkan/icd.d', '/etc/vulkan/icd.d', '/usr/local/share/vulkan/icd.d',
            '~/.local/share/vulkan/icd.d', '/run/host/usr/share/vulkan/icd.d')
ROSETTA = '/Library/Apple/usr/libexec/oah/libRosettaRuntime'
ROSETTA_COMMAND = ['softwareupdate', '--install-rosetta', '--agree-to-license']


def _row(key, ok, text, fix=None):
    return {'key': key, 'ok': ok, 'text': text, 'fix': fix}


def _version(text):
    """(2, 39) from '2.39', (1, 3) from '1.3.290'; None when there is no number."""
    m = re.search(r'(\d+)\.(\d+)', text or '')
    return (int(m.group(1)), int(m.group(2))) if m else None


# --- the looks at the system (each one replaceable) -----------------------------------------------------------------
def _cpu_flags():
    try:
        with open('/proc/cpuinfo', encoding='utf-8', errors='replace') as f:
            line = next((ln for ln in f if ln.startswith('flags')), '')
    except OSError:
        return None
    return set(line.partition(':')[2].split()) or None


def _vulkan_summary(run=subprocess.run):
    """vulkaninfo's summary text, or None when the tool is not installed (most systems) or says nothing."""
    try:
        out = run(['vulkaninfo', '--summary'], capture_output=True, text=True, timeout=20,
                  env=selfupdate.clean_environment()).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return out or None


def _vulkan_drivers():
    found = []
    for folder in ICD_DIRS:
        found += glob.glob(os.path.join(os.path.expanduser(folder), '*.json'))
    return found


def _free(folder):
    try:
        return shutil.disk_usage(folder).free
    except OSError:
        return None


PROBES = {
    'machine': platform.machine,
    'cpu_flags': _cpu_flags,
    'glibc': lambda: platform.libc_ver(),
    'vulkan_summary': _vulkan_summary,
    'vulkan_drivers': _vulkan_drivers,
    'free': lambda: _free(paths.app_home()),
    'mac_ver': lambda: platform.mac_ver()[0],
    'rosetta': lambda: os.path.exists(ROSETTA),
}


# --- the rows ---------------------------------------------------------------------------------------------------------
def _disk(free):
    if free is None:
        return _row('disk', None, 'Free disk space could not be read.')
    gb = free / (1 << 30)
    if free < DISK_FLOOR:
        return _row('disk', False, f'Only {gb:.1f} GB free where Overtime keeps its files; it needs about '
                                   f'{DISK_FLOOR >> 30} GB. Free some space.')
    return _row('disk', True, f'{gb:.0f} GB free.')


def _cpu(machine, flags):
    if machine.lower() not in ('x86_64', 'amd64'):
        return _row('cpu', False, f'This computer has a {machine or "unknown"} CPU. NHL 19 on shadPS4 needs a 64-bit '
                                  'Intel or AMD one.')
    if flags is None:
        return _row('cpu', None, 'The CPU could not be read.')
    missing = [f for f in V3_FLAGS if f not in flags]
    if missing:
        return _row('cpu', False, 'This CPU is too old for shadPS4: it lacks ' + ', '.join(m.upper() for m in missing)
                    + '. It needs an Intel Core of the 4th generation (2013) or newer, or an AMD Ryzen.')
    return _row('cpu', True, 'The CPU has what shadPS4 needs.')


def _glibc(libc):
    name, version = (libc or ('', ''))[:2]
    have = _version(version)
    floor = '.'.join(map(str, GLIBC_FLOOR))
    if name != 'glibc' or have is None:
        return _row('system', None, f'The system library could not be read (shadPS4 needs glibc {floor} or newer).')
    if have < GLIBC_FLOOR:
        return _row('system', False, f'This Linux is too old for the Overtime build of shadPS4: it has glibc '
                                     f'{version}, the build needs {floor} (Ubuntu 24.04, Fedora 40, SteamOS 3.6 or '
                                     'newer). Update the system.')
    return _row('system', True, f'glibc {version}.')


def vulkan_version(summary):
    """The highest Vulkan version a graphics device offers in vulkaninfo's summary, or None."""
    found = [_version(m) for m in re.findall(r'apiVersion\s*=\s*([\d.]+)', summary or '')]
    found = [v for v in found if v]
    return max(found) if found else None


def _vulkan(summary, drivers):
    floor = '.'.join(map(str, VULKAN_FLOOR))
    have = vulkan_version(summary)
    if have is not None:
        if have < VULKAN_FLOOR:
            return _row('vulkan', False, f'The graphics driver offers Vulkan {have[0]}.{have[1]}; shadPS4 needs '
                                         f'{floor}. Update the graphics driver (Mesa 23 or newer, or the current '
                                         'NVIDIA driver).')
        return _row('vulkan', True, f'Vulkan {have[0]}.{have[1]}.')
    if not drivers:
        return _row('vulkan', False, 'No Vulkan graphics driver was found. Install your graphics card\'s Vulkan '
                                     'driver (mesa-vulkan-drivers, or the NVIDIA driver), then start Overtime again.')
    return _row('vulkan', None, f'A Vulkan driver is installed; whether it offers Vulkan {floor} shows when the '
                                'game starts.')


def linux(probes=None):
    p = {**PROBES, **(probes or {})}
    return [_cpu(p['machine'](), p['cpu_flags']()), _glibc(p['glibc']()),
            _vulkan(p['vulkan_summary'](), p['vulkan_drivers']()), _disk(p['free']())]


def macos(probes=None):
    p = {**PROBES, **(probes or {})}
    rows = []
    have = _version((p['mac_ver']() or '') + '.0')
    if have is None:
        rows.append(_row('system', None, f'The macOS version could not be read (shadPS4 needs macOS {MACOS_FLOOR}).'))
    elif have[0] < MACOS_FLOOR:
        rows.append(_row('system', False, f'This Mac has macOS {have[0]}.{have[1]}; the Overtime build of shadPS4 '
                                          f'needs macOS {MACOS_FLOOR} or newer. Update macOS.'))
    else:
        rows.append(_row('system', True, f'macOS {have[0]}.{have[1]}.'))
    if p['machine']().lower() in ('arm64', 'aarch64'):
        if p['rosetta']():
            rows.append(_row('rosetta', True, 'Rosetta is installed.'))
        else:
            rows.append(_row('rosetta', False, 'shadPS4 is an Intel program and this Mac has an Apple chip: it needs '
                                               'Rosetta, which is not installed yet.', 'install_rosetta'))
    rows.append(_disk(p['free']()))
    return rows


def report(system=None, probes=None):
    """The rows for this system: [] on Windows."""
    system = system or sys.platform
    if system == 'win32':
        return []
    return macos(probes) if system == 'darwin' else linux(probes)


_ROWS = {}


def cached(system=None):
    """report() of this system, looked at once per run (refresh() looks again)."""
    system = system or sys.platform
    if system not in _ROWS:
        _ROWS[system] = report(system)
    return _ROWS[system]


def refresh():
    _ROWS.clear()


def worst(rows):
    """The first row that stops the game (ok False), or None."""
    return next((r for r in rows if r['ok'] is False), None)


def summary(rows):
    """What to send with a first-run report: one line per row."""
    mark = {True: 'ok', False: 'MISSING', None: 'unknown'}
    return [f"{r['key']}: {mark[r['ok']]} - {r['text']}" for r in rows]


def install_rosetta(run=subprocess.run):
    """Apple's own installer for Rosetta (a few seconds, no restart). True when it reports done."""
    try:
        return run(ROSETTA_COMMAND, capture_output=True, text=True, timeout=600).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
