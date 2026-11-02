"""Save pipeline: gather -> build -> verify -> (backup) -> install as a NEW save / export -> report.

Nothing is written when verify fails. Verify = the roster rules (overtime_core.roster, not strict: only corruption
stops a save, the default roster's patterns are warnings), the roster keys (put right on the way, refused only when they
cannot be), a byte-exact re-parse of the built database (checksum chain included), the roster CRC, and a re-read of the
built save container.

Targets:
  'save'    a new save folder `RosterCustom<N>` holding the `rosters` savegroup, written like a custom roster the game
            saves itself (version 46.0); the game lists it as "Custom Roster <N+1>" and loads it (run 2026-10-16c/d)
  'folder'  the same save folder, built under the app's exports folder in the shadPS4 layout (with a HOW-TO) to copy to
            another PC; needs no save on this PC (param.sfo and trailer are built, docs/notes/export-folder.md)
  'export'  the `rosterupdate` database (exactly what the game downloads as the online roster, proven in run
            2026-10-15p) plus its 54-character CRC, for the Overtime server
"""
import datetime
import os
import time
from dataclasses import dataclass, field

from overtime_core import overlay, rostercrc, rosterupdate, tdb

from . import howto, jobs, report, savegame

STEPS = [('gather', 'Gather'), ('build', 'Build'), ('verify', 'Verify'), ('backup', 'Back up saves'),
         ('install', 'Install'), ('report', 'Report')]
TARGET_SAVE, TARGET_EXPORT, TARGET_FOLDER = 'save', 'export', 'folder'


@dataclass
class Outcome:
    ok: bool
    title: str
    lines: list = field(default_factory=list)
    items: list = field(default_factory=list)  # (label, text)
    folder: str = ''
    report: str = ''
    crc: str = ''
    after: list = field(default_factory=list)  # what failed after a good save (the roster IS saved): red lines


RUNNING = ('shadPS4 is running, and the game holds its saves while it runs. Close it, then save again. '
           'Nothing was written.')


class Failed(Exception):
    pass


def group_order(schema, group):
    return [m.short for m in schema.tables.values() if group in m.savegroups]


def unique_dir(path):
    """`path`, or `path (2)`, `path (3)`... when it exists."""
    n, out = 1, path
    while os.path.exists(out):
        n += 1
        out = f'{path} ({n})'
    return out


def build_database(session, game, target):
    """The database to write for `target`, sharing the session's table objects."""
    schema = game.schema()
    order = game.roster_order()  # the 41 rosterupdate tables, in the game's roster-file order
    db = session.db
    if target == TARGET_EXPORT:
        return db.subset('rosterupdate', order=order)
    tables = [db[tag] for tag in order]
    default = None
    for tag in group_order(schema, 'custom'):
        if tag in db:
            tables.append(db[tag])
        else:
            default = default or game.default_db()
            tables.append(default[tag])
    return tdb.Database(tables, db._header)


def roster_crc(session, game):
    order = group_order(game.schema(), 'rosterupdate')
    return rostercrc.roster_crc(tdb.Database([session.db[t] for t in order], session.db._header))


