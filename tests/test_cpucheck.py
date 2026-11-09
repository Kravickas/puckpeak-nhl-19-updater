"""Check my CPU (overtime_roster/app/cpucheck.py): the digests, the verdicts, the run of the tool, the report."""
import base64
import gzip
import json
import os
import struct
import threading
import zipfile

import pytest

from overtime_roster.app import cpucheck as C, cpuref, crashreport as CR, packdownload

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUMPS = {   # tools/build_cpuref.py's (not imported: the public tree has no tools/)
    'amd': os.path.join(ROOT, 're', 'extract', 'cpu-estimates', 'cpu-estimates-AMD-Ryzen-7-9800X3D-8-Core-Processor.zip'),
    'intel': os.path.join(ROOT, 're', 'extract', 'cpu-estimates', 'cpu-estimates-Intel-Core-i5-10210U.zip'),
}
INTEL_ID, AMD_ID = 'GenuineIntel', 'AuthenticAMD'
NAN_EVEN, NAN_ODD = 0x1fe, 0x1ff        # the chunks of positive infinity and NaNs


def data(seed, bucket=None, rel_chunk=None):
    """(first, rel) of one synthetic run: `seed` picks the values; `bucket` (a bucket number) and `rel_chunk` (a chunk
    number) are changed from them."""
    first = bytearray(struct.pack('<I', seed) * (1 << 21))
    rel = bytearray(bytes([seed & 0xff]) * C.REL_BYTES)
    if bucket is not None:
        first[bucket * 4] ^= 0x01
    if rel_chunk is not None:
        rel[rel_chunk * 16] ^= 0x01
    return bytes(first), bytes(rel)


def dump(path, vendor, runs, tool=C.TOOL, name='Test CPU', compression=zipfile.ZIP_STORED):
    """A cpu_estimates zip; runs: {label: (first, rel)} (the same data for both instructions)."""
    info = {'tool': tool, 'cpu': {'name': name, 'vendor': vendor, 'identifier': 'Family 6'}, 'platform': 'Windows',
            'chunks': C.CHUNKS, 'seconds': 30.0,
            'runs': [{'label': label, 'efficiency_class': None if label == 'cpu' else int(label[-1]),
                      'logical_processor': None, 'fingerprints': {i: '0123456789abcdef' for i in C.INSNS}}
                     for label in runs]}
    with zipfile.ZipFile(path, 'w', compression) as z:
        z.writestr('info.json', json.dumps(info))
        for label, (first, rel) in runs.items():
            for insn in C.INSNS:
                z.writestr(f'{label}/{insn}_first.bin', first)
                z.writestr(f'{label}/{insn}_rel.bin', rel)
    return str(path)


@pytest.fixture(scope='module')
def refs(tmp_path_factory):
    d = tmp_path_factory.mktemp('refs')
    return {'amd': C.reference(dump(d / 'a.zip', AMD_ID, {'cpu': data(1)})),
            'intel': C.reference(dump(d / 'i.zip', INTEL_ID, {'cpu': data(2)}))}


def test_each_reference_cpu_is_judged_its_own_kind(tmp_path, refs):
    amd = C.judge(dump(tmp_path / 'a.zip', AMD_ID, {'cpu': data(1)}), refs)
    intel = C.judge(dump(tmp_path / 'i.zip', INTEL_ID, {'cpu': data(2)}), refs)
    assert (amd['verdict'], intel['verdict']) == (C.AMD, C.INTEL)
    assert amd['runs'][0]['like'] == 'amd' and amd['runs'][0]['differs']['amd'] == 0
    assert intel['runs'][0]['differs'] == {'amd': 2 * (C.CHUNKS - 2), 'intel': 0}   # the 2 odd NaN chunks hold nothing
    line, tone, title = C.text(intel)
    assert tone == 'good' and 'proven' in line and '2048 of 2048 parts like the Intel reference' in title


