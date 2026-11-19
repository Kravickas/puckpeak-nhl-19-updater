"""The window and the first-open offers on Linux and macOS (overtime_roster/window/main.py, webview2.py,
overtime_roster/app/desktopentry.py): what is decided, without a window."""
import os
import subprocess
import threading
import time

import pytest

import overtime_roster
from overtime_roster.app import desktopentry, preflight, selfupdate
from overtime_roster.window import main as app_main
from overtime_roster.window import webview2

SLASH = chr(92)


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'home'))
    return tmp_path / 'home'


# --- the window's toolkit ---------------------------------------------------------------------------------------------
def test_linux_draws_with_qt_and_the_others_with_the_systems_own():
    assert app_main.window_toolkit('linux') == 'qt'
    assert app_main.window_toolkit('win32') is None and app_main.window_toolkit('darwin') is None


def test_qt_flags_keep_the_players_own_and_drop_the_sandbox_only_in_an_appimage():
    assert app_main.qt_flags({}) == '--disable-gpu'
    assert app_main.qt_flags({'OVERTIME_GPU': '1'}) == ''
    assert app_main.qt_flags({'APPIMAGE': '/x/Overtime.AppImage'}) == '--disable-gpu --no-sandbox'
    assert app_main.qt_flags({'APPDIR': '/tmp/.mount_x', 'QTWEBENGINE_CHROMIUM_FLAGS': '--no-sandbox --foo'}) == (
        '--no-sandbox --foo --disable-gpu')


def test_the_environment_is_set_for_qt_only():
    env = {'APPIMAGE': '/x/Overtime.AppImage'}
    app_main.prepare_toolkit('qt', env)
    assert env['QT_API'] == 'pyside6' and env['QTWEBENGINE_DISABLE_SANDBOX'] == '1'
    assert env['QTWEBENGINE_CHROMIUM_FLAGS'] == '--disable-gpu --no-sandbox'
    plain = {'QT_API': 'pyqt6'}
    app_main.prepare_toolkit('qt', plain)
    assert plain == {'QT_API': 'pyqt6', 'QTWEBENGINE_CHROMIUM_FLAGS': '--disable-gpu'}     # the player's choice stays
    untouched = {}
    app_main.prepare_toolkit(None, untouched)
    assert untouched == {}


def test_the_release_file_has_one_name_in_both_places():
    assert selfupdate.SYSTEM_ASSETS['linux'] == 'OvertimeNHL19-x86_64.AppImage'
    assert overtime_roster.EXE_NAME in ('OvertimeNHL19.exe', *selfupdate.SYSTEM_ASSETS.values())


def test_selftest_window_is_an_entry_of_its_own(monkeypatch):
    monkeypatch.setattr(app_main, 'selftest_window', lambda: 7)
    monkeypatch.setattr(app_main, 'selftest', lambda: pytest.fail('the plain selftest ran'))
    assert app_main.entry(['--selftest-window']) == 7


def test_selftest_window_fails_in_words_without_a_toolkit(monkeypatch, capsys):
    monkeypatch.setattr(app_main, 'have_pywebview', lambda: False)
    monkeypatch.setattr(app_main, 'HEADLESS', False)
    assert app_main.selftest_window() == 1
    out = capsys.readouterr().out
    assert 'the window toolkit is not there' in out and out.strip().endswith('FAIL')


def test_a_child_does_not_inherit_the_apps_own_appimage(monkeypatch):
    """shadPS4's unpacked AppRun keeps an APPDIR it is given: with ours it would look for its files in our mount."""
    monkeypatch.setattr(selfupdate.os, 'name', 'posix')
    for name in selfupdate.APPIMAGE_ENV:
        monkeypatch.setenv(name, '/tmp/.mount_Overtime')
    env = selfupdate.clean_environment()
    assert not [n for n in selfupdate.APPIMAGE_ENV if n in env]
    monkeypatch.setattr(selfupdate.os, 'name', 'nt')
    assert selfupdate.clean_environment()['APPDIR'] == '/tmp/.mount_Overtime'      # Windows: nothing to do with it


def test_a_double_click_start_has_no_console_off_windows():
    class Pipe:
        def isatty(self):
            return False

    class Terminal:
        def isatty(self):
            return True
    assert app_main.no_console(True, 'linux', Pipe()) is True
    assert app_main.no_console(True, 'darwin', Terminal()) is False
    assert app_main.no_console(False, 'linux', Pipe()) is False             # a run from source prints
    assert app_main.no_console(True, 'win32', Pipe()) is False              # the Windows exe has HEADLESS
    assert app_main.no_console(True, 'linux', object()) is True


