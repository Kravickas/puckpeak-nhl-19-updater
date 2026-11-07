"""The app's web code gives React `style` objects, never strings.

htm/React refuses a string `style` (React error #62) and the whole tab stops: live 2026-11-07, app 0.60.2's Multiplayer
tab died for the first ranked player on the rank progress bar (`style=${`width:...`}`).
"""
import pathlib
import re

WEB_JS = pathlib.Path(__file__).resolve().parents[1] / 'overtime_roster' / 'web' / 'js'
STRING_STYLE = re.compile(r'style=\$\{\s*[`\'"]|style="')


def test_no_string_style_props():
    bad = ['%s:%d: %s' % (p.relative_to(WEB_JS), n, line.strip()[:100])
           for p in sorted(WEB_JS.rglob('*.js'))
           for n, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1) if STRING_STYLE.search(line)]
    assert not bad, 'string style props (use style=${{ ... }}):\n' + '\n'.join(bad)
