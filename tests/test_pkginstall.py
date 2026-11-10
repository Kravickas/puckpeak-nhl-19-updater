"""pkginstall: NHL 19 from its PKG files with shadPS4Plus's pkg_extractor, here a fake one (no real PKG in the tests)."""
import hashlib
import io
import os
import pathlib
import zipfile
from collections import namedtuple

import pytest

from overtime_core import sfo
from overtime_roster.app import pkginstall

Usage = namedtuple('Usage', 'total used free')


def _sfo(title_id='CUSA11126', app_ver='01.60'):
    return sfo.build([sfo.Entry('APP_VER', sfo.FMT_UTF8, app_ver, 8), sfo.Entry('TITLE_ID', sfo.FMT_UTF8, title_id, 12)])


def _pkg(path, title='CUSA11126', size=4096):
    content = f'UP0006-{title}_00-NHL19GAME0000000'.encode().ljust(36, b'0')[:36]
    path.write_bytes(pkginstall.MAGIC + b'\0' * 0x3c + content + b'\0' * (size - 0x64))
    return path


def _game_files(folder, app_ver):
    (folder / 'sce_sys').mkdir(parents=True)
    (folder / 'sce_sys' / 'param.sfo').write_bytes(_sfo(app_ver=app_ver))
    (folder / 'eboot.bin').write_bytes(b'\x7fELF fake eboot')
    if app_ver == '01.00':
        (folder / 'databigs').mkdir()
        (folder / 'databigs' / 'inxp_10.big').write_bytes(b'x' * 100)


class FakeTool:
    """popen for pkg_extractor: --check-type exits `kind`; an extract writes what a real one writes (or nothing)."""

    def __init__(self, kind=pkginstall.BASE, writes=True):
        self.kind, self.writes, self.calls = kind, writes, []

    def __call__(self, args, **kw):
        self.calls.append(args)
        tool = self

        class Proc:
            returncode = None

            def __init__(self):
                if args[-1] == '--check-type':
                    self.returncode, self.stdout = tool.kind, io.StringIO('pkg is a base game\n')
                    return
                title = pkginstall.title_of(args[1])
                if tool.writes:
                    out = os.path.join(args[2], title + ('-patch' if tool.kind == pkginstall.UPDATE else ''))
                    _game_files(pathlib.Path(out), '01.60' if tool.kind == pkginstall.UPDATE else '01.00')
                    self.stdout = io.StringIO(f'Extracting file 1 of 1 to {out}\n\nTHE END {args[1]}\n')
                else:
                    self.stdout = io.StringIO('Cannot extract PKG file : Failed to decrypt\n\nTHE END x\n')
                self.returncode = 0

            def communicate(self):
                return self.stdout.read(), None

            def wait(self):
                return self.returncode
        return Proc()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'apphome'))
    monkeypatch.setattr(pkginstall.overlay, 'launcher_running', lambda: False)
    monkeypatch.setattr(pkginstall, 'ensure_tool', lambda progress=None, opener=None: str(tmp_path / 'pkg_extractor.exe'))
    return tmp_path


def _install(pkg, game_dir=None, tool=None):
    return pkginstall.install(str(pkg), game_dir and str(game_dir), running=lambda: False, popen=tool or FakeTool())


def test_title_comes_from_the_pkg_header(tmp_path):
    assert pkginstall.title_of(str(_pkg(tmp_path / 'a.pkg'))) == 'CUSA11126'
    (tmp_path / 'b.pkg').write_bytes(b'not a pkg' * 20)
    with pytest.raises(pkginstall.PkgError, match='not a PS4 PKG'):
        pkginstall.title_of(str(tmp_path / 'b.pkg'))


def test_base_goes_into_a_new_folder_beside_the_pkg(home):
    (home / 'dl').mkdir()
    pkg = _pkg(home / 'dl' / 'game.pkg')
    use, kind, game = _install(pkg)
    assert use == str(home / 'dl' / 'CUSA11126') and kind == pkginstall.BASE
    assert game['title_id'] == 'CUSA11126' and game['app_ver'] == '01.00' and not game['ok']
    assert sorted(os.listdir(home / 'dl')) == ['CUSA11126', 'game.pkg']      # the scratch folder is gone
    # a folder of that name already there is never written into
    use2, _kind, _game = _install(pkg)
    assert use2 == str(home / 'dl' / 'CUSA11126-2')


