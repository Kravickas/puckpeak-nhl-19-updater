"""The game patch from the app's side (Patch tab, tools/game_patch.py): the data overlay (overtime_core.overlay) and
the default roster brought up to 2026-27 for its database layer.

The database layer is the game's own default roster (nhl_game.db) after the same update the Update tab makes:
NHL.com rosters, Utah, Seattle, ratings, lines and the real calendar. With it in the patch, every mode that starts
from the default roster sees the 2026-27 league without loading a custom roster, Seattle filled and active. Only the
expansion career's start roster (overlay.mode_roster_files: expansion_draft.db) has Seattle empty, so the expansion
draft builds the team; that career takes its free agents from this database, so Seattle's players are on its free
agent list too (rosterupdate.expansion_free_agents; other modes do not list a rostered player).

The art layer serves the art packs found (ART_PACKS: NHL 27's team art; built on the owner's PC by tools/build_looks.py,
never committed): switch ART_SWITCH. The packs (all-team logos / menus / centre ice, Utah's and Seattle's whole look, the 3D kits) are downloads
from the release host, never inside the exe; the 3D kits are a delta pack (KITS_PACK, switch `kits`; overtime_roster.
app.packdownload). NHL.com portraits (PHOTOS_PACK, built by tools/build_photopack.py) are keyed by the served bios'
art ids, and the overlay's database step sets each bio's portrait flag from the art served (art.portrait_flags).
NHL 27's other jerseys (the NHL's alternates, the national teams, the clubs) and the NHL kits' 2026 pants are made on
the player's PC at Patch from small layer packs and the game's own files (make_kits, overtime_core.kitcompose), as the
clubs' logos are (make_clubart, overtime_core.clubart): no game texture is downloaded for them.
"""
import os

from overtime_core import art, clubart, kitcompose, menus, overlay, photos, rosterupdate, teams

from . import sources, update
from .session import RosterSession


class PatchFailed(RuntimeError):
    pass


# Seattle's centre ice from its own logo (teams.seattle_center_ice, WS7's ice_centerlogo_10499_cm): off until WS7's
# runs show Seattle still in Play Now with it.
SEATTLE_CENTER_ICE = False


def updated_default(game, gathered, per32=None, log=lambda msg: None, seattle_ice=None):
    """(nhl_game.db bytes, update Report): the game's default roster after the whole update. `seattle_ice` (default
    SEATTLE_CENTER_ICE) adds Seattle's own centre ice."""
    session = RosterSession(game.default_db(), 'NHL 19 default roster')
    todo = update.plan(session.db, gathered)
    log(f'plan: {todo.summary()}')
    rep = update.run(session, game, gathered, todo, per32=per32, log=log, lines=True)
    rosterupdate.expansion_active(session.db)
    # the 32-team Franchise is the expansion career, which starts in the 2018 offseason and ends every deal in its
    # last season: one season more, so the deals after that offseason are 2026-27's (ws5 run6). A Franchise without
    # expansion (31 teams, starts in the preseason) gets every deal a season long: one database serves every mode.
    longer = rosterupdate.expansion_contracts(session.db)
    log(f'expansion career contracts: {longer} NHL deals one season longer')
    listed = rosterupdate.expansion_free_agents(session.db)
    log(f'expansion career free agents: {len(listed)} Seattle players listed (they stay on Seattle elsewhere)')
    dropped = teams.drop_throwbacks(session.db, game.schema())
    log(f"Utah's Coyotes throwbacks: {len(dropped)} jersey rows removed")
    kit = teams.seattle_kit(session.db, game.schema())
    log(f"Seattle's kit: {len(kit)} jersey rows on art {teams.SEATTLE_KIT_ART}")
    if SEATTLE_CENTER_ICE if seattle_ice is None else seattle_ice:
        log(f"Seattle's centre ice: {teams.seattle_center_ice(session.db)} team rows on its own logo")
    problems = rep.problems + [str(i) for i in session.verify(strict=True) if i.level == 'error']
    problems += rosterupdate.check(session.db, game.schema(), None, gathered.season)
    if problems:
        raise PatchFailed(f'the updated default roster has {len(problems)} problem(s): ' + '; '.join(problems[:10]))
    return session.db.to_bytes(), rep


