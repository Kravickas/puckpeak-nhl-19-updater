"""The Setup tab: where shadPS4 is and its checks, the server and the firewall (their card shows on the Multiplayer
tab), the picture packs (Downloads), this program's updates, and which roster you work on (rosters_ctl). docs/ui/setup.md.

The one click (setup_patch, the Game patch tab's Patch) = checks -> a clean-game record (first time) -> the data
overlay (the Game patch tab's layers, the default roster too when picked there) -> the eboot patch with the Overtime
server address and the network settings (gamesetup.install; the 32-team switch only when the roster served has an
active Seattle) -> status. Unpatch takes both away. The game folder is only ever read.

The checks (_scan, a job): shadPS4 is there (its version from the block in its exe), NHL 19 is CUSA11126 with update
1.60, a ShadNet user is set up in shadPS4 (and its last run signed in, from its log), the Overtime server answers the
game's first call (the redirector, a few seconds at most), the firewall rule, and the picture packs (packdownload).
A shadPS4 found there is remembered, and the game and saves folders follow it when the ones set are not there.

`SetupController(controller)` is one of the Controller's parts (registry.py): it shares its lock, busy flag, status
line and settings. Its slice `setup` is `view()`, with beta1's keys (snap_setup) that re/scripts/oneclick_run.py reads.
"""
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import webbrowser

from overtime_core import gamefiles, overlay, rosterupdate, tdb, xmlpatch

from .. import SITE, VERSION
from . import (boost, cachemove, cpucheck, crashreport, emuinput, emusettings, gamesetup, jobs, launch, packdownload,
               patch, patch_ctl, paths, pkginstall, selfupdate)
from .registry import Part
from .shell import friendly_date

# Where the community release sends the game (docs/notes/remaster-recon.md: the Nucleus slots hold 22-24 chars).
# The accounts slot (the login) gets https://ot.puckpeak.com/; nucleus_url only fills the slots the name doesn't fit.
SERVER = {'host': 'ot.puckpeak.com', 'nucleus_url': 'https://91.98.195.150/'}
HOST_ROOM = 29              # the game's redirector slot (xmlpatch FEATURES.redirector)
LOGIN_ROOM = min(room for _addr, room, _v in xmlpatch.FEATURES['nucleus'].lines) - len('https:///')
PLAY_WATCH_SECONDS = 180
FIREWALL_WAIT = 40          # seconds Let it through... waits for the rule (Windows asks first: UAC)
GAME_PORT = 'UDP 3659'      # the port NHL 19's online games use (docs/notes/beta-plan.md)
LABELS = {'emulator': 'shadPS4', 'game': 'NHL 19', 'shadnet': 'ShadNet', 'network': 'Network'}
STEPS = ('Looking at shadPS4...', 'Looking at NHL 19...', 'Asking ShadNet...', 'Asking the Overtime server...')
# the picture packs: name -> (title, core: the one click fetches it)
PACKS = {name: (p['title'], p['core']) for name, p in packdownload.PACKS.items()}
KITS = patch.KITS_PACK
WANTED = ('missing', 'newer', 'offline')    # pack states Download all fetches
# the packs with their own switch (patch.EXTRA_PACKS, the Game patch tab's More jerseys and ice card): never by
# Download all or the Photos, logos card (several hundred MB each)
OPTIONAL = frozenset(patch.EXTRA_PACKS)
PACK_TITLE = 'Updated assets'     # the core packs as one (v0.10.0's card; v0.70.0: a switch each downloads its own)
PACK_SUB = ('Updated logos, menu jerseys, centre ice and 3D jerseys for all 32 teams, and NHL.com player photos. Kept '
            'on this PC.')
PACK_SIZE = 'about 150 MB'      # the four packs of 2026-10-21 (148 MB) when the server cannot say
CPU_IDLE = {'busy': False, 'stage': '', 'part': None, 'result': None, 'zip': '', 'output': '', 'sending': False,
            'note': '', 'error': ''}


def waiting(busy):
    """'Wait a moment: patching NHL 19 is still running.' for a job's busy text ('Patching NHL 19...')."""
    text = str(busy).rstrip('. ')
    if text[1:2].islower():
        text = text[0].lower() + text[1:]
    return f'Wait a moment: {text} is still running.'


def patch_cache():
    """The app's cache folder, where art packs fetched later go (patch.art_places looks there first)."""
    return paths.app_dir('cache')


# Find game's picker: the launcher, the emulator, the game itself or its PKG (pkginstall)
FIND_KINDS = 'shadPS4 or NHL 19 (*.exe;eboot.bin;*.pkg)'
# Setup's Folders list, in its order: key -> label
FOLDERS = {'emulator': 'shadPS4', 'game': 'NHL 19', 'data': 'shadPS4 data', 'saves': 'Saves',
           'cache': 'Downloads and cache'}


def _game_of(path):
    """The NHL 19 folder when `path` is its eboot.bin (or a folder holding one), else ''."""
    if not path:
        return ''
    if os.path.isfile(path) and os.path.basename(path).lower() == 'eboot.bin':
        return os.path.dirname(os.path.abspath(path))
    if os.path.isdir(path) and os.path.isfile(os.path.join(path, 'eboot.bin')):
        return os.path.abspath(path)
    return ''


def _megabytes(n):
    return f'{n / 2**20:.0f} MB' if n else ''


def _gigabytes(n):
    return f'about {n / 2**30:.1f} GB' if n >= 2**30 else _megabytes(n)


BOOST_PACK = 'shadps4_nhl19.zip'
# the blue "!" beside the Updated assets size (owner 2026-11-07: testers thought it hung at 65%)
ASSETS_WAIT = ('Switching on every asset takes 20 to 40 minutes. The bar can stay on one number (often 65%) for a '
               'long time: it is still working. Keep Overtime open and wait for it to finish.')


def local_packs(cache_dir):
    """The packs as this PC has them, without the network: [{name, title, core, size, state ('here' | 'missing'),
    local_size, removable}] (removable: in the cache, where downloads go)."""
    out = []
    for name, (title, core) in PACKS.items():
        path = next((p for p in (os.path.join(d, name) for d in patch.art_places(cache_dir)) if os.path.isfile(p)),
                    None)
        local = os.path.getsize(path) if path else None
        out.append({'name': name, 'title': title, 'core': core, 'size': None, 'state': 'here' if path else 'missing',
                    'local_size': local, 'removable': bool(cache_dir and path
                                                           and os.path.dirname(path) == os.path.normpath(cache_dir))})
    return out


def pack_status(cache_dir, game_dir=None):
    """packdownload.status() (the published size and state of each pack: latest.json, up to 10 s; call it in a job),
    or local_packs() when OVERTIME_ART_PACKS names the only packs folder (the patch then reads nothing else, and
    nothing is asked of the server)."""
    if not cache_dir or os.environ.get(patch.ART_ENV):
        return local_packs(cache_dir)
    return [dict(r) for r in packdownload.status(cache_dir, game_dir=game_dir)]


def _pack_text(row):
    kits = row['name'] == KITS
    state, size = row['state'], _megabytes(row.get('size'))
    if state == 'here':
        return f"Downloaded ({_megabytes(row.get('local_size')) or 'ready'})." + (
            ' Patch the game to put them in.' if kits else '')
    if state == 'newer':
        return 'A newer version is out. Download it, then patch the game again.'
    if state == 'offline':
        return 'Not downloaded. The Overtime server does not answer: check your internet connection.'
    if state == 'wrong_roster':
        return 'Made for another roster, so not used. Update Overtime Roster, then download them again.'
    size = f' ({size})' if size else ''
    if kits:
        return f"Not downloaded{size}. Until then the teams wear the game's own kits."
    return f'Not downloaded{size}. Press Download.'


