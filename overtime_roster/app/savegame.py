"""NHL 19 roster save folders: read them, and write NEW ones (never over an existing folder).

What a roster save looks like (the game's own `RosterOnline0`, written in run 2026-10-15p; docs/notes/roster-app.md):
  <folder>/INDEX, DATA     EA SaveLoad container (overtime_core.savefile) with four files:
      <folder>             u8 1 + LZ4 frame + u32 size; unpacked = t3db database + 18-byte trailer
      __SaveLoadFileInfo   '{\\n"IsBackup":false\\n}'
      __SaveLoadMetaData   JSON; a custom roster the game wrote: {FileCreateDate (ms), FileDisplayName, CRCValue}
      __SaveloadVer        8 bytes (double) + "1.60", padded to 72: 45.0 in RosterOnline0, 46.0 in RosterCustomN
  <folder>/NAME            the folder name (ASCII, no NUL)
  <folder>/sce_sys/param.sfo, icon0.png
Each container file starts with an 8-byte stamp: the save time in nanoseconds since 1970 (u64 little-endian).
Trailer: u32 unknown (not a CRC of the database we could identify), u32 0, u32 database size, u32 0, u16 1.

Run 2026-10-16c: a RosterCustomN with version 45.0 lists as "CORRUPT CUSTOM ROSTER"; with 46.0 it lists and loads,
whatever the table order. The game names it "Custom Roster <N+1>" there (FileDisplayName is not shown).
"""
import json
import os
import re
import shutil
import struct
import time
from dataclasses import dataclass

from overtime_core import durable, lz4f, savefile, sfo

FILE_INFO = b'{\n"IsBackup":false\n}'
VER_PAYLOAD = struct.pack('<d', 45.0) + b'1.60'.ljust(64, b'\0')
CUSTOM_VER_PAYLOAD = struct.pack('<d', 46.0) + b'1.60'.ljust(64, b'\0')
TRAILER = struct.Struct('<IIIIH')
BACKUPS_KEPT = 10       # install.run keeps the newest 10 backups of the save folder
BACKUP_NAME = re.compile(r'^\d{8}-\d{6}$')
META_KEYS = ('FileDisplayName', 'FileCreateDate', 'FileModifiedDate', 'FileDescription', 'CRCValue')


class SaveError(ValueError):
    pass


ACTIVE_SLOT = re.compile(rb'"ActiveRosterSaveSlot"\s*:\s*(-?\d+)')
ACTIVE_TYPE = re.compile(rb'"ActiveRosterType"\s*:\s*"(\w*)"')


@dataclass
class RosterSave:
    folder: str  # path
    name: str  # folder name = slot file name
    db_bytes: bytes
    trailer: bytes
    meta: dict
    entries: list


def split_unpacked(unpacked):
    """(database bytes, trailer bytes) of an unpacked roster payload (database size is at +8 of its header)."""
    if unpacked[:4] != b'DB\x00\x08':
        raise SaveError('the roster file does not hold a t3db database')
    size = struct.unpack_from('<I', unpacked, 8)[0]
    if size > len(unpacked):
        raise SaveError('the roster database is cut short')
    return unpacked[:size], unpacked[size:]


def trailer_for(db_size, template=None):
    """The 18-byte trailer: the template's first word (unknown meaning; 0 or no template: TRAILER_WORD, as the game
    crashes loading a save with 0) with our database size."""
    word = TRAILER.unpack(template)[0] if template and len(template) == TRAILER.size else 0
    return TRAILER.pack(word or TRAILER_WORD, 0, db_size, 0, 1)


def meta_json(meta):
    """The game's metadata layout: one key per line (in `meta` order), values as strings, no spaces."""
    body = ',\n'.join(f'{json.dumps(k)}:{json.dumps(str(v), ensure_ascii=False)}' for k, v in meta.items())
    return ('{\n' + body + '\n}').encode('utf-8')


