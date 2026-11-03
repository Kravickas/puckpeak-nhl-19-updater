import json
import os
import threading
import types

import pytest

from overtime_core import art, overlay
from overtime_roster.app import gamesetup, jobs, launch, patch, setup_controller as SC

from test_gamesetup import world  # noqa: F401  (fixture)

SEATTLE_READY = SC.SetupController._seattle_ready


class FakeHost:
    def __init__(self):
        self.slices, self.changes, self.logs = {}, [], []

    def register(self, name, snap):
        self.slices[name] = snap

    def changed(self, *names):
        self.changes += names

    def log(self, text):
        self.logs.append(text)


class FakeCtl:
    def __init__(self, game_dir):
        self.host = FakeHost()
        self.lock = threading.RLock()
        self.busy = None
        self.prefs = {}
        self.game_dir = game_dir
        self.patch_want = {'text': True, 'names': False, 'league': False, 'roster': False}
        self.said = []

    def say(self, text, tone='info', progress=None):
        self.said.append((text, tone))

    def changed(self, *names):
        self.host.changed(*names)

    def remember(self, **kv):
        self.prefs.update(kv)

    def set_game_dir(self, path):
        self.game_dir = path


@pytest.fixture
def sc(world, monkeypatch):  # noqa: F811
    def run_now(work, done=None, failed=None, expected=()):
        try:
            out = work()
        except expected as err:
            if failed:
                failed(str(err))
            return
        if done:
            done(out)
    monkeypatch.setattr(jobs, 'run', run_now)
    monkeypatch.setattr(overlay, 'emulator_running', lambda: False)
    monkeypatch.setattr(gamesetup, 'firewall_allows', lambda emu: None)
    monkeypatch.setattr(gamesetup, 'server_answers', lambda host, **kw: (True, ''))   # no network in the tests
    calls = {'apply': [], 'undo': []}
    calls['menus'] = []

    calls['art'] = []

    def apply(game_dir, layers, database=None, menus=None, art=None, lang=None):
        calls['apply'].append(layers)
        calls['menus'].append(menus)
        calls['art'].append(art)
        return {'layers': layers}
    monkeypatch.setattr(overlay, 'apply', apply)
    monkeypatch.setattr(overlay, 'undo', lambda game_dir: calls['undo'].append(game_dir) or [])
    monkeypatch.setattr(overlay, 'status', lambda game_dir: {'applied': bool(calls['apply']), 'layers': {}, 'problems': []})
    monkeypatch.setattr(patch, 'art_packs', lambda cache_dir=None, game_dir=None, kits=True, photos=True, extras=None: (list(getattr(patch, '_test_packs', [])), []))
    from overtime_roster.app import patch_ctl
    monkeypatch.setattr(patch_ctl, 'packs_here', lambda cache: list(getattr(
        patch, '_test_found', patch.ART_PACKS if getattr(patch, '_test_packs', None) else [])))
    monkeypatch.setattr(SC, 'patch_cache', lambda: None)
    monkeypatch.setattr(patch_ctl, 'game_text', lambda game_dir, log=None: 'eng_us')    # the fake game has no loc files
    monkeypatch.setattr(SC.SetupController, '_seattle_ready', lambda self, database: getattr(self, 'seattle', False))
    ctl = FakeCtl(str(world['game']))
    s = SC.SetupController(ctl)
    s.calls, s.world = calls, world
    return s


def test_scan_finds_everything(sc):
    sc.setup_refresh()
    snap = sc.snap_setup()
    assert snap['emulator'] == str(sc.world['emu']) and snap['game_ok']
    assert snap['users'] == [{'user_id': 1000, 'name': 'shadPS4', 'shadnet': True, 'npid': 'skater',
                              'password': True}]
    assert not snap['installed'] and not snap['network_ok']
    assert snap['server'] == SC.SERVER and snap['server_default']
    assert 'hunter2' not in json.dumps(snap)


def test_one_click_then_unpatch(sc):
    sc.setup_refresh()
    sc.setup_patch()
    assert sc.calls['apply'] == [['text']]
    snap = sc.snap_setup()
    assert snap['installed'] and snap['intact'] and snap['network_ok']
    assert snap['targets'] == {'redirector': 'ot.puckpeak.com', 'nucleus': [
        'https://ot.puckpeak.com/', 'https://91.98.195.150/', 'https://91.98.195.150/']}
    assert snap['clean'] and gamesetup.load_clean()['files']['eboot.bin'][1]
    assert sc.ctl.prefs['patched_by'] == SC.VERSION    # Update warns when an older Overtime patched (update_ctl)
    sc.setup_verify()
    assert sc.verify_result['diff'] == []
    sc.setup_unpatch()
    assert sc.calls['undo'] == [str(sc.world['game'])]
    snap = sc.snap_setup()
    assert not snap['installed'] and not (sc.world['user'] / 'patches' / 'Overtime').exists()
    assert sc.ctl.said[-1][1] == 'good'


def test_patch_refused_for_wrong_game_and_running(sc, monkeypatch):
    sc.setup_refresh()
    monkeypatch.setattr(overlay, 'emulator_running', lambda: True)
    sc.setup_patch()
    assert sc.ctl.said[-1] == ('shadPS4 is running. Close NHL 19, then press Patch again.', 'caution')
    assert not gamesetup.load_manifest()
    assert sc.ctl.busy is None