def test_update_goes_beside_the_game_as_shadps4_mounts_it(home):
    games = home / 'games'
    _game_files(games / 'NHL 19', '01.00')
    (games / 'NHL 19-patch').mkdir()                    # an older update folder: kept, not deleted
    (games / 'NHL 19-patch' / 'old.txt').write_text('keep')
    pkg = _pkg(home / 'update.pkg')
    use, kind, game = _install(pkg, games / 'NHL 19', FakeTool(pkginstall.UPDATE))
    assert use == str(games / 'NHL 19') and kind == pkginstall.UPDATE
    assert game['ok'] and game['app_ver'] == '01.60' and game['update'] == str(games / 'NHL 19-patch')
    assert (games / 'NHL 19-patch.old' / 'old.txt').read_text() == 'keep'
    assert sorted(os.listdir(games)) == ['NHL 19', 'NHL 19-patch', 'NHL 19-patch.old']


def test_update_needs_the_game_first(home):
    with pytest.raises(pkginstall.PkgError, match='game PKG first'):
        _install(_pkg(home / 'update.pkg'), None, FakeTool(pkginstall.UPDATE))


def test_update_refused_where_an_update_folder_shadps4_prefers_is(home):
    _game_files(home / 'CUSA11126', '01.00')
    (home / 'CUSA11126-UPDATE').mkdir()
    with pytest.raises(pkginstall.PkgError, match='-UPDATE'):
        _install(_pkg(home / 'u.pkg'), home / 'CUSA11126', FakeTool(pkginstall.UPDATE))


def test_refusals_before_anything_is_written(home):
    with pytest.raises(pkginstall.PkgError, match='CUSA00001, not NHL 19'):
        _install(_pkg(home / 'other.pkg', title='CUSA00001'))
    with pytest.raises(pkginstall.PkgError, match='DLC'):
        _install(_pkg(home / 'dlc.pkg'), None, FakeTool(pkginstall.DLC))
    with pytest.raises(pkginstall.PkgError, match='cannot read'):
        _install(_pkg(home / 'bad.pkg'), None, FakeTool(0))
    with pytest.raises(Exception, match='running'):
        pkginstall.install(str(_pkg(home / 'g.pkg')), running=lambda: True, popen=FakeTool())
    assert not [n for n in os.listdir(home) if n.startswith(pkginstall.SCRATCH) or n == 'CUSA11126']


def test_no_room_says_how_much(home, monkeypatch):
    monkeypatch.setattr(pkginstall.shutil, 'disk_usage', lambda p: Usage(10**12, 10**12, 1000))
    with pytest.raises(pkginstall.PkgError, match='free, the game needs about'):
        _install(_pkg(home / 'g.pkg'))


def test_a_failed_extract_leaves_nothing_and_says_the_tools_reason(home):
    with pytest.raises(pkginstall.PkgError, match='Failed to decrypt'):
        _install(_pkg(home / 'g.pkg'), None, FakeTool(writes=False))
    assert sorted(os.listdir(home)) == ['g.pkg']


def test_the_tool_is_downloaded_once_and_checked(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'apphome'))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name in ('pkg_extractor.exe', 'libc++.dll', 'zlib1.dll', 'readme_windows.txt'):
            z.writestr(name, b'MZ ' + name.encode())
    data = buf.getvalue()
    monkeypatch.setattr(pkginstall, 'TOOL_SHA256', hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(pkginstall, 'TOOL_SIZE', len(data))
    opened = []

    def opener(url):
        opened.append(url)
        return io.BytesIO(data)
    exe = pkginstall.ensure_tool(opener=opener)
    folder = os.path.dirname(exe)
    assert exe.endswith('pkg_extractor.exe') and os.path.isfile(os.path.join(folder, 'zlib1.dll'))
    assert pkginstall.ensure_tool(opener=opener) == exe and len(opened) == 1      # not again
    assert opened == [pkginstall.TOOL_URL] and not os.path.exists(os.path.join(folder, 'tool.zip.part'))


def test_another_tool_file_is_not_used(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'apphome'))
    monkeypatch.setattr(pkginstall, 'TOOL_SIZE', 10)
    with pytest.raises(pkginstall.PkgError, match='not the one Overtime knows'):
        pkginstall.ensure_tool(opener=lambda url: io.BytesIO(b'0123456789'))
    assert not os.path.exists(pkginstall.tool_exe())
