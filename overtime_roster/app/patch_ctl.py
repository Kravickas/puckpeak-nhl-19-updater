"""Game patch: what the Overtime patch puts into NHL 19 (its switches), what is in the game now, and what the patch
does. docs/ui/patch.md.

The switches are beta1's patch_want (kept in the settings). Patch is the one click (one_click): the data overlay
with exactly the switches that are on, the eboot patch with the Overtime server address and the network settings
(gamesetup), then a look at what is in the game now. Unpatch (one_unpatch) takes both away. The page calls Setup's names for them (setup_patch / setup_unpatch, which re/scripts/oneclick_run.py
drives on a SetupController of its own), so the one click is a function of the SetupController here: Setup's calls run
it, and this tab's patch_apply / patch_undo (beta1's names) are the same two. The game folder is only ever read: the
patch is served from the overlay folder beside it (overtime_core.overlay).
"""
import os
import threading
import time

from overtime_core import (eb, gamefiles, kitcompose, nhlcom, overlay, rosterupdate, tdb, teams as T, textpack,
                           xmlpatch)

from .. import VERSION
from . import (crosscpu, gamesetup, jobs, launch, matchsetup, onlinetag, packdownload, patch, patchmeter, paths,
               savegame, selfupdate, update)
from .packdownload import PackError
from .registry import Part
from .shell import friendly_date

SEASON_LABEL = '2026-27'
# a lobby match plays on a setup of its own (matchsetup): the player's patch, config and -mods wait until it is back
MATCH_LOCKED = ('A lobby match setup is in place. Your own setup comes back when NHL 19 closes; press again after '
                'that.')
KEYS = ('names', 'roster', 'league', 'text', 'menus', 'chel', 'art', 'photos', 'kits')
# key, title, sub (one short line), the "?" text; the page's order
LAYERS = (
    ('names', 'Utah and Coachella Valley names',
     'Arizona becomes the Utah Mammoth (UTA). Burnaby becomes Coachella Valley.',
     "In the game's menus, Arizona's city, name, nickname and short name become the Utah Mammoth's. Burnaby, the "
     "city of Seattle's AHL club, becomes Coachella Valley."),
    ('roster', f'{SEASON_LABEL} default roster',
     "Today's NHL in every new mode: all 32 teams, rosters, lines, ratings and the calendar.",
     "Modes that start from the default roster (Play Now, Season, Franchise, Be a Pro) get today's league: rosters, "
     'ratings, lines and the calendar, with Utah. NHL 19 came out in 2018 with 31 teams, before the Seattle Kraken '
     'joined the NHL, so this switch is also what adds Seattle as the 32nd team. Off, those modes keep NHL 19\'s 31 '
     'teams.'),
    ('league', f'{SEASON_LABEL} salary cap',
     'Cap $104.0M, floor $76.9M, lowest salary $850,000.',
     'New Franchise and Season leagues use the 2026-27 money rules. The game as it came has the 2018-19 rules: '
     'cap $79.5M, floor $58.8M, lowest salary $650,000.'),
    ('text', 'Overtime server texts',
     'Connection messages name the Overtime server, not EA. The news tile shows gg.puckpeak.com.',
     'When NHL 19 connects, signs in or loses the connection, its messages name the Overtime community server '
     "instead of EA's servers, which are closed. The main menu's news tile says \"Puck Peak: Updates, patches, "
     'statistics! Join us on gg.puckpeak.com".'),
    ('menus', 'Hub without the closed modes',
     'Takes Hockey Ultimate Team, Draft Champions and World of Chel off the menu.',
     'These modes need EA servers that no longer run, so their tiles leave the main menu. Every other mode stays '
     'where it was.'),
    ('chel', 'Keep the World of Chel tile',
     'Leaves its tile in the hub, for a server that runs it. Overtime does not yet.',
     "World of Chel (EASHL) is NHL 19's online club mode: your own pro in 6-on-6 club and drop-in games. It needed "
     "EA's servers, which are closed, and the Overtime server does not run it yet. With \"Hub without the closed "
     'modes" on, this keeps its tile anyway.'),
    ('art', 'Team art',
     "Every team's logos, menu jerseys and centre ice. Utah's arena.",
     "Updated logos, menu jerseys and centre ice for every team, Utah's and Seattle's 3D jerseys, and Utah's Delta "
     "Center in place of Arizona's arena. Downloads when you switch it on. The game's own files stay as they are."),
    ('photos', 'Player photos',
     "Today's portraits on the player cards.",
     f'NHL.com portraits for the players of the {SEASON_LABEL} default roster. They show with that roster only, so '
     'the switch needs it. Downloads when you switch it on. Off, the game keeps its own pictures.'),
    ('kits', '3D jerseys',
     "The other 30 NHL teams' updated jerseys, numbers and socks on the ice.",
     "Every other NHL team's updated jerseys on the ice. Downloads when you switch it on."),
)
PACK_KEYS = ('art', 'photos', 'kits')   # the asset switches of the core packs (off until a pack is here)
NO_PACK = ("Not downloaded yet. Until the team art is here, Utah plays in the Coyotes' look and Seattle shows a "
           "stand-in crest and kit.")
# the packs each pack switch reads (patch.ART_PACKS names); the art switch needs one of its two
PACK_FILES = {'art': (patch.LOOKS32_PACK, 'looks.zip'), 'photos': (patch.PHOTOS_PACK, patch.PEOPLE_PACK), 'kits': (patch.KITS_PACK,)}
# the packs with a switch of their own: {switch key: pack}
EXTRA_KEYS = {patch.extra_key(name): name for name in patch.EXTRA_PACKS}
EXTRA_TITLES = {'ice_all': ('Centre ice of every league', 'The centre ice of every club of every league.'),
                'rink': ('IIHF centre ice and rink art', 'The IIHF emblem and puck in national team games; updated '
                         "pucks, board ads and league logos. National team games keep NHL 19's boards."),
                'alts_nhl': ('NHL alternate jerseys', "The NHL teams' updated alternate jerseys, made on this PC at Patch."),
                'alts_intl': ('National team jerseys', 'Updated main and alternate jerseys of the national teams, made on '
                              'this PC at Patch.'),
                'alts_hometown': ('Hometown Remix jerseys (BETA)', "Each team's Hometown Remix jersey, in place of one of its "
                                  'other jerseys. Switched off, they all come back.'),
                'alts_clubs': ('Club jerseys of every league', 'Updated jerseys of the AHL, ECHL, junior and European '
                               'clubs, made on this PC at Patch (a few minutes the first time, about 3 GB on the disk).')}
# the "?" text of the Hometown Remix switch: which jersey it takes the place of (tools/build_hometown.py picks the rows)
EXTRA_INFOS = {'alts_hometown': (
    "Beta, not finished: the photos are approximate. Adds each team's Hometown Remix jersey as an alternate, made on this PC at Patch. It takes the place of one jersey "
    'per team. Vegas: the away jersey. Utah: the third jersey. Seattle: the alternate. Winnipeg, Calgary, Columbus, '
    'Dallas, Edmonton, Montreal, New Jersey and Ottawa: one of the alternates. The other 21 teams: one of their old '
    'throwback jerseys. Switch it off and Patch again, and every one of them is back as it was.')}
# every asset switch and the packs it downloads when switched on (v0.70.0: one switch, one download, no bundle)
ASSET_PACKS = {'art': (*PACK_FILES['art'], patch.CLUBART_PACK), 'photos': PACK_FILES['photos'],
               'kits': PACK_FILES['kits'], **{key: (name,) for key, name in EXTRA_KEYS.items()}}
ART_NEEDED = 'Needs "Team art".'
# the Game patch page's groups (v0.70.0): key, title, one line, its switches in the page's order, and the switches
# its own switch turns on (the rest are choices: World of Chel's tile, the big jersey and ice downloads)
GROUPS = (
    ('league', 'Teams and league', "Utah, today's rosters and the salary cap.", ('names', 'roster', 'league'),
     ('names', 'roster', 'league')),
    ('menus', 'Menus and server texts', 'The hub without the closed modes; Overtime in the messages.',
     ('text', 'menus', 'chel'), ('text', 'menus')),
    ('assets', 'Updated assets', 'Logos, jerseys, centre ice and player photos. Each downloads when you switch it on.',
     ('art', 'kits', 'photos', 'alts_nhl', 'alts_intl', 'alts_clubs', 'alts_hometown', 'ice_all', 'rink'), ('art', 'kits', 'photos')),
)
COMING = {'title': '32 teams in every mode',
          'sub': 'Classic Franchise and NHL Season with both Seattle and Utah. Today a 32 Team Expansion Draft Franchise '
                 'has both. Still being built.'}
