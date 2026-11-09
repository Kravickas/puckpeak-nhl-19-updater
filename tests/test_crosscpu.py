"""Cross-CPU self-check (overtime_roster/app/crosscpu.py): shadPS4's log after a boot, and the Game patch card line."""
import os
import time

import pytest

from overtime_core import crossvendor, xmlpatch
from overtime_roster.app import crosscpu, gamesetup

TITLE = xmlpatch.CROSSVENDOR_TITLE


def boot_log(caves=None, key='true', pass_line=True, unsupported=0, other=True, failed=False):
    """A shadPS4 log as the T15's key-ON boot wrote it (2026-11-09), with the parts a test changes."""
    caves = len(crossvendor.LINES) if caves is None else caves
    out = [f'[Config] <Info> (shadPS4:Main) emulator.cpp:490 Run: General isRedZonePatchingEnabled: {key}',
           '[Config] <Info> (shadPS4:Main) emulator.cpp:529 Run: CPU Model: Intel(R) Core(TM) i5-10210U CPU @ 1.60GHz']
    if other:
        out.append('[Loader] <Info> () memory_patcher.cpp:417 PatchMemory: Applied patch: ProtoHttp: accept EAGAIN '
                   'while waiting for the status code, Offset: 0x8a80813, Value: 82104380')
    out += [f'[Loader] <Info> () memory_patcher.cpp:417 PatchMemory: Applied patch: {TITLE}, Offset: 0x{0x563da08 + i:x}, '
            'Value: E905CB2905' for i in range(caves)]
    if failed:
        out.append(f'[Loader] <Error> () memory_patcher.cpp:420 PatchMemory: Failed to apply patch: {TITLE}')
    if pass_line:
        out.append('[Core.Linker] <Debug> () module.cpp:416 LoadModuleToMemory: Windows guest red-zone static patching '
                   'for eboot.bin: 148716 functions, ... (5201 short, 0 stack-dependent, 1 control-flow, 368 '
                   f'unrelocatable), {2285 - unsupported}/2285 short CPU patches applied ({unsupported} unsupported)')
    return '\n'.join(out) + '\n'


def test_a_full_boot_on_intel_is_ready():
    got = crosscpu.read_log(boot_log(), intel=True)
    assert got['state'] == crosscpu.READY and got['caves'] == got['want'] == len(crossvendor.LINES)
    assert got['key'] is True and got['unsupported'] == 0 and got['cpu'].startswith('Intel(R) Core(TM) i5-10210U')
    # the kit's block name had a " 1/1" suffix: it counts too
    assert crosscpu.read_log(boot_log().replace(f'{TITLE},', f'{TITLE} 1/1,'), intel=True)['state'] == crosscpu.READY
    # the Debug pass line filtered out: the Warning line, or nothing (the caves and the key still say ready)
    assert crosscpu.read_log(boot_log(pass_line=False), intel=True)['state'] == crosscpu.READY


@pytest.mark.parametrize('kw,why', [
    ({'caves': 0}, 'older patch'), ({'caves': 100}, 'only 100 of'), ({'failed': True}, 'could not apply 1'),
    ({'key': 'false'}, 'AMD math was off'), ({'unsupported': 150}, '150 Intel math sites')])
def test_what_breaks_cross_cpu_play_on_intel(kw, why):
    got = crosscpu.read_log(boot_log(**kw), intel=True)
    assert got['state'] == crosscpu.BAD and why in got['why']


def test_amd_needs_only_the_block_and_an_early_log_proves_nothing():
    assert crosscpu.read_log(boot_log(key='false', pass_line=False), intel=False)['state'] == crosscpu.READY
    assert crosscpu.read_log(boot_log(caves=0, other=False), intel=False)['state'] == crosscpu.UNKNOWN
    assert crosscpu.read_log('', intel=True)['state'] == crosscpu.UNKNOWN


class FakeSetup:
    def __init__(self, emu, features=xmlpatch.DEFAULT):
        self.emu, self._features = emu, features

    def known_emulator(self):
        return self.emu

    def features(self):
        return self._features


@pytest.fixture
def emu(tmp_path, monkeypatch):
    user = tmp_path / 'user'
    (user / 'log').mkdir(parents=True)
    monkeypatch.setattr(gamesetup, 'emu_user_dir', lambda exe: str(user))
    monkeypatch.setattr(gamesetup, 'amd_math_needed', lambda: True)
    monkeypatch.setattr(gamesetup, 'amd_math_on', lambda u: True)
    crosscpu._LOG.clear()
    patch = tmp_path / 'overtime.xml'
    monkeypatch.setattr(gamesetup, 'patch_dir', lambda u: str(tmp_path))
    monkeypatch.setattr(gamesetup, 'PATCH_FILE', 'overtime.xml')
    monkeypatch.setattr(gamesetup, 'installed_patch',
                        lambda: patch.read_text(encoding='utf-8') if patch.exists() else None)
    return {'exe': str(tmp_path / 'shadPS4.exe'), 'log': user / 'log' / 'shad_log.txt', 'patch': patch}


def _age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def test_the_card_line_follows_the_patch_then_the_last_boot(emu):
    setup = FakeSetup(emu['exe'])
    assert crosscpu.item(setup)['text'] == 'Cross-CPU fix: comes with the patch'
    emu['patch'].write_text(xmlpatch.build('localhost', features=xmlpatch.NO_CROSSVENDOR), encoding='utf-8')
    assert crosscpu.item(setup)['tone'] == 'caution'                 # a 0.80 file: the next Play brings it up
    emu['patch'].write_text(xmlpatch.build('localhost'), encoding='utf-8')
    assert crosscpu.item(setup)['tone'] == 'good' and 'next start' in crosscpu.item(setup)['text']
    emu['log'].write_text(boot_log(key='false'), encoding='utf-8')
    _age(emu['patch'], 60)                                           # the log is newer: its verdict counts
    got = crosscpu.item(setup, running=True)                         # that game is still open: red
    assert got['tone'] == 'bad' and 'AMD math was off' in got['text'] and 'open now' in got['text']
    got = crosscpu.item(setup, running=False)                        # closed: Play sets it up again
    assert got['tone'] == 'caution' and 'AMD math was off' in got['text'] and 'Play here puts it in' in got['text']
    emu['log'].write_text(boot_log(caves=0), encoding='utf-8')       # a 0.80 patch: the owner's case, 2026-11-09
    _age(emu['patch'], 90)
    assert 'older patch that does not have the fix' in crosscpu.item(setup, running=False)['text']
    emu['log'].write_text(boot_log(), encoding='utf-8')
    _age(emu['patch'], 120)
    assert crosscpu.item(setup)['text'] == 'Cross-CPU: ready (checked at the last start)'
    _age(emu['log'], 600)                                            # an older boot than the patch file: not it
    assert 'next start' in crosscpu.item(setup)['text']


def test_an_eboot_the_block_was_not_made_for_says_so(emu):
    got = crosscpu.item(FakeSetup(emu['exe'], features=xmlpatch.NO_CROSSVENDOR))
    assert got['tone'] == 'caution' and 'not made for this eboot.bin' in got['text']
    assert crosscpu.item(FakeSetup('')) is None
