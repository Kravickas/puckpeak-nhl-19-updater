"""The first-run report of a Linux PC or a Mac (docs/plans/proud-shimmying-kettle.md, "First players are the proof").

Nobody on the team has such a computer, so what the first players' computers say is how we learn whether NHL 19
starts there. Only when the player opted in to reports (Multiplayer's one-time question, the same switch as the crash
reports), after the first game on each shadPS4 build the app sends one report of reason 'first_run': the usual facts
(crashreport.collect), the system, what preflight.py found, and the first lines of shad_log.txt, which name the GPU,
the Vulkan driver and how many CPU patches the static pass made. It goes through crashreport.build, so the player's
name, home folder, addresses and ShadNet details are taken out as in every report. Windows sends none.

What was sent is kept in the app's folder (first_run.json): {"<sha256 of the shadPS4>": "<report id>" | tries}.
A build is tried at most TRIES times (a server that does not know the reason yet refuses it). Standard library only.
"""
import json
import os
import platform
import sys

from overtime_core import durable

from . import crashreport, crossplay, paths, preflight

FILE = 'first_run.json'
REASON = 'first_run'
HEAD = 1500             # the log's first lines: the start-up, the GPU, the patches, the first frames
MIN_LINES = 5           # an emptier log is no game start: the next game is the first one
TRIES = 3


def _path():
    return os.path.join(paths.app_home(), FILE)


def state():
    """{emulator sha256: report id (sent) or the number of failed tries}; {} when there is no readable file."""
    try:
        with open(_path(), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and (isinstance(v, str) or type(v) is int)}


def _keep(sha, value):
    data = {**state(), sha: value}
    tmp = _path() + '.tmp'
    try:
        os.makedirs(paths.app_home(), exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1, sort_keys=True)
        durable.replace(tmp, _path())
    except OSError:
        pass


def wanted(sha, system=None):
    """Is a first-run report of the shadPS4 `sha` still to send from this system?"""
    if not crossplay.pool(system) or not sha or sha == '?':
        return False
    seen = state().get(sha)
    return not isinstance(seen, str) and (seen or 0) < TRIES


def meta(rows, system=None):
    """The report's own facts: the system and one value per preflight row ('pre_cpu': 'ok - ...')."""
    system = system or sys.platform
    out = {'system': system, 'os': platform.platform(), 'machine': platform.machine()}
    for line in preflight.summary(rows):
        key, _, value = line.partition(': ')
        out['pre_' + key] = value
    return out


def head(log_text):
    return '\n'.join((log_text or '').splitlines()[:HEAD])


def run(emu, game_dir, log_text, base_url, system=None, send=crashreport.send, rows=None):
    """Send the report when one is wanted and the log shows a start. Returns the report's id, or None (not wanted,
    no log yet). crashreport.ReportError when the server did not take it (the try is counted)."""
    system = system or sys.platform
    if not crossplay.pool(system) or not emu:
        return None
    facts = crashreport.collect(emu, game_dir, log_text)
    sha = facts.get('emu_sha256')
    if not wanted(sha, system) or len((log_text or '').splitlines()) < MIN_LINES:
        return None
    rows = preflight.cached(system) if rows is None else rows
    body = crashreport.build(REASON, head(log_text), {**facts, **meta(rows, system)},
                             extra=crashreport.own_secrets(emu))
    try:
        rid = send(base_url, body)
    except crashreport.ReportError:
        seen = state().get(sha)
        _keep(sha, (seen if type(seen) is int else 0) + 1)
        raise
    _keep(sha, str(rid))
    return rid