DEFAULT_LAYERS = ('text', 'names', 'league', 'menus')
# The menus layer's switches (overlay `menus=` options), all off by default: the hub without the modes that have no
# server (Hockey Ultimate Team, Draft Champions, World of Chel). Its `news` option is no switch: the news tile stays
# and the text layer makes it the Puck Peak line.
MENU_SWITCHES = {'chel': 'Bring back World of Chel'}


def menu_options(game_dir, chel=None):
    """The menus layer's options: the ones served now (else the defaults), with `chel` set when given."""
    served = ((overlay.status(game_dir).get('layers') or {}).get('menus') or {}).get('options')
    return menus.options(None if chel is None else {'chel': chel}, served)


def layers_for(game_dir, want=None, database=False, no_database=False, art=False, no_art=False):
    """The layers to apply: `want` (default text + names + league + menus), plus the database layer when given
    now or already served (unless `no_database`), and the art layer the same way (`art`, `no_art`)."""
    out = list(want or DEFAULT_LAYERS)
    served = (overlay.status(game_dir).get('layers')) or {}
    for name, given, drop in (('database', database, no_database), ('art', art, no_art)):
        if (given or (name in served and want is None)) and not drop and name not in out:
            out.append(name)
        if drop and name in out:
            out.remove(name)
    return out


# The art layer's switch (Patch tab) and its packs, in the order they are laid over each other (a later one wins).
ART_SWITCH = {'art': 'NHL 27 team art: logos, menu jerseys and centre ice of all teams, Utah\'s and Seattle\'s kits and '
                     'Utah\'s arena', 'kits': 'NHL 27 3D kits of all teams (a download)'}
LOOKS32_PACK = 'looks32.zip'   # all teams: logos, menu jerseys, centre ice (a core download)
KITS_PACK = 'kits.zip'         # all teams' 3D kits, a delta pack on the game's own files (downloaded)
PHOTOS_PACK = 'photos.zip'     # NHL.com portraits, p<artid> of the default database's bios
PEOPLE_PACK = 'people.zip'     # the players of every league (tools/build_people.py): Update gives them these art ids
ICE_PACK = 'ice_all.zip'       # centre ice of every team NHL 27 has one for (build_looks --teams every), over looks32's
RINK_PACK = 'rink.zip'         # NHL 27 pucks, ice lines, board ads, league logos and the IIHF art (build_looks --parts rink,iihf), over ice_all
# NHL 27's jerseys beyond the NHL teams' main kits: the NHL's alternates, the national teams, the other leagues' clubs. A
# layer pack per family (overtime_core.kitcompose, tools/build_kitlayers.py: NHL 27's pictures in NHL 19's layout and a
# step per texture, no game file in it), downloaded with the family's switch (alts_<family>: the switch 0.30's whole
# alts_* packs had; those carried NHL 19's own normal maps and are no longer served). Patch makes the family's textures
# on this PC from the game's own files (make_kits) into the cache, served right after the kits pack.
KITLAYER_PACKS = {kitcompose.source_pack('nhl'): 'NHL alternate jerseys from NHL 27',
                  kitcompose.source_pack('intl'): 'National team jerseys from NHL 27',
                  kitcompose.source_pack('clubs'): 'AHL, ECHL, junior and European club jerseys from NHL 27'}
FAMILY_OF = {kitcompose.source_pack(f): f for f in kitcompose.FAMILIES}
# 0.30's whole jersey packs (only alts_intl was served): nothing reads them now, so Patch takes them out of the cache
OLD_ALT_PACKS = ('alts_nhl.zip', 'alts_intl.zip', 'alts_ahl.zip', 'alts_chl.zip', 'alts_euro.zip')
# the packs with a switch of their own (Game patch, More jerseys and ice): each downloads when it is switched on
EXTRA_PACKS = {ICE_PACK: 'Centre ice of the clubs of every league from NHL 27', RINK_PACK: 'IIHF centre ice and puck, NHL 27 pucks, board ads and league logos',
               **KITLAYER_PACKS}
