"""The online roster file (CMS File_Type roster_h2h): the rosterupdate tables of a database and the CRC the game
compares. Shared by the server (overtime_server/rosters.py, the published roster) and the app (a lobby host's own
roster, overtime_roster/app/hostroster.py). docs/notes/roster-download.md.
"""
from overtime_core import gamefiles, rostercrc

SAVEGROUP = 'rosterupdate'
# The game's own roster file; its table order is used for the files Overtime serves.
ROSTER_FILE = 'nhl/data/common/gamemodes/roster/initial_experience.db'
# The game walks the group in nhl_game-meta.xml order (run 2026-10-15n: only that value made roster_h2h current).
GAME_ORDER = 'meta'


def game_orders(db, schema, initial):
    """Candidate orders (table tags) in which the game walks the roster savegroup for CRC value 0."""
    group = [t for t in db.tables if t.meta and SAVEGROUP in t.meta.savegroups]
    return {'initial': [t.tag for t in initial.tables],
            'database': [t.tag for t in group],
            'meta': [m.short for m in schema.tables.values() if SAVEGROUP in m.savegroups],
            'name': [t.tag for t in sorted(group, key=lambda t: t.name)],
            'tag': sorted(t.tag for t in group)}


def build(db, schema, initial, order=GAME_ORDER):
    """(roster file bytes, CRC string) for the rosterupdate tables of `db`."""
    orders = game_orders(db, schema, initial)
    blob = db.subset(SAVEGROUP, order=orders['initial']).to_bytes()
    return blob, rostercrc.roster_crc(db.subset(SAVEGROUP, order=orders[order]))


def initial_roster(game_dir):
    """The game's own roster file bytes (its table order is the order of the files Overtime serves)."""
    return gamefiles.read_latest(game_dir, ROSTER_FILE, False)[0]