class SetupController(Part):
    SLICES = {'setup': 'view'}
    CALLS = {'setup_refresh': 'setup_refresh', 'setup_pick_emulator': 'pick_emulator',
             'setup_set_emulator': 'setup_set_emulator', 'setup_set_game': 'setup_set_game',
             'setup_emulator_page': 'setup_emulator_page', 'setup_set_server': 'setup_set_server',
             'setup_firewall': 'setup_firewall', 'setup_kits_download': 'kits_download',
             'setup_kits_remove': 'kits_remove', 'setup_pack_download': 'pack_download',
             'setup_pack_remove': 'pack_remove', 'setup_packs_download_all': 'packs_download_all',
             'setup_packs_get': 'packs_get', 'setup_packs_drop': 'packs_drop', 'setup_pack_switch': 'pack_switch',
             'setup_check_updates': 'check_updates', 'setup_check_updates_now': 'check_now',
             'setup_patch': 'setup_patch', 'setup_unpatch': 'setup_unpatch', 'setup_verify': 'setup_verify',
             'setup_play': 'setup_play', 'setup_build': 'setup_build', 'setup_build_update': 'setup_build_update',
             'setup_boost': 'setup_boost',
             'setup_boost_source': 'setup_boost_source', 'setup_resolution': 'setup_resolution',
             'setup_pkg_source': 'setup_pkg_source',
             'setup_emu_settings': 'emu_settings', 'setup_emu_settings_save': 'emu_settings_save',
             'setup_emu_input': 'emu_input', 'setup_emu_input_save': 'emu_input_save',
             'setup_cpu_check': 'cpu_check', 'setup_cpu_send': 'cpu_send',
             'setup_folder_pick': 'folder_pick', 'setup_folder_set': 'folder_set', 'setup_folder_auto': 'folder_auto'}
    TAB = 'setup'

    def __init__(self, ctl):
        super().__init__(ctl)
        prefs = ctl.prefs.get('setup') or {}
        self.emulator = prefs.get('emulator') or ''
        self.server = {**SERVER, **(prefs.get('server') or {})}
        self.skipped = prefs.get('skipped') or ''     # "Skip this version": not offered again
        self.server_error = None    # why the typed server address was refused
        self.found = None  # the last look: emulators, build, games, status, network, users, firewall, server, ...
        self.verify_result = None
        self.play = None  # {'state', 'pid', 'log'} while / after Play
        self._launching = False  # a Play click is starting the emulator (a second click must not start another)
        self.checking = False   # a look (_scan) runs
        self._looks = 0         # the newest look's number (an older one that ends later is dropped)
        self.newer = None       # {version, notes} when a newer version is out (window.main's look, or Check now)
        self.looked = False     # Check now looked in this session
        self.packs = None       # pack_status() of the last look
        self.boost_table = None     # packdownload.published() of the last look
        self.dl = None          # {names, name, part, share} while packs download
        self.dl_stop = False    # a pack switched off while it downloads
        self.asked = set()      # the core asset switches (patch_ctl.PACK_KEYS) switched on here: their packs download
        self.first_assets = bool(ctl.prefs.get('first_assets'))  # a new install's asset packs still to download
        # the shadPS4 builds (boost.py): the one chosen on the Boost performance card (Nightly from the first start,
        # owner 2026-11-11), and {emulator: the player's own shadPS4, sha: {build: sha256 of the pack in place}}
        self.build = boost.name_of(prefs.get('build'))
        old = prefs.get('boost') or {}
        sha = {b: s for b, s in (old.get('sha') or {}).items() if b in boost.BUILDS and isinstance(s, str)}
        if isinstance(old.get('sha256'), str):      # apps before 0.90.2: the Kravickas build's
            sha.setdefault(boost.KRAVICKAS, old['sha256'])
        self.boost = {'emulator': old.get('emulator') or '', 'sha': sha}
        self.boost_part = None  # how far a build's download is (0..1)
        self.boost_getting = ''     # the label of the build downloading
        # the data folders (normcased) that got PS4 Pro mode and Shader cache once (emusettings.apply_defaults)
        self.defaults_done = [d for d in prefs.get('defaults_done') or [] if isinstance(d, str)]
        self.cpu = dict(CPU_IDLE)   # Check my CPU (cpucheck.py): the run and its last result, this session only
        self.resolution = prefs.get('resolution') if prefs.get('resolution') in xmlpatch.RESOLUTIONS else 1080
        gamesetup.set_display(prefs.get('display'))     # Game settings' display mode (default borderless)
        # Folders list: what the player set by hand ({'emulator': bool, 'game': bool, 'saves': bool, 'data': path,
        # 'cache': path (paths.cache_dir reads it from the settings itself)}); a
        # folder set here is never replaced by what a look finds (a tester's portable shadPS4, 2026-11-07)
        self.custom = {k: v for k, v in (prefs.get('custom') or {}).items() if k in FOLDERS and v}
        gamesetup.set_custom_data(self.custom.get('data') or '')

    # --- helpers -------------------------------------------------------------------------------------------
    def _remember(self):
        self.ctl.remember(setup={'emulator': self.emulator, 'skipped': self.skipped, 'boost': self.boost,
                                 'build': self.build, 'defaults_done': list(self.defaults_done),
                                 'resolution': self.resolution, 'display': gamesetup.display_mode(),
                                 'custom': dict(self.custom),
                                 'server': {k: v for k, v in self.server.items() if v != SERVER.get(k)}})

    def features(self):
        """The eboot patch's features for this game: the one place that picks them, for a new patch file (_xml) and for
        the next start's refresh (patch_ctl.refresh_network). The cross-vendor block only for the eboot it was made
        for (xmlpatch.for_eboot)."""
        return xmlpatch.for_eboot(gamesetup.eboot_sha(getattr(self.ctl, 'game_dir', None)))

    def _xml(self):
        return xmlpatch.with_resolution(xmlpatch.build(self.server['host'], self.server.get('nucleus_url'),
                                                       self.features()), self.resolution)

    def _wait(self):
        """True (and the Help bar says so) while another job runs."""
        busy = self.ctl.busy
        if busy:
            self.ctl.say(waiting(busy), 'caution')
        return bool(busy)

    def _job(self, busy, work, said, expected=(), rescan=True, after=None):
        """work() in a job holding the busy flag; then said(out) -> (text, tone) for the Help bar. After it (also
        when it failed): after(), then a new look when `rescan`."""
        ctl = self.ctl
        with ctl.lock:
            if ctl.busy:
                return None
            ctl.busy = busy
        ctl.say(busy, 'info', -1)
        ctl.changed('setup', 'patch', 'app')

        def end():
            if after:
                after()
            if rescan:
                self._scan()
            else:
                ctl.changed('setup', 'patch', 'app')

        def done(out):
            with ctl.lock:
                ctl.busy = None
            text, tone = said(out)
            if text:
                ctl.say(text, tone)
            end()

        def failed(message):
            with ctl.lock:
                ctl.busy = None
            ctl.host.log(message)
            ctl.say(message, 'bad')
            end()
        jobs.run(work, done, failed, expected=(gamesetup.SetupError, launch.LaunchError, overlay.PatchError,
                                               patch.PatchFailed, xmlpatch.PatchError, OSError, ValueError) + expected)
        return None

    # --- the look ------------------------------------------------------------------------------------------
    def _scan(self, announce=False, picked=False, auto=None):
        """Look at everything again (a job: the firewall check takes a second or two, the server a few). announce:
        the Help bar walks through the steps and ends with the first thing still wrong (Check again, a pick);
        picked: shadPS4 was just picked (the saves folder follows it); auto: 'game' / 'saves' was put back to Auto
        in the Folders list (it takes what this look finds)."""
        ctl = self.ctl
        with ctl.lock:
            self._looks += 1
            look = self._looks
            self.checking = True
            emulator, host, game_dir = self.emulator, self.server['host'], ctl.game_dir
            custom_game = bool(self.custom.get('game'))
            announce = announce and not ctl.busy

        def step(n):
            if announce:
                ctl.say(STEPS[n], 'info', (n + 1) / (len(STEPS) + 1))

        def work():
            packs, cache = {}, patch_cache()

            def look_packs():           # latest.json, meanwhile (a pack look that fails keeps the last one)
                try:
                    packs['rows'] = pack_status(cache, game_dir)
                    packs['published'] = None if os.environ.get(patch.ART_ENV) else packdownload.published()
                except Exception as err:  # noqa: BLE001
                    ctl.host.log(f'The picture packs could not be looked at: {err}')
            worker = threading.Thread(target=look_packs, daemon=True, name='packs-look')
            worker.start()
            step(0)
            emus = gamesetup.find_emulators(near=gamesetup.around(game_dir, 2) if game_dir else ())
            emu = emulator if emulator and os.path.isfile(emulator) else (emus[0] if emus else '')
            user = gamesetup.emu_user_dir(emu) if emu else ''
            build = gamesetup.emulator_build(emu) if emu else None
            step(1)
            # NHL 19 beside the folder set and beside shadPS4 too, not only in the folders shadPS4's config lists
            extra = ([os.path.dirname(game_dir)] if game_dir else []) + (gamesetup.around(emu) if emu else [])
            games = gamesetup.find_games(user, extra=extra) if user else []
            game = gamesetup.read_game(game_dir) if game_dir else None
            follow = None
            if not (game and game['ok']) and 'OVERTIME_GAME_DIR' not in os.environ and not custom_game:
                ok = [g for g in games if g['ok']]
                if ok:
                    follow, game = ok[0]['path'], ok[0]
            step(2)
            users = gamesetup.shadnet_users(user) if user else []
            log = gamesetup.shadnet_log(user) if user else None
            try:
                users_time = os.path.getmtime(os.path.join(user, 'users.json')) if user else None
            except OSError:
                users_time = None
            firewall = gamesetup.firewall_allows(emu) if emu else None
            step(3)
            answers = gamesetup.server_answers(host) if emu else (None, '')
            worker.join(15)
            status = gamesetup.status(emu or None)
            return {
                'emulators': emus, 'emulator': emu, 'build': build, 'user_dir': user, 'games': games, 'game': game,
                'follow_game': follow, 'saves': gamesetup.save_dir(user) if user else '',
                'status': status, 'teams32': patch_ctl.installed_teams32(status),
                'overlay': overlay.status(follow or game_dir) if game and game['ok'] else None,
                'network': gamesetup.network_settings(user) if user else {},
                'users': users, 'log': log, 'users_time': users_time,
                'firewall': firewall, 'host': host, 'server': answers,
                'running': overlay.emulator_running(),
                'clean': gamesetup.load_clean(),
                'packs': packs.get('rows'), 'published': packs.get('published'),
            }

        def done(found):
            with ctl.lock:
                if look != self._looks:
                    return              # a newer look runs: it tells
                self.found = found
                self.checking = False
                if found['packs'] is not None:
                    self.packs = found['packs']
                    self.boost_table = found.get('published')
                if not self.known_emulator() and found['emulator']:
                    self.emulator = found['emulator']   # found: remembered
                    self._remember()
            self._follow(found, picked, auto)
            self._defaults(found)
            self._first_assets(found)
            if announce:
                text, tone = self._outcome()
                ctl.say(text, tone, 1)
            ctl.changed('setup', 'app', 'patch')

        def failed(message):
            with ctl.lock:
                if look == self._looks:
                    self.checking = False
            ctl.say(message, 'bad')
            ctl.changed('setup')
        ctl.changed('setup')
        jobs.run(work, done, failed)

    def _follow(self, found, picked, auto=None):
        """The game and saves folders follow shadPS4: NHL 19 found in its game folders when the folder set does not
        hold it; its saves folder when the one set is not there, or shadPS4 was just picked and no roster is open.
        A folder the player set in the Folders list is never overruled, nor OVERTIME_GAME_DIR and OVERTIME_SAVE_DIR
        (tests, the owner's runs). `auto` ('game' / 'saves', just put back to Auto) takes what was found."""
        c = self.ctl
        follow = found.get('follow_game')
        if auto == 'game' and not follow and 'OVERTIME_GAME_DIR' not in os.environ:
            ok = [g['path'] for g in found.get('games') or [] if g.get('ok')]
            follow = ok[0] if ok and os.path.normcase(ok[0]) != os.path.normcase(c.game_dir or '') else None
        if follow and not self.custom.get('game') and callable(getattr(c, 'set_game_dir', None)):
            c.host.log(f"NHL 19 found in {follow}: the game folder follows shadPS4.")
            c.set_game_dir(follow)
        saves, now = found.get('saves') or '', getattr(c, 'save_dir', None)
        if not saves or now is None or 'OVERTIME_SAVE_DIR' in os.environ or self.custom.get('saves'):
            return
        if not os.path.isdir(saves) and auto != 'saves':
            return
        if os.path.normcase(os.path.normpath(saves)) == os.path.normcase(os.path.normpath(now or '.')):
            return
        if auto == 'saves' or not os.path.isdir(now or '') or (picked and getattr(c, 'session', None) is None):
            if callable(getattr(c, 'set_save_dir', None)):
                c.host.log(f'Saves folder: {saves} (shadPS4\'s).')
                c.set_save_dir(saves)

    def _defaults(self, found=None):
        """Game settings without Patch, once a game is found (owner 2026-11-11, 0.90.2): Readbacks Precise and Readback
        linear images every time; PS4 Pro mode, Shader cache, Direct memory access, Vblank 9999 and DMem 3500 once
        per data folder (emusettings.apply_defaults, FIRST_DEFAULTS).
        While the game runs or a match is set up, the next look does it."""
        f = found if found is not None else (self.found or {})
        emu = self.known_emulator()
        user, game = f.get('user_dir') or (gamesetup.emu_user_dir(emu) if emu else ''), f.get('game') or {}
        if not user or not game.get('ok'):
            return
        key = os.path.normcase(os.path.abspath(user))
        first = key not in self.defaults_done
        try:
            wrote = emusettings.apply_defaults(user, first)
        except emusettings.SettingsError as err:
            self.ctl.host.log(f'Game settings not set now: {err}')
            return
        if first:
            with self.ctl.lock:
                self.defaults_done.append(key)
                self._remember()
        if wrote:
            self.ctl.host.log(f"Game settings set without Patch: {', '.join(wrote)} ({user})")

    def _first_assets(self, found):
        """A new install's first look that finds NHL 19 and the published packs (0.90.2, owner 2026-11-11): the team
        art, 3D jerseys and player photos it starts with switched on (controller: `first_assets`) download now, in turn,
        The mark goes only once nothing is left to fetch (all here, or switched off, or a failed pack's switch went off):
        busy, offline or an app closed mid-download, the next look (or start) tries again."""
        c = self.ctl
        if not self.first_assets or self.packs is None or not (found.get('game') or {}).get('ok') \
                or not self.known_emulator() or c.busy:
            return
        rows = {r['name']: r for r in self.packs}
        names = {n for k in patch_ctl.PACK_KEYS for n in patch_ctl.ASSET_PACKS[k]}
        if any(rows.get(n, {}).get('state') == 'offline' for n in names):
            return
        with c.lock:
            self.asked.update(k for k in patch_ctl.PACK_KEYS if c.patch_want.get(k))
        if not self._extras_wanted():
            with c.lock:
                self.first_assets = False
                c.remember(first_assets=False)
            return
        c.host.log('New install: downloading the team art, 3D jerseys and player photos (Updated assets).')
        self._extras_next()

    def find_at_start(self):
        """At the app's start (rosters_ctl.start): with no shadPS4 picked yet, look for one (no network, no
        questions), so the app knows it from now on (app.emulator_known)."""
        if self.known_emulator():
            return

        def done(emus):
            with self.ctl.lock:
                if self.known_emulator() or not emus:
                    return
                self.emulator = emus[0]
                self._remember()
            self.ctl.changed('setup', 'app')
        jobs.run(gamesetup.find_emulators, done, lambda message: None)

    def _outcome(self):
        """The Help bar's line after a look: the first thing still wrong in its tone, else what to do next."""
        f = self.found or {}
        if not self.known_emulator():
            return 'Press Find game and pick NHL 19 (its eboot.bin or PKG). No shadPS4 needed.', 'info'
        checks = self._checks(f, False)
        for tone in ('bad', 'caution'):
            bad = next((c for c in checks if c['tone'] == tone), None)
            if bad:
                return bad['text'], tone
        rosters = self.ctl.parts.get('rosters') if hasattr(self.ctl, 'parts') else None
        if rosters is not None and rosters.open_roster() is not None:
            return 'Everything is ready.', 'good'
        return 'shadPS4 and NHL 19 are ready. Now pick the roster you work on.', 'good'

    # --- buttons -------------------------------------------------------------------------------------------
    def setup_refresh(self):
        self._scan(announce=True)
        return {'ok': True}

    def setup_set_emulator(self, path):
        picked = (path or '').strip().strip('"')
        if picked.lower().endswith('.pkg') and os.path.isfile(picked):
            return self.setup_install_pkg(picked)
        game = _game_of(picked)
        by_hand = bool(picked) and not game      # shadPS4 itself picked (not found from the game)
        if game:
            # NHL 19 itself: the game folder is that one, and shadPS4 is the one the player runs (QtLauncher's
            # selected version, else the newest found where the emulator keeps its games)
            self.ctl.set_game_dir(game)
            found = gamesetup.find_emulators(near=gamesetup.around(game, 2))
            if not found and self.known_emulator():
                self._scan(announce=True, picked=True)     # the shadPS4 in use stays (the app's own, or one picked)
                return {'ok': True}
            if not found:
                # no shadPS4 on this PC: the app's own (owner 2026-11-10: players need not install one)
                return self._standalone('Found NHL 19. No shadPS4 on this PC, so Overtime gets its own...')
            picked = found[0]
        path = gamesetup.resolve_emulator(picked) if picked else ''
        if picked and not path:
            name = os.path.basename(picked.rstrip('\\/')) or picked
            text = (f'No shadPS4 found in {name}. Point Find game at NHL 19\'s eboot.bin or its PKG (Overtime gets '
                    'shadPS4 by itself), or at shadPS4QtLauncher.exe or shadPS4.exe.')
            self.ctl.say(text, 'bad')
            return {'error': text}
        with self.ctl.lock:
            self.emulator = path
            if by_hand:
                self.custom['emulator'] = True
            self._remember()
        if path:
            self.ctl.host.log(f'shadPS4: {path}')
        self._scan(announce=True, picked=True)
        return {'ok': True}

    def setup_set_game(self, path):
        self.ctl.set_game_dir(path)
        self._scan()
        return {'ok': True}

    # --- no shadPS4 on this PC: the app's own (owner 2026-11-10, docs/notes/standalone.md) ---------------------------
    def standalone(self):
        """True when NHL 19 plays on a build the app set up with no shadPS4 of the player's on this PC."""
        own = self.boost.get('emulator') or ''
        return self._boosted() and not os.path.isfile(own)

    def _build_label(self, build=None):
        return boost.BUILDS[boost.name_of(build or self.build)]['label']

    def _install_build(self, build=None):
        """boost.install of the chosen build with the card's progress (in a job)."""
        build = boost.name_of(build or self.build)
        with self.ctl.lock:
            self.boost_getting = self._build_label(build)
        return build, boost.install(build, patch_cache(), self._boost_progress)

    def _standalone(self, intro):
        """The chosen build as this PC's shadPS4 (boost.install), a job."""
        if self._wait():
            return None
        self.ctl.say(intro, 'info')

        def said(out):
            self._boost_applied(*out)
            return (f'NHL 19 plays on the {self._build_label(out[0])} build of shadPS4, which Overtime set up for you. '
                    'Sign in to ShadNet on the Multiplayer tab to play online.', 'good')
        self._job(f'Getting shadPS4 (the {self._build_label()} build) for NHL 19...', self._install_build, said,
                  expected=(boost.BoostError,), after=self._boost_done)
        return {'ok': True}

    def setup_install_pkg(self, path):
        """Find game picked a .pkg: install it (pkginstall.install, a job; the base beside the PKG, the update beside
        the game), the game folder follows, and with no shadPS4 on this PC the Kravickas build is set up in the same
        job."""
        if self._wait():
            return None
        c = self.ctl
        game_dir, emu = c.game_dir, self.known_emulator()

        def progress(stage, done, total):
            part = min(1.0, done / total) if total else 0.0
            c.say('Downloading the PKG tool...' if stage == 'tool' else
                  f'Extracting the PKG... {round(part * 100)} % of {_gigabytes(total)}', 'info', part)

        def work():
            use, kind, game = pkginstall.install(path, game_dir, progress)
            c.set_game_dir(use)
            got = None if emu else self._install_build()
            return use, kind, game, got

        def said(out):
            use, kind, game, got = out
            c.host.log(f"PKG installed: {path} -> {use} ({'update' if kind == pkginstall.UPDATE else 'game'}, "
                       f"version {game.get('app_ver')})")
            if got is not None:
                self._boost_applied(*got)
            also = f' shadPS4 (the {self._build_label(got[0])} build) is set up too.' if got is not None else ''
            version = (game.get('app_ver') or '').lstrip('0') or '?'
            needed = gamesetup.APP_VER.lstrip('0')
            if game.get('ok'):
                return f'NHL 19 {version} is ready in {use}.{also}', 'good'
            if kind == pkginstall.BASE:
                return f'NHL 19 is in {use}.{also} Now press Find game again and pick the update {needed} PKG.', 'caution'
            return (f'Update {version} is installed, but Overtime needs {needed}: pick that update PKG with Find '
                    f'game.{also}', 'caution')
        self._job(f'Installing {os.path.basename(path)}...', work, said,
                  expected=(pkginstall.PkgError, boost.BoostError), after=self._boost_done)
        return {'ok': True}

    def setup_pkg_source(self):
        webbrowser.open(pkginstall.SOURCE)
        return {'ok': True}

    def setup_set_server(self, host, nucleus_url=None):
        """The address for a LAN or private server; empty puts back the community server."""
        host, nucleus_url = (host or '').strip(), (nucleus_url or '').strip() or None
        server = dict(SERVER) if host in ('', SERVER['host']) and not nucleus_url else {'host': host,
                                                                                       'nucleus_url': nucleus_url}
        try:
            xmlpatch.build(server['host'], server['nucleus_url'])
        except xmlpatch.PatchError as err:
            text = self._server_refused(server['host'], err)
            self.server_error = text
            self.ctl.host.log(f'Server address refused: {err}')
            self.ctl.say(f'Server address refused. {text}', 'bad')
            self.ctl.changed('setup')
            return {'error': text}
        with self.ctl.lock:
            changed = server != self.server
            self.server, self.server_error = server, None
            self._remember()
        if changed:
            self.ctl.host.log(f"Server: {server['host']}")
            try:
                put = patch_ctl.refresh_network(self)   # a patched game takes it now: no Patch (owner, 2026-11-03)
            except (gamesetup.SetupError, OSError, ValueError) as err:
                self.ctl.host.log(f'The server was not put into the game: {err}')
                put = None
            name = 'The Overtime server is set again.' if server == SERVER else f"Server set to {server['host']}."
            if put:
                then = 'NHL 19 uses it from its next start.'
            elif gamesetup.load_manifest() is None:
                then = 'Patch the game to use it.'
            else:
                then = 'Patch the game again to use it.'
            self.ctl.say(f'{name} {then}', 'good')
            if put == 'written':
                self.ctl.changed('patch')
        self.ctl.changed('setup')
        return {'ok': True}

    @staticmethod
    def _server_refused(host, err):
        """Why an address does not go into the game, in player words (xmlpatch says it in its own)."""
        if not xmlpatch._HOST.match(host or '') or '--' in host:
            return 'Use letters, digits, dots and dashes only, like ot.puckpeak.com.'
        if len(host) > HOST_ROOM:
            return f'That address is too long: the game holds {HOST_ROOM} characters at most.'
        if 'Nucleus' in str(err) or 'slot' in str(err):
            return (f'That address is too long for the game\'s sign-in: use {LOGIN_ROOM} characters at most, '
                    'or the server\'s IP address.')
        return 'The game cannot take that address. Use the server\'s name or IP address.'

    def setup_patch(self):
        """The one click (patch_ctl.one_click: the Game patch tab's Patch is the same)."""
        return patch_ctl.one_click(self)

    def _seattle_ready(self, database):
        """Whether the roster the game starts from takes the 32-team switch (rosterupdate.seattle_ready): `database`
        (the default roster just built, or None to keep the one the overlay serves); none served is the stock roster,
        whose Seattle is empty. Without it New Season would crash with the switch on (ws8 run7a), so the patch then
        keeps 31 teams."""
        game_dir = self.ctl.game_dir
        raw = database
        if raw is None:
            state = overlay.status(game_dir)
            if 'database' in (state.get('layers') or {}):
                raw = overlay._current_database(game_dir, state)
        return raw is not None and rosterupdate.seattle_ready(tdb.Database.parse(raw, self.ctl.game.schema()))

    def _default_roster(self):
        """The verified default the exe carries (the bytes the in-game tests ran), unless Update was run in this
        app: then the default rebuilt from it, kept in the cache for later patches (defaultdb.pick). Without a
        verified default (a source run without the capture) it is built fresh, as before."""
        ctl = self.ctl
        from overtime_core import nhlcom
        from . import defaultdb, paths, update
        with ctl.lock:
            gathered, season, per32, offline = ctl.upd_gathered, ctl.upd_season, ctl.upd_per32, ctl.upd_offline
        g = gathered if gathered is not None and gathered.season == season else None
        rebuild = (lambda: patch.updated_default(ctl.game, g, per32, log=ctl.host.log)[0]) if g is not None else None
        database, came = defaultdb.pick(paths.app_dir('cache'), rebuild, season)
        self.default_came = came        # Patch's club logos ask where it came from (patch_ctl.clubart_roster)
        if database is not None:
            ctl.host.log({'update': 'Default roster: rebuilt from the Update tab\'s data (kept for later patches).',
                          'cache': 'Default roster: the one rebuilt after your last Update.',
                          'embedded': 'Default roster: the verified default this version ships.'}[came])
            return database
        client = nhlcom.Client(cache_dir=paths.app_dir('cache'))
        g = update.gather(client, season, paths.app_dir('cache'), fetch=update.fetch, offline=offline,
                          log=ctl.host.log)
        database, _rep = patch.updated_default(ctl.game, g, per32, log=ctl.host.log)
        return database

    def setup_unpatch(self):
        return patch_ctl.one_unpatch(self)

    def setup_verify(self, full=False):
        """Compare the game folder with the clean record (made at the first patch, or now)."""
        return patch_ctl.verify(self, full)

    def play_state(self):
        """The header's Play NHL 19 button (shell.app): {can, text, why, progress}. It can once a game is found and
        nothing else runs."""
        c = self.ctl
        if self.found is None:      # before the first look: the game and shadPS4 the app remembers
            game_ok = bool(c.game_dir and self.known_emulator())
        else:
            game_ok = bool((self.found.get('game') or {}).get('ok'))
        part = self.boost_part
        running = (self.play or {}).get('state') in ('starting', 'running') or self._launching
        if part is not None:
            return {'can': False, 'text': f'Getting {self.boost_getting or self._build_label()} {round(part * 100)}%',
                    'why': 'Downloading the shadPS4 build.', 'progress': part}
        if running:
            return {'can': False, 'text': 'NHL 19 is running', 'why': 'NHL 19 is running.', 'progress': None}
        if not game_ok:
            return {'can': False, 'text': 'Play NHL 19', 'why': 'Find NHL 19 first: press Find game in Setup.',
                    'progress': None}
        if c.busy:
            return {'can': False, 'text': 'Play NHL 19', 'why': waiting(c.busy), 'progress': None}
        return {'can': True, 'text': 'Play NHL 19', 'why': f'Starts NHL 19 on the {self._build_label()} build.',
                'progress': None}

    def _play_exe(self):
        """(exe to play on, build or None, why it is the player's own or '') without downloading. exe '' = the chosen
        build must download first."""
        current = self.known_emulator()
        own = current if current and boost.build_of(current) is None else (self.boost.get('emulator') or '')
        if own and os.path.isfile(own) and boost.own_portable(own):
            return own, None, ('Your shadPS4 keeps its saves in its own user folder, so NHL 19 starts on it, not on the '
                               f'{self._build_label()} build.')
        build = self.build
        exe = boost.here(build)
        pub = (self.boost_table or {}).get(boost.BUILDS[build]['pack'])
        if exe and pub is not None and pub.digest != self.boost['sha'].get(build):
            exe = ''                    # a newer build is published: Play gets it first
        return exe, build, ''

    def setup_play(self):
        """Play NHL 19 (the header button, Game patch's Play): the chosen build, downloaded first when it is not here or
        a newer one is published (offline with it here: plays as it is); then patch_ctl.play (not patched: the
        Question first)."""
        if self._wait():
            return None
        if overlay.emulator_running():
            self.ctl.say('NHL 19 is already running.', 'caution')
            return {'error': 'NHL 19 is already running.'}
        exe, build, why = self._play_exe()
        if exe:
            if build is None:
                self._use_own(exe)
            else:
                self._use_build(build, exe)
            if why:
                self.ctl.say(why, 'caution')
            self._defaults()
            return patch_ctl.play(self)

        def said(out):
            self._boost_applied(*out)
            self._defaults()
            patch_ctl.play(self)
            return '', ''

        def work():
            try:
                return self._install_build(build)
            except boost.BoostError:
                old = boost.here(build)
                if old and self.boost['sha'].get(build):
                    return build, (old, self.boost['sha'][build])   # offline: the build here plays as it is
                raise
        self._job(f'Getting the {self._build_label(build)} build of shadPS4...', work, said,
                  expected=(boost.BoostError,), after=self._boost_done)
        self.ctl.changed('app')
        return {'ok': True}

    def _use_own(self, exe):
        with self.ctl.lock:
            if not boost.same(self.emulator, exe):
                self.emulator = exe
                self._remember()

    def _use_build(self, build, exe):
        """`exe` (a build here) is the shadPS4 the app plays with; the player's own is kept."""
        with self.ctl.lock:
            current = self.known_emulator()
            if current and boost.build_of(current) is None:
                self.boost['emulator'] = current
            if not boost.same(self.emulator, exe):
                self.emulator = exe
                self.ctl.host.log(f'shadPS4: the {self._build_label(build)} build ({exe})')
            self._remember()

    def _watch_play(self, emu, proc):
        """Read the emulator log for a few minutes: did the patch apply, is ShadNet signed in?"""
        end = time.monotonic() + PLAY_WATCH_SECONDS
        while time.monotonic() < end:
            time.sleep(5)
            info = launch.check(emu)
            exited = proc.poll() is not None
            with self.ctl.lock:
                self.play = {'state': 'ended' if exited else 'running', 'pid': proc.pid, 'log': info}
            self.ctl.changed('setup', 'app')
            if exited:
                return

    def setup_firewall(self):
        """Ask Windows (UAC) to let shadPS4 in; only ever on the player's click. Then waits (a job) until the rule
        is there, up to FIREWALL_WAIT seconds."""
        emu = self.known_emulator()
        if not emu or sys.platform != 'win32':
            self.ctl.say('Find NHL 19 first.', 'caution')
            return {'error': 'Find NHL 19 first.'}
        if (self.found or {}).get('firewall') is True:
            self.ctl.say('Windows already lets NHL 19 through.', 'good')
            return {'ok': True}
        if self._wait():
            return None
        import ctypes
        args = subprocess.list2cmdline(gamesetup.firewall_rule_args(emu))
        rc = ctypes.windll.shell32.ShellExecuteW(None, 'runas', 'netsh', args, None, 0)
        if rc <= 32:
            self.ctl.say('Windows did not add the rule (the question was answered No). Press Let it through... '
                         'again and answer Yes.', 'caution')
            return {'ok': False}

        def work():
            end = time.monotonic() + FIREWALL_WAIT
            while time.monotonic() < end:
                if gamesetup.firewall_allows(emu):
                    return True
                time.sleep(2)
            return False
        self._job('Letting NHL 19 through the firewall...', work,
                  lambda ok: ('Windows lets NHL 19 through now. Online games can connect.', 'good') if ok else
                  ('NHL 19 is not let through yet. Press Let it through... again and answer Yes when Windows asks.',
                   'caution'))
        return {'ok': True}

    def setup_emulator_page(self):
        """Kept for old pages: shadPS4 is no longer needed (the app sets up its own)."""
        webbrowser.open(gamesetup.EMULATOR_URL)
        self.ctl.say('Opened the shadPS4 QtLauncher page. Install it, download a version in it, then pick its folder.',
                     'info')
        return {'ok': True}

    # --- shadPS4 ---------------------------------------------------------------------------------------------------
    def known_emulator(self):
        """The shadPS4.exe picked (or found), when it is still there; '' before the first pick."""
        return self.emulator if self.emulator and os.path.isfile(self.emulator) else ''

    def pick_emulator(self, folder=False):
        """Find game: Windows' picker for shadPS4QtLauncher.exe, shadPS4.exe or NHL 19's eboot.bin (one button, owner
        2026-11-07), then as setup_set_emulator. `folder` picks a folder instead (kept for old pages). {type: true}
        in browser mode (no window to show it in: the page asks for the path instead)."""
        if self._wait():
            return None
        pick = getattr(self.ctl.host, 'pick', None)
        start = os.path.dirname(self.emulator) if self.emulator else ''
        path = (pick(True, start) if folder else pick(False, start, (FIND_KINDS,))) if pick else None
        if path is None:
            return {'type': True}
        if not path:
            return {'cancelled': True}
        return self.setup_set_emulator(path)

    # --- Folders: each one found, or set by hand (Change...), and back to found (Auto) ---------------------------------
    def _folder_now(self, key):
        f = self.found or {}
        emu = self.known_emulator()
        data = (gamesetup.emu_user_dir(emu) if emu else gamesetup.custom_data()) or f.get('user_dir') or ''
        return {'emulator': emu, 'game': self.ctl.game_dir or '', 'data': data,
                'saves': getattr(self.ctl, 'save_dir', '') or '',
                'cache': paths.chosen_cache_dir() or paths.default_cache_dir()}[key]

    def _boosted(self):
        emu = self.known_emulator()
        return boost.build_of(emu) is not None

    def folder_pick(self, key):
        """Change...: Windows' picker (a file for shadPS4, a folder for the rest), then folder_set. {type: true} in
        browser mode (the page asks for the path)."""
        if key not in FOLDERS:
            return {'error': f'no folder {key}'}
        if key == 'emulator':
            return self.pick_emulator()
        if self._wait():
            return None
        pick = getattr(self.ctl.host, 'pick', None)
        now = self._folder_now(key)
        path = pick(True, now if os.path.isdir(now) else os.path.dirname(now)) if pick else None
        if path is None:
            return {'type': True}
        if not path:
            return {'cancelled': True}
        return self.folder_set(key, path)

    def _check_folder(self, key, path):
        """(folder to use, None) or (None, why not) for a folder the player picked."""
        if key == 'game':
            game = _game_of(path) or path
            info = gamesetup.read_game(game) if os.path.isdir(game) else None
            if not info or info['title_id'] not in gamesetup.TITLE_IDS:
                return None, (f'No NHL 19 in {path}. Pick the game folder: the one holding eboot.bin and sce_sys.')
            return os.path.abspath(game), None
        if key == 'data':
            if not gamesetup.is_data_dir(path):
                return None, (f'No config.json in {path}. Pick shadPS4\'s data folder: "user" beside shadPS4.exe, or '
                              '%APPDATA%\\shadPS4.')
            if not gamesetup.reachable_data_dir(path):
                return None, (f'shadPS4 cannot use {path}: it reads the "user" folder inside the folder it starts '
                              'from, or %APPDATA%\\shadPS4. Pick a folder named "user", or %APPDATA%\\shadPS4.')
            if self._boosted() and os.path.normcase(os.path.abspath(path)) != os.path.normcase(
                    gamesetup.emu_user_dir(boost.exe_path())):
                return None, ("Overtime's shadPS4 builds use %APPDATA%\\shadPS4. To use another data folder, pick "
                              'your own shadPS4 with Find game first.')
            return os.path.abspath(path), None
        if key == 'cache':
            return self._check_cache(path)
        if not os.path.isdir(path):           # saves: the game's save folder, or a folder above it
            return None, f'{path} is not a folder.'
        title = gamesetup.active_title()      # shadPS4's Home folder, home, savedata or the game's folder itself
        for inner in (os.path.join(path, 'home', '1000', 'savedata', title), os.path.join(path, '1000', 'savedata', title),
                      os.path.join(path, title)):
            if os.path.isdir(inner):
                return os.path.abspath(inner), None
        return os.path.abspath(path), None

    def folder_set(self, key, path):
        """A folder of the Folders list set by hand: checked, remembered, never replaced by a look until Auto."""
        path = (path or '').strip().strip('"')
        if key == 'emulator':
            return self.setup_set_emulator(path)
        if key not in FOLDERS or not path:
            return {'error': 'Pick a folder.'}
        use, why = self._check_folder(key, path)
        if why:
            self.ctl.say(why, 'bad')
            return {'error': why}
        if key == 'cache':
            return self._cache_move(use)
        with self.ctl.lock:
            self.custom[key] = use if key == 'data' else True
            if key == 'data':
                gamesetup.set_custom_data(use)
            self._remember()
        self.ctl.host.log(f'{FOLDERS[key]} folder set by hand: {use}')
        if key == 'game':
            self.ctl.set_game_dir(use)
        elif key == 'saves':
            self.ctl.set_save_dir(use)
        self._scan(announce=True, picked=key == 'data')
        return {'ok': True}

    def folder_auto(self, key):
        """Auto: the folder is found again (shadPS4: the one QtLauncher selects, else the newest found)."""
        if key not in FOLDERS:
            return {'error': f'no folder {key}'}
        if key == 'cache':
            return self._cache_move(None)
        with self.ctl.lock:
            self.custom.pop(key, None)
            if key == 'data':
                gamesetup.set_custom_data('')
            if key == 'emulator':
                self.emulator = ''
            self._remember()
        self._scan(announce=True, picked=key in ('emulator', 'data'), auto=key if key in ('game', 'saves') else None)
        return {'ok': True}

    def _folders(self):
        """The Folders list: each row's path, whether the player set it, and whether it is all right."""
        rows = []
        for key, label in FOLDERS.items():
            path = self._folder_now(key)
            ok = {'emulator': bool(path), 'game': bool(((self.found or {}).get('game') or {}).get('ok')),
                  'data': gamesetup.is_data_dir(path), 'saves': os.path.isdir(path),
                  'cache': not self.custom.get('cache') or os.path.isdir(path)}[key]
            rows.append({'key': key, 'label': label, 'path': path, 'custom': bool(self.custom.get(key)), 'ok': ok})
        return rows

    def _check_cache(self, path):
        """(folder to use, None) or (None, why not) for the cache folder the player picked: a folder of its own on a
        drive that is there (a picked folder that holds other files gets one inside it: cachemove.pick, since a later
        move takes every file of the cache folder), never inside the game, its update or mods folder, shadPS4's data or
        the saves (the game would see the files, or Patch and Unpatch would meet them), and one this program may write
        to."""
        path = os.path.abspath(path)
        if os.path.dirname(path) == path:
            return None, f'Pick a folder on {path}, not the drive itself: the cache puts its files in that folder.'
        if not os.path.isdir(os.path.dirname(path)):
            return None, f'{os.path.dirname(path)} is not there. Pick a folder on a drive this PC has.'
        if not cachemove.same(path, paths.default_cache_dir()):
            try:
                path = cachemove.pick(path)
            except cachemove.CacheMoveError as err:
                return None, str(err)
        game = self.ctl.game_dir
        keep_out = []
        if game:
            base, update = gamefiles.roots(game)
            keep_out += [(base, 'NHL 19'), (update, "NHL 19's update"), (gamefiles.mods_dir(game), "NHL 19's mods")]
        keep_out += [(self._folder_now('data'), "shadPS4's data"), (self._folder_now('saves'), 'the saves')]
        for folder, what in keep_out:
            if folder and (cachemove.inside(path, folder) or cachemove.inside(folder, path)):
                return None, f'Pick a folder outside {what} ({folder}): the cache must not mix with it.'
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, '.overtime-write-test')
            with open(probe, 'wb') as f:
                f.write(b'ok')
            os.remove(probe)
        except OSError as err:
            return None, f'This program cannot write to {path} ({err}).'
        return path, None

    def _cache_move(self, dst):
        """Downloads and cache: Change... (`dst`) or Auto (None, the default folder). The files move in a job
        (cachemove: on another drive copied first, the setting changes once all are there, then the old ones go)."""
        if self._wait():
            return None
        c = self.ctl
        src, target = paths.cache_dir(), dst or paths.default_cache_dir()

        def switch():
            with c.lock:
                if dst:
                    self.custom['cache'] = dst
                else:
                    self.custom.pop('cache', None)
                self._remember()
            paths.set_cache_dir(dst)
            c.host.log(f'Downloads and cache: {target}')

        def progress(done, total):
            share = done / total if total else -1
            c.say(f'Moving the downloads and cache to {target}... {round(share * 100) if total else 0} %', 'info',
                  share)

        def work():
            return cachemove.move(src, target, switch, progress, log=c.host.log, default=paths.default_cache_dir())

        def said(out):
            if out.get('kept'):
                return (f"Downloads and cache: {target}. The files in {out['kept']} stay there: that folder may hold "
                        'files that are not the cache, so the program does not move them. Download the packs again, or '
                        'move them by hand.'), 'caution'
            if not out['files']:
                return f'Downloads and cache: {target}.', 'good'
            text = f"Downloads and cache moved to {target}: {out['files']} files, {out['bytes'] / 2**20:.0f} MB."
            if out['left']:
                text += f" {out['left']} old file(s) were in use and stay in {src}; they can be deleted."
            return text, 'good'
        return self._job('Moving the downloads and cache...', work, said, expected=(cachemove.CacheMoveError,))

    # --- Downloads: the picture packs --------------------------------------------------------------------------------
    def _pack_row(self, name):
        rows = self.packs if self.packs is not None else local_packs(patch_cache())
        return next((r for r in rows if r['name'] == name), None)

    def pack_download(self, name):
        """Download one pack into the cache (a job; the Help bar and its row show how far)."""
        if name not in PACKS:
            return {'error': 'Overtime Roster does not know this pack.'}
        return self._download([name])

    def packs_download_all(self):
        """Download every pack this PC lacks, or has an older version of (a job)."""
        with self.ctl.lock:
            rows = self.packs if self.packs is not None else local_packs(patch_cache())
            names = [r['name'] for r in rows if r['state'] in WANTED and r['name'] not in OPTIONAL]
        if not names:
            self.ctl.say('Every pack is downloaded already.', 'good')
            return None
        return self._download(names)

    def kits_download(self):
        return self.pack_download(KITS)

    def _download(self, names, busy=None, after_ok=None, not_got=None, then=None, switch=False):
        """A job downloading `names`. after_ok(): when all came, says the outcome. not_got(name): each that did not.
        then(): when the job is over."""
        c = self.ctl
        if not self.known_emulator():
            text = 'Find NHL 19 first: the packs go in when you patch the game.'
            c.say(text, 'caution')
            return {'error': text}
        if self._wait():
            return None
        titles = PACKS
        cache, game_dir = patch_cache(), c.game_dir
        with c.lock:
            self.dl = {'names': list(names), 'name': names[0], 'part': 0.0, 'share': 0.0, 'switch': switch}

        def progress(name, done, total):
            part = min(1.0, done / total) if total else 0.0
            share = (names.index(name) + part) / len(names) if name in names else part
            with c.lock:
                self.dl = {'names': list(names), 'name': name, 'part': part, 'share': share, 'switch': switch}
            c.say(f'Downloading {titles.get(name, (name,))[0]}... {round(part * 100)} %', 'info', share)
            c.changed('setup', 'patch')

        def work():
            results = packdownload.download(names, cache, progress=progress, game_dir=game_dir,
                                            cancelled=lambda: self.dl_stop)
            return results, pack_status(cache, game_dir)

        def said(out):
            results, rows = out
            with c.lock:
                self.packs = rows
            for name, ok, message in results:
                c.host.log(f"{name}: {'downloaded' if ok else 'not downloaded'} ({message})")
                if not_got is not None and not ok:
                    not_got(name)
            if after_ok is not None and all(ok for _n, ok, _m in results):
                return after_ok()
            return self._summary(results, titles)

        def after():
            with c.lock:
                self.dl = None
            if then is not None:
                then()
        self.dl_stop = False
        busy = busy or ('Downloading the picture packs...' if len(names) > 1 else
                        f'Downloading {titles.get(names[0], (names[0],))[0]}...')
        return self._job(busy, work, said, rescan=False, after=after)

    @staticmethod
    def _summary(results, titles):
        failed = [(titles.get(n, (n,))[0], msg) for n, ok, msg in results if not ok]
        if not failed:
            if all(msg == 'Already downloaded.' for _n, _ok, msg in results):
                return 'Every pack is downloaded already.', 'good'
            got = ', '.join(titles.get(n, (n,))[0] for n, _ok, _m in results)
            return f'Downloaded: {got}. Patch the game again to put them in.', 'good'
        title, why = failed[0]
        more = f' ({len(failed) - 1} more not downloaded.)' if len(failed) > 1 else ''
        return f'{title}: {why}{more}', 'bad' if len(failed) == len(results) else 'caution'

    def pack_remove(self, name):
        """Asks first; Delete then takes the pack out of the cache (a job)."""
        c = self.ctl
        row = self._pack_row(name)
        title = PACKS.get(name, (name,))[0]
        if row is None or not row.get('removable'):
            c.say(f'{title}: nothing downloaded to delete.', 'info')
            return None
        if self._wait():
            return None
        size = _megabytes(row.get('local_size'))
        size = f' ({size})' if size else ''
        if name == KITS:
            question = ('Delete the downloaded kits?', [f'The {title} are taken off this PC{size}.',
                                                       'Patch the game again to take them out of NHL 19 too. You can '
                                                       'download them again any time.'],
                        [('Delete the kits', 'delete', 'danger'), ('Keep them', 'keep', 'plain')])
        else:
            question = (f'Delete "{title}"?', [f'The pack is taken off this PC{size}.',
                                               'Patch the game again to take it out of NHL 19 too. You can download '
                                               'it again any time.'],
                        [('Delete it', 'delete', 'danger'), ('Keep it', 'keep', 'plain')])
        c.shell.ask(*question, {'delete': lambda: self._remove(name, title)})
        return None

    def kits_remove(self):
        return self.pack_remove(KITS)

    def _remove(self, name, title):
        cache, game_dir = patch_cache(), self.ctl.game_dir

        def work():
            had = packdownload.remove(name, cache)
            return had, pack_status(cache, game_dir)

        def said(out):
            had, rows = out
            with self.ctl.lock:
                self.packs = rows
            if not had:
                return f'{title}: nothing downloaded to delete.', 'info'
            if any(name in names for names in patch_ctl.ASSET_PACKS.values()):
                self._extra_off(name)
            if name == KITS:
                return 'The kits are deleted. Patch the game again to take them out.', 'good'
            return f'{title} is deleted. Patch the game again to take it out.', 'good'
        return self._job(f'Deleting {title}...', work, said, expected=(packdownload.PackError,), rescan=False)

    # --- Boost performance: the shadPS4 build Play starts, Nightly or Kravickas (boost.py, owner 2026-11-11) --------
    def setup_boost_source(self):
        webbrowser.open(boost.BUILDS[self.build]['source'])
        return {'ok': True}

    def setup_boost(self, on=True):
        """The pre-0.90.2 name (Boost on/off), kept for old pages: on = Kravickas (what Boost was), off = Nightly."""
        return self.setup_build(boost.KRAVICKAS if on else boost.NIGHTLY)

    def setup_build(self, name):
        """Nightly / Kravickas on the Boost performance card: remembered (it stays until another click), and when that
        build is here and shadPS4 is closed, the app plays with it from now on. Play downloads it when it is not."""
        if name not in boost.BUILDS:
            return {'error': f'no build {name}'}
        c = self.ctl
        with c.lock:
            self.build = name
            self._remember()
        exe, build, _why = self._play_exe()
        if exe and build and not overlay.emulator_running():
            self._use_build(build, exe)
            text = f'NHL 19 plays on the {self._build_label()} build of shadPS4.'
        else:
            text = f'{self._build_label()} chosen: Play NHL 19 gets it first.'
        c.say(text, 'good')
        c.changed('setup', 'app', 'patch')
        return {'ok': True}

    def setup_build_update(self):
        """Update on the Boost performance card: the published chosen build, now (a job)."""
        c = self.ctl
        if self._wait():
            return None
        no = boost.refused(None)
        if no:
            c.say(no, 'caution')
            return {'error': no}

        def said(out):
            build, got = out
            self._boost_applied(build, got)
            return f'The {self._build_label(build)} build of shadPS4 is up to date.', 'good'
        self._job(f'Getting the {self._build_label()} build of shadPS4...', self._install_build, said,
                  expected=(boost.BoostError,), after=self._boost_done)
        return {'ok': True}

    def _boost_progress(self, _name, done, total):
        c = self.ctl
        part = min(1.0, done / total) if total else 0.0
        with c.lock:
            self.boost_part = part
        c.say(f'Downloading the {self.boost_getting or self._build_label()} build... {round(part * 100)} %', 'info',
              part)
        c.changed('setup', 'app')

    def _boost_done(self):
        with self.ctl.lock:
            self.boost_part, self.boost_getting = None, ''

    def _boost_applied(self, build, got):
        """A build put in place (boost.install's (exe, sha)): remembered, and the shadPS4 the app plays with."""
        exe, sha = got
        with self.ctl.lock:
            self.boost['sha'][build] = sha
        self._use_build(build, exe)

    def online_boost(self, note=None):
        """Before an online Ready in a lobby without a match plan (multiplayer_ctl): NHL 19 on the published Kravickas
        build (the lobby build), switched on or brought up to date with no click (owner 2026-11-08: "we just handle all
        things for him"). Lockstep play needs the same shadPS4 on both PCs. The build chosen on the card stays chosen:
        the next Play starts it again. Waits for the download. Returns what it did: 'on', 'already', or why not
        ('none published', a refusal); the lobby compares what is there either way."""
        c = self.ctl
        k = boost.KRAVICKAS
        pub = (self.boost_table or {}).get(boost.PACK)
        current = self.known_emulator()
        on = boost.build_of(current) == k
        if on and (pub is None or pub.digest == self.boost['sha'].get(k)):
            return 'already'
        if pub is None:
            return 'none published'
        no = boost.refused(current, True)
        with c.lock:
            if not no and c.busy:
                no = waiting(c.busy)
            if not no:
                c.busy = 'Getting the NHL 19 build of shadPS4 for online play...'
                self.boost_getting = self._build_label(k)
        if no:
            c.host.log(f'Online: the Kravickas build not switched on ({no})')
            return no

        def progress(_name, done, total):
            part = min(1.0, done / total) if total else 0.0
            with c.lock:
                self.boost_part = part
            if note:
                note(f'Getting the NHL 19 build of shadPS4 for online play... {round(part * 100)} %')
            c.changed('setup', 'app')
        try:
            self._boost_applied(k, boost.install(k, patch_cache(), progress))
            return 'on'
        except (boost.BoostError, OSError, ValueError) as err:
            c.host.log(f'Online: the Kravickas build did not download ({err})')
            return str(err) or 'download failed'
        finally:
            with c.lock:
                c.busy, self.boost_part, self.boost_getting = None, None, ''
            c.changed('setup', 'app')

    def _boost_card(self, emulator):
        """The Boost performance card: the build choice (the chosen one lit), what Play starts, Update."""
        c = self.ctl
        table = self.boost_table or {}
        builds = []
        for b, info in boost.BUILDS.items():
            pub = table.get(info['pack'])
            here = bool(boost.here(b))
            builds.append({'id': b, 'label': info['label'], 'here': here, 'published': pub is not None,
                           'newer': here and pub is not None and pub.digest != self.boost['sha'].get(b),
                           'size': _megabytes(pub.size) if pub else ''})
        cur = next(x for x in builds if x['id'] == self.build)
        label = cur['label']
        part = self.boost_part
        own, _build, why = self._play_exe() if self.found is not None else ('', None, '')
        if part is not None:
            text, tone = f'Downloading the {self.boost_getting or label} build... {round(part * 100)} %', 'info'
        elif why:
            text, tone = why, 'caution'
        elif cur['newer']:
            text, tone = f'{label}: a newer build is out. Press Update, or Play NHL 19 gets it.', 'info'
        elif cur['here']:
            text, tone = f'{label}: ready. Play NHL 19 starts it.', 'good'
        elif cur['published']:
            size = f' ({cur["size"]})' if cur['size'] else ''
            text, tone = f'{label}: Play NHL 19 downloads it first{size}.', ''
        elif self.found is None:
            text, tone = 'Looking...', ''
        elif self.boost_table is None:
            text, tone = 'The Overtime server does not answer: check your internet connection.', 'caution'
        else:
            text, tone = f'{label}: not available for download yet.', 'caution'
        news, upstream = self._emulator_news() if self.build == boost.KRAVICKAS else ('', '')
        return {'build': self.build, 'builds': builds, 'playing': boost.build_of(emulator) or '',
                'text': text, 'tone': tone, 'progress': part, 'can': not c.busy,
                'can_update': cur['published'] and not c.busy and part is None,
                'resolution': self.resolution, 'news': '' if part is not None else news, 'upstream': upstream}

    @staticmethod
    def _emulator_news():
        """(line, tooltip) from the server's watch of Kravickas's builds (latest.json "emulator"): a newer build on
        GitHub the server has not moved to yet, and how the build stands to upstream shadPS4."""
        news = packdownload.emulator_news() or {}
        newer, up = news.get('newer'), news.get('upstream')
        line = ''
        if isinstance(newer, dict):
            when = f' ({newer["date"]})' if isinstance(newer.get('date'), str) else ''
            line = f'A newer Kravickas build is on GitHub{when}. Overtime moves to it after a test.'
        tip = ''
        if isinstance(up, dict) and isinstance(up.get('ahead'), int) and isinstance(up.get('behind'), int):
            tip = (f"Kravickas's build is upstream shadPS4 plus NHL 19 fixes: {up['ahead']} commits ahead of upstream, "
                   f"{up['behind']} behind.")
            if isinstance(up.get('release'), str):
                tip += f" Upstream's latest release: {up['release']}."
        return line, tip

    # --- Check my CPU (cpucheck.py; the page shows it in Multiplayer > Advanced) ----------------------------------------
    def _cpu_set(self, **changes):
        with self.ctl.lock:
            self.cpu = {**self.cpu, **changes}
        self.ctl.changed('setup')

    def cpu_check(self):
        """The Check my CPU button: the tool's pack downloaded (the first time), run, and its result judged. A job of
        its own, so the rest of the app stays free; refused while shadPS4 runs (the check keeps a core busy)."""
        c = self.ctl
        if overlay.emulator_running():
            no = 'Close NHL 19 first: the CPU check keeps one CPU core busy for about a minute.'
            self._cpu_set(error=no, note='')
            return {'error': no}
        with c.lock:
            if self.cpu['busy'] or self.cpu['sending']:
                return {'error': 'The CPU check runs already.'}
            self.cpu = {**self.cpu, 'busy': True, 'stage': 'download', 'part': 0.0, 'note': '', 'error': ''}
        c.changed('setup')

        def got(_name, done, total):
            self._cpu_set(stage='download', part=min(1.0, done / total) if total else 0.0)

        def work():
            exe = cpucheck.ensure(patch_cache(), got)
            self._cpu_set(stage='run', part=0.0)
            path, output = cpucheck.run(exe, progress=lambda part: self._cpu_set(part=part))
            return path, output, cpucheck.judge(path)

        def done(out):
            path, output, result = out
            self._cpu_set(**{**CPU_IDLE, 'result': result, 'zip': path, 'output': output})
            line, tone, _title = cpucheck.text(result)
            c.host.log(f"Check my CPU: {result['verdict']} ({result['cpu']}, {len(result['runs'])} core types)")
            c.say(f'CPU check: {line}', tone)

        def failed(message):
            self._cpu_set(busy=False, stage='', part=None, error=message)
            c.host.log(f'Check my CPU: {message}')
        jobs.run(work, done, failed, expected=(cpucheck.CheckError, packdownload.PackError, OSError, ValueError))
        return {'ok': True}

    def cpu_send(self):
        """Send the last check's result (the page asked first): a 'cpu' report with the result zip attached and the
        usual facts of this PC (crashreport.collect), to the server Setup uses."""
        c = self.ctl
        with c.lock:
            cpu = dict(self.cpu)
            if cpu['busy'] or cpu['sending']:
                return {'error': 'Wait for the CPU check to end.'}
            if cpu['result'] is None or not cpu['zip']:
                return {'error': 'Check the CPU first.'}
            self.cpu = {**self.cpu, 'sending': True, 'note': '', 'error': ''}
        c.changed('setup')
        emu, game_dir, base = self.known_emulator(), c.game_dir, f"https://{self.server['host']}"

        def work():
            with open(cpu['zip'], 'rb') as f:
                data = f.read()
            meta = {**crashreport.collect(emu, game_dir), **cpucheck.report_meta(cpu['result'])}
            body = crashreport.build('cpu', cpu['output'], meta, extra=crashreport.own_secrets(emu),
                                     attach=(os.path.basename(cpu['zip']), data))
            return crashreport.send(base, body)

        def done(rid):
            self._cpu_set(sending=False, note=f'Result sent (id {rid}). Thank you.')
            c.host.log(f'Check my CPU: result sent ({rid})')

        def failed(message):
            self._cpu_set(sending=False, error=message)
        jobs.run(work, done, failed, expected=(crashreport.ReportError, OSError, ValueError))
        return {'ok': True}

    def _cpu_card(self):
        """The CPU line (Multiplayer > Advanced): this PC's CPU, the check's state or verdict, what the buttons do."""
        s = self.cpu
        pub = (self.boost_table or {}).get(cpucheck.PACK)
        here = os.path.isfile(cpucheck.tool_exe())
        title = ''
        if s['busy']:
            pct = round((s['part'] or 0) * 100)
            text, tone = ((f'Downloading the CPU check... {pct} %', 'info') if s['stage'] == 'download' else
                          (f'Checking... {pct} % (about a minute; a CPU with two core types takes two)', 'info'))
        elif s['result'] is not None:
            text, tone, title = cpucheck.text(s['result'])
        elif pub is not None or here:
            text, tone = 'Not checked. The check takes about a minute; it sends nothing by itself.', ''
        elif self.found is None:
            text, tone = 'Looking...', ''
        elif self.boost_table is None:
            text, tone = 'The Overtime server does not answer: check your internet connection.', 'caution'
        else:
            text, tone = 'The CPU check is not available for download yet.', 'caution'
        free = not s['busy'] and not s['sending']
        full = gamesetup.cpu_name()
        name = ' '.join(re.sub(r'\((?:R|TM|tm)\)|\bCPU\b|@.*$|\b\d+-Core\b|\bProcessor\b', ' ', full).split())
        return {'name': name, 'full_name': full, 'text': text, 'tone': tone, 'title': title, 'busy': s['busy'],
                'sending': s['sending'], 'note': s['note'], 'error': s['error'],
                'can_check': free and (pub is not None or here), 'can_send': free and s['result'] is not None}

    def setup_resolution(self, value):
        """The Resolution choice (Boost performance card): 720 (Kravickas's res720 block), 1080 (the game's own) or
        1440 (Kravickas's res1440 block, with Additional DMem 3500 MB). A patched game takes it now, or at its next Play
        while shadPS4 runs; no Patch."""
        try:
            value = int(value or 0)
        except (TypeError, ValueError):
            value = 1080
        value = value if value in xmlpatch.RESOLUTIONS else 1080
        with self.ctl.lock:
            changed = value != self.resolution
            self.resolution = value
            self._remember()
        if not changed:
            return {'ok': True}
        self.ctl.host.log(f'Resolution: {value}p')
        try:
            put = patch_ctl.refresh_network(self)
        except (gamesetup.SetupError, OSError, ValueError) as err:
            self.ctl.host.log(f'The resolution was not put into the game: {err}')
            put = None
        if put in ('written', 'later', 'same'):
            then = 'NHL 19 uses it from its next start.'
        elif gamesetup.load_manifest() is None:
            then = 'Patch the game to use it.'
        else:
            then = 'Patch the game again to use it.'
        self.ctl.say(f'Resolution set to {value}p. {then}'.strip(), 'good')
        self.ctl.changed('setup')
        return {'ok': True}

    # --- Game settings, Controllers, Keyboard (Boost card; emusettings.py, emuinput.py) ----------------------------
    def _emu_user(self):
        emu = self.known_emulator()
        return gamesetup.emu_user_dir(emu) if emu else ''

    def emu_settings(self):
        """The Game settings view: shadPS4's per-game settings for NHL 19 with their values and locks."""
        user = self._emu_user()
        if not user:
            return {'error': 'Find NHL 19 in Setup first.'}
        return emusettings.view(user, self.resolution)

    def emu_settings_save(self, changes):
        """Save and Apply: the changed fields into the game's config file. Returns the view again, or {'error'}."""
        user = self._emu_user()
        if not user:
            return {'error': 'Find NHL 19 in Setup first.'}
        try:
            done = emusettings.save(user, changes, self.resolution)
        except emusettings.SettingsError as err:
            return {'error': str(err)}
        except OSError as err:
            return {'error': f'The settings were not saved: {err}'}
        if emusettings.DISPLAY_ID in done:
            with self.ctl.lock:
                self._remember()
        self.ctl.host.log(f"Game settings saved: {', '.join(done)}")
        self.ctl.say('Game settings saved. NHL 19 uses them from its next start.', 'good')
        return {'ok': True, **emusettings.view(user, self.resolution)}

    def emu_input(self, kind):
        """The Controllers ('pad') or Keyboard ('keys') view: the bindings of the input file shadPS4 uses."""
        user = self._emu_user()
        if not user:
            return {'error': 'Find NHL 19 in Setup first.'}
        try:
            return emuinput.view(user, kind)
        except emuinput.InputError as err:
            return {'error': str(err)}

    def emu_input_save(self, kind, model):
        """Save the Controllers or Keyboard view into the input file; the rest of the file stays as it is."""
        user = self._emu_user()
        if not user:
            return {'error': 'Find NHL 19 in Setup first.'}
        try:
            path = emuinput.save(user, kind, model)
        except emuinput.InputError as err:
            return {'error': str(err)}
        except OSError as err:
            return {'error': f'Not saved: {err}'}
        what = 'Controller' if kind == 'pad' else 'Keyboard'
        self.ctl.host.log(f'{what} bindings saved: {path}')
        then = ('Press F8 in NHL 19 to use them now.' if overlay.emulator_running()
                else 'NHL 19 uses them from its next start.')
        self.ctl.say(f'{what} bindings saved. {then}', 'good')
        return {'ok': True, **emuinput.view(user, kind)}

    # --- Updated assets: a switch per pack, as in Legacy (v0.70.0: the team art, photos and 3D jerseys too) -----------
    def _extra_off(self, name):
        """A pack did not come (or was deleted): every switch that needs it and has nothing else to use goes off."""
        c = self.ctl
        found = patch_ctl.packs_here(patch_cache())
        with c.lock:
            for key, names in patch_ctl.ASSET_PACKS.items():
                if name in names and patch_ctl.why(dict(c.patch_want, **{key: True}), key, found) is not None:
                    c.patch_want[key] = False
                    self.asked.discard(key)
            c.remember(patch=dict(c.patch_want))

    def _extras_running(self):
        return self.dl is not None and bool(self.dl.get('switch') or self.dl['names'][0] in OPTIONAL)

    def pack_switch(self, key, on):
        """One asset switch: on downloads its packs when they are not here, in turn with the others switched on; off
        stops its download and keeps what is on this PC. The next Patch puts the pack in or takes it out."""
        c = self.ctl
        names = patch_ctl.ASSET_PACKS.get(key)
        if names is None:
            return {'error': 'Overtime Roster does not know this pack.'}
        with c.lock:
            want = dict(c.patch_want, **{key: True})
            taken = bool(c.busy) and not self._extras_running()
        no = patch_ctl.why(want, key, patch_ctl.packs_here(patch_cache()), missing_ok=True) if on else None
        if on and not no and not self.known_emulator():
            no = 'Find NHL 19 first: the packs go in when you patch the game.'
        if taken or no:
            c.say(no or waiting(c.busy), 'caution')
            c.changed('patch')  # the switch goes back
            return None
        with c.lock:
            c.patch_want[key] = bool(on)
            c.remember(patch=dict(c.patch_want))
            (self.asked.add if on else self.asked.discard)(key)
            if not on and self.dl is not None and self.dl['name'] in names and not any(
                    c.patch_want.get(k) for k, v in patch_ctl.ASSET_PACKS.items() if self.dl['name'] in v):
                self.dl_stop = True
        c.changed('patch')
        if on and self._extras_wanted():
            return self._extras_next()
        if on:
            c.say('Switched on. Press Patch to put it in the game.', 'good')
        return None

    def _extras_wanted(self):
        """The packs of the asset switches that are on (and can be) and are not here, in the page's order."""
        with self.ctl.lock:
            rows = {r['name']: r for r in (self.packs if self.packs is not None else local_packs(patch_cache()))}
            want = dict(self.ctl.patch_want)
        found = patch_ctl.packs_here(patch_cache())
        out = []
        for key, names in patch_ctl.ASSET_PACKS.items():
            if not want.get(key) or patch_ctl.why(want, key, found, missing_ok=True):
                continue
            if key in patch_ctl.PACK_KEYS and key not in self.asked:
                continue        # switched on before (or by Download): no download the player did not ask for now
            out += [n for n in names if n not in out and rows.get(n, {}).get('state') in WANTED]
        return out

    def _extras_next(self, tried=()):
        """Download the next pack switched on and not here; a job that runs already picks it up when it ends. A pack
        that was tried and is still not here turns its switch off (the job failed): no second try by itself."""
        names = []
        for name in self._extras_wanted():
            if name in tried:
                self._extra_off(name)
            else:
                names.append(name)
        if not names or self.ctl.busy:
            self.ctl.changed('patch')
            return None
        name, title = names[0], PACKS[names[0]][0]

        def got():
            return f'{title} downloaded. Press Patch to put it in the game.', 'good'
        return self._download([name], busy=f'Downloading {title}...', after_ok=got, not_got=self._extra_off,
                              then=lambda: self._extras_next((*tried, name)), switch=True)

    @staticmethod
    def _asset_row(rows, names, found, key):
        """One switch's packs as one pack row: here when the switch can use what is here (the team art needs one of
        its looks packs), else what is left to do, with the size of what it downloads."""
        rs = [rows.get(n, {'name': n, 'state': 'missing'}) for n in names]
        rs = [r for r in rs if r['state'] != 'not_served'] or rs
        usable = patch_ctl.why({'art': True, 'roster': True, key: True}, key, found) is None
        newer = [r for r in rs if r['state'] == 'newer']
        todo = [r for r in rs if r['state'] in WANTED]
        if usable:
            state = 'newer' if newer else 'here'
        else:
            state = next((s for s in ('offline', 'missing') if any(r['state'] == s for r in rs)), rs[0]['state'])
        size = sum(r.get('size') or 0 for r in todo) if state != 'here' else sum(r.get('local_size') or 0 for r in rs)
        first = next((r for r in rs if r['state'] == state), rs[0])
        return {'name': names[0], 'state': state, 'size': size, 'local_size': sum(r.get('local_size') or 0 for r in rs),
                'removable': len(names) == 1 and bool(first.get('removable')), 'text': first.get('text', ''),
                'title': first.get('title')}

    def extra_card(self, emulator, want, picked, now, patched, keys=None):
        """The asset switches (Game patch, Updated assets): one row per switch with its download state. `keys`: the
        switches (default: the jersey and ice packs, v0.30's More jerseys and ice card)."""
        c = self.ctl
        rows = {r['name']: r for r in (self.packs if self.packs is not None else local_packs(patch_cache()))}
        found = patch_ctl.packs_here(patch_cache())
        dl, out = self.dl, []
        busy = bool(c.busy) and not self._extras_running()
        titles = {key: (title, sub) for key, title, sub, _info in patch_ctl.LAYERS}
        infos = {key: info for key, _title, _sub, info in patch_ctl.LAYERS}
        for key in (keys or patch_ctl.EXTRA_KEYS):
            names = patch_ctl.ASSET_PACKS[key]
            r = self._asset_row(rows, names, found, key)
            title, sub = patch_ctl.EXTRA_TITLES.get(key) or titles[key]
            size = _megabytes(r['size'] or r['local_size'])
            state, wanted = r['state'], bool(want.get(key))
            row = {'key': key, 'name': names[0], 'title': title, 'sub': sub, 'size': size, 'on': wanted,
                   'progress': None, 'tag': None, 'tone': '', 'quiet': False,
                   'info': {'title': title, 'text': infos.get(key) or patch_ctl.EXTRA_INFOS.get(key) or sub},
                   'can_remove': bool(r.get('removable')) and not c.busy, 'can_update': False}
            if dl is not None and c.busy and dl['name'] in names:
                row.update(tone='info', progress=dl['part'], text=f"Downloading... {round(dl['part'] * 100)} %"
                                                                  f"{f' of {size}' if size else ''}")
            elif wanted and state in WANTED and self._extras_running():
                row['text'] = 'Waiting for its turn...'
            elif state == 'here' or state == 'newer':
                row.update(text=f'Downloaded ({size}).' if size else 'Downloaded.', quiet=True)
                if state == 'newer':
                    row.update(text='A newer version is out.', quiet=False,
                               can_update=bool(emulator) and not c.busy)
                if patched:
                    on, there = bool(picked.get(key)), bool(now.get(key))
                    row['tag'] = {'text': 'In the game', 'tone': 'good'} if on and there else \
                        {'text': 'Patch to add', 'tone': 'caution'} if on else \
                        {'text': 'Patch to take away', 'tone': 'caution'} if there else None
                if not wanted and state == 'here':
                    row['text'] = f'Off. Kept on this PC{f" ({size})" if size else ""}.'
            elif state == 'offline':
                row['text'] = 'The Overtime server does not answer: check your internet connection.'
            elif state == 'missing' and wanted:
                row['text'] = 'Not downloaded yet. Switch it off and on to try again.'
            elif state == 'missing':
                row['text'] = f'Off: nothing is downloaded{f" ({size} when you switch it on)" if size else ""}.'
            else:
                row['text'] = r.get('text') or _pack_text(r)
            dep = patch_ctl.why(dict(want, **{key: True}), key, found, missing_ok=True)
            can = state in ('here', 'newer', *WANTED) and bool(emulator) and (wanted or not dep)
            row['disabled'] = busy or not can
            if not wanted and dep:
                row.update(text=dep, quiet=False)
            out.append(row)
        return {'title': 'More jerseys and ice', 'rows': out,
                'sub': 'Switch on what you want: it downloads by itself, and Patch puts it in the game.'}

    def assets_store(self):
        """The Updated assets group's corner: how much is on this PC, how much all of them are (the server's sizes,
        not the emulator pack), the wait hint, and Delete for all of it."""
        every = self.packs if self.packs is not None else local_packs(patch_cache())
        rows = [r for r in every if r.get('removable')]
        total = sum(r.get('size') or 0 for r in every if r['name'] != BOOST_PACK)
        return {'size': _megabytes(sum(r.get('local_size') or 0 for r in rows)), 'total': _gigabytes(total),
                'wait': ASSETS_WAIT, 'can_remove': bool(rows) and not self.ctl.busy}

    # --- The Photos, logos pack (v0.10.0): the four picture packs as one card on Game patch ---------------------------
    def _pack_rows(self):
        rows = self.packs if self.packs is not None else local_packs(patch_cache())
        return [r for r in rows if r['name'] not in OPTIONAL]

    def pack_card(self, emulator):
        """The Photos, logos pack card (Game patch): the four packs as one, with the share done while they download."""
        c = self.ctl
        rows = self._pack_rows()
        states = {r['name']: r['state'] for r in rows}
        wanted = [r['name'] for r in rows if r['state'] in WANTED]
        removable = [r['name'] for r in rows if r.get('removable')]
        here = all(state == 'here' for state in states.values())
        if here:
            size = _megabytes(sum(r.get('local_size') or 0 for r in rows))
        else:
            size = _megabytes(sum(r.get('size') or 0 for r in rows if r['name'] in wanted)) or PACK_SIZE
        card = {'title': PACK_TITLE, 'sub': PACK_SUB, 'size': size, 'progress': None, 'state': 'missing',
                'tone': 'caution', 'can_download': bool(emulator and wanted) and not c.busy,
                'can_remove': bool(removable) and not c.busy, 'download_text': 'Download'}
        dl = self.dl
        if dl is not None and c.busy and not self._extras_running():
            card.update(state='downloading', tone='info', progress=dl['share'], can_download=False, can_remove=False,
                        text=f"Downloading... {round(dl['share'] * 100)} %")
        elif here:
            card.update(state='here', tone='good', text=f'Downloaded ({size}). Press Patch to put it in the game.'
                        if size else 'Downloaded. Press Patch to put it in the game.')
        elif any(state == 'newer' for state in states.values()):
            card.update(state='newer', tone='info', download_text='Download the new version',
                        text='A newer version is out. Download it, then patch the game again.')
        elif any(state == 'offline' for state in states.values()):
            card.update(state='offline', text='Not downloaded. The Overtime server does not answer: check your '
                                              'internet connection.')
        elif not wanted:    # what is missing cannot be had now (not offered yet, photos for another roster)
            row = next(r for r in rows if r['state'] != 'here')
            card.update(state=row['state'], text=row.get('text') or _pack_text(row))
        elif any(state == 'here' for state in states.values()):
            got = sum(1 for state in states.values() if state == 'here')
            rest = _megabytes(sum(r.get('size') or 0 for r in rows if r['name'] in wanted))
            card.update(state='partial', size=rest, download_text='Download the rest',
                        text=f"{got} of {len(rows)} packs downloaded. Download the rest{f' ({rest})' if rest else ''}.")
        else:
            card.update(text=f'Not downloaded ({size}). {patch_ctl.NO_PACK}')
        if not emulator and card['state'] not in ('here', 'downloading'):
            card['text'] = 'Find NHL 19 in Setup first: the pack goes in when you patch the game.'
        return card

    def _packs_switch(self, on):
        """The pack switches on (each that can be: the photos need the default roster) or off, remembered."""
        c = self.ctl
        found = patch_ctl.packs_here(patch_cache())
        with c.lock:
            for key in patch_ctl.PACK_KEYS:     # art first: the photos and the kits need it
                c.patch_want[key] = bool(on) and not patch_ctl.why(dict(c.patch_want, **{key: True}), key, found)
            c.remember(patch=dict(c.patch_want))
        c.changed('patch')

    def packs_get(self):
        """Download the Photos, logos pack (every pack missing or older; a job), then switch art, photos and kits on."""
        def switched():
            self._packs_switch(True)
            return f'{PACK_TITLE} downloaded and switched on. Press Patch to put it in the game.', 'good'
        with self.ctl.lock:
            rows = self._pack_rows()
            names = [r['name'] for r in rows if r['state'] in WANTED]
        if not names:
            if all(r['state'] == 'here' for r in rows):
                text, tone = switched()
                self.ctl.say(text, tone)
            else:
                self.ctl.say('The pack cannot be downloaded now. Try again later.', 'caution')
            return None
        return self._download(names, busy=f'Downloading the {PACK_TITLE}...', after_ok=switched)

    def packs_drop(self):
        """Asks first; Delete then takes the four packs out of the cache (a job) and switches art, photos, kits off."""
        c = self.ctl
        rows = [r for r in self._pack_rows() if r.get('removable')]
        if not rows:
            self._packs_switch(False)
            c.say(f'{PACK_TITLE}: nothing downloaded to delete.', 'info')
            return None
        if self._wait():
            return None
        size = _megabytes(sum(r.get('local_size') or 0 for r in rows))
        size = f' ({size})' if size else ''
        c.shell.ask('Delete the downloaded assets?',
                    [f'The team art, jerseys, centre ice and player photos are taken off this PC{size}.',
                     'Patch the game again to take them out of NHL 19 too. You can download them again any time.'],
                    [('Delete it', 'delete', 'danger'), ('Keep it', 'keep', 'plain')],
                    {'delete': lambda: self._drop([r['name'] for r in rows])})
        return None

    def _drop(self, names):
        cache, game_dir = patch_cache(), self.ctl.game_dir

        def work():
            had = [name for name in names if packdownload.remove(name, cache)]
            return had, pack_status(cache, game_dir)

        def said(out):
            _had, rows = out
            with self.ctl.lock:
                self.packs = rows
            self._packs_switch(False)
            return 'The downloaded assets are deleted. Patch the game again to take them out.', 'good'
        return self._job('Deleting the downloaded assets...', work, said, expected=(packdownload.PackError,),
                         rescan=False)

    # --- This program --------------------------------------------------------------------------------------------
    def check_updates(self, on):
        """Look for a newer version at every start, or not (selfupdate.json, read by window.main's update ticks)."""
        selfupdate.set_check_updates(bool(on))
        self.ctl.say('The program looks for a newer version every time it starts.' if on else
                     'The program no longer looks by itself. Press Check now to look.', 'info')
        self.ctl.changed('setup')
        return {'ok': True}

    def check_now(self):
        """Look now (a job), then ask: the newest version, or "Version X is out" (Update now, Later, Skip this
        version). A version skipped before is offered here too: the player asked."""
        c = self.ctl
        with c.lock:
            if c.busy:
                busy = c.busy
            else:
                busy = None
                c.busy = 'Looking for a newer version...'
        if busy:
            c.say(waiting(busy), 'caution')
            return None
        c.say(c.busy, 'info', -1)
        c.changed('setup')

        def work():
            seen = []

            def fetch(url):
                try:
                    return selfupdate.http_text(url, timeout=15)
                except urllib.error.HTTPError:
                    seen.append('answered')     # the server answered: nothing published there
                    raise
                except Exception:
                    seen.append('offline')
                    raise
            release = selfupdate.latest(fetch_text=fetch)
            offline = release is None and seen[:1] == ['offline']
            if not offline:
                selfupdate.mark_checked()
            return release, offline

        def done(out):
            release, offline = out
            with c.lock:
                c.busy = None
                self.looked = not offline
                if release is not None:
                    self.newer = {'version': release.text, 'notes': self._notes(release)}
            c.say('Done looking.', 'info')
            c.changed('setup')
            if release is not None:
                self._ask_newer(release)
            elif offline:
                c.shell.ask('The program could not look', [
                    'The Overtime server does not answer.', 'Check your internet, then press Check now again.'],
                    [('OK', 'ok', 'plain')])
            else:
                c.shell.ask('You have the newest version', [
                    f'Version {VERSION} is the latest one.',
                    'If you are offline, the program cannot look: try again in a moment.'], [('OK', 'ok', 'plain')])

        def failed(message):
            with c.lock:
                c.busy = None
            c.say(message, 'bad')
            c.changed('setup')
        jobs.run(work, done, failed)
        return None

    @staticmethod
    def _notes(release):
        lines = [x.strip(' -*\t') for x in (release.notes or '').splitlines()]
        return [x[:200] for x in lines if x][:4]

    def _ask_newer(self, release):
        c = self.ctl
        can = bool(selfupdate.running_exe()) and release.can_install()
        lines = [f'You have version {VERSION}.', *self._notes(release),
                 'The program downloads the new version, restarts and keeps all your settings and rosters.' if can
                 else 'This copy cannot replace itself: get the new version from the Overtime page.']
        first = ('Update now', 'update', 'primary') if can else ('Open the page', 'page', 'primary')
        c.shell.ask(f'Version {release.text} is out', lines,
                    [first, ('Later', 'later', 'plain'), ('Skip this version', 'skip', 'plain')],
                    {'update': lambda: self._update(release), 'skip': lambda: self._skip(release.text),
                     'page': lambda: webbrowser.open(release.page or SITE)})

    def _skip(self, version):
        with self.ctl.lock:
            self.skipped = version
            self._remember()
        self.ctl.say(f'Skipped version {version}. The program tells you again when the next one is out.', 'info')
        self.ctl.changed('setup')

    def _update(self, release):
        c = self.ctl
        if overlay.emulator_running():
            c.shell.ask('Close shadPS4 first', ['The program cannot update while shadPS4 runs.',
                                               'Close shadPS4, then press Check now again.'], [('OK', 'ok', 'plain')])
            return None
        return c.shell.ask_unsaved('update the program', go=lambda: self._install(release))

    def _install(self, release):
        c = self.ctl
        version = release.text

        def work():
            def progress(share):
                c.say(f'Downloading version {version}... {round(share * 100)} %', 'info', share)
            return selfupdate.install(release, progress=progress)

        def quit_now():
            closing = getattr(c, 'quit', None)      # window.main's Quit (Needs from the integrator)
            if callable(closing):
                closing()
            elif selfupdate.running_exe():
                os._exit(0)                         # the new exe is starting: this one goes

        def said(_exe):
            threading.Timer(1.5, quit_now).start()  # the Help bar shows the line first
            return f'Version {version} is ready. The program restarts with it.', 'good'
        return self._job(f'Updating the program to {version}...', work, said, expected=(selfupdate.Refused,),
                         rescan=False)

    # --- the slice -----------------------------------------------------------------------------------------
    def snap_setup(self):
        with self.ctl.lock:
            f = self.found or {}
            st = f.get('status') or {}
            game = f.get('game') or {}
            ov = f.get('overlay') or {}
            clean = f.get('clean')
            return {
                'scanned': self.found is not None, 'busy': bool(self.ctl.busy), 'running': bool(f.get('running')),
                'emulator': self.emulator or f.get('emulator') or '', 'emulators': f.get('emulators') or [],
                'emulator_url': gamesetup.EMULATOR_URL, 'user_dir': f.get('user_dir') or '',
                'game_dir': self.ctl.game_dir, 'game_ok': bool(game.get('ok')), 'game_problem': game.get('problem'),
                'games': [g['path'] for g in f.get('games') or []],
                'installed': bool(st.get('installed')), 'intact': bool(st.get('intact')),
                'problems': list(st.get('problems') or []) + list(ov.get('problems') or []),
                'targets': st.get('targets'), 'layers': sorted((ov.get('layers') or {}).keys()),
                'data_patched': bool(ov.get('applied')),
                'network': f.get('network') or {}, 'network_ok': all(
                    (f.get('network') or {}).get(k) == v for k, v in gamesetup.NETWORK.items()),
                'users': f.get('users') or [], 'firewall': f.get('firewall'),
                'server': dict(self.server), 'server_default': self.server == SERVER,
                'clean': {'made': clean.get('made'), 'full': clean.get('full')} if clean else None,
                'verify': self.verify_result, 'play': self.play,
            }

    # --- the new slice (docs/ui/setup.md) ----------------------------------------------------------------------------
    def _checks(self, f, first):
        """The four tiles: shadPS4, NHL 19, ShadNet, Network (from the last look, `found`)."""
        def tile(key, value, tone, text):
            return {'key': key, 'label': LABELS[key], 'value': value, 'tone': tone, 'text': text}
        if first:
            return [tile(k, 'Not checked', '', 'Find NHL 19 first.') for k in LABELS]
        if self.checking or self.found is None:
            return [tile(k, 'Checking...', '', 'Checking...') for k in LABELS]
        return [self._emulator_tile(f, tile), self._game_tile(f, tile), self._shadnet_tile(f, tile),
                self._network_tile(f, tile)]

    @staticmethod
    def _emulator_tile(f, tile):
        build = f.get('build')
        if f.get('running'):
            return tile('emulator', 'Running', 'caution',
                        'shadPS4 is running. Close it before you save or delete a roster.')
        if build is None:
            return tile('emulator', 'Found', 'good', 'Found shadPS4. It does not say which version it is.')
        return tile('emulator', build['version'], 'good',
                    f"Found shadPS4 {build['version']} ({build['branch']}, {build['rev'][:7]}).")

    @staticmethod
    def _game_tile(f, tile):
        game = f.get('game') or {}
        version = (game.get('app_ver') or '').lstrip('0') or '?'
        needed = gamesetup.APP_VER.lstrip('0')
        if game.get('ok'):
            return tile('game', f"{version} · {game['title_id']}", 'good',
                        f"NHL 19 ({game['title_id']}) with update {version}.")
        if game.get('title_id') in gamesetup.TITLE_IDS and game.get('app_ver') != gamesetup.APP_VER:
            return tile('game', f'Version {version}', 'bad',
                        f'NHL 19 is version {version}. Install update {needed}: pick its PKG with Find game.')
        if game.get('title_id') in gamesetup.TITLE_IDS:
            return tile('game', 'Not complete', 'bad',
                        'NHL 19 is not complete. Install it again from its PKG with Find game.')
        return tile('game', 'Not found', 'bad', 'NHL 19 was not found. Press Find game and pick its eboot.bin '
                                                 'or its PKG.')

    @staticmethod
    def _shadnet_tile(f, tile):
        """As deep as shadPS4's files go: users.json (ShadNet on, an Online ID, a password filled in) and its log
        of the last run (signed in, or refused). The tooltip says what was checked."""
        on = [u for u in f.get('users') or [] if u.get('shadnet')]
        if not on:
            return tile('shadnet', 'Not signed in', 'caution',
                        'Sign in to ShadNet on the Multiplayer tab to play online.')
        user = on[0]
        who = user.get('npid') or user.get('name') or 'you'
        if not user.get('npid') or not user.get('password', True):
            return tile('shadnet', 'Not signed in', 'caution',
                        'ShadNet is on, but the Online ID or password is missing. Sign in again on the '
                        'Multiplayer tab.')
        log = f.get('log') or {}
        fresh = log.get('when') is not None and (f.get('users_time') is None or log['when'] >= f['users_time'])
        when = friendly_date(log['when']) if log.get('when') else ''
        if fresh and log.get('state') == 'rejected':
            return tile('shadnet', 'Sign-in refused', 'bad',
                        f'ShadNet refused the sign-in when shadPS4 last ran ({when}). Sign in again on the Multiplayer '
                        'tab: the Online ID (capitals count) and the password.')
        if fresh and log.get('state') == 'signed_in':
            return tile('shadnet', who, 'good', f'Signed in to ShadNet as {who}. Checked: the shadPS4 settings, '
                                                f'and its last run signed in ({when}).')
        return tile('shadnet', who, 'good', f'Signed in to ShadNet as {who}. Checked: the shadPS4 settings (ShadNet '
                                            'on, Online ID and password set); the sign-in itself shows when the game '
                                            'starts.')

    def _network_tile(self, f, tile):
        ok, why = f.get('server') or (None, '')
        host = f.get('host') or self.server['host']
        if ok:
            return tile('network', 'Server answers', 'good', f'The Overtime server ({host}) answers.')
        if host != SERVER['host']:
            return tile('network', 'No answer', 'bad', f'The server you set ({host}) does not answer. Check the '
                                                       'address under Online, then check again.')
        return tile('network', 'No answer', 'bad', 'The Overtime server does not answer. Check your internet, then '
                                                   'check again.')

    def _state(self, first, checks, roster_open):
        """The line under the tiles: what is wrong, or what to do next."""
        if first:
            return {'tone': 'info', 'get': False,
                    'text': 'Press Find game and pick NHL 19: its eboot.bin, or its PKG files to install it. No shadPS4? '
                            'Overtime gets it by itself. Have one? Pick shadPS4.exe or QtLauncher instead.'}
        if self.checking or self.found is None:
            return {'tone': 'info', 'text': 'Checking shadPS4, NHL 19, ShadNet and the Overtime server...',
                    'get': False}
        for tone in ('bad', 'caution'):
            bad = next((c for c in checks if c['tone'] == tone), None)
            if bad:
                return {'tone': tone, 'text': bad['text'], 'get': False}
        # the firewall no longer gates "ready" (0.83.0): matches go through the Overtime relay, which the game reaches
        # first, so Windows lets the replies in without a rule. The rule stays optional, for a direct link.
        if not roster_open:
            return {'tone': 'good', 'text': 'Ready. Now pick the roster you work on.', 'get': False}
        return {'tone': 'good', 'text': 'Everything is ready. Go to Update or patch the game.', 'get': False}

    @staticmethod
    def _firewall(emulator, allows):
        if not emulator:
            return {'tone': '', 'text': 'Find NHL 19 first.', 'can_fix': False}
        # Optional since 0.83.0: matches run through the Overtime relay. A rule only matters for a direct link (the
        # relay full or down) and stops Windows asking over the game the first time.
        hint = ('Matches go through the Overtime server. The rule only helps a direct link, used when the server cannot '
                'carry a match.')
        if allows is True:
            return {'tone': 'good', 'text': f'Allowed ({GAME_PORT})', 'hint': hint, 'can_fix': False}
        return {'tone': '', 'text': 'Optional', 'hint': hint, 'can_fix': True}

    def _downloads(self, emulator):
        """Downloads: one row per pack, and Download all."""
        c = self.ctl
        rows = self.packs if self.packs is not None else local_packs(patch_cache())
        dl = self.dl
        part = c.parts.get('patch') if hasattr(c, 'parts') else None
        beta1 = part.kits_progress if part is not None and c.busy == getattr(part, 'KITS_BUSY', None) else None
        out = []
        for r in rows:
            name, size = r['name'], _megabytes(r.get('size') or r.get('local_size'))
            row = {'name': name, 'title': r.get('title') or PACKS.get(name, (name,))[0], 'core': bool(r.get('core')),
                   'size': size, 'state': r['state'], 'progress': None, 'can_remove': bool(r.get('removable')),
                   'can_download': r['state'] in WANTED and bool(emulator),
                   'tone': {'here': 'good', 'newer': 'info'}.get(r['state'], 'caution'),
                   'text': r.get('text') or _pack_text(r)}
            turn = dl['names'].index(name) - dl['names'].index(dl['name']) \
                if dl is not None and c.busy and name in dl['names'] and dl['name'] in dl['names'] else None
            if turn == 0 or (turn is None and name == KITS and beta1 is not None):
                share = dl['part'] if turn == 0 else beta1
                row.update(state='downloading', tone='info', progress=share, can_download=False, can_remove=False,
                           text=f"Downloading... {round(share * 100)} %{f' of {size}' if size else ''}")
            elif turn is not None and turn > 0:
                row.update(state='downloading', tone='info', progress=0.0, can_download=False, can_remove=False,
                           text='Waiting for its turn...')
            elif turn is not None:      # downloaded in this run: its row shows it once the run ends
                row.update(can_download=False, can_remove=False, tone='good', text='Downloaded.')
            out.append(row)
        wanted = [r['name'] for r in rows if r['state'] in WANTED and r['name'] not in OPTIONAL]
        return {
            'rows': out,
            'all': {'can': bool(emulator and wanted) and not c.busy, 'count': len(wanted),
                    'title': ('Find NHL 19 first: the packs go in when you patch the game.' if not emulator else
                              f"Download the {len(wanted)} pack{'s' if len(wanted) != 1 else ''} not on this PC"
                              if wanted else 'Every pack is downloaded.')},
            'note': None if emulator else 'Find NHL 19 first: the packs go in when you patch the game.',
        }

    def _kits(self, downloads):
        """beta1's kits row (the slice's `kits`), from the Downloads row of kits.zip."""
        row = next((r for r in downloads['rows'] if r['name'] == KITS), None)
        if row is None:
            return {'name': PACKS[KITS][0], 'size': '', 'state': 'none', 'progress': None, 'tone': 'caution',
                    'text': "Not downloaded. Until then the teams wear the game's own kits."}
        state = {'here': 'ready', 'downloading': 'downloading'}.get(row['state'], 'none')
        return {'name': row['title'], 'size': row['size'], 'state': state, 'progress': row['progress'],
                'tone': row['tone'], 'text': row['text']}

    def _program(self):
        state = selfupdate._state()
        on = state.get('check_updates', True) is not False
        newer = self.newer if self.newer and self.newer.get('version') != self.skipped else None
        if newer:
            line = {'tone': 'caution', 'text': f"Version {newer['version']} is out."}
        elif self.looked or (on and state.get('checked')):
            line = {'tone': 'good', 'text': 'This is the newest version.'}
        else:
            line = {'tone': '', 'text': 'Press Check now to look for a newer version.'}
        return {'version': VERSION, 'check_on_start': on, 'newer': dict(newer) if newer else None, 'state': line,
                'skipped': self.skipped or None}

    def view(self):
        c = self.ctl
        with c.lock:
            f = self.found or {}
            emulator = self.known_emulator()
            first = not emulator
            running = bool(f.get('running'))
            checks = self._checks(f, first)
            rosters = c.parts['rosters']
            build = f.get('build') if f.get('emulator') == emulator else None
            downloads = self._downloads(emulator)
            beta1 = self.snap_setup()       # the lock is re-entrant (re/scripts/oneclick_run.py reads these keys)
            return dict(beta1, **{
                'first': first,
                'emulator': {'path': emulator, 'build': (f"{build['branch']} · {build['version']}" if build else
                                                         'shadPS4' if emulator else '')},
                'checks': checks,
                'folders': self._folders(),
                'state': self._state(first, checks, rosters.open_roster() is not None),
                'checking': bool(self.checking),
                'running': running,
                'online': {'server': self.server['host'], 'server_default': SERVER['host'],
                           'is_default': self.server == SERVER, 'error': self.server_error, 'port': GAME_PORT,
                           'firewall': self._firewall(emulator, f.get('firewall')), 'cpu': self._cpu_card()},
                'downloads': downloads,
                'boost': self._boost_card(emulator),
                'kits': self._kits(downloads),
                'program': self._program(),
                'rosters': rosters.view(not first, running, f.get('teams32')),
                'busy': bool(c.busy),
            })
