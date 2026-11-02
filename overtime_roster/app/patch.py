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
"""
import os

from overtime_core import art, menus, overlay, rosterupdate, teams

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
    rep = update.run(session, game, gathered, todo, per32=per32, log=log)
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
ICE_PACK = 'ice_all.zip'       # centre ice of every team NHL 27 has one for (build_looks --teams every), over looks32's
# NHL 27 main and alternate kits of the other leagues' clubs and the NHL's alternates (tools/build_alts.py), one downloadable
# pack per league family; they win over the game's own kit files
ALT_PACKS = {'alts_nhl.zip': 'NHL alternate jerseys from NHL 27', 'alts_ahl.zip': 'AHL and ECHL jerseys from NHL 27',
             'alts_chl.zip': 'OHL, QMJHL and WHL jerseys from NHL 27',
             'alts_euro.zip': 'European league jerseys from NHL 27',
             'alts_intl.zip': 'National team jerseys from NHL 27'}
INTL_PACK = 'alts_intl.zip'
NHL_ALTS_PACK = 'alts_nhl.zip'
# the packs with a switch of their own (Game patch, More jerseys and ice): each downloads when it is switched on. The
# other jersey packs are built, but left out of 0.30.0: too much data to serve for now (PLAN.md)
EXTRA_PACKS = {ICE_PACK: 'Centre ice for every league from NHL 27', INTL_PACK: ALT_PACKS[INTL_PACK],
               NHL_ALTS_PACK: ALT_PACKS[NHL_ALTS_PACK]}
ART_PACKS = (LOOKS32_PACK, ICE_PACK, KITS_PACK, NHL_ALTS_PACK, INTL_PACK, PHOTOS_PACK, 'looks.zip')   # looks.zip (Utah, Seattle: kits, arena) last: wins
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
    """Names of the art packs present (ART_PACKS order), without loading them: for the Patch tab's switch."""
    return [name for name in ART_PACKS if any(os.path.isfile(os.path.join(f, name)) for f in art_places(cache_dir))]


def extra_key(name):
    """The switch of an EXTRA_PACKS pack: its name without .zip."""
    return name[:-4]


def art_packs(cache_dir=None, game_dir=None, kits=True, photos=True, extras=None):
    """[art.Pack] of every art pack found (ART_PACKS order; the kits pack only with `kits`, and read against
    `game_dir`, its deltas' bases; the photos pack only with `photos`; of EXTRA_PACKS only `extras`, all when None); a
    pack that does not load is skipped with its error in the second list. A
    photos.zip outside the cache that is made for another default roster (packdownload's `wrong_roster`) is skipped
    the same way and the next folder's is used: its portraits would land on other players (the cache's own is
    checked when it is downloaded)."""
    from . import packdownload  # it imports this module
    packs, problems = [], []
    for name in ART_PACKS:
        if (name == KITS_PACK and not kits) or (name == PHOTOS_PACK and not photos):
            continue
        if name in EXTRA_PACKS and extras is not None and name not in extras:
            continue
        for folder in art_places(cache_dir):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and name == PHOTOS_PACK and folder != cache_dir and \
                    packdownload.photos_fit(path, game_dir)['fits'] is False:
                problems.append(f'{path} is made for another roster: not used')
                continue
            if os.path.isfile(path):
                try:
                    packs.append(art.load_pack(path, game_dir))
                except art.ArtError as err:
                    problems.append(str(err))
                break
    return packs, problems


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