def test_one_bucket_off_is_unknown_and_told_how_close(tmp_path, refs):
    r = C.judge(dump(tmp_path / 'x.zip', INTEL_ID, {'cpu': data(2, bucket=5000)}), refs)
    assert r['verdict'] == C.UNKNOWN and r['runs'][0]['like'] is None
    assert r['runs'][0]['differs']['intel'] == 2          # one chunk, both instructions
    assert C.text(r)[1] == 'caution' and 'send' in C.text(r)[0]


def test_nan_inputs_do_not_count_but_infinity_does(tmp_path, refs):
    nan_bucket = NAN_EVEN * C.PER_CHUNK + 5           # (b >> 12) & 0xff == 0xff and b & 0xfff
    odd = NAN_ODD * C.PER_CHUNK
    r = C.judge(dump(tmp_path / 'n.zip', INTEL_ID, {'cpu': data(2, bucket=nan_bucket, rel_chunk=NAN_ODD)}), refs)
    assert r['verdict'] == C.INTEL
    r = C.judge(dump(tmp_path / 'o.zip', INTEL_ID, {'cpu': data(2, bucket=odd)}), refs)
    assert r['verdict'] == C.INTEL
    r = C.judge(dump(tmp_path / 'inf.zip', INTEL_ID, {'cpu': data(2, bucket=NAN_EVEN * C.PER_CHUNK)}), refs)
    assert r['verdict'] == C.UNKNOWN                  # the infinity's bucket (1/inf = 0) counts
    r = C.judge(dump(tmp_path / 'r.zip', INTEL_ID, {'cpu': data(2, rel_chunk=3)}), refs)
    assert r['verdict'] == C.UNKNOWN                  # an in-bucket difference of a number chunk counts


def test_the_maker_must_match_the_reference(tmp_path, refs):
    """shadPS4 corrects Intel results only: AMD-like results on an Intel would be 'corrected' away from AMD's."""
    r = C.judge(dump(tmp_path / 'x.zip', INTEL_ID, {'cpu': data(1)}), refs)
    assert r['verdict'] == C.UNKNOWN and r['runs'][0]['like'] == 'amd'
    assert "other maker's reference" in C.text(r)[0]
    assert C.judge(dump(tmp_path / 'y.zip', 'CentaurHauls', {'cpu': data(2)}), refs)['verdict'] == C.UNKNOWN


def test_hybrid_core_types_must_agree(tmp_path, refs):
    same = C.judge(dump(tmp_path / 'h.zip', INTEL_ID, {'class0': data(2), 'class1': data(2)}), refs)
    assert same['verdict'] == C.INTEL and same['core_types_agree'] and len(same['runs']) == 2
    mixed = C.judge(dump(tmp_path / 'm.zip', INTEL_ID, {'class0': data(2), 'class1': data(2, bucket=9)}), refs)
    assert mixed['verdict'] == C.MIXED and not mixed['core_types_agree']
    line, tone, title = C.text(mixed)
    assert tone == 'bad' and 'core types' in line and title.startswith('class0: ')


def test_a_foreign_or_short_result_is_refused(tmp_path, refs):
    with pytest.raises(C.CheckError, match='not one this app reads'):
        C.judge(dump(tmp_path / 'v.zip', INTEL_ID, {'cpu': data(2)}, tool='cpu_estimates/2'), refs)
    first, rel = data(2)
    with pytest.raises(C.CheckError, match='not complete'):
        C.judge(dump(tmp_path / 's.zip', INTEL_ID, {'cpu': (first[:-4], rel)}), refs)
    (tmp_path / 'bad.zip').write_bytes(b'not a zip')
    with pytest.raises(C.CheckError, match='does not read'):
        C.judge(str(tmp_path / 'bad.zip'), refs)


def test_references_are_the_two_measured_cpus():
    assert sorted(cpuref.REFS) == ['amd', 'intel']
    assert C.maker(cpuref.REFS['amd']['vendor']) == 'amd' and '9800X3D' in cpuref.REFS['amd']['cpu']
    assert C.maker(cpuref.REFS['intel']['vendor']) == 'intel' and 'i5-10210U' in cpuref.REFS['intel']['cpu']
    for ref in cpuref.REFS.values():
        for insn in C.INSNS:
            assert len(ref[insn]['strong']) == 32
            assert len(base64.b64decode(''.join(ref[insn]['chunks']) if isinstance(ref[insn]['chunks'], tuple)
                                        else ref[insn]['chunks'])) == C.CHUNKS * C.DIGEST


