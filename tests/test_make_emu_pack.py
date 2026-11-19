"""tools/make_emu_pack.py: a build's files into the pack emufile.unpack reads, the same bytes every time."""
import hashlib
import zipfile

import pytest

from overtime_roster.app import emufile

make_emu_pack = pytest.importorskip('tools.make_emu_pack')    # the public copy has the app, not the tools

ELF = bytes([0x7F]) + b'ELF' + b'appimage' * 500
MACHO = bytes([0xCF, 0xFA, 0xED, 0xFE]) + b'macho' * 500
EXE = b'MZ' + b'exe' * 500


def test_a_linux_pack_holds_the_appimage_under_the_apps_name(tmp_path):
    src = tmp_path / 'Shadps4-sdl.AppImage'
    src.write_bytes(ELF)
    got = make_emu_pack.make(str(src), str(tmp_path / 'out' / 'shadps4_native2_linux.zip'), 'linux')
    assert got['program'] == 'shadps4.AppImage' and got['files'] == 1
    assert got['program_sha256'] == hashlib.sha256(ELF).hexdigest()
    with zipfile.ZipFile(got['pack']) as z:
        info, = z.infolist()
        assert info.filename == 'shadps4.AppImage' and (info.external_attr >> 16) & 0o777 == 0o755
    target = tmp_path / 'native2' / 'shadps4.AppImage'
    target.parent.mkdir()
    emufile.unpack(got['pack'], str(target), 'linux', run=lambda cmd, **kw: type('R', (), {'returncode': 1})())
    assert target.read_bytes() == ELF


def test_the_same_input_gives_the_same_pack(tmp_path):
    src = tmp_path / 'shadPS4.exe'
    src.write_bytes(EXE)
    a = make_emu_pack.make(str(src), str(tmp_path / 'a.zip'), 'win32')
    b = make_emu_pack.make(str(src), str(tmp_path / 'b.zip'), 'win32')
    assert a['pack_sha256'] == b['pack_sha256'] and a['size'] == b['size']
    emufile.check(a['pack'], 'win32')


def test_a_macos_pack_brings_the_files_beside_the_program(tmp_path):
    build = tmp_path / 'build'
    (build / 'vulkan' / 'icd.d').mkdir(parents=True)
    (build / 'shadps4').write_bytes(MACHO)
    (build / 'libMoltenVK.dylib').write_bytes(b'lib')
    (build / 'vulkan' / 'icd.d' / 'kk.json').write_bytes(b'{}')
    got = make_emu_pack.make(str(build), str(tmp_path / 'mac.zip'), 'darwin')
    with zipfile.ZipFile(got['pack']) as z:
        modes = {i.filename: (i.external_attr >> 16) & 0o777 for i in z.infolist()}
    assert list(modes) == ['shadps4', 'libMoltenVK.dylib', 'vulkan/icd.d/kk.json']       # the program first
    assert modes == {'shadps4': 0o755, 'libMoltenVK.dylib': 0o755, 'vulkan/icd.d/kk.json': 0o644}
    target = tmp_path / 'native2' / 'shadps4'
    target.parent.mkdir()
    emufile.unpack(got['pack'], str(target), 'darwin')
    assert (target.parent / 'vulkan' / 'icd.d' / 'kk.json').read_bytes() == b'{}'


def test_a_wrong_input_is_refused_and_leaves_no_pack(tmp_path, capsys):
    src = tmp_path / 'shadPS4.exe'
    src.write_bytes(EXE)
    with pytest.raises(make_emu_pack.PackError, match='is not a Linux program'):
        make_emu_pack.make(str(src), str(tmp_path / 'x.zip'), 'linux')
    (tmp_path / 'empty').mkdir()
    with pytest.raises(make_emu_pack.PackError, match='no shadPS4 program'):
        make_emu_pack.make(str(tmp_path / 'empty'), str(tmp_path / 'x.zip'), 'darwin')
    assert make_emu_pack.main(['--platform', 'linux', '--input', str(src), '--out', str(tmp_path / 'x.zip')]) == 1
    assert 'is not a Linux program' in capsys.readouterr().err and not (tmp_path / 'x.zip').exists()
    assert make_emu_pack.main(['--platform', 'windows', '--input', str(src), '--out', str(tmp_path / 'w.zip')]) == 0
    assert 'the matchmaking tag hashes this' in capsys.readouterr().out
