"""Overtime game patch, data part: what the patch changes in the game's data, served through shadPS4's mods overlay.

`<game folder>-mods/` mirrors the game folder and a file there is served instead of the game's. For every archive
that wins for an edited entry, `apply` writes a copy into the overlay with the edited entries appended
(`eb.append_entry`). The game folder is only read. Layers (each optional):

  text      the Overtime text pack (client/textpack/<lang>.json): the connection texts
  names     Arizona's texts become Utah's (loc ids keyed by art abbreviation PHX and by 22), and "Burnaby", the
            city of customteams 498 (Seattle's AHL club), becomes "Coachella Valley"
  database  a whole default database (nhl_game.db), e.g. the game's default roster brought up to 2026-27, and
            the game's roster file (initial_experience.db) made from it: the game lays that file's 41 rosterupdate
            tables (players, teams, calendars) over nhl_game.db's, so without it modes keep the stock league
            (run x2-20261016/run5: Franchise on Arizona and the stock calendar with only nhl_game.db patched),
            and the Franchise start rosters (expansion_draft.db, entry_draft.db) given the same players
  league    the 2026-27 league for new Franchise / Season leagues (boot.big): capdefs.brk's money table (floor
            and cap $76.9M / $104.0M in place of 2018-19's $58.8M / $79.5M, the CBA's next caps, lowest and
            entry-level salaries per league year), the league creation schemas' $80M limit on a team's cap and
            payroll raised, and the Division Realignment screen (nhlselectteam.lua) set up with the real
            alignment: the league gives each list position its stock division, so the expansion team (Seattle)
            takes slot 22's Pacific position and Utah the expansion team's Central one (run x4-20261016/run2)
  menus     the hub (boot.big homepage.lua / homepage.layout, overtime_core.menus) without Hockey Ultimate Team,
            Draft Champions and World of Chel (no servers); the news tile stays for the text pack's Puck Peak line.
            Its options (menus.OPTIONS: `chel` brings World of Chel back, `news` off drops the news tile) are kept
            in the state file
  art       team art and portraits from art packs (overtime_core.art): NHL 27's logos, menu jerseys, kits and centre
            ice for the 32 teams (Utah on Arizona's art, Seattle at its own art id 10499), NHL.com portraits. These
            go into NEW archives one number above the game's highest of each family (patch_inxp_57.big,
            patch_game_97.big), so no game archive copy is touched; re-applying other layers keeps the art served

`overtime-patch.json` in the overlay lists every file written with its sha256; `undo` removes only those files,
only while unchanged, then the folders left empty. The state is saved as each file lands, so undo reaches stock after a
failed apply too. A file of someone else's at a path the patch writes (a user's own patch archive) is moved into
`overtime-patch-backup/` and put back by undo or by an apply that drops it. Deleting the whole `-mods` folder also
returns the game to stock (and loses such a file).
Nothing is written while shadPS4 runs (it holds the overlay files open and would mix old and new data).
"""
import datetime
import functools
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys

from . import art as art_mod, eb, gamefiles, menus as menus_mod, textpack
from .schema import parse_schema
from .tdb import Database

VERSION = 1
STATE_NAME = 'overtime-patch.json'
BACKUP_DIR = 'overtime-patch-backup'  # someone else's files the patch's own replace while it is applied
LAYERS = ('text', 'names', 'database', 'league', 'menus', 'art')
LEGACY_SUFFIX = textpack.STATE_SUFFIX  # the text pack's own overlay state (before this module)

