"""Entry point of OvertimeNHL19.exe (windowed: no console): the window, or --selftest / --update."""
import multiprocessing
import os
import sys

multiprocessing.freeze_support()                    # a texture worker process (workers.ordered) runs its job, not the app

from overtime_roster.window import startup

startup.mark('python')                              # the bootloader has unpacked the exe and started Python
from overtime_roster.window import main as window  # noqa: E402

startup.mark('imports')
if sys.stdout is None or sys.stderr is None:        # a windowed exe has nowhere to print
    window.HEADLESS = True
    sys.stdout = sys.stdout or open(os.devnull, 'w', encoding='utf-8')
    sys.stderr = sys.stderr or open(os.devnull, 'w', encoding='utf-8')

sys.exit(window.entry())
