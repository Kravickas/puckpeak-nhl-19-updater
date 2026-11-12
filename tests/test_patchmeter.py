"""Patch's progress bar (overtime_roster.app.patchmeter) and what feeds it: the share follows the time of the work,
never goes back or jumps when a step turns out larger or smaller, learns this PC's speeds; overlay.apply keeps an art
archive whose content is unchanged instead of writing it again and reports its bytes; a delta pack checked against the
game is recorded; packs made at Patch are recorded as checked."""
import os
import zipfile

import pytest

from overtime_core import art, eb, kitcompose as K, overlay
from overtime_roster.app import patch, patchmeter as PM, sources

from test_art import IDLE, KIT, LOGO, NEW_LOGO, game, gnf, pack  # noqa: F401  (fixture)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def meter(speeds=None):
    clock, said = Clock(), []
    m = PM.Meter(lambda text, share: said.append((text, share)), speeds or {'a': 1.0, 'b': 1.0, 'time:t': 10.0},
                 clock=clock)
    return m, clock, said


# --- the meter -------------------------------------------------------------------------------------------------------
def test_the_share_is_the_planned_time_done():
    m, _clock, _said = meter({'a': 1.0, 'b': 3.0})
    m.plan('one', 'a', 100)         # 100 s
    m.plan('two', 'b', 100)         # 300 s
    m.begin('one')
    m.tick('one', 50)
    assert m.share() == pytest.approx(50 / 400)
    m.tick('one', 50)
    m.begin('two')
    m.tick('two', 50)
    assert m.share() == pytest.approx(250 / 400)
    m.tick('two', 50)
    assert m.share() == PM.CAP          # full only when Patch is done
    m.finish()
    assert m.share() == 1.0


def test_a_step_measured_larger_or_kept_never_moves_the_bar_back_or_ahead():
    m, _clock, _said = meter()
    m.plan('one', 'a', 100)
    m.plan('two', 'b', 100)
    m.begin('one')
    m.tick('one', 50)
    at = m.share()
    assert at == pytest.approx(0.25)
    m.resize('two', 1000)               # measured: ten times the work
    assert m.share() == pytest.approx(at)
    m.tick('one', 50)                   # the rest of the bar is spread over the work left (50 + 1000)
    assert m.share() == pytest.approx(at + (1 - at) * 50 / 1050)
    m.skip('two')                       # kept after all: nothing left but the bar stays where it is
    assert m.share() == pytest.approx(at + (1 - at) * 50 / 1050)
    m.plan('three', 'a', 10)
    m.begin('three')
    m.tick('three', 10)
    assert m.share() == PM.CAP


def test_a_step_without_units_creeps_on_its_time_and_never_past_its_share():
    m, clock, _said = meter()
    m.plan('t', 'time:t', 1)            # 10 s
    m.plan('one', 'a', 10)              # 10 s
    m.begin('t')
    seen = []
    for _ in range(100):
        clock.t += 1
        seen.append(m.share())
    assert seen == sorted(seen) and len(set(seen)) == len(seen)     # never back, never still
    assert seen[3] == pytest.approx(0.2)                        # on time up to the knee (4 s of 10 s, of 20 s in all)
    assert 0.48 < seen[19] < seen[-1] < 0.5         # past its time: slower and slower, never its whole share
    m.begin('one')                                              # the timed step ends: no jump
    assert m.share() == pytest.approx(seen[-1])
    m.tick('one', 10)
    assert m.share() == PM.CAP


def test_more_units_than_planned_grow_the_step_instead_of_standing_still():
    m, _clock, _said = meter()
    m.plan('one', 'a', 10)
    m.plan('two', 'b', 10)
    m.begin('one')
    m.tick('one', 10)
    before = m.share()
    m.tick('one', 5)                    # the step was larger
    m.tick('one', 5)
    assert m.share() > before


def test_the_text_and_share_are_said_as_they_change():
    m, clock, said = meter()
    m.plan('one', 'a', 1000, 'doing one...')
    m.begin('one')
    assert said[-1] == ('doing one...', 0.0)
    clock.t += 1
    m.tick('one', 0.5)                  # under 0.1 %: not said again
    assert len(said) == 1
    m.tick('one', 10)
    assert said[-1][1] == pytest.approx(0.0105)
    m.say('one: 50 %...')
    assert said[-1][0] == 'one: 50 %...'


