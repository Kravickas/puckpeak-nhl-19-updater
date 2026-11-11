"""World of Chel's tile is on by default (v0.90.0, M5): the menus option, and the one-time migration of saved patch
states (controller.chel_migrate, the same pattern as packs_migrate). The Patch tab's "patch again" note is the existing
`changed` check (patch_ctl.facts), so no separate flag is kept."""
from overtime_core import menus
from overtime_roster.app import controller as C


def test_the_menus_option_is_on_by_default():
    assert menus.OPTIONS['chel'] is True and menus.options()['chel'] is True


def test_a_fresh_install_keeps_chel_on():
    assert C.chel_migrate({}, {'menus': True, 'chel': True}) == {'menus': True, 'chel': True}


def test_an_install_with_the_hub_on_gets_chel_on_once():
    want = C.chel_migrate({'patch': {'menus': True, 'chel': False}}, {'menus': True, 'chel': False})
    assert want['chel'] is True


def test_a_marked_install_keeps_its_own_choice():
    prefs = {'chel_default': C.CHEL_DEFAULT, 'patch': {'menus': True, 'chel': False}}
    assert C.chel_migrate(prefs, {'menus': True, 'chel': False})['chel'] is False


def test_with_the_hub_off_chel_is_left_alone():
    assert C.chel_migrate({}, {'menus': False, 'chel': False})['chel'] is False


def test_the_marker_is_set_for_the_settings():
    assert C.CHEL_DEFAULT == 1
