"""Cross-CPU readiness (0.81.0). Intel and AMD CPUs return other low bits for rcpps/rsqrtps, so two games in lockstep
drift apart unless both run the cross-vendor block (xmlpatch 'crossvendor') and an Intel PC also runs shadPS4's AMD
math (gamesetup.AMD_MATH_KEY) (docs/notes/cross-vendor-desync.md).

read_log() says what the last boot had, from shadPS4's log: the block's "Applied patch" lines, the key, and the static
pass's unsupported count (which the block pre-empts on Intel). item() is the Game patch card's line: the last boot's
verdict when the log is newer than the patch file, else what the next start will have. Standard library only.
"""
import os
import re

from overtime_core import crossvendor, overlay, xmlpatch

from . import gamesetup, launch

APPLIED = re.compile(r'Applied patch: ' + re.escape(xmlpatch.CROSSVENDOR_TITLE) + r'[^,\n]*, Offset')
ANY_APPLIED = re.compile(r'Applied patch: ')
KEY = re.compile(r'isRedZonePatchingEnabled:\s*(true|false)', re.I)
CPU = re.compile(r'CPU Model:\s*([^\r\n]+)')
PASS = re.compile(r'(\d+)/(\d+) short CPU patches applied \((\d+) unsupported\)')    # Core.Linker, Debug
UNSUPPORTED = re.compile(r'(\d+) CPU patch instructions were unsupported')          # Core.Linker, Warning
FAILED = re.compile(r'Failed to (?:apply|patch)', re.I)

READY, BAD, UNKNOWN = 'ready', 'bad', 'unknown'


def read_log(text, intel):
    """{'state': READY | BAD | UNKNOWN, 'why', 'caves', 'want', 'key', 'unsupported', 'failures', 'cpu'} for one boot's
    shadPS4 log. UNKNOWN: the log never got to the patches (an early read, or a game started without any patch)."""
    want = len(crossvendor.LINES)
    caves = len(APPLIED.findall(text))
    key = KEY.search(text)
    key = None if key is None else key.group(1).lower() == 'true'
    m, u = PASS.search(text), UNSUPPORTED.search(text)
    unsupported = int(m.group(3)) if m else int(u.group(1)) if u else None
    cpu = CPU.search(text)
    out = {'caves': caves, 'want': want, 'key': key, 'unsupported': unsupported, 'failures': len(FAILED.findall(text)),
           'cpu': cpu.group(1).strip()[:80] if cpu else ''}
    if not caves and not ANY_APPLIED.search(text):
        return dict(out, state=UNKNOWN, why='the game had not applied its patch yet')
    if not caves:
        return dict(out, state=BAD, why='it started with an older patch that does not have the fix')
    if caves != want:
        return dict(out, state=BAD, why=f"only {caves} of the fix's {want} parts went in")
    if out['failures']:
        return dict(out, state=BAD, why=f"shadPS4 could not apply {out['failures']} of the patch's parts")
    if intel and key is not True:
        return dict(out, state=BAD, why="shadPS4's AMD math was off on this Intel PC")
    if intel and unsupported:
        return dict(out, state=BAD, why=f'shadPS4 left {unsupported} Intel math sites unfixed')
    return dict(out, state=READY, why='')


_LOG = {}       # log path -> ((size, mtime_ns), verdict): the log can be MBs late in a match


def last_boot(emu):
    """read_log() of the emulator's current log with its mtime ('when'), or None when there is no log."""
    path = launch.log_path(emu)
    try:
        st = os.stat(path)
        stamp = (st.st_size, st.st_mtime_ns)
        hit = _LOG.get(path)
        if hit and hit[0] == stamp:
            return hit[1]
        with open(path, encoding='utf-8', errors='replace') as f:
            verdict = dict(read_log(f.read(), gamesetup.amd_math_needed()), when=st.st_mtime)
    except OSError:
        return None
    _LOG[path] = (stamp, verdict)
    return verdict


def item(setup, running=None):
    """The Game patch card's Cross-CPU line: {'tone', 'text', 'title'}, or None when shadPS4 is not set up. A last
    start without the fix is red only while that game is still open (`running`, default: a shadPS4 is running); once it
    is closed, Play sets the patch and the key up again, so it is a caution that names what went wrong."""
    emu = setup.known_emulator()
    if not emu:
        return None
    user = gamesetup.emu_user_dir(emu)
    text = gamesetup.installed_patch()
    title = ('Intel and AMD PCs play in step only when both games run the Cross-CPU fix (and, on Intel, '
             "shadPS4's AMD math). Checked in shadPS4's log after NHL 19 starts.")
    if 'crossvendor' not in setup.features():
        return {'tone': 'caution', 'title': title,
                'text': 'Cross-CPU fix: not made for this eboot.bin (online you meet only games like yours)'}
    if text is None:
        return {'tone': 'idle', 'title': title, 'text': 'Cross-CPU fix: comes with the patch'}
    try:
        patched = os.path.getmtime(os.path.join(gamesetup.patch_dir(user), gamesetup.PATCH_FILE))
    except OSError:
        patched = None
    boot = last_boot(emu)
    if boot and boot['state'] != UNKNOWN and patched is not None and boot['when'] >= patched:
        if boot['state'] == READY:
            return {'tone': 'good', 'title': title, 'text': 'Cross-CPU: ready (checked at the last start)'}
        if overlay.emulator_running() if running is None else running:
            return {'tone': 'bad', 'title': title,
                    'text': f"The NHL 19 that is open now runs without the Cross-CPU fix ({boot['why']}). Don't play "
                            'online with it against the other CPU maker: close it and start it with Play here.'}
        return {'tone': 'caution', 'title': title,
                'text': f"Cross-CPU: the last game ran without the fix ({boot['why']}). Play here puts it in; this "
                        'line checks it again when NHL 19 starts.'}
    if xmlpatch.has_crossvendor(text) and gamesetup.amd_math_on(user):
        return {'tone': 'good', 'title': title, 'text': 'Cross-CPU fix in (checked at the next start)'}
    return {'tone': 'caution', 'title': title, 'text': 'Cross-CPU fix: goes in at the next Play'}