def test_speeds_are_learned_half_and_half_and_kept(tmp_path):
    m, clock, _said = meter({'a': 1.0, 'time:t': 10.0})
    m.plan('one', 'a', 100)
    m.plan('t', 'time:t', 1)
    m.begin('one')
    m.tick('one', 100)
    clock.t += 300                      # 3 s per unit, not 1
    m.begin('t')
    clock.t += 2
    m.end()
    m.plan('gone', 'a', 50)
    m.skip('gone')                      # kept this time: none next time either
    speeds, last = m.learned({'old': 7.0, 'gone': 50.0})
    assert speeds['a'] == pytest.approx(2.0) and speeds['time:t'] == pytest.approx(6.0)
    assert last == {'old': 7.0, 'one': 100.0, 't': 1.0, 'gone': 0.0}
    PM.save(str(tmp_path), speeds, last)
    got = PM.load(str(tmp_path))
    assert got['speeds']['a'] == pytest.approx(2.0) and got['last']['one'] == 100.0
    assert got['speeds']['copy'] == PM.default_speeds()['copy']      # kinds not learned yet: the defaults
    (tmp_path / PM.FILE).write_text('{broken')
    assert PM.load(str(tmp_path))['speeds'] == PM.default_speeds()


def test_an_odd_patch_never_throws_a_speed_far_off():
    m, clock, _said = meter({'a': 1.0})
    m.plan('one', 'a', 1)
    m.begin('one')
    m.tick('one', 1)
    clock.t += 1e6
    m.end()
    assert m.learned()[0]['a'] == pytest.approx(0.5 + 50)       # at most 100 times the old speed, then half and half


def test_the_bytes_patched_count_as_the_writing_steps_go():
    clock, said = Clock(), []
    m = PM.Meter(lambda text, share, amount: said.append(amount), {'a': 1.0, 'b': 1.0, 'kits': 1.0}, clock=clock,
                 amount=PM.patched_text)
    m.plan('check', 'a', 100)                               # reads only: not counted
    m.plan('kits:nhl', 'kits', 50, writes=True)             # weighed units
    m.written_bytes('kits:nhl', 3 << 30)                    # its textures: 3 GB
    m.plan('copy', 'b', 2 << 20, writes=True)               # bytes
    m.begin('check')
    m.tick('check', 100)
    assert m.written() == 0 and said[-1] == 'Patched 0 MB'
    m.begin('kits:nhl')
    clock.t += 1
    m.share_of('kits:nhl', 0.5)
    assert m.written() == 1.5 * 2**30 and said[-1] == 'Patched 1.5 GB'
    m.share_of('kits:nhl', 1.0)
    m.begin('copy')
    clock.t += 1
    m.tick('copy', 1 << 20)
    assert said[-1] == 'Patched 3.0 GB' and m.written() == (3 << 30) + (1 << 20)
    assert PM.patched_text(850 * 2**20) == 'Patched 850 MB' and PM.patched_text(int(10.34 * 2**30)) == 'Patched 10.3 GB'


def test_the_help_bar_line_carries_the_count_only_while_given():
    from overtime_roster.app import controller
    c = controller.Controller.__new__(controller.Controller)
    c.changed = lambda *names: None
    c.say('Patching NHL 19: writing...', 'info', 0.4, amount='Patched 1.2 GB')
    assert c.status == {'text': 'Patching NHL 19: writing...', 'tone': 'info', 'progress': 0.4,
                        'amount': 'Patched 1.2 GB'}
    c.say('Patched.', 'good')
    assert c.status == {'text': 'Patched.', 'tone': 'good', 'progress': None}


