"""The hub without the modes that died with EA's servers: Hockey Ultimate Team, Draft Champions and World of Chel;
the news tile shows the Puck Peak line (or goes, with `news` off). The overlay's menus layer (overtime_core.overlay)
serves boot.big with these two files changed:

  homepage.lua     ProcessHomepageTilesData builds self.MODES (every hub tile, l.~900-1243), then the grid and the
                   pinned row from it. Right before that, the three modes leave self.MODES (and the featured-tile
                   list), so neither the grid nor the pinned row nor the featured tile can show them. The grid is
                   6 columns x 3 rows in self.MODES order (row by row), and the three are exactly its ONLINE column,
                   so with them gone it is 5 columns with every other tile under its own title. The ONLINE title
                   leaves o.TITLES the same way. With World of Chel on (`chel`), its tile takes the EA SPORTS ad
                   tile's place (EXTRAS, last row) instead.
                   The featured tile is looked up by FeatureId in self.MODES; a featured mode that is gone would
                   index self.MODES[-1] (a Lua error), so the first tile (Play Now) is featured instead.
                   The pinned row's last tile is the news tile (IDENTIFIER.DYNAMIC_MESSAGE: EA's dynamic messages,
                   without a server the default TXT_DEFAULT_MESSAGE_HOME_1, which the text pack makes the Puck Peak
                   line "Updates, patches, statistics! Join us on gg.puckpeak.com"). It stays (`news`, on by
                   default, owner 2026-10-23). With `news` off its place becomes an EMPTY tile: the row keeps its 5
                   positions (pin, unpin and the featured tile work by position) and the cursor skips EMPTY.
  homepage.layout  the grid's PositionItemsInGrid numSections 6 -> 5.

Zero-press launch (`launch`, docs/plans/m2-zero-press.md): not an option, never served or recorded as one. With
`{'until': <unix seconds>}` the two files above gain one hook each and hub.lua is served too:

  homepage.lua     at the end of ProcessHomepageTilesData, once per process, while os.time() <= until: the Online Versus
                   tile's own nav event (what `_OnAdvanceAction` sends), flag `_G.OvertimeAutoplay = 'home'`.
  hub.lua          (online hub) at the end of Hub:PublishData, when the hub is the Online Versus one and both data
                   sources are in and the flag is 'home': `_OnAdvance(PLAYNOW_ONLINE)` (PLAY), flag 'hub'.
  Threes: the homepage hook jumps with the Threes tile's event (evt_3_on_3) into NHL Threes' own hub (3on3 hub.lua),
                   whose hook, at the end of Hub:new, picks Online once (`_OnOnlineSelection`, which sets the game type and
                   sends evt_online); that leads to the shared online hub in its MODE_3ON3ONLINE, where the hook above
                   presses PLAY.
`{'rules': {...}}` (overtime_core.rules; only with a launch) also serves the Online Versus rules file with those rules'
`defaultvalue`s set, so the game searches with them (docs/plans/m3b-match-settings.md). It goes off with the hook.
Every hook body is a pcall: a Lua error (an `os` that is not reachable, a missing global) leaves the screen as it was,
and a stale hook (the window passed) does nothing. `diag` writes the clock and the flag into the grid's last column
title (a lab aid: it shows whether `os.time()` works and which clock it reads).

Nothing here knows offsets: each edit has an anchor that must be in the player's own file exactly once, and a
file that does not look as expected is refused (MenuError). Line ends stay CRLF. Modes are never removed on the
server's side (the hub crashes without them, docs/notes/hub-config.md).
"""
from . import rules

HOMEPAGE_PATH = 'nhl/ui/features/homepage/vvms/homepage.lua'
LAYOUT_PATH = 'nhl/ui/features/homepage/vvms/homepage.layout'
HUB_PATH = 'nhl/ui/features/online/vvms/hub/hub.lua'
THREES_HUB_PATH = 'nhl/ui/features/3on3/vvms/hub/hub.lua'   # NHL Threes' own hub: Offline / Campaign / Online
PATHS = (HOMEPAGE_PATH, LAYOUT_PATH)
LAUNCH_PATHS = PATHS + (HUB_PATH, THREES_HUB_PATH) + tuple(rules.PATHS.values())   # what a launch (set_menus) adds, and a clear takes off again

