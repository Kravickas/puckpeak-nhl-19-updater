import array
import math
import os
import struct
import zipfile

import pytest

from tools import cpu_estimates as C
from tools import cpu_estimates_compare as X

needs_avx = pytest.mark.skipif(os.name != 'nt' or not C.has_avx(), reason='runs x86 code: Windows with AVX')


def _f(bits):
    return struct.unpack('<f', struct.pack('<I', bits))[0]


def test_the_machine_code_is_the_listed_instructions():
    capstone = pytest.importorskip('capstone')
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    got = {name: [(a, f'{m} {o}'.strip()) for a, _s, m, o in md.disasm_lite(b, 0)]
           for name, b in C.kernel_bytes().items()}
    for insn in C.INSNS:
        assert [t for _a, t in got[insn]] == [
            'vmovd xmm0, ecx', 'vpshufd xmm0, xmm0, 0', 'vpaddd xmm0, xmm0, xmmword ptr [r9]',
            'vmovdqu xmm2, xmmword ptr [r9 + 0x10]', f'{insn} xmm1, xmm0', 'vmovups xmmword ptr [r8], xmm1',
            'vpaddd xmm0, xmm0, xmm2', 'add r8, 0x10', 'sub rdx, 4', 'jne 0x14', 'ret']
        assert dict((t, a) for a, t in got[insn])[f'{insn} xmm1, xmm0'] == 0x14   # the loop starts at the estimate
    rel = got['rel']
    assert [t for _a, t in rel] == [
        'vbroadcastss xmm1, dword ptr [rcx]', 'mov eax, 0x200', 'vxorps xmm0, xmm1, xmmword ptr [rcx]',
        'vmovups xmmword ptr [rcx], xmm0', 'add rcx, 0x10', 'dec eax', 'jne 0xa', 'dec rdx', 'jne 0', 'ret']
    assert dict((t, a) for a, t in rel)['vxorps xmm0, xmm1, xmmword ptr [rcx]'] == 0xa
    assert 0x200 * 4 == C.BUCKET


@needs_avx
@pytest.mark.parametrize('start', [0x3f800000, 0x00800000, 0x7e000000, 0xbf800000])
def test_estimates_stay_inside_the_spec_and_repeat_exactly(start):
    k = C.Kernels()
    try:
        for insn in C.INSNS:
            got = k.estimates(insn, start, 4096)
            assert k.estimates(insn, start, 4096) == got
            for i, v in enumerate(struct.unpack('<4096I', got)):
                x = _f(start + i)
                if insn == 'vrsqrtps' and x < 0:
                    assert math.isnan(_f(v))
                    continue
                exact = 1 / x if insn == 'vrcpps' else 1 / math.sqrt(x)
                assert abs(_f(v) - exact) <= 1.5 * 2 ** -12 * abs(exact), (insn, hex(start + i))
        assert struct.unpack('<4I', k.estimates('vrcpps', 0, 4))[0] == 0x7f800000   # 1/+0 = +inf
        with pytest.raises(ValueError):
            k.estimates('vrcpps', 0, 6)
        with pytest.raises(ValueError):
            k.estimates('vrcpps', 0xfffffffc, 8)
    finally:
        k.close()


@needs_avx
def test_relative_xors_every_value_with_its_buckets_first():
    k = C.Kernels()
    try:
        # arbitrary words, not estimates: on this AMD the estimate is the same for every input of a bucket
        r = [(i * 2654435761) & 0xffffffff for i in range(3 * C.BUCKET)]
        rel = bytearray(struct.pack(f'<{len(r)}I', *r))
        k.relative(rel)
        w = struct.unpack(f'<{len(r)}I', rel)
        for i in range(len(r)):
            assert w[i] ^ r[i - i % C.BUCKET] == r[i]
        assert w[0] == w[C.BUCKET] == 0 and any(w)
        with pytest.raises(ValueError):
            k.relative(bytearray(100))
    finally:
        k.close()


@needs_avx
def test_a_short_run_writes_one_file_that_compares_identical_with_itself(tmp_path):
    lines = []
    path = C.run(str(tmp_path), chunks=2, say=lines.append)
    assert os.path.basename(path).startswith('cpu-estimates-') and path.endswith('.zip')
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
    assert {'info.json', 'cpu/vrcpps_first.bin', 'cpu/vrcpps_rel.bin', 'cpu/vrsqrtps_first.bin'} <= names
    d = X.load(path)
    first, rel = d['runs']['cpu']['vrcpps']
    assert len(first) == 2 * C.CHUNK // C.BUCKET and len(rel) == 2
    assert d['info']['runs'][0]['fingerprints']['vrcpps'] == C.fingerprint(first.tobytes(), b''.join(rel))
    out = X.report(d, d, say=lambda *_: None)
    assert all(r['differ'] == 0 and r['chunks_differ'] == 0 for r in out.values())