# --- overlay: unchanged archives are kept, bytes reported ------------------------------------------------------------
def test_an_art_archive_with_the_same_content_is_kept_not_written_again(game, tmp_path, monkeypatch):  # noqa: F811
    looks = pack(tmp_path, 'looks', {LOGO: gnf('utah'), NEW_LOGO: gnf('seattle'), KIT: gnf('utah kit')})
    seen = []
    st = overlay.apply(game, ('art',), art=[looks], progress=lambda stage, n: seen.append((stage, n)), **IDLE)
    plan = seen[0][1]
    assert seen[0][0] == 'plan' and plan['write'] > 0 and plan['verify'] == plan['write'] and plan['copy'] == 0
    assert sum(n for s, n in seen if s == 'write') == plan['write']           # every byte said once
    assert sum(n for s, n in seen if s == 'verify') == plan['verify']
    assert all(r.get('content') for r in st['files'].values())
    mods = overlay.overlay_dir(game)
    times = {rel: os.stat(overlay._target(game, rel)).st_mtime_ns for rel in st['files']}

    written = []
    real = eb.new_archive
    monkeypatch.setattr(eb, 'new_archive', lambda out, files, **kw: written.append(out) or real(out, files, **kw))
    seen.clear()
    st2 = overlay.apply(game, ('art',), art=[pack(tmp_path, 'looks', {LOGO: gnf('utah'), NEW_LOGO: gnf('seattle'),
                                                                      KIT: gnf('utah kit')})],
                        progress=lambda stage, n: seen.append((stage, n)), **IDLE)
    assert written == [] and seen == [('plan', {'copy': 0, 'write': 0, 'verify': 0})]
    assert {rel: os.stat(overlay._target(game, rel)).st_mtime_ns for rel in st2['files']} == times
    assert st2['files'] == st['files'] and overlay.status(game)['problems'] == []

    # one texture changed: only the archive that holds it is written again
    overlay.apply(game, ('art',), art=[pack(tmp_path, 'looks2', {LOGO: gnf('utah v2'), NEW_LOGO: gnf('seattle'),
                                                                 KIT: gnf('utah kit')})], **IDLE)
    assert [os.path.basename(p) for p in written] == ['patch_inxp_57.big.tmp']
    with eb.EbArchive(os.path.join(mods, 'databigs', 'patch_inxp_57.big')) as arc:
        assert arc.read(LOGO) == gnf('utah v2')


def test_a_kept_archive_that_changed_on_disk_is_refused_as_before(game, tmp_path):  # noqa: F811
    looks = pack(tmp_path, 'looks', {LOGO: gnf('utah'), KIT: gnf('utah kit')})
    st = overlay.apply(game, ('art',), art=[looks], **IDLE)
    target = overlay._target(game, next(iter(st['files'])))
    with open(target, 'r+b') as f:      # someone else's change, same size, after the patch
        f.seek(-1, 2)
        f.write(b'!')
    os.utime(target, ns=(os.stat(target).st_atime_ns, os.stat(overlay.state_path(game)).st_mtime_ns + 10**9))
    with pytest.raises(overlay.PatchError, match='changed since the patch wrote it'):
        overlay.apply(game, ('art',), art=[looks], **IDLE)


def test_a_kept_archive_whose_table_is_damaged_with_its_size_and_time_is_written_again(game, tmp_path):  # noqa: F811
    looks = pack(tmp_path, 'looks', {LOGO: gnf('utah'), KIT: gnf('utah kit')})
    st = overlay.apply(game, ('art',), art=[looks], **IDLE)
    target = overlay._target(game, 'databigs/patch_inxp_57.big')
    before = os.stat(target)
    with open(target, 'r+b') as f:      # a bit flip in its table that keeps the size and the time
        f.seek(0x30 + 8)
        f.write(b'\xff')
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    seen = []
    overlay.apply(game, ('art',), art=[looks], progress=lambda stage, n: seen.append((stage, n)), **IDLE)
    assert seen[0][1]['write'] > 0                               # not kept: written again
    with eb.EbArchive(target) as arc:
        assert arc.read(LOGO) == gnf('utah')
    assert overlay.status(game)['problems'] == [] and st['files'].keys() == overlay._load_state(game)['files'].keys()


