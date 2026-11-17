"""Rank icons (v0.90.0, M5; redrawn 0.97.0): ten original hockey emblems, one per rank tier, in a 64-unit box.

The shapes are plain point lists so the same data serves three places: the web pages (generated JS below), the server
board, and the HUD's GDI+ polygon fill (overtime_roster/hud/cards.py). GDI+ there fills flat colours only, so the
depth comes from layers of flat polygons painted in order: a dark rim, bevel facets lit from the top left, the face, a
sheen across its upper part, then the crest (sticks, chevrons, a captain's letter, stars, a crown). A polygon with a
hole is bridged into one contour and filled even-odd (the captain's letters).

The ladder escalates: a puck (Unranked), a bronze shield with crossed sticks (Minor League), one to three chevrons
(Rookie, Pro, Top 6), the jersey's letter patches (Alternate Captain, Captain), a faceted star (All-Star), three stars
(Superstar), a jewelled crown (Hall of Fame).

Regenerate the two JS files after a change here:  py -3.13 -m overtime_core.rankicons
tests/test_rankicons.py fails when they are out of date. Notes: docs/notes/rank-icons.md.
"""
import json
import math
import os

from .rating import TIERS, UNRANKED

BOX = 64
WHITE = '#ffffff'
LETTER = '#f7f9fc'
# tier -> colour (the tier's own; every facet is a shade of it)
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
RUBY = '#d8243a'
LIGHT = (-0.42, -0.91)          # where the light comes from (top left), a unit vector
RIM = -0.82                     # the outline's shade
SHEEN = 0.16                    # the face's upper part


# --- colour -------------------------------------------------------------------------------------------------------
def _rgb(hexcolor):
    h = hexcolor.lstrip('#')
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def shade(hexcolor, t):
    """The colour towards white (t > 0) or black (t < 0); t in -1..1, 1 is 60 % white, -1 is 70 % black."""
    r = _rgb(hexcolor)
    if t >= 0:
        k = min(1.0, t) * 0.6
        out = [c + (255 - c) * k for c in r]
    else:
        k = min(1.0, -t) * 0.7
        out = [c * (1 - k) for c in r]
    return '#' + ''.join(f'{max(0, min(255, round(c))):02x}' for c in out)


def _fill(spec, colour):
    """A shape's fill: None (the tier colour), a number (a shade of the tier colour), (hex, t) (a shade of hex), or hex."""
    if spec is None:
        return colour
    if isinstance(spec, (int, float)):
        return shade(colour, spec)
    if isinstance(spec, tuple):
        return shade(spec[0], spec[1])
    return spec


# --- geometry -----------------------------------------------------------------------------------------------------
def _n(v):
    """A coordinate as the path text needs it: at most two decimals, no trailing zeros."""
    s = f'{v:.2f}'.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def _area(pts):
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])) / 2


def _normals(pts):
    """The outward unit normal of each edge (pts[i] -> pts[i + 1])."""
    sign = 1 if _area(pts) > 0 else -1
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy) or 1.0
        out.append((sign * dy / ln, -sign * dx / ln))
    return out


def _offset(pts, d, limit=2.6):
    """The outline moved by d (outward > 0, inward < 0), mitred at the corners (a sharp corner's miter is capped)."""
    ns = _normals(pts)
    out = []
    for i, (x, y) in enumerate(pts):
        n1, n2 = ns[i - 1], ns[i]
        mx, my = n1[0] + n2[0], n1[1] + n2[1]
        k = 1 + n1[0] * n2[0] + n1[1] * n2[1]
        if k < 1e-6:
            mx, my, k = n2[0], n2[1], 1.0
        f = min(1 / k, limit / max(1e-6, math.hypot(mx, my)))
        out.append((x + d * mx * f, y + d * my * f))
    return out


def _lit(n):
    return n[0] * LIGHT[0] + n[1] * LIGHT[1]


def _move(pts, dx, dy):
    return [(x + dx, y + dy) for x, y in pts]


def _circle(cx, cy, r, n=28, start=-90):
    return [(cx + r * math.cos(math.radians(start + 360 * k / n)), cy + r * math.sin(math.radians(start + 360 * k / n)))
            for k in range(n)]


def _star(cx, cy, big, small, points=5):
    pts = []
    for k in range(points * 2):
        a = math.radians(-90 + 180 / points * k)
        r = big if k % 2 == 0 else small
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _octagon(r=28.5):
    return [(32 + r * math.cos(math.radians(22.5 + 45 * k)), 32 + r * math.sin(math.radians(22.5 + 45 * k)))
            for k in range(8)]


def _clip(pts, keep):
    """The part of the polygon where keep(x, y) >= 0 (one straight cut; keep is linear)."""
    out = []
    for a, b in zip(pts, pts[1:] + pts[:1]):
        fa, fb = keep(*a), keep(*b)
        if fa >= 0:
            out.append(a)
        if (fa >= 0) != (fb >= 0):
            t = fa / (fa - fb)
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _bridge(outer, hole):
    """One contour of an outline and a hole (filled even-odd, the hole stays open)."""
    return outer + [outer[0]] + hole + [hole[0]]