def read(folder, name=None):
    """A roster save folder (any slot whose own file is a packed t3db). `name`: the slot's name when the folder is
    not named after it yet (a copy being written)."""
    name = name or os.path.basename(os.path.normpath(folder))
    entries = savefile.read_folder(folder)
    by = {e.name: e for e in entries}
    slot = by.get(name)
    if slot is None or not savefile.is_packed(slot.payload):
        raise SaveError(f'{name}: no packed roster file in this save')
    db_bytes, trailer = split_unpacked(savefile.unpack(slot.payload))
    meta = {}
    if '__SaveLoadMetaData' in by:
        try:
            meta = json.loads(by['__SaveLoadMetaData'].payload.decode('utf-8'))
        except ValueError:
            meta = {}
    return RosterSave(folder, name, db_bytes, trailer, meta if isinstance(meta, dict) else {}, entries)


@dataclass
class RosterInfo:
    """What the Source tab lists about a roster save, without unpacking it (savegame.peek)."""
    name: str
    db_size: int
    meta: dict


def peek(folder):
    """The listing facts of a roster save folder, cheaply: its container, metadata and database size (from the
    database header, the first 12 unpacked bytes). The LZ4 checksum is checked only when the save is read in full
    (`read`, when it is opened)."""
    name = os.path.basename(os.path.normpath(folder))
    entries = savefile.read_folder(folder)
    by = {e.name: e for e in entries}
    slot = by.get(name)
    if slot is None or not savefile.is_packed(slot.payload):
        raise SaveError(f'{name}: no packed roster file in this save')
    if len(slot.payload) < 9:
        raise SaveError(f'{name}: the roster file is cut short')
    unpacked = struct.unpack_from('<I', slot.payload, len(slot.payload) - 4)[0]
    head = lz4f.decode_prefix(slot.payload[1:-4], 12)
    if head[:4] != b'DB\x00\x08' or len(head) < 12:
        raise SaveError('the roster file does not hold a t3db database')
    size = struct.unpack_from('<I', head, 8)[0]
    if size > unpacked:
        raise SaveError('the roster database is cut short')
    meta = {}
    if '__SaveLoadMetaData' in by:
        try:
            meta = json.loads(by['__SaveLoadMetaData'].payload.decode('utf-8'))
        except ValueError:
            meta = {}
    return RosterInfo(name, size, meta if isinstance(meta, dict) else {})


def build_container(name, db_bytes, meta, trailer_template=None, ver_payload=CUSTOM_VER_PAYLOAD, stamp_ns=None):
    """(INDEX bytes, DATA bytes) of a roster save holding `db_bytes`; DATA in the game's order."""
    stamp = struct.pack('<Q', stamp_ns if stamp_ns is not None else time.time_ns())
    unpacked = db_bytes + trailer_for(len(db_bytes), trailer_template)
    payload = b'\x01' + lz4f.encode_compressed(unpacked) + struct.pack('<I', len(unpacked))
    files = [savefile.SaveEntry('__SaveLoadFileInfo', stamp, FILE_INFO),
             savefile.SaveEntry('__SaveloadVer', stamp, ver_payload),
             savefile.SaveEntry('__SaveLoadMetaData', stamp, meta_json(meta)),
             savefile.SaveEntry(name, stamp, payload)]
    index, data = savefile.build(files)
    rec = savefile.NAME_LEN + 16 + 32  # one INDEX record per single-extent file
    recs = [index[i * rec:(i + 1) * rec] for i in range(len(files))]
    order = [3, 0, 2, 1]  # the game lists the slot file first, then FileInfo, MetaData, Ver
    return b''.join(recs[i] for i in order), data


def check_container(name, index, data, db_bytes):
    """Re-read a built container; raises SaveError unless it gives back exactly `db_bytes`."""
    entries = savefile.parse(index, data)
    by = {e.name: e for e in entries}
    if set(by) != {name, '__SaveLoadFileInfo', '__SaveLoadMetaData', '__SaveloadVer'}:
        raise SaveError(f'container files: {sorted(by)}')
    got, trailer = split_unpacked(savefile.unpack(by[name].payload))
    if got != db_bytes:
        raise SaveError('the container does not give back the same database bytes')
    if len(trailer) != TRAILER.size or TRAILER.unpack(trailer)[2] != len(db_bytes) or not TRAILER.unpack(trailer)[0]:
        raise SaveError('bad roster trailer')
    json.loads(by['__SaveLoadMetaData'].payload.decode('utf-8'))
    return entries


