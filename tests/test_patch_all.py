"""The Patch tab's one press (patchall_ctl, 0.97.0): the roster update, the starter profile, then the patch. Runs on
test_update_go's made-up roster (NHL.com, the plan, the change and the save replaced; jobs inline) with the patch
itself replaced (patch_ctl.one_click records its calls). Nothing is written outside the test's temp folder."""
import os

import pytest

from overtime_roster.app import patch_ctl, patchall_ctl as PA, sources, starter
from test_update_go import app, open_roster, view  # noqa: F401  (fixture)


@pytest.fixture
def one(app, monkeypatch):  # noqa: F811
    c, host, fakes = app
    monkeypatch.setattr(sources.GameData, 'ok', property(lambda self: True))
    monkeypatch.setattr(PA.overlay, 'emulator_running', lambda: False)
    monkeypatch.setattr(PA.matchsetup, 'active', lambda: False)
    monkeypatch.setattr(patch_ctl, 'packs_here', lambda cache: {})
    c.setup.emulator = 'shadPS4.exe'
    patched = []
    order = []
    fakes.order = order
    real_install = fakes.install

    def install(*a, **k):
        order.append('update saved')
        return real_install(*a, **k)
    monkeypatch.setattr(PA.install, 'run', install)

    def one_click(setup, then=None):
        assert not c.busy and c.parts['update'].running is None, 'the patch starts after the update let go'
        order.append('patch')
        patched.append(dict(c.patch_want))
        if fakes.patch_fails:
            return {'error': fakes.patch_fails}
        then and then()
        return None
    fakes.patch_fails = None
    monkeypatch.setattr(patch_ctl, 'one_click', one_click)
    return c, host, fakes, patched


def test_update_then_patch_in_that_order(one):
    c, host, fakes, patched = one
    open_roster(c, fakes, 'RosterCustom0')
    assert c.calls['patch_all']() is None
    assert fakes.order == ['update saved', 'patch']
    assert view(host)['result']['kind'] == 'good'
    v = host.snap('patchall')
    assert v['phase'] is None and not v['stopped'] and v['update_runs'] and v['button']['enabled']


def test_the_update_is_written_for_the_game_as_the_patch_leaves_it(one):
    """A game never patched, league switch on: the deals are 2026-27 money (served from the coming patch)."""
    c, host, fakes, patched = one
    open_roster(c, fakes, 'RosterCustom0')
    c.patch_want['league'] = True
    c.calls['patch_all']()
    assert fakes.ran[-1]['served'] is True
    c.patch_want['league'] = False
    c.calls['patch_all']()
    assert fakes.ran[-1]['served'] is False


def test_roster_update_off_or_no_roster_patches_only(one):
    c, host, fakes, patched = one
    assert c.calls['patch_all']() is None           # no roster open: the patch alone
    assert fakes.order == ['patch'] and fakes.ran == []
    open_roster(c, fakes, 'RosterCustom0')
    assert c.calls['patch_update_on'](False) is None
    assert host.snap('patchall')['update_on'] is False and c.prefs[PA.PREF]['update'] is False
    c.calls['patch_all']()
    assert fakes.order == ['patch', 'patch'] and fakes.ran == []


@pytest.mark.parametrize('why', ['running', 'match', 'emulator'])
def test_pre_flight_refuses_before_anything_runs(one, monkeypatch, why):
    c, host, fakes, patched = one
    open_roster(c, fakes, 'RosterCustom0')
    if why == 'running':
        monkeypatch.setattr(PA.overlay, 'emulator_running', lambda: True)
    elif why == 'match':
        monkeypatch.setattr(PA.matchsetup, 'active', lambda: True)
    else:
        c.setup.emulator = ''
    out = c.calls['patch_all']()
    assert out and out['error'] and fakes.order == [] and fakes.ran == []
    assert c.status['tone'] == 'caution'


def test_a_stopped_update_offers_patch_anyway(one):
    c, host, fakes, patched = one
    open_roster(c, fakes, 'RosterCustom0')
    fakes.fail_gather = 'NHL.com did not answer'
    c.calls['patch_all']()
    assert fakes.order == [] and patched == []
    v = host.snap('patchall')
    assert v['stopped'] and v['phase'] == 'update'
    assert view(host)['run']['failed']
    assert c.calls['patch_anyway']() is None
    assert fakes.order == ['patch']
    assert not host.snap('patchall')['stopped']


