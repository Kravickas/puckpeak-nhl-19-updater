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
# World of Chel's PLAY menu (Pro-Am / Ones / Drop-in Threes / EASHL tiles, docs/notes/woc-menus.md). Pro-Am's challenge
# room stalls on CHOOSE A POSITION (docs/notes/woc.md, lab p28-p32, q1-q2), so its tile leaves the menu.
PLAYNOW_PATH = 'nhl/ui/features/resort/vvms/playnowmenu/playnowmenu.lua'
PLAYNOW_LAYOUT_PATH = 'nhl/ui/features/resort/vvms/playnowmenu/playnowmenu.layout'
# World of Chel's hub, the EASHL menu (Drop-in / Online Seasons) and the Drop-in hub (6s / 3s): the CHEL auto-walk
MAINHUB_PATH = 'nhl/ui/features/resort/vvms/mainhub/mainhub.lua'
EASHLMENU_PATH = 'nhl/ui/features/resort/vvms/playnowmenu/eashlmenu.lua'
DROPINHUB_PATH = 'nhl/ui/features/resort/vvms/dropin/hub/dropinhub.lua'
GAUNTLETHUB_PATH = 'nhl/ui/features/resort/vvms/gauntlet/hub/gauntlethub.lua'   # Ones' hub (PLAY NOW, LEADERBOARDS)
DRESSINGROOM_PATH = 'nhl/ui/features/eashl/vvms/dressingroomflow/dressingroomflow.lua'   # 0.97.0 auto-ready (NULL GPU)
EASHLMENU_LAYOUT_PATH = 'nhl/ui/features/resort/vvms/playnowmenu/eashlmenu.layout'
PLAYNOW_DD_PATH = 'nhl/ui/features/resort/vvms/playnowmenu/playnowmenu.dd'
PATHS = (HOMEPAGE_PATH, LAYOUT_PATH, PLAYNOW_PATH, PLAYNOW_LAYOUT_PATH, PLAYNOW_DD_PATH, EASHLMENU_PATH,
         EASHLMENU_LAYOUT_PATH, DROPINHUB_PATH)
CHEL_WALK_PATHS = (MAINHUB_PATH, EASHLMENU_PATH, DROPINHUB_PATH, GAUNTLETHUB_PATH, DRESSINGROOM_PATH)
LAUNCH_PATHS = tuple(dict.fromkeys(PATHS + (HUB_PATH, THREES_HUB_PATH) + CHEL_WALK_PATHS
                                  + tuple(rules.PATHS.values())))   # what a launch (set_menus) adds, and a clear takes off again

DEAD = ('ULTIMATETEAM', 'HOCKEYDRAFT', 'EASHL')  # MODES_NAMES keys: Hockey Ultimate Team, Draft Champions, WOC
OPTIONS = {'chel': True, 'news': True, 'hut': False}
# chel = bring back World of Chel (on by default since v0.90.0, M5); news = keep the news tile (Puck Peak); hut = keep the Hockey Ultimate Team tile (the
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
HOME_EVENTS = {rules.VERSUS: 'evt_playonline', rules.SHOOTOUT: 'evt_goto_online_shootout', rules.THREES: 'evt_3_on_3',
               'chel': 'evt_eashl'}   # the World of Chel tile (TXT_EA_RESORT) -> homepage.nav out_eashl
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
        *(['            _G.OvertimeChelStep = 1'] if mode == CHEL_LAUNCH else []),
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


# The World of Chel auto-walk (0.96.0 Phase 4, docs/notes/woc.md "CHEL auto-walk"): the homepage jumps into World of
# Chel (step 1); then each screen presses its one choice a moment after it opens, through the screen's own update
# tick (the way DropInHub runs its stats timer): the hub PLAY (2), the PLAY menu EASHL or Drop-in Threes (3), the
# EASHL menu Drop-in (4), the Drop-in hub 6s or 3s (5). A screen presses only while the walk has not passed it, so a
# press by hand in between lets the rest go on. It stops in the dressing room: the player picks a position and Play.
CHEL_WAIT = 2   # seconds a screen waits after it opened (and, on the hub, after its buttons came on)
CHEL_WALKS = {rules.CHEL_DROPIN: 'sixes', rules.CHEL_DROPIN3: 'threes', rules.CHEL_GM3ON3: 'gm3on3',
              rules.CHEL_ONES: 'ones'}   # Ones: the PLAY menu picks Ones (3), its hub presses PLAY NOW (4)
