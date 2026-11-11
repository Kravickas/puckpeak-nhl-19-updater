"""The app's state and what the page's buttons do. Each tab reads one slice of state; Python pushes a slice again
whenever it changes (window/host.py). What is typed on the player card stays in the page until Apply (or a pick
of another player, which applies it first).

The Controller holds the state every tab shares (the lock, the open roster, the busy flag, the status line, the
settings) and its parts (registry.py): one module per tab plus the shell and the rail, each owning its slices and
calls. window/api.py dispatches the page's calls to `calls`. Beta1's method names (pick_team, save_start,
snap_editor, ...) stay on the Controller as shims to the part that has the code now (OLD below): tests, tools and
re/scripts call them.
"""
import os
import threading

from overtime_core import calendar, overlay, rosterupdate as U, teams as T

from . import (editors_controller, gamesetup, install, jobs, labels as L, patch, paths, registry, savegame, settings,
               sources, update)

# beta1's slice names (pushed as before: changed() turns them into the new slices that show the same things)
OLD_SLICES = ('source', 'editor', 'lines', 'save', 'update', 'strategy', 'calendar', 'patch', 'status', 'faces',
              'equipment')
ALIASES = {
    'source': ('setup', 'app', 'save', 'rail'),
    'editor': ('roster', 'roster_card', 'rail', 'save', 'faces', 'equipment'),
    'faces': ('roster_face',),
    'equipment': ('roster_gear', 'jerseys'),
    'patch': ('patch', 'patch_files'),
    'save': ('save', 'update'),
}

# beta1's public names -> (part, method there). Each becomes a Controller method that calls the part's.
OLD = {
    'tab': ('shell', 'tab'), 'open_path': ('shell', 'open_path'), 'snap_status': ('shell', 'status'),
    'set_game_dir': ('rosters', 'set_game_dir'), 'set_save_dir': ('rosters', 'set_save_dir'),
    'refresh_sources': ('rosters', 'refresh_sources'), 'load_source': ('rosters', 'load_source'),
    'snap_source': ('rosters', 'snap_source'),
    'pick_league': ('rail', 'pick_league'), 'pick_team': ('rail', 'pick_team'),
    'search': ('roster', 'search'), 'pick_player': ('roster', 'pick_player'), 'apply': ('roster', 'apply'),
    'undo': ('roster', 'undo'), 'snap_editor': ('roster', 'snap_editor'),
    'set_slot': ('lines', 'set_slot'), 'set_captain': ('lines', 'set_captain'),
    'lines_section': ('lines', 'lines_section'), 'auto_group': ('lines', 'auto_group'),
    'auto_lines': ('lines', 'auto_lines'), 'snap_lines': ('lines', 'snap_lines'),
    'run_verify': ('save', 'run_verify'), 'save_name': ('save', 'save_name'), 'save_target': ('save', 'save_target'),
    'save_slot': ('save', 'save_slot'), '_slots': ('save', '_slots'), 'save_start': ('save', 'save_start'),
    'result_close': ('save', 'result_close'), 'snap_save': ('save', 'snap_save'),
    'update_option': ('update', 'update_option'), '_upd_step': ('update', '_upd_step'),
    'update_check': ('update', 'update_check'), 'update_apply': ('update', 'update_apply'),
    'snap_update': ('update', 'snap_update'),
    '_strategy_teams': ('strategy', '_strategy_teams'), 'strategy_team': ('strategy', 'strategy_team'),
    'strategy_set': ('strategy', 'strategy_set'), 'strategy_reset': ('strategy', 'strategy_reset'),
    'snap_strategy': ('strategy', 'snap_strategy'),
    'calendar_team': ('calendar', 'calendar_team'), 'snap_calendar': ('calendar', 'snap_calendar'),
    '_patch_check': ('patch', '_patch_check'), '_patch_job': ('patch', '_patch_job'),
    'patch_refresh': ('patch', 'patch_refresh'), 'patch_option': ('patch', 'patch_option'),
    'patch_apply': ('patch', 'patch_apply'), 'patch_kits_download': ('patch', 'patch_kits_download'),
    'patch_kits_remove': ('patch', 'patch_kits_remove'), 'patch_undo': ('patch', 'patch_undo'),
    'snap_patch': ('patch', 'snap_patch'),
}


