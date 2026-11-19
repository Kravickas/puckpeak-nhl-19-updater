"""Is a newer OvertimeNHL19.exe out? Read the release file on the Overtime server; if it is newer, swap the exe for
it. Standard library only (certifi when the exe carries it). Nothing here touches the game, a roster or a save.

The release is two files next to each other on the server (or wherever OVERTIME_RELEASE_URL points):
  latest.json      {"version": "0.2.0", "exe": "OvertimeNHL19.exe", "size": 14020379, "notes": "...", "page": "..."}
                   ("exe" may be a full URL; relative names are taken next to latest.json; "sha256", "size", "sums"
                   and "cli" (the console exe's name) are optional)
  SHA256SUMS.txt   "<sha256>  OvertimeNHL19.exe" lines, written by packaging/build.ps1

Each exe updates only from its own file: OvertimeNHL19-cli.exe from OvertimeNHL19-cli.exe, never from the window exe.

The Linux and macOS apps have their own release inside latest.json, so they can come out later than the Windows exe:
  "linux": {"version": "0.97.0", "exe": "OvertimeNHL19-x86_64.AppImage", "sha256": "...", "size": 1, "page": "..."}
  "macos": {"version": "0.97.0", "exe": "OvertimeNHL19-macos.dmg", ...}
("notes" and "page" fall back to the ones above them.) A Windows app never reads those keys, and a Linux or macOS app
never reads the Windows ones: with no key for its system there is no release for it.

The Windows exe and the Linux AppImage replace themselves, never while shadPS4 runs. The macOS app and a run from
source are told that a new version exists."""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from overtime_core import durable, net

from .. import VERSION
from . import paths

RELEASE_URL = 'https://ot.puckpeak.com/app/latest.json'
EXE_ASSET = 'OvertimeNHL19.exe'
CLI_ASSET = 'OvertimeNHL19-cli.exe'
LINUX_ASSET = 'OvertimeNHL19-x86_64.AppImage'       # the file the running AppImage swaps itself for
MACOS_ASSET = 'OvertimeNHL19-macos.dmg'             # opened by the player: the app tells, it does not swap
SYSTEM_KEYS = {'linux': 'linux', 'darwin': 'macos'}   # sys.platform -> that system's release inside latest.json
SYSTEM_ASSETS = {'linux': LINUX_ASSET, 'darwin': MACOS_ASSET}
APPIMAGE_ENV = ('APPIMAGE', 'APPDIR', 'ARGV0', 'OWD')     # what an AppImage's runtime sets for the program inside
MAX_BYTES = 512 << 20               # a download larger than this is not an exe of ours (when latest.json gives no size)
SUMS_ASSET = 'SHA256SUMS.txt'
STATE_FILE = 'selfupdate.json'      # its own file: the controller rewrites settings.json whole
CHECK_EVERY = 12 * 3600             # seconds between two looks
CHUNK = 256 * 1024
AGENT = f'Mozilla/5.0 (OvertimeNHL19 {VERSION})'


def release_url():
    """The latest.json to read: OVERTIME_RELEASE_URL (a test, a fork, a local fixture) or the Overtime server."""
    return os.environ.get('OVERTIME_RELEASE_URL') or RELEASE_URL


class Release:
    def __init__(self, version, notes='', page='', exe_url=None, size=0, digest=None, asset=EXE_ASSET):
        self.version, self.notes, self.page = version, notes, page
        self.exe_url, self.size, self.digest, self.asset = exe_url, size, digest, asset

    @property
    def text(self):
        return str(Version._of(self.version))

    def can_install(self):
        return bool(self.exe_url and self.digest)


_STAGES = {'a': 0, 'alpha': 0, 'b': 1, 'beta': 1, 'rc': 2}


class Version(tuple):
    """(major, minor, patch); a pre-release ('0.1.0-beta1') keeps its tag in `pre` and sorts before its release, so
    the release self-updates over it."""
    pre = None          # (stage, number, tag) of a pre-release

    def _key(self):
        return tuple(self), ((0,) + self.pre[:2] if self.pre else (1, 0))

    @staticmethod
    def _of(other):
        return other if isinstance(other, Version) else Version(other)

    def __eq__(self, other):
        return isinstance(other, tuple) and self._key() == self._of(other)._key()

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(self._key())

    def __lt__(self, other):
        return self._key() < self._of(other)._key()

    def __le__(self, other):
        return self._key() <= self._of(other)._key()

    def __gt__(self, other):
        return self._key() > self._of(other)._key()

    def __ge__(self, other):
        return self._key() >= self._of(other)._key()

    def __str__(self):
        return '.'.join(str(n) for n in self) + (f'-{self.pre[2]}' if self.pre else '')


