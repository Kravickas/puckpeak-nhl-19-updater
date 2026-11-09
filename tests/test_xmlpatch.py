import os

import pytest

from overtime_core import xmlpatch

PATCHES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'patches')


def _read(name):
    with open(os.path.join(PATCHES, name), 'rb') as f:
        return f.read()


def test_reproduces_the_lan_patch():
    assert xmlpatch.build('192.168.1.15').encode('utf-8') == _read('overtime_lan.xml')


def test_reproduces_the_dev_patch():
    assert xmlpatch.build('localhost', newline='\n').encode('utf-8') == _read('overtime_dev.xml')


def test_targets_and_blocks():
    text = xmlpatch.build('ot.puckpeak.com', 'https://91.98.195.150/')
    # accounts (24, the login) names the host, so Caddy routes it by name; the IP only where the name doesn't fit
    assert xmlpatch.targets(text) == {'redirector': 'ot.puckpeak.com', 'nucleus': [
        'https://ot.puckpeak.com/', 'https://91.98.195.150/', 'https://91.98.195.150/']}
    blocks = xmlpatch.parse(text)
    assert [b['name'] for b in blocks] == [
        'ProtoHttp: accept EAGAIN while waiting for the status code', 'Redirector host: ot.puckpeak.com',
        'QoS coordinator: skip TLS cert validation', 'Nucleus hosts: ot.puckpeak.com, 91.98.195.150',
        '60 FPS replays (Kravickas)', 'Resolution 2560x1440 (Kravickas)', 'Resolution 1280x720 (Kravickas)',
        xmlpatch.THREES_REWARDS_TITLE, 'Cross-vendor exact math (rcp/rsqrt)',
        'R1: cap check on the Franchise per-team list append', 'BAP32: Seattle in Be a Pro', 'E32: 32 teams in every mode']
    off = (xmlpatch.RES1440_TITLE, xmlpatch.RES720_TITLE)
    assert all(b['enabled'] == (b['name'] not in off) and b['app_ver'] == '01.60' for b in blocks)


def test_feature_subset_keeps_order():
    text = xmlpatch.build('localhost', features=('eagain', 'qos_ncrt'))
    assert [b['lines'][0][0] for b in xmlpatch.parse(text)] == ['0x3C90813', '0x3C5AA16']
    assert xmlpatch.targets(text) == {'redirector': None, 'nucleus': []}


@pytest.mark.parametrize('host, nucleus_url', [
    ('ot.puckpeak.com', None),                       # https://ot.puckpeak.com/ = 24, gateway holds 23
    ('a-very-long-hostname-for-redirector.example', 'https://1.2.3.4/'),  # redirector holds 29
    ('bad host', None),
    ('localhost"', None),
    ('localhost', 'ftp://localhost/'),
    ('localhost', 'https://localhost'),
    ('my--pc.lan', None),                            # '--' would end the XML comment that names the host
    ('localhost', 'https://a--b/'),
])
def test_refused(host, nucleus_url):
    with pytest.raises(xmlpatch.PatchError):
        xmlpatch.build(host, nucleus_url)


def test_nucleus_url_only_where_the_host_does_not_fit():
    text = xmlpatch.build('192.168.1.15', 'https://91.98.195.150/')  # https://192.168.1.15/ = 21, fits every slot
    assert xmlpatch.targets(text)['nucleus'] == ['https://192.168.1.15/'] * 3


def test_slot_room_limits():
    xmlpatch.build('91.98.195.150')  # https://91.98.195.150/ = 22, fits every slot
    xmlpatch.build('a' * 29, 'https://1.2.3.4/')
    with pytest.raises(xmlpatch.PatchError):
        xmlpatch.build('a' * 30, 'https://1.2.3.4/')


def test_unknown_feature_refused():
    with pytest.raises(xmlpatch.PatchError):
        xmlpatch.build('localhost', features=('eagain', 'warp_drive'))


def test_parse_rejects_garbage():
    with pytest.raises(xmlpatch.PatchError):
        xmlpatch.parse('not xml at all')