def test_the_browser_fallback_waits_on_a_box_only_where_one_can_show(monkeypatch):
    """Without kdialog or zenity the box answers at once: waiting on it would close the app as it opens."""
    assert webview2.can_box('win32') and webview2.can_box('darwin')
    assert webview2.can_box('linux', which=lambda tool: '/usr/bin/' + tool if tool == 'zenity' else None)
    assert not webview2.can_box('linux', which=lambda tool: None)

    class Server:
        url = 'http://127.0.0.1:1/'
        waited = []

        def __init__(self, *a):
            pass

        def serve_background(self):
            self.waited.append('box')

        def serve_forever(self):
            self.waited.append('forever')

        def shutdown(self):
            pass

        def server_close(self):
            pass
    from overtime_roster.window import server as server_module
    monkeypatch.setattr(server_module, 'AppServer', Server)
    monkeypatch.setattr(app_main, 'HEADLESS', False)
    monkeypatch.setattr(app_main, 'no_console', lambda: True)
    monkeypatch.setattr(app_main.startup, 'close_splash', lambda: None)
    monkeypatch.setattr(webview2, 'message', lambda *a, **k: False)
    monkeypatch.setattr(webview2, 'can_box', lambda: False)
    app_main.run_browser(None, None, open_browser=False)
    monkeypatch.setattr(webview2, 'can_box', lambda: True)
    app_main.run_browser(None, None, open_browser=False)
    assert Server.waited == ['forever', 'box']


# --- the message box -------------------------------------------------------------------------------------------------
def test_the_box_is_the_desktops_own_tool():
    def both(tool):
        return '/usr/bin/' + tool
    kde = webview2.box_command('Overtime', 'Add it?', ask=True, system='linux', which=both,
                               env={'XDG_CURRENT_DESKTOP': 'KDE'})
    assert kde == ['kdialog', '--title', 'Overtime', '--yesno', 'Add it?']
    gnome = webview2.box_command('Overtime', 'Done.', info=True, system='linux', which=both, env={})
    assert gnome[:2] == ['zenity', '--info'] and gnome[-2:] == ['--text', 'Done.'] and '--no-markup' in gnome
    only_k = webview2.box_command('Overtime', 'Bad.', system='linux', which=lambda t: t == 'kdialog' and t, env={})
    assert only_k == ['kdialog', '--title', 'Overtime', '--error', 'Bad.']
    assert webview2.box_command('Overtime', 'x', system='linux', which=lambda t: None, env={}) is None


def test_the_macos_box_escapes_what_applescript_reads():
    cmd = webview2.box_command('Overtime', 'say "hi" ' + SLASH + ' there', ask=True, system='darwin')
    assert cmd[:2] == ['osascript', '-e']
    assert 'display dialog "say ' + SLASH + '"hi' + SLASH + '" ' + SLASH * 2 + ' there"' in cmd[2]
    assert 'buttons {"No", "Yes"}' in cmd[2]


@pytest.mark.parametrize('system, code, out, ask, want', [
    ('linux', 0, '', True, True), ('linux', 1, '', True, False), ('linux', 0, '', False, False),
    ('darwin', 0, 'button returned:Yes', True, True), ('darwin', 0, 'button returned:No', True, False)])
def test_yes_is_read_from_the_tool(system, code, out, ask, want):
    def run(cmd, **kw):
        assert 'env' in kw                      # the system's libraries, not the app's
        return subprocess.CompletedProcess(cmd, code, out, '')
    assert webview2._box('T', 'x', ask, False, run=run, system=system, which=lambda t: t) is want


def test_no_tool_or_a_failing_one_prints_and_answers_no(capsys):
    def broken(cmd, **kw):
        raise OSError('no display')
    assert webview2._box('Title', 'the text', True, False, run=broken, system='linux', which=lambda t: t) is False
    assert webview2._box('Title', 'the text', True, False, run=None, system='linux', which=lambda t: None) is False
    assert capsys.readouterr().out.count('the text') == 2


# --- the app menu ----------------------------------------------------------------------------------------------------
def test_only_a_linux_appimage_is_offered_the_app_menu(tmp_path):
    image = tmp_path / 'Overtime NHL19.AppImage'
    image.write_bytes(b'x')
    env = {'APPIMAGE': str(image)}
    assert desktopentry.appimage(env, 'linux') == os.path.abspath(str(image))
    assert desktopentry.appimage(env, 'darwin') is None and desktopentry.appimage({}, 'linux') is None
    assert desktopentry.appimage({'APPIMAGE': str(tmp_path / 'gone')}, 'linux') is None


def test_the_entry_names_the_file_as_the_spec_wants():
    text = desktopentry.text('/home/deck/My Games/Overtime $5 100%.AppImage')
    assert 'Exec="/home/deck/My Games/Overtime ' + SLASH + '$5 100%%.AppImage"' in text.splitlines()
    assert text.splitlines()[:3] == ['[Desktop Entry]', 'Type=Application', 'Name=Overtime Roster']
    assert 'Terminal=false' in text