DEAD = ('ULTIMATETEAM', 'HOCKEYDRAFT', 'EASHL')  # MODES_NAMES keys: Hockey Ultimate Team, Draft Champions, WOC
OPTIONS = {'chel': False, 'news': True, 'hut': False}
# chel = bring back World of Chel; news = keep the news tile (Puck Peak); hut = keep the Hockey Ultimate Team tile (the
# server's CardHouse is scaffolding only, docs/notes/hut.md; no switch in the app, set with overlay `menus={'hut': True}`)
SERVED_DEAD = {'EASHL': 'chel', 'ULTIMATETEAM': 'hut'}   # the dead modes an option brings back


def hidden_keys(opts):
    """The MODES_NAMES keys the options leave hidden."""
    return [k for k in DEAD if not opts.get(SERVED_DEAD.get(k))]
MARK = b'Overtime menus'


class MenuError(ValueError):
    pass


# self.MODES is complete here; the grid and the pinned row are built right after.
MODES_ANCHOR = (b'    local auxList = {}\r\n'
                b'    local auxList2 = {}\r\n'
                b'    local featureModeIndex = -1\r\n')
FEATURED_ANCHOR = b'    local featureTileAuxData = TableUtil.clone(self.MODES[featureModeIndex].data)\r\n'
NEWS_ANCHOR = (b'    table.insert(auxList2,{identifier = IDENTIFIER.DYNAMIC_MESSAGE , '
               b'data = {id = 16 , isFeatured = FEATURED.REGULAR}})\r\n')
TITLES_ANCHOR = (b'        {  Text = o.loc.LocalizeString("TXT_EXTRAS", { case = "upper"}        ) }\r\n'
                 b'    }\r\n')
ONLINE_TITLE = b'        {  Text = o.loc.LocalizeString("OSDK_OL_COL_ONLINE", { case = "upper"}  ) },\r\n'
GRID_ANCHOR = b'"numSections": 6,\r\n'
# The stock file's shape around the anchors: the modes and the identifiers the Lua below names.
STOCK = (b'function HomePage:ProcessHomepageTilesData()', b'    ULTIMATETEAM                = "UltimateTeam",',
         b'    HOCKEYDRAFT                 = "HockeyDraft",', b'    EASHL                       = "Eashl",',
         b'    DYNAMIC_MESSAGE             = "DYNAMIC_MESSAGE",', b'    EMPTY                       = "EMPTY"',
         ONLINE_TITLE)


def _once(raw, anchor, path):
    n = raw.count(anchor)
    if n != 1:
        raise MenuError(f'{path}: anchor {anchor[:60]!r} found {n} times, expected once')


def _filter(chel, hut=False):
    gone = hidden_keys({'chel': chel, 'hut': hut})
    hidden = ', '.join(f'[MODES_NAMES.{k}] = true' for k in gone)
    lines = [
        '    -- Overtime menus: Hockey Ultimate Team, Draft Champions and World of Chel have no server. They leave',
        '    -- the hub (grid, pinned row, featured tile) with the grid\'s ONLINE column, which is exactly them.',
        f'    local overtimeHidden = {{ {hidden} }}',
        '    local overtimeChel = nil',
        '    for i = #self.MODES, 1, -1 do',
        '        local mode = self.MODES[i]',
        '        if mode.modeName ~= nil and overtimeHidden[mode.modeName] == true then',
        '            if mode.featureId ~= nil then self.mFeaturedListId[mode.featureId] = nil end',
        '            table.remove(self.MODES, i)',
        '        elseif mode.modeName == MODES_NAMES.EASHL then',
        '            overtimeChel = table.remove(self.MODES, i)',
        '        end',
        '    end',
        '    if overtimeChel ~= nil then',
        '        -- World of Chel switched on: its tile takes the EA SPORTS ad tile\'s place (EXTRAS, last row)',
        '        local at = #self.MODES + 1',
        '        for i = 1, #self.MODES do',
        '            if self.MODES[i].identifier == IDENTIFIER.DYNAMIC_MESSAGE then at = i end',
        '        end',
        '        self.MODES[at] = overtimeChel',
        '    end',
        '']
    return '\r\n'.join(lines).encode('ascii')