ART_PACKS = (LOOKS32_PACK, ICE_PACK, RINK_PACK, KITS_PACK, PHOTOS_PACK, PEOPLE_PACK, 'looks.zip')   # looks.zip (Utah, Seattle: kits, arena) last: wins
# the photos the people pack lacks, drawn by Update on this PC (overtime_core.photos): only in the app's cache, no
# download, served with the photos; its art ids are the people pack's free ones, so no other pack's file is replaced
LOCAL_PEOPLE_PACK = photos.LOCAL_PACK
# the clubs' 2026 logos and centre ice (overtime_core.clubart): CLUBART_PACK is a download of source pictures, never
# served itself; Update makes the game's files of them on this PC into LOCAL_CLUBART_PACK, served last (it wins)
CLUBART_PACK = clubart.PACK
LOCAL_CLUBART_PACK = clubart.LOCAL_PACK
ART_ENV = 'OVERTIME_ART_PACKS'  # a folder with the packs, or `off`


def art_places(cache_dir=None):
    """Folders an art pack may be in, first wins: the app's cache folder, the exe's own packs, the repository's packs/
    (a source run). OVERTIME_ART_PACKS names the only folder instead ('off': none)."""
    env = os.environ.get(ART_ENV)
    if env == 'off':
        return []
    if env:
        return [env]
    out = []
    if cache_dir:
        out.append(cache_dir)
    return out + [sources.BUILD_PACKS, sources.REPO_PACKS]


def art_found(cache_dir=None):
    """Names of the art packs present (ART_PACKS order, then the jersey layer packs), without loading them: for the Patch
    tab's switches."""
    return [name for name in (*ART_PACKS, *KITLAYER_PACKS)
            if any(os.path.isfile(os.path.join(f, name)) for f in art_places(cache_dir))]


def extra_key(name):
    """The switch of an EXTRA_PACKS pack: its name without .zip; a jersey layer pack's, its family's (alts_<family>)."""
    return kitcompose.switch(FAMILY_OF[name]) if name in FAMILY_OF else name[:-4]


def art_packs(cache_dir=None, game_dir=None, kits=True, photos=True, extras=None):
    """[art.Pack] of every art pack found (ART_PACKS order; the kits pack only with `kits`, and read against
    `game_dir`, its deltas' bases; the photos pack only with `photos`; of EXTRA_PACKS only `extras`, all when None); a
    pack that does not load is skipped with its error in the second list. A
    photos.zip outside the cache that is made for another default roster (packdownload's `wrong_roster`) is skipped
    the same way and the next folder's is used: its portraits would land on other players (the cache's own is
    checked when it is downloaded)."""
    from . import packdownload  # it imports this module
    packs, problems = [], []

    def add(path):
        try:
            packs.append(art.load_pack(path, game_dir))
        except art.ArtError as err:
            problems.append(str(err))
    # the jerseys made on this PC (make_kits): the NHL kits' pants with `kits`, the families switched on
    made = [local_kits(cache_dir, f) for f in (['pants'] if kits else []) +
            [f for f in kitcompose.FAMILIES if extras is None or kitcompose.source_pack(f) in extras]]
    for name in ART_PACKS:
        skip = (name == KITS_PACK and not kits) or (name in (PHOTOS_PACK, PEOPLE_PACK) and not photos) or \
            (name in EXTRA_PACKS and extras is not None and name not in extras)
        for folder in [] if skip else art_places(cache_dir):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and name == PHOTOS_PACK and folder != cache_dir and \
                    packdownload.photos_fit(path, game_dir)['fits'] is False:
                problems.append(f'{path} is made for another roster: not used')
                continue
            if os.path.isfile(path):
                add(path)
                break
        if name == KITS_PACK:
            for path in filter(None, made):
                add(path)
    local = local_people(cache_dir) if photos else None
    for path in (local, local_clubart(cache_dir)):     # the people's files are in no other pack; the clubs' come last:
        if path:                                        # they win over looks32's and ice_all's of the same art id
            add(path)
    return packs, problems