def test_server_override_and_reset(sc):
    assert 'error' in sc.setup_set_server('ot.puckpeak.com', 'https://ot.puckpeak.com/')  # 24 > 23 / 22
    assert sc.setup_set_server('192.168.1.15') == {'ok': True}
    assert sc._xml() == SC.xmlpatch.build('192.168.1.15')
    assert sc.ctl.prefs['setup']['server'] == {'host': '192.168.1.15', 'nucleus_url': None}
    sc.setup_set_server('')
    assert sc.server == SC.SERVER and sc.ctl.prefs['setup']['server'] == {}


def test_emulator_pick(sc, tmp_path):
    other = tmp_path / 'notes.exe'
    other.write_bytes(b'MZ')
    assert 'error' in sc.setup_set_emulator(str(other))
    assert sc.setup_set_emulator(str(sc.world['emu'])) == {'ok': True}
    assert sc.ctl.prefs['setup']['emulator'] == str(sc.world['emu'])


def test_play_refusal_is_reported(sc, monkeypatch):
    def refuse(*a, **kw):
        raise launch.LaunchError('shadPS4 is already running.')
    monkeypatch.setattr(launch, 'start', refuse)
    sc.setup_refresh()
    assert sc.setup_play() == {'error': 'shadPS4 is already running.'}


def test_one_click_switch_off_takes_its_layer_away(sc, monkeypatch):
    monkeypatch.setattr(overlay, 'status', lambda game_dir: {'applied': True, 'problems': [],
                                                            'layers': {'text': {}, 'database': {'bytes': 1}}})
    sc.setup_refresh()
    sc.setup_patch()
    assert sc.calls['apply'] == [['text']]  # a switch that is off is off: the served default roster goes


def test_one_click_hides_modes_with_options(sc, monkeypatch):
    sc.ctl.patch_want.update(menus=True, chel=True)
    monkeypatch.setattr(overlay, 'status', lambda game_dir: {'applied': True, 'problems': [],
                                                            'layers': {'menus': {'options': {'chel': False}}}})
    sc.setup_refresh()
    sc.setup_patch()
    assert sc.calls['apply'] == [['text', 'menus']] and sc.calls['menus'] == [{'chel': True, 'news': True}]


def test_patch_brings_the_news_tile_back_over_a_beta1_patch(sc, monkeypatch):
    """news is not a switch: a beta1 patch served the hub without the news tile (news False), Patch serves it again."""
    sc.ctl.patch_want.update(menus=True, chel=False)
    monkeypatch.setattr(overlay, 'status', lambda game_dir: {'applied': True, 'problems': [], 'layers': {
        'menus': {'options': {'chel': False, 'news': False}, 'news': False}}})
    sc.setup_refresh()
    sc.setup_patch()
    assert sc.calls['menus'] == [{'chel': False, 'news': True}]


def test_one_click_menus_off_drops_served_menus(sc, monkeypatch):
    sc.ctl.patch_want.update(menus=False)
    monkeypatch.setattr(overlay, 'status', lambda game_dir: {'applied': True, 'problems': [],
                                                            'layers': {'text': {}, 'menus': {'options': {}}}})
    sc.setup_refresh()
    sc.setup_patch()
    assert sc.calls['apply'] == [['text']]  # switched off here: the served menus edit goes


def test_one_click_all_switches_off_removes_the_data_patch(sc, monkeypatch):
    sc.ctl.patch_want = {'text': False, 'names': False, 'league': False, 'roster': False, 'menus': False}
    monkeypatch.setattr(overlay, 'status', lambda game_dir: {'applied': True, 'problems': [],
                                                            'layers': {'text': {}, 'menus': {'options': {}}}})
    sc.setup_refresh()
    sc.setup_patch()
    assert sc.calls['apply'] == [] and sc.calls['undo'] == [sc.ctl.game_dir]  # as the Patch tab does it
    assert sc.ctl.said[-1][1] == 'good'


def test_play_double_click_starts_one_emulator(sc, monkeypatch):
    started = []
    monkeypatch.setattr(launch, 'start', lambda *a, **kw: started.append(a) or object())
    sc.emulator = str(sc.world['emu'])
    sc._launching = True  # the first click is still inside launch.start
    assert sc.setup_play() is None and started == []


def test_one_click_keeps_31_teams_without_seattle(sc):
    """The 32-team switch only with a roster whose Seattle has players and is active (New Season crash, ws8 run7a)."""
    installed = sc.world['user'] / 'patches' / 'Overtime' / 'overtime.xml'
    sc.setup_refresh()
    sc.setup_patch()
    assert not SC.xmlpatch.expansion32(installed.read_text(encoding='utf-8'))
    assert '31 teams' in sc.ctl.said[-1][0] and sc.ctl.said[-1][1] == 'good'
    sc.seattle = True
    sc.setup_patch()
    assert SC.xmlpatch.expansion32(installed.read_text(encoding='utf-8')) and '31' not in sc.ctl.said[-1][0]


def test_one_click_seattle_in_be_a_pro_only_with_the_league_layer(sc):
    """bap32 offers Seattle in Choose Team; the league layer's Lua makes the career start there."""
    installed = sc.world['user'] / 'patches' / 'Overtime' / 'overtime.xml'
    sc.seattle = True
    sc.setup_refresh()
    sc.setup_patch()  # the fake's league switch is off
    text = installed.read_text(encoding='utf-8')
    assert SC.xmlpatch.expansion32(text) and not SC.xmlpatch.bap32(text)
    sc.ctl.patch_want = {**sc.ctl.patch_want, 'league': True}
    sc.setup_patch()
    text = installed.read_text(encoding='utf-8')
    assert SC.xmlpatch.expansion32(text) and SC.xmlpatch.bap32(text)


