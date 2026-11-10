"""Which roster every tab works on: the game folder and the saves folder, the rosters found there, opening one
(Setup's "Which roster do you work on?", beta1's Source tab), and deleting a save (to the Recycle Bin).
docs/ui/setup.md, calls rosters_*.

A roster is opened as one RosterSession for all tabs (a job); the rail then starts on its first club and every part
hears of it (Rail.roster_changed). The one opened last is remembered and opened again at the next start
(Controller(reopen=True)). The two starts: the game roster (the game's own database) and the Overtime default (the
verified default the exe carries, or the one rebuilt after an Update: defaultdb.pick).
"""
import datetime
import os
import re
import threading

from overtime_core import overlay, rosterupdate, sfo, tdb

from . import defaultdb, gamesetup, install, jobs, paths, savegame, sources, trash
from .registry import Part
from .session import RosterSession
from .shell import friendly_date

SLOTS = 15          # NHL 19 lists RosterCustom0-14
DEFAULT = 'default'
STARTS = (('game', 'Game roster', 'The roster NHL 19 came with (2018-19).', 'NHL 19'),
          (DEFAULT, 'Overtime default', 'The 2026-27 teams with Seattle. Ready to play.', None))
MADE_BY = re.compile(r'\(Overtime Roster(?: ([^()]+))?\)\s*$')     # install.py's DETAIL: "<name> (Overtime Roster)"
RUNNING = ['shadPS4 is running. Rosters are not deleted while the game is open.',
           'Close shadPS4, press Check again, then delete it.']
MISFIT = ('New Season crashes with this roster while the game runs 32 teams. Open it and run Update: Seattle comes '
          'in.')


