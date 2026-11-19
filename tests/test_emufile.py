"""shadPS4's program file per system: pack names, what a pack must hold, how it is put in place and started
(overtime_roster/app/emufile.py)."""
import os
import subprocess
import zipfile

import pytest

from overtime_roster.app import emufile

ELF = bytes([0x7F]) + b'ELF' + b'x' * 60
MACHO = bytes([0xCF, 0xFA, 0xED, 0xFE]) + b'x' * 60
EXE = b'MZ' + b'x' * 60


def _pack(path, files, modes=None):
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in files.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = ((modes or {}).get(name, 0o644)) << 16
            z.writestr(info, data)
    return str(path)


def test_names_per_system():
    assert [emufile.name(s) for s in ('win32', 'linux', 'darwin')] == ['shadPS4.exe', 'shadps4.AppImage', 'shadps4']
    assert emufile.name('freebsd14') == 'shadps4.AppImage'             # another Unix: the Linux names
    assert emufile.pack_name('shadps4_native2.zip', 'win32') == 'shadps4_native2.zip'
    assert emufile.pack_name('shadps4_native2.zip', 'linux') == 'shadps4_native2_linux.zip'
    assert emufile.pack_name('shadps4_native2.zip', 'darwin') == 'shadps4_native2_macos.zip'


@pytest.mark.parametrize('system, name, good', [('win32', 'shadPS4.exe', EXE), ('linux', 'shadps4.AppImage', ELF),
                                                 ('darwin', 'shadps4', MACHO)])
def test_a_pack_must_hold_this_systems_program(tmp_path, system, name, good):
    emufile.check(_pack(tmp_path / 'ok.zip', {'build/' + name: good}), system)
    for other in {EXE, ELF, MACHO} - {good}:
        with pytest.raises(emufile.EmuFileError, match='is not a'):
            emufile.check(_pack(tmp_path / 'bad.zip', {name: other}), system)
    with pytest.raises(emufile.EmuFileError, match='not one'):
        emufile.check(_pack(tmp_path / 'none.zip', {'readme.txt': b'x'}), system)
    with pytest.raises(emufile.EmuFileError, match='not one'):
        emufile.check(_pack(tmp_path / 'two.zip', {'a/' + name: good, 'b/' + name: good}), system)
    (tmp_path / 'broken.zip').write_bytes(b'not a zip')
    with pytest.raises(emufile.EmuFileError):
        emufile.check(str(tmp_path / 'broken.zip'), system)


def test_windows_unpack_writes_the_exe_alone(tmp_path):
    pack = _pack(tmp_path / 'p.zip', {'shadPS4.exe': EXE, 'LICENSE.txt': b'gpl'})
    target = tmp_path / 'boost' / 'shadPS4.exe'
    target.parent.mkdir()
    emufile.unpack(pack, str(target), 'win32')
    assert target.read_bytes() == EXE and os.listdir(target.parent) == ['shadPS4.exe']


def test_macos_unpack_brings_the_libraries_and_refuses_paths_outside(tmp_path):
    pack = _pack(tmp_path / 'p.zip', {
        'mac/shadps4': MACHO, 'mac/libMoltenVK.dylib': b'lib', 'mac/vulkan/icd.d/kk.json': b'{}',
        'mac/../evil.txt': b'no', 'elsewhere/other.txt': b'no', 'mac/sub/': b''},
        modes={'mac/shadps4': 0o755, 'mac/libMoltenVK.dylib': 0o755})
    target = tmp_path / 'native2' / 'shadps4'
    target.parent.mkdir()
    emufile.unpack(pack, str(target), 'darwin')
    assert target.read_bytes() == MACHO
    assert (target.parent / 'libMoltenVK.dylib').read_bytes() == b'lib'
    assert (target.parent / 'vulkan' / 'icd.d' / 'kk.json').read_bytes() == b'{}'
    assert not (tmp_path / 'evil.txt').exists() and not (target.parent / 'other.txt').exists()
    assert not any(n.endswith('.part') for n in os.listdir(target.parent))


def _fake_appimage(folder, ok=True):
    """run() of an AppImage's --appimage-extract: makes squashfs-root/AppRun beside it."""
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        if ok:
            os.makedirs(os.path.join(kw['cwd'], emufile.ROOT, 'usr', 'bin'))
            with open(os.path.join(kw['cwd'], emufile.ROOT, 'AppRun'), 'w') as f:
                f.write('#!/bin/sh')
        return subprocess.CompletedProcess(cmd, 0 if ok else 1)
    return run, calls


def test_linux_unpack_unpacks_the_appimage_beside_itself(tmp_path):
    pack = _pack(tmp_path / 'p.zip', {'Shadps4.AppImage': ELF})
    target = tmp_path / 'native2' / 'shadps4.AppImage'
    target.parent.mkdir()
    (target.parent / emufile.ROOT / 'old').mkdir(parents=True)             # the build before
    run, calls = _fake_appimage(target.parent)
    emufile.unpack(pack, str(target), 'linux', run)
    (cmd, kw), = calls
    assert cmd == [str(target), '--appimage-extract'] and kw['cwd'] == str(target.parent)
    assert kw['timeout'] == emufile.EXTRACT_TIMEOUT and isinstance(kw['env'], dict)
    assert not (target.parent / emufile.ROOT / 'old').exists()
    apprun = str(target.parent / emufile.ROOT / 'AppRun')
    assert emufile.unpacked(str(target)) == apprun
    assert emufile.program(str(target)) == (apprun, {})
    # another file under the same name (a newer build copied in by hand): the unpacked copy is not its
    target.write_bytes(ELF + b'newer')
    assert emufile.unpacked(str(target)) is None
    assert emufile.program(str(target), fuse=False) == (str(target), {'APPIMAGE_EXTRACT_AND_RUN': '1'})
    assert emufile.program(str(target), fuse=True) == (str(target), {})


def test_an_appimage_that_does_not_unpack_is_started_as_it_is(tmp_path):
    target = tmp_path / 'shadps4.AppImage'
    target.write_bytes(ELF)
    run, _calls = _fake_appimage(tmp_path, ok=False)
    assert emufile.extract(str(target), run) is False and emufile.unpacked(str(target)) is None

    def gone(cmd, **kw):
        raise OSError('exec format error')
    assert emufile.extract(str(target), gone) is False
    assert emufile.program(str(target), fuse=False)[1] == {'APPIMAGE_EXTRACT_AND_RUN': '1'}


def test_other_program_files_start_as_they_are(tmp_path):
    for name in ('shadPS4.exe', 'shadps4'):
        path = str(tmp_path / name)
        assert emufile.program(path) == (path, {})


def test_fuse_is_there_only_with_the_device_and_its_helper():
    assert emufile.fuse_here(which=lambda n: '/usr/bin/' + n, exists=lambda p: True) is True
    assert emufile.fuse_here(which=lambda n: None, exists=lambda p: True) is False
    assert emufile.fuse_here(which=lambda n: '/usr/bin/' + n, exists=lambda p: False) is False
    assert emufile.fuse_here(which=lambda n: '/usr/bin/x' if n == 'fusermount3' else None, exists=lambda p: True)