def test_seattle_ready_reads_the_roster_the_game_starts_from(sc, monkeypatch):
    parsed = []
    monkeypatch.setattr(SC, 'tdb', types.SimpleNamespace(Database=types.SimpleNamespace(
        parse=lambda raw, schema: parsed.append(raw) or raw)))
    monkeypatch.setattr(SC, 'rosterupdate', types.SimpleNamespace(seattle_ready=lambda db: db == b'filled'))
    sc.ctl.game = types.SimpleNamespace(schema=lambda: None)
    assert SEATTLE_READY(sc, b'filled') and not SEATTLE_READY(sc, b'empty')  # the default roster just built
    assert not SEATTLE_READY(sc, None)  # no database layer: the stock roster, Seattle empty
    monkeypatch.setattr(overlay, 'status', lambda game_dir: {'layers': {'database': {}}})
    monkeypatch.setattr(overlay, '_current_database', lambda game_dir, state: b'filled')
    assert SEATTLE_READY(sc, None) and parsed == [b'filled', b'empty', b'filled']  # the one served now


def test_refused_server_and_emulator_are_said(sc, tmp_path):
    sc.setup_set_server('my--pc.lan')
    assert sc.ctl.said[-1][1] == 'bad' and sc.server == SC.SERVER
    other = tmp_path / 'notes.exe'
    other.write_bytes(b'MZ')
    sc.setup_set_emulator(str(other))
    assert sc.ctl.said[-1][1] == 'bad'


def test_one_click_serves_the_art_packs_found(sc, monkeypatch):
    monkeypatch.setattr(patch, '_test_packs', ['looks', 'photos'], raising=False)
    sc.ctl.patch_want['art'] = True
    sc.setup_refresh()
    sc.setup_patch()
    assert sc.calls['apply'] == [['text', 'art']] and sc.calls['art'] == [['looks', 'photos']]


def test_one_click_art_off_drops_the_served_art(sc, monkeypatch):
    monkeypatch.setattr(patch, '_test_packs', ['looks'], raising=False)
    sc.ctl.patch_want['art'] = False
    monkeypatch.setattr(overlay, 'status', lambda game_dir: {'applied': True, 'problems': [],
                                                            'layers': {'text': {}, 'art': {'packs': []}}})
    sc.setup_refresh()
    sc.setup_patch()
    assert sc.calls['apply'] == [['text']] and sc.calls['art'] == [None]


def test_one_click_without_packs_takes_the_served_art_away(sc, monkeypatch):
    """v0.10.0: the art switch needs the Photos, logos pack here; without it the switch is off, so Patch takes a
    served art layer away (the game's own look)."""
    sc.ctl.patch_want['art'] = True
    monkeypatch.setattr(overlay, 'status', lambda game_dir: {'applied': True, 'problems': [],
                                                            'layers': {'text': {}, 'art': {'packs': []}}})
    sc.setup_refresh()
    sc.setup_patch()
    assert sc.calls['apply'] == [['text']] and sc.calls['art'] == [None]


# --- Downloads (packdownload) and This program's Check now (2026-10-21) --------------------------------------------
class FakeShell:
    def __init__(self):
        self.asked = []

    def ask(self, title, lines, buttons, answers=None, tone=''):
        self.asked.append((title, lines, [b[1] for b in buttons], dict(answers or {})))

    def ask_unsaved(self, what, go):
        return go()


def _packs_world(sc, monkeypatch, tmp_path):
    from overtime_roster.app import packdownload
    cache = tmp_path / 'cache'
    cache.mkdir()
    monkeypatch.setattr(SC, 'patch_cache', lambda: str(cache))
    monkeypatch.delenv('OVERTIME_ART_PACKS', raising=False)
    have = {'looks32.zip'}
    got = []

    def status(cache_dir, game_dir=None, **kw):
        return [{'name': n, 'title': p['title'], 'core': p['core'], 'size': 2 ** 20 * 5,
                 'state': 'here' if n in have else 'missing', 'local_size': 2 ** 20 * 5 if n in have else None,
                 'removable': n in have, 'text': ''} for n, p in packdownload.PACKS.items()]

    def download(names, cache_dir, progress=None, game_dir=None, **kw):
        out = []
        for n in names:
            progress(n, 1, 2)
            got.append(n)
            have.add(n)
            out.append((n, True, 'Downloaded.'))
        return out

    def remove(name, cache_dir):
        had = name in have
        have.discard(name)
        return had
    monkeypatch.setattr(packdownload, 'status', status)
    monkeypatch.setattr(packdownload, 'download', download)
    monkeypatch.setattr(packdownload, 'remove', remove)
    sc.ctl.shell = FakeShell()
    sc.ctl.parts = {}
    return have, got


def _downloads(sc):
    return sc._downloads(sc.known_emulator())


def test_downloads_list_every_pack_and_fetch_them(sc, monkeypatch, tmp_path):
    from overtime_roster.app import packdownload
    have, got = _packs_world(sc, monkeypatch, tmp_path)
    sc.packs = SC.pack_status(SC.patch_cache())
    d = _downloads(sc)
    assert [r['name'] for r in d['rows']] == list(packdownload.PACKS)
    assert d['all']['can'] is False and d['note']                   # shadPS4 not picked yet: nothing to fetch
    assert sc.pack_download('looks.zip') == {'error': d['note']} and got == []
    sc.setup_set_emulator(str(sc.world['emu']))
    d = _downloads(sc)
    assert d['all'] == {'can': True, 'count': 5, 'title': 'Download the 5 packs not on this PC'}
    row = {r['name']: r for r in d['rows']}
    assert row['looks32.zip']['can_remove'] and not row['looks32.zip']['can_download']
    assert row['looks.zip']['can_download'] and row['looks.zip']['size'] == '5 MB'
    assert sc.pack_download('nope.zip') == {'error': 'Overtime Roster does not know this pack.'}
    sc.pack_download('looks.zip')
    assert got == ['looks.zip'] and sc.ctl.busy is None and sc.dl is None
    assert sc.ctl.said[-1] == ('Downloaded: Utah and Seattle looks. Patch the game again to put them in.', 'good')
    sc.packs_download_all()
    assert got == ['looks.zip', 'photos.zip', 'people.zip', 'clubart.zip', 'kits.zip'] and _downloads(sc)['all']['count'] == 0
    sc.packs_download_all()
    assert sc.ctl.said[-1] == ('Every pack is downloaded already.', 'good')
    assert sc._kits(_downloads(sc))['state'] == 'ready'                    # beta1's kits row follows kits.zip