UTAH_CITY, UTAH_NAME, UTAH_NICK, UTAH_ABBR = 'Utah', 'Utah Mammoth', 'Mammoth', 'UTA'
# loc string id -> (stock text without the trademark sign, new text). Ids ending _ARZL are the Coyotes Alumni
# classic team and stay; the stock text is checked so a game version with other ids fails loudly.
NAMES = {
    'NHLCityName_22': ('Arizona', UTAH_CITY), 'NHLCityName_PHX': ('Arizona', UTAH_CITY),
    'CITYLINE1_22': ('Arizona', UTAH_CITY), 'TEAMLINE1_PHX': ('Arizona', UTAH_CITY),
    'NHLTeamName_22': ('Arizona Coyotes', UTAH_NAME), 'NHLTeamName_PHX': ('Arizona Coyotes', UTAH_NAME),
    'NHLTeamName_ARZ': ('Arizona Coyotes', UTAH_NAME),
    'NICKLINE2_22': ('Coyotes', UTAH_NICK), 'NICKLINE2_PHX': ('Coyotes', UTAH_NICK),
    'TEAMLINE2_PHX': ('Coyotes', UTAH_NICK), 'TXT_NICKNAME_PHX': ('Coyotes', UTAH_NICK),
    'TXT_NICKNAME_ALT_PHX': ('Yotes', UTAH_NICK),
    'X_XLA_TEAM_PHX': ('ARZ', UTAH_ABBR), 'NHLTeamName_Abbr3_22': ('ARZ', UTAH_ABBR),
    'NHLTeamName_Abbr3_PHX': ('ARI', UTAH_ABBR),
    'BURNABY': ('Burnaby', 'Coachella Valley'),
    # The clubs the update renames on their slot (rosterupdate.rename_ahl, rename_allsvenskan): the menus show the loc
    # texts keyed by the slot's artabbr, not the database's names (docs/notes/nhl19-2026-patch.md). Ids spelt as the
    # loc database has them; TEAMLINE1 of the Swedish clubs is ' ' and stays.
    'NHLCityName_BIN': ('Binghamton', 'Abbotsford'), 'NHLTeamName_BIN': ('Binghamton Devils', 'Abbotsford Canucks'),
    'NHLTeamName_ABBR3_BIN': ('BNG', 'ABB'), 'TXT_NICKNAME_BIN': ('Devils', 'Canucks'),
    'TXT_NICKNAME_ALT_BIN': ('Baby Sens', 'Canucks'), 'Teamline1_BIN': ('Binghamton', 'Abbotsford'),
    'Teamline2_BIN': ('Devils', 'Canucks'),
    'NHLCityName_BRP': ('Bridgeport', 'Hamilton'), 'NHLTeamName_BRP': ('Bridgeport Sound Tigers', 'Hamilton Hammers'),
    'NHLTeamName_ABBR3_BRP': ('BRI', 'HAM'), 'TXT_NICKNAME_BRP': ('Sound Tigers', 'Hammers'),
    'TXT_NICKNAME_ALT_BRP': ('Sound Tigers', 'Hammers'), 'Teamline1_BRP': ('Bridgeport', 'Hamilton'),
    'Teamline2_BRP': ('Sound Tigers', 'Hammers'),
    'NHLCityName_SAN': ('San Antonio', 'Henderson'), 'NHLTeamName_SAN': ('San Antonio Rampage', 'Henderson Silver Knights'),
    'NHLTeamName_ABBR3_SAN': ('SA', 'HSK'), 'TXT_NICKNAME_SAN': ('Rampage', 'Silver Knights'),
    'TXT_NICKNAME_ALT_SAN': ('Rampage', 'Silver Knights'), 'Teamline1_SAN': ('San Antonio', 'Henderson'),
    'Teamline2_SAN': ('Rampage', 'Silver Knights'), 'X_XLA_TEAM_SAN': ('SA', 'HSK'),
    'NHLCITYNAME_STOC': ('Stockton', 'Calgary'), 'NHLTEAMNAME_STOC': ('Stockton Heat', 'Calgary Wranglers'),
    'NHLTeamName_Abbr3_STOC': ('STK', 'CGY'), 'NICKLINE2_STOC': ('Heat', 'Wranglers'),
    'TEAMLINE1_STOC': ('Stockton', 'Calgary'), 'TEAMLINE2_STOC': ('Heat', 'Wranglers'),
    'TXT_NICKNAME_STOC': ('Heat', 'Wranglers'), 'TXT_NICKNAME_ALT_STOC': ('Heat', 'Wranglers'),
    'X_XLA_TEAM_STOC': ('STK', 'CGY'),
    'NHLCityName_BJOR': ('Björklöven', 'Östersund'), 'NHLTEAMNAME_BJOR': ('IF Björklöven', 'Östersunds IK'),
    'NHLTEAMNAME_Abbr3_BJOR': ('IFB', 'OST'), 'TEAMLINE2_BJOR': ('IF Bjorkloven', 'Östersunds IK'),
    'TXT_NICKNAME_BJOR': ('Björklöven', 'Östersund'), 'TXT_NICKNAME_ALT_BJOR': ('Björklöven', 'Östersund'),
    'NHLCITYNAME_KRLS': ('Karlskrona HK', 'Kalmar HC'), 'NHLTEAMNAME_KRLS': ('Karlskrona HK', 'Kalmar HC'),
    'NHLTeamName_Abbr3_KRLS': ('KHK', 'KAL'), 'NICKLINE2_KRLS': ('Karlskrona', 'Kalmar'),
    'TEAMLINE2_KRLS': ('Karlskrona HK', 'Kalmar HC'), 'TXT_NICKNAME_KRLS': ('Karlskrona', 'Kalmar'),
    'TXT_NICKNAME_ALT_KRLS': ('Karlskrona', 'Kalmar'), 'X_XLA_TEAM_KRLS': ('KHK', 'KAL'),
    'NHLCityName_PANT': ('Pantern', 'Nybro'), 'NHLTEAMNAME_PANT': ('IK Pantern', 'Nybro Vikings IF'),
    'NHLTEAMNAME_Abbr3_PANT': ('PAN', 'NYB'), 'TEAMLINE2_PANT': ('IK Pantern', 'Nybro Vikings IF'),
    'TXT_NICKNAME_PANT': ('Pantern', 'Nybro'), 'TXT_NICKNAME_ALT_PANT': ('Pantern', 'Nybro'),
    'NHLCityName_TING': ('Tingsryd', 'Vimmerby'), 'NHLTEAMNAME_TING': ('Tingsryds AIF', 'Vimmerby Hockey'),
    'NHLTEAMNAME_Abbr3_TING': ('TAIF', 'VIM'), 'TEAMLINE2_TING': ('Tingsryds AIF', 'Vimmerby Hockey'),
    'TXT_NICKNAME_TING': ('Tingsryds', 'Vimmerby'), 'TXT_NICKNAME_ALT_TING': ('Tingsryds', 'Vimmerby'),
    'NHLCityName_VIK': ('Västervik', 'Visby'), 'NHLTEAMNAME_VIK': ('Västerviks IK', 'Visby/Roma HK'),
    'NHLTEAMNAME_Abbr3_VIK': ('VVIK', 'VIS'), 'TEAMLINE2_VIK': ('Västerviks IK', 'Visby/Roma HK'),
    'TXT_NICKNAME_VIK': ('Västervik', 'Visby'), 'TXT_NICKNAME_ALT_VIK': ('Västervik', 'Visby'),
    # The Penticton Vees (overtime_core/vees.py): the loc texts of the Plymouth Whalers, an OHL club no slot has, which the
    # Vees' slot takes as its artabbr.
    'NHLCityName_PLYM': ('Plymouth', 'Penticton'), 'NHLTeamName_PLYM': ('Plymouth Whalers', 'Penticton Vees'),
    'NHLTeamName_Abbr3_PLYM': ('PLY', 'PEN'), 'TEAMLINE1_PLYM': ('Plymouth', 'Penticton'),
    'TEAMLINE2_PLYM': ('Whalers', 'Vees'), 'TXT_NICKNAME_PLYM': ('Whalers', 'Vees'),
    'TXT_NICKNAME_ALT_PLYM': ('Whalers', 'Vees'), 'X_XLA_TEAM_PLYM': ('PLY', 'PEN'),
    'NHLCityName_VITA': ('Vita Hästen', 'Mora'), 'NHLTEAMNAME_VITA': ('HC Vita Hästen', 'Mora IK'),
    'NHLTEAMNAME_Abbr3_VITA': ('VIT', 'MORA'), 'TEAMLINE2_VITA': ('HC Vita Hästen', 'Mora IK'),
    'TXT_NICKNAME_VITA': ('Vita Hästen', 'Mora'), 'TXT_NICKNAME_ALT_VITA': ('Vita Hästen', 'Mora'),
}

# The league layer. capdefs.brk (170 bytes, the league kernel's money table; the same rows as the table Legacy found
# in guest memory): u16 salary floor and cap of the first league year in $100,000 at 0x1c / 0x1e, then four rows of
# 12 u16 in $1,000, one value per league year: the floor's rise, the cap's rise, the lowest salary and the highest
# entry-level salary (leaguestates key 162). The game's league year stays 2018, so year 0 is 2026-27.
# Real numbers: docs/notes/nhl19-2026-patch.md.
CAPDEFS_PATH = 'nhl/data/common/gamemodes/league/resource_kernel/capdefs.brk'
# Franchise start rosters next to the roster file: 10 player tables each (players, bios, AI, equipment, roster,
# free agents, draft picks, salary extras), same capacities as nhl_game.db's. The game's own copies hold launch-day
# (Sept 2018) rosters that no patch updated; a 32-team expansion Franchise on the default roster starts from
# expansion_draft.db (run x4-20261016/run3: Zetterberg on Detroit with the 2026-27 default roster served).
# proam.db (World of CHEL tiers) is the same launch file and stays as it is.
MODE_ROSTERS = tuple(f'nhl/data/common/gamemodes/roster/{name}.db' for name in ('expansion_draft', 'entry_draft'))
EXPANSION_ROSTER = MODE_ROSTERS[0]
CAP_AT, CAP_STOCK, CAP_2026 = 0x1c, (588, 795), (769, 1040)
ROWS_AT = 0x20
ROWS_STOCK = ((0,) + (500,) * 11,  # floor's rise
              (0, 1000, 1000, 1000) + (500,) * 8,  # cap's rise
              (650, 700, 700, 750, 750, 775, 775, 800, 825, 850, 875, 900),  # lowest salary
              (925, 925, 925, 925, 925, 950, 950, 950, 975, 1000, 1025, 1050))  # highest entry-level salary
