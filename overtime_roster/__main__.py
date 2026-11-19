"""python -m overtime_roster [--browser] [--port N] [--no-open] [--game-dir DIR] [--save-dir DIR]"""
import argparse
import sys

from . import APP_NAME, VERSION


def main(argv=None):
    p = argparse.ArgumentParser(prog='overtime_roster', description=f'{APP_NAME} {VERSION}: NHL 19 roster editor')
    p.add_argument('--browser', action='store_true', help='run as a local web page in your browser')
    p.add_argument('--port', type=int, default=0, help='port for --browser (default: any free port)')
    p.add_argument('--no-open', action='store_true', help="with --browser: don't open the browser, print the URL")
    p.add_argument('--game-dir', help='the NHL 19 game folder (CUSA11126, with eboot.bin)')
    p.add_argument('--save-dir', help="shadPS4's save folder for NHL 19 (...\\savedata\\CUSA11126)")
    a = p.parse_args(argv)
    from .window.main import main as run
    return run(browser=a.browser, port=a.port, open_browser=not a.no_open, game_dir=a.game_dir,
               save_dir=a.save_dir)


if __name__ == '__main__':
    from .window.main import leave
    sys.exit(leave(main()))