def test_get_shadps4_opens_the_official_launcher(sc, monkeypatch):
    opened = []
    monkeypatch.setattr(SC.webbrowser, 'open', opened.append)
    sc.setup_emulator_page()
    assert opened == ['https://github.com/shadps4-emu/shadps4-qtlauncher/releases'] and 'QtLauncher' in sc.ctl.said[-1][0]


def test_any_build_of_shadps4_is_good(sc):
    tile = lambda key, value, tone, text: (value, tone, text)
    main = {'version': '0.21.1 WIP', 'rev': '8a66adab', 'branch': 'main', 'remote': ''}
    assert sc._emulator_tile({'build': main}, tile)[:2] == ('0.21.1 WIP', 'good')
    assert sc._emulator_tile({'build': None}, tile)[:2] == ('Found', 'good')


def _extras(sc):
    from overtime_roster.app import patch_ctl
    with sc.ctl.lock:
        want = dict(sc.ctl.patch_want)
    found = patch_ctl.packs_here(SC.patch_cache())
    card = sc.extra_card(sc.known_emulator(), want, patch_ctl.switches(want, found), {}, False)
    return {r['key']: r for r in card['rows']}


def test_a_pack_switch_downloads_the_pack_and_off_keeps_it(sc, monkeypatch, tmp_path):
    from overtime_roster.app import patch_ctl
    have, got = _packs_world(sc, monkeypatch, tmp_path)
    monkeypatch.setattr(patch_ctl, 'packs_here', lambda cache: sorted(have))
    sc.packs = SC.pack_status(SC.patch_cache())
    sc.ctl.patch_want.update(art=False)
    assert _extras(sc)['ice_all']['disabled']                               # no shadPS4 yet, no team art
    sc.setup_set_emulator(str(sc.world['emu']))
    sc.pack_switch('ice_all', True)
    assert got == [] and not sc.ctl.patch_want.get('ice_all') and sc.ctl.said[-1][1] == 'caution'
    sc.ctl.patch_want.update(art=True)
    assert list(_extras(sc)) == list(patch_ctl.EXTRA_KEYS) and 'nothing is downloaded' in _extras(sc)['alts_intl']['text']
    sc.pack_switch('alts_intl', True)
    assert got == ['kitlayers_intl.zip'] and sc.ctl.busy is None and sc.dl is None and sc.ctl.patch_want['alts_intl']
    assert sc.ctl.said[-1][1] == 'good' and 'Press Patch' in sc.ctl.said[-1][0]
    assert _extras(sc)['alts_intl']['on'] and _extras(sc)['alts_intl']['text'] == 'Downloaded (5 MB).'
    assert patch_ctl.switches(sc.ctl.patch_want, sorted(have))['alts_intl']
    sc.pack_switch('alts_intl', False)
    assert 'kitlayers_intl.zip' in have and not sc.ctl.patch_want['alts_intl']   # kept on this PC
    assert 'Kept on this PC' in _extras(sc)['alts_intl']['text']
    picked, now = {'alts_intl': False}, {'alts_intl': True}
    rows = sc.extra_card(sc.known_emulator(), dict(sc.ctl.patch_want), picked, now, True)['rows']
    row = next(r for r in rows if r['key'] == 'alts_intl')
    assert row['tag']['text'] == 'Patch to take away' and 'Kept on this PC' in row['text']
    sc.pack_switch('alts_intl', True)
    assert got == ['kitlayers_intl.zip'] and sc.ctl.patch_want['alts_intl']      # here already: no second download
    assert sc.pack_switch('nope', True) == {'error': 'Overtime Roster does not know this pack.'}


def test_packs_switched_on_during_a_download_wait_their_turn_and_a_failure_goes_off(sc, monkeypatch, tmp_path):
    from overtime_roster.app import packdownload, patch_ctl
    have, got = _packs_world(sc, monkeypatch, tmp_path)
    monkeypatch.setattr(patch_ctl, 'packs_here', lambda cache: sorted(have))
    sc.setup_set_emulator(str(sc.world['emu']))
    sc.ctl.patch_want.update(art=True, ice_all=True, alts_intl=True)        # both on before the first job starts
    sc.packs = SC.pack_status(SC.patch_cache())
    sc._extras_next()
    assert got == ['ice_all.zip', 'kitlayers_intl.zip'] and sc.ctl.busy is None
    have.difference_update(patch.EXTRA_PACKS)
    sc.ctl.patch_want.update(ice_all=False, alts_intl=False)
    sc.packs = SC.pack_status(SC.patch_cache())

    def broken(names, cache_dir, **kw):
        return [(names[0], False, 'The disk said no.')]
    monkeypatch.setattr(packdownload, 'download', broken)
    sc.pack_switch('alts_intl', True)
    assert not sc.ctl.patch_want['alts_intl'] and sc.ctl.said[-1] == ('National team jerseys from NHL 27: The disk said no.', 'bad')

    def crashed(names, cache_dir, **kw):
        raise OSError('disk full')
    monkeypatch.setattr(packdownload, 'download', crashed)
    sc.pack_switch('ice_all', True)
    assert not sc.ctl.patch_want['ice_all'] and sc.ctl.busy is None         # one try, not a loop