def _shim(name, part, method):
    def call(self, *args, **kwargs):
        return getattr(self.parts[part], method)(*args, **kwargs)
    call.__name__ = name
    call.__doc__ = f'Beta1\'s name: {part}.{method} (app/{dict((k, m) for k, m, _c in registry.PARTS)[part]}.py).'
    return call


def _no_temporary(prefs):
    """`prefs` without a game, save or emulator folder in the temp folder (paths.temporary: the exe only)."""
    out = {k: v for k, v in prefs.items() if not (k in ('game_dir', 'save_dir') and paths.temporary(v))}
    setup = out.get('setup')
    if isinstance(setup, dict) and paths.temporary(setup.get('emulator')):
        out['setup'] = {**setup, 'emulator': ''}
    return out


PACKS_DEFAULT = 1      # settings marker: the pack switches' v0.10.0 default (off until the pack is here) is applied
PACK_KEYS = ('art', 'photos', 'kits')


def _packs_kept(game_dir):
    """A picture pack is in the app's cache, or the game is served art now (overtime-patch.json)."""
    cache = paths.app_dir('cache')
    if any(os.path.isfile(os.path.join(cache, name)) for name in patch.ART_PACKS):
        return True
    try:
        state = overlay._load_state(game_dir) if game_dir else None
    except (OSError, ValueError):
        state = None
    return 'art' in ((state or {}).get('layers') or {})


def packs_migrate(prefs, game_dir):
    """The patch switches from the settings. Once (no packs_default marker yet): an install from before v0.10.0 keeps
    its pack switches (on unless switched off, as they were) when it has a pack or the game is served art; otherwise
    they go off like a fresh install's, until the Photos, logos pack is downloaded."""
    want = dict(prefs.get('patch') or {})
    if prefs.get('packs_default') == PACKS_DEFAULT:
        return want
    kept = _packs_kept(game_dir)
    for key in PACK_KEYS:
        if kept:
            want[key] = want.get(key, True)
        else:
            want.pop(key, None)
    return want


CHEL_DEFAULT = 1       # settings marker: World of Chel's tile is on by default (v0.90.0, M5), applied once


def chel_migrate(prefs, want):
    """The World of Chel switch on by default. Once (no chel_default marker yet): an install whose patch has the
    closed-modes hub on (menus) gets the tile on too. Its game still has the tile off until it is patched again, and
    the Patch tab says so (patch_ctl's `changed`). Without the marker a fresh install takes the default (on)."""
    if prefs.get('chel_default') == CHEL_DEFAULT:
        return want
    if want.get('menus'):
        want['chel'] = True
    return want