# NHL 27's own table (legacybrkfeatureskernel.brk at 37, the capdefs layout; nhl27.money, the NHL 27 pack's 'money';
# docs/notes/nhl27-data.md): the same 2026-27 floor and cap, its own rises ($8.4M / $8.5M, then $9.5M, then $1.5M a
# year), the CBA's lowest salaries ($1,000,000 to 2032-33, then $25,000 a year) and ELC maximum = lowest + $175,000
NHL27_CAP = (769, 1040)
NHL27_ROWS = ((0, 8400, 9500) + (1500,) * 9,
              (0, 8500, 9500) + (1500,) * 9,
              (850, 900, 950) + (1000,) * 4 + (1025, 1050, 1075, 1100, 1125),
              (1025, 1075, 1125) + (1175,) * 4 + (1200, 1225, 1250, 1275, 1300))
# What the league fixed comes first: floors $83.9M / $94.35M and caps $113.5M / $127.5M for 2027-28 / 2028-29 (fixed
# / the league's estimate), lowest salary $850,000 to $1,000,000 by 2029-30 (CBA), ELC maximum = lowest salary +
# $175,000 (MOU); NHL 27's rows after that (rises of $1.5M a year where the stock table has $500,000)
FIXED_RISES, FIXED_LOWEST = 3, 4
LOWEST_2026 = (850, 900, 950, 1000) + NHL27_ROWS[2][FIXED_LOWEST:]
ROWS_2026 = ((0, 7000, 10450) + NHL27_ROWS[0][FIXED_RISES:],
             (0, 9500, 14000) + NHL27_ROWS[1][FIXED_RISES:],
             LOWEST_2026,
             tuple(v + 175 for v in LOWEST_2026))
SALARY_SCHEMAS = tuple(f'nhl/data/common/gamemodes/service-defs/{kind}/league_creation/competition.json'
                       for kind in ('data', 'job', 'view'))
SALARY_LIMIT_STOCK, SALARY_LIMIT = b'"Max":80000000', b'"Max":250000000'  # TeamCapSalary, TeamCurrentSalary
# The Division Realignment screen of a new Franchise: the end of AddDataToTeams (run on load and on Reset to
# Defaults, after the list positions are numbered) gets the 2026-27 alignment. Positions keep their stock division
# in the league, whatever the screen shows, so the expansion team (499) and Utah (22) trade positions, and the
# screen lists them where they will play. A game without either team leaves the list alone. Season uses the same
# screen and seeding, so it gets the swap too when the 32-team switch (xmlpatch expansion32) puts 499 in its list.
SELECT_TEAM_PATH = 'nhl/ui/features/season/vvms/selectteam/nhlselectteam.lua'
SELECT_TEAM_ANCHOR = b'        self.mData[i].Swapping = false\r\n    end\r\nend\r\n'
SELECT_TEAM_ALIGN = (
    b'        self.mData[i].Swapping = false\r\n'
    b'    end\r\n'
    b'    -- Overtime 2026 patch: the league gives every list position its stock division, so the expansion team\r\n'
    b'    -- takes slot 22\'s Pacific position and Utah the expansion team\'s Central one.\r\n'
    b'    if self.mGameMode == GAME_MODES.BE_A_GM or self.mGameMode == GAME_MODES.SEASON then\r\n'
    b'        local utah, seattle\r\n'
    b'        for i=1, #self.mData do\r\n'
    b'            if self.mData[i].TeamId == 22 then utah = self.mData[i] end\r\n'
    b'            if self.mData[i].TeamId == 499 then seattle = self.mData[i] end\r\n'
    b'        end\r\n'
    b'        if utah ~= nil and seattle ~= nil then\r\n'
    b'            utah.SortId, seattle.SortId = seattle.SortId, utah.SortId\r\n'
    b'            utah.DivisionId, seattle.DivisionId = 9, 8\r\n'
    b'        end\r\n'
    b'    end\r\n'
    b'end\r\n')
# The other leagues' Season team list (Liiga, SHL, ...): with the 32-team switch the service appends the expansion
# team (499) to every league's list, where it shows at 0 OVR though the league never holds it. Without Utah (22,
# always in the NHL's list) in the list it is dropped before the list is numbered and sent back to the service.
LIST_PATH = 'nhl/ui/features/season/vvms/selectteam/selectteam.lua'
LIST_ANCHOR = (b'\tself.mData = output.ResponseAsMapByUniqueId.get_team_selection_data.Output.TeamList\r\n')
LIST_NEW = LIST_ANCHOR + (
    b'    -- Overtime 2026 patch: only the NHL has the expansion team (Seattle, 499).\r\n'
    b'    local nhl = false\r\n'
    b'    for i = 1, #self.mData do\r\n'
    b'        if self.mData[i].TeamId == 22 then nhl = true end\r\n'
    b'    end\r\n'
    b'    if not nhl then\r\n'
    b'        for i = #self.mData, 1, -1 do\r\n'
    b'            if self.mData[i].TeamId == 499 then table.remove(self.mData, i) end\r\n'
    b'        end\r\n'
    b'    end\r\n')
