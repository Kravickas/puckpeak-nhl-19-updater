"""Overtime eboot patch: the GoldHEN-style XML that shadPS4 applies in memory to NHL 19 (CUSA11126, v1.60).

Nothing is written to the game: shadPS4 reads the file at boot (`-p <file>`, or its patches folder) and changes the
loaded eboot only. `build` makes the file from the FEATURES table below; `build('localhost', newline='\\n')` is
`patches/overtime_dev.xml` and `build('192.168.1.15')` is `patches/overtime_lan.xml`, byte for byte.

  eagain      ProtoHttp accepts shadPS4's EAGAIN while a non-blocking request is in flight (else every request drops)
  redirector  the redirector host string (stock "spring18.gosredirector.ea.com", room 29 chars)
  qos_ncrt    no TLS certificate check on the QoS coordinator link only
  nucleus     the three Nucleus base URLs (stock accounts / gateway / signin, room 24 / 23 / 22 chars)
  expansion32 the 32-team switch on in Season, Play Now and Classic Franchise (team 499 = Seattle).
              Needs a roster whose Seattle 499 has players and is active (customteams), as the default roster has
              since 2026-10-20; an empty, inactive 499 crashes New Season (docs/notes/32teams-everywhere.md, E32, s1)
  bap32       Seattle in Be a Pro: Choose Team keeps the expansion team (399) and a Be a Pro league is built with 32
              teams (NHL and AHL) while the 32-team switch is live; with the overlay league layer's Be a Pro Lua
              (overlay.BAP_PATHS). Goes off with the switch (expansion32_off) (docs/notes/nhl19-32teams-re.md, run c2)
  ledger_cap  a capacity check on the Franchise per-team list append in 0x423ad80 (a daily per-team ledger, cleared at
              the season reset: 369 days against 366 slots), whose overflow crashes the expansion career offseason at
              0x423ce8c; the cap drops at most 3 days' entries (docs/notes/nhl19-32teams-re.md, R1: runs c1, e1)

A string slot holds as many characters as the stock string it replaces (its NUL follows), so the address must fit:
`https://ot.puckpeak.com/` (24) fits only the accounts slot, `https://91.98.195.150/` (22) fits all three
(docs/notes/remaster-recon.md). Addresses are eboot vaddr + 0x400000 (docs/notes/shadps4-network.md).
"""
import re
import xml.etree.ElementTree as ET
from string import Template

APP_VER = '01.60'

HEADER = """<?xml version="1.0" encoding="utf-8"?>
<!--
  Overtime dev patches for NHL 19 (CUSA11126, v1.60), applied in memory by shadPS4: pass this file to tools/run_game.py (patch option).
  Addresses are eboot vaddr + 0x400000 (shadPS4 subtracts 0x400000 for non-offset lines). See docs/notes/shadps4-network.md.
-->
<Patch>
"""
FOOTER = "</Patch>\n"

REDIRECTOR = '0x51DCCFF'
NUCLEUS = ('0x526E089', '0x526E0A2', '0x526E0BA')
E32_DEFAULT, E32_STOCK = '0x6F7963', 'C6051E2EC50500'
BAP32_TITLE = 'BAP32: Seattle in Be a Pro'


class Feature:
    """One <Metadata> block. `lines` hold (address, hex bytes) for code, or (address, room, template) for a string slot;
    `title` and `comment` are templates over $redirector / $nucleus (the Nucleus host) / $nucleus_url."""

    def __init__(self, title, comment, lines):
        self.title, self.comment, self.lines = title, comment, lines