# --- the layers -----------------------------------------------------------------------------------------------------
def _emblem(pts, depth=3.0, rim=1.8, face=None, sheen=SHEEN, strength=0.9, base=None):
    """A bevelled plate: the rim, one lit or shaded facet per edge, the face and its sheen.
    `base` (hex) shades another colour than the tier's (a crown's gems)."""
    def f(t):
        return (base, t) if base else t
    out = []
    if rim:
        out.append((f(RIM), _offset(pts, rim)))
    inner = _offset(pts, -depth)
    for i, n in enumerate(_normals(pts)):
        j = (i + 1) % len(pts)
        out.append((f(strength * _lit(n)), [pts[i], pts[j], inner[j], inner[i]]))
    out.append((f(face) if face is not None else (base or None), inner))
    if sheen:
        xs, ys = [p[0] for p in inner], [p[1] for p in inner]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        top = _clip(inner, lambda x, y: (cy - 0.45 * (x - cx)) - y)
        if len(top) >= 3:
            out.append((f((face or 0) + sheen), top))
    return out


def _facets(pts, centre, rim=2.0, strength=0.85):
    """A faceted crest (a star): its rim, then a triangle from the centre to each edge, lit by the edge's normal."""
    out = [(RIM, _offset(pts, rim, limit=1.6))] if rim else []
    for i, n in enumerate(_normals(pts)):
        out.append((strength * _lit(n), [centre, pts[i], pts[(i + 1) % len(pts)]]))
    return out


def _letter(contour, shadow):
    """A white letter with a drop shadow under it (bottom right)."""
    return [(shadow, _move(contour, 1.4, 1.7)), (LETTER, contour)]


# --- the crests -----------------------------------------------------------------------------------------------------
def _stick(x0, y0, x1, y1, w, blade):
    """A hockey stick from the knob (x0, y0) to the heel (x1, y1), w wide, the blade `blade` long along x."""
    dx, dy = x1 - x0, y1 - y0
    ln = math.hypot(dx, dy)
    nx, ny = -dy / ln * w / 2, dx / ln * w / 2
    toe = x1 + blade
    return [(x0 + nx, y0 + ny), (x0 - nx, y0 - ny), (x1 - nx, y1 - ny), (toe, y1 - ny + 0.6),
            (toe + 0.8, y1 + w * 0.9), (x1 + nx - w * 0.3, y1 + w * 0.9)]


def _mirror(pts):
    return [(BOX - x, y) for x, y in reversed(pts)]


SHIELD = [(13, 8), (51, 8), (53, 30), (46, 45), (32, 56), (18, 45), (11, 30)]
CHEVRON_H, CHEVRON_T, CHEVRON_GAP = 17, 10, 14     # arm height, thickness, step between stacked chevrons
LETTER_A = _bridge([(18.5, 47), (27.6, 16.5), (36.4, 16.5), (45.5, 47), (37.6, 47), (35.6, 40.3), (28.4, 40.3), (26.4, 47)],
                   [(30.1, 34), (33.9, 34), (32, 27)])
CROWN = [(10, 45), (7, 19), (20.5, 31), (32, 12), (43.5, 31), (57, 19), (54, 45)]


def _letter_c():
    outer = [(32 + 15.5 * math.cos(math.radians(a)), 32 + 15.5 * math.sin(math.radians(a))) for a in range(42, 319, 12)]
    inner = [(32 + 8 * math.cos(math.radians(a)), 32 + 8 * math.sin(math.radians(a))) for a in range(318, 41, -12)]
    return outer + inner


def _chevron(top):
    h, t = CHEVRON_H, CHEVRON_T
    return [(8, top), (32, top + h), (56, top), (56, top + t), (32, top + h + t), (8, top + t)]


def _ellipse(cx, cy, rx, ry, a0=0, a1=360, n=36):
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * k / n)), cy + ry * math.sin(math.radians(a0 + (a1 - a0) * k / n)))
            for k in range(n + 1)]


def _puck():
    """A puck seen from above at an angle: the top face, the knurled side lit from the left."""
    cx, top, low, rx, ry = 32, 25, 38.5, 25, 10
    upper, lower = _ellipse(cx, top, rx, ry, 0, 180, 24), _ellipse(cx, low, rx, ry, 0, 180, 24)
    outline = _ellipse(cx, top, rx, ry, 180, 360, 24) + lower
    out = [(RIM, _offset(outline, 2.2))]
    for k in range(24):                                 # the side, strip by strip
        t = -0.62 - 0.35 * math.cos(math.radians(7.5 * (k + 0.5))) + (0.07 if k % 2 else 0)
        out.append((t, [upper[k], upper[k + 1], lower[k + 1], lower[k]]))
    face = _ellipse(cx, top, rx, ry, 0, 360, 48)[:-1]
    out.append((0.05, face))
    out.append((0.24, _clip(face, lambda x, y: (top - 0.25 * (x - cx)) - y)))
    out.append((-0.22, _bridge(_ellipse(cx, top, 15, 6, 0, 360, 36)[:-1], _ellipse(cx, top, 12.6, 4.9, 0, 360, 36)[:-1])))
    return out