FEATURED_GUARD = (b'    -- Overtime menus: a featured mode that left the hub gives its place to the first tile (Play Now)\r\n'
                  b'    if featureModeIndex == -1 then\r\n'
                  b'        featureModeIndex = 1\r\n'
                  b'        self.mFeaturedTileId = self.MODES[1].featureId\r\n'
                  b'    end\r\n')
NEWS_EMPTY = (b'    -- Overtime menus: no news tile (EA\'s news service is gone); the row keeps its 5 positions\r\n'
              b'    table.insert(auxList2,{identifier = IDENTIFIER.EMPTY})\r\n')
TITLES_DROP = (b'    -- Overtime menus: the ONLINE column left the hub\r\n'
               b'    table.remove(o.TITLES, 3)\r\n'
               b'    table.insert(o.TITLES, { Text = "" })\r\n')


HOME_END_ANCHOR = (b'    self:_PublishIsTutorialAvailable()\r\nend\r\n\r\n'
                   b'function HomePage:_CheckPreviousPinnedListActionState()\r\n')
HUB_END_ANCHOR = b'    self.im.Publish(BINDINGS.BUTTONS_FONT_STYLE, self.mButtonsState)\r\nend\r\n'
HUB_STOCK = (b'function Hub:PublishData()', b'MODE_SHOOTOUT_ONLINE', b'function Hub:_OnAdvance(evt)')
HUB_MODE = 'MODE_PLAY_NOW_ONLINE_QUICKMATCH'  # gameMode of the Online Versus hub (playonline.nav, OnlineHub)
HUB_MODES = {rules.VERSUS: HUB_MODE, rules.SHOOTOUT: 'MODE_SHOOTOUT_ONLINE',   # ... and of the Online Shootout hub
             rules.THREES: 'MODE_3ON3ONLINE'}                                   # ... and of the Online Threes one
# The homepage tile's nav event per game: Versus' own (what _OnAdvanceAction sends), and the one the Shootout tile's
# Offline / Online popup sends for its Online choice (_ShootoutPopUpCallBack, EVENTS.GOTO_ONLINE_SHOOTOUT).
# NHL Threes' tile sends evt_3_on_3 (homepage.nav -> out_3_on_3 -> the 3on3 nav, docs/notes/threes-otp.md).
HOME_EVENTS = {rules.VERSUS: 'evt_playonline', rules.SHOOTOUT: 'evt_goto_online_shootout', rules.THREES: 'evt_3_on_3'}
THREES_HUB_ANCHOR = (b'    o:_RegisterActions()\r\n'
                     b'    return o\r\n'
                     b'end\r\n')
THREES_HUB_STOCK = (b'function Hub:_OnOnlineSelection()', b'local ONLINE_GAME_TYPE = "PLAYNOW_ONLINE_PERIODS"',
                    b'ACTIONS.ONLINE')


def _lines(*lines):
    return ('\r\n'.join(lines) + '\r\n').encode('ascii')


def home_hook(until, mode=rules.VERSUS):
    return _lines(
        '    -- Overtime autoplay: one jump into Online %s per launch, while the clock is before the window ends' % mode.title(),
        '    pcall(function()',
        f'        if _G.OvertimeAutoplay == nil and os.time() <= {int(until)} then',
        "            _G.OvertimeAutoplay = 'home'",
        '            self.nav.Event(nil, AvatarEnum.EVENTS.CHANGE_AVATAR_STATE, { state = AvatarEnum.STATES.DISABLE_AVATAR_INPUT })',
        '            self.nav.Event(nil, EVENTS.CHECK_MOVIE_ELIGIBILITY, { controllerid = 0, LinkTarget = nil, movieType = nil,',
        '                                                                   afterMovieTarget = "%s" })' % HOME_EVENTS[mode],
        '        end',
        '    end)')


