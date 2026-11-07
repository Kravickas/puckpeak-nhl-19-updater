"""Read any NHL 19 save folder (Franchise, Season, Be a Pro, rosters) for checks; never writes.

A save folder holds an EA SaveLoad container (`savefile`): INDEX + DATA with named files. Files whose payload is
packed (u8 1 + LZ4 frame + u32 size) are unpacked; an unpacked file that starts with the t3db magic is a database
(possibly followed by a trailer, as in roster saves), parsed with the schema when one is given.

Franchise / Season saves (`BeAGM<n>`, run x1-20261016): the unpacked file is itself a chain of chunks, each u8 1 +
LZ4 frame (no size word), then raw bytes. Of the 4 chunks of a Franchise save the last one is the league database
(leagueteams, leaguescheduletable, leaguerostertable, ...: tables with index definitions, see tdb).
"""
import json
import os
import struct
from dataclasses import dataclass, field

from . import lz4f, savefile, tdb

DB_MAGIC = b'DB\x00\x08'


@dataclass
class SaveFile:
    name: str
    raw: bytes  # payload as stored
    data: bytes  # unpacked payload (== raw when not packed)
    db: object = None  # tdb.Database when `data` holds one
    trailer: bytes = b''
    chunks: list = field(default_factory=list)  # decoded LZ4 chunks of a chained file (Franchise / Season)
    chunk_dbs: list = field(default_factory=list)  # tdb.Database per database chunk
    rest: bytes = b''  # raw bytes after the last chunk

    @property
    def text(self):
        try:
            return self.data.decode('utf-8')
        except UnicodeDecodeError:
            return None


@dataclass
class ModeSave:
    folder: str
    name: str
    files: dict = field(default_factory=dict)  # name -> SaveFile

    @property
    def databases(self):
        out = {n: f.db for n, f in self.files.items() if f.db is not None}
        for n, f in self.files.items():
            for k, db in enumerate(f.chunk_dbs):
                out[f'{n}#{k}'] = db
        return out

    @property
    def meta(self):
        f = self.files.get('__SaveLoadMetaData')
        try:
            return json.loads(f.text) if f and f.text else {}
        except ValueError:
            return {}

    def table(self, schema, name):
        """The first table called `name` (long name) in any database of this save, else None."""
        short = schema.by_name(name).short
        for db in self.databases.values():
            if short in db:
                return db[short]
        return None


def _database(data, schema):
    if data[:4] != DB_MAGIC or len(data) < 12:
        return None, b''
    size = struct.unpack_from('<I', data, 8)[0]
    if size > len(data):
        return None, b''
    try:
        return tdb.Database.parse(data[:size], schema), data[size:]
    except tdb.FormatError:
        return None, b''


def chunks(data):
    """Split a chained file (u8 1 + LZ4 frame, repeated) into decoded chunks and the raw rest."""
    out, pos = [], 0
    while data[pos:pos + 1] == b'' and data[pos + 1:pos + 5] == struct.pack('<I', lz4f.MAGIC):
        chunk, n = lz4f.decode(data[pos + 1:])
        out.append(chunk)
        pos += 1 + n
    return out, data[pos:]


def read(folder, schema=None):
    name = os.path.basename(os.path.normpath(folder))
    out = ModeSave(folder, name)
    for e in savefile.read_folder(folder):
        data = savefile.unpack(e.payload) if savefile.is_packed(e.payload) else e.payload
        db, trailer = _database(data, schema)
        f = SaveFile(e.name, e.payload, data, db, trailer)
        if db is None and savefile.is_packed(data):
            f.chunks, f.rest = chunks(data)
            f.chunk_dbs = [d for d in (_database(c, schema)[0] for c in f.chunks) if d is not None]
        out.files[e.name] = f
    return out


def list_saves(save_dir):
    """Folder names in a title's save dir that hold a SaveLoad container. sce_* folders are shadPS4's own (newer
    builds keep save backups next to the saves as sce_bu_<name>), never a save."""
    if not os.path.isdir(save_dir):
        return []
    return sorted(n for n in os.listdir(save_dir)
                  if not n.startswith('sce_') and os.path.isfile(os.path.join(save_dir, n, 'INDEX')))


def summary(folder, schema=None):
    """One line per file: name, size, and the table count / non-empty tables of a database."""
    save = read(folder, schema)
    lines = []
    for f in save.files.values():
        for k, db in enumerate(f.chunk_dbs):
            used = [(t.meta.name if t.meta else t.tag, t.count) for t in db.tables if t.count]
            lines.append(f'{f.name}#{k}: database chunk, {len(db.tables)} tables, {len(used)} with rows')
            lines += [f'    {n}: {c}' for n, c in used]
        if f.chunks:
            lines.append(f'{f.name}: {len(f.chunks)} chunks {[len(c) for c in f.chunks]}, {len(f.rest):,} raw bytes after')
            continue
        if f.db is None:
            kind = 'text' if f.text is not None and len(f.data) < 4096 else 'bytes'
            lines.append(f'{f.name}: {len(f.data):,} {kind}')
            continue
        used = [(t.meta.name if t.meta else t.tag, t.count) for t in f.db.tables if t.count]
        lines.append(f'{f.name}: database, {len(f.db.tables)} tables, {len(used)} with rows')
        lines += [f'    {n}: {c}' for n, c in used]
    return lines
