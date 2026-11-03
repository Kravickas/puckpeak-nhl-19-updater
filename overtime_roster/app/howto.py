"""HOW-TO-INSTALL.txt for a roster exported to a folder (install.TARGET_FOLDER).

The folder holds the shadPS4 user-data layout, so copying its `home` folder over the player's own `home` folder
installs the roster. Paths per system: docs/notes/export-folder.md.
"""
import sys

DATA_DIR = 'shadPS4 data'
SAVE_PARTS = ('home', '1000', 'savedata', 'CUSA11126')
FILE = 'HOW-TO-INSTALL.txt'

WHERE = [
    ('Windows', r'%APPDATA%\shadPS4  (in Explorer: paste that into the address bar)'),
    ('Linux', '$XDG_DATA_HOME/shadPS4, or ~/.local/share/shadPS4 when XDG_DATA_HOME is not set'),
    ('macOS', '~/Library/Application Support/shadPS4'),
]


def save_parts(title=None):
    """The save folder's path in shadPS4's user data, named by the game's title id (CUSA11126; Europe CUSA11116)."""
    return SAVE_PARTS[:-1] + (title or SAVE_PARTS[-1],)


def _own_first():
    here = {'win32': 'Windows', 'darwin': 'macOS'}.get(sys.platform, 'Linux')
    return sorted(WHERE, key=lambda w: w[0] != here)


def text(folder_name, name, title=None):
    slot = int(folder_name[len('RosterCustom'):]) + 1
    parts = '/'.join(save_parts(title))
    where = '\n'.join(f'  {system}: {path}' for system, path in _own_first())
    return f"""Overtime Roster: "{name}"

This folder holds one NHL 19 custom roster save, {folder_name}, for shadPS4. Nothing was changed on the PC that made it.

1. Close shadPS4.
2. Find shadPS4's user data folder on the PC that runs the game:
{where}
  If you start shadPS4 with a "user" folder next to where you launch it, that folder is the one.
3. Copy the folder
     {DATA_DIR}/{parts}/{folder_name}
   into
     <user data folder>/{parts}/
   If {folder_name} is already there, do not copy over it (that would replace a roster you may want) and do not
   rename the folder: a renamed copy shows in the game's list but does not load. Make the folder again in
   Overtime Roster with "Slot on the other PC" set to a slot that is free there (RosterCustom0 to RosterCustom14).
4. Start NHL 19. In Rosters > Active Rosters, pick "Custom Roster {slot}" (the number follows the folder name,
   RosterCustom0 is Custom Roster 1).

The game lists RosterCustom0 to RosterCustom14 only.
"""