def test_expansion32_is_one_line_and_default():
    assert xmlpatch.DEFAULT[-1] == 'expansion32'
    text = xmlpatch.build('localhost', newline='\n')
    blocks = xmlpatch.parse(text)
    assert blocks[-1] == {'name': 'E32: 32 teams in every mode', 'app_ver': '01.60', 'enabled': True,
                          'lines': [('0x6F7963', 'C6051E2EC50501')]}
    # without the switch: the same file minus its last block, hosts untouched
    no32 = xmlpatch.build('localhost', features=xmlpatch.DEFAULT[:-1], newline='\n')
    assert xmlpatch.targets(text) == xmlpatch.targets(no32)
    assert text.startswith(no32[:-len(xmlpatch.FOOTER)]) and text.endswith(xmlpatch.FOOTER)


def test_expansion32_off_writes_the_stock_bytes():
    """For a roster whose Seattle is empty or inactive (New Season crashes with the switch on, ws8 run7a)."""
    on = xmlpatch.build('192.168.1.15')
    off = xmlpatch.expansion32_off(on)
    assert xmlpatch.expansion32(on) and not xmlpatch.expansion32(off)
    assert xmlpatch.parse(off)[-1]['lines'] == [('0x6F7963', 'C6051E2EC50500')]
    # the Be a Pro block goes off with the switch (its league would stay at 31)
    assert xmlpatch.bap32(on) and not xmlpatch.bap32(off)
    assert xmlpatch.parse(off)[-2] == {**xmlpatch.parse(on)[-2], 'enabled': False}
    assert xmlpatch.parse(off)[:-2] == xmlpatch.parse(on)[:-2] and xmlpatch.targets(off) == xmlpatch.targets(on)
    assert xmlpatch.expansion32_off(off) == off
    no32 = xmlpatch.build('localhost', features=xmlpatch.DEFAULT[:-2], newline='\n')
    assert not xmlpatch.expansion32(no32) and xmlpatch.expansion32_off(no32) == no32
    bap_only = xmlpatch.build('localhost', features=xmlpatch.DEFAULT[:-1], newline='\n')
    assert not xmlpatch.bap32(xmlpatch.expansion32_off(bap_only))
    disabled = on.replace('Name="E32: 32 teams in every mode" AppVer="01.60" AppElf="eboot.bin" isEnabled="true"',
                          'Name="E32: 32 teams in every mode" AppVer="01.60" AppElf="eboot.bin" isEnabled="false"')
    assert disabled != on and not xmlpatch.expansion32(disabled)
    reordered = on.replace('Address="0x6F7963" Value="C6051E2EC50501"', 'Value="C6051E2EC50501" Address="0x6F7963"')
    with pytest.raises(xmlpatch.PatchError):
        xmlpatch.expansion32_off(reordered)


@pytest.mark.game
def test_expansion32_patches_the_stock_default_store(game_dir):
    """The line rewrites the static initialiser's `mov byte [rip+disp32], 0` of the tweak's default byte (object
    0x5f4a750 + 0x38), found once in the eboot; only the immediate changes."""
    import struct
    path = os.path.join(game_dir, 'eboot.bin-decrypted')
    if not os.path.exists(path):
        pytest.skip('no decrypted eboot')
    with open(path, 'rb') as f:
        elf = f.read()
    addr, value = xmlpatch.FEATURES['expansion32'].lines[0]
    vaddr, new = int(addr, 16) - 0x400000, bytes.fromhex(value)
    phoff, phnum = struct.unpack_from('<Q', elf, 0x20)[0], struct.unpack_from('<H', elf, 0x38)[0]
    for k in range(phnum):
        _t, _f, off, va, _pa, size, _ms, _al = struct.unpack_from('<IIQQQQQQ', elf, phoff + k * 56)
        if size and va <= vaddr < va + size:
            stock = elf[off + vaddr - va:off + vaddr - va + len(new)]
            break
    else:
        pytest.fail('address not in a loaded segment')
    assert stock == new[:-1] + b'\0' and elf.count(stock) == 1
    disp = struct.unpack_from('<i', stock, 2)[0]
    assert vaddr + len(stock) + disp == 0x5f4a750 + 0x38


def _jmp_target(addr, code, at):
    """Target of the E9 rel32 at byte `at` of `code` placed at vaddr `addr`."""
    import struct
    assert code[at] == 0xE9
    return addr + at + 5 + struct.unpack_from('<i', code, at + 1)[0]


