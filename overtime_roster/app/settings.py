"""The app's remembered choices (settings.json in %APPDATA%\\OvertimeRoster)."""
import json

from overtime_core import durable

from . import paths

FILE = 'settings.json'


def load():
    try:
        with open(paths.app_dir(FILE), encoding='utf-8') as f:
            values = json.load(f)
            return values if isinstance(values, dict) else {}
    except (OSError, ValueError):
        return {}


def save(values):
    """False when the file could not be written."""
    path = paths.app_dir(FILE)
    try:
        with open(path + '.tmp', 'w', encoding='utf-8') as f:     # whole or not at all, even on a power cut
            json.dump(values, f, indent=1)
        durable.replace(path + '.tmp', path)
        return True
    except OSError:
        return False