def test_a_pack_switched_off_while_it_downloads_stops(sc, monkeypatch, tmp_path):
    from overtime_roster.app import packdownload, patch_ctl
    have, got = _packs_world(sc, monkeypatch, tmp_path)
    monkeypatch.setattr(patch_ctl, 'packs_here', lambda cache: sorted(have))
    sc.setup_set_emulator(str(sc.world['emu']))
    sc.ctl.patch_want.update(art=True)
    sc.packs = SC.pack_status(SC.patch_cache())

    def download(names, cache_dir, progress=None, game_dir=None, cancelled=None, **kw):
        progress(names[0], 1, 2)
        row = _extras(sc)['ice_all']
        assert row['progress'] == 0.5 and row['text'] == 'Downloading... 50 % of 5 MB' and not row['disabled']
        assert _extras(sc)['alts_intl']['disabled'] is False                # another can be switched on meanwhile
        sc.pack_switch('ice_all', False)
        assert cancelled()
        return [(names[0], False, packdownload.STOPPED)]
    monkeypatch.setattr(packdownload, 'download', download)
    sc.pack_switch('ice_all', True)
    assert not sc.ctl.patch_want['ice_all'] and sc.ctl.busy is None and sc.dl is None
    assert 'ice_all.zip' not in have


def test_the_pack_card_is_not_the_jersey_packs_download(sc, monkeypatch, tmp_path):
    have, _got = _packs_world(sc, monkeypatch, tmp_path)
    sc.setup_set_emulator(str(sc.world['emu']))
    sc.packs = SC.pack_status(SC.patch_cache())
    sc.dl = {'names': ['kitlayers_intl.zip'], 'name': 'kitlayers_intl.zip', 'part': 0.1, 'share': 0.1}
    sc.ctl.busy = 'Downloading'
    assert sc.pack_card(sc.known_emulator())['state'] != 'downloading'
    sc.ctl.busy, sc.dl = None, None


def test_only_the_packs_switched_on_are_served(monkeypatch, tmp_path):
    from overtime_core import kitcompose
    from overtime_roster.app import sources
    monkeypatch.delenv('OVERTIME_ART_PACKS', raising=False)
    monkeypatch.setattr(sources, 'BUILD_PACKS', str(tmp_path / 'exe-packs'))
    monkeypatch.setattr(sources, 'REPO_PACKS', str(tmp_path / 'repo-packs'))
    # the jerseys a family's layer pack made on this PC (patch.make_kits) are served as the family's switch says
    names = {'looks32.zip': 'looks32', patch.ICE_PACK: 'ice_all', patch.RINK_PACK: 'rink',
             **{kitcompose.local_pack(f): kitcompose.served_name(f) for f in kitcompose.FAMILIES}}
    for i, (name, served) in enumerate(names.items()):
        art.write_pack(str(tmp_path / name), served, {f'nhl/ui/kettle_assets/teamlogos/large/t{i}.gnf': b'GNF ' + bytes(60)})
    layers = []
    want = {'art': True, 'kits': False, 'photos': False, 'alts_intl': True, 'ice_all': True}
    packs = patch.art_layer(want, layers, str(tmp_path))
    assert [p.name for p in packs] == ['looks32', 'ice_all', 'alts-intl'] and layers == ['art']
    assert not set(patch.KITLAYER_PACKS) & set(patch.ART_PACKS)     # the layer packs are made into textures first
    assert [p.name for p in patch.art_layer({'art': True, 'kits': False, 'photos': False}, [], str(tmp_path))] == ['looks32']


def test_downloads_delete_asks_first(sc, monkeypatch, tmp_path):
    have, _got = _packs_world(sc, monkeypatch, tmp_path)
    sc.packs = SC.pack_status(SC.patch_cache())
    sc.pack_remove('looks.zip')                                     # not downloaded: nothing to ask
    assert sc.ctl.shell.asked == [] and 'nothing downloaded' in sc.ctl.said[-1][0]
    sc.pack_remove('looks32.zip')
    (title, _lines, buttons, answers), = sc.ctl.shell.asked
    assert title == 'Delete "NHL 27 looks for all 32 teams"?' and buttons == ['delete', 'keep']
    assert 'looks32.zip' in have
    answers['delete']()
    assert 'looks32.zip' not in have and sc.ctl.said[-1][1] == 'good'
    assert not {r['name']: r for r in _downloads(sc)['rows']}['looks32.zip']['can_remove']


