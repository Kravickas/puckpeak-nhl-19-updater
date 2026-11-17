"""The starter profile: a brand-new NHL 19 `Profile0` for a player who never started the game (plan section B).

A save with `MiscFlags.IsFirstBoot` 0 skips the game's first-run onboarding (`pressstart.lua`: `OnGetUserProfileMiscCallback`
enters the normal boot only when the flag is present and 0; absent or other values run the first boot).

Nothing here is copied from anyone's save. The profile is built key by key from the tables below, in the order of the
game's own profile samples (key names and nesting: 48 local samples, all with the same key set). Values come from the
game's data where it has them (the mode list and flag names of `user_profile/misc.json`, the settings and hospitality
schemas) and otherwise from "never played": zero counts, empty lists, no favourite team.

Layout of the save (facts in docs/notes/starter-profile.md):
  INDEX, DATA       EA SaveLoad container (overtime_core.savefile): __SaveLoadFileInfo, __SaveLoadMetaData,
                    __SaveloadVer (double 30.0 + "1.60"), and the slot file `Profile0`
  Profile0          u8 1 + LZ4 frame of (JSON text, padded with NUL to a multiple of 4, binary tail) + u32 size
  sce_sys/param.sfo savegame.default_sfo, with DETAIL 'Profile Save' and ACCOUNT_ID zero
"""
import json
import os
import struct
import time

from overtime_core import savefile, sfo

from . import savegame

PROFILE = 'Profile0'
TITLE_ID = savegame.TITLE_ID
ROSTER_TYPES = ('Custom', 'Download', 'Online')
ROSTER_NONE = ('None', -1)

# __SaveloadVer of the profile samples: the double 30.0 (not 45.0 / 46.0 of the roster saves) and "1.60"
PROFILE_VER_PAYLOAD = struct.pack('<d', 30.0) + b'1.60'.ljust(64, b'\0')
META_PAYLOAD = b'Placeholder\0'                 # the game's own __SaveLoadMetaData of a profile (12 bytes)
FILE_INFO_PAYLOAD = savegame.FILE_INFO

# The flags the game keeps in MiscFlags.Flags, in the order of the samples, with the starter's value for each.
# Zero is "not seen". IsFirstBoot 0 is the gate (pressstart.lua). OnlineVersusGameSetupTutorial 1 skips the one
# online setup tutorial. The six franchise/resort tutorial flags stay unseen (0), as asked in plan section B.
MISC_FLAGS = (
    ('FirstTraitOnboardingComplete', 0),
    ('ClubCreationZone', 0),
    ('HUTHasSeenRewards', 0),
    ('ClubProgressionScreen', 0),
    ('LoadoutScreenTutorial', 0),
    ('HUTHasReadCollectionTooltip', 0),
    ('ResortDressingRoomTutorial', 0),
    ('HUTHasLoggedInBefore', 0),
    ('PlayerProgressionScreen', 0),
    ('BEAGM_Creation_PlayerMorale_FirstTimeExit', 0),
    ('TunerSetPopupStatus', 0),
    ('FriendsWidgetTutorial', 0),
    ('IsFirstBootflowMode', 0),
    ('PlayerCardTutorial', 0),
    ('ProAmOnboardingComplete', 0),
    ('HUTHasReadHubTooltip2', 0),
    ('BEAGM_Creation_HUB_PlayerMoraleExists', 0),
    ('PlayerCreationZone', 0),
    ('HUTHasReadHubTooltip1', 0),
    ('IsFirstBoot', 0),
    ('BEAGM_Creation_HUB_ChemistryExplanation', 0),
    ('OnlineVersusGameSetupTutorial', 1),
    ('TutorialFranchiseContractExtensions', 0),
    ('TutorialFranchiseHub', 0),
    ('TutorialFranchiseProtectionList', 0),
    ('TutorialProposeTrade', 0),
    ('TutorialProposeTradeOverlay', 0),
    ('TutorialResortHub', 0),
)