NAMES = (('City', 'Arizona', 'Utah'), ('Team', 'Arizona Coyotes', 'Utah Mammoth'), ('Nickname', 'Coyotes', 'Mammoth'),
         ('Short name', 'ARI', 'UTA'), ('AHL city', 'Burnaby', 'Coachella Valley'))
ABOUT = (
    ('In the game', ["Utah plays in Arizona's place and Seattle is the 32nd team.",
                     'The 2026-27 rosters, salary cap and updated team art.',
                     "NHL 19 goes online on the Overtime server instead of EA's."]),
    ('On your PC', ['The game folder is only read. shadPS4 serves the patch from a folder beside it (named like the game folder, plus -mods).',
                    'Unpatch takes every patch file away. Deleting that folder by hand does the same.']),
    ('Your rosters', ['Your roster saves stay as they are.',
                      'The default roster switch only changes the roster new modes start from.']),
    ('When to patch again', ['After you change a switch, or after Overtime Roster updates.',
                             "When \"What's in your game now\" lists a problem."]),
)

PATCHING = 'Patching NHL 19...'
UNPATCHING = 'Unpatching NHL 19...'
CHECKING = 'Checking the game...'
DATA_LAYERS = ('text', 'names', 'league', 'menus')   # the overlay layers a switch of the same name turns on
EXPECTED = (gamesetup.SetupError, launch.LaunchError, overlay.PatchError, patch.PatchFailed, xmlpatch.PatchError,
            update.UpdateError, nhlcom.NhlComError, PackError, OSError, ValueError)


class Refused(Exception):
    """A step that cannot run now (shadPS4 runs, no NHL 19): said as a caution, not as an error of the patch."""


NO_BASE = ('This folder has the NHL 19 update but not the game itself. In Setup, pick the folder of the base game (the '
           'one with databigs\\inxp_00.big). An update kept beside it, in a folder of the same name with -UPDATE at the '
           'end, is found by itself.')
TEXT_LAYERS = {'text': 'the Overtime texts', 'names': 'the new team names'}


def game_text(game_dir, log=None):
    """The game's text file the text layers edit (textpack.game_language: eng_us, else another English, else None),
    after checking the folder holds the game itself and not only its update (a tester's CUSA11116, 2026-11-03: the raw
    "eng_us-meta.xml not in" stopped the patch). `log` gets the text files found: which one a European game shows is
    not known here (its update may carry eng_us.db beside its own English)."""
    try:
        gamefiles.schema_xml(game_dir)
    except FileNotFoundError:
        raise Refused(NO_BASE) from None
    files = textpack.loc_files(game_dir)
    lang = textpack.game_language(game_dir, files)
    if log:
        dbs, metas = files
        meta = lang if lang in metas else (metas[0] if metas and lang else 'none')
        log(f"Text files: {', '.join(dbs) or 'none'}; metas: {', '.join(metas) or 'none'}. "
            f"The patch edits {lang or 'none'} (read with the {meta} meta).")
    return lang


def left_out_text(lang, left):
    """The line for text layers Patch left out (game_text): the rest of the patch went in."""
    what = ' and '.join(TEXT_LAYERS[k] for k in left)
    why = ('this NHL 19 has no English text file' if lang is None else
           f'its English text file ({lang}) is not the one the patch knows')
    return f"{what[0].upper()}{what[1:]} stay the game's own: {why}."


def served(st):
    """{switch key: bool} of what overlay.status() says the game is served now."""
    ly = (st or {}).get('layers') or {}
    packs = [str(p.get('name', '') if isinstance(p, dict) else p).lower() for p in (ly.get('art') or {}).get('packs') or []]
    return {'names': 'names' in ly, 'roster': 'database' in ly, 'league': 'league' in ly, 'text': 'text' in ly,
            'menus': 'menus' in ly, 'chel': bool(((ly.get('menus') or {}).get('options') or {}).get('chel')),
            'art': 'art' in ly, 'photos': any('photos' in p for p in packs), 'kits': any('kits' in p for p in packs),
            **{key: key.replace('_', '-') in packs for key in EXTRA_KEYS}}


def why(want, key, found, missing_ok=False):
    """Why a switch cannot be on now, or None. `found`: the art packs here (packs_here). `missing_ok`: a pack not
    downloaded yet is no reason (switching it on downloads it)."""
    if key in EXTRA_KEYS:
        if not want.get('art'):
            return ART_NEEDED
        return None if missing_ok or EXTRA_KEYS[key] in found else 'Not downloaded yet.'
    if key == 'chel' and not want.get('menus'):
        return 'Needs "Hub without the closed modes".'
    if key in PACK_KEYS and not missing_ok and not any(name in found for name in PACK_FILES[key]):
        return NO_PACK
    if key in ('kits', 'photos') and not want.get('art'):
        return ART_NEEDED
    if key == 'photos' and not want.get('roster'):
        return f'Needs the {SEASON_LABEL} default roster.'
    return None


def switches(want, found):
    """{key: bool}: the switches that are on and can be (why). A switch that is off is off (v0.10.0: the pack
    switches too, until the Photos, logos pack is here)."""
    return {k: bool(want.get(k)) and not why(want, k, found) for k in (*KEYS, *EXTRA_KEYS)}


def cache_dir():
    """The app's cache folder: the picture packs downloaded go there (patch.art_places looks there first)."""
    return paths.app_dir('cache')


def packs_here(cache):
    """The art packs here (patch.art_found: the cache, the exe's, a source run's packs/). The patch only uses what is
    here: it never downloads (the Photos, logos pack card does)."""
    return patch.art_found(cache)


def kits_here(cache):
    """The kits pack is here (beta1's name)."""
    return patch.KITS_PACK in packs_here(cache)


def _lower(text):
    """A message after a colon: its first letter small, unless the word is a name in capitals (NHL, EA)."""
    text = str(text or '').strip()
    return text[0].lower() + text[1:] if len(text) > 1 and text[0].isupper() and not text[1].isupper() else text


def _doing(busy):
    return _lower(str(busy).rstrip('. '))


def _part(ctl):
    return (getattr(ctl, 'parts', None) or {}).get('patch')


# --- the jobs: Patch, Unpatch, Check again, the clean-game check and copy ---------------------------------------------
def adopt_patch(setup):
    """The patch file in shadPS4 is the one this Overtime writes but another record holds it (a lab run or a second
    copy of the app patched with its own app folder; 2026-10-29 17:59): take it over, and note this version made it,
    instead of "Patched, with 1 problem" and "patched by an older Overtime" until Patch is pressed again."""
    ctl = setup.ctl
    try:
        xml = setup._xml()
        if gamesetup.adopt(tuple(xmlpatch.with_resolution(t, res) for t in (xml, xmlpatch.bap32_off(xml),
                                                                             xmlpatch.expansion32_off(xml))
                                 for res in xmlpatch.RESOLUTIONS)):
            by = selfupdate.parse_version(ctl.prefs.get('patched_by'))
            if by is None or by < selfupdate.parse_version(VERSION):
                ctl.remember(patched_by=VERSION)
            ctl.host.log('The patch file in shadPS4 is this version\'s own: its record was brought up to date.')
    except EXPECTED:
        pass


def look(setup):
    """What is in the game now (in the job's thread: overlay.status hashes the patch files): the overlay, whether
    shadPS4 runs, the eboot patch and whether its 32-team switch is on, and the game folder's size (once a folder)."""
    ctl = setup.ctl
    adopt_patch(setup)
    game_dir = ctl.game_dir
    game = getattr(ctl, 'game', None)
    ok = bool(game_dir) and (game.ok if game is not None else gamesetup.read_game(game_dir)['ok'])
    emu = setup.emulator if setup.emulator and os.path.isfile(setup.emulator) else None
    st = gamesetup.status(emu)
    m = st.get('manifest') or {}
    eboot = {'installed': st['installed'], 'intact': st['intact'], 'targets': st['targets'],
             'problems': list(st['problems']), 'updated': m.get('updated')}
    out = {'overlay': overlay.status(game_dir) if ok else None, 'running': overlay.emulator_running(),
           'match_setup': matchsetup.active(),
           'eboot': eboot, 'teams32': installed_teams32(st)}
    part = _part(ctl)
    if ok and part is not None and part.size[0] != game_dir:
        out['size'] = (game_dir,) + measure(game_dir)
    return out


