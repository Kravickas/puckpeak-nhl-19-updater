"""The cross-vendor block in the app (overtime_core/crossvendor.py, generated; xmlpatch 'crossvendor'; matchsetup).

The drift guard that regenerates the block from the local eboot lives in tests/test_crossvendor_patch.py (it needs the
re/ scripts, capstone and keystone)."""
import hashlib
import re

from overtime_core import crossvendor, xmlpatch
from overtime_roster.app import matchsetup

SERVER = ('ot.puckpeak.com', 'https://91.98.195.150/')
CAVES = (0x5AEA4B0, 0x5AEC000)          # xml addresses of the free text padding the caves sit in


def _ranges(lines):
    out = []
    for line in lines:
        if len(line) == 2:
            addr, value = line
            out.append((int(addr, 16), int(addr, 16) + len(value) // 2))
        else:
            addr, room, _template = line
            out.append((int(addr, 16), int(addr, 16) + room + 1))
    return out


def test_the_block_is_whole_and_fits_the_app():
    rows = '\n'.join(f'{a.upper()}={v}' for a, v in crossvendor.LINES)
    assert hashlib.sha256(rows.encode('ascii')).hexdigest() == crossvendor.LINES_SHA256
    assert crossvendor.TITLE == xmlpatch.CROSSVENDOR_TITLE == 'Cross-vendor exact math (rcp/rsqrt)'
    assert (crossvendor.SITES, crossvendor.HOOKS) == (262, 260)
    assert all(re.fullmatch(r'[0-9a-f]{64}', s) for s in crossvendor.EBOOT_SHA256)
    for addr, value in crossvendor.LINES:
        assert matchsetup._ADDR.match(addr) and matchsetup._HEX.match(value)       # every line <= 1024 bytes
    text = xmlpatch.build(*SERVER)
    assert sum(len(b['lines']) for b in xmlpatch.parse(text)) <= matchsetup.MAX_LINES
    assert '--' not in xmlpatch.FEATURES['crossvendor'].comment.strip()[4:-3]     # a valid XML comment


def test_hooks_jump_into_caves_and_nothing_overlaps():
    hooks = caves = 0
    for addr, value in crossvendor.LINES:
        a, b = int(addr, 16), bytes.fromhex(value)
        if CAVES[0] <= a < CAVES[1]:
            assert a + len(b) <= CAVES[1]
            caves += 1
        else:
            assert len(b) == 5 and b[0] == 0xE9                                    # jmp rel32
            target = a + 5 + int.from_bytes(b[1:], 'little', signed=True)
            assert CAVES[0] <= target < CAVES[1]
            hooks += 1
    assert hooks == crossvendor.HOOKS and caves
    mine = sorted(_ranges(crossvendor.LINES))
    assert all(x[1] <= y[0] for x, y in zip(mine, mine[1:]))
    others = [r for name, f in xmlpatch.FEATURES.items() if name != 'crossvendor' for r in _ranges(f.lines)]
    for lo, hi in mine:
        assert not any(lo < o_hi and o_lo < hi for o_lo, o_hi in others), hex(lo)


def test_default_carries_the_block_and_an_unknown_eboot_does_not():
    assert 'crossvendor' in xmlpatch.DEFAULT and xmlpatch.DEFAULT[-2:] == ('bap32', 'expansion32')
    assert xmlpatch.NO_CROSSVENDOR == tuple(f for f in xmlpatch.DEFAULT if f != 'crossvendor')
    assert xmlpatch.EARLIER[-1] == tuple(f for f in xmlpatch.DEFAULT if f != 'res720')   # the 0.81.0 candidate's file
    for sha in crossvendor.EBOOT_SHA256:
        assert xmlpatch.for_eboot(sha) == xmlpatch.for_eboot(sha.upper()) == xmlpatch.DEFAULT
    assert xmlpatch.for_eboot('0' * 64) == xmlpatch.for_eboot(None) == xmlpatch.NO_CROSSVENDOR
    assert xmlpatch.has_crossvendor(xmlpatch.build(*SERVER))
    assert not xmlpatch.has_crossvendor(xmlpatch.build(*SERVER, features=xmlpatch.NO_CROSSVENDOR))
    addr, value = crossvendor.LINES[-1]
    bent = xmlpatch.build(*SERVER).replace(f'Value="{value}"', f'Value="{value[:-2]}90"')
    assert bent != xmlpatch.build(*SERVER) and not xmlpatch.has_crossvendor(bent)


def test_repoint_brings_an_080_file_up_and_keeps_the_gate():
    for newline in ('\r\n', '\n'):
        for earlier in (xmlpatch.EARLIER[2], xmlpatch.EARLIER[3]):     # 0.80.0's file, the 0.81.0 candidate's
            old = xmlpatch.build(*SERVER, features=earlier, newline=newline)
            new = xmlpatch.repoint(old, *SERVER)
            assert new == xmlpatch.build(*SERVER, newline=newline) and xmlpatch.has_crossvendor(new)
        gated = xmlpatch.repoint(new, *SERVER, features=xmlpatch.NO_CROSSVENDOR)          # an eboot it does not fit
        assert gated == xmlpatch.build(*SERVER, features=xmlpatch.NO_CROSSVENDOR, newline=newline)
        assert not xmlpatch.has_crossvendor(gated) and xmlpatch.repoint(gated, *SERVER) == new
        assert xmlpatch.repoint(new, *SERVER) == new
    on = xmlpatch.with_resolution(xmlpatch.expansion32_off(xmlpatch.build(*SERVER)), 1440)
    assert xmlpatch.repoint(on, '192.168.1.15') == xmlpatch.with_resolution(
        xmlpatch.expansion32_off(xmlpatch.build('192.168.1.15')), 1440)


def test_the_recipe_leaves_the_block_out_and_each_match_patch_has_it():
    host = xmlpatch.build(*SERVER)
    r = matchsetup.recipe(host)
    assert all(len(t) <= matchsetup.MAX_TEXT for t in r['xml_blocks'])
    assert len(r['xml_blocks'][0]) < 16 * 1024                                     # the block alone is ~30 KB
    assert crossvendor.TITLE not in r['xml_blocks'][0]
    assert [b['name'] for b in matchsetup.shared_blocks(host)] == [crossvendor.TITLE]
    guest = xmlpatch.with_resolution(xmlpatch.bap32_off(xmlpatch.build('91.98.195.150')), 1440)  # 1440p, by IP
    played = matchsetup.match_xml(r, guest)
    assert xmlpatch.has_crossvendor(played)
    assert xmlpatch.netplay_fingerprint(played) == xmlpatch.netplay_fingerprint(host)
    # a guest without the block (0.80 file, unknown eboot) gets another fingerprint, so the lobby keeps them apart
    bare = xmlpatch.build(*SERVER, features=xmlpatch.NO_CROSSVENDOR)
    assert not xmlpatch.has_crossvendor(matchsetup.match_xml(r, bare))
    assert xmlpatch.netplay_fingerprint(matchsetup.match_xml(r, bare)) != xmlpatch.netplay_fingerprint(host)


def test_a_recipe_never_brings_its_own_block():
    host = xmlpatch.build(*SERVER)
    forged = matchsetup.render([{'name': crossvendor.TITLE, 'lines': [['0x84DA08', '9090909090']]}], newline='\n')
    r = matchsetup.recipe(host)
    r['xml_blocks'].append(forged)
    played = matchsetup.match_xml(r, host)
    assert xmlpatch.has_crossvendor(played) and 'CCCCCCCCCC' not in played
