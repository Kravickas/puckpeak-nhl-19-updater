"""The matchmaking tag (overtime_roster/app/onlinetag.py): only games that stay in step meet (0.81.0, plan WP3)."""
import json
import os
import re

import pytest

from overtime_core import gamefiles, xmlpatch
from overtime_roster.app import gamesetup, launch, matchsetup, onlinetag

from test_gamesetup import _versioninfo, world  # noqa: F401 (the fixture)

SERVER = ('ot.puckpeak.com', 'https://91.98.195.150/')
TRUSTED = next(iter(onlinetag.TRUSTED_EXES))


@pytest.fixture
def game(world, monkeypatch):  # noqa: F811
    """world with the game's own na_versioninfo.ini, the Overtime patch installed, an AMD PC on the trusted exe."""
    _versioninfo(world['game'], 'na')
    patch = os.path.join(gamesetup.patch_dir(str(world['user'])), gamesetup.PATCH_FILE)
    os.makedirs(os.path.dirname(patch))
    with open(patch, 'w', encoding='utf-8', newline='') as f:
        f.write(xmlpatch.build(*SERVER))
    monkeypatch.setattr(gamesetup, 'cpu_vendor', lambda: 'amd')
    monkeypatch.setattr(onlinetag, 'exe_sha', lambda path: TRUSTED)
    world['patch'] = patch
    world['ini'] = os.path.join(gamefiles.mods_dir(str(world['game'])), *gamesetup.VERSION_DIR, 'na_versioninfo.ini')
    return world


def _key(user, on):
    path = gamesetup.custom_config_path(str(user))
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'General': {gamesetup.AMD_MATH_KEY: on}}, f)


def test_the_tag_is_what_the_game_sends_and_the_lobby_takes():
    t = onlinetag.compute('NHL19_1.60', 'f' * 20, TRUSTED, 'amd')
    assert len(t) == onlinetag.TAG_MAX == 15 and t.startswith('NHL19_1.60-')   # the game sends 15 characters
    assert gamesetup._IDENTITY_TEXT.fullmatch(t)                # never '?' on both sides (the lobby's charset)
    assert t != 'NHL19_1.60' and t == onlinetag.compute('NHL19_1.60', 'f' * 20, TRUSTED, 'amd')
    others = {onlinetag.compute('NHL19_1.60', 'e' * 20, TRUSTED, 'amd'), onlinetag.compute('NHL19_1.60', 'f' * 20,
              '0' * 64, 'amd'), onlinetag.compute('NHL19_1.60', 'f' * 20, TRUSTED, 'intel/nokey')}
    assert t not in others and len(others) == 3
    assert onlinetag.compute('NHL19_1.60_long', 'f' * 20, TRUSTED, 'amd')[:11] == 'NHL19_1.60-'   # cut to 15
    # the server's "same base" advice splits at the first '-'
    assert t.split('-', 1)[0] == 'NHL19_1.60'


def test_the_lobby_takes_the_tag():
    """The server's own charset (overtime_server is not in the public tree: skipped there)."""
    lobby = pytest.importorskip('overtime_server.lobby')
    t = onlinetag.compute('NHL19_1.60', 'f' * 20, TRUSTED, 'amd')
    assert lobby._GAME_TEXT.fullmatch(t) and lobby._game({'online': t}) == {'online': t}
    assert lobby._GAME_TEXT.pattern == gamesetup._IDENTITY_TEXT.pattern.replace('{1,80}', '{0,80}')


def test_math_class_puts_intel_with_the_key_on_the_trusted_build_with_amd():
    assert onlinetag.math_class('0' * 64, 'amd', False) == 'amd'
    assert onlinetag.math_class(TRUSTED, 'intel', True) == 'amd'
    assert onlinetag.math_class(TRUSTED, 'intel', False) == 'intel/nokey'
    assert onlinetag.math_class('0' * 64, 'intel', True) == 'intel/key'
    assert onlinetag.math_class(TRUSTED, '?', False) == '?/nokey'


def test_both_kravickas_builds_are_trusted_and_an_intel_pc_on_either_meets_amd():
    """0.82.0 moves Boost and lobbies to 749170d; an Intel player still on b23fb67 (own Boost copy) keeps the AMD class,
    so the builds' tags differ only by the exe (the server's pin sets which one lobbies play). 0.90.0 adds Overtime's
    smooth build on 749170d (same CPU math)."""
    assert sorted(onlinetag.TRUSTED_EXES.values()) == ['Kravickas NHL19-Build 749170d', 'Kravickas NHL19-Build b23fb67',
                                                      'Overtime smooth c97b8b51 (Kravickas 749170d)']
    for sha in onlinetag.TRUSTED_EXES:
        assert len(sha) == 64 and sha == sha.lower()
        assert onlinetag.math_class(sha, 'intel', True) == 'amd' and onlinetag.math_class(sha, 'intel', False) != 'amd'
    new, old, smooth = sorted(onlinetag.TRUSTED_EXES, key=onlinetag.TRUSTED_EXES.get)
    assert onlinetag.compute('NHL19_1.60', 'f' * 20, smooth, 'amd') != onlinetag.compute('NHL19_1.60', 'f' * 20, new, 'amd')
    assert onlinetag.compute('NHL19_1.60', 'f' * 20, new, 'amd') != onlinetag.compute('NHL19_1.60', 'f' * 20, old, 'amd')


