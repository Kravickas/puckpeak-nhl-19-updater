"""Save: the Save bar under the team tabs (My edits, the open roster, Update this roster or Save as a new roster,
the name, Save) and beta1's Verify & save steps, which still write the roster (install.run).
docs/ui/CONTRACT.md "Save, edits, drafts".

Edits wait in the open roster (RosterSession.history) until Save writes it; the ones made since the last save (or
since the roster was opened), and saved ones taken back since, are the unsaved ones. Each carries the tab and the
rail team it was made on (session.Change.tab / .team): My edits' chips and the rail's dots.

A good save also keeps the Roster tab's player edits it wrote in edits.json (myedits, RosterCtl.to_keep): My edits'
second list, "Kept for every update", put back after each update; its Remove drops one player's (myedits_remove).
"""
import os

from overtime_core import overlay, sfo

from . import install, jobs, myedits, paths, savegame
from .registry import Part
from .shell import TAB_LABELS, TEAM_TABS

MODES = ('update', 'new')
CANNOT_UPDATE = {
    'online': 'The online roster is replaced at every login: save it as a new roster.',
    'start': 'This roster is not a save yet: save it as a new roster.',
}


class SaveCtl(Part):
    SLICES = {'save': 'view'}
    CALLS = {'save': 'save', 'save_mode': 'set_mode', 'save_name': 'save_name', 'edits_open': 'edits_open',
             'myedits_remove': 'kept_remove', 'run_verify': 'run_verify', 'save_target': 'save_target',
             'save_slot': 'save_slot', 'save_start': 'save_start', 'result_close': 'result_close'}

    def __init__(self, ctl):
        super().__init__(ctl)
        self.mode = 'update'    # 'update' (only for a save) or 'new'
        self.listing = False    # My edits is open
        self.saved = []         # the roster's changes (RosterSession.history) when it was saved or opened

    def roster_changed(self):
        s = self.ctl.session
        self.saved = list(s.history) if s is not None else []
        self.mode = 'update'

    def pending(self):
        """[(change, undone)]: what makes the open roster differ from the one saved (or opened): the changes made since,
        and (undone True) saved ones taken back since. A change gets its tab and team the first time it is seen here
        when the part that made it did not set them (the tab in view, the rail's team). Call under the lock."""
        c = self.ctl
        s = c.session
        if s is None:
            return []
        h, kept = s.history, self.saved
        same = 0
        while same < len(h) and same < len(kept) and h[same] is kept[same]:
            same += 1
        out = [(ch, True) for ch in reversed(kept[same:])] + [(ch, False) for ch in h[same:]]
        for ch, _undone in out:
            if ch.tab is None:
                ch.tab = TAB_LABELS.get(c.tab_name, 'Roster')
                if ch.team is None and c.tab_name in TEAM_TABS:
                    ch.team = c.team
        return out

    def unsaved(self):
        with self.ctl.lock:
            return len(self.pending())

    def teams(self):
        """{rail id} of the teams with unsaved changes (the rail's dots). Call under the lock."""
        return {ch.team for ch, _undone in self.pending() if ch.team is not None}

    def mark_saved(self, history):
        """The roster as written (its changes: `history`) is the saved one now, so nothing is unsaved. Update's Go
        saves through install.run itself and tells the Save bar here."""
        with self.ctl.lock:
            self.saved = list(history)
        self.ctl.changed('save', 'rail', 'editor', 'lines', 'strategy')

    def discard(self):
        """Drop the unsaved edits (the unsaved question's Lose them): the changes made since the roster was saved or
        opened are taken back, newest first. A saved change already taken back stays taken back (only the bytes from
        before a change are kept). Returns how many were taken back."""
        c = self.ctl
        with c.lock:
            s = c.session
            if s is None:
                return 0
            h, kept = s.history, self.saved
            same = 0
            while same < len(h) and same < len(kept) and h[same] is kept[same]:
                same += 1
            n = len(h) - same
            for _ in range(n):
                s.undo()
            if n:
                c.issues = None
        if n:
            c.host.log(f'{n} unsaved edit(s) dropped.')
            c.changed_all()
        return n

    def update_mode(self, roster):
        """Whether Save writes over the open roster (a save, with 'Update this roster' picked)."""
        return self.mode == 'update' and (roster or {}).get('kind') == 'save'

    # --- the Save bar ------------------------------------------------------------------------------------------------
    @staticmethod
    def modes(roster):
        why = None if roster is not None and roster['kind'] == 'save' else \
            CANNOT_UPDATE.get((roster or {}).get('kind'), CANNOT_UPDATE['start'])
        return [{'value': 'update', 'label': 'Update this roster', 'disabled': bool(why),
                 'title': why or 'Write over the open roster'},
                {'value': 'new', 'label': 'Save as a new roster'}]

    def view(self):
        c = self.ctl
        with c.lock:
            roster = c.parts['rosters'].open_roster()
            kept = myedits.rows(c.parts['roster'].kept())
            if roster is None:
                return {'roster': None, 'edits_count': 0, 'unsaved': 0, 'edits': [], 'edits_open': False,
                        'kept': kept[:500], 'kept_count': len(kept), 'mode': 'new', 'modes': self.modes(None),
                        'name': c.save_name_text, 'button': {'text': 'Save as new', 'enabled': False},
                        'busy': bool(c.busy)}
            mode = 'update' if self.update_mode(roster) else 'new'
            changes = self.pending()
            n = len(changes)
            edits = []
            for i, (ch, undone) in enumerate(changes[-300:]):
                chip = c.rail.chip(ch.team) if ch.team is not None else None
                edits.append({'id': i, 'tab': ch.tab, 'team': ch.team, 'code': chip['code'] if chip else '',
                              'label': f'Taken back: {ch.label}' if undone else ch.label})
            return {
                'roster': roster, 'edits_count': n, 'unsaved': n, 'edits': edits,
                'kept': kept[:500], 'kept_count': len(kept),
                'edits_open': self.listing, 'mode': mode, 'modes': self.modes(roster), 'name': c.save_name_text,
                'button': {'text': 'Save' if mode == 'update' else 'Save as new',
                           'enabled': not c.busy and (n > 0 or mode == 'new')},
                'busy': bool(c.busy),
            }

    def set_mode(self, mode):
        if mode in MODES:
            self.mode = mode
        self.ctl.changed('save')

    def edits_open(self, on):
        self.listing = bool(on)
        self.ctl.changed('save')

    def kept_remove(self, key):
        """My edits' Remove on a kept player: his edits are no longer put back after an update (the open roster keeps
        what it has)."""
        c = self.ctl
        with c.lock:
            try:
                name = c.parts['roster'].kept_remove(str(key))
            except OSError as err:
                name, text = None, f'My edits could not be changed: {err}'
        if name is None:
            c.say(text, 'bad')
            return {'ok': False, 'error': text}
        if not name:
            return {'ok': False}
        c.say(f'{name} is out of My edits: the next update leaves him as NHL.com has him.', 'good')
        c.changed('save', 'update')
        return {'ok': True}

    def save(self, draft=None, then=None):
        """Save (the Save bar, Ctrl+S): the card's typed values are applied first, other tabs' changes not applied yet
        ask "Apply your changes first?", then the roster is written: over the open save or as a new one. `then` runs
        after a good save (the unsaved question's Save first)."""
        c = self.ctl
        if c.session is None:
            return {'error': 'Pick a roster in Setup first.'}
        if c.busy:
            return None
        if isinstance(draft, dict) and draft.get('values') is not None and draft.get('id') == c.player:
            reply = c.parts['roster'].apply(draft['values'])
            if reply and reply.get('error'):
                return reply
        waiting = [text for text in (part.drafts() for part in c.parts.values() if hasattr(part, 'drafts')) if text]
        with c.lock:    # the Save button's rules (view): Ctrl+S and the unsaved question come here too
            update = self.update_mode(c.parts['rosters'].open_roster())
            nothing = update and not self.pending()
            unnamed = not update and not (c.save_name_text or '').strip()
        if nothing or unnamed:
            if nothing:
                text = 'Apply your changes first, then save.' if waiting else 'Nothing to save yet.'
            else:
                text = 'Type a name for the new roster first.'
            c.say(text, 'caution')
            return {'error': text}
        if waiting:
            c.shell.ask('Apply your changes first?', waiting + ['Save writes only what was applied.'],
                        [('Save without them', 'save', 'primary'), ('Go back', 'back', 'plain')],
                        {'save': lambda: self.write(then)})
            return None
        return self.write(then)

    def write(self, then=None):
        c = self.ctl
        roster = c.parts['rosters'].open_roster() or {}
        update = self.update_mode(roster)
        with c.lock:
            c.target = install.TARGET_SAVE
            c.slot = roster['id'] if update and roster['id'] in savegame.slot_names() else None
        return self.save_start(then=then, name=roster.get('name') if update else None, reopen=not update)

    # --- beta1's Verify & save ---------------------------------------------------------------------------------------
    def run_verify(self):
        c = self.ctl
        with c.lock:
            if not c.session:
                return
            c.issues = c.session.verify()
        e = sum(1 for i in c.issues if i.level == 'error')
        c.host.log(f'Verify: {e} error(s), {len(c.issues) - e} warning(s).')
        c.say(f'Verify: {e} error(s), {len(c.issues) - e} warning(s).', 'bad' if e else 'good')
        c.changed('save')

    def save_name(self, text):
        c = self.ctl
        with c.lock:
            c.save_name_text = (text or '')[:64]
            c.remember(save_name=c.save_name_text)
        c.changed('save')

    def save_target(self, target):
        c = self.ctl
        if target in (install.TARGET_SAVE, install.TARGET_EXPORT, install.TARGET_FOLDER):
            with c.lock:
                c.target = target
            c.changed('save')

    def save_slot(self, name):
        """Overwrite this custom roster slot on the next save (None / '': write a new folder)."""
        c = self.ctl
        with c.lock:
            c.slot = name if name in savegame.slot_names() else None
        c.changed('save')

    def _slots(self):
        c = self.ctl
        used = []
        for n in savegame.used_slots(c.save_dir) if os.path.isdir(c.save_dir or '') else []:
            label = ''
            try:
                with open(os.path.join(c.save_dir, n, 'sce_sys', 'param.sfo'), 'rb') as f:
                    label = sfo.values(f.read()).get('SUBTITLE', '')
            except (OSError, ValueError):
                pass
            used.append({'name': n, 'label': f'{n} (Custom Roster {int(n[12:]) + 1}){": " + label if label else ""}'})
        return {'limit': savegame.SLOTS, 'used': used, 'free': savegame.SLOTS - len(used), 'full_text': savegame.FULL}

    def save_start(self, then=None, name=None, reopen=False):
        """Write the roster (a job). name: the roster's name (None: the one typed); then: runs after a good save;
        reopen: a new save becomes the open roster (Save as new: the Save bar then updates it)."""
        c = self.ctl
        if c.session and c.target == install.TARGET_SAVE and overlay.emulator_running():
            c.shell.ask('Close shadPS4 first', ['shadPS4 is running, and the game holds its saves while it runs.',
                                                'Close it, press Check again, then save.'], [('OK', 'ok', 'plain')])
            return
        with c.lock:
            if not c.session or c.busy:
                return
            c.busy = 'Saving...'
            c.result = None
            c.steps = {k: {'state': 'idle', 'text': ''} for k, _ in install.STEPS}
            session, target, name = c.session, c.target, name or c.save_name_text
            slot = c.slot if target == install.TARGET_SAVE else None
            written = list(session.history)
        c.changed('save', 'source', 'editor')
        c.say('Saving...', 'info', 0.0)
        order = [k for k, _ in install.STEPS]

        def step(key, state, text=''):
            with c.lock:
                c.steps[key] = {'state': state, 'text': text}
            if state in ('ok', 'skip'):
                c.say(f'{dict(install.STEPS)[key]}: {text}', 'info', (order.index(key) + 1) / len(order))
            c.changed('save')

        def work():
            with c.lock:  # nobody edits while the roster is written
                out = install.run(session, c.game, target, name, c.save_dir, paths.app_dir('exports'),
                                  step=step, log=c.host.log, overwrite=slot)
                keep = None
                if out.ok and c.session is session:
                    try:
                        keep = c.parts['roster'].to_keep(written)
                    except Exception as err:    # noqa: BLE001 (the save itself went well)
                        c.host.log(f'My edits could not be kept: {err}')
                return out, keep

        def done(result):
            out, keep = result
            with c.lock:
                c.busy = None
                c.result = {'ok': out.ok, 'title': out.title, 'lines': out.lines, 'items': out.items,
                            'folder': out.folder, 'report': out.report, 'after': out.after}
                c.issues = c.session.verify() if not out.ok else c.issues
            if out.ok and out.after:    # saved all the same (Legacy 0.51.1)
                c.say(f"{out.title}. Not done: {'; '.join(out.after)} (Error log has the details).", 'caution', 1.0)
            else:
                c.say(out.title + ('' if out.ok else ': ' + out.lines[0]), 'good' if out.ok else 'bad',
                      1.0 if out.ok else None)
            if out.ok:
                with c.lock:
                    c.slot = None
                    if c.session is session:
                        self.saved = written
                        if keep is not None:
                            c.parts['roster'].kept_saved(*keep)
                c.refresh_sources(quiet=True)
                if reopen and target == install.TARGET_SAVE and out.folder and c.session is session:
                    self.opened(os.path.basename(os.path.normpath(out.folder)))
            # a save makes the applied changes the base: Lines' and Strategy's notes and Take back follow
            c.changed('save', 'source', 'editor', 'lines', 'strategy')
            if out.ok and then:
                then()

        def failed(message):
            with c.lock:
                c.busy = None
                c.result = {'ok': False, 'title': 'Not saved', 'lines': [message], 'items': [], 'folder': '',
                            'report': ''}
            c.say(message, 'bad')
            c.changed('save', 'source', 'editor')
        jobs.run(work, done, failed)

    def opened(self, folder):
        """The roster just saved as new is the open one now (the mockup's save): Save then updates it, and the next
        "Save as new" needs a name of its own."""
        c = self.ctl
        rosters = c.parts['rosters']
        with c.lock:
            src = rosters.source(folder)
            if src is None:
                return
            rosters.open_id = c.selected = src.id
            self.mode = 'update'
            c.save_name_text = ''
            c.remember(roster=src.id, save_name='')
        c.changed('save', 'setup', 'app', 'update')

    def result_close(self):
        c = self.ctl
        with c.lock:
            c.result = None
        c.changed('save')

    def snap_save(self):
        c = self.ctl
        with c.lock:
            s = c.session
            issues = c.issues
            iv = None
            if issues is not None:
                errors = [i for i in issues if i.level == 'error']
                iv = {'errors': len(errors), 'warnings': len(issues) - len(errors),
                      'list': [{'level': i.level, 'rule': i.rule, 'message': i.message,
                                'team': s.team_name(i.team) if (s and i.team is not None) else ''}
                               for i in issues[:300]]}
            slots = self._slots()
            full = c.target == install.TARGET_SAVE and not c.slot and slots['free'] <= 0
            enabled = bool(s) and not c.busy and not full
            if c.target == install.TARGET_FOLDER:
                text = 'Export to folder'
            elif c.target != install.TARGET_SAVE:
                text = 'Export roster file'
            else:
                text = f'Overwrite {c.slot}' if c.slot else 'Save as new roster'
            return {
                'slots': slots, 'slot': c.slot, 'full': full,
                'loaded': bool(s), 'busy': bool(c.busy), 'name': c.save_name_text, 'target': c.target,
                'targets': [{'value': install.TARGET_SAVE, 'label': 'New roster save'},
                            {'value': install.TARGET_FOLDER, 'label': 'Folder to copy to another PC'},
                            {'value': install.TARGET_EXPORT, 'label': 'Roster file for Overtime server'}],
                'steps': [{'key': k, 'label': lab, **c.steps[k]} for k, lab in install.STEPS],
                'verify': iv, 'result': c.result, 'edits': s.change_lines()[-200:] if s else [],
                'edit_count': len(s.change_lines()) if s else 0,
                'button': {'enabled': enabled, 'text': text},
                'save_dir': c.save_dir,
            }