@needs_avx
def test_a_hybrid_cpu_gets_one_run_per_core_type(tmp_path, monkeypatch):
    monkeypatch.setattr(C, 'core_types', lambda: [(0, 0), (1, 0)])
    path = C.run(str(tmp_path), chunks=1, say=lambda *_: None)
    d = X.load(path)
    assert list(d['runs']) == ['class0', 'class1']
    lines = []
    X.report(d, d, say=lines.append)
    assert any('core types class0 vs class1 vrcpps: identical' in s for s in lines)


def _dump(vendor, firsts, rels):
    runs = {'cpu': {insn: (array.array('I', firsts[insn]), rels[insn]) for insn in X.NAMES}}
    return {'info': {'cpu': {'name': vendor + ' test', 'vendor': vendor, 'identifier': 'x'}, 'runs': []}, 'runs': runs}


def test_the_correction_goes_on_the_intel_side_and_skips_nan_buckets():
    n = 4096
    table = bytes(i % 3 for i in range(n))
    values = [0, 0x800, 0x1000]
    base = list(range(1000, 1000 + n))
    intel = [v ^ values[table[i]] for i, v in enumerate(base)]
    rel = [b'r' * 16, b's' * 16]
    tables = {insn: (table, values) for insn in X.NAMES}
    amd = _dump('AuthenticAMD', {insn: base for insn in X.NAMES}, {insn: rel for insn in X.NAMES})
    itl = _dump('GenuineIntel', {insn: intel for insn in X.NAMES}, {insn: rel for insn in X.NAMES})
    out = X.report(amd, itl, tables, say=lambda *_: None)
    assert out[('cpu', 'cpu', 'vrcpps', 'raw')]['differ'] > 0
    assert out[('cpu', 'cpu', 'vrcpps', 'corrected')]['differ'] == 0
    base[5] ^= 1
    amd = _dump('AuthenticAMD', {insn: base for insn in X.NAMES}, {insn: rel for insn in X.NAMES})
    r = X.report(amd, itl, tables, say=lambda *_: None)[('cpu', 'cpu', 'vrsqrtps', 'corrected')]
    assert r['differ'] == 1 and r['examples'][0][0] == 5 << 11
    other = _dump('AuthenticAMD', {insn: base for insn in X.NAMES}, {insn: [b'r' * 16, b't' * 16] for insn in X.NAMES})
    assert X.compare_insn(other['runs']['cpu']['vrcpps'], amd['runs']['cpu']['vrcpps'])['chunks_differ'] == 1
    full = [bytes([i % 251]) * 16 for i in range(1024)]
    nan_only = list(full)
    nan_only[0x7fc00000 >> 22] = b'n' * 16   # a NaN-input chunk: each CPU's own quiet NaN, not a table question
    r = X.compare_insn((array.array('I', base), full), (array.array('I', base), nan_only))
    assert r['chunks_differ'] == 0 and r['nan_chunks_differ'] == 1 and 'identical' in X._verdict(r)
    assert [c for c in range(1024) if X.is_nan_chunk(c)] == [0x1fe, 0x1ff, 0x3fe, 0x3ff]
    assert X.is_nan_bucket(0x7fc00000 >> 11) and X.is_nan_bucket(0xffc00000 >> 11)
    assert not X.is_nan_bucket(0x7f800000 >> 11) and not X.is_nan_bucket(0x3f800000 >> 11)


def test_tables_are_read_from_a_shadps4_folder_at_run_time(tmp_path):
    src = tmp_path / 'src' / 'core'
    res = tmp_path / 'src' / 'resources'
    src.mkdir(parents=True)
    res.mkdir(parents=True)
    (src / 'cpu_patches.cpp').write_text('constexpr static std::array rcp_xor_values = {\n    0x00000000, 0x00000010};\n'
                                         'constexpr static std::array rsqrt_xor_values = {0x0, 0x20, 0x30};\n')
    (res / 'amd_rcp_index_table.bin').write_bytes(bytes(1 << 21))
    with pytest.raises(SystemExit):
        X.shadps4_tables(str(tmp_path))
    (res / 'amd_rsqrt_index_table.bin').write_bytes(b'\x01' * (1 << 21))
    t = X.shadps4_tables(str(tmp_path))
    assert t['vrcpps'][1] == [0, 0x10] and t['vrsqrtps'][1] == [0, 0x20, 0x30]
    assert len(t['vrsqrtps'][0]) == 1 << 21 and t['vrsqrtps'][0][7] == 1


def test_the_file_is_named_after_the_cpu():
    assert C.file_name('Intel(R) Core(TM) i5-10210U CPU @ 1.60GHz') == 'cpu-estimates-Intel-Core-i5-10210U.zip'
    assert C.file_name('AMD Ryzen 7 9800X3D 8-Core Processor') == 'cpu-estimates-AMD-Ryzen-7-9800X3D-8-Core-Processor.zip'
    assert C.file_name('') == 'cpu-estimates-cpu.zip'
