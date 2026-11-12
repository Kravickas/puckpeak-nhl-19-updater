"""Find NHL 19 data in the user's own game folder (read only).

The game mounts `databigs/*.big`; for a path present in several archives the highest-numbered `patch_*`
archive wins (`patch_inxp_56.big` holds the current `nhl_game.db` in v1.60).

shadPS4 can keep the update beside the base game, in `<base>-UPDATE` or `<base>-patch`, and serves the two as one game
(a file in the update folder wins). `roots` finds the pair from either folder, and `archives`, `served`, `rel` and
`locate` see the game as the emulator does. The mods overlay is `<base>-mods`.
"""
import os
import re

from .eb import EbArchive

DB_PATH = 'nhl/data/common/gamemodes/database/t3db/nhl_game.db'
META_PATH = 'nhl/data/common/gamemodes/database/t3db/nhl_game-meta.xml'
# the game's own roster file: the 41 rosterupdate tables (players, teams, calendars), laid over nhl_game.db's
ROSTER_PATH = 'nhl/data/common/gamemodes/roster/initial_experience.db'


def _order(name):
    """Sort key: base archives first, then patches by number."""
    m = re.match(r'(patch_)?\w+?_(\d+)\.big$', name)
    return (1 if m and m.group(1) else 0, int(m.group(2)) if m else -1, name)


UPDATE_SUFFIXES = ('-UPDATE', '-patch')     # shadPS4's names for an update kept beside the base game


def _is_game(folder):
    return os.path.isfile(os.path.join(folder, 'sce_sys', 'param.sfo'))


def roots(game_dir):
    """(base folder, update folder or None) for the game folder set: the base or its `-UPDATE` / `-patch` sibling.
    An update folder with no base beside it is a whole game on its own. With both siblings beside the base, the
    update is the one shadPS4 mounts (`-UPDATE`), whichever folder was picked."""
    folder = os.path.normpath(os.path.abspath(game_dir))
    name = os.path.basename(folder)
    for suffix in UPDATE_SUFFIXES:
        if name.lower().endswith(suffix.lower()) and len(name) > len(suffix):
            base = os.path.join(os.path.dirname(folder), name[:-len(suffix)])
            if not _is_game(base):
                return folder, None
            return base, next((base + s for s in UPDATE_SUFFIXES if _is_game(base + s)), folder)
    for suffix in UPDATE_SUFFIXES:
        if _is_game(folder + suffix):
            return folder, folder + suffix
    return folder, None


def mods_dir(game_dir):
    """shadPS4's mods overlay for this game: `<base folder>-mods`."""
    return roots(game_dir)[0] + '-mods'


def rel(game_dir, path):
    """`path` (a file of the base or the update folder) as a game path, 'databigs/x.big'."""
    path = os.path.abspath(path)
    for root in roots(game_dir):
        if root and os.path.normcase(path).startswith(os.path.normcase(root) + os.sep):
            return os.path.relpath(path, root).replace('\\', '/')
    return os.path.relpath(path, roots(game_dir)[0]).replace('\\', '/')


def locate(game_dir, game_path):
    """The file the game reads for `game_path` (mods aside): the update's copy when it has one, else the base's
    (which need not exist)."""
    base, update = roots(game_dir)
    parts = game_path.replace('\\', '/').split('/')
    if update and os.path.exists(os.path.join(update, *parts)):
        return os.path.join(update, *parts)
    return os.path.join(base, *parts)


def archives(game_dir):
    """The game's archives in mount order. With an update folder its archives join the base's (same name: the
    update's copy)."""
    base, update = roots(game_dir)
    found = {}
    for root in (base, update):
        if root is None or (root == update and not os.path.isdir(os.path.join(root, 'databigs'))):
            continue
        big_dir = os.path.join(root, 'databigs')
        for n in os.listdir(big_dir):
            if n.endswith('.big'):
                found[n.lower()] = os.path.join(big_dir, n)
    return sorted(found.values(), key=lambda p: _order(os.path.basename(p)))


def served(game_dir, archive):
    """The file the game opens for `archive` under shadPS4: `<base folder>-mods/<same path>` when the Overtime
    patch (or another mod) put one there, else the game's own."""
    alt = os.path.join(mods_dir(game_dir), *rel(game_dir, archive).split('/'))
    return alt if os.path.isfile(alt) else archive


def read_latest(game_dir, path, mods=False):
    """Bytes of `path` from the archive that wins, and that archive's file name. With `mods`, as the game sees it
    with the mods overlay (overtime_core.overlay): an archive copy in `<game folder>-mods/` replaces the game's."""
    found = None
    for big in archives(game_dir):
        with EbArchive(served(game_dir, big) if mods else big) as arc:
            if path in arc.entries:
                found = (arc.read(path), os.path.basename(big))
    if found is None:
        raise FileNotFoundError(f"{path} not in {game_dir}")
    return found


def winning(game_dir):
    """{game path: archive} of the game's own archives, the copy that wins (the last mounted)."""
    return winning_index(game_dir)[0]


def winning_index(game_dir):
    """({game path: archive}, {game path: its stored bytes there}) of the copies that win: winning() with the sizes
    the archives' tables already hold. Patch reads it once and hands it to every step that makes textures (and to its
    progress, which weighs a texture by its size), instead of each step listing every archive again."""
    where, sizes = {}, {}
    for big in archives(game_dir):
        with EbArchive(big) as arc:
            for p, (_off, size) in arc.entries.items():
                where[p] = big
                sizes[p] = size
    return where, sizes


def default_database(game_dir, mods=False):
    return read_latest(game_dir, DB_PATH, mods)


def schema_xml(game_dir):
    return read_latest(game_dir, META_PATH)
