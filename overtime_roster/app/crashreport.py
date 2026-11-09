"""Opt-in crash and early-end reports (0.81.0, plan WP4). The server side is docs/notes/reports.md (POST /app/report,
GET /app/report/wanted); the body is gzip of UTF-8 JSON {"v": 1, "reason", "meta", "log"}, a 'cpu' report (Check my
CPU) also "attach": {"name", "b64"} (the server checks the four keys and keeps the rest as it came).

Nothing here is sent by itself: multiplayer_ctl asks for it (automatic only when the player opted in, the manual
button always). scrub() takes out the player's own paths, names, addresses and e-mail addresses, and (own_secrets)
the ShadNet Online IDs, passwords and tokens of users.json, before a log leaves the PC. Standard library only (plus the app's own small modules for the meta).
"""
import base64
import gzip
import hashlib
import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from overtime_core import net

from .. import VERSION
from . import crosscpu, gamesetup, launch

REASONS = ('crash', 'early_end', 'manual', 'cpu')
HEAD_LINES, TAIL_LINES = 3000, 20000    # the log's first and last lines (the middle is left out)
MAX_BODY = 2 << 20                      # the body as sent (gzip), the server's limit
MAX_RAW = 20 << 20                      # the unpacked JSON, the server's limit
META_KEYS, META_KEY, META_TEXT = 64, 40, 300
SEND_TIMEOUT, WANT_TIMEOUT = 60, 8
CRASH = re.compile(r'Unhandled Exception code 0x[0-9A-Fa-f]+')     # shadPS4's SignalHandler line (docs/notes/network-stats-crash.md)
GPU_ID = re.compile(r'Vulkan gpuId: (\d+)')
DMEM_KEY = gamesetup.DMEM_KEY
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
IPV4 = re.compile(r'(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\w]|\.\d)')
IPV6 = re.compile(r'(?<![0-9A-Za-z:.])[0-9A-Fa-f:]{2,}(?![0-9A-Za-z:.])')
MIN_NAME = 3
MIN_SECRET = 4
SECRET = '<secret>'


class ReportError(Exception):
    """A report that did not go. `str(err)` is the text to show the player."""


# --- scrubbing -----------------------------------------------------------------------------------------------------

def _home_pattern():
    home = os.environ.get('USERPROFILE') or os.path.expanduser('~') or ''
    parts = [p for p in re.split(r'[\\/]+', home) if p]
    if not parts:
        return None
    return re.compile(r'[\\/]+'.join(re.escape(p) for p in parts), re.IGNORECASE)


def _word(name):
    return re.compile(r'(?<![\w])' + re.escape(name) + r'(?![\w])', re.IGNORECASE)


def _ipv6(match):
    text = match.group(0)
    if text.count(':') < 2:
        return text
    try:
        ipaddress.IPv6Address(text)
    except ValueError:
        return text             # a time (19:11:44) or some other run of hex and colons
    return '<ip>'


def _extra(text, extra):
    """The (value, placeholder) pairs of own_secrets, longest first: a secret (<secret>) of MIN_SECRET or more
    characters wherever it stands, exactly; a name of MIN_NAME or more as a whole word, any case."""
    for value, placeholder in sorted(extra or (), key=lambda p: -len(p[0] or '')):
        if not isinstance(value, str) or not isinstance(placeholder, str):
            continue
        if placeholder == SECRET:
            if len(value) >= MIN_SECRET:
                text = text.replace(value, SECRET)
        elif len(value) >= MIN_NAME:
            text = _word(value).sub(placeholder, text)
    return text


def scrub(text, extra=()):
    """`text` with the player's home folder, user and computer names, e-mail addresses and IPv4 / IPv6 addresses
    replaced by <home>, <user>, <pc>, <email> and <ip>, and the `extra` (value, placeholder) pairs (own_secrets: the
    ShadNet Online ID, password, ...) by theirs. Hex numbers (0x56ea4b0), times and version strings stay."""
    if not text:
        return text or ''
    text = _extra(text, extra)
    home = _home_pattern()
    if home is not None:
        text = home.sub('<home>', text)
    for env, placeholder in (('USERNAME', '<user>'), ('COMPUTERNAME', '<pc>')):
        name = (os.environ.get(env) or '').strip()
        if len(name) >= MIN_NAME:
            text = _word(name).sub(placeholder, text)
    text = EMAIL.sub('<email>', text)
    text = IPV4.sub('<ip>', text)
    return IPV6.sub(_ipv6, text)