MAINHUB_SHOW = b'function MainHub:OnShowDone()\r\n'
MAINHUB_INPUTS = b'function MainHub:UpdateActionsState(newstate)\r\n'
MAINHUB_STOCK = (b'    PLAY              = "evt_play",', b'function MainHub:update(delta)')
PLAYNOW_INIT = b'function PlayNowMenu:_Initialize()\r\n'
EASHLMENU_INIT = b'function EASHLMenu:_Initialize()\r\n'
EASHLMENU_STOCK = (b'    DROPIN', b'"evt_goto_drop_in"')
DROPINHUB_END = b'\t    self.mTimer:start()\r\n\tend\r\nend\r\n'
DROPINHUB_STOCK = (b'function DropInHub:_OpenPlayers6s()', b'function DropInHub:_OpenPlayers3s()')
GAUNTLETHUB_DATA = b'function GauntletHub:_OnGetHubData(success, data)\r\n'
GAUNTLETHUB_STOCK = (b'function GauntletHub:_GotoPlayNow()', b'HUB_STATE.BLACK_OUT', b'o:_SetupTimer()')


def chel_step(until, step, what, action, cond=''):
    """Lua for one screen of the walk: arm a press of `action` CHEL_WAIT seconds after the screen opened."""
    return _lines(
        f'    -- Overtime autoplay (World of Chel): {what}, once, a moment after this screen opened',
        '    pcall(function()',
        f'        if (_G.OvertimeChelStep or 99) < {step} and os.time() <= {int(until)} then',
        '            local base, t0 = self.update, os.time()',
        '            self.update = function(s, dt)',
        '                if base ~= nil then base(s, dt) end',
        f'                if (_G.OvertimeChelStep or 99) < {step} and os.time() >= t0 + {CHEL_WAIT}{cond} then',
        f'                    _G.OvertimeChelStep = {step}',
        f'                    pcall(function() {action} end)',
        '                end',
        '            end',
        '        end',
        '    end)')


def _check(raw, path, stock, name):
    if raw.count(b'\r\n') != raw.count(b'\n'):
        raise MenuError(f'{path} does not have CRLF line ends')
    missing = [x for x in stock if raw.count(x) < 1]
    if missing:
        raise MenuError(f'{path} is not the {name} this patch knows ({missing[0][:60]!r})')


def edit_mainhub(raw, until):
    """mainhub.lua pressing PLAY once its buttons are on (the hub's own inputs; the trait popup comes first)."""
    _check(raw, MAINHUB_PATH, MAINHUB_STOCK, 'World of Chel hub')
    _once(raw, MAINHUB_SHOW, MAINHUB_PATH)
    _once(raw, MAINHUB_INPUTS, MAINHUB_PATH)
    hook = chel_step(until, 2, 'the hub presses PLAY', 's.nav.Event(nil, EVENTS.PLAY, nil)',
                     ' and s.mOvertimeInputs == s.mValid and s.mCurrentMenu == MENUS.MAIN')
    out = raw.replace(MAINHUB_SHOW, MAINHUB_SHOW + hook)
    return out.replace(MAINHUB_INPUTS, MAINHUB_INPUTS + b'    self.mOvertimeInputs = newstate\r\n')


def edit_playnow_walk(raw, until, walk):
    """playnowmenu.lua (already edit_playnow'd) picking EASHL, or Drop-in Threes for the gm3on3 walk."""
    _check(raw, PLAYNOW_PATH, PLAYNOW_STOCK, 'playnowmenu.lua')
    _once(raw, PLAYNOW_INIT, PLAYNOW_PATH)
    action, pick = {'gm3on3': ('s:_OnAdvance(EVENTS.THREES)', 'Drop-in Threes'),
                    'ones': ('s:_OnAdvance(EVENTS.GAUNTLET)', 'Ones')}.get(walk, ('s:_OnAdvanceEASHL()', 'EASHL'))
    what = 'the PLAY menu picks ' + pick
    return raw.replace(PLAYNOW_INIT, PLAYNOW_INIT + chel_step(until, 3, what, action))