def test_ledger_cap_is_default_and_wired():
    """In DEFAULT since R1's runs c1 / e1 (expansion career to the season-2 preseason with no crash), before the
    Be a Pro block and the 32-team switch, which stay last."""
    assert xmlpatch.DEFAULT[-3:] == ('ledger_cap', 'bap32', 'expansion32')
    text = xmlpatch.build('localhost', newline='\n')
    block = xmlpatch.parse(text)[-3]
    assert block['enabled'] and block['name'] == 'R1: cap check on the Franchise per-team list append'
    assert block['lines'] == xmlpatch.FEATURES['ledger_cap'].lines and len(block['lines']) == 2 + 2 * len(RESIDUAL)
    (hook_a, hook_v), (cave_a, cave_v) = block['lines'][:2]
    hook, cave = bytes.fromhex(hook_v), bytes.fromhex(cave_v)
    hook_at, cave_at = int(hook_a, 16) - 0x400000, int(cave_a, 16) - 0x400000
    # hook: jmp cave, nops up to the next original instruction (0x423ce7d)
    assert _jmp_target(hook_at, hook, 0) == cave_at and hook[5:] == b'\x90' * 7 and hook_at + len(hook) == 0x423ce7d
    # cave: mov rdi,[rdx+rax+0x10]; cmp rsi,rdi; jae full; the 3 original instructions; jmp back; full: jmp cleanup
    assert cave[:10] == bytes.fromhex('488B7C02104839FE7311')
    assert cave[10:22] == bytes.fromhex('488D440208488D7E38488938')
    assert _jmp_target(cave_at, cave, 22) == 0x423ce7d
    assert 10 + cave[9] == 27 and _jmp_target(cave_at, cave, 27) == 0x423b41b and len(cave) == 32


# The same ledger's four other appends (R1 residual sites): flat address of the not-found block, its stock bytes (the
# hook overwrites exactly them), the function's found continuation (where a full list takes its last entry)
RESIDUAL = ((0x42094b1, '488D440808488D5338488910', 0x42094ed),
            (0x421146f, '488D440808488D5738488910', 0x42114b3),
            (0x422c2af, '488D440808488D5638C5F857C0488910', 0x422c2f2),
            (0x422487f, '488D440808498D542438488910', 0x42248c3))


def _sites():
    lines = xmlpatch.FEATURES['ledger_cap'].lines
    return [(int(h, 16) - 0x400000, bytes.fromhex(hv), int(c, 16) - 0x400000, bytes.fromhex(cv))
            for (h, hv), (c, cv) in zip(lines[0::2], lines[1::2])]


def test_ledger_cap_residual_sites_merge_into_the_last_entry():
    """Each hook jumps to its cave over exactly the stock block; the cave: mov rdx,[rax+rcx+0x10]; cmp end,rdx; jae
    full; the stock block; jmp back; full: the end pointer one entry back (lea r,[r-0x38]); jmp found."""
    sites = _sites()[1:]
    assert [h for h, *_ in sites] == [r[0] for r in RESIDUAL]
    for (hook_at, hook, cave_at, cave), (_a, stock, found) in zip(sites, RESIDUAL):
        stock = bytes.fromhex(stock)
        n = len(stock)
        assert len(hook) == n and _jmp_target(hook_at, hook, 0) == cave_at and hook[5:] == b'\x90' * (n - 5)
        assert cave[:5] == bytes.fromhex('488B540810') and cave[8] == 0x73 and cave[10:10 + n] == stock
        assert _jmp_target(cave_at, cave, 10 + n) == hook_at + n and 10 + cave[9] == 15 + n
        assert cave[15 + n:-5] in (bytes.fromhex(x) for x in ('488D5BC8', '488D7FC8', '488D76C8', '4D8D6424C8'))
        assert _jmp_target(cave_at, cave, len(cave) - 5) == found
    caves = sorted((c, c + len(cv)) for _h, _hv, c, cv in _sites())
    assert all(end <= nxt for (_s, end), (nxt, _e) in zip(caves, caves[1:])) and caves[-1][1] <= 0x56eb100