def test_apply_writes_the_tag_and_the_game_reads_it(game):
    emu, gd = str(game['emu']), str(game['game'])
    own = (game['game'] / 'nhl' / 'data' / 'kettle' / 'config' / 'na_versioninfo.ini').read_bytes()
    t, inp = onlinetag.apply(emu, gd)
    assert t and t == onlinetag.tag(inp) == onlinetag.sent(onlinetag.start_inputs(emu, gd))
    assert inp['crossvendor'] and inp['math'] == 'amd' and onlinetag.why(inp) == ''
    assert gamesetup.online_version(gd) == ('na', t)
    assert gamesetup.online_version(gd, mods=False) == ('na', 'NHL19_1.60')    # the base stays the game's own
    with open(game['ini'], 'rb') as f:
        written = f.read().decode()
    assert written.splitlines()[0] == onlinetag.MARK and 'skuVersion=1.60' in written
    assert written.count('onlineVersion=') == 1 and f'onlineVersion={t}' in written.splitlines()
    assert (game['game'] / 'nhl' / 'data' / 'kettle' / 'config' / 'na_versioninfo.ini').read_bytes() == own
    assert onlinetag.apply(emu, gd)[0] == t                                     # the same start, the same tag
    assert gamesetup.game_identity(gd)['online'] == t
    assert onlinetag.remove(gd) == [game['ini']]
    assert not os.path.exists(gamefiles.mods_dir(gd))                           # nothing else was there
    assert gamesetup.online_version(gd) == ('na', 'NHL19_1.60')


def test_remove_keeps_other_files_and_folders(game):
    gd = str(game['game'])
    onlinetag.apply(str(game['emu']), gd)
    other = os.path.join(gamefiles.mods_dir(gd), 'nhl', 'data', 'other.txt')
    with open(other, 'w') as f:
        f.write('x')
    onlinetag.remove(gd)
    assert os.path.isfile(other) and not os.path.exists(os.path.dirname(game['ini']))


def test_a_new_tag_replaces_a_hardlink_and_leaves_its_target(game, tmp_path):
    """The match -mods view is hardlinks of the player's own files: the tag of the match must not change the player's."""
    gd = str(game['game'])
    first, _ = onlinetag.apply(str(game['emu']), gd)
    own = tmp_path / 'own_versioninfo.ini'
    os.link(game['ini'], own)
    assert onlinetag.write(gd, 'NHL19_1.60-ZZZZ') == game['ini']
    assert f'onlineVersion={first}' in own.read_text() and 'onlineVersion=NHL19_1.60-ZZZZ' in open(game['ini']).read()
    assert not os.path.exists(game['ini'] + onlinetag.TMP)


def test_another_mods_versioninfo_is_left_alone_and_sent(game):
    gd, emu = str(game['game']), str(game['emu'])
    mods = gamefiles.mods_dir(gd)
    _versioninfo(type(game['game'])(mods), 'na', 'NHL19_MOD')
    t, inp = onlinetag.apply(emu, gd)
    assert t is None and inp['foreign'] == 'NHL19_MOD' and onlinetag.sent(inp) == 'NHL19_MOD'
    assert 'Another mod' in onlinetag.why(inp)
    assert onlinetag.remove(gd) == [] and 'onlineVersion=NHL19_MOD' in open(game['ini']).read()
    os.remove(game['ini'])
    _versioninfo(type(game['game'])(mods), 'ww', 'NHL19_WW')       # a ww file wins over the game's na one
    assert onlinetag.apply(emu, gd)[0] is None and not os.path.exists(game['ini'])
    assert onlinetag.sent(onlinetag.start_inputs(emu, gd)) == 'NHL19_WW'


def test_no_patch_no_tag_and_the_old_one_goes(game):
    gd, emu = str(game['game']), str(game['emu'])
    assert onlinetag.apply(emu, gd)[0]
    os.remove(game['patch'])
    t, inp = onlinetag.apply(emu, gd)
    assert t is None and not os.path.exists(game['ini']) and onlinetag.sent(inp) == 'NHL19_1.60'
    assert onlinetag.why(inp) == ''                     # an unpatched game reaches no Overtime server


def test_a_game_without_versioninfo_gets_no_tag(world):  # noqa: F811
    t, inp = onlinetag.apply(str(world['emu']), str(world['game']))
    assert t is None and onlinetag.sent(inp) == '?' and not os.path.exists(gamefiles.mods_dir(str(world['game'])))


