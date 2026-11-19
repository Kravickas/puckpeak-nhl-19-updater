"""Windows: is Microsoft's WebView2 Runtime there (it draws the window)? Windows 11 and an updated Windows 10 have it;
an old Windows 10 may not, and then the app runs in the browser instead. Also the app's plain message box on every
system: Windows' own, the desktop's on Linux (kdialog or zenity, whichever is installed), AppleScript's on macOS.
Standard library only."""
import os
import shutil
import subprocess
import sys

CLIENT = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
DOWNLOAD = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"      # the Evergreen Bootstrapper


def available():
    """True when the runtime is installed (or when this is not Windows: the question does not arise).
    OVERTIME_NO_WEBVIEW2=1 answers False (to try the browser fallback on a PC that has it)."""
    if os.environ.get('OVERTIME_NO_WEBVIEW2') == '1':
        return False
    if os.name != 'nt':
        return True
    import winreg
    places = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node" + CLIENT[len("SOFTWARE"):]),
              (winreg.HKEY_LOCAL_MACHINE, CLIENT), (winreg.HKEY_CURRENT_USER, CLIENT)]
    for root, key in places:
        try:
            with winreg.OpenKey(root, key) as k:
                version, _kind = winreg.QueryValueEx(k, 'pv')
                if version and version != '0.0.0.0':
                    return True
        except OSError:
            continue
    return False


def _applescript(text):
    """`text` as an AppleScript string: in double quotes, its own quotes and backslashes escaped."""
    slash = chr(92)
    return '"' + text.replace(slash, slash * 2).replace('"', slash + '"') + '"'


def box_command(title, text, ask=False, info=False, system=None, which=shutil.which, env=None):
    """The command that shows the box off Windows, or None when the system has no tool for it. Linux: kdialog on a KDE
    desktop (a Steam Deck), else zenity, else whichever is there; both answer Yes with exit code 0. macOS: osascript,
    which prints the pressed button."""
    system = system or sys.platform
    env = os.environ if env is None else env
    if system == 'darwin':
        buttons = '{"No", "Yes"} default button "Yes"' if ask else '{"OK"} default button "OK"'
        icon = 'caution' if ask else ('note' if info else 'stop')
        return ['osascript', '-e', f'display dialog {_applescript(text)} with title {_applescript(title)} '
                                   f'buttons {buttons} with icon {icon}']
    tools = ['zenity', 'kdialog']
    if 'kde' in (env.get('XDG_CURRENT_DESKTOP') or '').lower():
        tools.reverse()
    tool = next((t for t in tools if which(t)), None)
    if tool == 'kdialog':
        return ['kdialog', '--title', title, '--yesno' if ask else ('--msgbox' if info else '--error'), text]
    if tool == 'zenity':
        kind = '--question' if ask else ('--info' if info else '--error')
        return ['zenity', kind, '--title', title, '--no-markup', '--width', '460', '--text', text]
    return None


def can_box(system=None, which=shutil.which):
    """Can message() show a box that stays up until it is answered? Not on a Linux desktop with neither tool."""
    system = system or sys.platform
    return system == 'win32' or box_command('', '', system=system, which=which) is not None


def _box(title, text, ask, info, run=subprocess.run, system=None, which=shutil.which):
    """The box off Windows: True for Yes. With no tool (or no desktop) the text goes to the console and the answer
    is No."""
    command = box_command(title, text, ask, info, system, which)
    if command is None:
        print(f"{title}\n{text}")
        return False
    from ..app import selfupdate
    try:    # the system's own libraries for the system's tool, not the app's bundled ones
        done = run(command, capture_output=True, text=True, env=selfupdate.clean_environment())
    except (OSError, subprocess.SubprocessError):
        print(f"{title}\n{text}")
        return False
    if command[0] == 'osascript':
        return ask and 'button returned:Yes' in (done.stdout or '')
    return ask and done.returncode == 0


def message(title, text, ask=False, info=False):
    """A plain message box (no window toolkit needed). With `ask`: Yes / No, True for Yes."""
    if os.name != 'nt':
        return _box(title, text, ask, info)
    import ctypes
    if ask:
        flags = 0x00000004 | 0x00000030         # MB_YESNO | MB_ICONWARNING
    else:
        flags = 0x00000040 if info else 0x00000010      # MB_ICONINFORMATION, or MB_ICONERROR
    return ctypes.windll.user32.MessageBoxW(None, text, title, flags | 0x00010000) == 6     # MB_SETFOREGROUND; IDYES