def _minor_league():
    out = _emblem(SHIELD, depth=3.2, rim=2.0)
    left = _stick(19.5, 14, 37.5, 41.5, 3.8, 9)
    right = _mirror(left)
    for stick in (left, right):
        out.append((-0.85, _move(stick, 1.1, 1.4)))
    out += [(0.58, left), (0.66, right)]
    return out


def _chevrons(count):
    total = (count - 1) * CHEVRON_GAP + CHEVRON_H + CHEVRON_T
    top = (BOX - total) / 2
    shapes = [_chevron(top + k * CHEVRON_GAP) for k in range(count)]
    out = [(RIM, _offset(pts, 1.8)) for pts in shapes]
    for pts in shapes:
        out += _emblem(pts, depth=2.6, rim=0, sheen=0.14)
    return out


def _patch(letter):
    out = _emblem(_octagon(), depth=3.4, rim=2.0)
    out.append((0.42, _bridge(_offset(_octagon(), -5.4), _offset(_octagon(), -6.5))))     # a trim line inside the bevel
    return out + _letter(letter, -0.8)


def _all_star():
    return _facets(_star(32, 33.5, 27.5, 11.5), (32, 33.5), rim=2.2)


def _superstar():
    out = []
    for cx, cy, big, small in ((16.5, 42.5, 13, 5.6), (47.5, 42.5, 13, 5.6), (32, 19.5, 16, 6.9)):
        out += _facets(_star(cx, cy, big, small), (cx, cy), rim=1.8)
    return out


def _gem(cx, cy, r):
    pts = [(cx, cy - r), (cx + r * 0.8, cy), (cx, cy + r), (cx - r * 0.8, cy)]
    return [((RUBY, RIM), _offset(pts, 1.1))] + [((RUBY, 0.8 * _lit(n)), [(cx, cy), pts[i], pts[(i + 1) % 4]])
                                                 for i, n in enumerate(_normals(pts))]


def _hall_of_fame():
    out = []
    for cx, cy in ((7.6, 16.6), (32, 9.6), (56.4, 16.6)):          # the pearls on the three tall points, under the rim
        out.append((RIM, _circle(cx, cy, 4.9, 16)))
    out += _emblem(CROWN, depth=3.0, rim=2.0)
    for cx, cy in ((7.6, 16.6), (32, 9.6), (56.4, 16.6)):
        out += [(0.1, _circle(cx, cy, 3.4, 16)), (0.7, _circle(cx - 1, cy - 1, 1.4, 10))]
    out += _emblem([(9, 43), (55, 43), (55, 55), (9, 55)], depth=2.4, rim=1.8, face=-0.12)
    out += _gem(32, 49, 4.4) + _gem(19.5, 49, 3) + _gem(44.5, 49, 3)
    return out


def _shapes(tier):
    """The polygons of one tier, painted in order: [(fill spec, [(x, y), ...]), ...] (see _fill for the specs)."""
    if tier == UNRANKED:
        return _puck()
    if tier == 'Minor League':
        return _minor_league()
    if tier in ('Rookie', 'Pro', 'Top 6'):
        return _chevrons({'Rookie': 1, 'Pro': 2, 'Top 6': 3}[tier])
    if tier == 'Alternate Captain':
        return _patch(LETTER_A)
    if tier == 'Captain':
        return _patch(_letter_c())
    if tier == 'All-Star':
        return _all_star()
    if tier == 'Superstar':
        return _superstar()
    if tier == 'Hall of Fame':
        return _hall_of_fame()
    raise KeyError(tier)


def icon(tier):
    """{color, shapes: [{fill, d}]} for a tier (d: SVG path data in the 64-unit box), or None for an unknown tier.
    fill is a hex colour, or None for the tier's own colour."""
    if tier not in COLOURS:
        return None
    colour = COLOURS[tier]
    shapes = []
    for spec, pts in _shapes(tier):
        d = 'M' + ' L'.join(f'{_n(x)} {_n(y)}' for x, y in pts) + ' Z'
        fill = _fill(spec, colour)
        shapes.append({'fill': None if fill == colour else fill, 'd': d})
    return {'color': colour, 'shapes': shapes}


def icons():
    """Every icon, keyed by tier name: the Unranked puck, then the ladder from the bottom."""
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
    """The tier's polygons in pixels for a size x size square at (x, y), in paint order: [(hex colour, [(px, py), ...]),
    ...]. For the HUD's GDI+ fill (overtime_roster/hud/cards.py). Empty for an unknown tier."""
    if tier not in COLOURS:
        return []
    k, colour = size / BOX, COLOURS[tier]
    return [(_fill(spec, colour), [(x + px * k, y + py * k) for px, py in pts]) for spec, pts in _shapes(tier)]


def render_js():
    """The text of rankicons.js: a global `rankIcon(tier, size)` (an SVG string) and `RANK_ICONS` (the data)."""
    data = json.dumps(icons(), separators=(',', ':'), ensure_ascii=True)
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