def test_check_now_asks_what_it_found(sc, monkeypatch):
    from overtime_roster.app import selfupdate
    sc.ctl.shell = FakeShell()
    marked = []
    monkeypatch.setattr(selfupdate, 'mark_checked', lambda *a: marked.append(1))
    monkeypatch.setattr(selfupdate, 'latest', lambda fetch_text=None, **kw: None)
    sc.check_now()
    assert sc.ctl.shell.asked[-1][0] == 'You have the newest version' and marked and sc.looked
    assert sc._program()['state'] == {'tone': 'good', 'text': 'This is the newest version.'}

    def offline(fetch_text=None, **kw):
        try:
            fetch_text('https://example.invalid/latest.json')
        except Exception:
            return None
    monkeypatch.setattr(selfupdate, 'http_text', lambda url, timeout=None: (_ for _ in ()).throw(OSError('down')))
    monkeypatch.setattr(selfupdate, 'latest', offline)
    marked.clear()
    sc.check_now()
    assert sc.ctl.shell.asked[-1][0] == 'The program could not look' and not marked
    release = types.SimpleNamespace(text='9.9.9', notes='- Faster\n- Better', page='', can_install=lambda: False)
    monkeypatch.setattr(selfupdate, 'latest', lambda fetch_text=None, **kw: release)
    sc.check_now()
    title, lines, buttons, answers = sc.ctl.shell.asked[-1]
    assert title == 'Version 9.9.9 is out' and 'Faster' in lines and buttons == ['page', 'later', 'skip']
    assert sc._program()['newer'] == {'version': '9.9.9', 'notes': ['Faster', 'Better']}
    answers['skip']()
    assert sc._program()['newer'] is None and sc.ctl.prefs['setup']['skipped'] == '9.9.9'
    sc.ctl.busy = 'Patching NHL 19...'
    assert sc.check_now() is None and sc.ctl.said[-1] == ('Wait a moment: patching NHL 19 is still running.', 'caution')


@pytest.mark.game
def test_rosters_delete_moves_the_save_to_the_recycle_bin(game_dir, default_roster, tmp_path, monkeypatch):
    """Through the Controller, on the game's roster and a throwaway saves folder: the game's roster cannot go,
    a save goes only after the question (and not while shadPS4 runs); the open one gone, the Overtime default opens."""
    import shutil
    from overtime_roster.app import controller as C, sources, trash
    from test_savebar_app import Host, _template_save
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'home'))

    def inline(work, done=None, failed=None, expected=()):
        try:
            out = work()
        except expected as err:
            return failed and failed(str(err))
        return done and done(out)
    monkeypatch.setattr(jobs, 'run', inline)
    moved = []
    monkeypatch.setattr(trash, '_shell_delete', lambda op: moved.append(op.pFrom) or shutil.rmtree(op.pFrom) or 0)
    monkeypatch.setattr(trash.sys, 'platform', 'win32')
    running = [False]
    monkeypatch.setattr(overlay, 'emulator_running', lambda: running[0])
    saves = str(tmp_path / 'saves')
    _template_save(saves)
    c = C.Controller(Host(), game_dir=game_dir, save_dir=saves)
    c.load_source(sources.GAME_ID)
    assert c.calls['rosters_delete']('game') == {'error': 'The game roster and the Overtime default cannot be deleted.'}
    c.calls['save_name']('Gone soon')
    c.calls['save'](None)
    rosters = c.parts['rosters']
    ident = rosters.open_id
    assert ident == 'save:RosterCustom0' and os.path.isdir(os.path.join(saves, 'RosterCustom0'))
    running[0] = True
    c.calls['rosters_delete'](ident)
    assert c.host.snap('question')['title'] == 'Close shadPS4 first'
    running[0] = False
    c.calls['rosters_delete'](ident)
    q = c.host.snap('question')
    assert q['title'] == 'Move "Gone soon" to the Recycle Bin?' and [b['answer'] for b in q['buttons']] == ['delete', 'keep']
    assert any('Overtime default opens instead' in line for line in q['lines'])
    c.calls['answer'](q['id'], 'delete')
    assert moved == [os.path.join(saves, 'RosterCustom0')] and not os.path.exists(moved[0])
    assert rosters.open_id != ident and c.session is not None          # the Overtime default is open now
    assert 'is in the Recycle Bin' in c.status['text']


def test_one_click_never_downloads_packs(sc, monkeypatch, tmp_path):
    """v0.10.0: Patch uses only the packs here; downloading is the Photos, logos pack card's."""
    from overtime_roster.app import packdownload, patch_ctl
    monkeypatch.setattr(patch_ctl, 'cache_dir', lambda: str(tmp_path / 'cache'))
    monkeypatch.setattr(packdownload, 'missing_core', lambda cache, game_dir=None: ['looks32.zip', 'photos.zip'])
    monkeypatch.setattr(packdownload, 'download', lambda *a, **kw: pytest.fail('the patch downloaded a pack'))
    monkeypatch.setattr(SC.SetupController, '_default_roster', lambda self: object())
    sc.ctl.patch_want.update(art=True, roster=True, photos=True)
    sc.setup_refresh()
    sc.setup_patch()
    assert sc.calls['apply'] and 'art' not in sc.calls['apply'][0]     # no pack here: the art switch is off
    text, tone = next((t, tone) for t, tone in reversed(sc.ctl.said) if t.startswith('Patched'))
    assert tone == 'good' and 'not downloaded' not in text


def test_pack_switches_need_the_pack():
    from overtime_roster.app import patch_ctl
    everything = list(patch.ART_PACKS)
    assert not any(patch_ctl.switches({'roster': True}, everything)[k] for k in patch_ctl.PACK_KEYS)   # off by default
    on = {'roster': True, 'art': True, 'photos': True, 'kits': True}
    assert all(patch_ctl.switches(on, everything)[k] for k in patch_ctl.PACK_KEYS)
    assert not any(patch_ctl.switches(on, [])[k] for k in patch_ctl.PACK_KEYS)
    assert patch_ctl.why(on, 'art', []) == patch_ctl.NO_PACK and 'Utah' in patch_ctl.NO_PACK and 'Seattle' in patch_ctl.NO_PACK
    assert patch_ctl.why(on, 'art', ['looks.zip']) is None                       # either looks pack is the art
    assert patch_ctl.why(on, 'kits', ['looks.zip']) == patch_ctl.NO_PACK         # the kits need kits.zip
    assert patch_ctl.why(dict(on, roster=False), 'photos', everything) == \
        f'Needs the {patch_ctl.SEASON_LABEL} default roster.'
    assert patch_ctl.why(dict(on, art=False), 'photos', everything) == 'Needs "NHL 27 team art".'
    served = patch_ctl.served({'layers': {'art': {'packs': [{'name': 'looks'}, {'name': 'photos'}]}}})
    assert served['photos'] and served['art'] and not served['kits']


