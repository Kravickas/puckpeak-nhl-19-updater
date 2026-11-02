"""The app's remembered choices (settings.json in %APPDATA%\\OvertimeRoster)."""
import json

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
    try:
        with open(paths.app_dir(FILE), 'w', encoding='utf-8') as f:
            json.dump(values, f, indent=1)
        return True
    except OSError:
        return False