def parse_version(text):
    """'v0.11.0' or '0.11' -> (0, 11, 0); '0.1.0-beta1' -> (0, 1, 0) with pre-release beta 1, before 0.1.0; None when
    it is not a version."""
    m = re.match(r'^\s*v?(\d+)\.(\d+)(?:\.(\d+))?(?:-?(alpha|beta|rc|a|b)\.?(\d*))?\s*$',
                 text if isinstance(text, str) else '', re.IGNORECASE)
    if not m:
        return None
    version = Version((int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)))
    if m.group(4):
        stage, number = m.group(4).lower(), int(m.group(5) or 0)
        version.pre = (_STAGES[stage], number, f'{stage}{m.group(5)}')
    return version


def digest_from_sums(text, name):
    for line in (text or '').splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip('*') == name and re.fullmatch(r'[0-9a-fA-F]{64}', parts[0]):
            return parts[0].lower()
    return None


def asset_for(exe, system=None):
    """Which release file replaces `exe`: the console exe (...-cli.exe) has its own, Linux and macOS have theirs."""
    system = system or sys.platform
    if system in SYSTEM_ASSETS:
        return SYSTEM_ASSETS[system]
    stem = os.path.splitext(os.path.basename(exe or ''))[0].lower()
    return CLI_ASSET if stem.endswith('-cli') else EXE_ASSET


def from_json(data, base, fetch_text=None, asset=EXE_ASSET):
    """A Release of `asset` from latest.json (read at `base`); None for nonsense, and for a Linux or macOS file when
    latest.json has no release for that system. The exe's sha256 comes from SHA256SUMS.txt; when latest.json names
    one too, both must agree, else the release cannot be installed."""
    if not isinstance(data, dict):
        return None
    system = next((s for s, a in SYSTEM_ASSETS.items() if a == asset), None)
    if system:
        own = data.get(SYSTEM_KEYS[system])
        if not isinstance(own, dict):
            return None
        data = {'notes': data.get('notes'), 'page': data.get('page'), 'sums': data.get('sums'),
                **{k: v for k, v in own.items() if v is not None}}
    version = parse_version(data.get('version'))
    if version is None:
        return None
    main = asset == EXE_ASSET or bool(system)        # "exe", "sha256" and "size" describe this file
    name = (data.get('exe') if main else data.get('cli')) or asset
    exe_url = urllib.parse.urljoin(base, name) if isinstance(name, str) else None
    digest = None
    if fetch_text:
        try:
            sums = fetch_text(urllib.parse.urljoin(base, data.get('sums') or SUMS_ASSET))
            digest = digest_from_sums(sums, os.path.basename(urllib.parse.urlparse(exe_url or '').path))
        except Exception:
            digest = None
    named = data.get('sha256') if main else None      # "sha256" and "size" describe the window exe
    if digest and isinstance(named, str) and named.lower() != digest:
        digest = None
    try:
        size = int(data.get('size') or 0) if main else 0
    except (TypeError, ValueError):
        size = 0
    return Release(version, str(data.get('notes') or '').strip(), str(data.get('page') or ''), exe_url, size, digest,
                   asset)


def tls_context():
    """Windows' trusted certificates, plus Mozilla's list when certifi is there (a PC can lack the root a site uses)."""
    return net.tls_context()


def _open(url, timeout):
    req = urllib.request.Request(url, headers={'User-Agent': AGENT, 'Cache-Control': 'no-cache'})
    return urllib.request.urlopen(req, timeout=timeout, context=tls_context() if url.startswith('https:') else None)


def http_text(url, timeout=20):
    with _open(url, timeout) as r:
        return r.read(4 << 20).decode('utf-8', 'replace')


def latest(current=VERSION, url=None, fetch_text=None, asset=None):
    """The newest release when it is newer than `current`, else None (also when the server cannot be reached).
    `asset`: the file to take (default: the one for the running exe)."""
    url = url or release_url()
    fetch_text = fetch_text or http_text
    asset = asset or asset_for(running_exe())
    try:
        release = from_json(json.loads(fetch_text(url)), url, fetch_text, asset)
    except Exception:           # offline, not published yet, a broken file: say nothing
        return None
    have = parse_version(current)
    return release if release and have and release.version > have else None