# --- the log -------------------------------------------------------------------------------------------------------

def _cut(lines, head, tail):
    if len(lines) <= head + tail:
        return '\n'.join(lines) + ('\n' if lines else '')
    cut = len(lines) - head - tail
    kept = lines[:head] + [f'--- {cut} lines left out (the log had {len(lines)}) ---'] + lines[len(lines) - tail:]
    return '\n'.join(kept) + '\n'


def cap_log(text, head=HEAD_LINES, tail=TAIL_LINES):
    """The first `head` and the last `tail` lines, with a one-line marker for how many were left out."""
    return _cut((text or '').splitlines(), head, tail)


def crashed(log_text, exit_code=None):
    """True when the emulator ended abnormally: a non-zero exit code, shadPS4's 'Unhandled Exception' line
    (docs/notes/network-stats-crash.md), or a <Critical> line (the same pattern launch.read_log uses)."""
    if exit_code not in (None, 0):
        return True
    text = log_text or ''
    return bool(CRASH.search(text) or launch.CRITICAL.search(text))


# --- the meta ------------------------------------------------------------------------------------------------------

def _value(v, extra=()):
    if v is None or isinstance(v, (bool, int)):
        return v
    text = scrub(v if isinstance(v, str) else str(v), extra)
    return text[:META_TEXT]


def _meta(meta, extra=()):
    out = {}
    for key, v in list(meta.items())[:META_KEYS]:
        out[str(key)[:META_KEY]] = _value(v, extra)
    return out


def own_secrets(emu):
    """gamesetup.report_secrets of this emulator's user folder (the ShadNet Online IDs, passwords, ...), for scrub's
    `extra`. [] when it cannot be read. Never raises."""
    try:
        return gamesetup.report_secrets(gamesetup.emu_user_dir(emu)) if emu else []
    except Exception:   # noqa: BLE001 (a look must never stop a report)
        return []


def _sha256_file(path):
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return '?'


def _dmem(user_dir):
    try:
        with open(gamesetup.custom_config_path(user_dir), encoding='utf-8-sig') as f:
            value = (json.load(f).get('General') or {}).get(DMEM_KEY)
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    except (OSError, ValueError, AttributeError, gamesetup.SetupError):
        return None


def collect(emu, game_dir, log_text='', ext=None, match=None):
    """The meta of a report about this PC and the game that just ran: app version, emulator (exe sha, revision,
    vblank and neo, dmem, GPU id), CPU name and maker, AMD math key, the Cross-CPU check, the game's online version,
    the player's ShadNet id (ext) and the match id. Unknown values are '?' or None. Never raises."""
    out = {'app_version': VERSION, 'emu_sha256': '?', 'emu': '?', 'timing': '?', 'dmem': None, 'gpu_id': None,
           'cpu': '?', 'cpu_vendor': '?', 'amd_math': None, 'cross_cpu': '?', 'cross_why': '', 'online': '?',
           'ext': ext if isinstance(ext, int) and not isinstance(ext, bool) else None,
           'match': match if isinstance(match, int) and not isinstance(match, bool) else None}
    checks = (
        ('emu_sha256', lambda: _sha256_file(emu) if emu else '?'),
        ('cpu', lambda: gamesetup.cpu_name() or '?'),
        ('cpu_vendor', gamesetup.cpu_vendor),
        ('online', lambda: gamesetup.online_version(game_dir)[1] if game_dir else '?'),
        ('gpu_id', lambda: int(GPU_ID.search(log_text).group(1)) if GPU_ID.search(log_text or '') else None),
    )
    for key, fn in checks:
        try:
            out[key] = fn()
        except Exception:   # noqa: BLE001 (a look must never stop a report)
            pass
    if emu:
        try:
            ident = gamesetup.emulator_identity(emu) or {}
            out['emu'], out['timing'] = ident.get('emu', '?'), ident.get('timing', '?')
        except Exception:   # noqa: BLE001
            pass
        try:
            user = gamesetup.emu_user_dir(emu)
            out['dmem'] = _dmem(user)
            out['amd_math'] = gamesetup.amd_math_on(user)
            boot = crosscpu.last_boot(emu)
            if boot:
                out['cross_cpu'], out['cross_why'] = boot['state'], boot.get('why', '')
        except Exception:   # noqa: BLE001
            pass
    return _meta(out)