CUSTOM, SLOTS = 'RosterCustom', 15  # the game lists RosterCustom0-14 only (run 2026-10-19): a 16th never shows
FULL = (f'The game shows only {SLOTS} custom rosters ({CUSTOM}0-{SLOTS - 1}) and all are taken: delete one in the '
        'game, or overwrite one of them.')


def active_roster(save_dir):
    """The save folder of the roster NHL 19 plays ('RosterCustom2'), read from the profile save (ActiveRosterType +
    ActiveRosterSaveSlot); None for the game's own roster or no profile. Only the game's Rosters > Active Rosters sets
    it: the profile is the user's save, and the online roster both players of a match need is chosen there too."""
    try:
        entries = savefile.read_folder(os.path.join(save_dir, 'Profile0'))
    except (OSError, ValueError):
        return None
    for e in entries:
        raw = savefile.unpack(e.payload) if savefile.is_packed(e.payload) else e.payload
        slot, kind = ACTIVE_SLOT.search(raw), ACTIVE_TYPE.search(raw)
        if slot and kind and kind.group(1) and int(slot.group(1)) >= 0:
            return f'Roster{kind.group(1).decode()}{int(slot.group(1))}'
    return None


def roster_label(folder):
    """What the game's Active Rosters list calls a save folder."""
    m = re.fullmatch(r'Roster(Custom|Download)(\d+)', folder or '')
    if not m:
        return "the game's own roster"
    return f"{'Custom' if m[1] == 'Custom' else 'Online'} Roster {int(m[2]) + 1}"


def slot_names():
    return [f'{CUSTOM}{n}' for n in range(SLOTS)]


def used_slots(save_dir):
    """The custom roster folders the game lists that exist in `save_dir`, in slot order (a swap a power cut stopped
    is put back first: recover_swaps)."""
    recover_swaps(save_dir)
    return [n for n in slot_names() if os.path.isdir(os.path.join(save_dir, n))]


_ASIDE = re.compile(r'^\.overtime-old-(.+)-(\d+)$')


def recover_swaps(save_dir):
    """Put back a save a swap moved aside (write_new_folder, repair_trailer) when the power went between its two
    renames: `.overtime-old-<name>-<pid>` whose <name> is missing becomes <name> again. Only another run's (its pid is
    not this process's: this one may be between the renames right now). Never raises: the names put back."""
    back = []
    try:
        names = os.listdir(save_dir)
    except OSError:
        return back
    for n in names:
        m = _ASIDE.match(n)
        if not m or int(m.group(2)) == os.getpid():
            continue
        final = os.path.join(save_dir, m.group(1))
        if not os.path.exists(final):
            try:
                os.rename(os.path.join(save_dir, n), final)
                back.append(m.group(1))
            except OSError:
                pass
    return back


def next_free_name(save_dir, prefix=CUSTOM):
    """The lowest free `<prefix><n>`; for custom rosters only the 15 the game lists (SaveError FULL when taken)."""
    n = 0
    while os.path.exists(os.path.join(save_dir, f'{prefix}{n}')):
        n += 1
    if prefix == CUSTOM and n >= SLOTS:
        raise SaveError(FULL)
    return f'{prefix}{n}'