def installed_teams32(st):
    """Whether the installed eboot patch (gamesetup.status `st`) has the 32-team switch on; None when not known."""
    m = st.get('manifest') or {}
    if not (st.get('installed') and m.get('user_dir')):
        return None
    try:
        with open(os.path.join(gamesetup.patch_dir(m['user_dir']), gamesetup.PATCH_FILE), encoding='utf-8') as f:
            return xmlpatch.expansion32(f.read())
    except (OSError, ValueError, xmlpatch.PatchError):
        return None


def safe_look(setup):
    try:
        return look(setup)
    except EXPECTED:
        return None


def measure(game_dir):
    """(bytes, files) of the game folder."""
    total = count = 0
    for folder, _dirs, names in os.walk(game_dir):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(folder, name))
                count += 1
            except OSError:
                continue
    return total, count


def keep(ctl, seen):
    """Store a look (under ctl.lock)."""
    ctl.patch_status, ctl.patch_running = seen['overlay'], seen['running']
    part = _part(ctl)
    if part is not None:
        part.eboot, part.teams32 = seen['eboot'], seen['teams32']
        if 'size' in seen:
            part.size = seen['size']


def run_job(setup, busy, work, said, stopped, then=None, error=False, rescan=True, stop=None):
    """Run `work(step)` as the app's one job (`busy` on the Help bar; step(text, share) tells where it is), then look
    at the game again. Done: said(result) gives the Help bar's line, then `then()`. Refused: its reason (caution).
    Failed: "<stopped>: <why>" (bad), kept as the tab's error state when `error`. Setup looks again after it.
    `stop()`: called first when the job ends, however it ends (the Patch meter's ticker stops before the last line)."""
    ctl = setup.ctl
    part = _part(ctl)
    with ctl.lock:
        doing = ctl.busy
        if not doing:
            ctl.busy = busy
            if error and part is not None:
                part.error = None
    if doing:
        ctl.say(f'Wait a moment: {_doing(doing)} is still running.', 'caution')
        return None
    ctl.say(busy, 'info', -1)
    ctl.changed('patch', 'setup', 'app')
    title = busy.rstrip('. ')

    def step(text, share=-1, amount=None):
        if amount:
            ctl.say(f'{title}: {text}', 'info', share, amount=amount)
        else:
            ctl.say(f'{title}: {text}', 'info', share)

    def body():
        try:
            out = work(step)
        except Refused as err:
            return True, str(err), safe_look(setup)
        return False, out, safe_look(setup)

    def end(text, tone, seen, failure=None):
        if stop:
            try:
                stop()
            except Exception as err:    # noqa: BLE001 - the job's end is said all the same
                ctl.host.log(f'{title}: {err}')
        if text:
            ctl.say(text, tone)     # before busy goes: a poll that sees it idle reads the end
        with ctl.lock:
            if seen is not None:
                keep(ctl, seen)
            ctl.busy = None
            if failure and part is not None:
                part.error = failure
        ctl.changed('patch', 'setup', 'app', 'status', 'update')     # Update's patch bar reads the look too
        if rescan and hasattr(setup, '_scan'):
            setup._scan()

    def done(result):
        refused, out, seen = result
        if refused:
            end(out, 'caution', seen)
            return
        with ctl.lock:
            if seen is not None:
                keep(ctl, seen)     # said() reads the new state
        text, tone = said(out)
        end(text, tone, None)
        if then:
            then()

    def failed(message):
        ctl.host.log(message)
        text = f'{stopped}: {_lower(message)}'
        end(text, 'bad', safe_look(setup), text if error else None)
    jobs.run(body, done, failed, expected=EXPECTED)
    return None


def patched_text(teams32, roster):
    if teams32:
        return 'Patched. Start NHL 19 to play on the Overtime server.'
    if roster:
        return 'Patched, with 31 teams: the default roster has no Seattle. Run Update, then press Patch again.'
    return 'Patched, with 31 teams. Turn on the default roster switch for Seattle.'


def offer_update(ctl):
    """After a Patch with 32 teams: when the open roster is a save without an active Seattle (New Season crashes with
    it while the game runs 32 teams, rosterupdate.seattle_ready), ask "Update <name> now?": Update it now opens the
    Update tab and runs Go over it (its own questions and backup first), Later closes. Returns whether it asked."""
    parts = getattr(ctl, 'parts', None) or {}
    if 'rosters' not in parts or 'update' not in parts or getattr(ctl, 'shell', None) is None:
        return False
    with ctl.lock:
        mine = parts['rosters'].open_roster()
        s = ctl.session
        if not mine or mine['kind'] != 'save' or s is None:
            return False
        try:
            ready = rosterupdate.seattle_ready(s.db)
        except (KeyError, IndexError, StopIteration, TypeError, ValueError):   # no custom team tables
            ready = False
        if ready:
            return False
        name = mine['name']

    def now():
        ctl.host.send('goto', 'update')
        up = parts['update']
        if up.save_mode('update') is not None:
            return None             # it says why (the Help bar)
        return up.update_go()
    ctl.shell.ask(f'Update {name} now?', [
        f'The game runs 32 teams now. New Season crashes with {name} until it is updated: the update brings '
        'Seattle in.', 'Update it now runs the Update tab\'s Go over it (your saves are backed up first).'],
        [('Update it now', 'update', 'primary'), ('Later', 'later', 'plain')], {'update': now})
    return True


SHIPPED_LOGOS = ('Club logos: made for the default roster this version ships, which has the 2018 club names. The clubs '
                 'that moved keep their old logos until you run Update and then Patch.')


def clubart_roster(ctl, database, came):
    """(team rows, origin, save folder) of the roster the club logos are made for, or (None, None, None). There is one
    club logo pack for the game, so it follows the roster NHL 19 plays (v0.50.1: Patch made it of the shipped default,
    whose AHL clubs carry their 2018 names, and the clubs Update moved lost their logos):
    1. the active roster's save (savegame.active_roster), as Update or the player left it ('save');
    2. the default Patch serves, when it was rebuilt by an Update ('default': defaultdb.pick's 'update' / 'cache' /
       'fresh');
    3. the default Patch serves, when the profile says NHL 19 plays its own roster ('shipped' when that is the
       default this version ships: its names are the ones the game shows);
    4. the save the last Update wrote (prefs 'update_saved'), when no profile says which roster is played;
    5. the shipped default ('shipped'). The saves are only read."""
    schema = ctl.game.schema()
    save_dir = getattr(ctl, 'save_dir', None)
    say = ctl.host.log

    def rows(raw):
        try:
            return tdb.Database.parse(raw, schema)[T.TEAMS].rows()
        except Exception as err:  # noqa: BLE001 - a logo never stops a patch
            say(f'club logos: the roster does not read ({err})')
            return None

    def of_save(folder):
        path = os.path.join(save_dir, folder) if save_dir and folder else None
        if not path or not os.path.isdir(path):
            return None
        try:
            return rows(savegame.read(path).db_bytes)
        except (OSError, ValueError, savegame.SaveError) as err:
            say(f'club logos: {folder} does not read ({err})')
            return None
    default = 'shipped' if came == 'embedded' else 'default'
    active = savegame.active_roster(save_dir) if save_dir else None
    if active and (got := of_save(active)) is not None:
        return got, 'save', active
    if database is not None and default == 'default' and (got := rows(database)) is not None:
        return got, 'default', None
    profile = bool(save_dir) and os.path.isdir(os.path.join(save_dir, 'Profile0'))
    if not (active is None and profile):
        saved = ctl.prefs.get('update_saved') or {}
        for folder in sorted(saved, key=lambda k: str((saved[k] or {}).get('when') or ''), reverse=True):
            if (got := of_save(folder)) is not None:
                return got, 'save', folder
    if database is not None and (got := rows(database)) is not None:
        return got, default, None
    return None, None, None


def clubart_text(clubs, log=None):
    """The Patch result's words about the club logos it made (clubart.compose's counts with clubart_roster's origin),
    or ''. Logged in full; said only when a club slot has no logo or the logos follow the shipped default."""
    if not clubs:
        return ''
    missing = clubs.get('missing') or []
    where = {'save': f"roster {clubs.get('where')}", 'default': 'the updated default roster',
             'shipped': 'the shipped default roster'}.get(clubs.get('origin'), 'the roster')
    if log:
        log(f"club logos of {where}: {clubs['clubs']} clubs matched, {clubs['files']} files "
            f"({'as before' if clubs.get('kept') else 'made'}), {len(missing)} club slots keep NHL 19's own logo"
            + (f": {', '.join(missing[:12])}" if missing else ''))
    words = []
    if clubs.get('origin') == 'shipped':
        words.append(SHIPPED_LOGOS)
    elif missing:
        words.append(f"Club logos: {clubs['clubs']} clubs matched, {len(missing)} slot"
                     f"{'s' if len(missing) != 1 else ''} kept NHL 19's own logo (the update has no club for "
                     f"{'it' if len(missing) == 1 else 'them'}).")
    return ' '.join(words)


