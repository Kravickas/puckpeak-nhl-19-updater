"""The HTML change report written next to every save or export (self-contained, opens in any browser)."""
import collections
import html
import re

CSS = """body{margin:0;background:#141217;color:#ece7e3;font:14px/1.45 'Segoe UI',system-ui,sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 20px 60px}
h1{font:800 34px/1 'Segoe UI',Arial,sans-serif;text-transform:uppercase;
letter-spacing:.5px;margin:0 0 6px}h1:after{content:'';display:block;width:84px;height:4px;background:#f05d4a;margin-top:12px}
h2{font:700 20px 'Segoe UI',Arial,sans-serif;text-transform:uppercase;
margin:30px 0 10px;color:#ff8a3d}table{border-collapse:collapse;width:100%;background:#1f1d22}
td,th{padding:6px 10px;border-bottom:1px solid #322d33;text-align:left;vertical-align:top}
th{color:#b9aea8;font-weight:600;text-transform:uppercase;font-size:12px;letter-spacing:.6px}
.k{color:#b9aea8;width:180px}.err{color:#ff7a6b}.warn{color:#e8b25a}.ok{color:#6fdc8c}
.exp{display:inline-block;background:#f26b1d;color:#141217;font-weight:700;padding:1px 8px;margin-left:8px;
font-size:12px;text-transform:uppercase}
details{margin:0 0 6px;background:#1f1d22}summary{cursor:pointer;padding:8px 10px;font-weight:700}
summary span{color:#b9aea8;font-weight:400;margin-left:8px}details table{background:#18161b}"""

FREE_AGENTS = 'Free agents'
# the roster moves update.details writes as (what, before, after), told by the end of `what`
MOVES = ((': team', 'move'), (': new player', 'new'), (': signed', 'signed'),
         (': called up so the team can dress 20', 'called'))
RETIRED = re.compile(r'^(.*): retired \((\d+)\)$')
# the order of a team's lines, and the words of its summary
KINDS = ('Joined', 'New player', 'Signed', 'Called up', 'Left', 'Released', 'Called up to', 'Retired')
COUNTS = {'Joined': 'joined', 'New player': 'new', 'Signed': 'signed', 'Called up': 'called up', 'Left': 'left',
          'Released': 'released', 'Called up to': 'went up', 'Retired': 'retired'}


def _team(where):
    return FREE_AGENTS if where == 'Free agent' else where


def by_team(changes):
    """{team: [(kind, player, from / to)]} of the update's roster moves among `changes` (what, before, after), as
    Legacy's List of changes groups them by team: a move under the team he joined and the team he left, a call-up under
    both teams, retirements under the free agents. Teams by name, the free agents last; other lines are left out."""
    out = collections.defaultdict(list)
    for what, old, new in changes:
        what, old, new = str(what), str(old), str(new)
        m = RETIRED.match(what)
        if m:
            out[FREE_AGENTS].append(('Retired', m[1], f'at {m[2]}'))
            continue
        kind = next((k for end, k in MOVES if what.endswith(end)), None)
        if kind is None:
            continue
        name = what[:what.rindex(': ')]
        if kind == 'move':
            out[_team(new)].append(('Joined', name, f'from {old}'))
            out[_team(old)].append(('Released', name, '') if new == 'Free agent' else ('Left', name, f'to {new}'))
        elif kind == 'new':
            out[_team(new)].append(('New player', name, ''))
        elif kind == 'signed':
            out[_team(new)].append(('Signed', name, 'a free agent'))
        else:
            out[_team(new)].append(('Called up', name, f'from {old}'))
            out[_team(old)].append(('Called up to', name, new))
    order = {k: n for n, k in enumerate(KINDS)}
    return {t: sorted(out[t], key=lambda r: (order[r[0]], r[1]))
            for t in sorted(out, key=lambda t: (t == FREE_AGENTS, t))}


def _teams_html(teams):
    e = html.escape
    parts = []
    for team, rows in teams.items():
        n = collections.Counter(kind for kind, _p, _w in rows)
        summary = ', '.join(f'{n[k]} {COUNTS[k]}' for k in KINDS if n[k])
        body = ''.join(f'<tr><td class="k">{e(kind)}</td><td>{e(p)}</td><td>{e(w)}</td></tr>' for kind, p, w in rows)
        parts.append(f'<details><summary>{e(team)}<span>{e(summary)}</span></summary><table>{body}</table></details>')
    return ''.join(parts)


def write(path, title, source, target, folder, crc, changes, issues, when):
    e = html.escape
    errors = [i for i in issues if i.level == 'error']
    rows = ''.join(f'<tr><td>{e(str(w))}</td><td>{e(str(o))}</td><td>{e(str(n))}</td></tr>' for w, o, n in changes)
    iss = ''.join(f'<tr><td class="{"err" if i.level == "error" else "warn"}">{e(i.level)}</td><td>{e(i.rule)}</td>'
                  f'<td>{e(i.message)}</td></tr>' for i in issues[:500])
    teams = by_team(changes)
    per_team = (f'<h2>By team ({len(teams)})</h2>{_teams_html(teams)}' if teams else '')
    kind = {'save': 'New roster save', 'folder': 'Folder to copy to another PC'}.get(
        target, 'Roster file for the Overtime server')
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(title)} - Overtime Roster report</title>
<style>{CSS}</style></head><body><main>
<h1>{e(title)}</h1>
<table><tr><td class="k">Made</td><td>{e(when.strftime('%Y-%m-%d %H:%M'))}</td></tr>
<tr><td class="k">From</td><td>{e(source)}</td></tr><tr><td class="k">Saved as</td><td>{kind}</td></tr>
<tr><td class="k">Where</td><td>{e(folder)}</td></tr><tr><td class="k">Roster CRC</td><td><code>{e(crc)}</code></td></tr>
<tr><td class="k">Verify</td><td class="{'err' if errors else 'ok'}">{len(errors)} error(s), {len(issues) - len(errors)} warning(s)</td></tr>
</table>
{per_team}
<h2>Changes ({len(changes)})</h2>
<table><tr><th>What</th><th>Before</th><th>After</th></tr>{rows or '<tr><td colspan="3">No edits: the roster as it was loaded.</td></tr>'}</table>
<h2>Verify</h2>
<table><tr><th>Level</th><th>Rule</th><th>Message</th></tr>{iss or '<tr><td colspan="3" class="ok">Every rule passed.</td></tr>'}</table>
</main></body></html>"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(doc)
    return path