# --- when to look -----------------------------------------------------------------------------------
def _state():
    try:
        with open(paths.app_dir(STATE_FILE), encoding='utf-8') as f:
            value = json.load(f)
            return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def due(now=None, state=None, first=False):
    """Time to look again? Not when switched off in selfupdate.json; else at every start (`first`) and, while the app
    stays open, every 12 hours."""
    state = _state() if state is None else state
    if state.get('check_updates', True) is False:
        return False
    if first:
        return True
    try:
        last = float(state.get('checked') or 0)
    except (TypeError, ValueError):
        last = 0.0
    return (now if now is not None else time.time()) - last >= CHECK_EVERY


def _write_state(state):
    path = paths.app_dir(STATE_FILE)
    try:
        with open(path + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=1)
        durable.replace(path + '.tmp', path)
    except OSError:
        pass


def mark_checked(now=None):
    state = _state()
    state['checked'] = now if now is not None else time.time()
    _write_state(state)


def set_check_updates(on):
    """Setup's "Check for updates at start": off stops the looks (due() says False) until it is on again."""
    state = _state()
    state['check_updates'] = bool(on)
    _write_state(state)


# --- replacing the exe ------------------------------------------------------------------------------
def running_exe():
    """The path of the program file that runs and can be swapped: the Windows exe, or the Linux AppImage (its
    runtime gives its path in APPIMAGE). None for a run from source, the macOS app (a bundle, replaced by the player
    from the .dmg) and a Linux app unpacked out of its AppImage."""
    if not getattr(sys, 'frozen', False):
        return None
    if os.name == 'nt':
        return os.path.abspath(sys.executable)
    image = os.environ.get('APPIMAGE') if sys.platform == 'linux' else None
    return os.path.abspath(image) if image and os.path.isfile(image) else None


def emulator_running():
    from overtime_core import overlay
    return overlay.emulator_running()


def can_replace(exe):
    if not exe or not os.path.isfile(exe):
        return False
    probe = os.path.join(os.path.dirname(exe), '.overtime-write-test')
    try:
        with open(probe, 'wb'):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False


def clean_leftovers(exe=None):
    """Remove the old exe and a half-finished download left by an earlier update."""
    exe = exe or running_exe()
    if not exe:
        return
    for suffix in ('.old', '.new'):
        try:
            os.remove(exe + suffix)
        except OSError:
            pass


def download(release, target, progress=None):
    """Download the release's exe to `target`; delete it and raise ValueError if it is not the file that was published
    (wrong sha256, or a size other than latest.json's; nothing larger than that size, or MAX_BYTES, is written)."""
    sha = hashlib.sha256()
    got = 0
    wrong = ValueError('The downloaded file is not the one that was published, so it was not used.')
    limit = release.size or MAX_BYTES
    try:
        with _open(release.exe_url, 60) as r, open(target, 'wb') as out:
            try:
                announced = int(r.headers.get('Content-Length') or 0)
            except ValueError:
                announced = 0
            if announced and (announced > limit or (release.size and announced != release.size)):
                raise wrong
            total = announced or release.size
            while True:
                block = r.read(CHUNK)
                if not block:
                    break
                if got + len(block) > limit:
                    raise wrong
                out.write(block)
                sha.update(block)
                got += len(block)
                if progress and total:
                    progress(min(1.0, got / total))
        if sha.hexdigest() != release.digest or (release.size and got != release.size):
            raise wrong
    except BaseException:
        try:
            os.remove(target)
        except OSError:
            pass
        raise


def signer(path):
    """The publisher (certificate subject) of a validly signed Windows program, or None when it is unsigned, the
    signature is not valid, or this is not Windows. Authenticode as Windows judges it (Get-AuthenticodeSignature)."""
    if os.name != 'nt' or not os.path.isfile(path):
        return None
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $env:OVERTIME_SIGNED_PATH; "
              "if ($s.Status -eq 'Valid') { [Console]::Out.Write($s.SignerCertificate.Subject) }")
    try:
        out = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                             env={**os.environ, 'OVERTIME_SIGNED_PATH': path}, capture_output=True, text=True, timeout=60, check=False,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def check_signature(new_path, exe, who=None):
    """A signed running exe only takes an update with a valid signature of the same publisher: a changed file on the
    release host (or a swapped download) cannot pass as ours. An unsigned running exe (a source run, a release made
    before signing) has nothing to compare: its sha256 from latest.json is the check. Raises ValueError."""
    who = who or signer
    mine = who(exe)
    if mine is None:
        return
    theirs = who(new_path)
    if theirs != mine:
        raise ValueError('The downloaded program is not signed by the same publisher as this one, so it was not used.')