def hub_hook(until, mode=rules.VERSUS):
    return _lines(
        '    -- Overtime autoplay: the Online %s hub presses PLAY once, right after the homepage jumped here' % mode.title(),
        '    pcall(function()',
        f"        if _G.OvertimeAutoplay == 'home' and self.mGameMode == GAMEMODES.{HUB_MODES[mode]} and os.time() <= {int(until)}",
        '           and self.mData.RankedQuickMatch ~= nil and self.mData.PlayersOnline ~= nil then',
        "            _G.OvertimeAutoplay = 'hub'",
        '            self:_OnAdvance(EVENTS.PLAYNOW_ONLINE)',
        '        end',
        '    end)')


def threes_hub_hook(until):
    return _lines(
        '    -- Overtime autoplay: the NHL Threes hub picks Online once, right after the homepage jumped here',
        '    pcall(function()',
        f"        if _G.OvertimeAutoplay == 'home' and _G.OvertimeThreesHub == nil and os.time() <= {int(until)} then",
        '            _G.OvertimeThreesHub = true',
        '            o:_OnOnlineSelection()',
        '        end',
        '    end)')


def edit_threes_hub(raw, until):
    """The Threes hub.lua with the Online hook at the end of Hub:new."""
    path = THREES_HUB_PATH
    if MARK in raw:
        raise MenuError(f'{path} is already edited')
    if raw.count(b'\r\n') != raw.count(b'\n'):
        raise MenuError(f'{path} does not have CRLF line ends')
    missing = [x for x in THREES_HUB_STOCK if raw.count(x) < 1]
    if missing:
        raise MenuError(f'{path} is not the Threes hub.lua this patch knows ({missing[0][:60]!r})')
    _once(raw, THREES_HUB_ANCHOR, path)
    tail = b'    return o' + b'\r\n' + b'end' + b'\r\n'
    new = THREES_HUB_ANCHOR[:-len(tail)] + threes_hub_hook(until) + tail
    return raw.replace(THREES_HUB_ANCHOR, new)


DIAG_TITLE = _lines(
    '    -- Overtime autoplay (diagnostic): the clock and the flag, in the last column title',
    '    do',
    "        local ok, text = pcall(function() return 'os.time ' .. tostring(os.time()) .. ' flag ' .. tostring(_G.OvertimeAutoplay) end)",
    "        o.TITLES[#o.TITLES].Text = ok and text or ('ERR ' .. tostring(text))",
    '    end')


def edit_hub(raw, until, mode=rules.VERSUS):
    """hub.lua with the PLAY hook (of `mode`'s hub) at the end of Hub:PublishData."""
    path = HUB_PATH
    if MARK in raw:
        raise MenuError(f'{path} is already edited')
    if raw.count(b'\r\n') != raw.count(b'\n'):
        raise MenuError(f'{path} does not have CRLF line ends')
    missing = [x for x in HUB_STOCK if raw.count(x) < 1]
    if missing:
        raise MenuError(f'{path} is not the hub.lua this patch knows ({missing[0][:60]!r})')
    _once(raw, HUB_END_ANCHOR, path)
    new = HUB_END_ANCHOR[:-len(b'end\r\n')] + hub_hook(until, mode) + b'end\r\n'
    return raw.replace(HUB_END_ANCHOR, new)