class RostersCtl(Part):
    CALLS = {'rosters_open': 'open', 'rosters_folder': 'folder', 'rosters_delete': 'delete',
             'set_game_dir': 'set_game_dir', 'set_save_dir': 'set_save_dir', 'refresh_sources': 'refresh_sources',
             'load_source': 'load_source'}

    def __init__(self, ctl):
        super().__init__(ctl)
        self.open_id = None     # the open roster: a source id (sources.GAME_ID, 'save:<folder>') or DEFAULT
        self._made = {}         # param.sfo path -> (mtime, (chip, note)): who made a save
        self._fits = {}         # save folder -> (sources.listing_key, True | False | None): it has an active Seattle
        self._fitting = False   # a job reads the saves not read yet

    # --- beta1's Source tab ------------------------------------------------------------------------------------------
    def set_game_dir(self, path):
        c = self.ctl
        with c.lock:
            c.game_dir = (path or '').strip().strip('"')
            gamesetup.use_game(c.game_dir)      # its title id names the save folder and the custom config
            c.game = sources.GameData(c.game_dir)
            c.editors._default = None
            c.remember(game_dir=c.game_dir)
        self.refresh_sources()

    def set_save_dir(self, path):
        c = self.ctl
        with c.lock:
            c.save_dir = (path or '').strip().strip('"')
            c.remember(save_dir=c.save_dir)
        self.refresh_sources()
        self.repair_saves()

    def repair_saves(self):
        """Once per saves folder (each read unpacks a roster): put right the rosters saved with trailer word 0, which
        the game crashes on (savegame.zero_trailers). A backup first; only that word changes. Not while shadPS4 runs."""
        c = self.ctl
        save_dir = c.save_dir
        if not os.path.isdir(save_dir or '') or c.prefs.get('trailers_checked') == save_dir:
            return

        def work():
            try:
                if savegame.zero_trailers(save_dir):
                    if overlay.emulator_running():   # the next start tries again
                        c.host.log('Rosters the game cannot load are put right at the next start: shadPS4 is running.')
                        return
                    self._repair(save_dir)
            except (OSError, ValueError) as err:
                c.host.log(f'Rosters the game cannot load were not put right: {err}')
                return
            with c.lock:
                c.remember(trailers_checked=save_dir)
        threading.Thread(target=work, daemon=True, name='save-repair').start()

    def _repair(self, save_dir):
        c = self.ctl
        with c.lock:    # nobody saves meanwhile
            found = savegame.zero_trailers(save_dir)
            if not found:
                return
            backups = paths.app_dir('backups')
            dest = os.path.join(backups, datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
            savegame.backup(save_dir, dest)
            c.host.log(f'Backed up the saves to {dest}')
            savegame.prune_backups(backups)
            trailer = savegame.template_files(save_dir)[2]
            for name in found:
                savegame.repair_trailer(os.path.join(save_dir, name), trailer)
                c.host.log(f'{name}: put right, the game crashed loading it.')
        c.say(f'{len(found)} roster(s) the game could not load were put right. A backup was made first.', 'good')
        self.refresh_sources(quiet=True)

    def refresh_sources(self, quiet=False):
        c = self.ctl
        with c.lock:
            c.sources = sources.find(c.game, c.save_dir)
            if c.selected is None:
                usable = [s for s in c.sources if s.usable]
                c.selected = usable[0].id if usable else None
        if not quiet:
            c.host.log(f'Found {len(c.sources)} roster source(s).')
        c.changed('source', 'setup')

    def load_source(self, ident):
        """Open a listed source (a job): the game roster or a save."""
        c = self.ctl
        src = next((s for s in c.sources if s.id == ident and s.usable), None)
        if src is None:
            return
        self._open_job(ident, src.name, lambda: sources.load(src, c.game), log=f'{src.name} ({src.path})')

    def load_default(self, said=None):
        """Open the Overtime default (a job): the one rebuilt after an Update when there is one, else the verified
        default the exe carries. said: the Help bar's line once it is open."""
        c = self.ctl

        def load():
            if not c.game.ok:
                raise ValueError('The NHL 19 game files were not found: set the game folder first.')
            data, came = defaultdb.pick(paths.app_dir('cache'))
            if data is None:
                raise ValueError('The Overtime default is not in this copy of the program. Open the game roster, '
                                 'or run Update.')
            c.host.log({'cache': 'Overtime default: the one rebuilt after your last Update.',
                        'embedded': 'Overtime default: the verified default this version ships.'}.get(came, came))
            return tdb.Database.parse(data, c.game.schema()), STARTS[1][1]
        self._open_job(DEFAULT, STARTS[1][1], load, said=said)

    def _open_job(self, ident, name, load, said=None, log=None):
        """Open a roster for every tab (a job): load() -> (tdb.Database, label)."""
        c = self.ctl
        with c.lock:
            if c.busy:
                return
            if ident != DEFAULT:
                c.selected = ident
            c.busy = f'Opening {name}...'
        c.say(c.busy, 'info', -1)
        c.changed('source', 'editor', 'setup')
        c.host.log(f'Opening {log or name}')

        def work():
            db, label = load()
            return RosterSession(db, label), label

        def done(result):
            with c.lock:
                c.session, label = result
                c.busy = None
                c.team = c.player = None
                c.query = ''
                c.issues = None
                c.result = None
                c.steps = {k: {'state': 'idle', 'text': ''} for k, _ in install.STEPS}
                self.open_id = ident
                c.remember(roster=ident)
            c.host.log(f'Opened {label}: {len(c.session.entry_row)} rostered players, '
                       f'{len(c.session.team_entries)} teams.')
            c.say(said or f'{label} is open. The Update tab and the team tabs use it now.', 'good')
            c.rail.roster_changed()     # the rail's first club; every part hears of the new roster
            c.changed_all()

        def failed(message):
            with c.lock:
                c.busy = None
            c.host.log(message)
            c.say(message, 'bad')
            c.changed('source', 'editor', 'setup')
        jobs.run(work, done, failed, expected=(OSError, ValueError))

    def snap_source(self):
        c = self.ctl
        with c.lock:
            return {
                'game_dir': c.game_dir, 'game_ok': c.game.ok, 'save_dir': c.save_dir,
                'save_ok': os.path.isdir(c.save_dir), 'sources': [s.view(c.selected) for s in c.sources],
                'selected': c.selected, 'loaded': c.session.source_name if c.session else None,
                'busy': bool(c.busy), 'home': paths.app_home(),
            }

    # --- the open roster ---------------------------------------------------------------------------------------------
    def source(self, ident):
        """The listed source of a source id, a save's folder name or 'game'."""
        if ident == 'game':
            ident = sources.GAME_ID
        return next((s for s in self.ctl.sources if s.id == ident or (s.kind == 'save' and s.info.get('folder') == ident)),
                    None)

    def open_roster(self):
        """{id, name, kind: 'start' | 'save' | 'online'} of the open roster, or None."""
        c = self.ctl
        if c.session is None or self.open_id is None:
            return None
        if self.open_id == sources.GAME_ID:
            return {'id': 'game', 'name': STARTS[0][1], 'kind': 'start'}
        if self.open_id == DEFAULT:
            return {'id': DEFAULT, 'name': STARTS[1][1], 'kind': 'start'}
        src = self.source(self.open_id)
        folder = src.info.get('folder') if src else self.open_id.split(':', 1)[-1]
        return {'id': folder, 'name': src.name if src else c.session.source_name,
                'kind': 'online' if folder.startswith('RosterOnline') else 'save'}

    @staticmethod
    def saved_on(src):
        """When a save was written, in words ('today at 21:14'), or '' (sources.Source.meta: folder · kind · date · KB)."""
        parts = (src.meta if src is not None else '').split(' · ')
        return friendly_date(parts[2]) if len(parts) > 2 else ''

    @staticmethod
    def _stamp(src):
        parts = (src.meta or '').split(' · ')
        return parts[2] if len(parts) > 2 else ''

    def remembered(self):
        """The roster opened last time, when it is still there: a source id, or DEFAULT while this copy carries the
        Overtime default."""
        ident = self.ctl.prefs.get('roster')
        if ident == DEFAULT:
            return DEFAULT if self.ctl.game.ok and (defaultdb.embedded_place()[0] or os.path.isfile(
                os.path.join(paths.app_dir('cache'), defaultdb.CACHE_DB))) else None
        return ident if any(s.id == ident and s.usable for s in self.ctl.sources) else None

    def start(self):
        """At the app's start: open the roster opened last time (a job); Setup looks for shadPS4 when none is
        picked yet (setup.find_at_start)."""
        c = self.ctl
        finder = getattr(c.setup, 'find_at_start', None) if getattr(c, 'setup', None) is not None else None
        if finder:
            finder()
        ident = self.remembered()
        if ident and c.session is None:
            if ident == DEFAULT:
                self.load_default()
            else:
                self.load_source(ident)

    # --- Setup's calls -----------------------------------------------------------------------------------------------
    def open(self, ident):
        """Open a roster for every tab: a save (its folder), 'game' or 'default'. Unsaved edits ask first."""
        c = self.ctl
        if ident == DEFAULT:
            name, go = STARTS[1][1], self.load_default
            same = self.open_id == DEFAULT
        else:
            src = self.source(ident)
            if src is None or not src.usable:
                text = 'That roster is not there any more. Check again.'
                c.say(text, 'caution')
                return {'error': text}
            name, same = src.name if src.kind == 'save' else STARTS[0][1], src.id == self.open_id
            go = lambda: self.load_source(src.id)   # noqa: E731
        if c.session is not None and same:
            c.say(f'{name} is open already.', 'info')
            return None
        if c.busy:
            c.say(f'Wait a moment: {str(c.busy).rstrip(". ")} is still running.', 'caution')
            return None
        return c.shell.ask_unsaved('open the other roster', go=go)

    def folder(self, ident):
        src = self.source(ident)
        path = src.path if src is not None and src.kind == 'save' else self.ctl.save_dir
        self.ctl.host.open_path(path)

    def delete(self, ident):
        """Move a save to the Recycle Bin, always after the question. Refused while shadPS4 runs, for the starts and
        the online roster, and for the open roster while its edits are not saved. The open roster deleted: the
        Overtime default opens."""
        c = self.ctl
        src = self.source(ident)
        if src is None or src.kind != 'save':
            text = 'The game roster and the Overtime default cannot be deleted.' if ident in ('game', DEFAULT) \
                else 'That roster is not there any more. Check again.'
            c.say(text, 'caution')
            return {'error': text}
        folder = src.info.get('folder') or os.path.basename(src.path)
        if folder.startswith('RosterOnline'):
            text = 'The online roster comes from the Overtime server: it is replaced when you sign in, not deleted.'
            c.say(text, 'caution')
            return {'error': text}
        if c.busy:
            c.say(f'Wait a moment: {str(c.busy).rstrip(". ")} is still running.', 'caution')
            return None
        if self._refused(src):
            return None
        is_open = src.id == self.open_id and c.session is not None
        chip, note = self._made_by(src)
        when = self.saved_on(src)
        lines = [f"Saved {when}{f': {note}' if note else ''}" if when else folder]
        if is_open:
            lines.append('It is the roster you work on. The Overtime default opens instead.')
        lines.append('You can take it out of the Recycle Bin again. Your other rosters are not changed.')
        c.shell.ask(f'Move "{src.name}" to the Recycle Bin?', lines,
                    [('Move to the Recycle Bin', 'delete', 'danger'), ('Keep it', 'keep', 'plain')],
                    {'delete': lambda: self._recycle(src.id)})
        return None

    def _refused(self, src):
        """Asks why not, when the save cannot go now: shadPS4 runs, or it is the open roster with edits not saved."""
        c = self.ctl
        if overlay.emulator_running():
            c.shell.ask('Close shadPS4 first', RUNNING, [('OK', 'ok', 'plain')])
            return True
        n = c.parts['save'].unsaved() if src.id == self.open_id and c.session is not None else 0
        if n:
            edits = f'{n} edits in it are' if n != 1 else '1 edit in it is'
            c.shell.ask('Your edits are not saved', [
                f'"{src.name}" is the roster you work on, and {edits} not saved.',
                'Save them as a new roster, or open another roster, then delete it.'], [('OK', 'ok', 'plain')])
            return True
        return False

    def _recycle(self, ident):
        """The answer Move to the Recycle Bin: checked again (time passed), then a job."""
        c = self.ctl
        src = self.source(ident)
        if src is None:
            c.say('That roster is not there any more. Check again.', 'caution')
            return
        if self._refused(src):
            return
        with c.lock:
            if c.busy:
                c.say(f'Wait a moment: {str(c.busy).rstrip(". ")} is still running.', 'caution')
                return
            was_open = src.id == self.open_id and c.session is not None
            c.busy = f'Deleting {src.name}...'
            save_dir = c.save_dir
        c.say(f'Moving {src.name} to the Recycle Bin...', 'info', -1)
        c.changed('setup', 'source')

        def done(path):
            with c.lock:
                c.busy = None
                if was_open:
                    c.session, self.open_id, c.selected = None, None, None
            c.host.log(f'Moved to the Recycle Bin: {path}')
            self.refresh_sources(quiet=True)
            text = f'"{src.name}" is in the Recycle Bin.'
            if was_open:
                c.rail.roster_changed()
                c.changed_all()
                self.load_default(said=f'{text} The Overtime default is open now.')
            else:
                c.say(text, 'good')
                c.changed('setup', 'update', 'save')

        def failed(message):
            with c.lock:
                c.busy = None
            c.host.log(message)
            c.say(message, 'bad')
            self.refresh_sources(quiet=True)
        jobs.run(lambda: trash.recycle(src.path, save_dir), done, failed, expected=(trash.TrashError, OSError))

    # --- Setup's roster card -----------------------------------------------------------------------------------------
    def _made_by(self, src):
        """(chip, note) of a save: who wrote it (install.py's DETAIL names Overtime Roster, with its version when it
        gives one), or the game ('Saved in the game.'). Read once per param.sfo change."""
        path = os.path.join(src.path, 'sce_sys', 'param.sfo')
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            return None, None
        hit = self._made.get(path)
        if hit is None or hit[0] != stamp:
            try:
                with open(path, 'rb') as f:
                    detail = str(sfo.values(f.read()).get('DETAIL') or '')
            except (OSError, ValueError, sfo.SfoError):
                detail = ''
            m = MADE_BY.search(detail)
            made = ((m.group(1) or 'Overtime Roster').strip(), None) if m else (None, 'Saved in the game.')
            hit = self._made[path] = (stamp, made)
        return hit[1]

    def fits(self, saves):
        """{save folder: True | False | None} of the saves read so far: whether the roster has an active Seattle
        (rosterupdate.seattle_ready; None: it cannot be read). The others are read in a job (Setup hears when it is
        done); each is read again only after it changed."""
        out, todo = {}, []
        for s in saves:
            if not s.usable:
                continue
            key = sources.listing_key(s.path)
            hit = self._fits.get(s.path)
            if hit is not None and hit[0] == key:
                out[s.path] = hit[1]
            else:
                todo.append((s, key))
        if todo and not self._fitting:
            self._fitting = True
            c = self.ctl

            def work():
                for s, key in todo:
                    self._fits[s.path] = (key, self._fit(s))

            def done(_out):
                self._fitting = False
                c.changed('setup')

            def failed(message):
                self._fitting = False
                c.host.log(f'The saves could not be read for Seattle: {message}')
            jobs.run(work, done, failed)
        return out

    def _fit(self, src):
        try:
            db, _label = sources.load(src, self.ctl.game)
            return bool(rosterupdate.seattle_ready(db))
        except Exception as err:   # noqa: BLE001 (only a mark: a save that cannot be read says so when opened)
            self.ctl.host.log(f'{src.name}: could not tell whether Seattle is in ({err}).')
            return None

    def view(self, known, running, teams32=None):
        """The `rosters` part of the setup slice. known: shadPS4 is picked (the list shows from then on); teams32: the
        installed patch has the 32-team switch on (a save without an active Seattle gets the "31 teams" mark)."""
        c = self.ctl
        mine = self.open_roster()
        open_id = mine['id'] if mine else None
        saves = [s for s in c.sources if s.kind == 'save'] if known else []
        saves.sort(key=self._stamp, reverse=True)       # newest first, the online roster last
        saves.sort(key=lambda s: (s.info.get('folder') or '').startswith('RosterOnline'))
        used = sum(1 for s in saves if s.info.get('folder', '').startswith('RosterCustom'))
        free = SLOTS - used
        if free <= 0:
            room = ('bad', f'0 free save slots from {SLOTS} total. Delete a roster you no longer play, or use '
                           '"Update this roster" when you save.')
        else:
            room = ('caution' if free == 1 else 'good', f'{free} free save slot{"s" if free != 1 else ""} from {SLOTS} total.')
        fits = self.fits(saves) if teams32 else {}
        rows = []
        for s in saves:
            folder = s.info.get('folder') or os.path.basename(s.path)
            online = folder.startswith('RosterOnline')
            when = self.saved_on(s)
            chip, note = (None, None) if online else self._made_by(s)
            said = (f'Sent by the server {when}' if online else f'Saved {when}') if when else folder
            chips = ([{'text': 'Online', 'tone': 'info'}] if online else
                     [{'text': chip, 'tone': ''}] if chip else [])
            misfit = fits.get(s.path) is False
            if misfit:
                chips.append({'text': '31 teams', 'tone': 'caution'})
            rows.append({
                'id': folder, 'kind': 'online' if online else 'save', 'name': s.name, 'chips': chips,
                'open': folder == open_id, 'meta': ' · '.join(x for x in (said, note) if x),
                'title': f'{s.name} ({folder})', 'problem': s.problem or (MISFIT if misfit else None),
                'acts': {'folder': True, 'delete': not online}, 'can_delete': not running,
                'delete_title': 'Close shadPS4 first: the game holds its saves while it runs.' if running
                else 'Move it to the Recycle Bin'})
        start = next((x for x in STARTS if x[0] == open_id), None) if mine and mine['kind'] == 'start' else None
        if start and known:
            rows.insert(0, {'id': start[0], 'kind': 'start', 'name': start[1],
                            'chips': [{'text': 'Start fresh', 'tone': 'accent'}], 'open': True,
                            'meta': 'Not saved yet. Save it as a new roster to keep your changes.', 'title': start[2],
                            'problem': None, 'acts': None, 'can_delete': False, 'delete_title': ''})
        return {
            'folder': c.save_dir if known else '', 'max': SLOTS, 'used': used, 'room_tone': room[0],
            'room_text': room[1], 'open': open_id, 'can_open': known,
            'starts': [{'id': i, 'name': n, 'note': note, 'tag': tag, 'open': i == open_id}
                       for i, n, note, tag in STARTS],
            'rows': rows,
            'empty': 'No saved rosters yet. Start fresh, then save it as a new roster in any team tab.' if known
            else 'Find NHL 19 first. Your rosters are listed here then.',
        }