def one_click(setup, then=None):
    """Patch (Setup's setup_patch; patch_apply is beta1's name): checks, the clean-game record (the first time), the
    data overlay with exactly the switches that are on (one that is off is off: its served layer goes), the eboot
    patch with the server address and the network settings (gamesetup.install; the 32-team switch only when the roster served has an active
    Seattle: SetupController._seattle_ready), then a look. `then()` after a patch that went in (Play's "Patch
    first"). The picture packs are used only when they are here: the one click never downloads them (v0.10.0: the
    Photos, logos pack card does, SetupController.packs_get)."""
    ctl = setup.ctl
    with ctl.lock:
        emu, game_dir, want = setup.emulator, ctl.game_dir, dict(ctl.patch_want)
    if not emu:
        text = 'Find NHL 19 in Setup first: the patch goes in with it.'
        ctl.say(text, 'caution')
        return {'error': text}
    cache = cache_dir()
    on = switches(want, packs_here(cache))
    box = {}            # the Patch meter, once work() made it

    def work(step):
        speed = patchmeter.load(cache)
        meter = box['meter'] = patchmeter.Meter(step, speed['speeds'], amount=patchmeter.patched_text)
        box['last'] = speed['last']
        plan_patch(meter, speed['last'], on, cache, setup)
        meter.start()
        meter.begin('prepare')
        game = gamesetup.read_game(game_dir)
        if not game['ok']:
            raise Refused(f"NHL 19 cannot be patched: {game['problem']}.")
        if overlay.emulator_running():
            raise Refused('shadPS4 is running. Close NHL 19, then press Patch again.')
        if matchsetup.active():
            raise Refused(MATCH_LOCKED)
        gamesetup.use_game(game_dir)
        if game['title_id'] != gamesetup.TITLE_ID:     # CUSA11116 v1.60 runs CUSA11126's eboot (same sha256, 2026-11-03)
            ctl.host.log(f"NHL 19 {game['title_id']}: eboot.bin sha256 "
                         f"{gamesetup._file_sha(gamefiles.locate(game_dir, 'eboot.bin'))}")
        with eb.cached_tocs():  # the game's archives are only read until overlay.apply: each table is parsed once
            index, kit_jobs = scan_patch(meter, box['last'], on, game_dir, cache, ctl.host.log)
            meter.begin('texts')
            lang = game_text(game_dir, log=ctl.host.log)
            xml = setup._xml()
            if gamesetup.load_clean() is None:
                meter.begin('clean')
                gamesetup.save_clean(gamesetup.snapshot(game_dir))
            else:
                meter.skip('clean')
            layers = [k for k in DATA_LAYERS if on[k]]
            texts = [k for k in TEXT_LAYERS if k in layers]
            left_out = texts if lang is None else [
                k for k in texts if lang != textpack.LANG and not overlay.layer_fits(game_dir, k, lang)]
            layers = [k for k in layers if k not in left_out]
            database = None
            if on['roster']:
                meter.begin('roster')
                database = setup._default_roster()
                meter.rekind('roster', ROSTER_KINDS.get(getattr(setup, 'default_came', None), meter.kind('roster')))
                layers.append('database')
            now = overlay.status(game_dir)
            if on['art'] and 'art' in (now.get('layers') or {}):
                layers.append('art')  # with no pack here the served art stays (patch.art_layer)
            clubs = None
            if on['art'] and patch.clubart_source(cache):
                meter.begin('clubart')  # as Update does after a save; unchanged: kept
                teams, origin, where = clubart_roster(ctl, database, getattr(setup, 'default_came', None))
                if teams is not None:
                    source, todo = patch.clubart_work(teams, game_dir, cache, index)
                    meter.resize('clubart', todo)
                    clubs = patch.make_clubart(teams, game_dir, cache, log=ctl.host.log,
                                               progress=lambda share: meter.share_of('clubart', share),
                                               index=index, source=source)
                    if clubs is not None:
                        clubs = dict(clubs, origin=origin, where=where)
            if on['art']:       # the jerseys of the layer packs on this PC's game files; unchanged: kept
                patch.make_kits(on, game_dir, cache, log=ctl.host.log, step=meter.say, jobs=kit_jobs,
                                progress=lambda fam, share: (meter.begin(f'kits:{fam}'),
                                                             meter.share_of(f'kits:{fam}', share)))
            if on['art']:
                meter.begin('packs')
                meter.resize('packs', patch.art_layer_work(on, cache, game_dir))   # the packs just made count none
            art = patch.art_layer(on, layers, cache, log=ctl.host.log, game_dir=game_dir,
                                  progress=lambda n: meter.tick('packs', n))
        meter.begin('build', 'writing the patch files' + (' and the updated team art...' if 'art' in layers else '...'))
        applied = None
        if layers:
            # news is no switch: always the tile (a beta1 patch served the hub without it, and apply keeps served options)
            applied = overlay.apply(game_dir, layers, database=database, menus={'chel': on['chel'], 'news': True},
                                    art=art, lang=lang or textpack.LANG, progress=apply_meter(meter))
        elif now.get('applied'):
            overlay.undo(game_dir)  # every switch off: no data patch, the server alone
        for key in ('copy', 'write', 'verify'):
            if not applied:
                meter.skip(key)
        teams32 = setup._seattle_ready(database)
        if not teams32:
            xml = xmlpatch.expansion32_off(xml)
        elif not on['league']:
            xml = xmlpatch.bap32_off(xml)  # Seattle in Be a Pro needs the league layer's Lua
        meter.begin('install')
        manifest = gamesetup.install(emu, xml)
        meter.begin('look')     # the look at the game after the work (run_job); the meter ends with said()
        return {'layers': list((applied or {}).get('layers') or []), 'targets': manifest['targets'],
                'teams32': teams32, 'lang': lang, 'left_out': left_out, 'clubs': clubs}

    def said(out):
        learn_patch(box.get('meter'), box.get('last'), cache, ctl.host.log)
        layers = ', '.join(out['layers']) or 'none'
        ctl.host.log(f"Game patched: server {out['targets']['redirector']}, layers {layers}, "
                     f"{'32 teams' if out['teams32'] else '31 teams (the roster served has no active Seattle)'}")
        # which version patched (the adopt check reads it); a text layer left out is no change waiting
        ctl.remember(patched_by=VERSION, left_out=out['left_out'])
        text = patched_text(out['teams32'], on['roster'])
        if out['left_out']:
            ctl.host.log(f"Text file {out['lang'] or 'none'}: left out {', '.join(out['left_out'])}")
            text += ' ' + left_out_text(out['lang'], out['left_out'])
        words = clubart_text(out.get('clubs'), log=ctl.host.log)
        if words:
            text += ' ' + words
        if out['teams32'] and then is None:
            offer_update(ctl)
        return text, 'good'
    return run_job(setup, PATCHING, work, said, 'The patch stopped', then=then, error=True,
                   stop=lambda: box['meter'].stop() if 'meter' in box else None)


# --- Patch's progress (patchmeter): what each step is, measured before the long ones run -----------------------------
ROSTER_KINDS = {'update': 'time:roster_update', 'cache': 'time:roster_quick', 'embedded': 'time:roster_quick',
                'fresh': 'time:roster_fresh'}       # defaultdb.pick's origin of the default roster: its kind of work
KIT_FAMILIES = ('pants', *kitcompose.FAMILIES)


def _roster_kind(setup):
    """How the default roster will be made (SetupController._default_roster): rebuilt from the Update tab's data
    gathered in this session ('update'), else read (cache / the exe's)."""
    ctl = setup.ctl
    with ctl.lock:
        gathered, season = getattr(ctl, 'upd_gathered', None), getattr(ctl, 'upd_season', None)
    rebuilt = gathered is not None and getattr(gathered, 'season', None) == season
    return 'time:roster_update' if rebuilt else 'time:roster_quick'


