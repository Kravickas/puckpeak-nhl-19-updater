"""The Patch tab's one press (0.97.0, docs/plans/nhl-27-perf-mellow-scroll.md A and B): Update, then the starter
profile, then Patch.

Update and Game patch were two tabs; they are one Patch tab now. UpdateCtl and PatchCtl keep their slices and calls;
this part adds the one press over both (`patch_all`) and the two switches of its own (the Roster update group, Skip the
first-run setup).

- Run order: Update, then Patch. Patch reads what Update gathered (the default roster rebuild, clubart_roster,
  _seattle_ready). Update runs when a roster is open and the Roster update group is on.
- Update writes the deals and the photos for the game as the coming Patch leaves it (UpdateCtl.start_go's `served`),
  so a game never patched gets 2026-27 money when the league switch is on.
- Pre-flight before anything runs: the emulator found, NHL 19 not running, no lobby match set up (one_click refuses
  these too, but only after Update would have saved).
- Update stops (check errors, NHL.com): its red step stays, and "Patch the game anyway" patches without it.
- Update saved, Patch refused or failed: Update's result with Undo stays; the next press skips Update while the
  roster is unchanged.
- The starter profile (starter.py) goes in between, only for a save folder with no Profile0 and with its switch on:
  it names the roster Update just saved as the active one.
"""
import os
import re

from overtime_core import overlay

from . import install, matchsetup, patch_ctl, starter
from .registry import Part

ROSTER_FOLDER = re.compile(r'Roster(Custom|Download)(\d+)')     # a roster save folder: the profile's type + slot
PREF = 'patch_tab'      # prefs: {'update': bool (the Roster update group), 'starter': bool (Skip the first-run setup)}


def roster_of(folder):
    """(ActiveRosterType, ActiveRosterSaveSlot) of a roster save folder ('RosterCustom2' -> ('Custom', 2)), as
    savegame.active_roster reads it back; None (no active roster) for anything else."""
    m = ROSTER_FOLDER.fullmatch(folder or '')
    return (m[1], int(m[2])) if m else None