def test_an_unknown_eboot_or_another_exe_meets_only_its_own_kind(game, monkeypatch):
    gd, emu = str(game['game']), str(game['emu'])
    good = onlinetag.start_inputs(emu, gd)
    with open(game['patch'], 'w', encoding='utf-8', newline='') as f:
        f.write(xmlpatch.build(*SERVER, features=xmlpatch.NO_CROSSVENDOR))
    bare = onlinetag.start_inputs(emu, gd)
    assert onlinetag.tag(bare) != onlinetag.tag(good) and 'v1.60 eboot.bin' in onlinetag.why(bare)
    monkeypatch.setattr(onlinetag, 'exe_sha', lambda path: '0' * 64)
    other = onlinetag.start_inputs(emu, gd)
    assert onlinetag.tag(other) != onlinetag.tag(bare) and 'Boost performance' in onlinetag.why(other)


def test_intel_meets_amd_only_with_the_key_on_the_trusted_build(game, monkeypatch):
    gd, emu = str(game['game']), str(game['emu'])
    amd = onlinetag.tag(onlinetag.start_inputs(emu, gd))
    monkeypatch.setattr(gamesetup, 'cpu_vendor', lambda: 'intel')
    monkeypatch.setattr(gamesetup, 'WINDOWS', True)
    _key(game['user'], True)
    keyed = onlinetag.start_inputs(emu, gd)
    assert onlinetag.tag(keyed) == amd and onlinetag.why(keyed) == ''
    _key(game['user'], False)
    off = onlinetag.start_inputs(emu, gd)
    assert onlinetag.tag(off) != amd and 'AMD math is off' in onlinetag.why(off)


def test_ready_and_the_match_start_make_the_same_tag(game, monkeypatch, tmp_path):
    """Ready sends match_inputs' value before the match setup exists; launch.start writes start_inputs' with the match
    patch (-p), the online copy and the match config. They must agree, or the lobby passes a pair that never meets."""
    gd, emu = str(game['game']), str(game['emu'])
    monkeypatch.setattr(gamesetup, 'cpu_vendor', lambda: 'intel')
    monkeypatch.setattr(gamesetup, 'WINDOWS', True)
    _key(game['user'], False)                           # the player's own config: key off
    own = xmlpatch.build(*SERVER)
    text = matchsetup.match_xml(matchsetup.recipe(own), xmlpatch.with_resolution(own, 1440))
    copy = str(tmp_path / 'online' / 'shadPS4.exe')
    at_ready = onlinetag.match_inputs(emu, gd, text, copy)
    cfg = matchsetup._config_values({}, str(game['user']), text, {})        # what matchsetup.apply writes
    with open(gamesetup.custom_config_path(str(game['user'])), 'w', encoding='utf-8') as f:
        json.dump(cfg, f)
    match = tmp_path / 'overtime-match.xml'
    match.write_text(text, encoding='utf-8', newline='')
    t, at_start = onlinetag.apply(emu, gd, str(match), copy)
    assert t and onlinetag.sent(at_ready) == t and at_ready['math'] == at_start['math'] == 'amd'


def test_text_with_keeps_the_line_ends_and_skips_comments():
    src = b'; onlineVersion=commented\r\nskuVersion=1.60\r\nonlineVersion=NHL19_1.60\r\nonlineVersion=again\r\n'
    out = onlinetag.text_with(src, 'NHL19_1.60-AbC9').decode()
    assert out.split('\r\n') == [onlinetag.MARK, '; onlineVersion=commented', 'skuVersion=1.60',
                                 'onlineVersion=NHL19_1.60-AbC9', 'onlineVersion=again', '']
    assert gamesetup.ini_value(out, 'onlineVersion') == 'NHL19_1.60-AbC9'
    assert onlinetag.text_with(b'onlineVersion=x', 'y').decode() == onlinetag.MARK + '\nonlineVersion=y'
    with pytest.raises(onlinetag.TagError):
        onlinetag.text_with(b'skuVersion=1.60\n', 'y')


def test_launch_start_writes_the_tag_and_refuses_when_a_stale_one_cannot_go(game, monkeypatch):
    gd, emu = str(game['game']), str(game['emu'])
    launch.start(emu, gd, running=lambda: False, popen=lambda cmd, **kw: 'proc')
    assert re.fullmatch(r'NHL19_1\.60-[0-9A-Za-z]{4}', gamesetup.online_version(gd)[1])

    def broken(*a, **k):
        raise OSError('denied')
    monkeypatch.setattr(onlinetag, 'write', broken)
    launch.start(emu, gd, running=lambda: False, popen=lambda cmd, **kw: 'proc')   # the old tag went instead
    assert not os.path.exists(game['ini'])
    monkeypatch.setattr(onlinetag, 'remove', broken)
    with pytest.raises(launch.LaunchError, match='could not be written'):
        launch.start(emu, gd, running=lambda: False, popen=None)


def test_exe_sha_is_cached_by_size_and_time(tmp_path):
    exe = tmp_path / 'shadPS4.exe'
    exe.write_bytes(b'MZ one')
    onlinetag._SHA.clear()
    first = onlinetag.exe_sha(str(exe))
    assert re.fullmatch(r'[0-9a-f]{64}', first) and onlinetag.exe_sha(str(exe)) == first
    exe.write_bytes(b'MZ two, longer')
    assert onlinetag.exe_sha(str(exe)) != first
    assert onlinetag.exe_sha(str(tmp_path / 'missing.exe')) == '?'