def people_rows(cache_dir=None, game_dir=None):
    """The `people` rows of the people pack the patch would serve (the first found), [] without one: who has a photo
    there, so Update draws only the others."""
    path = next((p for p in (os.path.join(f, PEOPLE_PACK) for f in art_places(cache_dir)) if os.path.isfile(p)), None)
    try:
        return (art.load_pack(path, game_dir).info.get('people') or []) if path else []
    except art.ArtError:
        return []


def local_people(cache_dir=None):
    """Path of the photos Update drew on this PC (LOCAL_PEOPLE_PACK), None when there is none or the art packs come from
    OVERTIME_ART_PACKS alone (the cache is then not read)."""
    if not cache_dir or cache_dir not in art_places(cache_dir):
        return None
    path = os.path.join(cache_dir, LOCAL_PEOPLE_PACK)
    return path if os.path.isfile(path) else None


def local_clubart(cache_dir=None):
    """Path of the club logos and centre ice Update made on this PC (LOCAL_CLUBART_PACK), None as local_people."""
    if not cache_dir or cache_dir not in art_places(cache_dir):
        return None
    path = os.path.join(cache_dir, LOCAL_CLUBART_PACK)
    return path if os.path.isfile(path) else None


def local_kits(cache_dir, family):
    """Path of a jersey family's textures Patch made on this PC (make_kits; family 'pants': the NHL kits' pants), None
    as local_people."""
    if not cache_dir or cache_dir not in art_places(cache_dir):
        return None
    path = os.path.join(cache_dir, kitcompose.PANTS_LOCAL if family == 'pants' else kitcompose.local_pack(family))
    return path if os.path.isfile(path) else None


def make_kits(want, game_dir, cache_dir, log=None, step=None):
    """Make the jerseys of the families switched on in `want` (alts_<family>) from their layer packs, and the NHL kits'
    pants with `kits`, into the cache (kitcompose.compose; the same pack and game as the last time: kept), for art_packs
    to serve. The textures of a family switched off, or whose layer pack is not here, are removed from the cache (the
    clubs' take about 3 GB; switched on again, the next Patch makes them again from the layer pack kept on this PC).
    0.30's whole packs (OLD_ALT_PACKS) are removed from the cache. Never raises: {family: counts}; a family that fails
    is logged and left out."""
    say = log or (lambda m: None)
    if not cache_dir or cache_dir not in art_places(cache_dir):
        return {}
    for old in OLD_ALT_PACKS:
        if os.path.isfile(os.path.join(cache_dir, old)):
            try:
                os.remove(os.path.join(cache_dir, old))
                say(f'jerseys: {old} of 0.30 removed (the jerseys are made on this PC now)')
            except OSError as err:
                say(f'jerseys: {old} of 0.30 stays ({err})')
    if not want.get('art', True):
        return {}
    jobs = [('pants', kitcompose.PANTS_LOCAL, kitcompose.PANTS_KIT, kitcompose.Pants)] if want.get('kits', True) else []
    for fam in kitcompose.FAMILIES:
        name = kitcompose.source_pack(fam)
        path = next((p for p in (os.path.join(f, name) for f in art_places(cache_dir)) if os.path.isfile(p)), None)
        if want.get(kitcompose.switch(fam)) and path:
            jobs.append((fam, kitcompose.local_pack(fam), kitcompose.served_name(fam),
                         lambda path=path: kitcompose.Source(path)))
        elif os.path.isfile(os.path.join(cache_dir, kitcompose.local_pack(fam))):
            try:
                os.remove(os.path.join(cache_dir, kitcompose.local_pack(fam)))
                say(f'jerseys ({fam}): switched off, the textures made on this PC are removed')
            except OSError as err:
                say(f'jerseys ({fam}): switched off, the textures made on this PC stay ({err})')
    out = {}
    for fam, local, served, source in jobs:
        progress = None
        if step and fam != 'pants':     # the first time a family takes minutes (the clubs' the most): said every 5 %
            title, shown = KITLAYER_PACKS[kitcompose.source_pack(fam)], []

            def progress(share, title=title, shown=shown):
                pct = int(share * 20) * 5
                if not shown or shown[-1] != pct:
                    shown.append(pct)
                    step(f'making the jerseys on this PC: {title}, {pct} %...')
            progress(0)
        try:
            out[fam] = kitcompose.compose(source(), game_dir, os.path.join(cache_dir, local), served, log=say,
                                          progress=progress)
        except Exception as err:  # noqa: BLE001 - a jersey never stops a patch
            say(f'jerseys ({fam}): not made ({err})')
            continue
        c = out[fam]
        say(f"jerseys ({fam}): {'kept' if c['kept'] else 'made'} {c['files']} textures"
            + (f", {c['failed']} failed" if c['failed'] else ''))
    return out