def plan_patch(meter, last, on, cache, setup):
    """Patch's steps in their order, each with what it was the last time (`last`: patchmeter.load) until it is
    measured (scan_patch, overlay.apply's plan)."""
    meter.plan('prepare', 'time:prepare', 1, 'checking NHL 19...')
    meter.plan('scan', 'time:scan', 1, 'measuring the work...')
    meter.plan('texts', 'time:texts', 1, "reading the game's text...")
    meter.plan('clean', 'time:clean', 1, 'noting the clean game first...')
    if on['roster']:
        meter.plan('roster', _roster_kind(setup), 1, f'making the {SEASON_LABEL} default roster...')
    if on['art']:
        meter.plan('clubart', 'clubart', last.get('clubart', 0), 'making the club logos of the roster you play...',
                   writes=True)
        for fam in KIT_FAMILIES:
            meter.plan(f'kits:{fam}', 'kits', last.get(f'kits:{fam}', 0),
                       'making the jerseys on this PC...' if fam == 'pants' else '', writes=True)
        meter.plan('packs', 'check', last.get('packs', 0), 'checking the art packs...')
    meter.plan('build', 'time:build', 1, 'writing the patch files...')
    meter.plan('copy', 'copy', last.get('copy', 0), 'writing the patch files...', writes=True)
    meter.plan('write', 'write', last.get('write', 0), 'writing the updated team art...', writes=True)
    meter.plan('verify', 'verify', last.get('verify', 0), 'reading the written team art back...')
    meter.plan('install', 'time:install', 1, 'pointing NHL 19 at the Overtime server...')
    meter.plan('look', 'time:look', 1, 'checking the patch files...')


def scan_patch(meter, last, on, game_dir, cache, log):
    """Measure the long steps before they run (the 'scan' step): the game's index (read once, handed to each step that
    makes textures), the jersey families to make and their work (patch.kit_jobs), the art pack bytes to check, and
    (the first time: after that, what the last Patch wrote is the better guess, an archive it kept writes nothing) the
    archives overlay.apply copies and writes. Returns (index, kit jobs)."""
    meter.begin('scan')
    index = patch._game_index(game_dir) if on['art'] or 'copy' not in last else None
    jobs = patch.kit_jobs(on, game_dir, cache, log=log, index=index) if on['art'] else []
    work = {f'kits:{j.family}': j for j in jobs}
    for fam in KIT_FAMILIES:
        key = f'kits:{fam}'
        if key in work and work[key].work:
            meter.resize(key, work[key].work)
            meter.written_bytes(key, work[key].bytes)
        else:
            meter.skip(key)     # off, kept as it is, or nothing to make
    if on['art']:
        meter.resize('packs', patch.art_layer_work(on, cache, game_dir))
    if 'copy' not in last and index is not None:
        layers = [k for k in DATA_LAYERS if on[k]] + (['database'] if on['roster'] else [])
        meter.resize('copy', overlay.copy_size(game_dir, layers, where=index[0]))
    if 'write' not in last and on['art']:
        size = patch.art_layer_bytes(on, cache, game_dir, jobs, index[1] if index else None)
        meter.resize('write', size)
        meter.resize('verify', size)
    return index, jobs


def apply_meter(meter):
    """overlay.apply's progress(stage, amount) on the meter: its plan sizes the copy, write and verify steps (none:
    skipped, an archive kept as it is writes nothing), then each stage's bytes."""
    def progress(stage, amount):
        if stage == 'plan':
            for key in ('copy', 'write', 'verify'):
                if amount.get(key):
                    meter.resize(key, amount[key])
                else:
                    meter.skip(key)
            return
        meter.begin(stage)
        meter.tick(stage, amount)
    return progress


def learn_patch(meter, last, cache, log=None):
    """After a Patch that went in: the bar full, this PC's speeds kept for the next one (patchmeter.save), and how long
    each step took against its plan in the log (the bar's 1 % is 1 % of the time when these match)."""
    if meter is None:
        return
    meter.finish()
    if log:
        rows = meter.report()
        total = sum(took for *_r, took in rows)
        log(f'Patch took {total:.1f} s, {patchmeter.patched_text(meter.written()).lower()}: ' + ', '.join(f'{key} {took:.1f} s (planned {plan:.1f})'
                                                      for key, _kind, _units, plan, took in rows if took >= 0.05))
    speeds, units = meter.learned(last)
    patchmeter.save(cache, speeds, units)


def one_unpatch(setup):
    """Unpatch (Setup's setup_unpatch; patch_undo is beta1's name): the overlay and the eboot patch go, the network
    settings come back as they were. Refused while shadPS4 runs."""
    ctl = setup.ctl
    game_dir = ctl.game_dir

    def work(_step):
        if overlay.emulator_running():
            raise Refused('shadPS4 is running. Close NHL 19, then press Unpatch again.')
        if matchsetup.active():
            raise Refused(MATCH_LOCKED)
        tags = onlinetag.remove(game_dir) if game_dir else []     # first: overlay.undo then clears empty folders
        removed = overlay.undo(game_dir) if game_dir else []
        return tags + list(removed or []) + gamesetup.remove()

    def said(removed):
        for line in removed:
            ctl.host.log(str(line))
        if not removed:
            return 'NHL 19 is not patched: there is nothing to take away.', 'info'
        return 'Unpatched. NHL 19 runs as it came. Press Patch to put it back.', 'good'
    return run_job(setup, UNPATCHING, work, said, 'Unpatch stopped', error=True)


def verify(setup, full=False):
    """Quick check (sizes, the eboot's hash) or every file (34 GB, minutes) against the clean-game record (made at the
    first patch, or now). A full check that finds the game as it came keeps its hashes as the record."""
    ctl = setup.ctl
    game_dir = ctl.game_dir
    full = bool(full)

    def work(step):
        clean = gamesetup.load_clean()

        def progress(done, total):
            step(f'{done / 2**30:.1f} of {total / 2**30:.1f} GB', done / total if total else -1)
        now = gamesetup.snapshot(game_dir, full=full, progress=progress if full else None)
        files = len(now['files'])
        if (clean is None or os.path.normcase(clean.get('game_dir', '')) != os.path.normcase(game_dir)
                or clean.get('update') != now.get('update')):   # a record from before the update folder counted
            gamesetup.save_clean(now)
            return None, files, False
        diff = gamesetup.compare(clean, now)
        upgraded = full and not diff and not clean.get('full')
        if upgraded:
            gamesetup.save_clean(now)
        return diff, files, bool(clean.get('full')) and full

    def said(out):
        diff, files, every = out
        setup.verify_result = {'when': time.strftime('%Y-%m-%d %H:%M'), 'full': full, 'diff': diff, 'files': files,
                               'every': every}
        text = verify_text(setup.verify_result)
        return text['text'], text['tone']
    return run_job(setup, 'Checking the game files...', work, said, 'The check stopped')


def verify_text(v, files=None):
    """{text, tone, date} of a clean-game check (setup.verify_result)."""
    diff = v.get('diff')
    n = v.get('files') or files
    date = friendly_date(v.get('when'))
    if diff is None:
        return {'text': 'Clean-game record made: Quick check compares with it later.', 'tone': 'good', 'date': date}
    if not diff:
        if not n:
            text = 'The game folder is as it came.'
        elif v.get('every'):
            text = f'All {n:,} game files are as they came.'
        elif v.get('full'):
            text = f'All {n:,} game files are there and the right size. The next full check compares every byte.'
        else:
            text = f'All {n:,} game files are there and the right size.'
        return {'text': text, 'tone': 'good', 'date': date}
    first = str(diff[0][0] if isinstance(diff[0], (list, tuple)) else diff[0])
    if len(diff) == 1:
        text = f'{first} is not as it came. Install NHL 19 again (its PKG with Find game).'
    else:
        text = (f'{len(diff)} game files are not as they came, {first} first. Install NHL 19 '
                'again (its PKG with Find game).')
    return {'text': text, 'tone': 'bad', 'date': date}


def online_facts(setup):
    """What "What's in your game now" says about playing online: the server the patch points at, whether shadPS4's
    network switches are on for NHL 19 (both config sections, gamesetup.network_written), and who NHL 19 signs in to
    ShadNet as, and whether it plays in step with the other CPU maker (crosscpu.item). {'server', 'network':
    True/False/None, 'shadnet': Online ID or '', 'cross': {tone, text, title} or None} (None/'': shadPS4 not set up)."""
    emu = setup.known_emulator()
    user = gamesetup.emu_user_dir(emu) if emu else ''
    out = {'server': (setup.server or {}).get('host') or '', 'network': None, 'shadnet': '', 'cross': None}
    if not user:
        return out
    try:
        out['network'] = gamesetup.network_on(user) and gamesetup.network_written(user)
        one = gamesetup.shadnet_player(user) or {}
        out['shadnet'] = (one.get('npid') or '') if one.get('shadnet') else ''
    except (OSError, ValueError, gamesetup.SetupError):
        pass
    try:
        out['cross'] = crosscpu.item(setup)
    except Exception as err:    # noqa: BLE001 (a look must never stop the tab; the block is for a bug report)
        jobs.log_block(err, 'Cross-CPU check')
    return out