@pytest.mark.game
def test_ledger_cap_matches_the_stock_eboot(game_dir):
    """The hook overwrites exactly the append's 3 instructions; the cave sits past the r-x segment's end but inside its
    last aligned page (mapped with it, zero-filled; the f1 run executed it)."""
    import struct
    path = os.path.join(game_dir, 'eboot.bin-decrypted')
    if not os.path.exists(path):
        pytest.skip('no decrypted eboot')
    with open(path, 'rb') as f:
        elf = f.read()
    phoff, phnum = struct.unpack_from('<Q', elf, 0x20)[0], struct.unpack_from('<H', elf, 0x38)[0]
    text = [struct.unpack_from('<IIQQQQQQ', elf, phoff + k * 56) for k in range(phnum)]
    text = [h for h in text if h[0] == 1 and h[1] & 1]  # PT_LOAD, PF_X
    assert len(text) == 1
    _t, _fl, off, va, _pa, filesz, memsz, align = text[0]
    page_end = (va + memsz + align - 1) // align * align
    assert filesz == memsz
    stocks = ['488D440208488D7E38488938'] + [s for _a, s, _f in RESIDUAL]
    for (hook_at, hook, cave_at, cave), stock in zip(_sites(), stocks):
        assert elf[off + hook_at - va:off + hook_at - va + len(hook)] == bytes.fromhex(stock)
        assert va + memsz <= cave_at and cave_at + len(cave) <= page_end


def _threes_rewards():
    (hook_a, hook_v), (cave_a, cave_v) = xmlpatch.FEATURES['threes_rewards'].lines
    return int(hook_a, 16) - 0x400000, bytes.fromhex(hook_v), int(cave_a, 16) - 0x400000, bytes.fromhex(cave_v)


def test_threes_rewards_is_default_and_wired():
    """0x1406990's equal_range: the hook replaces `cmovnz r8,rcx; mov rax,[r8+8]` (8 bytes) with jmp cave + 3 nops; the
    cave: je notfound (ZF of cmp rcx,rdx at 0x1406fb3 still live); mov r8,rcx; mov rax,[r8+8]; jmp 0x1406fc5;
    notfound: jmp 0x1406fd3 (the cmovz there writes 0xffff). Past bap32's caves, local only."""
    assert xmlpatch.DEFAULT.index('threes_rewards') < xmlpatch.DEFAULT.index('ledger_cap')
    block = next(b for b in xmlpatch.parse(xmlpatch.build('localhost', newline='\n'))
                 if b['name'] == xmlpatch.THREES_REWARDS_TITLE)
    assert block['enabled'] and block['lines'] == xmlpatch.FEATURES['threes_rewards'].lines
    hook_at, hook, cave_at, cave = _threes_rewards()
    assert hook_at == 0x1406fbd and _jmp_target(hook_at, hook, 0) == cave_at and hook[5:] == b'\x90' * 3
    assert cave[:2] == bytes.fromhex('740C') and cave[2:9] == bytes.fromhex('4989C8498B4008')
    assert _jmp_target(cave_at, cave, 9) == 0x1406fc5 and 2 + cave[1] == 14
    assert _jmp_target(cave_at, cave, 14) == 0x1406fd3 and len(cave) == 19
    assert cave_at >= max(a + len(v) for a, v in _bap32().items())
    assert xmlpatch.THREES_REWARDS_TITLE in xmlpatch.LOCAL_ONLY_TITLES


@pytest.mark.game
def test_threes_rewards_matches_the_stock_eboot(game_dir):
    """The hook overwrites exactly the stock cmovnz / mov; the cave is zero-filled, inside the r-x segment's last page."""
    import struct
    path = os.path.join(game_dir, 'eboot.bin-decrypted')
    if not os.path.exists(path):
        pytest.skip('no decrypted eboot')
    with open(path, 'rb') as f:
        elf = f.read()
    phoff, phnum = struct.unpack_from('<Q', elf, 0x20)[0], struct.unpack_from('<H', elf, 0x38)[0]
    text = [struct.unpack_from('<IIQQQQQQ', elf, phoff + k * 56) for k in range(phnum)]
    _t, _fl, off, va, _pa, _filesz, memsz, align = next(h for h in text if h[0] == 1 and h[1] & 1)
    hook_at, hook, cave_at, cave = _threes_rewards()
    assert elf[off + hook_at - va:off + hook_at - va + len(hook)] == bytes.fromhex('4C0F45C1498B4008')
    page_end = (va + memsz + align - 1) // align * align
    assert va + memsz <= cave_at and cave_at + len(cave) <= page_end