FEATURES = {
    'eagain': Feature(
        'ProtoHttp: accept EAGAIN while waiting for the status code',
        """  <!-- ProtoHttp polls sceHttpGetStatusCode while a non-blocking request is in flight and only treats 0x80431065 as
       "not ready"; shadPS4 answers 0x80431082 (EAGAIN), so every request was dropped. cmp eax, imm32 at 0x3890812. -->""",
        [('0x3C90813', '82104380')]),
    'redirector': Feature(
        'Redirector host: $redirector',
        """  <!-- Redirector host "spring18.gosredirector.ea.com" (0x4ddccff) -> "$redirector", so no hosts-file entry is needed. -->""",
        [(REDIRECTOR, 29, '$redirector')]),
    'qos_ncrt': Feature(
        'QoS coordinator: skip TLS cert validation',
        """  <!-- QosClient copies its 'ncrt' flag (state+0xe467) into the ProtoSSL ref before the coordinator request
       (mov cl, [rbx+0xe467] at 0x385aa16). mov cl, 1 disables cert validation for the QoS coordinator link only. -->""",
        [('0x3C5AA16', 'B10190909090')]),
    'nucleus': Feature(
        'Nucleus hosts: $nucleus',
        """  <!-- Nucleus prod base URLs (flat 0x4e6e089 accounts, 0x4e6e0a2 gateway, 0x4e6e0ba signin) -> https://localhost/
       (the stub serves HTTPS on 443). The login state machine calls {accounts}connect/auth, connect/token, ... -->""",
        [(NUCLEUS[0], 24, '$nucleus_url'), (NUCLEUS[1], 23, '$nucleus_url'), (NUCLEUS[2], 22, '$nucleus_url')]),
    'expansion32': Feature(
        'E32: 32 teams in every mode',
        """  <!-- Tweak gFEGameModesBeAGM_Enable32TeamExpansion (bool, object 0x5f4a750): its static initialiser stores the
       default 0 (mov byte [rip+0x5c52e1e], 0 at 0x2f7963 -> +0x38); the registry takes it as the live value that the
       TeamList builder (0x1d5e8a0, appends team 499) and the team-count getters read. Default 1 = 32 teams. -->""",
        [(E32_DEFAULT, 'C6051E2EC50501')]),
    'ledger_cap': Feature(
        'R1: cap check on the Franchise per-team list append',
        """  <!-- 0x423ad80 appends a 0x38 entry to a team's fixed list (32 slots of 366 inline entries, header begin/end/cap)
       with no capacity check; a full list's next entry zeroes the next team's begin/end and that team's next append
       writes to 0 (0xc0000005 at 0x423ce8c after "Too few players"). Hook 0x423ce71 -> cave 0x56eb000 (text padding):
       end >= cap skips the entry (jmp to the per-player cleanup 0x423b41b), else the original 3 instructions.
       The same ledger's four other appends (not-found blocks at 0x42094b1, 0x421146f, 0x422c2af, 0x422487f) get caves
       0x56eb040, 0x56eb070, 0x56eb0a0, 0x56eb0d0: end >= cap takes the last entry (its function's own found path,
       0x42094ed, 0x42114b3, 0x422c2f2, 0x42248c3) in place of a new one, else the original block. -->""",
        [('0x463CE71', 'E98AE14A0190909090909090'),
         ('0x5AEB000', '488B7C02104839FE7311488D440208488D7E38488938E9621EB5FEE9FB03B5FE'),
         ('0x46094B1', 'E98A1B4E0190909090909090'),
         ('0x5AEB040', '488B5408104839D37311488D440808488D5338488910E962E4B1FE488D5BC8E989E4B1FE'),
         ('0x461146F', 'E9FC9B4D0190909090909090'),
         ('0x5AEB070', '488B5408104839D77311488D440808488D5738488910E9F063B2FE488D7FC8E91F64B2FE'),
         ('0x462C2AF', 'E9ECED4B019090909090909090909090'),
         ('0x5AEB0A0', '488B5408104839D67315488D440808488D5638C5F857C0488910E90012B4FE488D76C8E92A12B4FE'),
         ('0x462487F', 'E94C684C019090909090909090'),
         ('0x5AEB0D0', '488B5408104939D47312488D440808498D542438488910E9A097B3FE4D8D6424C8E9CD97B3FE')]),
    'bap32': Feature(
        BAP32_TITLE,
        """  <!-- Be a Pro's Choose Team job (0x14827b0) sends Context "Exhibition"; its lea at 0x1482899 points at the job's
       own name ("nhl-job:bap-creation:...") as a marker. by-league-id (0x13c4910): the Context test at 0x13c4e13 sets
       bit 7 of [rbp-0x2c9] for a marked request, and the Exhibition limit block at 0x13c53af keeps team 399 for it.
       Builder 0x1008640 (competition:info:add): 0x100a920 -> cave 0x56eb100, so Be a Pro ([rbp-0x800]) also copies the
       mode-creation team list (loop 0x100ab60; exits 0x100ab78 / 0x100ac27 -> caves 0x56eb160 / 0x56eb180 back to the
       Be a Pro block 0x100a926). 0x1009b0d -> cave 0x56eb1a0: in Be a Pro with the 32-team switch live
       ([[0x5f4a790]+0x29]) the config is made for 32 teams (esi, [cfg+0x294] NHL, [cfg+0x3ec] AHL with 498). -->""",
        [('0x1882899', '488D155A738B03'),
         ('0x17C4E13', '4C8BBD20FDFFFF81384C656167750981780367756500744880BD37FDFFFF000F84960100006A1F5A488B0D5606F304'
                       'E313837930007E0D488B5140488B12488B128B521881386E686C2D750380CA80889537FDFFFFE961010000909090'
                       '909090'),
         ('0x17C53AF', '8BB35401000085C075330FB68D37FDFFFFE32A0FBAF107730F81FE8F0100007507BE8F010000EB1539CE7D20EB0F'
                       '909090909090909090909090909090'),
         ('0x140A920', 'E9DB076E0490'),
         ('0x140AB78', 'E9E3056E0490'),
         ('0x140AC27', 'E954056E04'),
         ('0x5AEB100', '0F8449FA91FB498B8424C0000000492B8424B8000000483D000300000F8504F891FBE939FA91FB488BBD10F8FFFF'
                       'C7879402000020000000C7875C140000000000008B8F3C0E0000448B87400E0000BE2000000031D2E8E5C295FE'
                       'E900FA91FB'),
         ('0x5AEB160', '0F8518FA91FB80BD00F8FFFF000F85B3F791FBE9150392FB'),
         ('0x5AEB180', '80BD00F8FFFF000F8599F791FBE9020392FB'),
         ('0x1409B0D', 'E88E166E049090'),
         ('0x5AEB1A0', '31F680BD00F8FFFF00742F488B05DEF585004885C0742380782900741DBE2000000041C7842494020000200000'
                       '0041C78424EC0300002000000031D24C89E7C3')]),
}
# bap32 and expansion32 stay last: DEFAULT[:-2] is the patch without the 32-team switch (xmlpatch.expansion32_off)
DEFAULT = ('eagain', 'redirector', 'qos_ncrt', 'nucleus', 'ledger_cap', 'bap32', 'expansion32')

