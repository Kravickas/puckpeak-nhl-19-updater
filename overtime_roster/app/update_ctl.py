"""Update: bring the open roster up to date with NHL.com (rosters, NHL 27 ratings, calendar, retirements) and save it.
docs/ui/update.md.

Go (update_go) is one job, as Legacy's: gather NHL.com's rosters and calendar (or the offline copy) without ctl.lock,
then plan, change the open roster (one bulk change: one Undo takes it back) and check it under the lock. Errors in the
check stop it there: nothing is written, the result lists them and Undo takes the update back. Otherwise it saves as
the Save card says through the Save bar's pipeline (install.run: a backup first, the save, the report) and shows the
result. ctl.busy stays set from the first step to the last; the Help bar says each step.

Check first (update_check) is Go's first two steps: nothing changes. Go uses its data again for the same season and
data source (and its plan while the roster has not changed since). Beta1's update_apply (change, no save: the Save bar
saves) stays. With unsaved edits Go asks first (the shell's ask_unsaved). The update's state stays on the Controller
(upd_*): the Game patch, the Calendar and Setup's default roster read it too.
"""
import datetime
import os
import time

from overtime_core import nhlcom, rosterupdate as U, sfo

from .. import VERSION
from . import install, jobs, myedits, paths, roster_card as RC, savegame, selfupdate, update
from .registry import Part
from .shell import friendly_date

SWITCHES = (
    ('rosters', 'NHL rosters', 'Trades, signings, call-ups and who left. New lines for every team that changed.',
     "Always on: every other part starts from today's NHL rosters. Utah plays in Arizona's place and Seattle is the "
     '32nd team.'),
    ('lines', 'Real lines and captains', 'Every NHL team plays the lines and letters of its last games, as in NHL '
     'Legacy.',
     "The announced lines, else the lines of the team's last 5 games on NHL.com, with the C and the As they wore: "
     'even strength, goalies, power play and penalty kill. Overtime, the shootout and the extra attackers are made '
     'from the 20 who dress. A unit whose player has moved on is made by rating. Lines you set yourself and saved '
     'stay when My edits is on (your line always wins). Off: lines by rating for every team that changed, as '
     'before.'),
    ('nhl27', 'NHL 27 ratings and types', "Every player's ratings, player type and contract from NHL 27.",
     "Players NHL 27 does not have keep EA's ratings. Draft info (year, round, pick) comes with the ratings."),
    ('calendar', 'Calendar', 'The real schedule of the season, for all 32 teams.',
     'The NHL plays 84 games a team since 2025-26. Pick 82 for the length NHL 19 was made for.'),
    ('retire', 'Retirements', 'Free agents no league lists any more retire.',
     'Off: they stay in the free agents, as they are now.'),
    ('myedits', 'My edits', 'Your saved player edits and lines go back in after the update.',
     'Every player edit you saved on the Roster tab (card, face & type, equipment) and the lines and letters you set '
     'on the Lines tab are kept in My edits and put back after the update. One the roster refuses (a number another player has now) is skipped and the result says '
     'why. Off: the update leaves every player as NHL.com has him. My edits on the Save bar lists them.'),
    ('drafts', 'Draft info', 'Year, round and pick of every player. It comes with the NHL 27 ratings.',
     'Draft info cannot be turned on or off on its own yet: it follows the NHL 27 ratings switch.'),
)
OPTIONS = ('lines', 'nhl27', 'calendar', 'retire', 'myedits')     # the switches the player turns (rosters, drafts follow)
LOCKED = {'rosters': 'NHL rosters are always on: the other parts start from them.',
          'drafts': 'Draft info follows the NHL 27 ratings switch. It cannot be turned off on its own yet.'}
GO_STEPS = (('check', 'NHL.com'), ('plan', 'Plan'), ('apply', 'Change'), ('verify', 'Check'), ('backup', 'Back up'),
            ('save', 'Save'), ('report', 'Report'))
CHECK_STEPS = GO_STEPS[:2]                         # Check first: NHL.com and the plan
SAVE_STEP = {'gather': 3, 'build': 3, 'verify': 3, 'backup': 4, 'install': 5, 'report': 6}   # install.STEPS on Go's
MODES = ('update', 'new', 'online', 'folder')
CANNOT_UPDATE = {
    'online': 'The online roster is replaced at every login: Go saves a new roster.',
    'game': "The game's own roster cannot be written over: Go saves a new roster.",
    'default': 'The Overtime default roster cannot be written over: Go saves a new roster.',
}
NAME_MAX = 40
BACKUPS_KEPT = savegame.BACKUPS_KEPT
CHECK_FRESH = 3600      # Go uses Check first's data for an hour
SEASONS = (update.DEFAULT_SEASON - 1, update.DEFAULT_SEASON, update.DEFAULT_SEASON + 1)
EXPECTED = (update.UpdateError, nhlcom.NhlComError, OSError, ValueError)
NOTHING_CHANGED = {'part': 'Nothing changed', 'text': 'The roster and your saves are as they were.'}


def changed_teams(todo):
    """The teams a plan changes (rosterupdate.Plan: moves, new players, releases)."""
    teams = {k for _pi, _n, f, t in todo.moves for k in (f, t) if k not in (None, 'FA')}
    teams |= {t for _r, t in todo.new if t not in (None, 'FA')}
    teams |= {f for _pi, _n, f in todo.releases if f not in (None, 'FA')}
    return teams


def season_label(year):
    return f'{year}-{(year + 1) % 100:02d}'


PATCH_FIRST = {
    'none': 'NHL 19 is not patched. Patch it first: without the patch the game has no Seattle or Utah and cannot go '
            'online.',
    'problem': 'The game patch has a problem. Open Game patch and press Patch again.',
    'older': "NHL 19 was patched by an older Overtime. Press Patch again so the game gets this version's default "
             'roster and calendars.',
}


def patch_notice(c):
    """The line over the Update tab when the game patch is missing, broken or made by an older Overtime (the patch
    remembers its version, patch_ctl): {'kind', 'text', 'tone'} or None. None until the Game patch tab has looked."""
    f = c.parts['patch'].facts()
    if not f['checked']:
        return None
    if not f['patched']:
        kind = 'none'
    elif f['problems']:
        kind = 'problem'
    else:
        by = selfupdate.parse_version(c.prefs.get('patched_by'))
        if by is not None and by >= selfupdate.parse_version(VERSION):
            return None
        kind = 'older'
    return {'kind': kind, 'text': PATCH_FIRST[kind], 'tone': 'bad' if kind == 'problem' else 'caution'}


def slot_number(folder):
    """RosterCustom4 is "Custom Roster 5" in the game."""
    return int(folder[len(savegame.CUSTOM):]) + 1