def run(session, game, target, name, save_dir, out_root, step=lambda key, state, text='': None, log=print,
        now=None, overwrite=None, folder_slot=None, running=None):
    """Run the pipeline. `step(key, state, text)` reports progress ('run', 'ok', 'fail', 'skip'). `overwrite`: a
    custom roster slot (savegame.slot_names) to replace instead of a new folder (after the backup). `folder_slot`: the slot
    a folder for another PC is made for (None: the next free one beside this PC's saves). The slot is baked into the
    folder (NAME, INDEX, param.sfo): a renamed copy lists in the game but does not load (checked in game 2026-10-27)."""
    now = now or datetime.datetime.now()
    stamp = now.strftime('%Y%m%d-%H%M%S')
    name = (name or 'Overtime roster').strip()[:64]
    current = ['gather']
    try:
        # gather
        step('gather', 'run')
        schema = game.schema()
        is_save = target in (TARGET_SAVE, TARGET_FOLDER)
        have_dir = bool(save_dir) and os.path.isdir(save_dir)
        if target == TARGET_FOLDER:
            # a folder for another PC: this PC's save only keeps the slot number clear of its own and lends its template
            sfo_raw, icon, trailer, _ = savegame.template_files(save_dir) if have_dir else (None, None, None, None)
            if overwrite:
                raise Failed('An export to a folder never overwrites a roster slot.')
            if folder_slot and folder_slot not in savegame.slot_names():
                raise Failed(f'{folder_slot} is not a roster slot the game lists.')
            try:
                folder_name = folder_slot or (savegame.next_free_name(save_dir) if have_dir else f'{savegame.CUSTOM}0')
            except savegame.SaveError as err:
                raise Failed(str(err)) from None
            sfo_raw = sfo_raw or savegame.default_sfo(folder_name)
            trailer = trailer or savegame.DEFAULT_TRAILER
        elif target == TARGET_SAVE:
            if not save_dir:
                raise Failed('Overtime does not know where shadPS4 keeps its saves. Pick the game in Setup first.')
            if (running or overlay.emulator_running)():
                raise Failed(RUNNING)
            if overwrite:
                if overwrite not in savegame.used_slots(save_dir):
                    raise Failed(f'{overwrite} is not a custom roster in the save folder; nothing was written.')
                folder_name = overwrite
            else:
                try:
                    folder_name = savegame.next_free_name(save_dir)
                except savegame.SaveError as err:
                    raise Failed(str(err)) from None
            # a first save (no save folder yet, or no save with a param.sfo to copy, as for a player who never ran the
            # game) builds what it needs: param.sfo and the trailer are nothing per user (docs/notes/export-folder.md)
            sfo_raw, icon, trailer, _ = savegame.template_files(save_dir)
            title = os.path.basename(os.path.normpath(save_dir))    # the game's save folder is named by its title id
            sfo_raw = sfo_raw or savegame.default_sfo(folder_name, title=title if title.startswith('CUSA') else None)
            trailer = trailer or savegame.DEFAULT_TRAILER
        log(f'Roster: {session.source_name}; {len(session.change_lines())} edit(s).')
        step('gather', 'ok', folder_name if is_save else 'export')

        # build
        current[0] = 'build'
        step('build', 'run')
        db = build_database(session, game, target)
        # roster keys out of the stock layout crash Play Now (RosterCustom11: 127 bad keys, 0x809a91a5): put them right
        # instead of refusing (a roster edited elsewhere); the CRC below is taken after
        if rosterupdate.key_problems(db):
            try:
                fixed = rosterupdate.repair_keys(db)
            except ValueError as err:
                raise Failed(f'The game cannot load this roster: {err}. Nothing was written.') from None
            log(f'Roster keys put in the order the game reads: {fixed} key(s).')
        blob = db.to_bytes()
        order = group_order(schema, 'rosterupdate')
        crc = rostercrc.roster_crc(tdb.Database([db[t] for t in order], db._header))  # of what is written
        log(f'Built {len(db.tables)} tables, {len(blob):,} bytes. Roster CRC {crc}.')
        step('build', 'ok', f'{len(db.tables)} tables, {len(blob) // 1024} KB')

        # verify
        current[0] = 'verify'
        step('verify', 'run')
        issues = session.verify()   # not strict: the default roster's patterns are warnings (the game plays them)
        errors = [i for i in issues if i.level == 'error']
        for i in issues[:200]:
            log(f'  {i}')
        if errors:
            raise Failed(f'The check found {len(errors)} error(s), so nothing was written. Open the details to see them.')
        keys = rosterupdate.key_problems(db)     # repaired above; still there means a bug, never write it
        for k in keys[:50]:
            log(f'  {k}')
        if keys:
            raise Failed(f'{len(keys)} team(s) have roster keys the game cannot load (they crash Play Now); '
                         'nothing was written.')
        again = tdb.Database.parse(blob, schema)
        if again.to_bytes() != blob:
            raise Failed('The database does not re-encode byte for byte; nothing was written.')
        if len(again.tables) != len(db.tables):
            raise Failed('Table count changed on re-read; nothing was written.')
        if is_save:
            # keys and version of a custom roster the game wrote itself (version 45.0 lists as corrupt)
            meta = {'FileCreateDate': int(now.timestamp() * 1000), 'FileDisplayName': name, 'CRCValue': crc}
            index, data = savegame.build_container(folder_name, blob, meta, trailer,
                                                   savegame.CUSTOM_VER_PAYLOAD, stamp_ns=time.time_ns())
            savegame.check_container(folder_name, index, data, blob)
        warn = len(issues) - len(errors)
        step('verify', 'ok', f'0 errors, {warn} warning(s), byte-exact')

        # backup + install
        out_dir = os.path.join(out_root, stamp)
        if target == TARGET_FOLDER:  # one folder per export, never an existing one
            out_dir = unique_dir(out_dir)
        os.makedirs(out_dir, exist_ok=True)
        folder = ''
        if target == TARGET_FOLDER:
            step('backup', 'skip', 'nothing in a save folder changes')
            current[0] = 'install'
            step('install', 'run')
            tree = os.path.join(out_dir, howto.DATA_DIR, *howto.SAVE_PARTS)
            os.makedirs(tree)
            folder = savegame.write_new_folder(tree, folder_name, index, data, sfo_raw, icon, labels={
                'MAINTITLE': 'Custom Roster', 'SUBTITLE': name, 'DETAIL': f'{name} (Overtime Roster)'})
            if savegame.read(folder).db_bytes != blob:
                raise Failed(f'{folder_name} was written but does not read back the same; delete {out_dir}.')
            with open(os.path.join(out_dir, howto.FILE), 'w', encoding='utf-8') as f:
                f.write(howto.text(folder_name, name))
            log(f'Built {folder}')
            step('install', 'ok', folder_name)
        elif target == TARGET_SAVE:
            current[0] = 'backup'
            step('backup', 'run')
            os.makedirs(save_dir, exist_ok=True)    # a first save: the game has not made its save folder yet
            dest = os.path.join(out_root, '..', 'backups', stamp)
            try:
                copied = savegame.backup(save_dir, os.path.normpath(dest))
            except FileExistsError:  # two saves in one second: nothing was written yet
                raise Failed('A backup was made a second ago; wait a moment and save again. Nothing was written.')                     from None
            log(f'Backed up {len(copied)} save folder(s) to {os.path.normpath(dest)}')
            gone = savegame.prune_backups(os.path.dirname(os.path.normpath(dest)))
            if gone:
                log(f'Removed {len(gone)} old backup(s): the newest {savegame.BACKUPS_KEPT} are kept')
            step('backup', 'ok', f'{len(copied)} folder(s)')
            current[0] = 'install'
            step('install', 'run')
            folder = savegame.write_new_folder(save_dir, folder_name, index, data, sfo_raw, icon, labels={
                'MAINTITLE': 'Custom Roster', 'SUBTITLE': name, 'DETAIL': f'{name} (Overtime Roster)'},
                replace=bool(overwrite))
            if savegame.read(folder).db_bytes != blob:
                raise Failed(f'{folder_name} was written but does not read back the same; it is left for you to '
                             'delete, nothing else changed.')
            log(f'Installed {folder}')
            step('install', 'ok', folder_name)
        else:
            step('backup', 'skip', 'nothing in the save folder changes')
            current[0] = 'install'
            step('install', 'run')
            folder = out_dir
            with open(os.path.join(out_dir, 'roster_h2h.db'), 'wb') as f:
                f.write(blob)
            with open(os.path.join(out_dir, 'roster_h2h.crc.txt'), 'w', encoding='ascii') as f:
                f.write(crc + '\n')
            log(f'Exported roster_h2h.db and its CRC to {out_dir}')
            step('install', 'ok', 'roster_h2h.db')

        # report: the roster is saved from here on, so a failure is told as such, not as "Not saved" (Legacy 0.51.1)
        current[0] = 'report'
        step('report', 'run')
        rpath = os.path.join(out_dir, 'report.html')
        after = []
        try:
            report.write(rpath, title=name, source=session.source_name, target=target, folder=folder, crc=crc,
                         changes=session.change_lines(), issues=issues, when=now)
            step('report', 'ok', 'report.html')
        except Exception as err:  # noqa: BLE001 (the save itself went well)
            jobs.log_unexpected(err, step='Report (after the save)')
            rpath = ''
            after.append(f'The list of changes (report.html) was not written: {err}')
            step('report', 'fail', after[-1])
            log(after[-1])
        if target == TARGET_FOLDER:
            return Outcome(True, 'Folder exported', [
                f'"{name}" is the folder {folder_name}, ready to copy to the PC that runs shadPS4.',
                f'Open {howto.FILE} in the same folder: it says where it goes. Nothing on this PC was changed.'],
                [('Folder', out_dir), ('Roster folder', folder_name), ('Roster CRC', crc),
                 ('Edits', str(len(session.change_lines()))), ('Report', rpath or 'not written')],
                out_dir, rpath, crc, after)
        if target == TARGET_SAVE:
            return Outcome(True, f'Saved as {folder_name}', [
                f'"{name}" was installed as the ' + (f'save folder {folder_name}, replacing the roster that was there '
                                                    '(it is in the backup).' if overwrite else
                                                    f'new save folder {folder_name}.'),
                f'In NHL 19: Rosters > Active Roster, pick "Custom Roster {int(folder_name[12:]) + 1}". '
                'Your other saves were not touched (a backup was made first).'],
                [('Folder', folder), ('Roster CRC', crc), ('Edits', str(len(session.change_lines()))),
                 ('Report', rpath or 'not written')], folder, rpath, crc, after)
        return Outcome(True, 'Roster file exported', [
            'roster_h2h.db is the online roster format the game downloads and installs (proven in game).',
            'Publish it with the Overtime server; the CRC file holds the value the server announces.'],
            [('Folder', out_dir), ('Roster CRC', crc), ('Edits', str(len(session.change_lines()))),
             ('Report', rpath or 'not written')], out_dir, rpath, crc, after)
    except Failed as err:
        step(current[0], 'fail', str(err))
        log(f'Stopped: {err}')
        return Outcome(False, 'Not saved', [str(err)])
