"""Play: start NHL 19 in shadPS4 and read back from the emulator's log whether the Overtime patch and ShadNet took.

The game starts from the emulator's own folder (so a portable `user\\` folder there is the one it uses), with the
patch from its patches folder (gamesetup.install), or with `-p <file>` when one is given (that skips the folder).
"""
import os
import re
import subprocess
import sys

from overtime_core import gamefiles, overlay

from . import gamesetup, selfupdate


class LaunchError(RuntimeError):
    pass


def command(emu_exe, game_dir, patch_file=None):
    """shadPS4 starts the base game's eboot.bin and lays its `-UPDATE` / `-patch` and `-mods` folders over it."""
    cmd = [os.path.abspath(emu_exe), '-g', os.path.join(gamefiles.roots(game_dir)[0], 'eboot.bin')]
    if patch_file:
        cmd += ['-p', os.path.abspath(patch_file)]
    return cmd


def start(emu_exe, game_dir, patch_file=None, running=None, popen=subprocess.Popen):
    """Start the game; returns the process. Refuses while another shadPS4 runs (one emulator at a time)."""
    if (running or overlay.emulator_running)():
        raise LaunchError('shadPS4 is already running.')
    if not os.path.isfile(emu_exe):
        raise LaunchError(f'shadPS4 not found: {emu_exe}')
    game = gamesetup.read_game(game_dir)
    if not game['ok']:
        raise LaunchError(f'cannot start {game_dir}: {game["problem"]}')
    flags = 0
    if sys.platform == 'win32':
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return popen(command(emu_exe, game_dir, patch_file), cwd=os.path.dirname(os.path.abspath(emu_exe)),
                 creationflags=flags, close_fds=True, env=selfupdate.clean_environment())


def log_path(emu_exe):
    return os.path.join(gamesetup.emu_user_dir(emu_exe), 'log', 'shad_log.txt')


APPLIED = re.compile(r'Applied patch: (?P<name>.+?), Offset: (?P<addr>0x[0-9a-fA-F]+)')
CRITICAL = re.compile(r'.*<Critical>.*')


def read_log(text):
    """{'patches': {block name: lines applied}, 'shadnet': True | False | None, 'crash': first critical line or None}.
    ShadNet is None when the log never reached NP (an early stop proves nothing)."""
    patches = {}
    for m in APPLIED.finditer(text):
        patches[m.group('name')] = patches.get(m.group('name'), 0) + 1
    if re.search(r'no users connected to shadNet', text, re.I):
        shadnet = False
    elif re.search(r'Lib\.Np', text):
        shadnet = True
    else:
        shadnet = None
    crash = CRITICAL.search(text)
    return {'patches': patches, 'shadnet': shadnet, 'crash': crash.group(0).strip() if crash else None}


def check(emu_exe):
    """read_log() of the emulator's current log, or None when there is none."""
    try:
        with open(log_path(emu_exe), encoding='utf-8', errors='replace') as f:
            return read_log(f.read())
    except OSError:
        return None
