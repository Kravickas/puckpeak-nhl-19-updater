"""Multiplayer: play one friend. Name and ShadNet id, a lobby (create, join by code or from the public list), Ready,
and the game starting by itself once both are ready. docs/ui/multiplayer.md, docs/plans/m3-multiplayer-tab.md.

The lobby is the service in overtime_server/lobby.py, spoken to through lobby_client. The player's ShadNet id is the
account id shadPS4's log prints when NHL 19 signs in (typed when there is no log yet): it is also the game's login
id, which is how the server knows who meets whom. The secret token of the lobby stays in this part, never in the slice.

Polling belongs to the lobby, not to the tab: a thread asks `state` every few seconds from create/join until leave, so
a match keeps going while the player is in the game. It also fills the public list while the tab shows.

The game start (`_launch_job`) is the M2 hook: refuse unless the patch is on and intact, bake the expiring hook
(overlay.set_menus), start shadPS4, press the title screen twice, watch until the game closes, take the hook off.
If NHL 19 already runs, nothing is baked (a rematch: the player presses PLAY in Online Versus).

The match rules (period length, ...) live in the lobby: the host picks them with `mp_set_rule` before Ready, the
partner sees them. At launch each app bakes the lobby's rules into its own game (overtime_core.rules, through the
same overlay as the hook), so both games search with the same ones; a lobby on the defaults bakes nothing.

The History card (recent matches, the players table, a player's pop-up, "Enter result") is the server's match history
(`/api/history`, overtime_server/matches.py) drawn by history_view.py; it is fetched when the tab shows, every
HISTORY_POLL seconds while it does, after the game closes and on every call that changes it.
"""
import re
import threading
import time
import webbrowser

from overtime_core import history as H, overlay, rules as RU

from .. import VERSION, hud
from . import (gamesetup, history_view as HV, hostroster, jobs, keypress, launch, lobby_client as LC, patch_ctl, paths,
               shadnet)
from .registry import Part

POLL = 3.0              # seconds between `state` asks while in a lobby
LIST_POLL = 8.0         # seconds between public-list asks while the tab shows and there is no lobby
HISTORY_POLL = 20.0     # seconds between match-history asks while the tab shows
CHAT_POLL = 1.5         # seconds between `state` asks while a game runs (chat lines arrive with it)
GAME_POLL = 5.0         # ... while a game runs (the result card over the game waits for the server's confirmation)
IDLE_POLL = 1.0         # how often the poller looks at what to do
HOOK_SECONDS = 1800     # the hook the launch bakes works this long (the jump happens about 100 s after boot)
BOOT_WAIT = 60          # seconds from start to the first title press (docs/notes/zero-press.md)
TITLE_GAP = 20          # seconds between the two title presses
WATCH_POLL = 2.0
READY_SETTLE = 3        # seconds from the app seeing stage 'setup' to the READY press (the screen draws first; a READY
                        # the second title press already gave shows up as 'searching' by then: CHAT_POLL < READY_SETTLE)
READY_GAP = 15          # seconds before READY is pressed again while no search started
READY_TRIES = 3
READY_BLIND = 45        # a server that never says 'setup' (before v0.10.0): READY this long after the title presses
READY_WAIT = 240        # then the card says to press READY
LAUNCHING = ('launching', 'matched')
# the quick phrases of the hotkeys (Ctrl+Shift+F1..F6 while the game window exists)
PHRASES = ('gg', 'Good game, rematch?', 'Nice one!', 'Unlucky', 'One sec', 'Ready?')
CHAT_MAX = 140
CHAT_SHOWN = 20
EXT = re.compile(r'^\d{1,12}$')
EMAIL = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]+')
NAME_MAX = 24
LOCAL = ('127.0.0.1', 'localhost', '::1')
DOWN_TEXT = 'The lobby service did not answer. Check your internet, then press Check again.'
CERT_TEXT = ("This PC could not check the server's certificate. Update Windows, then press Check again. If it stays, "
             'send us the error log.')
SIGNIN_MISSING = ('shadPS4 has no ShadNet sign-in for NHL 19. Sign in to ShadNet on the Multiplayer tab (with shadPS4 '
                  'and its launcher closed), then Ready again.')
EXPECTED = (LC.LobbyError, gamesetup.SetupError, launch.LaunchError, overlay.PatchError)

# the step list of the launch card (docs/ui/multiplayer.md)
STEPS = ('Online start set', 'NHL 19 started', 'Pressing the title screen', 'Game Setup: pressing READY',
         'Online Versus, searching for {partner}', 'Match found: pick your team')
PHASES = {'hook': 0, 'starting': 1, 'title': 2, 'ready': 3, 'running': 4}