def edit_eashlmenu(raw, until):
    """eashlmenu.lua picking Drop-in."""
    _check(raw, EASHLMENU_PATH, EASHLMENU_STOCK, 'eashlmenu.lua')
    _once(raw, EASHLMENU_INIT, EASHLMENU_PATH)
    return raw.replace(EASHLMENU_INIT, EASHLMENU_INIT + chel_step(until, 4, 'the EASHL menu picks Drop-in',
                                                                  's:_OnAdvance(EVENTS.DROPIN)'))


def edit_dropinhub(raw, until, walk):
    """dropinhub.lua picking 6s or 3s (at the end of Initialize, around the stats timer's own update)."""
    _check(raw, DROPINHUB_PATH, DROPINHUB_STOCK, 'dropinhub.lua')
    at = _before_init_end(raw, DROPINHUB_PATH)
    six = walk == 'sixes'
    hook = chel_step(until, 5, 'the Drop-in hub picks ' + ('6s' if six else '3s'),
                     's:_OpenPlayers6s()' if six else 's:_OpenPlayers3s()')
    return raw[:at] + hook + raw[at:]


def edit_gauntlethub(raw, until):
    """gauntlethub.lua (Ones) pressing PLAY NOW once its event data is in and the event is not blacked out (the hub's own
    timer drives `update`; GauntletHub:new sets it before the data comes)."""
    _check(raw, GAUNTLETHUB_PATH, GAUNTLETHUB_STOCK, 'gauntlethub.lua')
    _once(raw, GAUNTLETHUB_DATA, GAUNTLETHUB_PATH)
    hook = chel_step(until, 4, 'the Ones hub presses PLAY NOW', 's:_GotoPlayNow()',
                     ' and s.mHubData ~= nil and s.mHubState ~= HUB_STATE.BLACK_OUT')
    return raw.replace(GAUNTLETHUB_DATA, GAUNTLETHUB_DATA + hook)


# 0.97.0 auto-ready (owner 2026-11-15: a laptop with only an integrated GPU runs NULL GPU, so nobody sees its screen):
# the dressing room does what the player would press, one step every AUTO_READY_GAP seconds through the screen's update
# tick (the walk's way): in INITIAL_POSITION_SELECTION it takes a free skater position (the goalie only when nothing
# else is free), in IDLE it presses READY, in READY it presses START MATCHMAKING. Only in Drop-in and Ones, only for a
# launch that asks for it (the app: when this PC's NHL 19 starts with NULL GPU), and again after every match until the
# hook runs out. The game's own post-match clock force-readies the loadout screen.
AUTO_READY_GAP = 3
DRESSINGROOM_NEW_END = b'    o:initialize()\r\n    return o\r\nend\r\n'
DRESSINGROOM_STOCK = (b'function DressingRoomFlow:HandleSelectPosition(actionName,controllerId)',
                      b'function DressingRoomFlow:HandleReady(readyPresenceState, deviceId)',
                      b'function DressingRoomFlow:HandleStartMatchMaking()', b'    INITIAL_POSITION_SELECTION  = ',
                      b'    READY       = "PRESENCE_STATE_READY",', b'local selectedPosition = self.mPositionList:getCurrentItem().Position')