def swap(new_path, exe):
    """Put the downloaded exe in place of the running one (Windows lets a running exe be renamed)."""
    old = exe + '.old'
    try:
        os.remove(old)
    except OSError:
        pass
    durable.flush(new_path)     # the new exe whole on the disk before the old one gives up its name
    if os.name != 'nt':
        os.chmod(new_path, 0o755)   # a download has no exec bit; Linux lets a running file be renamed too
    os.replace(exe, old)
    try:
        os.replace(new_path, exe)
    except OSError:
        os.replace(old, exe)        # put the working one back
        raise


def clean_environment():
    """The environment for a program started from the exe (a new exe, shadPS4): a fresh PyInstaller start, without this
    one's unpacked folder on PATH, or the program loads our copies of its DLLs and stops ("vcruntime140.dll incorrectly
    installed" in Legacy). On Linux the frozen app runs with LD_LIBRARY_PATH on its own folder, so a child would load
    our libraries (our libstdc++, our Qt) in place of the system's: the value from before the start
    (LD_LIBRARY_PATH_ORIG, kept by PyInstaller) goes back, or the variable goes away. Run from its AppImage, the app
    also has APPIMAGE, APPDIR, ARGV0 and OWD naming its own file and mount: a child that is an AppImage unpacked
    (shadPS4's AppRun, the PKG tool) would take them for its own and look for its files in ours, so they go too."""
    env = dict(os.environ)
    if os.name != 'nt':
        for name in APPIMAGE_ENV:
            env.pop(name, None)
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    base = getattr(sys, '_MEIPASS', None)
    if base and env.get('PATH'):
        env['PATH'] = os.pathsep.join(p for p in env['PATH'].split(os.pathsep)
                                      if not os.path.normcase(p).startswith(os.path.normcase(base)))
    if base and os.name != 'nt':
        before = env.pop('LD_LIBRARY_PATH_ORIG', None)
        if before is not None:
            env['LD_LIBRARY_PATH'] = before
        else:
            env.pop('LD_LIBRARY_PATH', None)
    return env


def restart(exe, args=()):
    """Start the (new) exe the way a double-click would, free of this program's unpacked folder."""
    flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    kw = dict(close_fds=True, creationflags=flags, cwd=os.path.dirname(exe), env=clean_environment())
    base = getattr(sys, '_MEIPASS', None)
    if os.name != 'nt':
        return subprocess.Popen([exe, *args], start_new_session=True, **kw)
    if not base:
        return subprocess.Popen([exe, *args], **kw)
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.SetDllDirectoryW(None)      # the bootloader set it to _MEI...; a child would inherit it
    try:
        return subprocess.Popen([exe, *args], **kw)
    finally:
        k32.SetDllDirectoryW(base)


class Refused(RuntimeError):
    """The update cannot be installed now (the message says why, in plain words)."""


def install(release, exe=None, progress=None, start=True, emulator=None):
    """Download, check and swap in the new exe, then start it. Returns the exe path: the caller quits.
    Refused while shadPS4 runs (the game must not lose its app halfway; asked again after the download, just before
    the swap), when the release is another exe's file, or when this copy cannot replace itself."""
    exe = exe or running_exe()
    emulator = emulator or emulator_running
    running = Refused('Close the emulator (shadPS4) first, then update.')
    if emulator():
        raise running
    if not exe or not release.can_install() or not can_replace(exe):
        raise Refused('This copy cannot replace itself.')
    if release.asset != asset_for(exe):
        raise Refused(f'This release is {release.asset}, not {os.path.basename(exe)}.')
    new = exe + '.new'
    download(release, new, progress)
    try:
        check_signature(new, exe)
    except BaseException:
        try:
            os.remove(new)
        except OSError:
            pass
        raise
    if emulator():
        try:
            os.remove(new)
        except OSError:
            pass
        raise running
    swap(new, exe)
    if start:
        restart(exe)
    return exe