@pytest.mark.skipif(not all(os.path.isfile(p) for p in DUMPS.values()), reason='the measured dumps are not on this PC')
def test_references_match_the_measured_dumps():
    with open(os.path.join(ROOT, 'overtime_roster', 'app', 'cpuref.py'), encoding='utf-8') as f:
        assert C.reference_module(DUMPS) == f.read(), 'run tools/build_cpuref.py'
    assert C.judge(DUMPS['amd'])['verdict'] == C.AMD
    assert C.judge(DUMPS['intel'])['verdict'] == C.INTEL


def test_progress_follows_the_runs():
    state = {}
    assert C.share('CPU: Intel(R) Core(TM) i7-14700KF', state) is None
    assert C.share('Hybrid CPU: 2 core types, one pass on each', state) is None
    assert C.share('  class0 vrcpps: 50%', state) == pytest.approx(0.125)
    assert C.share('  class0 vrsqrtps: 100%', state) == pytest.approx(0.5)
    assert C.share('  class1 vrcpps: 0%', state) == pytest.approx(0.5)
    assert C.share('  class1 vrsqrtps fingerprint 0123456789abcdef', state) is None
    assert C.share('  cpu vrcpps: 12%', {}) == pytest.approx(0.06)


class FakeProc:
    def __init__(self, lines, code=0, write=None, block=None):
        self.lines, self.code, self.write, self.block, self.killed = lines, code, write, block, False
        self.stdout = self._out()

    def _out(self):
        for line in self.lines:
            yield line + '\n'
        if self.block is not None:
            self.block.wait(5)

    def kill(self):
        self.killed = True
        if self.block is not None:
            self.block.set()

    def wait(self):
        if self.write:
            self.write()
        return -9 if self.killed else self.code


def test_run_reads_progress_and_finds_the_zip(tmp_path):
    out_dir, seen, args = tmp_path / 'result', [], {}
    (tmp_path / 'result').mkdir()
    (out_dir / 'old.txt').write_text('a left-over')

    def popen(cmd, **kw):
        args.update(cmd=cmd, **kw)
        return FakeProc(['CPU: Test', '  cpu vrcpps: 50%', '  cpu vrsqrtps: 100%', 'Done. Send this file: x'],
                        write=lambda: (out_dir / 'cpu-estimates-Test.zip').write_bytes(b'zip'))
    path, output = C.run('tool.exe', str(out_dir), seen.append, popen=popen)
    assert path == str(out_dir / 'cpu-estimates-Test.zip') and 'Done.' in output
    assert seen == [pytest.approx(0.25), pytest.approx(1.0)]
    assert args['cmd'] == ['tool.exe', '--out', str(out_dir), '--no-wait'] and not (out_dir / 'old.txt').exists()


@pytest.mark.parametrize('code, lines, said', [
    (2, ['This test needs Windows on a CPU with AVX.'], 'needs Windows on a CPU with AVX'),
    (1, ['Measuring...', "Failed: OSError('VirtualAlloc failed')"], "Failed: OSError('VirtualAlloc failed')"),
    (0, ['Done.'], 'wrote no result'),
])
def test_run_says_why_it_failed(tmp_path, code, lines, said):
    with pytest.raises(C.CheckError, match=said.replace('(', r'\(').replace(')', r'\)')):
        C.run('tool.exe', str(tmp_path / 'r'), popen=lambda cmd, **kw: FakeProc(lines, code))


def test_run_is_stopped_after_its_time(tmp_path):
    proc = FakeProc(['  cpu vrcpps: 10%'], block=threading.Event())
    with pytest.raises(C.CheckError, match='took too long'):
        C.run('tool.exe', str(tmp_path / 'r'), timeout=0.05, popen=lambda cmd, **kw: proc)
    assert proc.killed