# Seattle in Be a Pro (with xmlpatch bap32, which keeps the expansion team on its stock id 399 in Choose Team only
# while the 32-team switch is live; without it these edits never run). Picking 399 plays as 499 and the service
# sets the mode-creation team list the way Season's configuration:default:set builds it (league 0's teams by
# Exhibition, their misc info, 499 as conference 6, division 9, affiliate 498) before the league add, which the
# patched builder copies into a 32-team league. default:set itself crashes from Be a Pro (run b4). Run c2, 2026-10-28.
# The league gives each position its stock division and ignores DivisionId here (run p3), and the position is the
# order of the list: the list puts the expansion team where Utah stood (slot 22, Pacific) and Utah last (slot 31,
# Central), as Franchise does, so each plays the real 2026-27 calendar of its own place (lab 2026-11-01: slot 22 =
# Seattle with 28 Pacific games, slot 31 = Utah with 28 Central games).
BAP_FLOW_PATH = 'nhl/ui/features/beapro/services/creationflow/bapcreationflowservice.lua'
BAP_TEAM_PATH = 'nhl/ui/features/beapro/vvms/beaprocreationteam/beaprocreationteam.lua'
BAP_PATHS = (BAP_FLOW_PATH, BAP_TEAM_PATH)
BAP_FLOW_ANCHOR = b'function BapCreationFlowService:_CreateLeague(data, callback)\r\n'
BAP_FLOW_NEW = b'''\
-- Overtime 2026 patch: with the expansion team picked from Choose Team, the league gets the 32-team list
function BapCreationFlowService:_CreateLeague(data, callback)
    if self.mTeamInfo ~= nil and self.mTeamInfo.Expansion32 then
        self:_SetExpansionTeams(function() self:_AddLeague(data, callback) end)
    else
        self:_AddLeague(data, callback)
    end
end

function BapCreationFlowService:_DataRequest(urn, input, callback)
    local serviceRequestInput =
    {
            RequestMode = "Parallel",
            ResponseFormat = "MapByUniqueId",
            RequestList = { { URN = urn, Input = input, ID = "data_request" } }
    }
    self.mBapCreationFlowServiceAdapter:RequestService(serviceRequestInput, function(success, output)
        local response = success and output ~= nil and output.ResponseAsMapByUniqueId ~= nil
                         and output.ResponseAsMapByUniqueId.data_request or nil
        callback(response ~= nil and response.Output or nil)
    end)
end

function BapCreationFlowService:_SetExpansionTeams(done)
    self:_DataRequest("nhl-data:team:id:by-league-id:get:01.00.00", { LeagueIdList = { 0 }, Context = "Exhibition" },
        function(ids)
            if ids == nil or ids.TeamIdList == nil then return done() end
            self:_DataRequest("nhl-data:team:misc:info:get:01.00.00", { Context = "Exhibition", TeamIdList = ids.TeamIdList },
                function(misc)
                    if misc == nil or misc.TeamMiscList == nil then return done() end
                    local teams = {}
                    for _, team in ipairs(misc.TeamMiscList) do
                        if team.TeamId ~= 499 and team.Misc ~= nil then
                            table.insert(teams, { TeamId = team.TeamId, ConferenceId = team.Misc.ConferenceId,
                                                  DivisionId = team.Misc.DivisionId, UserControlled = false,
                                                  AffiliateTeamId = team.Misc.AffiliateId })
                        end
                    end
                    -- the list order is the league's slot order: Seattle takes Utah's slot 22 (Pacific) and Utah
                    -- goes last, as in Franchise, so each plays the real 2026-27 calendar of its own place
                    local seattle = { TeamId = 499, ConferenceId = 6, DivisionId = 9,
                                      UserControlled = false, AffiliateTeamId = 498 }
                    local utah
                    for i, team in ipairs(teams) do
                        if team.TeamId == 22 then utah = i end
                    end
                    if utah ~= nil then
                        table.insert(teams, teams[utah])
                        teams[utah] = seattle
                    else
                        table.insert(teams, seattle)
                    end
                    self:_DataRequest("nhl-data:mode-creation:teams:info:set:01.00.00", { TeamList = teams },
                        function() done() end)
                end)
        end)
end

function BapCreationFlowService:_AddLeague(data, callback)
'''.replace(b'\n', b'\r\n')
BAP_TEAM_ANCHOR = (b'        TeamId = self.mTeamsList:getCurrentItem().TeamId\r\n'
                   b'    }\r\n'
                   b'\r\n'
                   b'    local selectedteaminfo = \r\n'
                   b'    {\r\n'
                   b'        TeamArtId =  self.mTeamLogoArtId,\r\n'
                   b'        TeamColorId =  self.mTeamColor\r\n'
                   b'    }\r\n')
BAP_TEAM_NEW = BAP_TEAM_ANCHOR + b'''\
    -- Overtime 2026 patch: Choose Team shows the expansion team on its stock id (399); it plays as 499 in a
    -- 32-team league
    if inputs.LeagueId == 0 then
        for _, team in ipairs(self.mSelectedLeagueData.TeamList or {}) do
            if team.TeamId == 399 then selectedteaminfo.Expansion32 = true end
        end
        if inputs.TeamId == 399 then inputs.TeamId = 499 end
    end
'''.replace(b'\n', b'\r\n')


class PatchError(Exception):
    pass


def overlay_dir(game_dir):
    return textpack.overlay_dir(game_dir)


def state_path(game_dir):
    return os.path.join(overlay_dir(game_dir), STATE_NAME)


def _shadps4_processes():
    """The lower-case names of the running shadPS4 processes: the emulator's and QtLauncher's."""
    try:
        if sys.platform == 'win32':
            out = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, timeout=30,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
            names = [line.split('","')[0].strip('"') for line in out.splitlines()]
        else:
            out = subprocess.run(['ps', '-A', '-o', 'comm='], capture_output=True, text=True, timeout=30).stdout
            names = [os.path.basename(line.strip()) for line in out.splitlines()]
    except (OSError, subprocess.SubprocessError):
        return []
    return [n.lower() for n in names if n.lower().startswith('shadps4')]


def emulator_running():
    """True while a shadPS4 emulator process runs (any build: shadPS4.exe, shadPS419.exe, ...)."""
    return any('launcher' not in n for n in _shadps4_processes())    # not the Qt launcher


def launcher_running():
    """True while QtLauncher runs."""
    return any('launcher' in n for n in _shadps4_processes())


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _clean(text):
    return text.replace('™', '').replace('®', '').strip()  # trademark signs