# The game's mode list (user_profile/misc.json, nhl-set:system:mode:name without None) and the modes PlayedModes counts.
MODE_INTROS = ('BeAGM', 'BeAPro', 'BootFlow', 'DebugSoak', 'Home', 'MomentsLive', 'PlayNow', 'PlayNowOnline',
               'Practice', 'Season', 'Playoff', 'Tournament', 'UltimateTeam', 'PlayNowOTP', 'Eashl',
               'OnlineShootout', 'OfflineShootout', 'HockeyDraft', 'ThreeOnThree')
PLAYED_MODES = ('PlayNow', 'PlayNowOnline', 'UltimateTeam', 'BeAGM', 'BeAPro', 'MomentsLive', 'Playoff', 'Tournament',
                'PlayNowOTP', 'Season', 'Eashl', 'OnlineShootout', 'OfflineShootout', 'HockeyDraft', 'ThreeOnThree')
INTRO_SKIP_SLOTS = 255                          # IntroCriteria.IntroSkipCounters: Max 255 (intro_criteria.json)
SETTING_GROUPS = 11                             # Settings.SettingGroupList: Max 11 (settings.json)

# PlayerClasses.CRCValue: the same string in all 48 local profiles, including the two that never downloaded anything
# (AITunerSets and ProAm read "0" in all 48). Not a CRC-32/MPEG-2 of any profile section (docs/notes/starter-profile.md).
PLAYER_CLASSES_CRC = '568547779'


class StarterError(ValueError):
    pass


def _roster(roster):
    """(ActiveRosterType, ActiveRosterSaveSlot) for the profile: None is the game's own roster (no active custom one)."""
    if roster is None:
        return ROSTER_NONE
    kind, slot = roster
    if kind not in ROSTER_TYPES:
        raise StarterError(f'roster type {kind!r} is not one of {ROSTER_TYPES}')
    if isinstance(slot, bool) or not isinstance(slot, int) or slot < 0:
        raise StarterError(f'roster slot {slot!r} must be a non-negative integer')
    return kind, slot


def build_profile(roster=None):
    """The profile as a dict (the JSON of `Profile0`), built key by key from the tables above. `roster` is None or
    (roster_type, slot): the roster the game plays (ActiveRosterType + ActiveRosterSaveSlot)."""
    kind, slot = _roster(roster)
    p = {}
    p['Customization'] = {'FeatureList': []}
    p['MomentsLive'] = {'ScenarioCompletedList': []}
    p['Roster'] = {'ActiveRosterSaveSlot': slot, 'ActiveRosterType': kind}
    p['Database'] = {'MaxSize': 0}
    p['AITunerSets'] = {'CRCValue': '0'}
    p['Advertisement'] = {'AdList': []}
    p['MiscFlags'] = {'Flags': [{'Value': v, 'StringId': k} for k, v in MISC_FLAGS]}
    p['PlayerClasses'] = {'CRCValue': PLAYER_CLASSES_CRC}
    p['PlayedModes'] = {
        'LastModesPlayed': [],
        'TotalTimesPlayed': [{'PlayCount': 0, 'Mode': m} for m in PLAYED_MODES],
        'LossStreak': 0,
    }
    p['ModeIntros'] = {'ModeIntroViewedList': [{'HasViewed': False, 'ModeName': m} for m in MODE_INTROS]}
    p['HospitalityScores'] = {'Side': 0, 'AwayScore': 0, 'HomeScore': 0, 'AwayId': 0, 'HomeId': 0,
                              'GameFinished': False}
    p['ProAm'] = {'CRCValue': '0'}
    p['Hospitality'] = {'UserHospitalityList': []}     # no entry = no favourite team (FavoriteTeamId has no "none")
    p['IntroCriteria'] = {
        'GlobalSkipCounter': 0,
        'IntroSkipCounters': [{'Count': 0, 'Index': i} for i in range(INTRO_SKIP_SLOTS)],
    }
    p['Settings'] = {'SettingGroupList': [
        {'SettingList': [], 'IsActive': False, 'Name': '', 'SettingGroupId': i} for i in range(SETTING_GROUPS)]}
    return p