def test_a_copied_game_archive_is_kept_while_the_game_and_its_entries_are_the_same(tmp_path):
    big = tmp_path / 'NHL 19' / 'databigs'
    big.mkdir(parents=True)
    path = 'nhl/data/common/x.db'
    eb.new_archive(str(big / 'boot.big'), {path: b'stock'})
    edits = {str(big / 'boot.big'): {path: b'edited'}}
    a = overlay._content(str(big / 'boot.big'), edits[str(big / 'boot.big')], False)
    assert a == overlay._content(str(big / 'boot.big'), {path: b'edited'}, False)
    assert a != overlay._content(str(big / 'boot.big'), {path: b'edited 2'}, False)
    os.utime(big / 'boot.big', ns=(1, 1))                       # the game archive changed (an update)
    assert a != overlay._content(str(big / 'boot.big'), edits[str(big / 'boot.big')], False)
    (tmp_path / 'NHL 19' / 'databigs' / ('boot.big' + overlay.LEGACY_SUFFIX)).write_text('{}')
    assert overlay._content(str(big / 'boot.big'), edits[str(big / 'boot.big')], False) is None
    assert overlay._content('x', {LOGO: art.Stored(4, lambda: b'GNF ')}, True) is None     # no sha: not told


# --- packs: the delta pack's record, the packs made at Patch ---------------------------------------------------------
def test_a_delta_pack_checked_against_the_game_is_not_checked_again_until_either_changes(tmp_path, game):  # noqa: F811
    base = gnf('stock kit')
    kit = base[:16] + b'X' * 16 + base[32:]
    path = str(tmp_path / 'kits.zip')
    art.write_pack(path, 'kits', {KIT: kit}, bases={KIT: base})
    checked = {}
    ticks = []
    assert art.check_work(path, game, checked) == len(kit)
    art.load_pack(path, game, checked, progress=ticks.append)
    assert ticks == [len(kit)] and list(checked) == [f'{art._checked_key(path)}|game={art.game_key(game)}']
    assert art.check_work(path, game, checked) == 0
    again = art.load_pack(path, game, checked, progress=ticks.append)
    assert ticks == [len(kit)]                                  # nothing checked in full the second time
    assert again.files[KIT].read() == kit                       # laid and checked as it is written
    os.utime(os.path.join(game, 'databigs', 'game_90.big'), ns=(1, 1))     # the game changed: checked again
    assert art.check_work(path, game, checked) == len(kit)


def test_a_recorded_delta_pack_on_another_kit_fails_when_it_is_written(tmp_path, game):  # noqa: F811
    base = gnf('stock kit')
    path = str(tmp_path / 'kits.zip')
    art.write_pack(path, 'kits', {KIT: base[:16] + b'X' * 16 + base[32:]}, bases={KIT: base})
    checked = {}
    art.load_pack(path, game, checked)
    eb.new_archive(os.path.join(game, 'databigs', 'game_90.big'), {KIT: gnf('modded kit')})
    key = f'{art._checked_key(path)}|game={art.game_key(game)}'
    loaded = art.load_pack(path, game, {key: True})             # as if recorded with the modded game
    with pytest.raises(art.ArtError, match='checksum'):
        loaded.files[KIT].read()


def test_the_record_keeps_a_delta_packs_key(tmp_path, game):  # noqa: F811
    cache = tmp_path / 'cache'
    cache.mkdir()
    base = gnf('stock kit')
    path = str(cache / 'kits.zip')
    art.write_pack(path, 'kits', {KIT: base[:16] + b'X' * 16 + base[32:]}, bases={KIT: base})
    checked = {}
    art.load_pack(path, game, checked)
    patch._save_checked(str(cache), checked)
    assert patch._load_checked(str(cache)) == checked


@pytest.fixture
def places(tmp_path, monkeypatch):
    monkeypatch.delenv(patch.ART_ENV, raising=False)
    monkeypatch.setattr(sources, 'BUILD_PACKS', str(tmp_path / 'exe-packs'))
    monkeypatch.setattr(sources, 'REPO_PACKS', str(tmp_path / 'repo-packs'))
    cache = tmp_path / 'cache'
    cache.mkdir()
    return cache


def test_a_pack_made_at_patch_is_recorded_as_checked(places, monkeypatch):
    path = str(places / K.PANTS_LOCAL)
    art.write_pack(path, K.PANTS_KIT, {LOGO: gnf('pants')}, source='test', built='2026-11-12')
    assert patch.art_work(str(places), kits=True, photos=False, extras=[]) > 0
    patch.mark_checked(str(places), path)
    assert patch.art_work(str(places), kits=True, photos=False, extras=[]) == 0
    read = []
    real = zipfile.ZipFile.read
    monkeypatch.setattr(zipfile.ZipFile, 'read', lambda self, name, *a: read.append(name) or real(self, name, *a))
    packs, problems = patch.art_packs(str(places), kits=True, photos=False, extras=[])
    assert not problems and [p.name for p in packs] == [K.PANTS_KIT] and read == [art.MANIFEST]