_HOST = re.compile(r'[A-Za-z0-9.-]+\Z')
_URL = re.compile(r'(https?)://([A-Za-z0-9.-]+(?::\d{1,5})?)/\Z')


class PatchError(ValueError):
    pass


def _string_hex(text, room, addr):
    if len(text) > room:
        raise PatchError(f'{text!r} is {len(text)} characters; the slot at {addr} holds {room}')
    return (text.encode('ascii') + b'\0').hex().upper()


def build(host, nucleus_url=None, features=DEFAULT, newline='\r\n'):
    """The patch file's text. `host` is the redirector host; each Nucleus slot gets `https://<host>/` where it fits and
    `nucleus_url` where it doesn't (e.g. `https://91.98.195.150/` for the 23/22-char slots when `host` is
    ot.puckpeak.com). The game logs in through the accounts slot (spike N1), which must name the host: Caddy routes 443
    by name and has no site for a bare IP (run oneclick h1, 2026-10-20: all three slots on the IP, no /connect/auth)."""
    if not _HOST.match(host or '') or '--' in host:  # '--' would end the XML comment that names the host
        raise PatchError(f'not a host name or address: {host!r}')
    host_url = f'https://{host}/'
    nucleus_url = nucleus_url or host_url
    m = _URL.match(nucleus_url)
    if not m or '--' in nucleus_url:
        raise PatchError(f'not a Nucleus base URL (scheme://host[:port]/): {nucleus_url!r}')
    slot_urls = {addr: host_url if len(host_url) <= room else nucleus_url
                 for addr, room, _ in FEATURES['nucleus'].lines}
    names = list(dict.fromkeys(_URL.match(u).group(2) for u in slot_urls.values()))
    subs = {'redirector': host, 'nucleus': ', '.join(names), 'nucleus_url': nucleus_url}
    out = [HEADER]
    for name in features:
        if name not in FEATURES:
            raise PatchError(f'unknown patch feature {name!r}')
        f = FEATURES[name]
        lines = []
        for line in f.lines:
            if len(line) == 2:
                addr, value = line
            else:
                addr, room, template = line
                text = slot_urls[addr] if template == '$nucleus_url' else Template(template).substitute(subs)
                value = _string_hex(text, room, addr)
            lines.append(f'      <Line Type="bytes" Address="{addr}" Value="{value}"/>\n')
        out.append(Template(f.comment).safe_substitute(subs) + '\n')
        out.append(f'  <Metadata Name="{Template(f.title).substitute(subs)}" AppVer="{APP_VER}" AppElf="eboot.bin" '
                   f'isEnabled="true">\n    <PatchList>\n')
        out.extend(lines)
        out.append('    </PatchList>\n  </Metadata>\n')
    out.append(FOOTER)
    return ''.join(out).replace('\n', newline)