def test_stopped_ends_when_the_result_is_closed_or_checked_again(one):
    c, host, fakes, patched = one
    open_roster(c, fakes, 'RosterCustom0')
    fakes.fail_gather = 'NHL.com did not answer'
    c.calls['patch_all']()
    assert host.snap('patchall')['stopped']
    c.calls['update_result']('close')
    v = host.snap('patchall')
    assert not v['stopped'] and v['phase'] is None
    c.calls['patch_all']()
    assert host.snap('patchall')['stopped']
    fakes.fail_gather = None
    c.calls['update_check']()
    assert not host.snap('patchall')['stopped'] and host.snap('patchall')['phase'] is None


def test_busy_and_roster_pushes_reach_the_patch_button(one):
    c, host, fakes, patched = one
    for push in (lambda: c.changed('app'), lambda: c.changed('save'), lambda: c.changed('patch'),
                 lambda: c.changed('source'), lambda: c.changed('setup')):
        host.pushes.clear()
        push()
        assert any('patchall' in names for names, _busy in host.pushes)


def test_the_next_press_skips_an_update_that_saved_when_the_patch_did_not_go_in(one):
    c, host, fakes, patched = one
    open_roster(c, fakes, 'RosterCustom0')
    fakes.patch_fails = 'NHL 19 cannot be patched: no eboot.'
    c.calls['patch_all']()
    assert fakes.order == ['update saved', 'patch'] and len(fakes.ran) == 1
    v = host.snap('patchall')
    assert v['skips'] and not v['update_runs']
    fakes.patch_fails = None
    c.calls['patch_all']()
    assert fakes.order == ['update saved', 'patch', 'patch'] and len(fakes.ran) == 1     # Update skipped once
    assert host.snap('patchall')['update_runs']                                        # and runs again after


def test_unsaved_edits_ask_first(one):
    c, host, fakes, patched = one
    open_roster(c, fakes, 'RosterCustom0')
    c.parts['save'].unsaved = lambda: 2
    out = c.calls['patch_all']()
    assert 'asked' in out and fakes.order == []
    assert c.shell.asking['title'] == 'Your edits are not saved'


def test_the_starter_profile_goes_in_between_with_the_saved_roster(one, monkeypatch):
    c, host, fakes, patched = one
    open_roster(c, fakes, 'RosterCustom0')
    os.makedirs(c.save_dir, exist_ok=True)
    assert host.snap('patchall')['starter'] == {'show': True, 'on': False}
    written = []
    monkeypatch.setattr(starter, 'write', lambda save_dir, roster=None: written.append(roster) or
                        fakes.order.append('starter') or os.path.join(save_dir, starter.PROFILE))
    c.calls['patch_all']()
    assert written == []                            # off by default
    assert c.calls['patch_starter'](True) is None and c.prefs[PA.PREF]['starter'] is True
    c.calls['patch_all']()
    assert fakes.order[-3:] == ['update saved', 'starter', 'patch']
    assert written == [('Custom', 0)]


def test_the_starter_profile_never_writes_over_one(one, monkeypatch):
    c, host, fakes, patched = one
    os.makedirs(os.path.join(c.save_dir, starter.PROFILE))
    assert host.snap('patchall')['starter']['show'] is False
    PA_ctl = c.parts['patchall']
    PA_ctl.starter_on = True
    monkeypatch.setattr(starter, 'write', lambda *a, **k: pytest.fail('wrote over Profile0'))
    c.calls['patch_all']()
    assert fakes.order == ['patch']


def test_a_starter_error_still_patches(one, monkeypatch):
    c, host, fakes, patched = one
    os.makedirs(c.save_dir, exist_ok=True)
    c.parts['patchall'].starter_on = True

    def boom(*a, **k):
        raise starter.StarterError('disk full')
    monkeypatch.setattr(starter, 'write', boom)
    c.calls['patch_all']()
    assert fakes.order == ['patch']
    assert any('Starter profile: disk full' in line for line in host.lines)


@pytest.mark.parametrize('folder, want', [('RosterCustom2', ('Custom', 2)), ('RosterDownload3', ('Download', 3)),
                                          (None, None), ('20261021-120000', None), ('RosterCustomX', None)])
def test_roster_of(folder, want):
    assert PA.roster_of(folder) == want