def edit_dressingroom(raw, until):
    """dressingroomflow.lua readying up and searching by itself (auto-ready, above)."""
    _check(raw, DRESSINGROOM_PATH, DRESSINGROOM_STOCK, 'dressingroomflow.lua')
    _once(raw, DRESSINGROOM_NEW_END, DRESSINGROOM_PATH)
    hook = _lines(
        '    -- Overtime autoplay (World of Chel, no picture): a position, READY and START MATCHMAKING by themselves',
        '    pcall(function()',
        f'        if os.time() > {int(until)} then return end',
        '        local base, last = o.update, 0',
        '        o.update = function(s, dt)',
        '            if base ~= nil then base(s, dt) end',
        f'            if s.mFinalized or os.time() > {int(until)} or os.time() < last + {AUTO_READY_GAP} then return end',
        '            if not (s.mIsDropInContext or s.mIsGauntletContext) then return end',
        '            pcall(function()',
        '                local st, me = s.mCurrentState, s.mLocalUserData',
        '                local dev = s.mUsersInfoData and s.mUsersInfoData.LocalDeviceId',
        '                if st == STATES.INITIAL_POSITION_SELECTION and s.mPositionList ~= nil then',
        '                    last = os.time()',
        '                    local goalie = s.mDressingRoomService.GetAllPositions().POSITION_GOALIE',
        '                    local pick = nil',
        '                    for _, it in pairs(s.mDressingRoomService.GetPositions() or {}) do',
        '                        if pick == nil and it.IsLockable and it.Position ~= goalie then pick = it end',
        '                    end',
        '                    local list, set, own = s.mPositionList, false, nil',
        '                    if pick ~= nil then pcall(function()',
        "                        own = rawget(list, 'getCurrentItem')",
        '                        list.getCurrentItem = function() return pick end',
        '                        set = true',
        '                    end) end',
        '                    pcall(function() s:HandleSelectPosition(nil, dev) end)',
        '                    if set then pcall(function() list.getCurrentItem = own end) end',
        '                elseif st == STATES.IDLE and not s.mHasPendingReadyRequest',
        '                        and me ~= nil and me.IsUser and me.UserInfo and me.UserInfo.IsReady ~= true then',
        '                    last = os.time()',
        '                    s:HandleReady(PRESENCE_IDS.READY, dev)',
        '                elseif st == STATES.READY and not s.mIsMatchmaking and not s.mIsGauntletContext then',
        '                    last = os.time()',
        '                    s:HandleStartMatchMaking()',
        '                end',
        '            end)',
        '        end',
        '    end)')
    tail = b'    return o\r\nend\r\n'
    return raw.replace(DRESSINGROOM_NEW_END, DRESSINGROOM_NEW_END[:-len(tail)] + hook + tail)


def chel_edits(read, until, chel, playnow, auto_ready=False, eashlmenu=None, dropinhub=None):
    """{path: bytes} of the walk for CHEL mode `chel` (none for a mode it does not know); `playnow` is the PLAY menu
    as served already (Pro-Am locked). `auto_ready`: the dressing room readies and searches by itself too."""
    walk = CHEL_WALKS.get(chel)
    if walk is None:
        return {}
    out = {MAINHUB_PATH: edit_mainhub(read(MAINHUB_PATH), until), PLAYNOW_PATH: edit_playnow_walk(playnow, until, walk)}
    if auto_ready:
        out[DRESSINGROOM_PATH] = edit_dressingroom(read(DRESSINGROOM_PATH), until)
    if walk == 'ones':
        out[GAUNTLETHUB_PATH] = edit_gauntlethub(read(GAUNTLETHUB_PATH), until)
    elif walk != 'gm3on3':
        out[EASHLMENU_PATH] = edit_eashlmenu(eashlmenu if eashlmenu is not None else read(EASHLMENU_PATH), until)
        out[DROPINHUB_PATH] = edit_dropinhub(dropinhub if dropinhub is not None else read(DROPINHUB_PATH), until, walk)
    return out


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


# World of Chel's PLAY menu, three tiles: Threes | Drop-in 3s | Drop-in 6s (owner 2026-11-15 had four with Ones first;
# 2026-11-16 Ones is hidden for 0.97.0: it fails on the game-server hub, game-server-hub.md game 69). Pro-Am's challenge
# room stalls (no server answer found), so its slot is Drop-in 3s; the EASHL slot is Drop-in 6s (the EASHL menu has
# only Drop-in left once Online Seasons is hidden). A Drop-in tile sets _G.OvertimeDropIn ('3s' / '6s') and opens the
# EASHL menu as the EASHL tile did; the EASHL menu then picks Drop-in and the Drop-in hub picks that room by themselves
# (DROPIN_DIRECT hooks), so the player lands in the dressing room. The PLAY menu clears the flag whenever it opens.
# playnowmenu.lua: Pro-Am's lock (the closed beta's) forced off, so the slot's action is VALID and its style enabled.
PROAM_LOCK_ANCHOR = b'    o.mProAmModeLocked = o.data.IsClosedBeta ~= nil and  o.data.IsClosedBeta or false\r\n'
PROAM_LOCK = (b'    -- Overtime menus: the Pro-Am slot is Drop-in 3s, never locked; no Drop-in room is picked yet\r\n'
              b'    o.mProAmModeLocked = false\r\n'
              b'    _G.OvertimeDropIn = nil\r\n')