def _text(v):
    """The game's JSON layout: one token per line. A member is `"key":` then its value; a dict or list value starts on
    the next line; members and items are separated by ",\\n"; an empty list is "[\\n]". Matches the samples byte for byte."""
    if isinstance(v, dict):
        return '{\n' + ',\n'.join(_member(k, x) for k, x in v.items()) + '\n}'
    if isinstance(v, list):
        return '[\n' + ',\n'.join(_text(x) for x in v) + '\n]' if v else '[\n]'
    return json.dumps(v)


def _member(k, x):
    head = json.dumps(k) + ':'
    return head + ('\n' + _text(x) if isinstance(x, (dict, list)) else _text(x))


def blank_tail():
    """The binary tail after the JSON: version 1 and an empty section table. The samples have six sections here (the
    controller and feedback blobs the game writes); the starter does not copy them (plan section B, rung c)."""
    return struct.pack('<II', 1, 0)


def profile_bytes(roster=None, tail=None):
    """The unpacked `Profile0` (before the LZ4 pack): the JSON padded with NUL to a multiple of 4, then the tail.
    `tail` None is blank_tail(); b'' writes the JSON alone (plan rung b)."""
    text = _text(build_profile(roster)).encode('ascii')
    pad = b'\0' * (-len(text) % 4)
    return text + pad + (blank_tail() if tail is None else tail)


def profile_payload(roster=None, tail=None):
    return savefile.pack_game(profile_bytes(roster, tail))


def container(roster=None, tail=None, stamp_ns=None):
    """(INDEX bytes, DATA bytes) of a starter profile, in the game's file order."""
    stamp = struct.pack('<Q', stamp_ns if stamp_ns is not None else time.time_ns())
    files = [savefile.SaveEntry('__SaveLoadFileInfo', stamp, FILE_INFO_PAYLOAD),
             savefile.SaveEntry('__SaveLoadMetaData', stamp, META_PAYLOAD),
             savefile.SaveEntry('__SaveloadVer', stamp, PROFILE_VER_PAYLOAD),
             savefile.SaveEntry(PROFILE, stamp, profile_payload(roster, tail))]
    return savefile.build(files)


def check_container(index, data, roster=None, tail=None):
    """Read a built container back and raise StarterError unless it gives back exactly the profile bytes."""
    by = {e.name: e for e in savefile.parse(index, data)}
    if set(by) != {PROFILE, '__SaveLoadFileInfo', '__SaveLoadMetaData', '__SaveloadVer'}:
        raise StarterError(f'container files: {sorted(by)}')
    if savefile.unpack(by[PROFILE].payload) != profile_bytes(roster, tail):
        raise StarterError('the container does not give back the same profile bytes')
    return True


def starter_sfo():
    """param.sfo of the profile folder: the roster save's layout (savegame.default_sfo), 'Profile Save' as its detail."""
    return sfo.patch(savegame.default_sfo(PROFILE, subtitle='User Profile', maintitle='User Profile',
                                                   title=TITLE_ID), {'DETAIL': 'Profile Save'})


def missing(save_dir):
    """True when player 1's save folder (the CUSA11126 savedata folder, paths.default_save_dir) has no Profile0."""
    return not os.path.exists(os.path.join(save_dir, PROFILE))


def write(save_dir, roster=None):
    """Write a new Profile0 into `save_dir` (created if needed) and return its path. Never overwrites: raises
    StarterError when Profile0 exists. `roster` is None or (roster_type, slot), as in build_profile."""
    if not missing(save_dir):
        raise StarterError(f'{PROFILE} already exists in {save_dir}; the starter never overwrites a save')
    _roster(roster)
    index, data = container(roster)
    check_container(index, data, roster)
    return savegame.write_new_folder(save_dir, PROFILE, index, data, starter_sfo())