class PatchAllCtl(Part):
    SLICES = {'patchall': 'view'}
    CALLS = {'patch_all': 'patch_all', 'patch_anyway': 'patch_anyway', 'patch_update_on': 'set_update_on',
             'patch_starter': 'set_starter'}

    def __init__(self, ctl):
        super().__init__(ctl)
        pref = ctl.prefs.get(PREF) or {}
        self.update_on = bool(pref.get('update', True))
        self.starter_on = bool(pref.get('starter', False))    # off until the owner's boot test of the profile passes
        self.phase = None       # 'update' | 'patch' while the one press runs (from Update's start to Patch's start)
        self.skip = None        # (session, history length): Update saved, Patch did not go in; that roster skips Update

    # --- what runs ---------------------------------------------------------------------------------------------------
    def _update_runs(self):
        """Whether the next press runs Update (call under the lock)."""
        c = self.ctl
        if not self.update_on or c.parts['rosters'].open_roster() is None:
            return False
        s = c.session
        return not (self.skip and s is not None and self.skip == (s, len(s.history)))

    def _preflight(self):
        """Why the one press cannot start now, or None (before anything runs or saves)."""
        c = self.ctl
        with c.lock:
            busy, emu, ok = c.busy, c.setup.emulator, bool(c.game.ok)
        if busy:
            return f'Wait a moment: {patch_ctl._doing(busy)} is still running.'
        if not emu or not ok:
            return 'Find NHL 19 in Setup first: the patch goes in with it.'
        if overlay.emulator_running():
            return 'NHL 19 is running. Close it, then press Patch again.'
        if matchsetup.active():
            return patch_ctl.MATCH_LOCKED
        return None

    def patch_all(self):
        """The Patch button: Update (when it runs), the starter profile, Patch. Unsaved edits ask first."""
        c = self.ctl
        why = self._preflight()
        if why is None:
            with c.lock:
                runs = self._update_runs()
                if runs:
                    block = c.parts['update'].save_view(c.parts['rosters'].open_roster())['block']
                    if block:
                        why = f'{block.rstrip(".")}, or turn Roster update off to patch only.'
        if why:
            c.say(why, 'caution')
            return {'error': why}
        if not runs:
            return self._patch_half()
        return c.shell.ask_unsaved('update the roster and patch the game', go=self._go_on)

    def _go_on(self):
        """After the unsaved question: drop what Save first did not keep, then Update with Patch next."""
        c = self.ctl
        upd = c.parts['update']
        upd.drop_edits()
        with c.lock:
            want = dict(c.patch_want)
        served = patch_ctl.switches(want, patch_ctl.packs_here(patch_ctl.cache_dir()))
        self.phase, self.skip = 'update', None
        out = upd.start_go(then=self._after_update, served=served)
        if out is not None:
            self.phase = None           # it did not start (it said why); a run that stops early keeps 'update' (stopped)
        c.changed('patchall')
        return out

    def _after_update(self):
        """Update saved (its job's end): the starter profile with the roster it saved, then Patch."""
        c = self.ctl
        rec = c.parts['update'].outcome or {}
        out = rec.get('out')
        folder = None
        if out is not None and getattr(out, 'ok', False) and rec.get('target') == install.TARGET_SAVE:
            folder = os.path.basename(os.path.normpath(out.folder))
        with c.lock:
            s = c.session
            self.skip = (s, len(s.history)) if s is not None else None
        self._patch_half(folder)

    def patch_anyway(self):
        """After an Update that stopped: Patch without it."""
        why = self._preflight()
        if why:
            self.ctl.say(why, 'caution')
            return {'error': why}
        return self._patch_half()

    def _patch_half(self, folder=None):
        c = self.ctl
        self.phase = 'patch'
        self._starter(folder)
        out = patch_ctl.one_click(c.setup, then=self._patched)
        if out is not None:
            self.phase = None
        c.changed('patchall')
        return out

    def _patched(self):
        self.phase, self.skip = None, None
        self.ctl.changed('patchall')

    # --- the starter profile ---------------------------------------------------------------------------------------
    def _starter(self, folder):
        """Skip the first-run setup: a new Profile0 for player 1 when there is none (never over one)."""
        c = self.ctl
        if not self.starter_on or not c.save_dir:
            return None
        try:
            if not starter.missing(c.save_dir):
                return None
            path = starter.write(c.save_dir, roster=roster_of(folder))
        except Exception as err:    # noqa: BLE001 - the patch goes in all the same; the first boot asks as before
            c.host.log(f'Starter profile: {err}')
            c.say(f'The starter profile was not written ({err}); the patch goes in all the same.', 'caution')
            return None
        c.host.log(f'Starter profile: {path}')
        return path

    def _starter_shows(self):
        c = self.ctl
        try:
            return bool(c.save_dir) and starter.missing(c.save_dir)
        except Exception:           # noqa: BLE001 - no save folder to look at: the switch does not show
            return False

    # --- the switches ----------------------------------------------------------------------------------------------
    def _remember(self):
        self.ctl.remember(**{PREF: {'update': self.update_on, 'starter': self.starter_on}})

    def set_update_on(self, on):
        c = self.ctl
        with c.lock:
            if c.busy:
                text = 'Wait for the patch to finish.'
            else:
                text, self.update_on = None, bool(on)
                self._remember()
        if text:
            c.say(text, 'caution')
            return {'error': text}
        c.changed('patchall')
        return None

    def set_starter(self, on):
        c = self.ctl
        with c.lock:
            busy = c.busy
        text = 'Wait for the patch to finish.' if busy else \
            'NHL 19 is running. Close it first.' if overlay.emulator_running() else None
        if text is None:
            self.starter_on = bool(on)
            self._remember()
        if text:
            c.say(text, 'caution')
            return {'error': text}
        c.changed('patchall')
        return None

    # --- the slice -------------------------------------------------------------------------------------------------
    def view(self):
        c = self.ctl
        shows = self._starter_shows()
        with c.lock:
            busy = bool(c.busy)
            upd = c.parts['update']
            roster = c.parts['rosters'].open_roster()
            runs = self._update_runs()
            stopped = (self.phase == 'update' and not busy and upd.running is None and upd.failed
                       and upd.kind == 'go')
            if self.phase == 'update' and not busy and not stopped and upd.running is None:
                self.phase = None   # the stopped update was closed, checked again or another roster opened
            phase = self.phase if busy or stopped else None
            name = (roster or {}).get('name') or ''
        title = (f'Updates {name} and saves it, then patches the game with the switches that are on (Enter).' if runs
                 else 'Patches the game with the switches that are on (Enter).')
        return {
            'update_on': self.update_on,
            'roster': bool(roster),
            'update_runs': runs,
            'skips': bool(self.update_on and roster and not runs),     # Update saved, Patch did not: skipped once
            'phase': phase,
            'stopped': stopped,
            # busy is not in here: the page adds the status line's live busy (a job may end with a narrower push)
            'button': {'enabled': bool(c.game.ok), 'title': title},
            'starter': {'show': shows, 'on': self.starter_on},
        }