PLAYNOW_STOCK = (b'function PlayNowMenu:new(init)', b'self.im.ChangeActionState(ACTIONS.PROAM, state)')
DROPIN_ACTIONS = ((b'    self.im.RegisterAction(ACTIONS.PROAM, function() self:_OnAdvance(EVENTS.PROAM) end)\r\n',
                   b"    self.im.RegisterAction(ACTIONS.PROAM, function() _G.OvertimeDropIn = '3s'; self:_OnAdvanceEASHL() end)"
                   b'   -- Overtime menus: Drop-in 3s\r\n'),
                  (b'    self.im.RegisterAction(ACTIONS.GAUNTLET, function() self:_OnAdvance(EVENTS.GAUNTLET) end)\r\n',
                   b'    self.im.RegisterAction(ACTIONS.GAUNTLET, function() end)   -- Overtime menus: Ones hidden\r\n'),
                  (b'    self.im.RegisterAction(ACTIONS.EASHL, function() self:_OnAdvanceEASHL() end)\r\n',
                   b"    self.im.RegisterAction(ACTIONS.EASHL, function() _G.OvertimeDropIn = '6s'; self:_OnAdvanceEASHL() end)"
                   b'   -- Overtime menus: Drop-in 6s\r\n'))
# playnowmenu.layout: the tiles' order on screen and for the cursor: Threes 335, Pro-Am slot (Drop-in 3s) 755, EASHL slot
# (Drop-in 6s) 1175, centred like the stock four (stock: Pro-Am 125, Ones 545, Threes 965, EASHL 1385); the Pro-Am slot
# gets the EASHL art. Ones (GauntletTile) leaves the cursor's targets and the canvas, and its action does nothing (the
# Seasons tile's way, SEASONS_*); the Ones walk (CHEL_WALKS 'ones') calls _OnAdvance itself and still works.
PLAYNOW_TARGETS = (b'                "ProamTile",\r\n                "GauntletTile",\r\n                "ThreesTile",\r\n'
                   b'                "EASHLTile"\r\n')
PLAYNOW_ORDER = (b'                "ThreesTile",\r\n                "ProamTile",\r\n'
                 b'                "EASHLTile"\r\n')
TILE_X = {b'ProamTile': (b'125.0', b'755.0'), b'GauntletTile': (b'545.0', b'6000.0'), b'ThreesTile': (b'965.0', b'335.0'),
          b'EASHLTile': (b'1385.0', b'1175.0')}
PROAM_ART = (b'"type": "resort_brand_proam",', b'"type": "resort_brand_eashl",')
PLAYNOW_LAYOUT_STOCK = (b'"name": "PlayNowMenu",', b'"name": "ProamTile",', b'"name": "EASHLTile",')
# playnowmenu.dd: the two Drop-in tiles' titles are the Drop-in hub's own button texts; the Pro-Am action starts VALID.
PLAYNOW_DD_EDITS = ((b'"tag": "TXT_PROAM_MODE_DESCR",', b'"tag": "TXT_PLAY_3S",'),
                    (b'"tag": "TXT_EASHL_MODE_DESCR",', b'"tag": "TXT_PLAY_6S",'),
                    (b'            "viewname": "open_proam_mode",\r\n            "state": "INVALID",',
                     b'            "viewname": "open_proam_mode",\r\n            "state": "VALID",'))