class Controller:
    def __init__(self, host, game_dir=None, save_dir=None, reopen=False):
        self.host = host
        self.lock = threading.RLock()
        prefs = _no_temporary(settings.load())
        self.prefs = prefs
        self.game_dir = game_dir or prefs.get('game_dir') or paths.default_game_dir()
        self.save_dir = save_dir or prefs.get('save_dir') or paths.default_save_dir(gamesetup.use_game(self.game_dir))
        savegame.recover_swaps(self.save_dir)    # a roster save swap a power cut stopped halfway: put back
        self.game = sources.GameData(self.game_dir)
        self.sources = []
        self.selected = None
        self.session = None
        self.busy = None  # text of the job that runs
        self.status = {'text': '', 'tone': 'info', 'progress': None}
        # the open roster's team (the rail) and player (the Roster tab)
        self.league = 0
        self.team = None
        self.query = ''
        self.player = None
        self.card_error = ''
        # save
        self.save_name_text = prefs.get('save_name', 'Overtime roster')
        self.target = install.TARGET_SAVE
        self.slot = None  # a custom roster folder to overwrite (None: a new folder)
        self.steps = {k: {'state': 'idle', 'text': ''} for k, _ in install.STEPS}
        self.result = None
        self.issues = None
        self.tab_name = 'setup'
        # update, strategy, calendar
        up = prefs.get('update') or {}
        self.upd_season = int(up.get('season') or update.DEFAULT_SEASON)
        self.upd_per32 = up.get('per32')
        self.upd_offline = bool(up.get('offline'))
        self.upd_gathered = None
        self._fresh_update()
        self.strat_team = 0
        self.lines_page = 'Even strength'
        self.cal_team = None
        # game patch. The default roster is on: it is the verified default the exe carries (defaultdb), and without
        # it the one click serves the stock roster, 31 teams and no Seattle. The pack switches (art, photos, kits)
        # are off until the Photos, logos pack is downloaded (v0.10.0); packs_migrate keeps an older install's.
        # The World of Chel tile is on by default (chel_migrate: once, for an install that had the hub on).
        # A new install (no patch switches saved yet, 0.90.2, owner 2026-11-11) starts with the team art, 3D jerseys and
        # player photos on too, and only those of the Updated assets: their packs download at the first look that finds
        # NHL 19 (SetupController._first_assets). Every install since v0.10.0 has its switches saved: unchanged.
        fresh = not isinstance(prefs.get('patch'), dict)
        self.patch_want = chel_migrate(prefs, {'text': True, 'names': True, 'league': True, 'roster': True,
                                               'menus': True, 'chel': True, **{k: fresh for k in PACK_KEYS},
                                               **packs_migrate(prefs, self.game_dir)})
        if fresh:
            self.remember(first_assets=True)
        if prefs.get('packs_default') != PACKS_DEFAULT or prefs.get('chel_default') != CHEL_DEFAULT:
            self.remember(patch=dict(self.patch_want), packs_default=PACKS_DEFAULT, chel_default=CHEL_DEFAULT)
        self.patch_status = None  # overlay.status, after the Game patch tab was opened
        self.patch_running = False
        # the parts (registry.py): each registers its slices with the host; `calls` is what window/api.py runs
        self.editors = editors_controller.EditorsController(self)   # the face, type and gear editors' helpers
        self.parts = {}
        self.calls = registry.attach(self)
        self.tab_parts = registry.tab_parts(self)
        self.shell, self.rail, self.setup = self.parts['shell'], self.parts['rail'], self.parts['setup']
        self.refresh_sources(quiet=True)
        self.parts['rosters'].repair_saves()
        jobs.set_context(self.error_context)
        if reopen:
            self.parts['rosters'].start()

    # --- helpers ---------------------------------------------------------------------------------------
    def error_context(self):
        """What every error-log block says about the app (read without the lock: the failing job may hold it)."""
        s = self.session
        return [('Job', self.busy or '-', False), ('Roster', s.source_name if s else '(none open)', False),
                ('Tab', self.tab_name, False), ('Game', self.game_dir, True), ('Saves', self.save_dir, True),
                ('shadPS4', os.path.dirname(self.setup.emulator or '') or '', True), ('App data', paths.app_home(), True)]

    def changed(self, *names):
        """Mark slices to push again. Beta1's names (source, editor, faces, ...) also push the new slices that show
        the same state (ALIASES); names no part registers are ignored by the host."""
        out = list(names)
        for name in names:
            out += [n for n in ALIASES.get(name, ()) if n not in out]
        for name in list(out):
            out += [n for n in ALIASES.get(name, ()) if n not in out]
        self.host.changed(*out)

    def changed_all(self):
        """Push every slice again (a roster opened, an update applied)."""
        self.host.changed(*registry.slices(), *OLD_SLICES)

    def say(self, text, tone='info', progress=None):
        self.status = {'text': text, 'tone': tone, 'progress': progress}
        self.changed('status')

    def remember(self, **kv):
        self.prefs.update(_no_temporary(kv))
        if not settings.save(self.prefs):
            self.host.log('Settings could not be saved: settings.json cannot be written.')

    # --- shared by the parts -----------------------------------------------------------------------------------------
    def _fresh_update(self):
        self.upd_steps = {k: {'state': 'idle', 'text': ''} for k, _ in update.STEPS}
        self.upd_plan = None  # rosterupdate.Plan of the last check
        self.upd_report = None

    def _code(self, team, table=None):
        if table == U.CUSTOM_ROSTER:
            return 'SEA' if team == T.SEATTLE else f'Custom {team}'
        if table in (None, U.ROSTER) and team in calendar.CODES and team <= 30:
            return calendar.CODES[team]
        s = self.session
        if s is None:
            return str(team)
        i = s.team_row.get(team)
        league = L.LEAGUES.get(s.rows['exhibitionteams'][i]['league'], '') if i is not None else ''
        abbr = s.team_abbr(team) or str(team)
        return f'{abbr} ({league})' if league and league != 'NHL' else abbr


for _name, (_part, _method) in OLD.items():
    setattr(Controller, _name, _shim(_name, _part, _method))
del _name, _part, _method