def test_a_downloaded_art_pack_is_recorded_as_checked(places, tmp_path):
    import hashlib
    from overtime_roster.app import packdownload, selfupdate
    src = tmp_path / 'release' / patch.LOOKS32_PACK
    src.parent.mkdir()
    art.write_pack(str(src), 'looks32', {LOGO: gnf('utah')}, source='test', built='2026-11-12')
    data = src.read_bytes()
    release = selfupdate.Release('1', exe_url=src.as_uri(), size=len(data), digest=hashlib.sha256(data).hexdigest(),
                                 asset=patch.LOOKS32_PACK)
    packdownload._get(patch.LOOKS32_PACK, release, str(places))
    assert patch.art_work(str(places), kits=False, photos=False, extras=[]) == 0    # the published file: not again
    os.utime(places / patch.LOOKS32_PACK, ns=(1, 1))                                # changed since: checked again
    assert patch.art_work(str(places), kits=False, photos=False, extras=[]) > 0


def test_the_full_check_on_every_core_says_the_first_bad_file(tmp_path, monkeypatch):
    from overtime_core import workers
    path = str(tmp_path / 'looks.zip')
    files = {f'nhl/ui/kettle_assets/teamlogos/large/t{i}.gnf': gnf(f'logo {i}') for i in range(30)}
    art.write_pack(path, 'looks', files, source='test', built='2026-11-12')
    monkeypatch.setattr(workers, 'count', lambda: 6)
    ticks = []
    loaded = art.load_pack(path, progress=ticks.append)
    assert list(loaded.files) == sorted(files) and sum(ticks) == sum(len(d) for d in files.values())
    with zipfile.ZipFile(path) as z:
        info = z.read(art.MANIFEST)
    with zipfile.ZipFile(path, 'w') as z:      # t7, t20 damaged: pack.json's first (t20) is said, as one core does
        z.writestr(art.MANIFEST, info)
        for p, d in files.items():
            z.writestr(p, gnf('bad') if p.endswith(('t7.gnf', 't20.gnf')) else d)
    with pytest.raises(art.ArtError, match='t20.gnf does not match'):
        art.load_pack(path)


# --- the whole Patch ---------------------------------------------------------------------------------------------
def test_patch_says_a_share_that_only_grows_and_keeps_its_speeds(sc, monkeypatch):  # noqa: F811
    from overtime_roster.app import patch_ctl
    shares = []
    real = sc.ctl.say

    def say(text, tone='info', progress=None, amount=None):
        if progress is not None and progress >= 0:
            shares.append(progress)
        real(text, tone, progress)
    sc.setup_refresh()
    sc.ctl.say = say
    sc.setup_patch()
    assert sc.ctl.said[-1][1] == 'good'
    assert shares and shares == sorted(shares) and shares[-1] == 1.0
    kept = PM.load(patch_ctl.cache_dir())
    assert 'prepare' in kept['last'] and 'install' in kept['last']
    assert any(line.startswith('Patch took ') for line in sc.ctl.host.logs)


def test_a_patch_that_stops_stops_its_bar(sc, monkeypatch):  # noqa: F811
    from overtime_roster.app import gamesetup
    shares = []
    real = sc.ctl.say
    sc.ctl.say = lambda text, tone='info', progress=None, amount=None: (shares.append((text, progress)),
                                                                        real(text, tone, progress))
    monkeypatch.setattr(gamesetup, 'install', lambda emu, xml: (_ for _ in ()).throw(OSError('disk full')))
    sc.setup_refresh()
    sc.setup_patch()
    assert sc.ctl.said[-1][1] == 'bad' and shares[-1][1] is None      # the last line is the failure, no bar after it


from test_gamesetup import world  # noqa: E402,F401  (fixture)
from test_setup_controller import sc  # noqa: E402,F401  (fixture)