def edit_playnow(raw):
    """playnowmenu.lua with the Pro-Am slot as Drop-in 3s, the EASHL tile as Drop-in 6s and Ones' action doing nothing."""
    path = PLAYNOW_PATH
    if MARK in raw:
        raise MenuError(f'{path} is already edited')
    if raw.count(b'\r\n') != raw.count(b'\n'):
        raise MenuError(f'{path} does not have CRLF line ends')
    missing = [s for s in PLAYNOW_STOCK if raw.count(s) != 1]
    if missing:
        raise MenuError(f'{path} is not the playnowmenu.lua this patch knows ({missing[0][:60]!r})')
    _once(raw, PROAM_LOCK_ANCHOR, path)
    for old, _new in DROPIN_ACTIONS:
        _once(raw, old, path)
    out = raw.replace(PROAM_LOCK_ANCHOR, PROAM_LOCK_ANCHOR + PROAM_LOCK)
    for old, new in DROPIN_ACTIONS:
        out = out.replace(old, new)
    return out


def _tile_x(raw, name, old, new, path):
    """The layout with tile `name`'s x moved from `old` to `new` (its x line is the first after its name)."""
    at = raw.find(b'"name": "' + name + b'",')
    key = b'"x": ' + old + b','
    x = raw.find(key, at)
    nxt = raw.find(b'"name": "', at + 1)
    if at < 0 or x < 0 or (0 <= nxt < x):
        raise MenuError(f'{path}: tile {name.decode()} has no x {old.decode()}')
    return raw[:x] + b'"x": ' + new + b',' + raw[x + len(key):]


def edit_playnow_layout(raw):
    """playnowmenu.layout as Threes | Drop-in 3s (the Pro-Am slot, EASHL art) | Drop-in 6s (the EASHL slot), Ones hidden."""
    path = PLAYNOW_LAYOUT_PATH
    if raw.count(b'\r\n') != raw.count(b'\n'):
        raise MenuError(f'{path} does not have CRLF line ends')
    missing = [s for s in PLAYNOW_LAYOUT_STOCK if raw.count(s) != 1]
    if missing:
        raise MenuError(f'{path} is not the playnowmenu.layout this patch knows ({missing[0][:60]!r})')
    _once(raw, PLAYNOW_TARGETS, path)
    _once(raw, PROAM_ART[0], path)
    out = raw.replace(PLAYNOW_TARGETS, PLAYNOW_ORDER).replace(*PROAM_ART)
    for name, (old, new) in TILE_X.items():
        out = _tile_x(out, name, old, new, path)
    return out


def edit_playnow_dd(raw):
    """playnowmenu.dd with the Drop-in titles on the Pro-Am and EASHL tiles, the Pro-Am action VALID."""
    path = PLAYNOW_DD_PATH
    if raw.count(b'\r\n') != raw.count(b'\n'):
        raise MenuError(f'{path} does not have CRLF line ends')
    for old, _new in PLAYNOW_DD_EDITS:
        _once(raw, old, path)
    for old, new in PLAYNOW_DD_EDITS:
        raw = raw.replace(old, new)
    return raw


# The Drop-in tiles' own walk: the EASHL menu picks Drop-in, the Drop-in hub picks the room the flag names (and clears
# it), each a moment after it opened, through the screen's update tick as chel_step does. No deadline: the flag is set
# only by a press on the PLAY menu.
def dropin_direct(what, cond, action):
    return _lines(
        f'    -- Overtime menus (Drop-in tiles): {what}, a moment after this screen opened',
        '    pcall(function()',
        f'        if {cond} then',
        '            local base, t0, done = self.update, os.time(), false',
        '            self.update = function(s, dt)',
        '                if base ~= nil then base(s, dt) end',
        f'                if not done and {cond} and os.time() >= t0 + 1 then',
        '                    done = true',
        f'                    pcall(function() {action} end)',
        '                end',
        '            end',
        '        end',
        '    end)')


DROPINHUB_TIMER = b'\t    self.mTimer:start()\r\n\tend\r\n'   # the end of DropInHub:Initialize's timer block


def _before_init_end(raw, path):
    """Where DropInHub:Initialize's last `end` starts (after the timer block and any hooks already there)."""
    _once(raw, DROPINHUB_TIMER, path)
    at = raw.find(b'\r\nend\r\n', raw.find(DROPINHUB_TIMER) + len(DROPINHUB_TIMER) - 2)
    if at < 0:
        raise MenuError(f'{path}: no end after the timer block')
    return at + 2


