"""Rank icons (v0.90.0, M5): ten original icons, one per rank tier, drawn as polygons in a 64-unit box.

The shapes are plain point lists so the same data serves three places: the web pages (generated JS below), the server
board, and the HUD's GDI+ polygon fill (overtime_roster/hud/cards.py). Every icon is one or more polygons filled with
the tier's colour (or a per-shape fill). A polygon with a hole is bridged into one contour and filled even-odd (the
Unranked ring).

Regenerate the two JS files after a change here:  py -3.13 -m overtime_core.rankicons
tests/test_rankicons.py fails when they are out of date. Notes: docs/notes/rank-icons.md.
"""
import json
import math
import os

from .rating import TIERS, UNRANKED

BOX = 64
WHITE = '#ffffff'
# tier -> colour (the tier's own; the badge patches take it as their field)
COLOURS = {
    UNRANKED: '#8a8f99',
    'Minor League': '#9a6b3f',
    'Rookie': '#5fb0e6',
    'Pro': '#3fb27f',
    'Top 6': '#2f7ad6',
    'Alternate Captain': '#a9b4c2',
    'Captain': '#ff8a1f',
    'All-Star': '#d25bd6',
    'Superstar': '#e5484d',
    'Hall of Fame': '#ffd84a',
}
CHEVRON_H, CHEVRON_T, CHEVRON_GAP = 18, 9, 14     # arm height, thickness, step between stacked chevrons


def _n(v):
    """A coordinate as the path text needs it: at most two decimals, no trailing zeros."""
    s = f'{v:.2f}'.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def _circle(cx, cy, r, n=32):
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def _star(cx, cy, big, small):
    pts = []
    for k in range(10):
        a = math.radians(-90 + 36 * k)
        r = big if k % 2 == 0 else small
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _chevron(top):
    h, t = CHEVRON_H, CHEVRON_T
    return [(10, top), (32, top + h), (54, top), (54, top + t), (32, top + h + t), (10, top + t)]


def _badge():
    """The patch's field: an octagon, inscribed radius about 27."""
    return [(32 + 29 * math.cos(math.radians(22.5 + 45 * k)), 32 + 29 * math.sin(math.radians(22.5 + 45 * k)))
            for k in range(8)]


def _letter_c():
    outer = [(32 + 15 * math.cos(math.radians(a)), 32 + 15 * math.sin(math.radians(a))) for a in range(40, 321, 10)]
    inner = [(32 + 8.5 * math.cos(math.radians(a)), 32 + 8.5 * math.sin(math.radians(a))) for a in range(320, 39, -10)]
    return outer + inner


LETTER_A = [(18, 46), (27, 18), (37, 18), (46, 46), (38, 46), (35, 37), (29, 37), (26, 46)]


def _ring():
    outer, inner = _circle(32, 32, 24), _circle(32, 32, 15)
    return outer + [outer[0]] + inner + [inner[0]]


def _shapes(tier):
    """The polygons of one tier: [(fill or None for the tier colour, [(x, y), ...]), ...]."""
    if tier == UNRANKED:
        return [(None, _ring())]
    if tier == 'Minor League':
        return [(None, [(14, 10), (50, 10), (50, 30), (44, 44), (32, 54), (20, 44), (14, 30)])]
    if tier in ('Rookie', 'Pro', 'Top 6'):
        count = {'Rookie': 1, 'Pro': 2, 'Top 6': 3}[tier]
        total = (count - 1) * CHEVRON_GAP + CHEVRON_H + CHEVRON_T
        top = (BOX - total) / 2
        return [(None, _chevron(top + k * CHEVRON_GAP)) for k in range(count)]
    if tier in ('Alternate Captain', 'Captain'):
        letter = LETTER_A if tier == 'Alternate Captain' else _letter_c()
        return [(None, _badge()), (WHITE, letter)]
    if tier == 'All-Star':
        return [(None, _star(32, 32, 26, 11))]
    if tier == 'Superstar':
        return [(None, _star(32, 19, 12, 5.2)), (None, _star(19, 42, 12, 5.2)), (None, _star(45, 42, 12, 5.2))]
    if tier == 'Hall of Fame':
        return [(None, [(10, 46), (8, 20), (22, 34), (32, 14), (42, 34), (56, 20), (54, 46)])]
    raise KeyError(tier)


