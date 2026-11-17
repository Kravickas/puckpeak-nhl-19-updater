"""The starter profile (overtime_roster/app/starter.py): a new Profile0 that skips first-run onboarding.

Synthetic data only: nothing here reads the owner's saves or the samples under re/extract. Every write goes to a
tmp folder.
"""
import json
import os
import struct

import pytest

from overtime_core import savefile, sfo
from overtime_roster.app import savegame, starter

FRANCHISE_FLAGS = ('TutorialFranchiseContractExtensions', 'TutorialFranchiseHub', 'TutorialFranchiseProtectionList',
                   'TutorialProposeTrade', 'TutorialProposeTradeOverlay', 'TutorialResortHub')
FLAG_NAMES = {
    'FirstTraitOnboardingComplete', 'ClubCreationZone', 'HUTHasSeenRewards', 'ClubProgressionScreen',
    'LoadoutScreenTutorial', 'HUTHasReadCollectionTooltip', 'ResortDressingRoomTutorial', 'HUTHasLoggedInBefore',
    'PlayerProgressionScreen', 'BEAGM_Creation_PlayerMorale_FirstTimeExit', 'TunerSetPopupStatus',
    'FriendsWidgetTutorial', 'IsFirstBootflowMode', 'PlayerCardTutorial', 'ProAmOnboardingComplete',
    'HUTHasReadHubTooltip2', 'BEAGM_Creation_HUB_PlayerMoraleExists', 'PlayerCreationZone', 'HUTHasReadHubTooltip1',
    'IsFirstBoot', 'BEAGM_Creation_HUB_ChemistryExplanation', 'OnlineVersusGameSetupTutorial',
} | set(FRANCHISE_FLAGS)
# every key the profile may hold (the game's user_profile schemas: misc.json, hospitality.json, settings.json,
# intro_criteria.json, and the samples' top level)
ALLOWED_KEYS = {
    'Customization', 'FeatureList', 'MomentsLive', 'ScenarioCompletedList', 'Roster', 'ActiveRosterSaveSlot',
    'ActiveRosterType', 'Database', 'MaxSize', 'AITunerSets', 'CRCValue', 'Advertisement', 'AdList', 'MiscFlags',
    'Flags', 'Value', 'StringId', 'PlayerClasses', 'PlayedModes', 'LastModesPlayed', 'TotalTimesPlayed', 'PlayCount',
    'Mode', 'LossStreak', 'ModeIntros', 'ModeIntroViewedList', 'HasViewed', 'ModeName', 'HospitalityScores', 'Side',
    'AwayScore', 'HomeScore', 'AwayId', 'HomeId', 'GameFinished', 'ProAm', 'Hospitality', 'UserHospitalityList',
    'IntroCriteria', 'GlobalSkipCounter', 'IntroSkipCounters', 'Count', 'Index', 'Settings', 'SettingGroupList',
    'SettingList', 'IsActive', 'Name', 'SettingGroupId',
}


def _walk(v, path='$'):
    if isinstance(v, dict):
        for k, x in v.items():
            yield path + '.' + k, k
            yield from _walk(x, path + '.' + k)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from _walk(x, f'{path}[{i}]')


def _unpacked(index, data):
    by = {e.name: e for e in savefile.parse(index, data)}
    return by, savefile.unpack(by[starter.PROFILE].payload)


def _json_of(unpacked):
    obj, end = json.JSONDecoder().raw_decode(unpacked.decode('ascii'))
    return obj, end


def _flags(obj):
    return {f['StringId']: f['Value'] for f in obj['MiscFlags']['Flags']}


# --- the JSON layout ---

def test_json_layout_is_the_game_style_one_token_per_line():
    text = starter._text({'a': {'b': [1, 2]}, 'c': []})
    assert text == '{\n"a":\n{\n"b":\n[\n1,\n2\n]\n},\n"c":\n[\n]\n}'
    assert json.loads(text) == {'a': {'b': [1, 2]}, 'c': []}