def play(setup):
    """Play: NHL 19 in shadPS4. Not patched (no eboot patch): the Question first (Patch first / Play as it is /
    Cancel); it returns at once."""
    ctl = setup.ctl
    with ctl.lock:
        doing = ctl.busy
    if doing:
        ctl.say(f'Wait a moment: {_doing(doing)} is still running.', 'caution')
        return None
    if not setup.known_emulator():
        text = 'Find NHL 19 in Setup first.'
        ctl.say(text, 'caution')
        return {'error': text}
    shell = getattr(ctl, 'shell', None)
    if shell is not None and gamesetup.load_manifest() is None:
        shell.ask('NHL 19 is not patched',
                  ['Without the patch, NHL 19 cannot go online and has 31 teams.',
                   'Patch it first? It takes about a minute.'],
                  [('Patch first', 'patch', 'primary'), ('Play as it is', 'play', 'danger'),
                   ('Cancel', 'cancel', 'plain')],
                  {'patch': lambda: one_click(setup, then=lambda: start(setup)), 'play': lambda: start(setup)})
        return None
    return start(setup)


def refresh_network(setup):
    """Point the patched game at the server of Setup's field and switch shadPS4's two network keys back on, without
    Patch (owner, 2026-11-03: "the app doesnt need a patch each time we edit network settings"), and readbacks back to
    Precise with readback linear images on (owner 2026-11-10: for everyone). Only the eboot patch file and the keys are
    written (gamesetup.install keeps the first backups and the player's first settings), never game data. Returns 'written', 'same' (nothing to do), 'later' (shadPS4 runs: the next start does it) or None (not
    patched by this Overtime, or its patch file is another version's: Patch makes it new)."""
    emu = setup.known_emulator()
    text = gamesetup.installed_patch() if emu else None
    if text is None:
        return None
    try:
        new = xmlpatch.repoint(text, setup.server['host'], setup.server.get('nucleus_url'), setup.features())
        new = xmlpatch.with_resolution(new, getattr(setup, 'resolution', 1080))     # the Resolution choice
    except xmlpatch.PatchError as err:
        setup.ctl.host.log(f'The server was not put into the patch file: {err}')
        return None
    user = gamesetup.emu_user_dir(emu)
    if (new == text and gamesetup.network_on(user) and gamesetup.network_written(user)
            and gamesetup.amd_math_on(user) and gamesetup.readbacks_on(user)):
        return 'same'
    if overlay.emulator_running() or matchsetup.active():
        return 'later'
    gamesetup.install(emu, new)
    setup.ctl.host.log(f"Server {setup.server['host']} put into the patch file, network keys on (no Patch needed).")
    return 'written'


def online_minimum(setup):
    """The least a game needs to play online, for an online Ready on a game without the patch (multiplayer_ctl; owner
    2026-11-08: "only the bare minimum for online ... so it doesnt take a lot of time"): the eboot patch file of this
    version (server, network fixes, the 32-team switch on), shadPS4's network keys and, on a game
    with no data patch at all, the menus layer alone (the online start the lobby's launch needs; 0.1 s to build). No
    roster, text, art or clean-game record: those are Patch's, and an online match plays the lobby's roster. About a
    second. Returns the manifest (gamesetup.install).
    The 32-team switch is on as in every fully patched game (its roster has an active Seattle), so the two patches hash
    the same (xmlpatch.netplay_fingerprint counts it). Off-line, a New Season on the stock roster with the switch on can
    crash (ws8 run7a): Patch sets it by the roster then."""
    emu, game_dir = setup.known_emulator(), setup.ctl.game_dir
    if not emu:
        raise gamesetup.SetupError('Find NHL 19 in Setup first.')
    if matchsetup.active():
        raise gamesetup.SetupError(MATCH_LOCKED)
    layers = (overlay.status(game_dir) or {}).get('layers') or {} if game_dir else {}
    if game_dir and not layers:
        overlay.apply(game_dir, ('menus',), menus={'news': True})
    xml = setup._xml()
    if 'league' not in layers:
        xml = xmlpatch.bap32_off(xml)           # Seattle in Be a Pro needs the league layer's Lua (local only)
    manifest = gamesetup.install(emu, xml)
    setup.ctl.host.log('Online: the eboot patch, network keys%s put in for online play (no full Patch).'
                       % ('' if layers else ' and the online start'))
    return manifest


def _refresh_before_start(setup):
    """refresh_network before a start; a failure is logged and the game starts as it is."""
    try:
        return refresh_network(setup)
    except Exception as err:    # noqa: BLE001 (Play must not stop on it; the block is for a bug report)
        jobs.log_block(err, 'Server into the patch file before Play')
        return None


def _tag_why(emu, game_dir):
    """onlinetag.why of this start: '' or why online it meets only games with the same setup. Never raises."""
    try:
        return onlinetag.why(onlinetag.start_inputs(emu, game_dir))
    except Exception as err:    # noqa: BLE001 (a hint only)
        jobs.log_block(err, 'Matchmaking tag hint at Start')
        return ''


def start(setup):
    """Start shadPS4 with NHL 19 (launch.start) and watch its log a few minutes (SetupController._watch_play). The
    server of Setup's field and the network keys go in first (refresh_network)."""
    ctl = setup.ctl
    with ctl.lock:
        emu, game_dir = setup.emulator, ctl.game_dir
        if ctl.busy or setup._launching:
            return None
        setup._launching = True  # until Popen returned: then emulator_running() sees it
    try:
        if _refresh_before_start(setup) == 'written':
            ctl.changed('setup', 'patch')
        proc = launch.start(emu, game_dir)
    except launch.LaunchError as err:
        ctl.say(str(err), 'bad')
        return {'error': str(err)}
    finally:
        with ctl.lock:
            setup._launching = False
    with ctl.lock:
        setup.play = {'state': 'starting', 'pid': proc.pid, 'log': None}
        ctl.patch_running = True    # Check again sees when it is closed
    why = _tag_why(emu, game_dir)
    ctl.say('NHL 19 is starting in shadPS4...' + (f' {why}' if why else ''), 'caution' if why else 'info')
    ctl.changed('setup', 'patch', 'app')
    threading.Thread(target=setup._watch_play, args=(emu, proc), daemon=True, name='play-watch').start()
    mp = getattr(ctl, 'parts', {}).get('multiplayer')
    if mp is not None and hasattr(mp, 'watch_open_link'):
        mp.watch_open_link(proc)    # the ping / loss corner in a match the game finds itself (0.90.2)
    return {'ok': True}


# --- what the tab shows --------------------------------------------------------------------------------------------
def chips(st, teams32):
    """[{key, text}]: the layers served now, in words."""
    ly = (st or {}).get('layers') or {}
    now = served(st)
    out = []

    def add(key, text):
        out.append({'key': key, 'text': text})
    if now['names']:
        n = (ly.get('names') or {}).get('strings')
        add('names', f'{n} names' if n else 'Utah names')
    if now['roster']:
        teams = ', 32 teams' if teams32 else ', 31 teams' if teams32 is False else ''
        add('roster', f'{SEASON_LABEL} default roster{teams}')
    if now['league']:
        league = ly.get('league') or {}
        cap, floor = league.get('cap'), league.get('floor')
        add('league', f'Cap ${cap / 1e6:.1f}M, floor ${floor / 1e6:.1f}M' if cap and floor else 'Salary cap')
    if now['text']:
        n = (ly.get('text') or {}).get('strings')
        add('text', f'{n} texts' if n else 'Overtime server texts')
    if now['menus']:
        add('menus', 'Hub without the closed modes')
    if now['chel']:
        add('chel', 'World of Chel kept')
    if now['art']:
        packs = [p for p in (ly.get('art') or {}).get('packs') or []
                 if not any(w in str(p.get('name', '') if isinstance(p, dict) else p).lower()
                            for w in ('kits', 'photos', 'alts-', 'ice-all'))]
        add('art', f"{len(packs)} art pack{'s' if len(packs) != 1 else ''}" if packs else 'Team art')
    if now['photos']:
        add('photos', 'NHL.com player photos')
    if now['kits']:
        add('kits', '3D jerseys')
    extra = sum(now[key] for key in EXTRA_KEYS)
    if extra:
        add('extras', f"{extra} jersey and ice pack{'s' if extra != 1 else ''}")
    return out