def _card(sc):
    return sc.pack_card(sc.known_emulator())


def test_pack_card_downloads_all_and_switches_on(sc, monkeypatch, tmp_path):
    from overtime_roster.app import patch_ctl
    have, got = _packs_world(sc, monkeypatch, tmp_path)
    monkeypatch.setattr(patch_ctl, 'packs_here', lambda cache: sorted(have))
    sc.ctl.patch_want.update(roster=True)
    sc.packs = SC.pack_status(SC.patch_cache())
    card = _card(sc)
    assert card['title'] == SC.PACK_TITLE and not card['can_download'] and 'Pick shadPS4' in card['text']
    sc.setup_set_emulator(str(sc.world['emu']))
    card = _card(sc)
    assert card['state'] == 'partial' and card['can_download'] and card['size'] == '25 MB'   # the 5 missing
    assert card['text'] == '1 of 6 packs downloaded. Download the rest (25 MB).' and card['can_remove']
    sc.packs_get()
    assert got == ['looks.zip', 'photos.zip', 'people.zip', 'clubart.zip', 'kits.zip'] and sc.dl is None
    assert sc.ctl.said[-1] == (f'{SC.PACK_TITLE} downloaded and switched on. Press Patch to put it in the game.',
                               'good')
    assert all(sc.ctl.patch_want[k] for k in patch_ctl.PACK_KEYS)
    assert sc.ctl.prefs['patch']['art'] and sc.ctl.prefs['patch']['kits']
    card = _card(sc)
    assert card['state'] == 'here' and card['tone'] == 'good' and card['size'] == '30 MB'


def test_pack_card_photos_wait_for_the_roster_switch(sc, monkeypatch, tmp_path):
    from overtime_roster.app import patch_ctl
    have, _got = _packs_world(sc, monkeypatch, tmp_path)
    monkeypatch.setattr(patch_ctl, 'packs_here', lambda cache: sorted(have))
    sc.ctl.patch_want.update(roster=False)
    sc.setup_set_emulator(str(sc.world['emu']))
    sc.packs = SC.pack_status(SC.patch_cache())
    sc.packs_get()
    assert sc.ctl.patch_want['art'] and sc.ctl.patch_want['kits'] and not sc.ctl.patch_want['photos']


def test_pack_card_delete_asks_then_switches_off(sc, monkeypatch, tmp_path):
    from overtime_roster.app import patch_ctl
    have, _got = _packs_world(sc, monkeypatch, tmp_path)
    have.update(n for n in patch.ART_PACKS if n not in patch.EXTRA_PACKS)   # the switched packs are not the card's
    monkeypatch.setattr(patch_ctl, 'packs_here', lambda cache: sorted(have))
    sc.ctl.patch_want.update(art=True, photos=True, kits=True, roster=True)
    sc.packs = SC.pack_status(SC.patch_cache())
    sc.packs_drop()
    (title, lines, buttons, answers), = sc.ctl.shell.asked
    assert title == f'Delete the {SC.PACK_TITLE}?' and buttons == ['delete', 'keep'] and '25 MB' in lines[0]
    assert have == set(patch.ART_PACKS) - set(patch.EXTRA_PACKS)         # nothing gone before the answer
    answers['delete']()
    assert not have and not any(sc.ctl.patch_want[k] for k in patch_ctl.PACK_KEYS)
    assert sc.ctl.said[-1] == (f'The {SC.PACK_TITLE} is deleted. Patch the game again to take it out.', 'good')
    card = _card(sc)
    assert card['state'] == 'missing' and not card['can_remove']
    sc.setup_set_emulator(str(sc.world['emu']))
    assert patch_ctl.NO_PACK in _card(sc)['text']


def test_pack_switches_migrate_once(tmp_path, monkeypatch):
    """v0.10.0: a fresh install has the pack switches off; an older install keeps them when it has a pack in the
    cache or the game is served art; after the marker the settings are taken as they are."""
    from overtime_roster.app import controller as C, paths
    monkeypatch.setattr(paths, 'app_dir', lambda name: str(tmp_path / name))
    game = tmp_path / 'game'
    old = {'patch': {'text': False, 'kits': False}}
    assert C.packs_migrate({}, str(game)) == {}                               # fresh: the defaults (off)
    assert C.packs_migrate(old, str(game)) == {'text': False}                 # no pack: the pack switches go off
    (tmp_path / 'cache').mkdir()
    (tmp_path / 'cache' / 'looks.zip').write_bytes(b'PK')
    assert C.packs_migrate(old, str(game)) == {'text': False, 'art': True, 'photos': True, 'kits': False}
    (tmp_path / 'cache' / 'looks.zip').unlink()
    monkeypatch.setattr(overlay, '_load_state', lambda game_dir: {'layers': {'art': {'packs': []}}})
    assert C.packs_migrate(old, str(game))['art'] is True                     # served art counts too
    marked = {'patch': {'art': False, 'photos': True}, 'packs_default': C.PACKS_DEFAULT}
    assert C.packs_migrate(marked, str(game)) == {'art': False, 'photos': True}


