"""Compare two `cpu_estimates` files: do two PCs' `vrcpps`/`vrsqrtps` agree, raw or with shadPS4's correction?

Usage: python -m tools.cpu_estimates_compare A.zip B.zip [--shadps4 DIR]

DIR is a shadPS4 source checkout (or any folder holding `cpu_patches.cpp`, `amd_rcp_index_table.bin(.zstd)` and
`amd_rsqrt_index_table.bin(.zstd)`). Its tables are read at run time and never copied into Overtime. With it, the
Intel side's outputs are corrected the way shadPS4 does on Intel (output XOR xor_values[index_table[input >> 11]],
NaN inputs left out) and then compared with the AMD side.

Reading the result (docs/notes/cross-vendor-desync.md):
- raw identical: these two PCs never disagree, so this pair can't desync through the estimates.
- corrected identical: shadPS4's AMD math on the Intel PC makes this pair agree.
- corrected differs: the tables don't fit this pair (Zen 2 and Skylake were measured; the counts say where).
"""
import argparse
import array
import json
import os
import re
import sys
import zipfile

NAMES = {'vrcpps': ('rcp_xor_values', 'amd_rcp_index_table.bin'),
         'vrsqrtps': ('rsqrt_xor_values', 'amd_rsqrt_index_table.bin')}


def load(path):
    """{'info': dict, 'runs': {label: {insn: (first array('I'), [rel digests])}}}"""
    with zipfile.ZipFile(path) as z:
        info = json.loads(z.read('info.json'))
        runs = {}
        for r in info.get('runs', []):
            label = r['label']
            runs[label] = {}
            for insn in NAMES:
                first = array.array('I')
                first.frombytes(z.read(f'{label}/{insn}_first.bin'))
                rel = z.read(f'{label}/{insn}_rel.bin')
                runs[label][insn] = (first, [rel[i:i + 16] for i in range(0, len(rel), 16)])
    return {'info': info, 'runs': runs}


def _decompress(blob):
    try:
        from compression import zstd   # Python 3.14+
        return zstd.decompress(blob)
    except ImportError:
        pass
    try:
        import zstandard
        return zstandard.ZstdDecompressor().decompress(blob, max_output_size=1 << 22)
    except ImportError:
        raise SystemExit('The .zstd tables need Python 3.14 or the zstandard package; or put the decompressed .bin '
                         'files in the folder.') from None


def _find(root, name):
    for d, _dirs, files in os.walk(root):
        if name in files:
            return os.path.join(d, name)
    return None


def xor_values(cpp_text, name):
    """The `name = { ... }` integer list from cpu_patches.cpp's text."""
    m = re.search(re.escape(name) + r'\s*=\s*\{([^}]*)\}', cpp_text)
    if not m:
        raise ValueError(f'{name} not found')
    return [int(v, 0) for v in re.findall(r'0x[0-9a-fA-F]+|\d+', m.group(1))]


def shadps4_tables(root):
    """{insn: (index table bytes (2^21), xor values)} read from a shadPS4 source folder."""
    cpp = _find(root, 'cpu_patches.cpp')
    if not cpp:
        raise SystemExit(f'cpu_patches.cpp not found under {root}')
    text = open(cpp, encoding='utf-8', errors='replace').read()
    out = {}
    for insn, (values_name, table_name) in NAMES.items():
        raw = _find(root, table_name)
        if raw:
            table = open(raw, 'rb').read()
        else:
            packed = _find(root, table_name + '.zstd')
            if not packed:
                raise SystemExit(f'{table_name}(.zstd) not found under {root}')
            table = _decompress(open(packed, 'rb').read())
        if len(table) < 1 << 21:
            raise SystemExit(f'{table_name}: {len(table)} bytes, expected {1 << 21}')
        out[insn] = (table[:1 << 21], xor_values(text, values_name))
    return out


def is_nan_bucket(b):
    """Every input in bucket b (input >> 11) is a NaN: exponent all ones and a nonzero top-12 mantissa."""
    return (b >> 12) & 0xff == 0xff and b & 0xfff


def is_nan_chunk(c):
    """Chunk c (input >> 22) holds NaN inputs: exponent all ones. shadPS4 passes NaN lanes through uncorrected, so a
    difference there is no table question."""
    return (c >> 1) & 0xff == 0xff


def describe(b):
    sign = '-' if b >> 20 else '+'
    exp = (b >> 12) & 0xff
    return f'{sign}2^{exp - 127}' if 0 < exp < 255 else (f'{sign}denormal/0' if exp == 0 else f'{sign}inf/NaN')