class MultiplayerCtl(Part):
    SLICES = {'multiplayer': 'view'}
    CALLS = {'mp_set_name': 'set_name', 'mp_set_ext': 'set_ext', 'mp_set_press': 'set_press', 'mp_refresh': 'refresh',
             'mp_create': 'create', 'mp_join': 'join', 'mp_ready': 'ready', 'mp_leave': 'leave',
             'mp_launch_now': 'launch_now', 'mp_set_rule': 'set_rule', 'mp_roster_mode': 'set_roster_mode',
             'mp_reset_rules': 'reset_rules', 'mp_history_refresh': 'history_refresh',
             'mp_history_player': 'history_player', 'mp_history_close': 'history_close',
             'mp_result_open': 'result_open', 'mp_result_close': 'result_close', 'mp_result': 'send_result',
             'mp_review_open': 'review_open', 'mp_review_close': 'review_close', 'mp_set_hidden': 'set_hidden',
             'mp_set_hud': 'set_hud', 'mp_say': 'say', 'mp_shadnet_signin': 'shadnet_signin',
             'mp_shadnet_register': 'shadnet_register', 'mp_shadnet_create': 'shadnet_create'}
    TAB = 'multiplayer'

    def __init__(self, ctl):
        super().__init__(ctl)
        self.mlock = threading.RLock()
        prefs = ctl.prefs.get('multiplayer') or {}
        self.name = str(prefs.get('name') or '')[:NAME_MAX]
        self.typed_ext = prefs.get('ext') if isinstance(prefs.get('ext'), int) else None
        checked = prefs.get('shadnet') if isinstance(prefs.get('shadnet'), dict) else {}
        # the Online ID and account id the app's own ShadNet sign-in proved (never the password)
        self.checked = ({'npid': checked['npid'], 'account': checked['account']}
                        if isinstance(checked.get('npid'), str) and isinstance(checked.get('account'), int) else None)
        self.sn_login = shadnet.login           # seams for tests
        self.sn_register = shadnet.register
        self.press_title = prefs.get('press', True) is not False
        self.show_hud = prefs.get('hud', True) is not False     # the card and the chat over the game
        self.hud = None
        self.chat_mark = {}         # (code, token) -> the newest chat number already shown
        self.url_override = str(prefs.get('url') or '')
        self.logged = {'npid': '', 'account': None, 'why': ''}   # what shadPS4's log said at the last look
        self.checks = None          # [{key, label, text, tone, go}] of the last look
        self.lobbies = []           # the public list
        self.error = ''             # the last thing that went wrong, in words
        self.busy = ''              # a call in flight ('create', 'join', ...)
        self.shown_now = False
        self.looked = False
        self.code = self.token = None
        self.lobby = None           # the server's view of my lobby
        self.me = 0                 # my index in lobby['players']
        self.down = 0               # polls in a row the service did not answer
        self.game = None            # the launch card: {phase, note, manual, failed}
        self.rules = None           # lab override of the rules the launch bakes ({rule: value}); else the lobby's
        self.launched_for = None    # (code, token) the launch was started for
        self.job = None
        self.poller = None
        # seams for tests
        self.threads = True
        self.make_client = LC.LobbyClient
        self.press = keypress.press
        self.sleep = time.sleep
        self.now = time.time
        self.running = overlay.emulator_running
        self.make_hud = lambda: hud.Hud(hud.emulator_rect, on_hotkey=self._hotkey, hotkeys=hud.PHRASE_KEYS)
        self.hud_ok = hud.available
        self.service_down = False   # the last ask of the service got no answer
        self.down_logged = ''       # the reason of the last "did not answer" written to the error log (once per reason)
        self.hist = {'raw': None, 'who': None, 'entering': None, 'form_error': '', 'error': '', 'supported': True,
                     'busy': False, 'review': None, 'seen': None, 'carded': None}   # the match history: the server's last answer, the
        # opened player, the open form, the opened review, and the newest confirmed match of mine already looked at
        # (`carded`: the newest one the HUD card was shown for)

    # --- who I am ------------------------------------------------------------------------------------------------
    def ext(self):
        """(ShadNet id, where it came from): the game's own sign-in wins (live 2026-11-07: a typed id that was not the
        player's own made two players one); a typed one only while the log has none; (None, '') when neither."""
        if self.logged.get('account'):
            return self.logged['account'], self.logged.get('from') or 'log'
        if self.typed_ext and self.logged.get('state') != 'stale':
            return self.typed_ext, 'typed'
        return None, ''

    def my_name(self):
        """The name friends see: the ShadNet Online ID (one name per player, owner 2026-11-07); a typed name only
        while there is none."""
        return self.logged.get('npid') or self.name or ''

    def _remember(self):
        self.ctl.remember(multiplayer={'name': self.name, 'ext': self.typed_ext, 'press': self.press_title,
                                       'url': self.url_override, 'hud': self.show_hud, 'shadnet': self.checked})

    def set_name(self, name):
        name = ' '.join(str(name or '').split())[:NAME_MAX]
        with self.mlock:
            self.name = name
            self._remember()
        self._changed()
        return {'ok': True}

    def set_ext(self, text):
        """The typed ShadNet id; '' puts the log's back."""
        text = str(text or '').strip()
        if text and not (EXT.match(text) and int(text) > 0):
            return self._fail('The ShadNet id is a number: copy it from the log line, after accountId=.')
        with self.mlock:
            self.typed_ext = int(text) if text else None
            self._remember()
            self.error = ''
        self._changed()
        return {'ok': True}

    def shadnet_signin(self, npid, password, new=False):
        """The player's own ShadNet account into shadPS4 (gamesetup.shadnet_signin). The app signs in to ShadNet
        first: a wrong password never reaches the game, and the account id is known at once (no NHL 19 run needed).
        When ShadNet does not answer it is saved anyway and the id comes from the game's next sign-in."""
        try:
            npid, password = self._can_save(npid, password)
        except gamesetup.SetupError as err:
            return self._fail(str(err))
        account = None
        why = f'Saved, but ShadNet did not answer. Start NHL 19 once so it signs in as {npid}, then press Check again.'
        try:
            account = self.sn_login(npid, password)
        except shadnet.ShadNetDown as err:
            self.ctl.host.log(f'Multiplayer: ShadNet check of {npid} got no usable answer ({err}); saved unchecked.')
        except shadnet.ShadNetError as err:
            if not (new and err.code == 8):
                return self._fail(str(err))
            # a brand-new account the server does not take yet (e-mail not confirmed): the password is right
            why = f'Account {npid} made. Confirm the e-mail ShadNet sent, then press Check again.'
        return self._save_signin(npid, password, account, why)

    def _can_save(self, npid, password):
        """(npid, password) cleaned when they can be written now, else SetupError."""
        if not self.logged.get('user_dir'):
            raise gamesetup.SetupError('Set up shadPS4 first (Setup tab).')
        npid, password = gamesetup.shadnet_check(npid, password)
        if overlay.emulator_running():
            raise gamesetup.SetupError('shadPS4 is running. Close the game first, then try again.')
        if overlay.launcher_running():
            raise gamesetup.SetupError("shadPS4's launcher is open: it keeps its own copy of the users and can write "
                                       'over the sign-in. Close it, then try again.')
        return npid, password

    def _save_signin(self, npid, password, account, why):
        user = self.logged.get('user_dir') or ''
        try:
            npid = gamesetup.shadnet_signin(user, npid, password)
        except gamesetup.SetupError as err:
            return self._fail(str(err))
        with self.mlock:
            self.typed_ext = None
            self.checked = {'npid': npid, 'account': account} if account else None
            self._remember()
            self.error = ''
            if account:
                self.logged = dict(self.logged, npid=npid, account=account, state='signed_in', why='',
                                   **{'from': 'shadnet'})
            else:
                self.logged = dict(self.logged, npid=npid, account=None, state='stale', why=why)
        self.ctl.host.log(f'Multiplayer: ShadNet sign-in set to {npid}' + (f' (account {account}).' if account else '.'))
        self.refresh()
        return {'ok': True, 'npid': npid, 'account': account}

    def shadnet_create(self, npid, email, password):
        """Make a new ShadNet account (the site's sign-up, from the app) and sign in with it."""
        try:
            npid, password = self._can_save(npid, password)     # before the account exists: nothing left half done
        except gamesetup.SetupError as err:
            return self._fail(str(err))
        email = str(email or '').strip()
        if len(password) < 6:
            return self._fail('The password needs at least 6 characters.')
        if not EMAIL.fullmatch(email) or len(email) > 120:
            return self._fail('Type a real e-mail address (ShadNet may send a confirmation).')
        try:
            self.sn_register(npid, password, email, agent=f'OvertimeRoster/{VERSION}')
        except shadnet.ShadNetDown as err:
            return self._fail(f'{err} Or make the account on the ShadNet site.')
        except shadnet.ShadNetError as err:
            return self._fail(str(err))
        self.ctl.host.log(f'Multiplayer: made ShadNet account {npid}.')
        out = self.shadnet_signin(npid, password, new=True)
        if not out.get('ok'):
            return dict(out, created=True, error=f'Account {npid} made. ' + out.get('error', ''))
        return dict(out, created=True)

    @staticmethod
    def shadnet_register():
        webbrowser.open(gamesetup.SHADNET_REGISTER)
        return {'ok': True}

    def set_press(self, on):
        with self.mlock:
            self.press_title = bool(on)
            self._remember()
        self._changed()
        return {'ok': True}

    # --- the lobby service ---------------------------------------------------------------------------------------
    def url(self):
        """The lobby service's address: the server Setup patches the game to (https://<host>); a typed override only
        for the lab (this PC's server), because the lobby and the game's login must be the same server."""
        host = self.ctl.setup.server['host']
        base = f'https://{host}'
        if self.url_override and self.url_override.rstrip('/') != base:
            if LC.lab_url(self.url_override) and host in LOCAL:
                return self.url_override
            raise LC.LobbyRefused(0, f'The lobby address must be the server Setup uses ({host}).')
        return base

    def client(self):
        return self.make_client(self.url())

    # --- reading the PC ------------------------------------------------------------------------------------------
    def look(self):
        """The log and the patch (files are hashed: not under any lock)."""
        c = self.ctl
        setup = c.setup
        emu = setup.known_emulator()
        user = gamesetup.emu_user_dir(emu) if emu else ''
        log = gamesetup.shadnet_log(user) if user else None
        who = gamesetup.shadnet_identity(user, log) if user else {'npid': '', 'account': None, 'state': None}
        if who['state'] == 'stale':
            why = (f'The ShadNet account changed to {who["npid"]}. Start NHL 19 once so it signs in as '
                   f'{who["npid"]}, then press Check again.')
        elif user and not who['npid']:
            why = 'Sign in to ShadNet below, or create your own account here.'
        else:
            why = gamesetup.shadnet_why(log) if user else ''
        logged = {'npid': who['npid'], 'account': who['account'], 'state': who['state'], 'why': why,
                  'user_dir': user}
        checked = self.checked
        if (not who['account'] and checked and who['npid'] and (log or {}).get('state') != 'rejected'
                and checked['npid'].casefold() == who['npid'].casefold()):
            # the app's own ShadNet sign-in proved this Online ID's account id: no NHL 19 run needed
            logged.update(account=checked['account'], state='signed_in', why='', **{'from': 'shadnet'})
        checks = self._checks(emu)
        with self.mlock:
            self.logged, self.checks = logged, checks
        return checks

    def _checks(self, emu):
        c = self.ctl
        game_dir = c.game_dir
        if not emu:
            patch = ('bad', 'shadPS4 not set up', 'setup')
            roster = ('caution', 'not known yet', 'setup')
        else:
            try:
                patch_ctl.adopt_patch(c.setup)
                eboot = gamesetup.status(emu)
                st = overlay.status(game_dir) if game_dir and c.game.ok else None
            except (OSError, ValueError, gamesetup.SetupError, overlay.PatchError) as err:
                eboot, st = None, None
                c.host.log(f'Multiplayer: the patch could not be read ({err!r}).')
            layers = (st or {}).get('layers') or {}
            problems = list((eboot or {}).get('problems') or ())
            keys_only = bool(eboot) and eboot.get('installed') and bool(problems) and all(
                str(p).startswith('network switched off') for p in problems)
            if keys_only and not eboot.get('intact'):
                patch = ('caution', 'network switched off: the game start turns it on', None)
            elif not eboot or not eboot.get('installed') or not eboot.get('intact'):
                patch = ('bad', 'not patched', 'patch')
            elif not st or 'menus' not in layers:
                patch = ('bad', 'online start missing', 'patch')
            elif st.get('problems'):
                patch = ('caution', 'changed since applied', 'patch')
            else:
                patch = ('good', 'on and intact', None)
            if 'database' in layers:
                roster = ('good', 'Overtime roster', None)
            elif layers:
                roster = ('caution', 'not the Overtime roster', 'update')
            else:
                roster = ('caution', 'game not patched', 'patch')
        return [{'key': 'roster', 'label': 'Roster', 'tone': roster[0], 'text': roster[1], 'go': roster[2]},
                {'key': 'patch', 'label': 'Patch', 'tone': patch[0], 'text': patch[1], 'go': patch[2]}]

    def shown(self):
        """The tab shows: look at the PC and the service, clear a hook an earlier run left."""
        with self.mlock:
            self.shown_now = True
            first, self.looked = not self.looked, True
        self.refresh()
        if first:
            self._spawn(self._clear_stale_hook, 'mp-hook')
        self._ensure_poller()

    def hide(self):
        with self.mlock:
            self.shown_now = False

    def refresh(self):
        """Look at the PC and the service again (a job: files are hashed and the service may be slow)."""
        self._spawn(self._refresh_job, 'mp-look')
        return {'ok': True}

    def _refresh_job(self):
        try:
            self.look()
            self._lobbies()
            self._history()
        except EXPECTED as err:
            self._set_error(str(err))
        self._changed()

    def _lobbies(self):
        try:
            rows = self.client().lobbies()
        except LC.LobbyDown as err:
            self._server_down(True, err)
            return
        except LC.LobbyRefused as err:
            self._set_error(err.text)
            return
        self._server_down(False)
        rows = rows.get('lobbies') if isinstance(rows, dict) else rows
        with self.mlock:
            self.lobbies = [r for r in rows or [] if isinstance(r, dict) and r.get('code')]

    def _list_job(self):
        self._lobbies()
        self._changed()

    def _server_down(self, down, err=None):
        """The service answered or not. Why it did not goes to the error log once per reason (a tester's "SERVER not
        reachable" left nothing to read, 2026-11-03); a certificate this PC cannot check gets its own words."""
        with self.mlock:
            self.service_down = down
            if down:
                self.error = CERT_TEXT if getattr(err, 'certificate', False) else DOWN_TEXT
                log = err is not None and str(err) != self.down_logged
                if log:
                    self.down_logged = str(err)
            else:
                log = False
                self.down_logged = ''
                if _down_text(self.error):
                    self.error = ''
        if log:
            try:
                where = self.url()
            except LC.LobbyError:
                where = ''
            jobs.log_block(err, f'Lobby service {where}'.rstrip())

    # --- lobby calls ---------------------------------------------------------------------------------------------
    def create(self, public=True):
        return self._enter('create', lambda ext, name: self.client().create(name, ext, bool(public)))

    def join(self, code):
        try:
            code = LC._code(code)
        except LC.LobbyRefused as err:
            return self._fail(err.text)
        return self._enter('join', lambda ext, name: self.client().join(code, name, ext))

    def _enter(self, what, call):
        ext, _from = self.ext()
        name = self.my_name()
        if not ext:
            return self._fail('Set your ShadNet id first: a lobby is tied to your game\'s sign-in.')
        if not name:
            return self._fail('Type your name first.')
        with self.mlock:
            if self.code:
                return self._fail('Leave your lobby first.')
            if self.busy:
                return {'ok': False}
            self.busy = what
        try:
            got = call(ext, name)
        except LC.LobbyError as err:
            return self._lobby_error(err)
        finally:
            with self.mlock:
                self.busy = ''
        self._joined(got)
        return {'ok': True}

    def _joined(self, got):
        lobby = got['lobby']
        with self.mlock:
            self.code, self.token = lobby['code'], got['token']
            self.lobby, self.me = lobby, int(got.get('you', 0))
            self.error, self.down, self.game, self.launched_for = '', 0, None, None
        self._changed()
        self._ensure_poller()

    def ready(self, value=True):
        with self.mlock:
            code, token = self.code, self.token
        if not code:
            return {'ok': False}
        patch = None
        if value:
            emu = self.ctl.setup.known_emulator()
            try:
                patch = gamesetup.patch_fingerprint(emu) if emu else 'none'
            except (OSError, ValueError, gamesetup.SetupError) as err:
                self.ctl.host.log(f'Multiplayer: the patch could not be read ({err!r}).')
        if value and self._hosts_own_roster():
            try:
                self._upload_roster(code, token)
            except hostroster.HostRosterError as err:
                return self._fail(str(err))
            except LC.LobbyError as err:
                return self._lobby_error(err)
        try:
            lobby = self.client().ready(code, token, bool(value), patch)
        except LC.LobbyError as err:
            return self._lobby_error(err)
        self._apply(lobby)
        return {'ok': True}

    def _hosts_own_roster(self):
        with self.mlock:
            return self.me == 0 and (self.lobby or {}).get('roster_mode') == 'host'

    def _upload_roster(self, code, token):
        """Build the roster this host's game serves and give it to the lobby (at every Ready, so edits made since
        are in). The guest's game, and this one, download it by its CRC in Online Versus."""
        c = self.ctl
        if not c.game_dir or not c.game.ok:
            raise hostroster.HostRosterError('Pick your NHL 19 folder in Setup first.')
        try:
            with c.lock:
                s = c.session
                blob, crc, came = hostroster.host_roster(c.game_dir, c.game.schema(), s.db if s is not None else None)
        except (OSError, ValueError, KeyError, overlay.PatchError) as err:
            raise hostroster.HostRosterError(f'Your roster could not be read ({err}).') from None
        where = 'the roster open here' if came == 'open' else 'the roster Patch put on your game'
        c.host.log(f'Multiplayer: uploading {where} ({len(blob)} bytes, CRC {crc[:12]}...).')
        self.client().upload_roster(code, token, blob)

    def set_roster_mode(self, mode):
        """The host picks whose roster the match plays on: 'server' (the online roster) or 'host' (the host's own
        roster and lines, uploaded at Ready; the guest's game adopts it)."""
        if mode not in ('server', 'host'):
            return self._fail('Pick the server roster or your own.')
        with self.mlock:
            code, token, me = self.code, self.token, self.me
            state = (self.lobby or {}).get('state')
        if not code:
            return {'ok': False}
        if me != 0:
            return self._fail('Only the host picks the roster.')
        if state in LAUNCHING:
            return self._fail('The game is starting: the roster is fixed now.')
        try:
            lobby = self.client().roster_mode(code, token, mode)
        except LC.LobbyError as err:
            return self._lobby_error(err)
        self._apply(lobby)
        return {'ok': True}

    def set_rule(self, key, value):
        """The host picks one match rule (before Ready; the server clears both ready flags on a change)."""
        try:
            wanted = RU.validate({key: value}, partial=True)
        except RU.RulesError as err:
            return self._fail(str(err))
        return self._send_rules(wanted)

    def reset_rules(self):
        """The host puts every match rule back to the game's own."""
        return self._send_rules(dict(RU.DEFAULTS))

    def _send_rules(self, wanted):
        with self.mlock:
            code, token, me = self.code, self.token, self.me
            state = (self.lobby or {}).get('state')
        if not code:
            return {'ok': False}
        if me != 0:
            return self._fail('Only the host picks the match rules.')
        if state in LAUNCHING:
            return self._fail('The game is starting: the rules are fixed now.')
        try:
            lobby = self.client().settings(code, token, wanted)
        except LC.LobbyError as err:
            return self._lobby_error(err)
        self._apply(lobby)
        return {'ok': True}

    # --- the match history ---------------------------------------------------------------------------------------
    def history_refresh(self):
        self._spawn(self._history_job, 'mp-history')
        return {'ok': True}

    def _history_job(self):
        self._history()
        self._changed()

    def _history(self):
        """Ask the service for the history (and the opened player's detail); keep the old answer when it fails."""
        ext, _from = self.ext()
        with self.mlock:
            who = self.hist['who']
        try:
            raw = self.client().history(ext, who)
        except LC.LobbyDown:
            return self._history_note('The history did not load: the server did not answer.')
        except LC.LobbyRefused as err:
            if err.status == 404:       # a server from before the match history
                with self.mlock:
                    self.hist.update(raw=None, supported=False, error='')
                return None
            return self._history_note(err.text)
        if not isinstance(raw, dict) or not isinstance(raw.get('matches'), list):
            return self._history_note('The history did not load: the server sent something else.')
        with self.mlock:
            self.hist.update(raw=raw, supported=True, error='')
            if self.hist['seen'] is None:           # the first look only sets the mark: old matches are not news
                self.hist['seen'] = HV.latest_mine(raw)
            card = None
            if self.hist['carded'] is None:
                self.hist['carded'] = HV.latest_mine(raw)
            else:
                card = HV.result_card(raw)
                if card and card['match'] > self.hist['carded']:
                    self.hist['carded'] = card['match']
                else:
                    card = None
        if card:
            self._hud_call('result', card)
        return None

    def set_hud(self, on):
        """The card and the chat over the game on or off (the game's window only; nothing is ever drawn on the desktop)."""
        with self.mlock:
            self.show_hud = bool(on)
            self._remember()
        self._changed()
        return {'ok': True}

    def _hud_call(self, what, *args):
        """Hand something to the HUD (started on first use); a machine that cannot draw it, or an off switch, drops it."""
        with self.mlock:
            if not (self.show_hud and self.hud_ok()):
                return False
            if self.hud is None:
                self.hud = self.make_hud()
                self.hud.start()
            target = self.hud
        getattr(target, what)(*args)
        return True

    def _history_note(self, text):
        with self.mlock:
            self.hist['error'] = text
        return None

    def history_player(self, pid):
        """Open a player's pop-up (the server sends that player's detail with the next history)."""
        if not isinstance(pid, str) or not re.match(r'^[0-9a-f]{10}$', pid):
            return {'error': 'That is not a player.'}
        with self.mlock:
            self.hist['who'] = pid
        return self.history_refresh()

    def history_close(self):
        with self.mlock:
            self.hist['who'] = None
            if self.hist['raw']:
                self.hist['raw'] = dict(self.hist['raw'], detail=None)
        self._changed()
        return {'ok': True}

    def review_open(self, match_id=None):
        """Open how I did in my latest (or the given) confirmed match; asking is quick, so the answer comes back at once."""
        ext, _from = self.ext()
        if not ext:
            return {'error': 'Set your ShadNet id first.'}
        if match_id is not None and (not isinstance(match_id, int) or isinstance(match_id, bool)):
            return {'error': 'That is not a match.'}
        try:
            got = self.client().review(ext, match_id)
        except LC.LobbyDown:
            return self._history_note('The review did not load: the server did not answer.') or {'error': 'The server did not answer.'}
        except LC.LobbyRefused as err:
            text = 'This server cannot review matches yet.' if err.status == 404 else err.text
            return self._history_note(text) or {'error': text}
        review = got.get('review') if isinstance(got, dict) else None
        if not isinstance(review, dict):
            self._history_note('No confirmed match to review yet.')
            self._changed()
            return {'error': 'No confirmed match to review yet.'}
        with self.mlock:
            self.hist.update(review=review, error='')
            self.hist['seen'] = max(self.hist['seen'] or 0, review.get('match') or 0)
        self._changed()
        return {'ok': True}

    def home(self):
        return paths.app_home()

    def review_close(self):
        with self.mlock:
            self.hist['review'] = None
        self._changed()
        return {'ok': True}

    def set_hidden(self, hidden):
        """Show me on (False) or hide me from (True) the public web board; the games still rate."""
        ext, _from = self.ext()
        if not ext:
            return {'error': 'Set your ShadNet id first.'}
        if not isinstance(hidden, bool):
            return {'error': 'Pick show or hide.'}
        try:
            self.client().privacy(ext, hidden)
        except LC.LobbyDown:
            return {'error': 'The server did not answer. Try again.'}
        except LC.LobbyRefused as err:
            return {'error': 'This server cannot hide you yet.' if err.status == 404 else err.text}
        self._history()
        self._changed()
        return {'ok': True}

    def result_open(self, match_id):
        with self.mlock:
            self.hist.update(entering=match_id if isinstance(match_id, int) else None, form_error='')
        self._changed()
        return {'ok': True}

    def result_close(self):
        with self.mlock:
            self.hist.update(entering=None, form_error='')
        self._changed()
        return {'ok': True}

    def send_result(self, match_id, team, score_for, score_against):
        """I say how my match ended; the match is confirmed once the other player says the mirror of it."""
        ext, _from = self.ext()
        team, sf, sa = H.team_code(team), H.score(score_for), H.score(score_against)
        if not ext:
            problem = 'Set your ShadNet id first: the result is filed under it.'
        elif not isinstance(match_id, int) or isinstance(match_id, bool):
            problem = 'That is not a match.'
        elif team is None:
            problem = 'Pick the team you played with.'
        elif sf is None or sa is None:
            problem = 'The scores are numbers from 0 to 99.'
        elif sf == sa:
            problem = 'A game has a winner: the scores must differ (overtime and shootout count).'
        else:
            problem = ''
        if not problem:
            try:
                self.client().result(ext, match_id, team, sf, sa)
            except LC.LobbyDown:
                problem = 'The server did not answer. Try again.'
            except LC.LobbyRefused as err:
                problem = err.text
        with self.mlock:
            self.hist['form_error'] = problem
            if not problem:
                self.hist['entering'] = None
        if problem:
            self._changed()
            return {'error': problem}
        self._history()
        self._changed()
        return {'ok': True}

    def leave(self):
        with self.mlock:
            code, token = self.code, self.token
        if not code:
            return {'ok': True}
        try:
            self.client().leave(code, token)
        except LC.LobbyDown:
            pass            # gone from the service's side soon enough (the lobby expires), gone from ours now
        except LC.LobbyRefused:
            pass            # already gone
        self._left('')
        return {'ok': True}

    def _left(self, note):
        with self.mlock:
            self.code = self.token = self.lobby = None
            self.launched_for = None
            if self.game and self.game.get('phase') in ('failed', 'ended', 'rematch'):
                self.game = None
            self.error = note
        self._changed()
        self._spawn(self._list_job, 'mp-list')

    def _lobby_error(self, err):
        if isinstance(err, LC.LobbyDown):
            self._server_down(True, err)
            return {'error': self.error}
        return self._fail(err.text if isinstance(err, LC.LobbyRefused) else str(err))

    # --- polling -------------------------------------------------------------------------------------------------
    def _ensure_poller(self):
        if not self.threads:
            return
        with self.mlock:
            if self.poller is not None and self.poller.is_alive():
                return
            self.poller = threading.Thread(target=self._poll_loop, daemon=True, name='mp-poll')
            self.poller.start()

    def _poll_loop(self):
        last = last_history = 0.0
        while True:
            with self.mlock:
                in_lobby, shown, history_on = bool(self.code), self.shown_now, self.hist['supported']
                phase = (self.game or {}).get('phase')
                playing = in_lobby and self.show_hud and phase in ('running', 'rematch')
                quick = playing or phase == 'ready'     # _ready waits on my stage
            if not in_lobby and not shown:
                return
            if (shown or playing) and history_on and self.now() - last_history >= (HISTORY_POLL if shown else GAME_POLL):
                last_history = self.now()
                self._history_job()
            every = (CHAT_POLL if quick else POLL) if in_lobby else LIST_POLL
            if self.now() - last >= every:
                last = self.now()
                try:
                    self.poll_once()
                except Exception as err:    # noqa: BLE001 (the poller must not die; the block is for a bug report)
                    jobs.log_block(err, 'Multiplayer poll')
            self.sleep(IDLE_POLL)

    def poll_once(self):
        """One look at the service: my lobby's state, or the public list."""
        with self.mlock:
            code, token = self.code, self.token
        if not code:
            self._lobbies()
            self._changed()
            return
        try:
            lobby = self.client().state(code, token)
        except LC.LobbyDown:
            with self.mlock:
                self.down += 1
                if self.down >= 2:
                    self.error = 'The lobby service did not answer. Still trying.'
            self._changed()
            return
        except LC.LobbyRefused as err:
            if err.status in (403, 404):
                self._left('The lobby is gone (it was idle for too long, or closed). Make a new one.')
            else:
                self._set_error(err.text)
            return
        with self.mlock:
            self.down = 0
            if _down_text(self.error):
                self.error = ''
        self._apply(lobby)

    def _apply(self, lobby):
        """Take the server's view; both ready starts the game once."""
        start = False
        with self.mlock:
            if not self.code:
                return
            self.lobby = lobby
            self.me = int(lobby.get('you', self.me))
            key = (self.code, self.token)
            news = self._chat_news(key, lobby)
            if lobby.get('state') in LAUNCHING:
                if self.launched_for != key and not (self.job and self.job.is_alive()):
                    self.launched_for = key
                    start = True
            else:
                self.launched_for = None
                if self.game and self.game.get('phase') in ('failed', 'ended', 'rematch'):
                    self.game = None
        self._changed()
        for line in news:
            self._hud_call('chat', line['name'], line['text'])
        if start:
            self._start_job()

    def _chat_news(self, key, lobby):
        """The partner's lines I have not shown yet (the first look at a lobby only sets the mark: old lines are not news)."""
        lines = [c for c in lobby.get('chat') or [] if isinstance(c, dict) and isinstance(c.get('n'), int)]
        top = max((c['n'] for c in lines), default=0)
        mark = self.chat_mark.get(key)
        self.chat_mark[key] = max(top, mark or 0)
        if mark is None:
            return []
        return [c for c in lines if c['n'] > mark and c.get('who') != self.me]

    def say(self, text):
        """A chat line to my partner (their app shows it in the tab and over the game)."""
        text = ' '.join(str(text or '').split())[:CHAT_MAX]
        with self.mlock:
            code, token = self.code, self.token
        if not code or not text:
            return {'ok': False}
        try:
            lobby = self.client().say(code, token, text)
        except LC.LobbyRefused as err:
            if err.status == 429:
                return {'ok': False, 'note': 'slow down'}
            return self._lobby_error(err)
        except LC.LobbyError as err:
            return self._lobby_error(err)
        self._apply(lobby)
        self._hud_call('chat', 'You', text)
        return {'ok': True}

    def _hotkey(self, index):
        """A quick-phrase hotkey pressed in the game (on the HUD thread: the send goes to its own)."""
        if 0 <= index < len(PHRASES):
            self._spawn(lambda: self.say(PHRASES[index]), 'mp-say')

    def launch_now(self):
        """Start the game again (it closed, or the first start failed), for a lobby that is launching."""
        with self.mlock:
            state = (self.lobby or {}).get('state')
            if state not in LAUNCHING:
                return self._fail('Both players have to be ready first.')
            if self.job and self.job.is_alive():
                return self._fail('The game is starting already.')
            self.launched_for = (self.code, self.token)
        self._start_job()
        return {'ok': True}

    # --- the game start ------------------------------------------------------------------------------------------
    def _start_job(self):
        if not self.threads:
            return
        with self.mlock:
            self.game = {'phase': 'hook', 'note': '', 'manual': False}
            self.job = self._spawn(self._launch_job, 'mp-launch')
        self._changed()

    def _phase(self, phase, note='', **extra):
        with self.mlock:
            was = self.game or {}
            self.game = {'phase': phase, 'note': note, 'manual': was.get('manual', False),
                         'ready_manual': was.get('ready_manual', False), **extra}
        self._changed()

    def _launch_job(self):
        """Hook on, game on, title pressed, then watch the game; the hook is always taken off once it closed."""
        try:
            self._launch()
        except EXPECTED as err:
            self._phase('failed', str(err))
        except Exception as err:    # noqa: BLE001
            self._phase('failed', jobs.log_unexpected(err, 'Multiplayer launch'))

    def _launch(self):
        c = self.ctl
        emu, game_dir = c.setup.known_emulator(), c.game_dir
        patch_ctl._refresh_before_start(c.setup)    # the server field and the network keys, no Patch needed
        checks = self.look()
        bad = next((k for k in checks if k['key'] == 'patch' and k['tone'] != 'good'), None)
        if bad:
            raise gamesetup.SetupError(f'Patch the game first ({bad["text"]}): open Game patch and press Patch.')
        user = gamesetup.emu_user_dir(emu)
        self._signin_ready(user)
        rules = self._launch_rules()
        if self.running():
            note = 'NHL 19 is already running. Press PLAY in Online Versus to meet your friend.'
            if rules:
                note += ' It keeps the rules it started with: close the game and Ready again to play the lobby\'s.'
            self._phase('rematch', note)
            self._hud_call('ping')
            self._watch(emu, hooked=False)
            return
        until = int(self.now()) + HOOK_SECONDS
        self._phase('hook')
        overlay.set_menus(game_dir, dict({'until': until}, **({'rules': rules} if rules else {})))
        before = (gamesetup.shadnet_log(user) or {}).get('when')
        try:
            self._phase('starting')
            launch.start(emu, game_dir)
            self._titles(emu, lambda: self._signed_in(user, before))
            self._ready(emu)
            self._watch(emu, hooked=True)
        finally:
            self._unhook(game_dir)

    def _launch_rules(self):
        """The rules to bake: the lab override, else the lobby's when they differ from the game's defaults, else None."""
        with self.mlock:
            lobby = (self.lobby or {}).get('rules')
        if self.rules:
            return self.rules
        if not isinstance(lobby, dict):
            return None
        try:
            picked = RU.validate(lobby)
        except RU.RulesError:
            return None             # a server speaking other rules than this app knows: the game's own
        return picked if picked != RU.DEFAULTS else None

    @staticmethod
    def _signin_ready(user):
        """Before a start: the user NHL 19 plays as has a ShadNet sign-in in users.json (else the game stops at SIGN IN
        REQUIRED while the friend waits, live 2026-11-07)."""
        one = gamesetup.shadnet_player(user) or {}
        if not (one.get('shadnet') and one.get('npid') and one.get('password')):
            raise gamesetup.SetupError(SIGNIN_MISSING)

    @staticmethod
    def _signed_in(user, before):
        """After the boot wait: shadPS4's log of this start (newer than `before`) says ShadNet signed in, or SetupError
        with the reason. A log that says nothing yet passes (an early look proves nothing)."""
        log = gamesetup.shadnet_log(user)
        if not log or (before is not None and log.get('when', 0) <= before):
            return
        off = log.get('shadnet_on') is False or log.get('network_on') is False or log.get('disabled_globally')
        if off or log.get('state') in ('signed_out', 'rejected'):
            why = gamesetup.shadnet_why(log) or SIGNIN_MISSING
            raise gamesetup.SetupError(f'NHL 19 did not sign in to ShadNet, so it stops at SIGN IN REQUIRED. {why} '
                                       'Close NHL 19 first.')

    def _titles(self, emu, signed_in=None):
        """The two title presses (the first only focuses the window); without them the card says what to press.
        `signed_in` runs after the boot wait and raises when the game did not sign in to ShadNet."""
        if not self.press_title:
            self._phase('title', manual=True)
            return
        key = keypress.cross_key(emu)
        self._phase('title')
        self.sleep(BOOT_WAIT)
        if signed_in:
            signed_in()
        sent = self.press(key)
        self.sleep(TITLE_GAP)
        sent = self.press(key) and sent
        if not sent:
            self._phase('title', manual=True)

    def _my_stage(self):
        """My stage in the server's view of the lobby (lobby, setup, searching, matched), or None."""
        with self.mlock:
            players = (self.lobby or {}).get('players') or []
            return players[self.me].get('stage') if self.me < len(players) else None

    def _ready(self, emu):
        """READY on purpose: ✕ once the server says this game is in Versus Game Setup (stage 'setup', from
        createOrJoinGame), or READY_BLIND s after the title presses from a server that does not say it; again every
        READY_GAP s while no search starts (READY_SETTLE s after 'setup' when it comes after a press), READY_TRIES
        presses at most. Without presses, or when none starts a search,
        the card says to press READY."""
        with self.mlock:
            manual = (self.game or {}).get('manual', False)
        if manual or not self.press_title:
            self._phase('ready', ready_manual=True)
            return
        self._phase('ready')
        key = keypress.cross_key(emu)
        start, seen, last, tries = self.now(), None, None, 0
        while self.running():
            now, stage = self.now(), self._my_stage()
            if stage in ('searching', 'matched'):       # the second title press may have been READY already
                return
            if now - start >= READY_WAIT or (tries >= READY_TRIES and now - last >= READY_GAP):
                break
            if stage == 'setup' and seen is None:
                seen = now
            if seen is not None and (last is None or last < seen):  # Game Setup came after the last press (a blind
                due = now - seen >= READY_SETTLE                    # one can land on the title screen): READY now
            elif last is None:
                due = now - start >= READY_BLIND
            else:
                due = now - last >= READY_GAP
            if due and tries < READY_TRIES:
                if not self.press(key):
                    break
                last, tries = self.now(), tries + 1
            self.sleep(WATCH_POLL)
        self._phase('ready', ready_manual=True)

    def _watch(self, emu, hooked):
        """Until the game closes. The card moves on by itself with the lobby's stages."""
        if hooked:
            with self.mlock:
                manual = (self.game or {}).get('manual', False)
            self._phase('running', manual=manual)
            self._hud_call('ping')
        while self.running():
            self.sleep(WATCH_POLL)
        self._phase('ended', 'NHL 19 closed.')
        self._spawn(self._history_job, 'mp-history')    # a result may have arrived while the game ran

    def _unhook(self, game_dir):
        """The hook comes off once the game is closed (set_menus refuses while it runs)."""
        for _ in range(3):
            try:
                overlay.set_menus(game_dir, None, running=self.running)
                return
            except overlay.PatchError as err:
                if self.running():
                    self.sleep(WATCH_POLL)
                    continue
                self.ctl.host.log(f'Multiplayer: the online start could not be taken off ({err}).')
                return

    def _clear_stale_hook(self):
        """An earlier run left the hook on (a crash, the app closed during a game): take it off while the game is off.
        It expires by itself anyway."""
        c = self.ctl
        if self.running() or not (c.game_dir and c.game.ok):
            return
        try:
            layer = ((overlay.status(c.game_dir) or {}).get('layers') or {}).get('menus') or {}
            if layer.get('autoplay_until'):
                overlay.set_menus(c.game_dir, None, running=self.running)
        except (overlay.PatchError, OSError, ValueError) as err:
            c.host.log(f'Multiplayer: a leftover online start could not be taken off ({err}).')

    # --- helpers -------------------------------------------------------------------------------------------------
    def _spawn(self, work, name):
        if not self.threads:
            return None
        t = threading.Thread(target=self._guard, args=(work,), daemon=True, name=name)
        t.start()
        return t

    def _guard(self, work):
        try:
            work()
        except Exception as err:    # noqa: BLE001
            jobs.log_block(err, 'Multiplayer')

    def _changed(self):
        self.ctl.changed('multiplayer')

    def _set_error(self, text):
        with self.mlock:
            self.error = text
        self._changed()

    def _fail(self, text):
        self._set_error(text)
        return {'error': text}

    # --- the slice -----------------------------------------------------------------------------------------------
    def view(self):
        with self.mlock:
            ext, source = self.ext()
            lobby = self._lobby_view()
            return {
                'you': {'name': self.my_name(), 'name_from': 'typed' if self.name else 'game' if self.logged['npid'] else '',
                        'ext': ext, 'ext_from': source, 'ext_why': self.logged.get('why', ''), 'press': self.press_title,
                        'shadnet': {'npid': self.logged.get('npid') or '', 'state': self.logged.get('state'),
                                    'ready': bool(self.logged.get('user_dir'))},
                        'hud': {'on': self.show_hud, 'available': self.hud_ok(), 'phrases': list(PHRASES)}},
                'checks': self._checks_view(),
                'lobby': lobby,
                'lobbies': [{'code': str(r['code']), 'host': str(r.get('host') or ''), 'players': r.get('players'),
                             'age': _age(r.get('age'))} for r in self.lobbies],
                'game': self._game_view(lobby),
                'history': self._history_view(),
                'error': self.error,
                'busy': self.busy,
                'quoted': 'signed in ... accountId=16349',
            }

    def _history_view(self):
        h = self.hist
        return HV.build(h['raw'], self.now(), supported=h['supported'], error=h['error'], busy=h['busy'],
                        entering=h['entering'], form_error=h['form_error'], seen=h['seen'], review=h['review'])

    def _checks_view(self):
        rows = [dict(r) for r in self.checks or []]
        rows.append({'key': 'server', 'label': 'Server', 'tone': 'bad' if self.service_down else 'good',
                     'text': ('not reachable' if self.service_down else self.ctl.setup.server['host']), 'go': None})
        return rows

    def _lobby_view(self):
        lobby = self.lobby
        if not lobby:
            return None
        players = [{'name': str(p.get('name') or ''), 'you': i == self.me, 'ready': bool(p.get('ready')),
                    'roster': p.get('roster') or 'unknown', 'stage': p.get('stage') or 'lobby'}
                   for i, p in enumerate(lobby.get('players') or [])]
        mine = players[self.me] if self.me < len(players) else None
        other = next((p for p in players if not p['you']), None)
        host = self.me == 0
        rules = self._rules_view(lobby, host) if isinstance(lobby.get('rules'), dict) else None   # None: a server before M3b
        return {'code': lobby.get('code'), 'public': bool(lobby.get('public')), 'state': lobby.get('state'),
                'waiting': lobby.get('waiting'), 'players': players, 'rules': rules,
                'roster_mode': (None if 'roster_mode' not in lobby else
                                {'mode': lobby.get('roster_mode'), 'uploaded': bool(lobby.get('host_roster')),
                                 'edit': host and lobby.get('state') not in LAUNCHING}),
                'chat': [{'n': c['n'], 'name': str(c.get('name') or ''), 'text': str(c.get('text') or ''),
                          'mine': c.get('who') == self.me}
                         for c in (lobby.get('chat') or [])[-CHAT_SHOWN:] if isinstance(c, dict) and isinstance(c.get('n'), int)],
                'host': host, 'host_name': players[0]['name'] if players else '',
                'me_ready': bool(mine and mine['ready']), 'partner': other['name'] if other else '',
                'full': len(players) == 2}

    @staticmethod
    def _rules_view(lobby, host):
        """The Match rules card: one row per rule with the choices, the lobby's pick, and whether this player may change
        it (the host, until the game is starting); `summary` names what differs from the defaults."""
        try:
            picked = RU.validate(lobby.get('rules') or {})
        except RU.RulesError:
            picked = dict(RU.DEFAULTS)
        edit = host and lobby.get('state') not in LAUNCHING
        rows = [{'key': key, 'label': name, 'value': picked[key], 'default': default, 'can_edit': edit,
                 'options': [{'value': v, 'label': text} for v, text in options]}
                for key, name, options, default in RU.RULES]
        return {'rows': rows, 'summary': RU.summary(picked), 'is_default': picked == RU.DEFAULTS, 'can_edit': edit}

    def _game_view(self, lobby):
        game = self.game
        if not game:
            return None
        phase = game['phase']
        partner = (lobby or {}).get('partner') or 'your friend'
        matched = bool(lobby) and (lobby['state'] == 'matched' or any(p['you'] and p['stage'] == 'matched'
                                                                      for p in lobby['players']))
        steps = []
        if phase in PHASES:
            now = (5 if matched else 4) if phase == 'running' else PHASES[phase]
            for i, text in enumerate(STEPS):
                text = text.format(partner=partner)
                if i == 2 and (game.get('manual') or not self.press_title):
                    text = 'Press ✕ on the title screen'
                if i == 3 and (game.get('ready_manual') or not self.press_title):
                    text = 'Press ✕ (READY) on Game Setup'
                steps.append({'text': text, 'state': 'done' if i < now else 'now' if i == now else 'todo'})
        return {'phase': phase, 'note': game.get('note') or '', 'manual': bool(game.get('manual')), 'steps': steps,
                'again': phase in ('failed', 'ended') and bool(lobby) and lobby['state'] in LAUNCHING}


def _down_text(text):
    """True for the words a service that did not answer left (cleared once it answers again)."""
    return text == CERT_TEXT or text.startswith('The lobby service did not answer')


def _age(seconds):
    """'2 min' for a lobby that is `seconds` old."""
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return ''
    return 'now' if s < 45 else f'{max(1, round(s / 60))} min'
