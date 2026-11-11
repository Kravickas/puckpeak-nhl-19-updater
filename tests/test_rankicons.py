"""Rank icons (overtime_core/rankicons.py, M5): every tier has an icon, the generated web files never drift from the
generator, the shapes stay in their box, and the after-game card draws the tier's polygons (swapping on a rank-up)
without a window (a fake GDI+ surface records the calls)."""
import os
import shutil
import subprocess
import sys

import pytest

from overtime_core import rankicons
from overtime_core.rating import TIERS, UNRANKED

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RANKED = [name for name, _low, _blurb in TIERS]


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8', newline='') as f:
        return f.read().replace('\r\n', '\n')     # a git checkout may turn the line endings


def test_every_tier_has_an_icon_and_its_own_colour():
    icons = rankicons.icons()
    assert set(icons) == {UNRANKED, *RANKED}
    assert all(icons[name] and icons[name]['shapes'] for name in icons)
    assert len({icons[name]['color'] for name in icons}) == len(icons)
    assert rankicons.icon('No such tier') is None and rankicons.svg('No such tier') == ''


def test_the_icons_are_the_ones_the_design_names():
    count = {name: len(rankicons.icon(name)['shapes']) for name in [UNRANKED, *RANKED]}
    assert count == {UNRANKED: 1, 'Minor League': 1, 'Rookie': 1, 'Pro': 2, 'Top 6': 3, 'Alternate Captain': 2,
                     'Captain': 2, 'All-Star': 1, 'Superstar': 3, 'Hall of Fame': 1}


@pytest.mark.parametrize('rel', [os.path.join('overtime_roster', 'web', 'js', 'rankicons.js'),
                                 os.path.join('overtime_server', 'http', 'web', 'rankicons.js')])
def test_the_generated_js_equals_the_generator_output(rel):
    if not os.path.exists(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), rel)):
        pytest.skip('not in this tree (the public repo has no server)')
    assert _read(rel) == rankicons.render_js(), f'{rel} is stale: py -3.13 -m overtime_core.rankicons'


def test_the_shapes_stay_in_the_64_unit_box():
    for name in [UNRANKED, *RANKED]:
        for fill, pts in rankicons._shapes(name):
            assert all(0 <= x <= rankicons.BOX and 0 <= y <= rankicons.BOX for x, y in pts), name


def test_svg_is_a_box_with_one_path_per_shape():
    text = rankicons.svg('Superstar', 32)
    assert text.startswith('<svg ') and 'viewBox="0 0 64 64"' in text and 'width="32"' in text
    assert text.count('<path ') == 3 and 'aria-label="Superstar"' in text
    assert 'fill="#ffffff"' in rankicons.svg('Captain') and 'fill="#ffffff"' not in rankicons.svg('Pro')


def test_pixels_scale_and_move_with_the_square():
    polys = rankicons.pixels('Pro', 100, 50, 128)
    assert len(polys) == 2
    colour, pts = polys[0]
    assert colour == rankicons.COLOURS['Pro']
    x0, y0 = rankicons._shapes('Pro')[0][1][0]
    assert pts[0] == pytest.approx((100 + x0 * 2, 50 + y0 * 2))
    assert rankicons.pixels('No such tier', 0, 0, 10) == []


def test_the_js_wrapper_builds_an_svg_when_node_is_here():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    script = os.path.join(ROOT, 'overtime_roster', 'web', 'js', 'rankicons.js')
    out = subprocess.run([node, '-e', f"require({script!r}); process.stdout.write(rankIcon('Captain', 24))"],
                         capture_output=True, text=True, check=True).stdout
    assert out.startswith('<svg ') and out.count('<path ') == 2 and 'width="24"' in out
    assert rankicons.render_js().count('root.rankIcon') == 1


class FakeGfx:
    """Stands in for native.Gfx: records fill_polygon, accepts every other drawing call."""

    def __init__(self, fail=False):
        self.polys, self.fail = [], fail

    def font(self, *a, **k):
        return None

    def measure(self, *a, **k):
        return (10, 10)

    def fill_polygon(self, pts, color):
        if self.fail:
            raise RuntimeError('no GDI+')
        self.polys.append((color, len(pts)))

    def __getattr__(self, name):
        return lambda *a, **k: None


def _card(**over):
    data = dict(title='Final', sub='', rating_from=1089, rating_to=1112, tier='Pro', next_name='Top 6', next_at=1200,
                band_low=1100, rank_up='Pro', rank=5, of=40)
    data.update(over)
    return data


def test_the_result_card_swaps_the_icon_on_a_rank_up():
    from overtime_roster.hud import anim, cards
    from overtime_roster.hud.native import hexcolor
    res = anim.Result(_card(), 0.0)
    before, after = FakeGfx(), FakeGfx()
    cards.draw_result(before, res, 1.0, 1.0)           # before the flash: the tier below (Rookie, one chevron)
    cards.draw_result(after, res, 3.0, 1.0)            # after it: Pro (two chevrons)
    assert before.polys == [(hexcolor(rankicons.COLOURS['Rookie']), 6)]
    assert [c for c, _ in after.polys] == [hexcolor(rankicons.COLOURS['Pro'])] * 2


def test_icon_tier_is_the_tier_below_until_the_flash_on_a_rank_up():
    from overtime_roster.hud import anim
    res = anim.Result(_card(tier='Minor League', rank_up='Minor League', rank=None), 0.0)
    assert res.icon_tier(0.5) == UNRANKED and res.icon_tier(3.0) == 'Minor League'
    plain = anim.Result(_card(rank_up=None), 0.0)
    assert plain.icon_tier(0.5) == 'Pro'
    placing = anim.Result(_card(tier=None, rank_up=None, placing=3), 0.0)
    assert placing.icon_tier(1.0) == UNRANKED


def test_a_failing_gdi_plus_call_never_stops_the_card():
    from overtime_roster.hud import anim, cards
    cards.draw_result(FakeGfx(fail=True), anim.Result(_card(), 0.0), 3.0, 1.0)   # no exception