_MADE = {}      # param.sfo path -> (mtime, written by Overtime Roster)


def made_by_overtime(folder):
    """Whether Overtime Roster wrote this save (install.run labels its param.sfo DETAIL "... (Overtime Roster)")."""
    path = os.path.join(folder or '', 'sce_sys', 'param.sfo')
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return False
    hit = _MADE.get(path)
    if hit is None or hit[0] != mtime:
        try:
            with open(path, 'rb') as f:
                detail = str(sfo.values(f.read()).get('DETAIL', ''))
        except (OSError, ValueError):
            detail = ''
        hit = _MADE[path] = (mtime, detail.endswith('(Overtime Roster)'))
    return hit[1]


class UpdateCtl(Part):
    SLICES = {'update': 'view', 'update_list': 'list_view'}
    CALLS = {'update_go': 'update_go', 'update_check': 'update_check', 'update_apply': 'update_apply',
             'update_option': 'update_option', 'update_save_mode': 'save_mode', 'update_name': 'set_name',
             'update_slot': 'set_slot', 'update_folder_slot': 'set_folder_slot', 'update_result': 'result', 'update_list': 'set_list'}
    TAB = 'update'

    def __init__(self, ctl):
        super().__init__(ctl)
        up = ctl.prefs.get('update') or {}
        self.opts = {k: bool(up.get(k, True)) for k in OPTIONS}
        self.mode = None        # the Save card's mode the player picked (None: the open roster's own)
        self.name = ''          # the new roster's name ('' : the default name)
        self.slot = None        # the save to write over when 15 of 15 are used
        self.fslot = None       # the roster slot of a folder for another PC (None: the next free one here)
        self.running = None     # 'check' | 'go' | 'apply' while a job runs
        self.kind = 'go'        # what ran last: 'check' | 'go' | 'apply' (the steps row)
        self.at = 0             # the step (GO_STEPS) the run is at, or stopped at
        self.failed = False     # the last run stopped: its step is red until the result is closed
        self.outcome = None     # what the last run gave (the result card): see _record
        self.checked = None     # Check first's data for Go: {key, gathered, plan, state, at}
        self.closed = False     # the result card was closed
        self.listing = False    # the list of changes is open

    def roster_changed(self):
        self.mode, self.slot, self.closed, self.listing = None, None, False, False
        self.outcome, self.failed = None, False

    # --- the switches ------------------------------------------------------------------------------------------------
    def update_option(self, key, value):
        c = self.ctl
        if key in LOCKED:
            c.say(LOCKED[key], 'caution')
            return None
        with c.lock:
            if c.busy or self.running:
                text = 'Wait for the update to finish.'
            elif key == 'season':
                try:
                    year = int(value)
                except (TypeError, ValueError):
                    year = None
                text = None if year in SEASONS else 'Pick one of the seasons shown.'
                if text is None and year != c.upd_season:
                    c.upd_season = year
                    c.upd_gathered = None
                    c._fresh_update()
                    self.checked = None
            elif key == 'per32':
                text = None if str(value) in ('82', '84') else 'Pick 84 or 82 games.'
                if text is None:
                    c.upd_per32 = None if str(value) == '84' else 82
            elif key == 'offline':
                text = None
                c.upd_offline = bool(value)
                if self.outcome and self.outcome.get('error'):     # the stopped run: try again with the other data
                    self.outcome, self.failed = None, False
            elif key in OPTIONS:
                text = None
                self.opts[key] = bool(value)
            else:
                text = f'There is no option called {key}.'
            if text is None:
                c.remember(update={'season': c.upd_season, 'per32': c.upd_per32, 'offline': c.upd_offline,
                                   **self.opts})
        if text:
            c.say(text, 'caution')
            return {'error': text}
        c.changed('update', 'update_list', 'calendar')
        return None

    # --- the steps ---------------------------------------------------------------------------------------------------
    def _upd_step(self, key, state, text=''):
        """Beta1's steps (update.STEPS: gather's rosters, calendar, pack; plan, apply, verify): the snapshot's list and
        Details."""
        c = self.ctl
        with c.lock:
            c.upd_steps[key] = {'state': state, 'text': text}
        if text and state in ('ok', 'skip', 'fail'):
            c.host.log(f'{dict(update.STEPS)[key]}: {text}')
        c.changed('update')

    def _step(self, i, text):
        """The run is at step i (GO_STEPS): the Save card lights it, the Help bar says `text`. ctl.busy stays set."""
        c = self.ctl
        n = len(CHECK_STEPS if self.kind == 'check' else GO_STEPS)
        with c.lock:
            self.at = i
            c.busy = text
        c.say(text, 'info', min(1.0, (i + 1) / n))
        c.changed('update')

    def _gather(self, season, offline, schedule):
        """NHL.com's (or the offline copy's) rosters and calendar, the data pack, NHL 27: no lock (the network)."""
        c = self.ctl
        client = nhlcom.Client(cache_dir=paths.app_dir('cache'))
        more = {} if schedule else {'schedule': False}   # the Calendar switch off: no calendar does not stop it
        return update.gather(client, season, paths.app_dir('cache'), fetch=update.fetch, offline=offline,
                             step=self._upd_step, log=c.host.log, **more)

    def _check_text(self, offline):
        date = update.offline_date(paths.app_dir('cache'))
        if offline:
            return f'Reading the offline copy from {date}...' if date else 'Reading the offline copy...'
        return "Checking NHL.com for today's rosters..."

    @staticmethod
    def _state(session):
        """What the plan was made on: the roster and its newest change."""
        return id(session), len(session.history), id(session.history[-1]) if session.history else None

    def _reuse(self, season, offline, schedule, session):
        """(gathered, plan or None) of Check first when Go may use them again: the same season and data source, an
        hour old at most, with a calendar when the Calendar switch is on; the plan only while the roster is as it was
        then. (None, None) otherwise. Call under the lock."""
        ck = self.checked
        if not ck or ck['key'] != (season, offline) or time.monotonic() - ck['at'] > CHECK_FRESH:
            return None, None
        if schedule and not ck['gathered'].games:
            return None, None
        return ck['gathered'], ck['plan'] if ck['state'] == self._state(session) else None

    def _record(self, run, **kv):
        """A run's record (the result card and the list of changes are made from it)."""
        c = self.ctl
        out = {'run': run, 'season': c.upd_season, 'per32': c.upd_per32, 'offline': c.upd_offline,
               'opts': dict(self.opts), 'when': datetime.datetime.now(), 'gathered': None, 'todo': None, 'rep': None,
               'issues': [], 'problems': [], 'out': None, 'change': None, 'undone': False, 'error': None,
               'retiring': None, 'teams': None, 'reused': False, 'myedits': None,
               'kept': myedits.count(c.parts['roster'].kept()) if self.opts.get('myedits') else 0}
        out.update(kv)
        return out

    # --- My edits ----------------------------------------------------------------------------------------------------
    def _aliases(self, session, rec):
        """The kept players the user renamed, for the plan (myedits.aliases). Call under the lock."""
        if not rec['kept']:
            return None
        c = self.ctl
        return myedits.aliases(c.parts['roster'].kept(), session, c.parts['roster'].clock(session)) or None

    def _replay(self, session, rec):
        """My edits back in after the update, folded into its change (one Undo takes both back). Call under the
        lock."""
        if not rec['kept']:
            return None
        c = self.ctl
        clock = RC.Clock(session, RC.roster_shift(session.db, c.upd_season))   # the update moved the birth dates
        out = myedits.replay(session, clock, c.parts['roster'].kept(),
                             model_of=lambda table: c.editors._model(session, table),
                             fold=lambda ch: session.fold(ch, rec['change']))
        c.host.log(f"My edits: {out['applied']} applied, {len(out['skipped'])} skipped")
        for sk in out['skipped'][:100]:
            c.host.log(f"  My edits skipped: {sk['who']} ({sk['part']}): {sk['why']}")
        return out

    def _begin(self, run, busy):
        """A run starts (call under the lock): busy from now until it ends."""
        c = self.ctl
        c.busy = busy
        self.running = self.kind = run
        self.at, self.failed = 0, False
        self.closed = self.listing = False

    # --- Check first -------------------------------------------------------------------------------------------------
    def update_check(self):
        """Check first: gather (NHL.com or the offline copy) and plan; nothing in the roster changes."""
        c = self.ctl
        with c.lock:
            if not c.session:
                return {'error': 'Pick a roster in Setup first.'}
            if c.busy:
                return None
            c._fresh_update()
            session, season, offline = c.session, c.upd_season, c.upd_offline
            rec = self._record('check')
            self._begin('check', self._check_text(offline))
            self.outcome = None
        c.changed('update', 'update_list', 'app', 'source', 'editor')

        def work():
            self._step(0, self._check_text(offline))
            gathered = rec['gathered'] = self._gather(season, offline, rec['opts']['calendar'])
            self._step(1, 'Planning the changes...')
            self._upd_step('plan', 'run')
            with c.lock:
                todo = update.plan(session.db, gathered, self._aliases(session, rec))
                if rec['opts']['retire']:
                    rec['retiring'] = update.retirees(session.db, gathered, rec['opts']['nhl27'])
                state = self._state(session)
            sm = todo.summary()
            self._upd_step('plan', 'ok', f"{sm['stay']} stay, {sm['moves']} move, {sm['new']} new, "
                                         f"{sm['releases']} leave")
            rec['todo'] = todo
            return rec, state

        def done(result):
            rec, state = result
            with c.lock:
                c.busy = None
                self.running = None
                c.upd_gathered, c.upd_plan = rec['gathered'], rec['todo']
                self.checked = {'key': (season, offline), 'gathered': rec['gathered'], 'plan': rec['todo'],
                                'state': state, 'at': time.monotonic()}
                self.outcome = rec
                say = self.result_view()['say']
            c.host.log(f"Update plan: {rec['todo'].summary()}")
            c.say(say, 'good')
            c.changed('update', 'update_list', 'app', 'source', 'editor', 'calendar')

        def failed(message):
            self._stopped(rec, message)
        jobs.run(work, done, failed, expected=EXPECTED)
        return None

    def _stopped(self, rec, message):
        """A run stopped on an error at its current step (self.at)."""
        c = self.ctl
        with c.lock:
            c.busy = None
            self.running = None
            self.failed = True
            self.outcome = dict(rec, error=message, at=self.at)
            say = self.result_view()['say']
        c.host.log(message)
        c.say(say, 'bad')
        c.changed_all()

    # --- Go ----------------------------------------------------------------------------------------------------------
    def update_go(self):
        """Go: unsaved edits ask first (the shell: Save first, Lose them, Cancel); then one job (start_go)."""
        c = self.ctl
        with c.lock:
            if c.busy or self.running:
                return None         # the Help bar says what runs; Go is off until it ends
            roster = c.parts['rosters'].open_roster()
            why = 'Pick a roster in Setup first.' if roster is None else self.save_view(roster)['block']
        if why:
            c.say(why, 'caution')
            return {'error': why}
        return c.shell.ask_unsaved('run the update', go=self._go_on)

    def _go_on(self):
        """After the question: Save first saved the edits (nothing is left to drop); Lose them drops them."""
        self.drop_edits()
        return self.start_go()

    def drop_edits(self):
        """Take back the edits made since the roster was saved or opened (the unsaved question's Lose them)."""
        return self.ctl.parts['save'].discard()

    def start_go(self):
        """Go's job: NHL.com (no lock), plan, change, check (under the lock); on errors stop, else back up, save and
        report (install.run, under the lock). Returns at once."""
        c = self.ctl
        with c.lock:
            roster = c.parts['rosters'].open_roster()
            if roster is None:
                return {'error': 'Pick a roster in Setup first.'}
            if c.busy:
                return None
            sv = self.save_view(roster)
            if sv['block']:
                c.say(sv['block'], 'caution')
                return {'error': sv['block']}
            session, season, offline, per32 = c.session, c.upd_season, c.upd_offline, c.upd_per32
            mode = sv['mode']
            fslot = self.fslot if mode == 'folder' else None
            if mode == 'online':
                target, name, slot = install.TARGET_EXPORT, 'Online roster', None
            elif mode == 'folder':
                target, name, slot = install.TARGET_FOLDER, sv['name'], None
            elif mode == 'update':
                target, name, slot = install.TARGET_SAVE, roster['name'], roster['id']
            else:
                target, name, slot = install.TARGET_SAVE, sv['name'], self.slot if sv['full'] else None
            over = next((s.name for s in c.sources if s.kind == 'save' and s.info.get('folder') == slot), None) \
                if mode == 'new' and slot else None
            rec = self._record('go', mode=mode, target=target, name=name, slot=slot, over=over, roster=roster)
            gathered, todo = self._reuse(season, offline, rec['opts']['calendar'], session)
            rec['reused'] = gathered is not None
            c._fresh_update()
            self._begin('go', 'Updating the roster...')
            self.outcome = None
        c.changed('update', 'update_list', 'app', 'save', 'source', 'editor')
        opts = rec['opts']

        def istep(key, state, text=''):
            """install.run's steps on Go's (called under the lock: the steps row shows when it is let go)."""
            i = SAVE_STEP[key]
            if state == 'run' and i != self.at:
                if i == 4 and mode == 'folder':
                    self._step(i, 'Nothing on this PC is changed...')
                elif i == 4:
                    self._step(i, f'Backing up {name}...' if mode == 'update' else
                               'Backing up the save it replaces...' if slot else 'Backing up your saves...')
                elif i == 5:
                    self._step(i, 'Writing roster_h2h.db...' if mode == 'online' else
                               f'Building the folder for {name}...' if mode == 'folder' else f'Saving {name}...')
                elif i == 6:
                    self._step(i, 'Writing the list of changes...')
            if state == 'fail':
                self.at = i
            if text and state in ('ok', 'skip', 'fail'):
                c.host.log(f'{dict(install.STEPS)[key]}: {text}')

        def work():
            nonlocal gathered, todo
            if gathered is None:
                self._step(0, self._check_text(offline))
                gathered = self._gather(season, offline, opts['calendar'])
            else:
                self._step(0, 'Using the data Check first found...')
            rec['gathered'] = gathered
            self._step(1, 'Planning the changes...')
            with c.lock:
                if c.session is not session:
                    raise update.UpdateError('Another roster was opened: nothing was changed.')
                if todo is None:
                    todo = update.plan(session.db, gathered, self._aliases(session, rec))
            rec['todo'] = todo
            sm = todo.summary()
            self._step(1, f"Planning: {sm['moves']} move, {sm['new']} new, {sm['releases']} leave...")
            self._upd_step('plan', 'ok', f"{sm['stay']} stay, {sm['moves']} move, {sm['new']} new, "
                                         f"{sm['releases']} leave")
            self._step(2, 'Changing the roster: rosters, lines, ratings, calendar...')
            with c.lock:
                rep = update.run(session, c.game, gathered, todo, per32=per32, names=c._code, log=c.host.log,
                                 nhl27=opts['nhl27'], schedule=opts['calendar'], retire=opts['retire'],
                                 expansion=True, lines=opts['lines'])
                rec['rep'], rec['change'] = rep, session.history[-1]
                rec['myedits'] = self._replay(session, rec)
            self._upd_step('apply', 'ok', f"{len(rep.created)} created, {len(rep.signed)} signed, "
                                          f"{len(rep.lines)} lines rebuilt, {rep.ratings} rating value(s)")
            self._step(3, 'Checking that the roster opens in NHL 19...')
            with c.lock:
                issues = rec['issues'] = session.verify()
                rec['teams'] = update.team_count(session.db)
                rec['short'], rec['both'] = update.heads_up(session.db)
                errors = [self._issue_text(session, i) for i in issues if i.level == 'error']
            rec['problems'] = list(dict.fromkeys(errors + [str(p) for p in rep.problems]))
            n = len(rec['problems'])
            self._upd_step('verify', 'fail' if n else 'ok',
                           f'{n} problem(s): nothing was saved' if n else '0 errors: ready to save')
            if n:
                return rec          # stopped: nothing is written, Undo takes the update back
            with c.lock:
                if c.session is not session:
                    raise update.UpdateError('Another roster was opened: nothing was saved.')
                rec['out'] = install.run(session, c.game, target, name, c.save_dir, paths.app_dir('exports'),
                                         step=istep, log=c.host.log, overwrite=slot, folder_slot=fslot)
                rec['written'] = list(session.history)
            return rec

        def done(rec):
            out = rec['out']
            ok = bool(out and out.ok)
            folder = os.path.basename(os.path.normpath(out.folder)) if ok and target == install.TARGET_SAVE else ''
            with c.lock:
                c.busy = None
                self.running = None
                self.checked = None
                c.upd_gathered, c.upd_plan, c.upd_report = rec['gathered'], rec['todo'], rec['rep']
                c.issues = rec['issues']
                if not ok:
                    self.failed = True
                    if out is None:
                        self.at = 3      # the check found errors
                if ok and folder:
                    rec['backups'] = self._backups()
                    self._remember_saved(folder, rec)
                    self.mark_saved(rec['written'])
                    self.mode, self.name, self.slot = None, '', None
                self.outcome = rec
            if ok:
                c.refresh_sources(quiet=True)
                if folder and mode != 'update':
                    c.parts['save'].opened(folder)      # the new save is the open roster: Save then updates it
            for prob in rec['problems'][:100]:
                c.host.log(f'  problem: {prob}')
            with c.lock:
                r = self.result_view()
            c.say(r['say'], ('caution' if r.get('log') else 'good') if ok else 'bad', 1.0 if ok else None)
            c.changed_all()

        def failed(message):
            self._stopped(rec, message)
        jobs.run(work, done, failed, expected=EXPECTED)
        return None

    @staticmethod
    def _issue_text(session, issue):
        try:
            team = session.team_name(issue.team) if issue.team is not None else ''
        except (KeyError, IndexError, TypeError):
            team = ''
        return f'{team}: {issue.message}' if team else issue.message

    def mark_saved(self, written):
        """The roster as written is the saved one now: the Save bar has nothing unsaved."""
        self.ctl.parts['save'].mark_saved(written)

    def _remember_saved(self, folder, rec):
        """What Go wrote into a save (the From bar shows it): when, by which version, from which data."""
        c = self.ctl
        done = {k: v for k, v in (c.prefs.get('update_saved') or {}).items() if k in savegame.slot_names()}
        done[folder] = {'when': rec['when'].strftime('%Y-%m-%d %H:%M'), 'version': VERSION,
                        'data': self.data_words(rec), 'season': rec['season']}
        c.remember(update_saved=done)

    @staticmethod
    def _backups():
        """How many backups of the save folder are kept (install.run writes them next to the exports and keeps the
        newest 10: savegame.prune_backups)."""
        where = os.path.normpath(os.path.join(paths.app_dir('exports'), '..', 'backups'))
        savegame.prune_backups(where, BACKUPS_KEPT)
        try:
            return len([n for n in os.listdir(where) if os.path.isdir(os.path.join(where, n))])
        except OSError:
            return 0

    # --- beta1's Apply (change, no save) -----------------------------------------------------------------------------
    def update_apply(self):
        """Do the update in the open roster (one Undo takes it back); the plan is made again first, on the roster as
        it is now. Nothing is saved: the Save bar saves it."""
        c = self.ctl
        with c.lock:
            if not c.session or c.upd_gathered is None:
                return {'error': 'Check for the update first.'}
            if c.busy:
                return None
            session, gathered, per32 = c.session, c.upd_gathered, c.upd_per32
            rec = self._record('apply', gathered=gathered)
            self._begin('apply', 'Updating the roster...')
            self.at = 2
            self.outcome = None
        c.say(c.busy, 'info', -1)
        c.changed('update', 'update_list', 'app', 'source', 'editor')
        opts = rec['opts']

        def work():
            with c.lock:
                self._upd_step('apply', 'run')
                todo = update.plan(session.db, gathered, self._aliases(session, rec))
                rep = update.run(session, c.game, gathered, todo, per32=per32, names=c._code, log=c.host.log,
                                 nhl27=opts['nhl27'], schedule=opts['calendar'], retire=opts['retire'],
                                 expansion=True, lines=opts['lines'])
                rec.update(todo=todo, rep=rep, change=session.history[-1])
                rec['myedits'] = self._replay(session, rec)
                self._upd_step('apply', 'ok', f"{len(rep.created)} created, {len(rep.signed)} signed, "
                                              f"{len(rep.lines)} lines rebuilt, {rep.ratings} rating value(s)")
                self._upd_step('verify', 'run')
                self.at = 3
                issues = rec['issues'] = session.verify()
                rec['teams'] = update.team_count(session.db)
                rec['short'], rec['both'] = update.heads_up(session.db)
                return todo, rep, issues

        def done(result):
            todo, rep, issues = result
            errors = [i for i in issues if i.level == 'error']
            with c.lock:
                c.busy = None
                self.running = None
                c.upd_plan, c.upd_report = todo, rep
                c.issues = issues
                rec['problems'] = [str(i) for i in errors] + [str(p) for p in rep.problems]
                self.failed = bool(rec['problems'])
                self.outcome = rec
            bad = len(errors) + len(rep.problems)
            self._upd_step('verify', 'fail' if bad else 'ok',
                           f'{len(errors)} roster error(s), {len(rep.problems)} other problem(s)' if bad
                           else '0 errors: ready to save')
            for prob in rep.problems[:100]:
                c.host.log(f'  problem: {prob}')
            c.say('Roster updated (not saved yet): press Save to keep it.' if not bad else
                  f'Updated with {bad} problem(s): see Details, or Undo.', 'good' if not bad else 'bad')
            c.changed_all()

        def failed(message):
            self._upd_step('apply', 'fail', message)
            self._stopped(rec, message)
        jobs.run(work, done, failed, expected=(U.UpdateError, ValueError))
        return None

    def snap_update(self):
        """Beta1's snapshot (tests and tools read it)."""
        c = self.ctl
        with c.lock:
            g, todo, rep, s = c.upd_gathered, c.upd_plan, c.upd_report, c.session

            def where(key):
                return 'FA' if key in (None, 'FA') else c._code(key[1], key[0])
            plan = None
            if todo is not None:
                plan = {'summary': todo.summary(),
                        'moves': [{'name': n, 'from': where(f), 'to': where(t)} for _pi, n, f, t in todo.moves[:300]],
                        'new': [{'name': f"{r['first']} {r['last']}", 'to': where(t), 'pos': r.get('position', ''),
                                 'num': r.get('number')} for r, t in todo.new[:300]],
                        'releases': [{'name': n, 'from': where(f)} for _pi, n, f in todo.releases[:300]]}
            season = c.upd_season
            return {
                'loaded': bool(s), 'busy': bool(c.busy), 'roster': s.source_name if s else '',
                'season': season, 'season_label': season_label(season), 'seasons': list(SEASONS),
                'per32': c.upd_per32 or 84, 'offline': c.upd_offline, 'base': nhlcom.BASE,
                'online_roster': bool(s) and U.CUSTOM_ROSTER not in s.db,
                'steps': [{'key': k, 'label': lab, **c.upd_steps[k]} for k, lab in update.STEPS],
                'sources': g.sources if g else {}, 'plan': plan,
                'report': rep.as_dict() if rep else None,
                'can_check': bool(s) and not c.busy, 'can_apply': bool(s) and not c.busy and g is not None,
                'can_go': bool(s) and not c.busy,
            }

    # --- the Save card -----------------------------------------------------------------------------------------------
    def save_mode(self, mode):
        c = self.ctl
        if mode not in MODES:
            return None
        with c.lock:
            why = self.cannot_update(c.parts['rosters'].open_roster())
            if not (mode == 'update' and why):
                self.mode = mode
        if mode == 'update' and why:
            c.say(why, 'caution')
            return {'error': why}
        c.changed('update')
        return None

    def set_name(self, text):
        self.name = str(text or '')[:NAME_MAX]
        self.ctl.changed('update')

    def set_slot(self, ident):
        c = self.ctl
        with c.lock:
            known = any(s.kind == 'save' and s.info.get('folder') == ident for s in c.sources)
            self.slot = ident if known and ident in savegame.slot_names() else None
        if not known:
            c.say('That save is not there any more.', 'caution')
        c.changed('update')

    def set_folder_slot(self, name):
        """The slot the folder for another PC is made for ('' / None: automatic)."""
        self.fslot = name if name in savegame.slot_names() else None
        self.ctl.changed('update')

    def result(self, what='close'):
        """The result's close (✕) and its Undo (takes the update back while it is the roster's newest change)."""
        c = self.ctl
        if what == 'undo':
            return self.undo_update()
        if what == 'close':
            with c.lock:
                self.closed, self.listing, self.failed = True, False, False
        c.changed('update', 'update_list')
        return None

    def undo_update(self):
        c = self.ctl
        with c.lock:
            o = self.outcome or {}
            s = c.session
            ok = o.get('change') is not None and s is not None and bool(s.history) and s.history[-1] is o['change']
        if not ok:
            text = 'The update is not the newest change any more: take it back on the Roster tab.'
            c.say(text, 'caution')
            return {'error': text}
        c.undo()        # the Roster tab's Undo (beta1's name): the newest change, the whole update
        with c.lock:
            if self.outcome is o:
                self.outcome = dict(o, undone=True)
            self.failed = False
            self.listing = False
        c.changed('update', 'update_list', 'save', 'rail')
        return None

    def set_list(self, on):
        self.listing = bool(on)
        self.ctl.changed('update_list')

    @staticmethod
    def cannot_update(roster):
        if roster is None or roster['kind'] == 'save':
            return None
        return CANNOT_UPDATE['online'] if roster['kind'] == 'online' else \
            CANNOT_UPDATE['game'] if roster['id'] == 'game' else CANNOT_UPDATE['default']

    def save_view(self, roster):
        """The Save card (call under the lock)."""
        c = self.ctl
        why = self.cannot_update(roster)
        mode = self.mode or ('new' if why else 'update')
        if mode == 'update' and why:
            mode = 'new'
        saves = [s for s in c.sources if s.kind == 'save' and s.info.get('folder', '').startswith(savegame.CUSTOM)]
        used = {s.info['folder'] for s in saves}
        free = next((n for n in savegame.slot_names() if n not in used), None)
        full = mode == 'new' and free is None
        slot = self.slot if self.slot in used else None
        name_default = f'Roster {datetime.datetime.now():%Y-%m-%d %H:%M}'
        name = self.name or name_default
        tone, block = '', None
        if mode == 'update':
            note = f'A backup copy is made first. The newest {BACKUPS_KEPT} are kept.'
        elif mode == 'online':
            note = 'Writes roster_h2h.db for an Overtime server. Your saves stay as they are.'
        elif mode == 'folder':
            note = 'Builds a folder to copy to the PC that runs shadPS4. Your saves stay as they are.'
        elif full and not slot:
            note = f'All {savegame.SLOTS} roster saves are used. Pick the one to write over: it is backed up first.'
            tone, block = 'caution', 'Pick the save to write over first.'
        elif full:
            over = next((s.name for s in saves if s.info['folder'] == slot), slot)
            note = f'Writes over {over}. A backup copy is made first.'
        else:
            note = f'Saved as Custom Roster {slot_number(free)} in the game.'
        if mode in ('new', 'folder') and not name.strip():
            block = 'Type a name for the new roster first.'
        rosters = c.parts['rosters']
        return {
            'mode': mode,
            'modes': [{'value': 'update', 'label': 'Update this roster', 'disabled': bool(why),
                       'title': why or 'Write over the open roster'},
                      {'value': 'new', 'label': 'Save as a new roster'},
                      {'value': 'folder', 'label': 'Folder for another PC',
                       'title': 'A folder to copy into shadPS4 on another PC, with the steps'},
                      {'value': 'online', 'label': 'Online roster file', 'title': 'roster_h2h.db for an Overtime server'}],
            'folder_slot': self.fslot if self.fslot in savegame.slot_names() else None,
            'folder_slots': [{'value': n, 'label': f'Custom Roster {slot_number(n)}'} for n in savegame.slot_names()]
            if mode == 'folder' else None,
            'why': why if mode == 'new' else None,
            'name': name, 'name_default': name_default,
            'used': len(saves), 'max': savegame.SLOTS, 'full': full, 'slot': slot,
            'slots': [{'value': s.info['folder'], 'label': f'{s.name}  ({rosters.saved_on(s)})'} for s in saves]
            if full else None,
            'target': roster['name'] if mode == 'update' else 'roster_h2h.db' if mode == 'online' else name,
            'note': {'text': note, 'tone': tone},
            'block': block,
        }

    # --- the slices --------------------------------------------------------------------------------------------------
    def from_view(self, roster):
        c = self.ctl
        rosters = c.parts['rosters']
        src = rosters.source(roster['id'])
        done = (c.prefs.get('update_saved') or {}).get(roster['id']) if roster['kind'] == 'save' else None
        note = ''
        if roster['kind'] == 'online':
            tag = {'text': 'Online', 'tone': 'info'}
            note = 'The roster the Overtime server sent at login.'
        elif roster['kind'] == 'start':
            tag = {'text': 'NHL 19', 'tone': ''}
            note = 'The roster NHL 19 came with (2018-19).' if roster['id'] == 'game' else ''
        elif done:
            tag = {'text': f"Overtime {done.get('version', '')}".strip(),
                   'tone': 'good' if done.get('version') == VERSION else ''}
            day = friendly_date(str(done.get('when', ''))[:10])
            data = done.get('data') or 'NHL.com'
            note = f'Updated from {data} {day}.' if day in ('today', 'yesterday') else f'Updated from {data} on {day}.'
        elif src is not None and made_by_overtime(src.path):
            tag = {'text': 'Overtime', 'tone': ''}
        else:
            tag = {'text': 'Saved in the game', 'tone': ''}
        date = rosters.saved_on(src) if roster['kind'] != 'start' else ''
        return {'id': roster['id'], 'name': roster['name'], 'kind': roster['kind'], 'date': date or None, 'tag': tag,
                'note': note}

    def run_view(self):
        """The steps row while a run goes and after one stopped (red at its step); None: faint, before a run."""
        if self.running is None and not self.failed:
            return None
        kind = 'check' if self.kind == 'check' else 'go'
        steps = CHECK_STEPS if kind == 'check' else GO_STEPS
        return {'kind': kind, 'at': min(self.at, len(steps) - 1), 'steps': [{'key': k, 'label': lab} for k, lab in steps],
                'failed': self.failed and self.running is None}

    @staticmethod
    def data_words(rec):
        """Where the run's rosters came from, in words ('NHL.com', 'the offline copy from 2026-10-18')."""
        g = rec.get('gathered')
        src = str(((g.sources if g else None) or {}).get('rosters', ''))
        if src.startswith('data pack'):
            date = src[len('data pack'):].strip()
            return f'the offline copy from {date}' if date else 'the offline copy'
        if src:
            return src
        return 'the offline copy' if rec.get('offline') else 'NHL.com'

    def data_label(self, rec):
        """The result's Data line: 'NHL.com, 2026-10-21 14:05', 'Offline copy from 2026-10-18'."""
        words = self.data_words(rec)
        if words == 'NHL.com':
            return f"NHL.com, {rec['when']:%Y-%m-%d %H:%M}"
        if not words.startswith('the offline copy'):
            return words
        label = 'Offline copy' + words[len('the offline copy'):]
        return label if rec.get('offline') else f'{label} (NHL.com did not answer)'

    @staticmethod
    def _part_lines(rec, would):
        """One line per part of the update: what it changed (or would change)."""
        o, rep, todo, g = rec['opts'], rec['rep'], rec['todo'], rec['gathered']
        sm = todo.summary()
        v = (lambda now, then: then) if would else (lambda now, then: now)
        if would:
            teams = changed_teams(todo)
            rosters = (f"{sm['moves']} players would move, {sm['new']} are new and {sm['releases']} would leave. "
                       f'{len(teams)} teams change.')
        else:
            rosters = (f"{sm['moves']} players moved, {sm['new']} are new and {sm['releases']} left. "
                       f'New lines for {len(rep.lines)} teams.')
        out = [{'part': 'NHL rosters', 'text': rosters}]
        real = (rep.real or {}) if rep is not None else {}
        part = (getattr(g, 'lines', None) or {}) if g else {}
        dates = sorted(str(e.get('date') or '') for e in part.values() if isinstance(e, dict))
        if not o.get('lines', True):
            text = v('Off: lines by rating.', 'Off: lines by rating.')
        elif real.get('lined') or real.get('lettered'):
            n, kept = len(real.get('lined') or []), len(real.get('refused') or {})
            text = (f"{n} teams play their real lines (games to {real['date'] or dates[-1]}), "
                    f"{len(real.get('lettered') or [])} have their real captains."
                    + (f' {kept} kept lines by rating: Details lists why.' if kept else ''))
        elif would and part:
            text = f'{len(part)} teams would play their real lines and captains (games to {dates[-1]}).'
        else:
            text = v('No real lines in the data here: lines by rating.', 'No real lines in the data here: lines by '
                                                                         'rating.')
        out.append({'part': 'Real lines', 'text': text})
        n27 = (g.nhl27 or {}) if g else {}
        if not o['nhl27']:
            text = v('Left as they were.', 'Off: left as they are.')
        elif rep is not None and (rep.nhl27 or {}).get('rated'):
            text = f"{rep.nhl27['rated']:,} players have NHL 27 ratings and types."
        elif would and n27.get('players'):
            text = f"{len(n27['players']):,} players in NHL 27 bring their ratings and types."
        elif rep is not None and rep.ratings:
            text = f"No NHL 27 pack here: {rep.ratings:,} of EA's rating values were used."
        elif would and g is not None and g.ratings:
            text = "No NHL 27 pack here: EA's ratings are used."
        else:
            text = v('No ratings data here: left as they were.', 'No ratings data here: left as they are.')
        out.append({'part': 'NHL 27 ratings', 'text': text})
        label = season_label(rec['season'])
        if not o['calendar']:
            text = v('Left as it was.', 'Off: left as it is.')
        elif rep is not None and rep.calendar:
            cal = rep.calendar.get('nhl32schedule') or next(iter(rep.calendar.values()))
            text = f"{label}, {cal['per_team'][1]} games for each of the 32 teams."
        elif would and g is not None and g.games:
            text = f"{label}, {rec['per32'] or 84} games for each of the 32 teams."
        else:
            text = v('No calendar found: left as it was.', 'No calendar found: left as it is.')
        out.append({'part': 'Calendar', 'text': text})
        if not o['retire']:
            text = v('Nobody retired.', 'Off: nobody retires.')
        elif rep is not None:
            text = f'{len(rep.retired)} free agents retired.'
        elif rec.get('retiring') is not None:
            text = f"{rec['retiring']} free agents would retire."
        else:
            text = 'Nothing says who still plays: nobody retires.'
        out.append({'part': 'Retirements', 'text': text})
        me, n = rec.get('myedits'), rec.get('kept') or 0
        if me is not None:
            skipped = len(me['skipped'])
            text = f"{me['applied']} put back" + (f', {skipped} skipped: see the warnings.' if skipped else '.')
            out.append({'part': 'My edits', 'text': text})
        elif would and n:
            out.append({'part': 'My edits', 'text': f"{n} player{'s' if n != 1 else ''}' saved edits go back in."})
        return out

    def result_view(self):
        """The result card of the last run (call under the lock), or None."""
        o = self.outcome
        if self.closed or o is None:
            return None
        c = self.ctl
        if o['undone']:
            return {'kind': 'plan', 'title': 'The update was taken back',
                    'lines': [{'part': 'Undo', 'text': 'The roster is as it was before the update. Nothing was saved.'}],
                    'issues': [], 'items': [['Data', self.data_label(o)]], 'folder': None, 'report': None,
                    'can_play': False, 'can_undo': False, 'say': 'The update was taken back. Nothing was saved.'}
        if o['error']:
            return self._error_result(o)
        if o['run'] == 'check':
            sm = o['todo'].summary()
            return {'kind': 'plan', 'title': 'What Go would change', 'lines': self._part_lines(o, True), 'issues': [],
                    'items': [['Data', self.data_label(o)], ['Saved', 'Nothing yet. Press Go to update and save.']],
                    'folder': None, 'report': None, 'can_play': False, 'can_undo': False,
                    'say': f"Go would move {sm['moves']} players, add {sm['new']} and let {sm['releases']} go. "
                           'Nothing was saved.'}
        can_undo = o['change'] is not None and c.session is not None and bool(c.session.history) \
            and c.session.history[-1] is o['change']
        lines = self._part_lines(o, False)
        warnings = [i for i in o['issues'] if i.level != 'error']
        if o['problems']:
            n = len(o['problems'])
            return {'kind': 'bad', 'title': 'Not saved: the check found problems',
                    'lines': lines + [{'part': 'Checked', 'text': f'{n} problem{"s" if n != 1 else ""} in the updated '
                                                                  'roster, so nothing was saved.'},
                                      {'part': 'What now', 'text': 'Undo takes the update back. Details lists every '
                                                                   'problem.'}],
                    'issues': o['problems'][:20], 'items': [['Data', self.data_label(o)], ['Saved', 'Nothing.']],
                    'folder': None, 'report': None, 'can_play': False, 'can_undo': can_undo,
                    'say': f'The update stopped: the check found {n} problem{"s" if n != 1 else ""}. Nothing was '
                           'saved. Undo takes it back.'}
        checked = (f"The roster opens in NHL 19 with {o['teams']} teams." if o['teams'] else
                   'The check found no errors.')
        lines.append({'part': 'Checked', 'text': checked})
        issues = []
        if warnings:
            issues.append(f'{len(warnings)} warning{"s" if len(warnings) != 1 else ""} in the check: Details lists '
                          'them.')
        if o['rep'] is not None and o['rep'].skipped_lines:
            issues.append(f"{len(o['rep'].skipped_lines)} teams kept their lines: not enough players to build new "
                          'ones.')
        issues += [f'Heads up: {t}. The game hangs on the first game with this team: it needs 2 goalies and 18 skaters.'
                   for t in (o.get('short') or [])[:3]]
        both = o.get('both') or []
        if both:
            issues.append(f"{len(both)} free agent{'s are' if len(both) != 1 else ' is'} also on a club: "
                          + ', '.join(both[:5]) + (' and more.' if len(both) > 5 else '.'))
        skipped = (o.get('myedits') or {}).get('skipped') or []
        issues += [f"My edits skipped: {sk['who']} ({sk['part']}): {sk['why']}" for sk in skipped[:8]]
        if len(skipped) > 8:
            issues.append(f'{len(skipped) - 8} more of My edits skipped: Details lists them.')
        if o['run'] == 'apply':
            return {'kind': 'good', 'title': 'Updated, not saved yet', 'lines': lines, 'issues': issues,
                    'items': [['Data', self.data_label(o)], ['Saved', 'Not yet. Press Save to keep it.']],
                    'folder': None, 'report': None, 'can_play': False, 'can_undo': can_undo,
                    'say': 'Roster updated (not saved yet): press Save to keep it.'}
        out = o['out']
        if out is None or not out.ok:
            why = (out.lines[0] if out and out.lines else 'The roster could not be saved.')
            return {'kind': 'bad', 'title': 'Updated, but not saved',
                    'lines': [{'part': 'Not saved', 'text': why},
                              {'part': 'What now', 'text': 'Press Go again, save it with the Save bar, or Undo to take '
                                                           'the update back.'}],
                    'issues': [], 'items': [['Data', self.data_label(o)]], 'folder': None, 'report': None,
                    'can_play': False, 'can_undo': can_undo, 'say': f'The update was not saved: {why}'}
        data = self.data_label(o)
        if o['target'] == install.TARGET_FOLDER:
            items = [['Roster', o['name']], ['Folder', out.folder], ['Steps', 'HOW-TO-INSTALL.txt in that folder'],
                     ['Data', data]]
            title, say = 'Updated: folder ready', f"Updated: the folder for {o['name']} is ready to copy to another PC."
        elif o['target'] == install.TARGET_EXPORT:
            items = [['File', 'roster_h2h.db'], ['Check code', f'CRC {out.crc}'], ['Folder', out.folder],
                     ['Data', data]]
            title, say = 'Updated: online roster file written', 'Updated: roster_h2h.db is ready for the Overtime server.'
        else:
            folder = os.path.basename(os.path.normpath(out.folder))
            game = f'Custom Roster {slot_number(folder)}'
            kept = o.get('backups') or 0
            backup = f'Made first. {kept} of {BACKUPS_KEPT} kept.' if kept <= BACKUPS_KEPT else f'Made first. {kept} kept.'
            if o['mode'] == 'update':
                items = [['Saved over', o['name']], ['In the game', game], ['Backup', backup], ['Data', data]]
                say = f"Updated: {o['name']} is saved. Start NHL 19 to play."
            else:
                items = [['Saved as', o['name']], ['In the game', game]]
                items += [['Wrote over', f"{o['over'] or folder} (backed up first)"]] if o['slot'] else []
                items += [['Data', data]]
                say = f"Updated: saved as {o['name']}. Start NHL 19 and load {game}."
            title = 'Updated and saved'
        play = o['target'] == install.TARGET_SAVE and bool(c.setup.known_emulator())
        after = getattr(out, 'after', None) or []
        if after:       # saved all the same (Legacy 0.51.1): the red lines say what failed after the save
            lines = lines + [{'part': 'Not done', 'text': t, 'tone': 'bad'} for t in after]
            say += ' Not done: ' + '; '.join(after) + ' (the error log has the details).'
        return {'kind': 'good', 'title': title, 'lines': lines, 'issues': issues, 'items': items,
                'folder': out.folder, 'report': out.report or None, 'can_play': play, 'can_undo': False, 'say': say,
                'log': bool(after)}

    def _error_result(self, o):
        """A run that stopped on an error (o['at']: its step)."""
        at, message = o.get('at', 0), o['error']
        undo = o['change'] is not None and self.ctl.session is not None and bool(self.ctl.session.history) \
            and self.ctl.session.history[-1] is o['change']
        if at == 0:     # NHL.com or the offline copy (the details are in the log)
            offline = o['offline']
            lines = [{'part': 'Offline copy', 'text': 'The offline copy could not be read. Turn Data back to NHL.com '
                                                      'and press Go again.'} if offline else
                     {'part': 'NHL.com', 'text': 'NHL.com did not answer. Check your internet connection and press '
                                                 'Go again.'}, NOTHING_CHANGED]
            can_offline = not offline and bool(update.offline_date(paths.app_dir('cache')))
            say = ('The update stopped: the offline copy could not be read.' if offline else
                   'The update stopped: NHL.com did not answer.') + ' Nothing was saved.'
        else:
            lines = [{'part': GO_STEPS[min(at, len(GO_STEPS) - 1)][1], 'text': message}]
            lines.append({'part': 'What now', 'text': 'Undo takes the update back. Details tells more.'} if undo
                         else NOTHING_CHANGED)
            can_offline = False
            say = f'The update stopped: {message}'
        return {'kind': 'bad', 'title': 'The update stopped', 'lines': lines, 'issues': [], 'items': [],
                'folder': None, 'report': None, 'can_play': False, 'can_offline': can_offline, 'can_undo': undo,
                'say': say}

    def view(self):
        c = self.ctl
        with c.lock:
            roster = c.parts['rosters'].open_roster()
            busy = bool(c.busy) or self.running is not None
            if roster is None:
                return {'ready': False, 'tip': 'Pick a roster in Setup first.',
                        'go': {'enabled': False, 'text': 'Go'}, 'check': {'enabled': False}, 'busy': busy}
            save = self.save_view(roster)
            on = dict(self.opts, rosters=True, drafts=self.opts['nhl27'])
            kept = myedits.count(c.parts['roster'].kept())
            subs = {'myedits': (f"{kept} player{'s' if kept != 1 else ''} kept: their saved edits go back in after "
                                'the update.') if kept else
                    'None kept yet: player edits you save on the Roster tab go back in after every update.'}
            return {
                'ready': True,
                'from': self.from_view(roster),
                'switches': [{'key': k, 'title': t, 'sub': subs.get(k, sub), 'on': on[k], 'locked': k in LOCKED,
                              'always': k == 'rosters', 'info': {'title': t, 'text': info}}
                             for k, t, sub, info in SWITCHES],
                'season': c.upd_season,
                'seasons': [{'value': y, 'label': season_label(y)} for y in SEASONS],
                'per32': c.upd_per32 or 84,
                'offline': c.upd_offline,
                'offline_date': update.offline_date(paths.app_dir('cache')),
                'save': save,
                'run': self.run_view(),
                'result': self.result_view(),
                'go': {'enabled': not busy and not save['block'], 'text': 'Go'},
                'check': {'enabled': not busy},
                'busy': busy,
                'tip': None,
                'patch': patch_notice(c),
            }

    def list_view(self):
        c = self.ctl
        with c.lock:
            o, s = self.outcome, c.session
            todo = o['todo'] if o else c.upd_plan
            if not self.listing or self.closed or todo is None or s is None:
                return {'open': False}

            def where(key):
                return 'FA' if key in (None, 'FA') else c._code(key[1], key[0])

            def pos(pi):
                try:
                    return s.summary(pi)['pos']
                except (KeyError, IndexError, TypeError):
                    return ''
            sm = todo.summary()
            teams = changed_teams(todo)
            out = o.get('out') if o else None
            return {'open': True, 'title': 'What Go would change' if o and o['run'] == 'check' else 'List of changes',
                    'summary': {'players': sm['players'], 'moves': sm['moves'], 'new': sm['new'],
                                'releases': sm['releases'], 'teams': len(teams)},
                    'moves': [{'name': n, 'pos': pos(pi), 'from': where(f), 'to': where(t)}
                              for pi, n, f, t in todo.moves[:300]],
                    'new': [{'name': f"{r['first']} {r['last']}", 'pos': r.get('position', ''), 'num': r.get('number'),
                             'to': where(t)} for r, t in todo.new[:300]],
                    'releases': [{'name': n, 'pos': pos(pi), 'from': where(f)} for pi, n, f in todo.releases[:300]],
                    'report': out.report if out is not None and out.ok and out.report else None}