def test_a_new_server_and_switched_off_network_need_no_patch(sc, monkeypatch):
    """Owner, 2026-11-03: "the app doesnt need a patch each time we edit network settings"."""
    from overtime_roster.app import patch_ctl
    sc.setup_set_server('192.168.1.15')                 # not patched yet: Patch puts it in
    assert sc.ctl.said[-1] == ('Server set to 192.168.1.15. Patch the game to use it.', 'good')
    sc.setup_set_server('')
    sc.setup_refresh()
    sc.setup_patch()
    emu = str(sc.world['emu'])
    sc.setup_set_server('192.168.1.15')
    st = gamesetup.status(emu)
    assert st['intact'] and st['targets']['redirector'] == '192.168.1.15'
    assert sc.ctl.said[-1] == ('Server set to 192.168.1.15. NHL 19 uses it from its next start.', 'good')
    cfg_path = sc.world['user'] / 'custom_configs' / 'CUSA11126.json'
    cfg = json.loads(cfg_path.read_text())
    cfg['GPU'] = {'full_screen': False}                 # the player's own shadPS4 setting: still patched
    cfg_path.write_text(json.dumps(cfg))
    assert gamesetup.status(emu)['intact']
    cfg['General']['shad_net_enabled'] = False          # a network switch off: Play turns it on again
    cfg_path.write_text(json.dumps(cfg))
    assert gamesetup.status(emu)['problems'] == [f'network switched off: {cfg_path}']
    monkeypatch.setattr(overlay, 'emulator_running', lambda: True)
    sc.setup_set_server('')                             # shadPS4 runs: the next start does it
    assert sc.ctl.said[-1] == ('The Overtime server is set again. NHL 19 uses it from its next start.', 'good')
    assert gamesetup.status(emu)['targets']['redirector'] == '192.168.1.15'
    monkeypatch.setattr(overlay, 'emulator_running', lambda: False)
    at_start = []
    monkeypatch.setattr(launch, 'start', lambda emu_exe, game_dir: at_start.append(gamesetup.status(emu)) or
                        types.SimpleNamespace(pid=7, poll=lambda: 0))
    monkeypatch.setattr(sc, '_watch_play', lambda emu_exe, proc: None)
    assert patch_ctl.start(sc) == {'ok': True}
    assert at_start[0]['intact'] and at_start[0]['targets']['redirector'] == 'ot.puckpeak.com'
    after = json.loads(cfg_path.read_text())
    assert after['GPU'] == {'full_screen': False} and after['General']['shad_net_enabled'] is True
    assert patch_ctl.refresh_network(sc) == 'same'
    sc.setup_unpatch()                                  # the player's own settings come back as they were
    general = json.loads(cfg_path.read_text())['General']
    assert general['connected_to_network'] is False and 'shad_net_enabled' not in general


def test_a_patch_file_of_another_version_still_asks_for_patch(sc):
    from overtime_roster.app import patch_ctl
    sc.setup_refresh()
    sc.setup_patch()
    path = sc.world['user'] / 'patches' / 'Overtime' / gamesetup.PATCH_FILE
    path.write_bytes(path.read_bytes().replace(b'82104380', b'82104381'))
    assert patch_ctl.refresh_network(sc) is None
    sc.setup_set_server('192.168.1.15')
    assert sc.ctl.said[-1] == ('Server set to 192.168.1.15. Patch the game again to use it.', 'good')


def test_a_game_without_english_text_is_patched_without_the_text_layers(sc, monkeypatch):
    """CUSA11116 (2026-11-03): no English text file leaves the text layers out with a line; the rest goes in."""
    from overtime_roster.app import patch_ctl
    monkeypatch.setattr(patch_ctl, 'game_text', lambda game_dir, log=None: None)
    sc.ctl.patch_want.update(names=True, league=True)
    sc.setup_refresh()
    sc.setup_patch()
    assert sc.calls['apply'] == [['league']]
    assert sc.ctl.prefs['left_out'] == ['text', 'names']
    text, tone = sc.ctl.said[-1]
    assert tone == 'good' and text.endswith("The Overtime texts and the new team names stay the game's own: this NHL 19 "
                                            'has no English text file.')
    monkeypatch.setattr(patch_ctl, 'game_text', lambda game_dir, log=None: 'eng_gb')
    monkeypatch.setattr(overlay, 'layer_fits', lambda game_dir, layer, lang: layer == 'text')
    sc.setup_patch()
    assert sc.calls['apply'][-1] == ['text', 'league'] and sc.ctl.prefs['left_out'] == ['names']
    assert sc.ctl.said[-1][0].endswith("The new team names stay the game's own: its English text file (eng_gb) is not "
                                       'the one the patch knows.')


def test_an_update_folder_alone_is_refused_in_plain_words(tmp_path):
    from overtime_roster.app import patch_ctl
    from test_textpack import make_eb
    (tmp_path / 'databigs').mkdir()
    make_eb(str(tmp_path / 'databigs' / 'patch_inxp_56.big'), [('nhl/data/kettle/loc', 'eng_us.db', b'x')])
    with pytest.raises(patch_ctl.Refused, match='update but not the game itself'):
        patch_ctl.game_text(str(tmp_path))
    make_eb(str(tmp_path / 'databigs' / 'inxp_00.big'), [('nhl/data/common/gamemodes/database/t3db', 'nhl_game-meta.xml', b'x'),
                                                         ('nhl/data/kettle/loc', 'ger_de-meta.xml', b'x')])
    said = []
    assert patch_ctl.game_text(str(tmp_path), log=said.append) == 'eng_us'
    assert said == ['Text files: eng_us; metas: ger_de. The patch edits eng_us (read with the ger_de meta).']