def edit_homepage(raw, chel=False, news=False, launch=None, hut=False):
    """homepage.lua without the dead modes (World of Chel kept when `chel`) and, unless `news`, the news tile; with
    `launch` ({'until', 'diag'}) the autoplay hook (and the diagnostic title)."""
    path = HOMEPAGE_PATH
    if MARK in raw:
        raise MenuError(f'{path} is already edited')
    if raw.count(b'\r\n') != raw.count(b'\n'):
        raise MenuError(f'{path} does not have CRLF line ends')
    missing = [s for s in STOCK if raw.count(s) != 1]
    if missing:
        raise MenuError(f'{path} is not the homepage.lua this patch knows ({missing[0][:60]!r})')
    edits = [(MODES_ANCHOR, _filter(chel, hut) + MODES_ANCHOR), (FEATURED_ANCHOR, FEATURED_GUARD + FEATURED_ANCHOR),
             (TITLES_ANCHOR, TITLES_ANCHOR + TITLES_DROP)]
    if not news:
        edits.append((NEWS_ANCHOR, NEWS_EMPTY))
    if launch:
        edits.append((HOME_END_ANCHOR,
                      HOME_END_ANCHOR.replace(b'end\r\n', home_hook(launch['until'], launch_mode(launch)) + b'end\r\n', 1)))
        if launch.get('diag'):
            edits[2] = (TITLES_ANCHOR, TITLES_ANCHOR + TITLES_DROP + DIAG_TITLE)
    for anchor, _new in edits:
        _once(raw, anchor, path)
    if raw.find(TITLES_ANCHOR) > raw.find(b'function HomePage:ProcessHomepageTilesData()') or \
            not raw.find(MODES_ANCHOR) < raw.find(FEATURED_ANCHOR) < raw.find(NEWS_ANCHOR):
        raise MenuError(f'{path}: the anchors are not in the order this patch knows')
    out = raw
    for anchor, new in edits:
        out = out.replace(anchor, new)
    if out.count(b'\r\n') != out.count(b'\n'):
        raise MenuError(f'{path}: the edit broke the line ends')
    return out


def edit_layout(raw):
    """homepage.layout with the grid at 5 columns."""
    path = LAYOUT_PATH
    if raw.count(b'\r\n') != raw.count(b'\n'):
        raise MenuError(f'{path} does not have CRLF line ends')
    _once(raw, GRID_ANCHOR, path)
    if raw.count(b'"PositionItemsInGrid"') != 1 or raw.find(b'"PositionItemsInGrid"') > raw.find(GRID_ANCHOR):
        raise MenuError(f'{path} is not the homepage.layout this patch knows')
    return raw.replace(GRID_ANCHOR, b'"numSections": 5,\r\n')


def options(given=None, served=None):
    """The layer's options: the defaults, then the ones served now, then `given` (unknown keys are refused)."""
    out = dict(OPTIONS)
    for src in (served or {}), (given or {}):
        unknown = set(src) - set(OPTIONS)
        if unknown:
            raise MenuError(f'unknown menus option(s): {", ".join(sorted(unknown))}')
        out.update({k: bool(v) for k, v in src.items()})
    return out


def launch_mode(launch):
    """The game a launch jumps into: 'versus' (the default), 'shootout' or 'threes'."""
    mode = (launch or {}).get('mode') or rules.VERSUS
    if mode not in HUB_MODES:
        raise MenuError(f'unknown game mode: {str(mode)[:20]}')
    return mode


def edits(read, opts, launch=None):
    """{path: new bytes} for the two files, plus hub.lua with `launch` ({'until': unix seconds, 'diag': bool, 'mode':
    versus|shootout, 'rules': {rule: value}}) and that mode's rules file when it names rules; `read(path)` gives the
    game's own bytes."""
    out = {HOMEPAGE_PATH: edit_homepage(read(HOMEPAGE_PATH), chel=opts['chel'], news=opts['news'], launch=launch, hut=opts['hut']),
           LAYOUT_PATH: edit_layout(read(LAYOUT_PATH))}
    if launch:
        mode = launch_mode(launch)
        out[HUB_PATH] = edit_hub(read(HUB_PATH), launch['until'], mode)
        if mode == rules.THREES:
            out[THREES_HUB_PATH] = edit_threes_hub(read(THREES_HUB_PATH), launch['until'])
        if launch.get('rules'):
            try:
                out[rules.path(mode)] = rules.edit(read(rules.path(mode)), launch['rules'], mode)
            except rules.RulesError as err:
                raise MenuError(str(err)) from err
    return out


def record(opts, launch=None):
    """The layer's record in the patch state file. A launch hook is recorded as `autoplay_until`, outside `options`
    (options are what a re-apply keeps; the hook is never kept)."""
    rec = {'options': dict(opts), 'hidden': hidden_keys(opts),
           'news': bool(opts['news']), 'grid_columns': 5}
    if launch:
        rec['autoplay_until'] = int(launch['until'])
        rec['autoplay_mode'] = launch_mode(launch)
        if launch.get('rules'):
            rec['rules'] = rules.validate(launch['rules'], partial=True, mode=launch_mode(launch))
    return rec
