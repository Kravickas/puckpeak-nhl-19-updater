"""A lobby host's own roster for Online Versus (docs/notes/lobby.md "Host roster").

The roster file the game downloads online (CMS roster_h2h) is built from the roster open in Overtime Roster (with
the host's My edits and lines, saved or not); with none open, from the database the Overtime patch serves (the
default roster of the last Patch). The host's game and the guest's game both download it and search with one CRC.
"""
from overtime_core import h2h, overlay, tdb


class HostRosterError(Exception):
    pass


def served_database(game_dir):
    """The nhl_game.db bytes the patched game serves, or None."""
    state = overlay.status(game_dir)
    return overlay._current_database(game_dir, state) if 'database' in (state.get('layers') or {}) else None


def host_roster(game_dir, schema, open_db=None):
    """(roster_h2h bytes, CRC, where it came from): the open roster `open_db` (a tdb.Database), else the served one.
    Raises HostRosterError with neither."""
    initial = tdb.Database.parse(h2h.initial_roster(game_dir), schema)
    wanted = [m.short for m in schema.tables.values() if h2h.SAVEGROUP in m.savegroups]
    if open_db is not None and all(t in open_db for t in wanted):    # else (a part roster) the served one
        blob, crc = h2h.build(open_db, schema, initial)
        return blob, crc, 'open'
    raw = served_database(game_dir)
    if raw is None:
        raise HostRosterError('Open your roster in Overtime Roster (or press Patch on the Game patch tab) first.')
    blob, crc = h2h.build(tdb.Database.parse(raw, schema), schema, initial)
    return blob, crc, 'patch'