def test_yes_writes_the_entry_and_the_icon_and_is_asked_once(tmp_path):
    env = {'XDG_DATA_HOME': str(tmp_path / 'data')}
    icon = tmp_path / 'app.png'
    icon.write_bytes(b'png')
    exe = '/apps/Overtime.AppImage'
    assert desktopentry.wanted(exe) is True and desktopentry.wanted(None) is False
    assert desktopentry.answer(True, exe, str(icon), env) is True
    with open(desktopentry.entry_path(env), encoding='utf-8') as f:
        assert 'Exec="/apps/Overtime.AppImage"' in f.read()
    with open(desktopentry.icon_path(env), 'rb') as f:
        assert f.read() == b'png'
    assert desktopentry.wanted(exe) is False
    assert desktopentry.refresh(exe, str(icon), env) is False                   # nothing moved
    assert desktopentry.refresh('/elsewhere/Overtime.AppImage', str(icon), env) is True
    with open(desktopentry.entry_path(env), encoding='utf-8') as f:
        assert 'Exec="/elsewhere/Overtime.AppImage"' in f.read()


def test_no_is_remembered_and_writes_nothing(tmp_path):
    env = {'XDG_DATA_HOME': str(tmp_path / 'data')}
    assert desktopentry.answer(False, '/apps/Overtime.AppImage', None, env) is False
    assert not os.path.exists(desktopentry.entry_path(env))
    assert desktopentry.wanted('/apps/Overtime.AppImage') is False
    assert desktopentry.refresh('/apps/Overtime.AppImage', None, env) is False


def test_steamos_is_read_from_os_release(tmp_path):
    deck = tmp_path / 'os-release'
    deck.write_text('NAME="SteamOS"\nID=steamos\nID_LIKE=arch\n')
    ubuntu = tmp_path / 'ubuntu'
    ubuntu.write_text('NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\n')
    assert desktopentry.steamos(str(deck)) is True and desktopentry.steamos(str(ubuntu)) is False
    assert desktopentry.steamos(str(tmp_path / 'none')) is False


# --- the first-open offers -------------------------------------------------------------------------------------------
class Host:
    def __init__(self):
        self.lines = []

    def log(self, text):
        self.lines.append(text)


def test_first_open_offers_the_app_menu_once_with_the_decks_steps(tmp_path, monkeypatch):
    data = str(tmp_path / 'data')
    asked = []
    monkeypatch.setattr(desktopentry, 'appimage', lambda: '/apps/Overtime.AppImage')
    monkeypatch.setattr(desktopentry, 'steamos', lambda: True)
    monkeypatch.setattr(desktopentry, 'data_home', lambda env=None: data)
    monkeypatch.setattr(preflight, 'cached', lambda system=None: [])
    host = Host()
    app_main.first_open(host, ask=lambda title, text, ask=False: asked.append(text) or True, wait=lambda s: True)
    assert len(asked) == 1 and 'Add a Non-Steam Game' in asked[0]
    assert host.lines == ['Overtime Roster is in the app menu.']
    assert os.path.isfile(os.path.join(data, 'applications', desktopentry.ENTRY))
    app_main.first_open(host, ask=lambda *a, **k: pytest.fail('asked twice'), wait=lambda s: True)


def test_first_open_offers_rosetta_on_an_apple_chip(monkeypatch):
    rows = [{'key': 'rosetta', 'ok': False, 'text': 'It needs Rosetta.', 'fix': 'install_rosetta'}]
    ran = []
    monkeypatch.setattr(desktopentry, 'appimage', lambda: None)
    monkeypatch.setattr(preflight, 'cached', lambda system=None: rows)
    monkeypatch.setattr(preflight, 'install_rosetta', lambda: ran.append(1) or True)
    host = Host()
    app_main.first_open(host, ask=lambda title, text, ask=False: 'It needs Rosetta.' in text, wait=lambda s: True)
    assert ran == [1] and host.lines == ['Rosetta is installed.']


def test_first_open_waits_for_the_page_and_never_raises(monkeypatch):
    monkeypatch.setattr(desktopentry, 'appimage', lambda: pytest.fail('looked before the page was up'))
    app_main.first_open(Host(), ask=None, wait=lambda s: False)

    def boom():
        raise RuntimeError('broken')
    monkeypatch.setattr(desktopentry, 'appimage', boom)
    app_main.first_open(Host(), ask=None, wait=lambda s: True)


def test_windows_ends_as_python_ends_it():
    assert app_main.leave(3, system='win32', end=lambda code: pytest.fail('the process was ended by hand')) == 3


def test_a_page_call_stuck_after_the_window_closed_does_not_keep_the_app_alive():
    stuck, work, ended = threading.Event(), threading.Event(), []
    call = threading.Thread(target=stuck.wait, name='Thread-54 (_call)')           # pywebview's, waits for ever
    job = threading.Thread(target=lambda: (time.sleep(0.2), work.set()), name='save')  # the app's own, ends by itself
    call.start()
    job.start()
    try:
        assert app_main.leave(0, grace=0.1, system='darwin', end=ended.append) == 0
        assert ended == [0] and work.is_set() and call.is_alive()      # the job was waited for, the stuck call was not
    finally:
        stuck.set()
        call.join()