def problem_text(text):
    """overlay.status()'s problem in player words."""
    rel, _sep, what = str(text).partition(': ')
    name = rel.rsplit('/', 1)[-1]
    if what.startswith('missing from the overlay'):
        return f'{name} is missing. Press Patch again to put it back.'
    if what.startswith('changed since the patch'):
        return f'{name} was changed after the patch. Press Patch again to put it right.'
    if 'game update' in what:
        return f'The game changed under {name} (a game update?). Press Patch again.'
    return f'{text}. Press Patch again.'


def eboot_problem(text):
    """gamesetup.status()'s problem in player words."""
    text = str(text)
    settings = 'custom_configs' in text
    if text.startswith('missing: '):
        return ("shadPS4's network settings for NHL 19 are missing. Press Patch again." if settings else
                'The Overtime server patch is missing in shadPS4. Press Patch again.')
    if text.startswith('network switched off: '):
        return "shadPS4's network switches for NHL 19 are off. Play turns them back on (no Patch needed)."
    if text.startswith('changed since setup: '):
        return ("shadPS4's network settings for NHL 19 were changed. Press Patch again." if settings else
                'The Overtime server patch in shadPS4 was changed. Press Patch again.')
    if text.startswith('set up for the emulator data'):
        return 'The patch is in another shadPS4 folder. Press Unpatch, then Patch.'
    return f'{text}. Press Patch again.'


def problems_of(st, eboot):
    out = [problem_text(p) for p in (st or {}).get('problems') or []]
    out += [eboot_problem(p) for p in (eboot or {}).get('problems') or []]
    return list(dict.fromkeys(out))


def size_text(size):
    if not size:
        return None
    return f'{size / 2**30:.0f} GB' if size >= 2**30 else f'{max(1, round(size / 2**20))} MB'


def state_line(f):
    """The state line under the card's head."""
    if f['busy']:
        return {'text': f['busy'], 'tone': 'info'}
    if not f['checked']:
        return {'text': 'Looking at NHL 19...', 'tone': 'info'}
    if f['running']:
        return {'text': 'shadPS4 is running. Close NHL 19 before you patch or unpatch.', 'tone': 'caution'}
    if f.get('match_setup'):
        return {'text': MATCH_LOCKED, 'tone': 'caution'}
    if f['error']:
        return {'text': f['error'], 'tone': 'bad'}
    if not f['patched']:
        return {'text': 'Not patched. NHL 19 runs as it came (lobby matches still work: Ready sets each one up). '
                        'Press Patch for the rest.', 'tone': ''}
    if f['problems']:
        n = len(f['problems'])
        return {'text': f"Patched, with {n} problem{'s' if n != 1 else ''}. Press Patch again to put "
                        f"{'them' if n != 1 else 'it'} right.", 'tone': 'bad'}
    if not f['online']:
        return {'text': 'The game data is patched, but NHL 19 cannot go online yet. Press Patch again.',
                'tone': 'caution'}
    if f['changed']:
        return {'text': 'Patched. You changed the switches: press Patch again to use them.', 'tone': 'caution'}
    teams32 = f['teams32'] if f['teams32'] is not None else f['served']['roster']
    if not teams32 and f['served']['roster']:
        return {'text': 'Patched, with 31 teams: the default roster has no Seattle. Run Update, then press Patch '
                        'again.', 'tone': 'caution'}
    if not teams32:
        return {'text': 'Patched, with 31 teams. Seattle needs the default roster switch.', 'tone': 'caution'}
    return {'text': f"Patched {f['applied_at']}. NHL 19 plays online on the Overtime server.".replace('  ', ' '),
            'tone': 'good'}