def build(reason, log_text, meta, extra=(), attach=None):
    """The gzip body of one report. The log is cut to HEAD_LINES + TAIL_LINES, scrubbed (with `extra`, see scrub), and
    cut further when the gzip body would pass MAX_BODY (or the JSON MAX_RAW). attach: (file name, bytes) of a file
    that holds no personal data (Check my CPU's result zip), sent whole as base64 under 'attach', never scrubbed (a
    replacement would break it); the server keeps the body as it came."""
    if reason not in REASONS:
        raise ValueError(f'unknown report reason {reason!r}')
    lines = (log_text or '').splitlines()
    extra = list(extra or ())
    clean = _meta(meta or {}, extra)
    # a result zip is LZMA already: its body is about its own size (a CPU with three core types: about 1.2 MB)
    if attach is not None and len(attach[1]) > MAX_BODY:
        raise ReportError('The file is too big to send.')
    added = {} if attach is None else {'attach': {'name': str(attach[0])[:80],
                                                  'b64': base64.b64encode(attach[1]).decode('ascii')}}
    if added:   # with no log at all: refused at once, not after halving the log down to nothing
        bare = json.dumps({'v': 1, 'reason': reason, 'meta': clean, 'log': '', **added}).encode('utf-8')
        if len(gzip.compress(bare, 9)) > MAX_BODY:
            raise ReportError('The file is too big to send.')
    head, tail = HEAD_LINES, TAIL_LINES
    while True:
        doc = {'v': 1, 'reason': reason, 'meta': clean, 'log': scrub(_cut(lines, head, tail), extra), **added}
        raw = json.dumps(doc, ensure_ascii=False).encode('utf-8')
        body = gzip.compress(raw, 9)
        if len(body) <= MAX_BODY and len(raw) < MAX_RAW:
            return body
        if head == 0 and tail == 0:
            if added:       # the file alone does not fit: say so here, not as the server's 413
                raise ReportError('The file is too big to send.')
            return body
        if tail:
            tail //= 2
        else:
            head //= 2


# --- the server ----------------------------------------------------------------------------------------------------

def _retry_text(err):
    try:
        seconds = int(err.headers.get('Retry-After') or 0)
    except (TypeError, ValueError):
        seconds = 0
    if seconds <= 0:
        return 'Try again later.'
    return f'Try again in {max(1, -(-seconds // 60))} minutes.'


def send(base_url, body, timeout=SEND_TIMEOUT, opener=None):
    """POST one report body; the server's id. ReportError with the text to show the player otherwise."""
    req = urllib.request.Request(base_url.rstrip('/') + '/app/report', data=body, method='POST',
                                 headers={'Content-Type': 'application/gzip', 'Accept': 'application/json'})
    try:
        with (opener or net.urlopen)(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as err:
        if err.code == 413:
            raise ReportError('The report is too big to send.') from None
        if err.code == 429:
            raise ReportError(f'Too many reports from this PC lately. {_retry_text(err)}') from None
        if err.code == 404:
            raise ReportError('The Overtime server does not take reports yet.') from None
        if err.code == 400:
            raise ReportError('The server refused the report.') from None
        raise ReportError(f'The server did not take the report (error {err.code}).') from None
    except (urllib.error.URLError, OSError, ValueError) as err:
        raise ReportError('Could not reach the Overtime server. Check your internet, then try again.') from err
    try:
        doc = json.loads(raw or b'null')
    except ValueError:
        doc = None
    rid = doc.get('id') if isinstance(doc, dict) else None
    if not isinstance(rid, str) or not rid:
        raise ReportError('The server did not confirm the report.')
    return rid


def wanted(base_url, ext, timeout=WANT_TIMEOUT, opener=None):
    """(wanted, match id or None): the server's answer for this ShadNet id. Never raises: (False, None) on any error."""
    try:
        url = base_url.rstrip('/') + '/app/report/wanted?' + urllib.parse.urlencode({'ext': int(ext)})
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with (opener or net.urlopen)(req, timeout=timeout) as r:
            doc = json.loads(r.read() or b'null')
        if not isinstance(doc, dict) or doc.get('wanted') is not True:
            return False, None
        match = doc.get('match')
        return True, match if isinstance(match, int) and not isinstance(match, bool) else None
    except Exception:   # noqa: BLE001 (a question that fails means no)
        return False, None