def compare_insn(a, b, correction=None):
    """a, b: (first, rel) of one instruction; correction: (index table, xor values) applied to a, or None.
    Returns {'buckets', 'differ', 'chunks', 'chunks_differ', 'examples', 'by_exponent'}; NaN buckets are skipped."""
    fa, ra = a
    fb, rb = b
    n = min(len(fa), len(fb))
    differ, examples, by_exp = 0, [], {}
    table, values = correction if correction else (None, None)
    for i in range(n):
        if is_nan_bucket(i):
            continue
        va = fa[i] ^ values[table[i]] if table is not None else fa[i]
        if va != fb[i]:
            differ += 1
            key = describe(i)
            by_exp[key] = by_exp.get(key, 0) + 1
            if len(examples) < 5:
                examples.append((i << 11, va, fb[i]))
    chunks = min(len(ra), len(rb))
    bad = [i for i in range(chunks) if ra[i] != rb[i]]
    return {'buckets': n, 'differ': differ, 'chunks': chunks,
            'chunks_differ': sum(1 for i in bad if not is_nan_chunk(i)),
            'nan_chunks_differ': sum(1 for i in bad if is_nan_chunk(i)),
            'examples': examples, 'by_exponent': by_exp}


def _intel(info):
    cpu = info.get('cpu', {})
    return 'intel' in (cpu.get('vendor', '') + cpu.get('name', '')).lower()


def report(da, db, tables=None, say=print):
    """Print the comparison; returns {(label a, label b, insn, 'raw'|'corrected'): result}."""
    ia, ib = da['info'], db['info']
    say(f'A: {ia["cpu"].get("name")} ({ia["cpu"].get("identifier")}), {len(da["runs"])} run(s)')
    say(f'B: {ib["cpu"].get("name")} ({ib["cpu"].get("identifier")}), {len(db["runs"])} run(s)')
    for d, tag in ((da, 'A'), (db, 'B')):
        if len(d['runs']) > 1:
            labels = list(d['runs'])
            for insn in NAMES:
                r = compare_insn(d['runs'][labels[0]][insn], d['runs'][labels[1]][insn])
                same = r['differ'] == 0 and r['chunks_differ'] == 0
                say(f'{tag} core types {labels[0]} vs {labels[1]} {insn}: '
                    + ('identical' if same else f'DIFFER ({r["differ"]} buckets)'))
    intel_side = 'A' if _intel(ia) and not _intel(ib) else 'B' if _intel(ib) and not _intel(ia) else None
    out = {}
    for la, ra in da['runs'].items():
        for lb, rb in db['runs'].items():
            for insn in NAMES:
                r = compare_insn(ra[insn], rb[insn])
                out[(la, lb, insn, 'raw')] = r
                say(f'\n{insn} [{la} vs {lb}] raw: ' + _verdict(r))
                if tables and intel_side:
                    a, b = (ra[insn], rb[insn]) if intel_side == 'A' else (rb[insn], ra[insn])
                    rc = compare_insn(a, b, tables[insn])
                    out[(la, lb, insn, 'corrected')] = rc
                    say(f'{insn} [{la} vs {lb}] with shadPS4\'s correction on the Intel side ({intel_side}): '
                        + _verdict(rc))
                    if rc['chunks_differ']:
                        say('  the outputs inside some buckets differ by more than one constant XOR, so no per-bucket '
                            'table can fix those chunks')
    if tables and not intel_side:
        say('\n(No correction applied: it needs exactly one Intel side.)')
    return out


def _verdict(r):
    nan = (f'\n  ({r["nan_chunks_differ"]} NaN-input chunk(s) differ too: each CPU\'s own quiet NaN, which shadPS4 '
           'passes through; not a table question)') if r.get('nan_chunks_differ') else ''
    if r['differ'] == 0 and r['chunks_differ'] == 0:
        return f'identical for every non-NaN input ({r["buckets"]} buckets, {r["chunks"]} chunks)' + nan
    s = (f'DIFFER: {r["differ"]} of {r["buckets"]} buckets\' first outputs, {r["chunks_differ"]} of {r["chunks"]} '
         'chunk patterns') + nan
    if r['by_exponent']:
        top = sorted(r['by_exponent'].items(), key=lambda kv: -kv[1])[:8]
        s += '\n  where: ' + ', '.join(f'{k} ({v})' for k, v in top)
    for x, va, vb in r['examples']:
        s += f'\n  input {x:#010x}: {va:#010x} vs {vb:#010x}'
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('a')
    ap.add_argument('b')
    ap.add_argument('--shadps4', help='shadPS4 source folder (cpu_patches.cpp and the amd_*_index_table files)')
    a = ap.parse_args(argv)
    tables = shadps4_tables(a.shadps4) if a.shadps4 else None
    report(load(a.a), load(a.b), tables)
    return 0


if __name__ == '__main__':
    sys.exit(main())