def _bap32():
    return {int(a, 16) - 0x400000: bytes.fromhex(v) for a, v in xmlpatch.FEATURES['bap32'].lines}


def _rel(addr, code, end):
    """Target of the rel32 that ends at byte `end` of `code` placed at vaddr `addr` (end = the instruction's end)."""
    import struct
    return addr + end + struct.unpack_from('<i', code, end - 4)[0]


def test_bap32_is_default_and_wired():
    """Run c2 (2026-10-28, Be a Pro career on Seattle): b8's Choose Team / builder lines and the init32 cave that also
    builds the AHL with 32 (docs/notes/nhl19-32teams-re.md). Hooks jump into caves past the ledger caps' ones."""
    assert xmlpatch.DEFAULT[-2:] == ('bap32', 'expansion32')
    block = xmlpatch.parse(xmlpatch.build('localhost', newline='\n'))[-2]
    assert block['enabled'] and block['name'] == xmlpatch.BAP32_TITLE and xmlpatch.bap32(xmlpatch.build('localhost'))
    p = _bap32()
    # builder 0x1008640: the Be a Pro test (je 0x100ab4f) and loop A's two exits go to caves A / B / C
    assert p[0x100a920][0] == 0xE9 and _rel(0x100a920, p[0x100a920], 5) == 0x56eb100 and p[0x100a920][5:] == b'\x90'
    assert _rel(0x100ab78, p[0x100ab78], 5) == 0x56eb160 and _rel(0x100ac27, p[0x100ac27], 5) == 0x56eb180
    a, b, c = p[0x56eb100], p[0x56eb160], p[0x56eb180]
    assert a[:2] == b'\x0f\x84' and _rel(0x56eb100, a, 6) == 0x100ab4f  # not Be a Pro: the stock target
    assert a[0x16:0x1c] == bytes.fromhex('483D00030000')  # a 32-entry list (0x18 bytes each) ...
    assert _rel(0x56eb100, a, 0x22) == 0x100a926 and _rel(0x56eb100, a, 0x27) == 0x100ab60  # ... takes loop A first
    assert _rel(0x56eb160, b, 6) == 0x100ab7e and _rel(0x56eb160, b, 0x13) == 0x100a926 and _rel(0x56eb160, b, 0x18) == 0x100b48d
    assert _rel(0x56eb180, c, 0xd) == 0x100a926 and _rel(0x56eb180, c, 0x12) == 0x100b494
    # init32: call over xor esi,esi / xor edx,edx / mov rdi,r12; Be a Pro + E32 live -> 32 for NHL and AHL
    d = p[0x56eb1a0]
    assert p[0x1009b0d][0] == 0xE8 and _rel(0x1009b0d, p[0x1009b0d], 5) == 0x56eb1a0 and p[0x1009b0d][5:] == b'\x90\x90'
    assert d[:2] == b'\x31\xf6' and d[2:9] == bytes.fromhex('80BD00F8FFFF00') and _rel(0x56eb1a0, d, 0x12) == 0x5f4a790
    assert d[0x17:0x1b] == bytes.fromhex('80782900')
    assert bytes.fromhex('41C784249402000020000000') in d and bytes.fromhex('41C78424EC03000020000000') in d
    assert d[-6:] == bytes.fromhex('31D24C89E7C3')
    # Choose Team: the marker string and the 399 kept by the Exhibition limit block
    assert _rel(0x1482899, p[0x1482899], 7) == 0x4d39bfa and len(p[0x13c4e13]) == 96 and len(p[0x13c53af]) == 61
    assert bytes.fromhex('81FE8F010000') in p[0x13c53af]  # cmp esi, 399
    caves = sorted((at, at + len(v)) for at, v in p.items() if at >= 0x56eb000)
    assert caves[0][0] >= 0x56eb100 and caves[-1][1] <= 0x56ec000
    assert all(end <= nxt for (_s, end), (nxt, _e) in zip(caves, caves[1:]))


# sha256[:16] of the stock bytes each in-place bap32 line overwrites (no game bytes in the repo)
BAP32_STOCK = {0x1482899: '93f0501495858516', 0x13c4e13: 'aead0cf3f59e367a', 0x13c53af: 'd051f1e1c23696d5',
               0x100a920: 'b39457a8c5472e31', 0x100ab78: 'faf132a247fefa6e', 0x100ac27: '4047a382115d101a',
               0x1009b0d: '24a9f4ad0e8eaeb9'}