def edit_dropinhub_direct(raw):
    """dropinhub.lua opening the room a Drop-in tile picked (served with every build)."""
    path = DROPINHUB_PATH
    if MARK in raw:
        raise MenuError(f'{path} is already edited')
    _check(raw, path, DROPINHUB_STOCK, 'dropinhub.lua')
    at = _before_init_end(raw, path)
    hook = dropin_direct('the Drop-in hub opens the room the PLAY menu picked', '_G.OvertimeDropIn ~= nil',
                         "local room = _G.OvertimeDropIn; _G.OvertimeDropIn = nil; "
                         "if room == '6s' then s:_OpenPlayers6s() else s:_OpenPlayers3s() end")
    return raw[:at] + hook + raw[at:]


# eashlmenu.lua: Online Seasons (club seasons and playoffs) has no working server side (club matchmaking never played a
# match; owner 2026-11-15: "doesnt seem to even work, can you hide that tile"). The game's own lock (the one it shows
# without a club: action INVALID, tile inactive) forced on, and the tile leaves the cursor's targets and the screen.
SEASONS_LOCK_ANCHOR = b'    self.mOnlineSeasonsLocked = result.Status.OnlineSeason.IsLocked\r\n'
SEASONS_LOCK = (b'    -- Overtime menus: Online Seasons has no server side yet, so the mode stays locked\r\n'
                b'    self.mOnlineSeasonsLocked = true\r\n')
SEASONS_STOCK = (b'function EASHLMenu:_BuildStats()', b'self.im.ChangeActionState(ACTIONS.ONLINE_SEASONS, state)')
# eashlmenu.layout (PanelLayout, two tiles centred by margins 460 apart): Drop-in alone in the centre, Online Seasons
# pushed far right off the 1920 canvas. The tile stays, so the behavior that names it still finds it.
SEASONS_TARGET = b'                "DropInTile",\r\n                "OnlineSeasonsTile"\r\n'
SEASONS_MARGINS = ((b'            "marginRight": 460.0,\r\n', b''),
                   (b'            "marginLeft": 460.0,\r\n', b'            "marginLeft": 6000.0,\r\n'))
EASHLMENU_LAYOUT_STOCK = (b'"name": "EASHLMenu",', b'"name": "DropInTile",', b'"name": "OnlineSeasonsTile",')


def edit_eashlmenu_seasons(raw):
    """eashlmenu.lua with Online Seasons locked, picking Drop-in by itself after a Drop-in tile."""
    path = EASHLMENU_PATH
    if MARK in raw:
        raise MenuError(f'{path} is already edited')
    if raw.count(b'\r\n') != raw.count(b'\n'):
        raise MenuError(f'{path} does not have CRLF line ends')
    missing = [s for s in SEASONS_STOCK if raw.count(s) != 1]
    if missing:
        raise MenuError(f'{path} is not the eashlmenu.lua this patch knows ({missing[0][:60]!r})')
    _once(raw, SEASONS_LOCK_ANCHOR, path)
    _once(raw, EASHLMENU_INIT, path)
    hook = dropin_direct('the EASHL menu picks Drop-in for a Drop-in tile', '_G.OvertimeDropIn ~= nil',
                         's:_OnAdvance(EVENTS.DROPIN)')
    out = raw.replace(SEASONS_LOCK_ANCHOR, SEASONS_LOCK_ANCHOR + SEASONS_LOCK)
    return out.replace(EASHLMENU_INIT, EASHLMENU_INIT + hook)


def edit_eashlmenu_layout(raw):
    """eashlmenu.layout without the Online Seasons tile (off screen, not a cursor target), Drop-in centred."""
    path = EASHLMENU_LAYOUT_PATH
    if raw.count(b'\r\n') != raw.count(b'\n'):
        raise MenuError(f'{path} does not have CRLF line ends')
    missing = [s for s in EASHLMENU_LAYOUT_STOCK if raw.count(s) != 1]
    if missing:
        raise MenuError(f'{path} is not the eashlmenu.layout this patch knows ({missing[0][:60]!r})')
    _once(raw, SEASONS_TARGET, path)
    for old, _new in SEASONS_MARGINS:
        _once(raw, old, path)
    out = raw.replace(SEASONS_TARGET, b'                "DropInTile"\r\n')
    for old, new in SEASONS_MARGINS:
        out = out.replace(old, new)
    return out