def test_ensure_unpacks_the_published_exe(tmp_path, monkeypatch):
    monkeypatch.setenv('OVERTIME_ROSTER_HOME', str(tmp_path / 'home'))
    pack = tmp_path / packdownload.CPUTEST_PACK
    with zipfile.ZipFile(pack, 'w') as z:
        z.writestr(packdownload.CPUTEST_EXE, b'MZ the tool')
    packdownload.check_cputest(str(pack))
    answer = {'ok': True, 'message': ''}
    monkeypatch.setattr(packdownload, 'download', lambda names, cache, progress=None, cancelled=None:
                        [(names[0], answer['ok'], answer['message'])])
    monkeypatch.setattr(packdownload, 'located', lambda name, cache: (str(pack), 'sha') if pack.exists() else None)
    exe = C.ensure(str(tmp_path))
    assert exe == C.tool_exe() and open(exe, 'rb').read() == b'MZ the tool'
    answer.update(ok=False, message=packdownload.OFFLINE)
    assert C.ensure(str(tmp_path)) == exe                     # offline: the pack downloaded before
    answer.update(message=packdownload.NOT_OFFERED)
    with pytest.raises(C.CheckError, match='does not offer'):
        C.ensure(str(tmp_path))
    pack.unlink()
    answer.update(message=packdownload.OFFLINE)
    with pytest.raises(C.CheckError, match='does not answer'):
        C.ensure(str(tmp_path))


def test_the_pack_is_known_and_checked(tmp_path):
    assert packdownload.CPUTEST_PACK in packdownload.KNOWN and packdownload.CPUTEST_PACK not in packdownload.PACKS
    assert packdownload.CHECKS[packdownload.CPUTEST_PACK] is packdownload.check_cputest
    bad = tmp_path / 'b.zip'
    with zipfile.ZipFile(bad, 'w') as z:
        z.writestr(packdownload.CPUTEST_EXE, b'not a program')
    with pytest.raises(Exception, match='not a Windows program'):
        packdownload.check_cputest(str(bad))


def test_the_report_carries_the_zip_as_it_is(tmp_path, refs):
    path = dump(tmp_path / 'cpu-estimates-Test.zip', INTEL_ID, {'cpu': data(2)}, compression=zipfile.ZIP_LZMA)
    result = C.judge(path, refs)
    blob = open(path, 'rb').read()
    meta = C.report_meta(result)
    assert all(len(k) <= CR.META_KEY for k in meta) and meta['cpu_verdict'] == C.INTEL
    # a name that a scrub would replace anywhere in a log stays in the attachment
    body = CR.build('cpu', 'CPU: Test\nDone. jdoe', meta, extra=[('jdoe', '<user>')],
                    attach=(os.path.basename(path), blob))
    doc = json.loads(gzip.decompress(body))
    assert doc['log'].rstrip().endswith('<user>') and base64.b64decode(doc['attach']['b64']) == blob
    assert doc['attach']['name'] == 'cpu-estimates-Test.zip' and doc['meta']['cpu_runs'].startswith('cpu like=intel')
    # an LZMA zip hardly shrinks again: a CPU with three core types (about 1.2 MB, 3 x the 415 KB i5 result) still
    # goes, with the log cut to make room; one that cannot fit is refused here, not by the server's 413
    three = CR.build('cpu', 'line\n' * 30000, meta, attach=('three.zip', os.urandom(1_250_000)))
    assert len(three) <= CR.MAX_BODY
    for big in (os.urandom(CR.MAX_BODY - 1000), bytes(CR.MAX_BODY + 1)):
        with pytest.raises(CR.ReportError, match='too big'):
            CR.build('cpu', '', meta, attach=('big.zip', big))
    reports = pytest.importorskip('overtime_server.reports')
    assert reports.parse(body)['attach']['name'] == 'cpu-estimates-Test.zip'
    assert len(reports.parse(three)['attach']['b64']) > 1_600_000