def icon(tier):
    """{color, shapes: [{fill, d}]} for a tier (d: SVG path data in the 64-unit box), or None for an unknown tier."""
    if tier not in COLOURS:
        return None
    shapes = []
    for fill, pts in _shapes(tier):
        d = 'M' + ' L'.join(f'{_n(x)} {_n(y)}' for x, y in pts) + ' Z'
        shapes.append({'fill': fill, 'd': d})
    return {'color': COLOURS[tier], 'shapes': shapes}


def icons():
    """Every icon, keyed by tier name: the Unranked ring, then the ladder from the bottom."""
    names = [UNRANKED] + [name for name, _low, _blurb in TIERS]
    return {name: icon(name) for name in names}


def svg(tier, size=24):
    """An inline SVG of the tier's icon (empty string for an unknown tier)."""
    ic = icon(tier)
    if ic is None:
        return ''
    paths = ''.join(f'<path fill="{sh["fill"] or ic["color"]}" d="{sh["d"]}"/>' for sh in ic['shapes'])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {BOX} {BOX}" width="{int(size)}" '
            f'height="{int(size)}" fill-rule="evenodd" role="img" aria-label="{tier}">{paths}</svg>')


def pixels(tier, x, y, size):
    """The tier's polygons in pixels for a size x size square at (x, y): [(hex colour, [(px, py), ...]), ...].
    For the HUD's GDI+ fill (overtime_roster/hud/cards.py). Empty for an unknown tier."""
    if tier not in COLOURS:
        return []
    k = size / BOX
    return [(fill or COLOURS[tier], [(x + px * k, y + py * k) for px, py in pts]) for fill, pts in _shapes(tier)]


def render_js():
    """The text of rankicons.js: a global `rankIcon(tier, size)` (an SVG string) and `RANK_ICONS` (the data)."""
    data = json.dumps(icons(), indent=1, ensure_ascii=True)
    return (
        "/* Generated by overtime_core/rankicons.py (py -3.13 -m overtime_core.rankicons). Do not edit by hand. */\n"
        "(function (root) {\n"
        "  'use strict';\n"
        f"  var ICONS = {data};\n"
        "  function rankIcon(tier, size) {\n"
        "    var ic = Object.prototype.hasOwnProperty.call(ICONS, tier) ? ICONS[tier] : null;\n"
        "    if (!ic) return '';\n"
        "    var s = size || 24;\n"
        "    var paths = ic.shapes.map(function (sh) {\n"
        "      return '<path fill=\"' + (sh.fill || ic.color) + '\" d=\"' + sh.d + '\"/>';\n"
        "    }).join('');\n"
        "    return '<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 64 64\" width=\"' + s + '\" height=\"' + s +\n"
        "      '\" fill-rule=\"evenodd\" role=\"img\" aria-label=\"' + tier + '\">' + paths + '</svg>';\n"
        "  }\n"
        "  root.rankIcon = rankIcon;\n"
        "  root.RANK_ICONS = ICONS;\n"
        "})(typeof window !== 'undefined' ? window : globalThis);\n"
    )


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = (os.path.join('overtime_roster', 'web', 'js', 'rankicons.js'),
           os.path.join('overtime_server', 'http', 'web', 'rankicons.js'))


def main():
    """Write both generated files (the roster's web/js and the server board's web folder)."""
    text = render_js()
    for rel in TARGETS:
        path = os.path.join(ROOT, rel)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        print('wrote', path)


if __name__ == '__main__':
    main()