def template_files(save_dir, prefer=('RosterOnline0', 'Profile0')):
    """(param.sfo bytes, icon0.png bytes or None, trailer bytes or None, __SaveloadVer payload or None) copied
    from an existing save of this game; param.sfo is required for a new folder."""
    sfo_raw = icon = trailer = ver = None
    names = list(prefer) + sorted(os.listdir(save_dir)) if os.path.isdir(save_dir) else []
    for n in names:
        folder = os.path.join(save_dir, n)
        p = os.path.join(folder, 'sce_sys', 'param.sfo')
        if sfo_raw is None and os.path.isfile(p):
            with open(p, 'rb') as f:
                sfo_raw = f.read()
            ip = os.path.join(folder, 'sce_sys', 'icon0.png')
            if os.path.isfile(ip):
                with open(ip, 'rb') as f:
                    icon = f.read()
        if trailer is None and n.startswith('Roster'):
            try:
                rs = read(folder)
                trailer = rs.trailer
                ver = next((e.payload for e in rs.entries if e.name == '__SaveloadVer'), None)
            except (OSError, ValueError):
                pass
    return sfo_raw, icon, trailer, ver


TITLE_ID = 'CUSA11126'
# the trailer's first u32 in every Roster* save the game wrote (24 of 24; docs/notes/export-folder.md). 0 crashes the game
# when the roster is picked (0xc0000005 at 0x809a9261; docs/notes/roster-load-crash.md)
TRAILER_WORD = 0x58b72ed9
DEFAULT_TRAILER = TRAILER.pack(TRAILER_WORD, 0, 0, 0, 1)


def default_sfo(name, subtitle='Overtime roster', maintitle='Custom Roster', title=None):
    """A param.sfo for the save folder `name`, built without a template: the layout and values of the ones the game
    writes for a custom roster (none of it is per user)."""
    return sfo.build([
        sfo.Entry('ACCOUNT_ID', sfo.FMT_BYTES, bytes(8), 8),
        sfo.Entry('MAINTITLE', sfo.FMT_UTF8, maintitle, 128),
        sfo.Entry('SUBTITLE', sfo.FMT_UTF8, subtitle, 128),
        sfo.Entry('DETAIL', sfo.FMT_UTF8, f'{subtitle} (Overtime Roster)', 1024),
        sfo.Entry('SAVEDATA_DIRECTORY', sfo.FMT_UTF8, name, 32),
        sfo.Entry('SAVEDATA_LIST_PARAM', sfo.FMT_U32, 0, 4),
        sfo.Entry('TITLE_ID', sfo.FMT_UTF8, title or TITLE_ID, 12),
        sfo.Entry('SAVEDATA_BLOCKS', sfo.FMT_BYTES, bytes([0xe0]) + bytes(7), 8)])