@pytest.mark.game
def test_bap32_matches_the_stock_eboot(game_dir):
    import hashlib
    import struct
    path = os.path.join(game_dir, 'eboot.bin-decrypted')
    if not os.path.exists(path):
        pytest.skip('no decrypted eboot')
    with open(path, 'rb') as f:
        elf = f.read()
    phoff, phnum = struct.unpack_from('<Q', elf, 0x20)[0], struct.unpack_from('<H', elf, 0x38)[0]
    text = [struct.unpack_from('<IIQQQQQQ', elf, phoff + k * 56) for k in range(phnum)]
    text = [h for h in text if h[0] == 1 and h[1] & 1]
    _t, _fl, off, va, _pa, _filesz, memsz, align = text[0]
    page_end = (va + memsz + align - 1) // align * align
    p = _bap32()
    assert set(BAP32_STOCK) == {at for at in p if at < va + memsz}
    for at, sha in BAP32_STOCK.items():
        assert hashlib.sha256(elf[off + at - va:off + at - va + len(p[at])]).hexdigest()[:16] == sha, hex(at)
    assert all(va + memsz <= at and at + len(v) <= page_end for at, v in p.items() if at not in BAP32_STOCK)


def test_repoint_keeps_every_switch_and_the_line_ends():
    nucleus = 'https://91.98.195.150/'
    for newline in ('\r\n', '\n'):
        full = xmlpatch.build('ot.puckpeak.com', nucleus, newline=newline)
        for make in (lambda t: t, xmlpatch.bap32_off, xmlpatch.expansion32_off):
            text = make(full)
            moved = xmlpatch.repoint(text, '192.168.1.15')
            assert moved == make(xmlpatch.build('192.168.1.15', newline=newline))
            assert xmlpatch.targets(moved)['redirector'] == '192.168.1.15'
            assert (xmlpatch.expansion32(moved), xmlpatch.bap32(moved)) == (xmlpatch.expansion32(text),
                                                                           xmlpatch.bap32(text))
            assert xmlpatch.repoint(moved, 'ot.puckpeak.com', nucleus) == text      # and back, byte for byte


def test_repoint_refuses_a_file_this_version_did_not_write():
    text = xmlpatch.build('ot.puckpeak.com', 'https://91.98.195.150/')
    edited = text.replace('82104380', '82104381')               # a hand edit of one line
    for bad in (edited, text.replace('isEnabled="true"', 'isEnabled="false"', 1),
                xmlpatch.build('ot.puckpeak.com', features=xmlpatch.DEFAULT[:3])):
        with pytest.raises(xmlpatch.PatchError):
            xmlpatch.repoint(bad, '192.168.1.15')
    with pytest.raises(xmlpatch.PatchError):
        xmlpatch.repoint(xmlpatch.build('a', features=('eagain',)), 'b')    # names no server


# sha256[:16] of the stock bytes the replays60 lines overwrite (flat address = patch address - 0x400000)
REPLAYS60_STOCK = {0x28ec8df: 'f0488a92c0aef001', 0x28ec8ef: '89a1ed29b83479f4'}
# res1440's in-place lines; its cave 0x4a35077 must be zero (text padding)
RES1440_STOCK = {0x293bd70: 'd86c53287702c1c8', 0x293bd75: '81dcac42b93e253a', 0x293bd7a: '399d8cd08536b989',
                 0x293bd7f: '97223e3ccb756b2d', 0x293bdaa: 'b46c03f95fc84025', 0x1736ea: '9fe9e18db3722a8d'}


