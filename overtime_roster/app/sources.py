"""The rosters the app can open: the game's own default roster (from the user's `databigs`) and the roster saves
in the emulator's save folder. The schema (table and field names) always comes from the user's game files.
Also where the owner's local NHL 27 pack is (nhl27_pack: tools/build_datapack.py writes it; it never ships)."""
import dataclasses
import datetime
import os
from dataclasses import dataclass, field

from overtime_core import gamefiles, nhl27, tdb
from overtime_core.schema import parse_schema

from . import savegame

ROSTER_FILE = gamefiles.ROSTER_PATH
GAME_ID = 'game:default'


@dataclass
class Source:
    id: str
    kind: str  # 'game' or 'save'
    name: str
    path: str
    meta: str = ''
    usable: bool = True
    problem: str = ''
    info: dict = field(default_factory=dict)

    def view(self, selected=None):
        return {'id': self.id, 'kind': self.kind, 'name': self.name, 'path': self.path, 'meta': self.meta,
                'usable': self.usable, 'problem': self.problem, 'selected': self.id == selected}


class GameData:
    """The user's game files, read once: schema, the full default database, the shipped roster file's order."""

    def __init__(self, game_dir):
        self.game_dir = game_dir
        self._schema = self._raw = self._order = None
        self.db_archive = ''

    @property
    def ok(self):
        return os.path.isdir(os.path.join(self.game_dir, 'databigs'))

    def schema(self):
        if self._schema is None:
            xml, _ = gamefiles.schema_xml(self.game_dir)
            self._schema = parse_schema(xml)
        return self._schema

    def default_bytes(self):
        if self._raw is None:
            self._raw, self.db_archive = gamefiles.default_database(self.game_dir)
        return self._raw

    def default_db(self):
        """A fresh parse of the game's database (edits never touch the cached bytes)."""
        return tdb.Database.parse(self.default_bytes(), self.schema())

    def roster_order(self):
        """Table tags of the game's own roster file (initial_experience.db): the order roster files use."""
        if self._order is None:
            raw, _ = gamefiles.read_latest(self.game_dir, ROSTER_FILE)
            self._order = [t.tag for t in tdb.Database.parse(raw, verify=False).tables]
        return self._order


def find(game, save_dir):
    """All sources, the game's default first."""
    out = []
    if game.ok:
        out.append(Source(GAME_ID, 'game', "NHL 19 default roster", game.game_dir,
                          meta='From your game files (databigs, latest patch wins)'))
    else:
        out.append(Source(GAME_ID, 'game', 'NHL 19 default roster', game.game_dir, usable=False,
                          problem='Game files not found: set the NHL 19 folder (the one with databigs).'))
    if os.path.isdir(save_dir):
        for name in sorted(os.listdir(save_dir)):
            folder = os.path.join(save_dir, name)
            if not name.startswith('Roster') or not os.path.isfile(os.path.join(folder, 'INDEX')):
                continue
            out.append(listed(folder))
    return out


_LISTED = {}    # folder -> (listing_key, Source): a save is peeked again only when its INDEX or DATA changed


def listing_key(folder):
    """(size, mtime_ns) of the folder's INDEX and DATA: what decides whether a listed save must be read again."""
    out = []
    for part in ('INDEX', 'DATA'):
        try:
            st = os.stat(os.path.join(folder, part))
            out += [st.st_size, st.st_mtime_ns]
        except OSError:
            out += [None, None]
    return tuple(out)


def listed(folder):
    """The Source tab's entry for a roster save folder, from its metadata and database header (savegame.peek): the
    roster itself is unpacked (and its LZ4 checksum checked) only when it is opened (load)."""
    key = listing_key(folder)
    hit = _LISTED.get(folder)
    if hit is None or hit[0] != key:
        hit = _LISTED[folder] = (key, _list(folder))
    return dataclasses.replace(hit[1], info=dict(hit[1].info))     # a copy: the caller may change it


def _list(folder):
    name = os.path.basename(os.path.normpath(folder))
    try:
        rs = savegame.peek(folder)
    except (OSError, ValueError) as err:
        return Source('save:' + name, 'save', name, folder, usable=False, problem=f'Cannot read: {err}')
    title = rs.meta.get('FileDisplayName') or name
    when = ''
    try:
        when = datetime.datetime.fromtimestamp(int(rs.meta.get('FileModifiedDate', ''))).strftime('%Y-%m-%d %H:%M')
    except (TypeError, ValueError, OSError):
        when = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(folder, 'DATA'))).strftime(
            '%Y-%m-%d %H:%M')
    kind = 'online roster' if name.startswith('RosterOnline') else 'roster save'
    return Source('save:' + name, 'save', title, folder,
                  meta=f'{name} · {kind} · {when} · {rs.db_size // 1024} KB',
                  info={'crc': rs.meta.get('CRCValue', ''), 'folder': name})


NHL27_ENV = 'OVERTIME_NHL27_PACK'
PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_PACKS = os.path.join(PACKAGE, 'packs')  # the exe's data pack only (nhl27.json.gz, numbers and names); picture packs are downloaded
REPO_PACKS = os.path.join(os.path.dirname(PACKAGE), 'packs')


def nhl27_places(cache_dir=None):
    """Where an NHL 27 pack may be, first wins: OVERTIME_NHL27_PACK (`off`: none at all), the app's cache folder,
    the exe's own packs, the repository's packs/ (a source run)."""
    if os.environ.get(NHL27_ENV) == 'off':
        return []
    out = [os.environ[NHL27_ENV]] if os.environ.get(NHL27_ENV) else []
    if cache_dir:
        out.append(os.path.join(cache_dir, nhl27.PACK_NAME))
    out += [os.path.join(BUILD_PACKS, nhl27.PACK_NAME), os.path.join(REPO_PACKS, nhl27.PACK_NAME)]
    return out


def nhl27_pack(cache_dir=None):
    """(pack, path) of the first usable NHL 27 pack (nhl27.load), else (None, '')."""
    for path in nhl27_places(cache_dir):
        if os.path.isfile(path):
            pack = nhl27.load(path)
            if pack is not None:
                return pack, path
    return None, ''


def load(source, game):
    """(tdb.Database, label) for a source."""
    if source.kind == 'game':
        return game.default_db(), 'NHL 19 default roster'
    rs = savegame.read(source.path)
    return tdb.Database.parse(rs.db_bytes, game.schema()), source.name