def clubart_source(cache_dir=None):
    """Path of the club art source pack (CLUBART_PACK) where it was found first (art_places), or None."""
    return next((p for p in (os.path.join(f, CLUBART_PACK) for f in art_places(cache_dir)) if os.path.isfile(p)), None)


def make_clubart(teams, game_dir, cache_dir, log=None):
    """Make the clubs' 2026 logos and centre ice of a roster's team rows `teams` (db[teams.TEAMS].rows()) into the
    cache's LOCAL_CLUBART_PACK (clubart.compose), which the next Patch serves. Update calls it after a save, Patch with
    the default roster it serves (both come from the same Update data). Never raises: clubart.compose's counts, or None
    without the club art pack, the cache, or when it fails (logged)."""
    path = clubart_source(cache_dir)
    if not path or not cache_dir:
        return None
    try:
        return clubart.compose(clubart.Source(path), teams, game_dir, os.path.join(cache_dir, LOCAL_CLUBART_PACK),
                               log=log)
    except Exception as err:  # noqa: BLE001 - a logo never stops an update or a patch
        if log:
            log(f'club logos: not made ({err})')
        return None


def served_portraits(game_dir, cache_dir=None):
    """(game paths of the player photos the applied patch serves, the people packs' `people`): what Update needs to give
    a saved roster its photos (art.player_portraits, art.portrait_flags). Nothing without the patch's art. The photos
    drawn on this PC count only as the patch served them (the same pack, by its sha256: Update draws new ones after this
    is read, and they count once Patch has put them in), and never for a person the people pack has."""
    records = ((overlay.status(game_dir).get('layers') or {}).get('art') or {}).get('packs') or ()
    served = {p.get('name') for p in records}
    files, people = set(), []
    for name in (PHOTOS_PACK, PEOPLE_PACK):
        path = next((p for p in (os.path.join(f, name) for f in art_places(cache_dir)) if os.path.isfile(p)), None)
        try:
            pack = art.load_pack(path, game_dir) if path else None
        except art.ArtError:
            pack = None
        if pack is not None and pack.name in served:
            files |= set(pack.files)
            people += pack.info.get('people') or []
    local = local_people(cache_dir)
    try:
        pack = art.load_pack(local, game_dir) if local else None
    except art.ArtError:
        pack = None
    if pack is not None and {'name': pack.name, 'sha256': pack.sha256} in \
            [{'name': p.get('name'), 'sha256': p.get('sha256')} for p in records]:
        have = {tuple(r[:4]) for r in people}
        files |= set(pack.files)
        people += [r for r in pack.info.get('people') or [] if tuple(r[:4]) not in have]
    return files, people


def art_layer(want, layers, cache_dir=None, log=None, game_dir=None):
    """Sets the art layer in `layers` from the ART_SWITCH in `want` (on by default) and returns the packs to pass as
    overlay.apply(art=...): switched off, the layer leaves `layers` (Apply then takes its archives away); on with packs
    found, it is added with them (the kits and photos packs only with their switches); on without packs, a served art layer stays as it is (None: overlay keeps it)."""
    if not want.get('art', True):
        if 'art' in layers:
            layers.remove('art')
        return None
    packs, problems = art_packs(cache_dir, game_dir, kits=want.get('kits', True), photos=want.get('photos', True),
                                extras=[name for name in EXTRA_PACKS if want.get(extra_key(name))])
    for problem in problems:
        if log:
            log(f'art pack skipped: {problem}')
    if not packs:
        return None
    if 'art' not in layers:
        layers.append('art')
    return packs