@pytest.mark.game
def test_replays60_matches_the_stock_eboot(game_dir):
    import hashlib
    import struct
    path = os.path.join(game_dir, 'eboot.bin-decrypted')
    if not os.path.exists(path):
        pytest.skip('no decrypted eboot')
    with open(path, 'rb') as f:
        elf = f.read()
    phoff, phnum = struct.unpack_from('<Q', elf, 0x20)[0], struct.unpack_from('<H', elf, 0x38)[0]
    text = [h for h in (struct.unpack_from('<IIQQQQQQ', elf, phoff + k * 56) for k in range(phnum))
            if h[0] == 1 and h[1] & 1][0]
    _t, _fl, off, va, *_ = text
    res720 = {at: sha for at, sha in RES1440_STOCK.items() if at != 0x1736ea}   # res1440's in-place lines only
    for name, stock in (('replays60', REPLAYS60_STOCK), ('res1440', RES1440_STOCK), ('res720', res720)):
        lines = {int(a, 16) - 0x400000: bytes.fromhex(v) for a, v in xmlpatch.FEATURES[name].lines}
        assert set(stock) <= set(lines)
        caves = set(lines) - set(stock)
        assert caves == ({0x4a35077} if name == 'res1440' else set())
        for at, sha in stock.items():
            assert hashlib.sha256(elf[off + at - va:off + at - va + len(lines[at])]).hexdigest()[:16] == sha, hex(at)
        for at in caves:
            assert elf[off + at - va:off + at - va + len(lines[at])] == bytes(len(lines[at])), hex(at)


def test_replays60_is_on_by_default():
    block = next(b for b in xmlpatch.parse(xmlpatch.build('localhost')) if b['name'].startswith('60 FPS replays'))
    assert block['enabled'] and block['lines'] == [('0x2CEC8DF', 'BB01000000'), ('0x2CEC8EF', '909090')]


def test_repoint_brings_an_earlier_versions_file_up_to_date():
    nucleus = 'https://91.98.195.150/'
    for newline in ('\r\n', '\n'):
        for make in (lambda t: t, xmlpatch.bap32_off, xmlpatch.expansion32_off):
            old = make(xmlpatch.build('ot.puckpeak.com', nucleus, xmlpatch.EARLIER[0], newline))
            assert 'replays' not in old
            new = xmlpatch.repoint(old, 'ot.puckpeak.com', nucleus)        # same server: Play upgrades the file
            assert new == make(xmlpatch.build('ot.puckpeak.com', nucleus, newline=newline))
            assert (xmlpatch.expansion32(new), xmlpatch.bap32(new)) == (xmlpatch.expansion32(old), xmlpatch.bap32(old))


def test_the_resolution_blocks_are_written_off_and_switch_one_at_a_time():
    text = xmlpatch.build('localhost')
    assert xmlpatch.resolution(text) == 1080 and not xmlpatch.res1440(text)
    hi, lo = xmlpatch.with_resolution(text, 1440), xmlpatch.with_resolution(text, 720)
    assert xmlpatch.resolution(hi) == 1440 and xmlpatch.res1440(hi) and xmlpatch.with_resolution(hi, 1080) == text
    assert xmlpatch.resolution(lo) == 720 and not xmlpatch.res1440(lo) and xmlpatch.with_resolution(lo, 1080) == text
    assert xmlpatch.with_resolution(hi, 720) == lo and xmlpatch.with_resolution(lo, 1440) == hi   # never both on
    block = next(b for b in xmlpatch.parse(hi) if b['name'] == xmlpatch.RES1440_TITLE)
    assert block['lines'][0] == ('0x2D3BD70', 'B8000A0000') and len(block['lines']) == 7
    block = next(b for b in xmlpatch.parse(lo) if b['name'] == xmlpatch.RES720_TITLE)
    assert block['lines'] == [('0x2D3BD70', 'B800050000'), ('0x2D3BD75', 'BA00050000'), ('0x2D3BD7A', 'B9D0020000'),
                              ('0x2D3BD7F', 'BED0020000'), ('0x2D3BDAA', '41C7455800050000')]
    both = hi.replace(f'Name="{xmlpatch.RES720_TITLE}" AppVer="01.60" AppElf="eboot.bin" isEnabled="false"',
                      f'Name="{xmlpatch.RES720_TITLE}" AppVer="01.60" AppElf="eboot.bin" isEnabled="true"')
    with pytest.raises(xmlpatch.PatchError):
        xmlpatch.resolution(both)
    with pytest.raises(xmlpatch.PatchError):
        xmlpatch.with_resolution(text, 900)
    for old in (xmlpatch.build('localhost', features=f) for f in xmlpatch.EARLIER):
        assert xmlpatch.with_resolution(old, 1080) == old
        with pytest.raises(xmlpatch.PatchError):
            xmlpatch.with_resolution(old, 720)                    # no 720p block before 0.80.1