def write(path, text):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)


def parse(text):
    """The blocks of a patch file: [{'name', 'app_ver', 'enabled', 'lines': [(address, hex)]}]."""
    try:
        root = ET.fromstring(text.encode('utf-8') if isinstance(text, str) else text)
    except ET.ParseError as e:
        raise PatchError(f'not a patch file: {e}') from None
    blocks = []
    for md in root.iter('Metadata'):
        blocks.append({
            'name': md.get('Name', ''),
            'app_ver': md.get('AppVer', ''),
            'enabled': md.get('isEnabled', 'true').lower() == 'true',
            'lines': [(ln.get('Address', ''), (ln.get('Value') or '').upper()) for ln in md.iter('Line')],
        })
    return blocks


def targets(text):
    """Where a patch file sends the game: {'redirector': host or None, 'nucleus': [url, ...]} (enabled blocks only)."""
    values = {addr.upper(): value for b in parse(text) if b['enabled'] for addr, value in b['lines']}

    def text_at(addr):
        value = values.get(addr.upper())
        if value is None:
            return None
        try:
            return bytes.fromhex(value).split(b'\0', 1)[0].decode('ascii')
        except (ValueError, UnicodeDecodeError):
            return None

    return {'redirector': text_at(REDIRECTOR), 'nucleus': [u for u in map(text_at, NUCLEUS) if u is not None]}


def expansion32(text):
    """Whether a patch file turns the 32-team switch on (an enabled block writes expansion32's bytes)."""
    addr32, on = FEATURES['expansion32'].lines[0]
    return any(addr.lower() == addr32.lower() and value == on
               for b in parse(text) if b['enabled'] for addr, value in b['lines'])


def expansion32_off(text):
    """The patch file with the 32-team line writing the stock bytes back (a no-op), for a roster whose Seattle is
    empty or inactive (rosterupdate.seattle_ready): New Season crashes there with the switch on (ws8 run7a). The Be a
    Pro block (bap32) is disabled with it: without the switch its league stays at 31 and Choose Team must not offer
    Seattle. A file with neither comes back as it is."""
    on = FEATURES['expansion32'].lines[0][1]
    out = re.sub(f'(Address="{E32_DEFAULT}" Value="){on}"', rf'\g<1>{E32_STOCK}"', text, flags=re.IGNORECASE)
    if expansion32(out):
        raise PatchError('the 32-team line is written in a way this tool does not change')
    return bap32_off(out)


def bap32_off(text):
    """The patch file with the Be a Pro block (bap32) disabled: without the switch, or without the overlay league
    layer's Be a Pro Lua (Choose Team would offer Seattle and start the career elsewhere)."""
    out = re.sub(f'(<Metadata Name="{re.escape(BAP32_TITLE)}"[^>]*?isEnabled=")true"', r'\g<1>false"', text)
    if bap32(out):
        raise PatchError('the Be a Pro block is written in a way this tool does not change')
    return out


def bap32(text):
    """Whether a patch file's Be a Pro block (bap32) is there and enabled."""
    return any(b['enabled'] and b['name'] == BAP32_TITLE for b in parse(text))


def _switched(text, e32, bap):
    """`text` (a build) with the 32-team switch / Be a Pro block as a patch file had them (patch_ctl.one_click)."""
    if not e32:
        return expansion32_off(text)
    return text if bap else bap32_off(text)


def repoint(text, host, nucleus_url=None):
    """The patch file `text` for another server: the same features and switches, the redirector and Nucleus slots
    naming `host` / `nucleus_url`. A server change then needs no Patch (owner, 2026-11-03). Refused (PatchError) when
    `text` is not what this version writes for its own server (another Overtime's file, a hand edit): Patch makes it
    new then."""
    old = targets(text)
    if not old['redirector']:
        raise PatchError('the patch file names no server')
    own = f"https://{old['redirector']}/"
    nucleus = next((u for u in old['nucleus'] if u != own), None)
    newline = '\r\n' if '\r\n' in text else '\n'
    e32, bap = expansion32(text), bap32(text)
    try:
        same = _switched(build(old['redirector'], nucleus, newline=newline), e32, bap) == text
    except PatchError:
        same = False
    if not same:
        raise PatchError('the patch file is not the one this Overtime writes; Patch the game again')
    return _switched(build(host, nucleus_url, newline=newline), e32, bap)