def test_profile_json_round_trips_through_the_container():
    index, data = starter.container(roster=None, stamp_ns=1)
    by, unpacked = _unpacked(index, data)
    obj, end = _json_of(unpacked)
    assert obj == starter.build_profile(None)
    assert unpacked[end:(end + 3) // 4 * 4] == b'\0' * ((end + 3) // 4 * 4 - end)   # NUL pad to a multiple of 4
    assert unpacked[(end + 3) // 4 * 4:] == starter.blank_tail()
    assert set(by) == {'__SaveLoadFileInfo', '__SaveLoadMetaData', '__SaveloadVer', starter.PROFILE}


def test_frame_is_the_game_layout_and_checksummed():
    payload = starter.profile_payload()
    assert payload[:1] == b'\x01'
    assert payload[1:5] == struct.pack('<I', 0x184D2204)
    assert payload[5] == 0x64 and payload[6] == 0x40          # FLG: content checksum; BD: 64 KB blocks
    assert struct.unpack_from('<I', payload, len(payload) - 4)[0] == len(starter.profile_bytes())
    assert savefile.unpack(payload) == starter.profile_bytes()


def test_container_check_rejects_a_different_profile():
    index, data = starter.container(stamp_ns=1)
    with pytest.raises(starter.StarterError):
        starter.check_container(index, data, roster=('Custom', 0))


def test_the_profile_is_checked_through_the_real_savefile_codec(tmp_path):
    index, data = starter.container(roster=('Download', 3), stamp_ns=7)
    folder = tmp_path / 'savedata' / starter.PROFILE
    folder.mkdir(parents=True)
    (folder / 'INDEX').write_bytes(index)
    (folder / 'DATA').write_bytes(data)
    entries = savefile.read_folder(str(folder))
    assert [e.name for e in entries] == ['__SaveLoadFileInfo', '__SaveLoadMetaData', '__SaveloadVer',
                                         starter.PROFILE]
    obj, _ = _json_of(savefile.unpack(entries[-1].payload))
    assert obj['Roster'] == {'ActiveRosterSaveSlot': 3, 'ActiveRosterType': 'Download'}


# --- what the profile says ---

def test_first_boot_flag_is_present_and_zero():
    obj, _ = _json_of(starter.profile_bytes())
    flags = _flags(obj)
    assert flags['IsFirstBoot'] == 0            # pressstart.lua: only a present 0 enters the normal boot


def test_tutorial_flags_follow_the_plan():
    flags = _flags(starter.build_profile())
    assert flags['OnlineVersusGameSetupTutorial'] == 1
    for name in FRANCHISE_FLAGS:
        assert flags[name] == 0, name


def test_allow_list_every_key_and_flag_is_known():
    obj = starter.build_profile(('Custom', 1))
    keys = {k for _, k in _walk(obj)}
    assert keys <= ALLOWED_KEYS, keys - ALLOWED_KEYS
    assert set(_flags(obj)) <= FLAG_NAMES
    assert set(_flags(obj)) == FLAG_NAMES          # the table holds every flag the game keeps
    for f in obj['MiscFlags']['Flags']:
        assert set(f) == {'Value', 'StringId'} and f['Value'] in (0, 1, 2)


def test_defaults_are_empty_or_zero():
    obj = starter.build_profile()
    assert obj['Customization'] == {'FeatureList': []}
    assert obj['MomentsLive'] == {'ScenarioCompletedList': []}
    assert obj['Advertisement'] == {'AdList': []}
    assert obj['Hospitality'] == {'UserHospitalityList': []}     # no favourite team: no entry
    assert obj['PlayedModes']['LastModesPlayed'] == []
    assert obj['PlayedModes']['LossStreak'] == 0
    assert all(m['PlayCount'] == 0 for m in obj['PlayedModes']['TotalTimesPlayed'])
    assert all(m['HasViewed'] is False for m in obj['ModeIntros']['ModeIntroViewedList'])
    assert obj['IntroCriteria']['GlobalSkipCounter'] == 0
    assert all(c['Count'] == 0 for c in obj['IntroCriteria']['IntroSkipCounters'])
    groups = obj['Settings']['SettingGroupList']
    assert len(groups) == 11 and all(g['SettingList'] == [] and g['IsActive'] is False for g in groups)
    assert obj['Database'] == {'MaxSize': 0}
    assert obj['AITunerSets'] == {'CRCValue': '0'} and obj['ProAm'] == {'CRCValue': '0'}


def test_roster_argument_sets_the_active_roster():
    assert starter.build_profile(None)['Roster'] == {'ActiveRosterSaveSlot': -1, 'ActiveRosterType': 'None'}
    assert starter.build_profile(('Online', 0))['Roster'] == {'ActiveRosterSaveSlot': 0, 'ActiveRosterType': 'Online'}
    for bad in (('Other', 0), ('Custom', -1), ('Custom', True), ('Custom', '2')):
        with pytest.raises(starter.StarterError):
            starter.build_profile(bad)


# --- privacy and determinism ---

def test_nothing_per_user_is_in_the_output():
    unpacked = starter.profile_bytes(('Custom', 2))
    assert b'UserId' not in unpacked
    obj, _ = _json_of(unpacked)
    assert all(k != 'UserId' for _, k in _walk(obj))


def test_same_input_gives_identical_bytes():
    assert starter.profile_bytes() == starter.profile_bytes()
    assert starter.profile_bytes(('Custom', 2)) == starter.profile_bytes(('Custom', 2))
    assert starter.container(('Custom', 2), stamp_ns=5) == starter.container(('Custom', 2), stamp_ns=5)
    assert starter.build_profile() == starter.build_profile()


def test_only_the_roster_argument_changes_the_profile():
    a, end_a = _json_of(starter.profile_bytes(None))
    b, end_b = _json_of(starter.profile_bytes(('Custom', 0)))
    assert a['Roster'] != b['Roster']
    a['Roster'] = b['Roster']
    assert a == b
    assert starter.profile_bytes(None)[-8:] == starter.blank_tail()
    assert starter.profile_bytes(('Custom', 0))[-8:] == starter.blank_tail()


def test_param_sfo_is_zero_account_and_fixed_title():
    raw = starter.starter_sfo()
    values = sfo.values(raw)
    assert values['ACCOUNT_ID'] == bytes(8)
    assert values['SAVEDATA_DIRECTORY'] == starter.PROFILE
    assert values['TITLE_ID'] == savegame.TITLE_ID
    assert values['DETAIL'] == 'Profile Save'


# --- disk ---

def test_missing_is_true_only_without_a_profile(tmp_path):
    save = tmp_path / 'savedata'
    assert starter.missing(str(save)) is True
    save.mkdir()
    assert starter.missing(str(save)) is True
    (save / starter.PROFILE).mkdir()
    assert starter.missing(str(save)) is False


def test_write_creates_a_profile_in_the_given_folder_only(tmp_path):
    save = tmp_path / 'savedata'
    save.mkdir()
    before = sorted(p.name for p in tmp_path.iterdir())
    path = starter.write(str(save), ('Custom', 2))
    assert os.path.normpath(path) == os.path.normpath(str(save / starter.PROFILE))
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert sorted(os.listdir(path)) == ['DATA', 'INDEX', 'NAME', 'sce_sys']
    assert open(os.path.join(path, 'NAME'), 'rb').read() == b'Profile0'
    assert starter.missing(str(save)) is False
    assert savegame.active_roster(str(save)) == 'RosterCustom2'
    assert [n for n in os.listdir(save) if n.startswith('.overtime-')] == []


def test_write_without_a_roster_plays_the_game_roster(tmp_path):
    save = tmp_path / 'savedata'
    save.mkdir()
    starter.write(str(save))
    assert savegame.active_roster(str(save)) is None


def test_write_refuses_an_existing_profile_and_leaves_it_alone(tmp_path):
    save = tmp_path / 'savedata'
    existing = save / starter.PROFILE
    existing.mkdir(parents=True)
    (existing / 'INDEX').write_bytes(b'keep me')
    with pytest.raises(starter.StarterError, match='already exists'):
        starter.write(str(save))
    assert (existing / 'INDEX').read_bytes() == b'keep me'
    assert sorted(os.listdir(save)) == [starter.PROFILE]


def test_blank_tail_and_json_only_variants():
    assert starter.blank_tail() == struct.pack('<II', 1, 0)
    text = starter._text(starter.build_profile()).encode('ascii')
    assert starter.profile_bytes(tail=b'') == text + b'\0' * (-len(text) % 4)


def test_pack_game_matches_the_packing_of_savefile():
    raw = b'{"x":1}' * 5000 + b'\x00\x01' * 3
    assert savefile.unpack(savefile.pack_game(raw)) == raw
    assert len(savefile.pack_game(raw)) < len(savefile.pack(raw))   # compressed, not stored blocks