def test_the_720p_block_is_kravickas_lines_on_res1440s_addresses():
    """1280 = 0x500, 720 = 0x2d0 in the same instructions res1440 writes 2560 / 1440 into; no memory line."""
    hi, lo = (dict(xmlpatch.FEATURES[n].lines) for n in ('res1440', 'res720'))
    assert set(lo) < set(hi) and set(hi) - set(lo) == {'0x5736EA', '0x4E35077'}
    for addr, value in lo.items():
        assert value == hi[addr].replace('000A0000', '00050000').replace('A0050000', 'D0020000'), addr


def test_repoint_keeps_the_resolution():
    base = xmlpatch.build('ot.puckpeak.com', 'https://91.98.195.150/')
    for value in xmlpatch.RESOLUTIONS:
        on = xmlpatch.with_resolution(base, value)
        moved = xmlpatch.repoint(on, '192.168.1.15')
        assert xmlpatch.resolution(moved) == value and xmlpatch.targets(moved)['redirector'] == '192.168.1.15'
        assert xmlpatch.repoint(moved, 'ot.puckpeak.com', 'https://91.98.195.150/') == on


def test_repoint_brings_a_0_70_7_or_0_80_0_file_up_with_its_resolution():
    nucleus = 'https://91.98.195.150/'
    for features, value in ((f, v) for f in xmlpatch.EARLIER[1:] for v in (1080, 1440)):
        old = xmlpatch.with_resolution(xmlpatch.build('ot.puckpeak.com', nucleus, features), value)
        assert xmlpatch.RES720_TITLE not in old
        new = xmlpatch.repoint(old, 'ot.puckpeak.com', nucleus)
        assert new == xmlpatch.with_resolution(xmlpatch.build('ot.puckpeak.com', nucleus), value)


def test_netplay_fingerprint_counts_only_what_reaches_the_other_game():
    # live 2026-11-08: a 1440p game and a 1080p game were told their patches differ (0.70.7 hashed the whole file)
    base = xmlpatch.build('ot.puckpeak.com', 'https://91.98.195.150/')
    fp = xmlpatch.netplay_fingerprint(base)
    assert len(fp) == 20
    for value in xmlpatch.RESOLUTIONS:                                              # the picture size: local
        assert xmlpatch.netplay_fingerprint(xmlpatch.with_resolution(base, value)) == fp
    assert xmlpatch.netplay_fingerprint(xmlpatch.bap32_off(base)) == fp               # league switch off: Be a Pro only
    assert xmlpatch.netplay_fingerprint(xmlpatch.build('91.98.195.150')) == fp         # the same server by its address
    assert xmlpatch.netplay_fingerprint(base.replace('\r\n', '\n')) == fp
    # the Threes unlock guard only changes a lookup that would crash: a game without it still plays one with it
    no_xv = xmlpatch.netplay_fingerprint(xmlpatch.build('91.98.195.150', features=xmlpatch.NO_CROSSVENDOR))
    assert xmlpatch.netplay_fingerprint(xmlpatch.build('ot.puckpeak.com', 'https://91.98.195.150/',
                                                       features=xmlpatch.EARLIER[1])) == no_xv
    assert xmlpatch.netplay_fingerprint(xmlpatch.build('ot.puckpeak.com', 'https://91.98.195.150/',
                                                       features=xmlpatch.EARLIER[2])) == no_xv   # 0.80.0: no 720p block
    # the 720p block is local (Setup's Resolution): the 0.81.0 candidate's file, without it, plays today's
    assert xmlpatch.netplay_fingerprint(xmlpatch.build('ot.puckpeak.com', 'https://91.98.195.150/',
                                                       features=xmlpatch.EARLIER[3])) == fp
    # the cross-vendor block counts: a game without it (0.80, another eboot) never plays one with it
    assert no_xv != fp
    # the 32-team switch changes the online team list: that one counts, and so does any other game byte
    assert xmlpatch.netplay_fingerprint(xmlpatch.expansion32_off(base)) != fp
    assert xmlpatch.netplay_fingerprint(xmlpatch.build('ot.puckpeak.com', 'https://91.98.195.150/', features=xmlpatch.EARLIER[0])) != fp