def write_new_folder(save_dir, name, index, data, sfo_raw, icon=None, labels=None, replace=False):
    """Create `save_dir/name` (it must not exist). Written into a temporary folder first, then renamed, so a
    failure never leaves a half-written save. Returns the folder path.

    replace=True: `name` must be one of the game's custom roster slots and exist; it is swapped for the new folder
    (the old one is moved aside first and put back when the swap fails). Back the save folder up before."""
    final = os.path.join(save_dir, name)
    if replace:
        if name not in slot_names() or not os.path.isdir(final):
            raise SaveError(f'{name} is not a custom roster to overwrite')
    elif os.path.exists(final):
        raise SaveError(f'{name} already exists; Overtime never overwrites a save')
    if sfo_raw is None:
        raise SaveError('no param.sfo to copy: save once in the game first')
    have = sfo.values(sfo_raw)
    labels = {k: v for k, v in (labels or {}).items() if k in have}  # relabel only what the template has
    labels['SAVEDATA_DIRECTORY'] = name
    sfo_new = sfo.patch(sfo_raw, labels)
    tmp = os.path.join(save_dir, f'.overtime-tmp-{name}-{os.getpid()}')
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    try:
        os.makedirs(os.path.join(tmp, 'sce_sys'))
        for rel, blob in (('INDEX', index), ('DATA', data), ('NAME', name.encode('ascii')),
                          (os.path.join('sce_sys', 'param.sfo'), sfo_new)):
            with open(os.path.join(tmp, rel), 'wb') as f:
                f.write(blob)
        if icon:
            with open(os.path.join(tmp, 'sce_sys', 'icon0.png'), 'wb') as f:
                f.write(icon)
        durable.flush_tree(tmp)     # whole on the disk before it takes the slot's name (a power cut: old or new)
        if replace:
            aside = os.path.join(save_dir, f'.overtime-old-{name}-{os.getpid()}')
            os.rename(final, aside)
            try:
                os.rename(tmp, final)
            except OSError:
                os.rename(aside, final)
                raise
            shutil.rmtree(aside, ignore_errors=True)  # the backup made before holds it
        else:
            if os.path.exists(final):
                raise SaveError(f'{name} appeared while writing; nothing was replaced')
            os.rename(tmp, final)
    finally:
        if os.path.exists(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
    return final


def prune_backups(backups_dir, keep=BACKUPS_KEPT):
    """Delete all but the newest `keep` backups in `backups_dir` (install.run's folders, named by their
    %Y%m%d-%H%M%S stamp, so the name sorts by age). Other folders and files are left alone. Returns the names
    removed."""
    try:
        names = sorted(n for n in os.listdir(backups_dir)
                       if BACKUP_NAME.match(n) and os.path.isdir(os.path.join(backups_dir, n)))
    except OSError:
        return []
    gone = names[:max(0, len(names) - keep)]
    for n in gone:
        shutil.rmtree(os.path.join(backups_dir, n), ignore_errors=True)
    return gone


def zero_trailers(save_dir):
    """The custom rosters in `save_dir` with trailer word 0: Overtime wrote those before 0.20.1 when no good save was
    there to copy the word from (a player offline has no RosterOnline0), and the game crashes loading them."""
    found = []
    for n in used_slots(save_dir):
        try:
            trailer = read(os.path.join(save_dir, n)).trailer
        except (OSError, ValueError):
            continue        # not a roster this can read: left as it is
        if len(trailer) == TRAILER.size and not TRAILER.unpack(trailer)[0]:
            found.append(n)
    return found


def repair_trailer(folder, template=None):
    """Give a roster save with trailer word 0 the word of `template` (see trailer_for): the same database, metadata,
    slot and param.sfo. The folder is copied with the new INDEX and DATA, put on the disk, then swapped in whole, so
    INDEX and DATA always belong together (a power cut: the old folder, or the new one; recover_swaps puts the old
    one back if it came between the renames). Back the save folder up before."""
    rs = read(folder)
    ver = next((e.payload for e in rs.entries if e.name == '__SaveloadVer'), CUSTOM_VER_PAYLOAD)
    index, data = build_container(rs.name, rs.db_bytes, rs.meta, template, ver)
    check_container(rs.name, index, data, rs.db_bytes)
    folder = os.path.normpath(folder)
    save_dir, name = os.path.split(folder)
    tmp = os.path.join(save_dir, f'.overtime-tmp-{name}-{os.getpid()}')
    aside = os.path.join(save_dir, f'.overtime-old-{name}-{os.getpid()}')
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    try:
        shutil.copytree(folder, tmp)
        for rel, payload in (('INDEX', index), ('DATA', data)):
            with open(os.path.join(tmp, rel), 'wb') as f:
                f.write(payload)
        if read(tmp, name).db_bytes != rs.db_bytes:
            raise SaveError(f'{rs.name} does not read back the same after the repair')
        durable.flush_tree(tmp)
        os.rename(folder, aside)
        try:
            os.rename(tmp, folder)
        except OSError:
            os.rename(aside, folder)
            raise
        shutil.rmtree(aside, ignore_errors=True)    # the backup made before holds it
    finally:
        if os.path.exists(tmp):
            shutil.rmtree(tmp, ignore_errors=True)


def backup(save_dir, dest):
    """Copy every save folder of the game into `dest` (a new folder). Returns the folders copied."""
    copied = []
    os.makedirs(dest, exist_ok=False)
    for n in sorted(os.listdir(save_dir)):
        src = os.path.join(save_dir, n)
        if os.path.isdir(src) and not n.startswith(('.overtime-tmp-', '.overtime-old-', 'sce_')):   # sce_bu_*: shadPS4's
            shutil.copytree(src, os.path.join(dest, n))
            copied.append(n)
    return copied