def options(given=None, served=None):
    """The layer's options: the defaults, then the ones served now, then `given` (unknown keys are refused)."""
    out = dict(OPTIONS)
    for src in (served or {}), (given or {}):
        unknown = set(src) - set(OPTIONS)
        if unknown:
            raise MenuError(f'unknown menus option(s): {", ".join(sorted(unknown))}')
        out.update({k: bool(v) for k, v in src.items()})
    return out


# A CHEL lobby launch (0.90.0): the World of Chel tile is served whatever the player's switch says. 0.96.0: with the
# lobby's mode in the launch ('chel': rules.CHEL_DROPIN / CHEL_DROPIN3 / CHEL_GM3ON3) the homepage jumps into World of
# Chel and the walk (chel_edits) goes on to that mode's dressing room; without it only the tile is served.
CHEL_LAUNCH = 'chel'


def launch_mode(launch):
    """The game a launch jumps into: 'versus' (the default), 'shootout' or 'threes'; 'chel' serves the tile only."""
    mode = (launch or {}).get('mode') or rules.VERSUS
    if mode not in HUB_MODES and mode != CHEL_LAUNCH:
        raise MenuError(f'unknown game mode: {str(mode)[:20]}')
    return mode


def playnow_edits(read):
    """World of Chel's PLAY menu as Ones | Threes | Drop-in 3s | Drop-in 6s, its EASHL menu without Online Seasons and
    the Drop-in tiles' walk, served with every build (World of Chel switched on or not)."""
    return {PLAYNOW_PATH: edit_playnow(read(PLAYNOW_PATH)), PLAYNOW_LAYOUT_PATH: edit_playnow_layout(read(PLAYNOW_LAYOUT_PATH)),
            PLAYNOW_DD_PATH: edit_playnow_dd(read(PLAYNOW_DD_PATH)),
            EASHLMENU_PATH: edit_eashlmenu_seasons(read(EASHLMENU_PATH)),
            EASHLMENU_LAYOUT_PATH: edit_eashlmenu_layout(read(EASHLMENU_LAYOUT_PATH)),
            DROPINHUB_PATH: edit_dropinhub_direct(read(DROPINHUB_PATH))}


def edits(read, opts, launch=None):
    """{path: new bytes} for the homepage's two files and the PLAY menu's two, plus hub.lua with `launch` ({'until': unix seconds, 'diag': bool, 'mode':
    versus|shootout, 'rules': {rule: value}}) and that mode's rules file when it names rules; `read(path)` gives the
    game's own bytes. A 'chel' launch changes only the homepage: the tile on, no hook."""
    if launch and launch_mode(launch) == CHEL_LAUNCH:
        walk = launch.get('chel') in CHEL_WALKS
        out = {HOMEPAGE_PATH: edit_homepage(read(HOMEPAGE_PATH), chel=True, news=opts['news'], hut=opts['hut'],
                                            launch=launch if walk else None),
               LAYOUT_PATH: edit_layout(read(LAYOUT_PATH)), **playnow_edits(read)}
        if walk:
            out.update(chel_edits(read, launch['until'], launch['chel'], out[PLAYNOW_PATH], bool(launch.get('auto_ready')),
                                  out[EASHLMENU_PATH], out[DROPINHUB_PATH]))
        return out
    out = {HOMEPAGE_PATH: edit_homepage(read(HOMEPAGE_PATH), chel=opts['chel'], news=opts['news'], launch=launch, hut=opts['hut']),
           LAYOUT_PATH: edit_layout(read(LAYOUT_PATH)), **playnow_edits(read)}
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
        if launch.get('rules') and launch_mode(launch) != CHEL_LAUNCH:
            rec['rules'] = rules.validate(launch['rules'], partial=True, mode=launch_mode(launch))
    return rec