class PatchCtl(Part):
    SLICES = {'patch': 'view', 'patch_files': 'files_view'}
    CALLS = {'patch_refresh': 'patch_refresh', 'patch_option': 'patch_option', 'patch_group': 'patch_group',
             'patch_apply': 'patch_apply',
             'patch_undo': 'patch_undo', 'patch_kits_download': 'patch_kits_download',
             'patch_kits_remove': 'patch_kits_remove', 'patch_files': 'set_files'}
    TAB = 'patch'
    KITS_BUSY = 'Downloading the 3D jerseys pack...'   # the busy text while it downloads (Setup's Downloads card)
    why = staticmethod(why)

    def __init__(self, ctl):
        super().__init__(ctl)
        self.listing = False    # the patch files dialog is open
        self.kits_progress = None   # 0..1 while the kits pack downloads (Setup reads it while busy is KITS_BUSY)
        self.eboot = None       # the eboot patch (gamesetup.status) at the last look
        self.teams32 = None     # its 32-team switch is on (None: not known)
        self.size = (None, 0, 0)    # (game folder, bytes, files)
        self.error = None       # "The patch stopped: ..." until the next Patch or Unpatch

    # --- beta1's Patch tab -------------------------------------------------------------------------------------------
    def _patch_check(self):
        c = self.ctl
        return (overlay.status(c.game_dir) if c.game.ok else None), overlay.emulator_running()

    def _patch_job(self, busy, work, said):
        """Run a patch job; `said(work result)` gives the status line. The tab then shows the overlay as it is."""
        c = self.ctl
        with c.lock:
            if c.busy:
                return None
            if not c.game.ok:
                return {'error': 'NHL 19 was not found. Find it in Setup first.'}
            c.busy = busy
        c.say(busy, 'info', -1)
        c.changed('patch', 'source', 'editor', 'update')

        def run():
            out = work()
            return out, self._patch_check()

        def done(result):
            out, (st, running) = result
            with c.lock:
                c.busy = None
                c.patch_status, c.patch_running = st, running
            text, tone = said(out)
            c.say(text, tone)
            c.changed('patch', 'source', 'editor', 'update')

        def failed(message):
            with c.lock:
                c.busy = None
            c.host.log(message)
            c.say(message, 'bad')
            c.changed('patch', 'source', 'editor', 'update')
        jobs.run(run, done, failed, expected=(overlay.PatchError, patch.PatchFailed, update.UpdateError, PackError,
                                              nhlcom.NhlComError, OSError, ValueError))
        return None

    def patch_refresh(self):
        """Check again (and each time the tab opens): the patch files, the eboot patch, whether shadPS4 runs."""
        c = self.ctl
        with c.lock:
            if c.busy:
                return None
            was = bool(c.patch_running)

        def said(_out):
            if was and not c.patch_running:
                return 'shadPS4 is closed now. You can patch again.', 'good'
            line = state_line(self.facts(busy=False))
            return line['text'], line['tone'] or 'info'
        return run_job(c.setup, CHECKING, lambda _step: None, said, 'The check stopped', rescan=False)

    def patch_option(self, key, value):
        """One switch. Refused (caution, with the reason) when it cannot be on, and while a job runs."""
        c = self.ctl
        if key in ASSET_PACKS:
            return c.setup.pack_switch(key, value)
        if key not in KEYS:
            c.say(f'There is no switch called {key}.', 'bad')
            return {'error': 'no such switch'}
        with c.lock:
            busy, want = c.busy, dict(c.patch_want)
        no = why(dict(want, **{key: bool(value)}), key, packs_here(cache_dir())) if value else None
        if busy or no:
            c.say('Wait for the patch to finish.' if busy in (PATCHING, UNPATCHING) else
                  f'Wait a moment: {_doing(busy)} is still running.' if busy else no, 'caution')
            c.changed('patch')  # the switch goes back
            return None
        with c.lock:
            c.patch_want[key] = bool(value)
            c.remember(patch=dict(c.patch_want))
        c.changed('patch')
        return None

    def patch_group(self, key, value):
        """A group's own switch: on turns on its main switches (each that can be, in the page's order, so the team art
        goes first); off turns every switch of the group off. Asset switches download what is not here."""
        c = self.ctl
        group = next((g for g in GROUPS if g[0] == key), None)
        if group is None:
            c.say(f'There is no group called {key}.', 'bad')
            return {'error': 'no such group'}
        _key, title, _sub, keys, main = group
        setup = c.setup
        with c.lock:
            busy = c.busy
            running = bool(busy) and key == 'assets' and setup._extras_running()
        if busy and not running:
            c.say('Wait for the patch to finish.' if busy in (PATCHING, UNPATCHING) else
                  f'Wait a moment: {_doing(busy)} is still running.', 'caution')
            c.changed('patch')
            return None
        if value and key == 'assets' and not setup.known_emulator():
            c.say('Find NHL 19 first: the assets go in when you patch the game.', 'caution')
            c.changed('patch')
            return None
        found = packs_here(cache_dir())
        with c.lock:
            for k in (main if value else keys):
                c.patch_want[k] = bool(value) and not why(dict(c.patch_want, **{k: True}), k, found, missing_ok=True)
                if k in PACK_KEYS:
                    (setup.asked.add if c.patch_want[k] else setup.asked.discard)(k)
            c.remember(patch=dict(c.patch_want))
            if not value and running:
                setup.dl_stop = True
        c.changed('patch')
        if value and key == 'assets' and setup._extras_wanted():
            return setup._extras_next()
        if value:
            c.say(f'{title}: switched on. Press Patch to put it in the game.', 'good')
        return None

    def patch_apply(self):
        """beta1's name of Patch (setup_patch): the one click."""
        return one_click(self.ctl.setup)

    def patch_undo(self):
        """beta1's name of Unpatch (setup_unpatch)."""
        return one_unpatch(self.ctl.setup)

    def patch_kits_download(self):
        """Download the all-team 3D kits pack (packdownload) into the cache; the next patch serves it. Setup's
        Downloads card shows the share done (kits_progress) while the job runs."""
        c = self.ctl

        def work():
            def progress(share):
                self.kits_progress = share
                c.say(f'Downloading the 3D jerseys pack... {share:.0%}', 'info', -1)
                c.changed('setup')
            return packdownload.download_kits(paths.app_dir('cache'), progress=progress)
        self.kits_progress = 0.0
        return self._patch_job(self.KITS_BUSY, work,
                               lambda _p: ('Kits pack downloaded: patch the game to lay the 3D kits in.', 'good'))

    def patch_kits_remove(self):
        """Delete the downloaded kits pack; the next Apply takes the kits out of the game."""
        return self._patch_job('Removing the kits pack...', lambda: packdownload.remove_kits(paths.app_dir('cache')),
                               lambda had: (('Kits pack deleted: patch the game again to take the kits out.' if had
                                             else 'No kits pack was downloaded.'), 'good'))

    def snap_patch(self):
        c = self.ctl
        with c.lock:
            st = c.patch_status or {}
            season = c.upd_season
            return {
                'ready': c.game.ok, 'busy': bool(c.busy), 'checked': c.patch_status is not None,
                'running': c.patch_running, 'match_setup': matchsetup.active(), 'game_dir': c.game_dir,
                'overlay': overlay.overlay_dir(c.game_dir) if c.game_dir else '',
                'want': dict(c.patch_want), 'applied': bool(st.get('applied')), 'applied_at': st.get('applied_at'),
                'layers': st.get('layers') or {}, 'files': st.get('files') or {}, 'problems': st.get('problems') or [],
                'legacy': bool(st.get('legacy_text_pack')),
                'season_label': f'{season}-{(season + 1) % 100:02d}', 'per32': c.upd_per32 or 84,
                'offline': c.upd_offline, 'gathered': c.upd_gathered is not None,
                'names': [{'id': k, 'from': old, 'to': new} for k, (old, new) in overlay.NAMES.items()],
                'art_found': patch.art_found(paths.app_dir('cache')),
            }

    # --- the tab -----------------------------------------------------------------------------------------------------
    def set_files(self, on):
        self.listing = bool(on)
        self.ctl.changed('patch_files')

    @staticmethod
    def file_list(st):
        return [{'path': rel, 'state': 'missing' if not f.get('present') else 'as written' if f.get('unchanged')
                 else 'changed'} for rel, f in sorted(((st or {}).get('files') or {}).items())]

    def facts(self, busy=None, found=None):
        """What the tab is made from (under ctl.lock; re-entrant)."""
        c = self.ctl
        with c.lock:
            st = c.patch_status or {}
            eboot = self.eboot or {}
            want = dict(c.patch_want)
            found = packs_here(cache_dir()) if found is None else found
            now = served(st)
            picked = switches(want, found)
            left = set(c.prefs.get('left_out') or ())    # text layers this game cannot take (one_click)
            online = bool(eboot.get('installed'))
            patched = bool(st.get('applied')) or online
            when = max([w for w in (st.get('applied_at') if st.get('applied') else None, eboot.get('updated')) if w],
                       default=None)
            return {
                'busy': c.busy if busy is None else busy,
                'checked': c.patch_status is not None or self.eboot is not None,
                'running': bool(c.patch_running), 'error': self.error, 'patched': patched, 'online': online,
                'problems': problems_of(st, eboot) if patched else [], 
                'changed': patched and any(picked[k] != now[k] and not (now[k] is False and k in left)
                                           for k in picked), 'served': now, 'picked': picked,
                'want': want, 'kits': patch.KITS_PACK in found, 'teams32': self.teams32 if online else None,
                'applied_at': friendly_date(when) if patched else '', 'st': st,
            }

    def view(self):
        c = self.ctl
        found = packs_here(cache_dir())
        online = online_facts(c.setup)      # files only: read before the lock
        with c.lock:
            f = self.facts(found=found)
            st, want, picked, now, patched = f['st'], f['want'], f['picked'], f['served'], f['patched']
            ready = bool(c.game.ok)
            free = ready and not f['busy'] and not f['running']
            files = self.file_list(st)
            setup = c.setup
            verify = getattr(setup, 'verify_result', None)
            emulator = setup.known_emulator()
            _folder, size, count = self.size
            rows = []
            for key, title, sub, info in LAYERS:
                if key in ASSET_PACKS:
                    continue
                no = why(want, key, found)
                on, there = picked[key], now[key]
                tag = None
                if patched:
                    tag = {'text': 'In the game', 'tone': 'good'} if on and there else \
                        {'text': 'Patch to add', 'tone': 'caution'} if on else \
                        {'text': 'Patch to take away', 'tone': 'caution'} if there else None
                rows.append({'key': key, 'title': title, 'sub': sub, 'info': {'title': title, 'text': info}, 'on': on,
                             'disabled': bool(no), 'why': no, 'tag': tag, 'kind': 'layer'})
            assets = setup.extra_card(emulator, want, picked, now, patched, keys=ASSET_PACKS)
            by = {r['key']: r for r in rows}
            by.update((r['key'], dict(r, kind='asset')) for r in assets['rows'])
            groups = []
            for gkey, gtitle, gsub, keys, main in GROUPS:
                grows = [by[k] for k in keys]
                groups.append({'key': gkey, 'title': gtitle, 'sub': gsub, 'rows': grows,
                               'on': all(by[k]['on'] for k in main), 'count': sum(1 for r in grows if r['on']),
                               'disabled': bool(f['busy']) and not (gkey == 'assets' and setup._extras_running())})
            groups[-1]['store'] = setup.assets_store()
            return {
                'ready': ready, 'patched': patched, 'running': f['running'], 'busy': bool(f['busy']),
                'changed': f['changed'], 'checked': f['checked'],
                'state': state_line(f),
                'layers': rows, 'groups': groups, 'coming': dict(COMING), 'kits': {'installed': f['kits']},
                'pack': setup.pack_card(emulator),
                'buttons': {'patch': {'text': 'Patch again' if patched else 'Patch', 'enabled': free},
                            'unpatch': {'enabled': free and patched},
                            'play': {'enabled': free and bool(emulator)},
                            'refresh': {'enabled': ready and not f['busy']}},
                'hint': 'Switches take effect when you press Patch.' if any(picked.values())
                else 'Every switch is off: Patch puts in only the Overtime server.',
                'game': {
                    'folder': c.game_dir, 'overlay': overlay.overlay_dir(c.game_dir) if c.game_dir else '',
                    'applied_at': f['applied_at'] or None,
                    'layers': chips(st, f['teams32']) if patched else [],
                    'files': {'count': len(files), 'bad': sum(1 for x in files if x['state'] != 'as written'),
                              'list': files},
                    'problems': f['problems'],
                    'verify': verify_text(verify, count) if verify else None,
                    'size': size_text(size),
                    'online': online,
                },
                'about': [{'head': h, 'items': list(items)} for h, items in ABOUT],
                'names': [{'what': w, 'from': a, 'to': b} for w, a, b in NAMES],
                'want': want,           # beta1's (re/scripts/oneclick_run.py reads it)
            }

    def files_view(self):
        c = self.ctl
        with c.lock:
            st = c.patch_status or {}
            if not self.listing or not st.get('applied'):
                return {'open': False}
            return {'open': True, 'list': self.file_list(st),
                    'overlay': overlay.overlay_dir(c.game_dir) if c.game_dir else ''}