def _load_state(game_dir):
    try:
        with open(state_path(game_dir), encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _rel(game_dir, path):
    return gamefiles.rel(game_dir, path)


def _target(game_dir, rel):
    return os.path.join(overlay_dir(game_dir), *rel.split('/'))


def names_strings(raw, meta):
    """The names layer's {stringid: text}, after checking each id still has its stock text in `raw`."""
    live = textpack.read_strings(raw, meta, NAMES)
    wrong = [f'{sid} is {live.get(sid)!r}, expected {old!r}' for sid, (old, _new) in NAMES.items()
             if sid not in live or _clean(live[sid]) not in (old, _clean(NAMES[sid][1]))]
    if wrong:
        raise PatchError('names layer: the loc database is not the one this patch knows (' + '; '.join(wrong) + ')')
    return {sid: new for sid, (_old, new) in NAMES.items()}


def capdefs_2026(raw, path=CAPDEFS_PATH):
    """capdefs.brk with the 2026-27 money table, after checking it holds the stock one."""
    rows = f'<{12 * len(ROWS_STOCK)}H'
    if (len(raw) < ROWS_AT + struct.calcsize(rows) or struct.unpack_from('<2H', raw, CAP_AT) != CAP_STOCK
            or struct.unpack_from(rows, raw, ROWS_AT) != sum(ROWS_STOCK, ())):
        raise PatchError(f'league layer: {path} is not the capdefs.brk this patch knows')
    out = bytearray(raw)
    struct.pack_into('<2H', out, CAP_AT, *CAP_2026)
    struct.pack_into(rows, out, ROWS_AT, *sum(ROWS_2026, ()))
    return bytes(out)


def salary_schema(raw, path):
    """A league creation schema with the $80M limit on TeamCapSalary / TeamCurrentSalary raised."""
    if raw.count(SALARY_LIMIT_STOCK) != 2:
        raise PatchError(f'league layer: {path} does not hold the two $80M salary limits')
    return raw.replace(SALARY_LIMIT_STOCK, SALARY_LIMIT)


def select_team_2026(raw, path=SELECT_TEAM_PATH):
    """nhlselectteam.lua with the 2026-27 alignment in AddDataToTeams, after checking the stock function is there."""
    if raw.count(SELECT_TEAM_ANCHOR) != 1 or b'function NhlSelectTeam:AddDataToTeams()' not in raw:
        raise PatchError(f'league layer: {path} is not the nhlselectteam.lua this patch knows')
    return raw.replace(SELECT_TEAM_ANCHOR, SELECT_TEAM_ALIGN)


def list_2026(raw, path=LIST_PATH):
    """selectteam.lua without the expansion team in a league that is not the NHL, after checking the stock handler."""
    if raw.count(LIST_ANCHOR) != 1 or b'function SelectTeam:OnServiceResponse(' not in raw:
        raise PatchError(f'league layer: {path} is not the selectteam.lua this patch knows')
    return raw.replace(LIST_ANCHOR, LIST_NEW)


def bap_flow_2026(raw, path=BAP_FLOW_PATH):
    """bapcreationflowservice.lua with the 32-team list set before the league add (BAP_FLOW_NEW)."""
    if raw.count(BAP_FLOW_ANCHOR) != 1 or b'function BapCreationFlowService:_SetExpansionTeams' in raw:
        raise PatchError(f'league layer: {path} is not the bapcreationflowservice.lua this patch knows')
    return raw.replace(BAP_FLOW_ANCHOR, BAP_FLOW_NEW)


def bap_team_2026(raw, path=BAP_TEAM_PATH):
    """beaprocreationteam.lua with Choose Team's expansion team (399) played as 499 (BAP_TEAM_NEW)."""
    if raw.count(BAP_TEAM_ANCHOR) != 1:
        raise PatchError(f'league layer: {path} is not the beaprocreationteam.lua this patch knows')
    return raw.replace(BAP_TEAM_ANCHOR, BAP_TEAM_NEW)


def check_database(raw, game_dir):
    """A database for the database layer must parse with the game's own schema and have every table it has."""
    schema = parse_schema(gamefiles.schema_xml(game_dir)[0])
    stock = Database.parse(gamefiles.default_database(game_dir)[0], schema)
    try:
        db = Database.parse(raw, schema)
    except Exception as err:  # noqa: BLE001 - any parse failure means "not a database of this game"
        raise PatchError(f'database layer: not an NHL 19 database ({err})') from err
    missing = sorted({t.name for t in stock.tables} - {t.name for t in db.tables})
    if missing:
        raise PatchError(f'database layer: tables missing: {", ".join(missing)}')
    return db


def roster_file(db, game_dir):
    """The roster file (initial_experience.db) for a default database: its rosterupdate tables, in the order of
    the game's own roster file."""
    raw, _ = gamefiles.read_latest(game_dir, gamefiles.ROSTER_PATH)
    order = [t.tag for t in Database.parse(raw, verify=False).tables]
    return db.subset('rosterupdate', order=order).to_bytes()


def mode_roster_files(db, game_dir):
    """{path: bytes} of the Franchise start rosters (MODE_ROSTERS) for a default database: each of the game's
    files with its tables replaced by the database's, in the file's own order.

    The expansion career's start roster (EXPANSION_ROSTER) comes from a copy with the expansion team emptied
    (rosterupdate.empty_expansion): its players are free agents there and Seattle builds its team in the expansion
    draft. The database itself keeps Seattle filled for every other mode."""
    from . import rosterupdate  # rosterupdate's imports never reach overlay: no cycle
    out = {}
    for path in MODE_ROSTERS:
        src = db
        if path == EXPANSION_ROSTER:
            src = Database.parse(db.to_bytes(), parse_schema(gamefiles.schema_xml(game_dir)[0]))
            rosterupdate.empty_expansion(src)
        raw, _ = gamefiles.read_latest(game_dir, path)
        own = Database.parse(raw, verify=False)
        out[path] = Database([src[t.tag] for t in own.tables], own._header).to_bytes()
    return out


def _base_copy(archive, tmp):
    """Copy a game archive for the overlay, undoing an old in-place text pack edit if the game copy has one."""
    shutil.copyfile(archive, tmp)
    in_place = textpack._load_json(archive + LEGACY_SUFFIX)
    if in_place:
        eb.restore_entry(tmp, in_place['record'])


def _current_database(game_dir, state):
    """The default database the applied patch serves (to keep the database layer when re-applying others)."""
    if not state or 'database' not in state.get('layers', {}):
        return None
    archive = textpack._winner(game_dir, gamefiles.DB_PATH)
    target = _target(game_dir, _rel(game_dir, archive))
    if not os.path.exists(target):
        return None
    with eb.EbArchive(target) as arc:
        return arc.read(gamefiles.DB_PATH)


def _current_art(game_dir, state):
    """The art the applied patch serves, as one art_mod.Pack holding the served packs' records (to keep the art layer
    when re-applying others), or None."""
    if not state or 'art' not in state.get('layers', {}):
        return None
    files = {}
    for rel, rec in state.get('files', {}).items():
        target = _target(game_dir, rel)
        if rec.get('new') and os.path.exists(target):
            with eb.EbArchive(target) as arc:
                for entry, (_off, size) in arc.entries.items():
                    files[entry] = art_mod.Stored(size, functools.partial(_read_entry, target, entry))
    if not files:
        return None
    return art_mod.Pack('served', {'packs': state['layers']['art'].get('packs', [])}, files)


def _read_entry(archive, entry):
    with art_mod._opened(eb.EbArchive, archive) as arc:
        return arc.read(entry)


def _art_record(packs):
    out = []
    for p in packs:
        out += p.info['packs'] if 'packs' in p.info else [p.record()]
    return out


def _read_winner(game_dir):
    def read(path):
        with eb.EbArchive(textpack._winner(game_dir, path)) as arc:
            return arc.read(path)
    return read


def _served_menus(state):
    """The menus options the applied patch serves (to keep them when re-applying). A patch applied before the `news`
    option existed recorded it only as the layer's `news` flag: that is what it serves."""
    rec = (state or {}).get('layers', {}).get('menus') or {}
    served = rec.get('options')
    if served is not None and 'news' not in served and 'news' in rec:
        served = dict(served, news=bool(rec['news']))
    return served


def build(game_dir, layers, pack=None, database=None, lang='eng_us', menus=None, art=None, launch=None):
    """_build, with each game archive's table of contents parsed once (the layers look up the winning copy of
    their files many times over; building writes no archive it reads)."""
    with eb.cached_tocs():
        return _build(game_dir, layers, pack, database, lang, menus, art, launch)


def _build(game_dir, layers, pack=None, database=None, lang='eng_us', menus=None, art=None, launch=None):
    """{game archive path: {entry: new bytes}} and the layer records for the state file. An archive path that is not
    in the game folder is a new archive (the art layer's). `launch` ({'until': unix seconds}) is the menus layer's
    zero-press hook (set_menus); apply never passes it, so a full apply serves the stock menus."""
    unknown = set(layers) - set(LAYERS)
    if unknown:
        raise PatchError(f'unknown layer(s): {", ".join(sorted(unknown))}')
    edits, info = {}, {}
    if 'text' in layers or 'names' in layers:
        db_path = textpack.loc_paths(lang)[0]
        archive = textpack._winner(game_dir, db_path)
        meta = textpack.loc_meta(game_dir, lang)
        tmp_dir = overlay_dir(game_dir)
        with eb.EbArchive(archive) as arc:
            raw = arc.read(db_path)
        record = textpack._load_json(archive + LEGACY_SUFFIX)
        if record:  # the game copy has an old in-place edit: read the original entry
            os.makedirs(tmp_dir, exist_ok=True)
            probe = os.path.join(tmp_dir, 'probe.tmp')
            _base_copy(archive, probe)
            with eb.EbArchive(probe) as arc:
                raw = arc.read(db_path)
            os.remove(probe)
        strings = {}
        if 'names' in layers:
            strings.update(names_strings(raw, meta))
            info['names'] = {'strings': len(NAMES), 'file': lang}
        if 'text' in layers:
            pack = pack or textpack.load_pack(lang=lang)
            clash = sorted(set(pack['strings']) & set(strings))
            if clash:
                raise PatchError(f'text pack and names layer both set {", ".join(clash)}')
            strings.update(pack['strings'])
            info['text'] = {'language': pack['language'], 'file': lang, 'strings': len(pack['strings']),
                            'pack_sha256': hashlib.sha256(json.dumps(pack, sort_keys=True).encode()).hexdigest()}
        new, missing = textpack.edit_database(raw, meta, strings)
        if missing:
            raise PatchError(f'string ids not in {db_path}: {", ".join(missing)}')
        if textpack.read_strings(new, meta, strings) != strings:
            raise PatchError('edited loc database does not read back the patch strings')
        edits.setdefault(archive, {})[db_path] = new
    if 'database' in layers:
        if database is None:
            raise PatchError('database layer: no database given')
        db = check_database(database, game_dir)
        # the portrait flags follow the art served (art_mod.portrait_flags): the same database serves both ways
        schema = parse_schema(gamefiles.schema_xml(game_dir)[0])
        stock = Database.parse(gamefiles.default_database(game_dir)[0], schema)
        served = art if 'art' in layers and art else []
        changed = art_mod.portrait_flags(db, stock, art_mod.merge(served) if served else {})
        changed += art_mod.alternate_rows(db, served)   # NHL 27 alternates ride on throwback rows (build_alts)
        if changed:
            database = db.to_bytes()
        roster = roster_file(db, game_dir)
        modes = mode_roster_files(db, game_dir)
        for path, raw in [(gamefiles.DB_PATH, database), (gamefiles.ROSTER_PATH, roster)] + sorted(modes.items()):
            edits.setdefault(textpack._winner(game_dir, path), {})[path] = raw
        info['database'] = {'bytes': len(database), 'sha256': hashlib.sha256(database).hexdigest(),
                            'roster_bytes': len(roster),
                            'mode_rosters': sorted(os.path.basename(p) for p in modes)}
    if 'league' in layers:
        for path, edit in ([(CAPDEFS_PATH, capdefs_2026), (SELECT_TEAM_PATH, select_team_2026),
                            (LIST_PATH, list_2026), (BAP_FLOW_PATH, bap_flow_2026), (BAP_TEAM_PATH, bap_team_2026)]
                           + [(p, salary_schema) for p in SALARY_SCHEMAS]):
            archive = textpack._winner(game_dir, path)
            with eb.EbArchive(archive) as arc:
                raw = arc.read(path)
            edits.setdefault(archive, {})[path] = edit(raw, path)
        info['league'] = {'floor': CAP_2026[0] * 100_000, 'cap': CAP_2026[1] * 100_000,
                          'lowest_salary': LOWEST_2026[0] * 1000, 'elc_max': ROWS_2026[3][0] * 1000,
                          'alignment': 'SEA Pacific, UTA Central'}
    if 'menus' in layers:
        try:
            opts = menus_mod.options(menus)
            new = menus_mod.edits(_read_winner(game_dir), opts, launch)
        except menus_mod.MenuError as err:
            raise PatchError(f'menus layer: {err}') from err
        for path, raw in new.items():
            edits.setdefault(textpack._winner(game_dir, path), {})[path] = raw
        info['menus'] = menus_mod.record(opts, launch)
    if 'art' in layers:
        if not art:
            raise PatchError('art layer: no art pack given')
        try:
            new, record = art_mod.edits(game_dir, art_mod.merge(art))
        except art_mod.ArtError as err:
            raise PatchError(f'art layer: {err}') from err
        clash = sorted(set(new) & set(edits))
        if clash:
            raise PatchError(f'art layer: {", ".join(clash)} is edited by another layer')
        edits.update(new)
        info['art'] = {'packs': _art_record(art), 'archives': record,
                       'textures': len(set().union(*(set(e) for e in new.values())))}
    return edits, info


def layer_fits(game_dir, layer, lang):
    """Whether the text or names layer can be made on `lang`'s text file: every string the pack sets is there, and the
    names layer's stock texts (another English than eng_us: CUSA11116). Nothing is written."""
    try:
        build(game_dir, [layer], lang=lang)
    except (PatchError, FileNotFoundError, KeyError):
        return False
    return True


def apply(game_dir, layers=('text', 'names'), pack=None, database=None, lang='eng_us', running=None, menus=None,
          art=None):
    """Write the overlay for `layers` (replacing whatever an earlier apply wrote). The game folder is only read.

    `database` is the whole nhl_game.db for the database layer; when the layer is asked for without one, the
    database the patch already serves is kept. `menus` is the menus layer's options ({'chel': bool, 'news':
    bool}); the ones served now are kept for every option not given. `art` is the art layer's packs ([art_mod.Pack], a later one
    wins); without them the art the patch already serves is kept. Returns the new state."""
    if (running or emulator_running)():
        raise PatchError('shadPS4 is running: close the game first')
    with art_mod.reading():     # one handle per pack zip / archive the art is read from, not one per texture
        return _apply(game_dir, tuple(layers), pack, database, lang, menus, art)


def _apply(game_dir, layers, pack, database, lang, menus, art):
    old = _load_state(game_dir)
    if 'database' in layers and database is None:
        database = _current_database(game_dir, old)
    if 'menus' in layers:
        try:
            menus = menus_mod.options(menus, _served_menus(old))
        except menus_mod.MenuError as err:
            raise PatchError(f'menus layer: {err}') from err
    if 'art' in layers and not art:
        served = _current_art(game_dir, old)
        art = [served] if served else None
    edits, info = build(game_dir, layers, pack, database, lang, menus, art)
    ours = dict((old or {}).get('files', {}))
    stamp = _stamp(game_dir)
    rels = {archive: _rel(game_dir, archive) for archive in edits}
    for rel in rels.values():  # before anything is written: whose is the file at each path?
        target = _target(game_dir, rel)
        if rel in ours:
            if os.path.exists(target) and not _intact(target, ours[rel], stamp):
                raise PatchError(f'{target} changed since the patch wrote it: check it and delete it by hand')
        elif os.path.exists(target) and not os.path.exists(target + LEGACY_SUFFIX)                 and os.path.exists(_backup(game_dir, rel)):
            raise PatchError(f'{_backup(game_dir, rel)} is in the way: check it and delete it by hand')
    written = {}
    tmps = []
    hashed = {}     # rel: sha256 of a new archive, taken as eb.new_archive wrote it

    def save(files, layers_info):
        """The state as it is on disk now: every file of ours listed, so undo always reaches stock."""
        st = {'version': VERSION, 'applied': datetime.datetime.now().isoformat(timespec='seconds'),
              'game_dir': os.path.abspath(game_dir), 'layers': layers_info, 'files': files}
        tmp = state_path(game_dir) + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(st, f, indent=1)
        os.replace(tmp, state_path(game_dir))
        return st

    try:
        for archive, entries in edits.items():
            rel = rels[archive]
            target = _target(game_dir, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            tmp = target + '.tmp'
            tmps.append((tmp, target, rel))
            new = not os.path.exists(archive)
            if new:  # the art layer's own archive: only its entries
                # hashed as it was written; each file was checked against its pack's sha256 as it was read for it.
                # Its table is checked here (every entry, at its size); the bytes at the end (_verify_written)
                hashed[rel] = eb.new_archive(tmp, entries)
                with eb.EbArchive(tmp) as arc:
                    for entry, data in entries.items():
                        if arc.entries.get(entry.lower(), (0, -1))[1] != len(data):
                            raise PatchError(f'{rel}: {entry} is not in the written archive at its size')
            else:
                _base_copy(archive, tmp)
                for entry, data in entries.items():
                    eb.append_entry(tmp, entry, data)
                with eb.EbArchive(tmp) as arc:      # a few small files: read back at once
                    for entry, data in entries.items():
                        if arc.read(entry) != data:
                            raise PatchError(f'{rel}: {entry} did not read back')
            if new:
                written[rel] = {'new': True, 'entries': sorted(entries), 'size': os.path.getsize(tmp)}
            else:
                st = os.stat(archive)
                written[rel] = {'source_size': st.st_size, 'source_mtime': int(st.st_mtime),
                                'entries': sorted(entries), 'size': os.path.getsize(tmp)}
        art_mod.release()   # the served art read back (_current_art) is in the archives replaced below
        partial = dict((old or {}).get('layers', {}), partial=True)
        for tmp, target, rel in tmps:
            if (old or {}).get('files', {}).get(rel, {}).get('backup'):
                written[rel]['backup'] = True
            elif rel not in ours and os.path.exists(target) and not os.path.exists(target + LEGACY_SUFFIX):
                # someone else's file at this path (a user's own patch archive): kept aside, put back by undo
                os.makedirs(os.path.dirname(_backup(game_dir, rel)), exist_ok=True)
                os.replace(target, _backup(game_dir, rel))
                written[rel]['backup'] = True
            ours[rel] = dict(written[rel])
            save(ours, partial)
            os.replace(tmp, target)
            written[rel]['sha256'] = ours[rel]['sha256'] = hashed.get(rel) or _sha256(target)
            save(ours, partial)
    except art_mod.ArtError as err:     # a pack changed after it was read (art.Stored)
        raise PatchError(f'art layer: {err}') from err
    finally:
        for tmp, _target_path, _rel_ in tmps:
            if os.path.exists(tmp):
                os.remove(tmp)
    for rel in written:  # the text pack's own state file, from before this module, is ours too
        legacy = _target(game_dir, rel) + LEGACY_SUFFIX
        if os.path.exists(legacy):
            os.remove(legacy)
    for rel in (old or {}).get('files', {}):
        if rel not in written:
            _remove_ours(game_dir, rel, old['files'][rel], stamp)
            ours.pop(rel, None)
            if ours:
                save(ours, dict(info, partial=True))
    if edits:
        state = save(written, info)
        _verify_written(game_dir, written, hashed, ours, save, info)
    else:
        state = {'version': VERSION, 'applied': datetime.datetime.now().isoformat(timespec='seconds'),
                 'game_dir': os.path.abspath(game_dir), 'layers': info, 'files': written}
        _forget(game_dir)
    return state


def _verify_written(game_dir, written, hashed, ours, save, info):
    """The end of a Patch: every new archive read back from disk whole and its sha256 compared with the one taken as it
    was written (the bytes shadPS4 will read, through the same file cache). A file that does not match is removed with
    its record, so the next Patch writes it again from the packs (they stay in the cache), and the Patch fails saying
    so. Several files are read at once (workers.ordered)."""
    from . import workers
    jobs = ((rel, (_target(game_dir, rel),)) for rel in sorted(hashed) if rel in written)
    bad = [rel for rel, sha, _err in workers.ordered(jobs, _sha256, ()) if sha != hashed[rel]]
    if not bad:
        return
    for rel in bad:
        try:
            os.remove(_target(game_dir, rel))
        except OSError:
            pass
        written.pop(rel, None)
        ours.pop(rel, None)
    save(written, dict(info, partial=True))
    raise PatchError(f'{", ".join(bad)} did not read back as written (disk or memory error?): removed. '
                     'Press Patch again to write it again.')


def _backup(game_dir, rel):
    """Where a file of someone else's that sat at an overlay path is kept while the patch serves its own."""
    return os.path.join(overlay_dir(game_dir), BACKUP_DIR, *rel.split('/'))


def _remove_ours(game_dir, rel, rec, stamp):
    """Remove one overlay file this patch wrote, only if it is still what was written (_intact; `stamp`: the state
    file's mtime as the patch left it). True when removed."""
    path = _target(game_dir, rel)
    removed = False
    if os.path.exists(path):
        if not _intact(path, rec, stamp):
            raise PatchError(f'{path} changed since the patch wrote it: left in place, check it and delete it by hand')
        os.remove(path)
        removed = True
    kept = _backup(game_dir, rel)
    if rec.get('backup') and os.path.exists(kept):  # the file that was there before the patch comes back
        os.replace(kept, path)
    return removed


def _forget(game_dir):
    """Remove the state file and the overlay folders left empty (never a folder with someone else's files)."""
    p = state_path(game_dir)
    if os.path.exists(p):
        os.remove(p)
    top = overlay_dir(game_dir)
    for here, _dirs, _files in sorted(os.walk(top), key=lambda w: -len(w[0])):
        if not os.listdir(here):
            os.rmdir(here)


def _legacy_files(game_dir):
    """Overlay archives the text pack wrote before this module (`<archive>.overtime-text.json` beside them)."""
    out = []
    big_dir = os.path.join(overlay_dir(game_dir), 'databigs')
    if os.path.isdir(big_dir):
        for name in os.listdir(big_dir):
            if name.endswith(LEGACY_SUFFIX):
                out.append(os.path.join(big_dir, name[:-len(LEGACY_SUFFIX)]))
    return out


def set_menus(game_dir, launch=None, running=None):
    """Rewrite only the menus layer's archive (boot.big) with the zero-press hook on (`launch`: {'until': unix
    seconds, 'diag': bool}) or off (None); every other layer's file stays. Entries other layers keep in that archive
    (league) are carried over from the overlay's own copy. A hook that is left on (a crash, the game started outside
    the app) does nothing once its time has passed, and any full apply puts the stock menus back. Returns the state."""
    if (running or emulator_running)():
        raise PatchError('shadPS4 is running: close the game first')
    old = _load_state(game_dir)
    if not old or 'menus' not in old.get('layers', {}):
        raise PatchError('the menus layer is not applied: apply the patch first')
    opts = menus_mod.options(None, _served_menus(old))
    try:
        new = menus_mod.edits(_read_winner(game_dir), opts, launch)
    except menus_mod.MenuError as err:
        raise PatchError(f'menus layer: {err}') from err
    archives = {}
    for path, raw in new.items():
        archives.setdefault(textpack._winner(game_dir, path), {})[path] = raw
    ours = dict(old['files'])
    stamp = _stamp(game_dir)
    for archive, entries in archives.items():
        rel = _rel(game_dir, archive)
        target = _target(game_dir, rel)
        rec = ours.get(rel)
        if rec is None or not os.path.exists(target):
            raise PatchError(f'{rel} is not a file the patch wrote: apply the patch first')
        if not _intact(target, rec, stamp):
            raise PatchError(f'{target} changed since the patch wrote it: check it and delete it by hand')
        with eb.EbArchive(target) as served:  # what other layers keep in this archive
            carried = {e: served.read(e) for e in rec.get('entries', []) if e not in menus_mod.LAUNCH_PATHS}
        entries = {**carried, **entries}
        tmp = target + '.tmp'
        try:
            _base_copy(archive, tmp)
            for entry, data in entries.items():
                eb.append_entry(tmp, entry, data)
            with eb.EbArchive(tmp) as arc:
                for entry, data in entries.items():
                    if arc.read(entry) != data:
                        raise PatchError(f'{rel}: {entry} did not read back')
            st = os.stat(archive)
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        ours[rel] = dict(rec, source_size=st.st_size, source_mtime=int(st.st_mtime), entries=sorted(entries),
                         sha256=_sha256(target), size=os.path.getsize(target))
    layers = dict(old['layers'], menus=menus_mod.record(opts, launch))
    state = dict(old, applied=datetime.datetime.now().isoformat(timespec='seconds'), layers=layers, files=ours)
    tmp = state_path(game_dir) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, state_path(game_dir))
    return state


def undo(game_dir, running=None):
    """Remove every overlay file the patch wrote. Returns the paths removed."""
    if (running or emulator_running)():
        raise PatchError('shadPS4 is running: close the game first')
    done = []
    state = _load_state(game_dir) or {}
    stamp = _stamp(game_dir)
    for rel, rec in state.get('files', {}).items():
        if _remove_ours(game_dir, rel, rec, stamp):
            done.append(_target(game_dir, rel))
    for archive in _legacy_files(game_dir):
        for p in (archive, archive + LEGACY_SUFFIX):
            if os.path.exists(p):
                os.remove(p)
                done.append(p)
    for big in gamefiles.archives(game_dir):  # an old in-place text pack edit of the game archive itself
        if textpack.restore_in_place(big):
            done.append(big)
    if state or done:
        _forget(game_dir)
    return done


def _untouched(path, rec, stamp):
    """An overlay archive as written: the size recorded for it, and no newer than the state file (`stamp`) written
    after it. Reading gigabytes at each look at the game (and again at each Patch) is too slow. A record from before
    copies kept their size has none: those are hashed."""
    st = os.stat(path)
    return rec.get('size') is not None and rec.get('size') == st.st_size and stamp is not None \
        and st.st_mtime_ns <= stamp


def _stamp(game_dir):
    """The state file's mtime (ns), None without one."""
    try:
        return os.stat(state_path(game_dir)).st_mtime_ns
    except OSError:
        return None


def _intact(path, rec, stamp):
    """An existing overlay file is still the one the patch wrote: untouched by size and time, else by its sha256."""
    return not rec.get('sha256') or _untouched(path, rec, stamp) or _sha256(path) == rec['sha256']


def status(game_dir, lang='eng_us'):
    """What the patch serves now: layers, files (present, unchanged), and whether the game changed under it."""
    state = _load_state(game_dir)
    out = {'overlay': overlay_dir(game_dir), 'applied': bool(state), 'layers': {}, 'files': {}, 'problems': [],
           'legacy_text_pack': [p for p in _legacy_files(game_dir) if os.path.exists(p)]}
    if not state:
        if out['legacy_text_pack']:  # the text pack's own overlay from before this module: still served
            out.update(applied=True, layers={'text': {'legacy': True}})
        return out
    out.update(applied_at=state.get('applied'), layers=state.get('layers', {}))
    stamp = _stamp(game_dir)
    for rel, rec in state.get('files', {}).items():
        path = _target(game_dir, rel)
        source = gamefiles.locate(game_dir, rel)
        present = os.path.exists(path)
        same = present and (_untouched(path, rec, stamp) or _sha256(path) == rec.get('sha256'))
        out['files'][rel] = {'present': present, 'unchanged': same}
        if not present:
            out['problems'].append(f'{rel}: missing from the overlay (apply again)')
        elif not same:
            out['problems'].append(f'{rel}: changed since the patch wrote it')
        if rec.get('new') and os.path.exists(source):
            out['problems'].append(f'{rel}: the game has an archive of this name now (game update?): apply again')
        elif os.path.exists(source) and os.path.getsize(source) != rec.get('source_size'):
            out['problems'].append(f'{rel}: the game archive changed (game update?): apply again')
    return out
