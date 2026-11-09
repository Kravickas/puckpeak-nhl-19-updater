"""Check my CPU (0.81.0 WP6, Multiplayer > Advanced): does this PC's `vrcpps`/`vrsqrtps` math match a CPU proven to
play in step? (docs/notes/cross-vendor-desync.md, "Check my CPU").

The measuring is tools/cpu_estimates.py built as an exe (packaging/cpu_pack.ps1), published as the pack
packdownload.CPUTEST_PACK and pinned by its sha256 in latest.json like Boost's shadPS4; the app never runs generated
machine code itself (owner, 2026-11-09: no hidden CPU check). The button downloads the pack on its first press, unpacks
the exe into the app's folder, runs it (about a minute, one more on a hybrid CPU) and judges the zip it writes:

- 'amd': an AMD CPU whose results equal the AMD reference (Ryzen 7 9800X3D, Zen 5).
- 'intel_proven': an Intel CPU whose results equal the tested Intel (Core i5-10210U); shadPS4's correction of that
  CPU gives the AMD reference's results for every input that is a number (measured), so this one's does too.
- 'mixed': the core types of a hybrid CPU disagree with each other (the game's threads move between them).
- 'unknown': anything else, also a reference's results on the other maker's CPU. Please send.

A result is compared by digests (chunk_digests): per instruction and per chunk of 2^22 inputs, the first output of
each bucket that is a number plus the chunk's in-bucket digest. NaN inputs are left out (the correction tables do not
cover them and the game normalises vectors of numbers). The references (cpuref.py) are the digests of the two
measured dumps, written by tools/build_cpuref.py. Sending puts the zip in a report (reason 'cpu', crashreport.build's
attachment), after a yes on the page. Standard library only.
"""
import base64
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import zipfile

from . import packdownload, paths

PACK = packdownload.CPUTEST_PACK
EXE = packdownload.CPUTEST_EXE
TOOL = 'cpu_estimates/1'
INSNS = ('vrcpps', 'vrsqrtps')
CHUNKS = 1 << 10                # chunks of 2^22 inputs
PER_CHUNK = 1 << 11             # buckets (2^11 inputs each) per chunk
FIRST_BYTES = 4 << 21           # one u32 per bucket
REL_BYTES = 16 * CHUNKS         # one 16-byte digest per chunk
DIGEST = 4                      # bytes per chunk digest in the references
TIMEOUT = 600                   # seconds before a run is stopped (a slow hybrid laptop takes about two minutes)

AMD, INTEL, MIXED, UNKNOWN = 'amd', 'intel_proven', 'mixed', 'unknown'
REFERENCES = {'amd': AMD, 'intel': INTEL}       # cpuref.REFS key -> the verdict when the maker matches too
GOOD = (AMD, INTEL)

HYBRID = re.compile(r'Hybrid CPU: (\d+) core types')
STEP = re.compile(r'^\s*(\S+) (' + '|'.join(INSNS) + r'): (\d+)%\s*$')


class CheckError(RuntimeError):
    pass


# --- digests --------------------------------------------------------------------------------------------------------
def nan_chunk(c):
    """Chunk c holds inputs whose exponent is all ones (infinities and NaNs)."""
    return (c >> 1) & 0xff == 0xff


def chunk_bytes(first, rel, c):
    """What counts of chunk c: its buckets' first outputs and its in-bucket digest; in a NaN chunk only the bucket of
    the infinity (the first bucket of an even chunk; a NaN bucket is (b >> 12) & 0xff == 0xff and b & 0xfff)."""
    at = c * PER_CHUNK * 4
    if nan_chunk(c):
        return first[at:at + 4] if c % 2 == 0 else b''
    return first[at:at + PER_CHUNK * 4] + rel[c * 16:(c + 1) * 16]


def chunk_digests(first, rel):
    """(DIGEST bytes per chunk, joined; a 32-hex strong digest of every chunk) of one run's one instruction."""
    if len(first) != FIRST_BYTES or len(rel) != REL_BYTES:
        raise CheckError('The CPU check result is not complete.')
    per, strong = bytearray(), hashlib.blake2b(digest_size=16)
    for c in range(CHUNKS):
        data = chunk_bytes(first, rel, c)
        per += hashlib.blake2b(data, digest_size=DIGEST).digest()
        strong.update(data)
    return bytes(per), strong.hexdigest()


def read_dump(path):
    """(info, {run label: {insn: (chunk digests, strong)}}) of a cpu_estimates zip. CheckError when it does not read."""
    try:
        with zipfile.ZipFile(path) as z:
            info = json.loads(z.read('info.json').decode('utf-8'))
            if not isinstance(info, dict) or info.get('tool') != TOOL or not isinstance(info.get('runs'), list) \
                    or not info['runs']:
                raise CheckError('The CPU check result is not one this app reads.')
            runs = {}
            for run in info['runs']:
                label = str(run.get('label') or '') if isinstance(run, dict) else ''
                if not label or label in runs:
                    raise CheckError('The CPU check result is not one this app reads.')
                runs[label] = {insn: chunk_digests(z.read(f'{label}/{insn}_first.bin'), z.read(f'{label}/{insn}_rel.bin'))
                               for insn in INSNS}
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as err:
        raise CheckError(f'The CPU check result does not read ({err}).') from err
    return info, runs


def maker(vendor):
    v = (vendor or '').lower()
    return 'amd' if 'amd' in v else 'intel' if 'intel' in v else 'other'


def _refs():
    from . import cpuref
    return cpuref.REFS


def judge(path, refs=None):
    """The verdict of a cpu_estimates zip: {'verdict', 'cpu', 'vendor', 'identifier', 'seconds', 'runs': [{'label',
    'efficiency_class', 'like' (a refs key or None), 'differs': {ref: chunks}, 'prints'}], 'core_types_agree'}."""
    refs = refs if refs is not None else _refs()
    info, runs = read_dump(path)
    cpu = info.get('cpu') if isinstance(info.get('cpu'), dict) else {}
    out = []
    for run in info['runs']:
        label = str(run['label'])
        got = runs[label]
        like, differs = None, {}
        for name, ref in refs.items():
            want = {insn: (base64.b64decode(ref[insn]['chunks']), ref[insn]['strong']) for insn in INSNS}
            differs[name] = sum(1 for insn in INSNS for c in range(CHUNKS)
                                if got[insn][0][c * DIGEST:(c + 1) * DIGEST] != want[insn][0][c * DIGEST:(c + 1) * DIGEST])
            if all(got[insn][1] == want[insn][1] for insn in INSNS):
                like = name
        prints = run.get('fingerprints') if isinstance(run.get('fingerprints'), dict) else {}
        out.append({'label': label, 'efficiency_class': run.get('efficiency_class'), 'like': like, 'differs': differs,
                    'prints': {k: str(v)[:32] for k, v in prints.items() if k in INSNS},
                    'strong': tuple(got[insn][1] for insn in INSNS)})
    agree = len({r['strong'] for r in out}) == 1
    vendor = maker(cpu.get('vendor'))
    likes = {r['like'] for r in out}
    if not agree:
        verdict = MIXED
    elif len(likes) == 1 and next(iter(likes)) == vendor and vendor in REFERENCES:
        verdict = REFERENCES[vendor]
    else:
        verdict = UNKNOWN
    for r in out:
        del r['strong']
    return {'verdict': verdict, 'cpu': str(cpu.get('name') or '')[:80], 'vendor': str(cpu.get('vendor') or '')[:40],
            'identifier': str(cpu.get('identifier') or '')[:80], 'seconds': info.get('seconds'), 'runs': out,
            'core_types_agree': agree}


def text(result):
    """(line, tone, title) for the page."""
    v = result['verdict']
    if v == AMD:
        line, tone = 'Matches the AMD reference: it plays in step with other PCs.', 'good'
    elif v == INTEL:
        line, tone = ("Matches the tested Intel, whose shadPS4 correction is proven: it plays in step with other "
                      'PCs.'), 'good'
    elif v == MIXED:
        line, tone = ('Its core types give different results, so a match can drift out of step. Please send the '
                      'result.'), 'bad'
    elif any(r['like'] for r in result['runs']):
        line, tone = ("Results like the other maker's reference, which shadPS4 does not expect on this CPU. Please "
                      'send them so we can check it.'), 'caution'
    else:
        line, tone = 'Results not seen before. Please send them so we can check this CPU.', 'caution'
    total = CHUNKS * len(INSNS)
    parts = []
    for r in result['runs']:
        name = f"{r['label']}: " if len(result['runs']) > 1 else ''
        parts.append(name + ', '.join(f'{total - n} of {total} parts like the {ref.upper() if ref == "amd" else ref.title()} '
                                      'reference' for ref, n in r['differs'].items()))
    return line, tone, '; '.join(parts)


def reference(path):
    """cpuref.REFS' entry for one measured dump: {'cpu', 'vendor', insn: {'strong', 'chunks' (base64)}}."""
    info, runs = read_dump(path)
    if len(runs) != 1:
        raise CheckError('a reference is one run of one core type')
    (got,) = runs.values()
    cpu = info.get('cpu') or {}
    return {'cpu': cpu.get('name', ''), 'vendor': cpu.get('vendor', ''),
            **{insn: {'strong': got[insn][1], 'chunks': base64.b64encode(got[insn][0]).decode('ascii')}
               for insn in INSNS}}


def reference_module(dumps):
    """The text of cpuref.py for {name: dump path} (deterministic: tools/build_cpuref.py writes it, a test compares)."""
    lines = ['"""The Check my CPU references (cpucheck.py): digests of what two measured CPUs\' vrcpps and vrsqrtps return',
             '(hardware data from tools/cpu_estimates.py, no game data). Written by tools/build_cpuref.py; do not edit."""',
             'REFS = {']
    for name in sorted(dumps):
        ref = reference(dumps[name])
        lines.append(f'    {name!r}: {{')
        lines.append(f"        'cpu': {ref['cpu']!r},")
        lines.append(f"        'vendor': {ref['vendor']!r},")
        for insn in INSNS:
            lines.append(f'        {insn!r}: {{')
            lines.append(f"            'strong': {ref[insn]['strong']!r},")
            lines.append("            'chunks': (")
            b64 = ref[insn]['chunks']
            lines.extend(f'                {b64[i:i + 96]!r}' for i in range(0, len(b64), 96))
            lines.append('            ),')
            lines.append('        },')
        lines.append('    },')
    lines.append('}')
    return '\n'.join(lines) + '\n'


# --- running the tool -----------------------------------------------------------------------------------------------
def tool_dir():
    return paths.app_dir('cpucheck')


def tool_exe():
    """Where the unpacked exe is (the folder is not made here: the page asks this on every look)."""
    return os.path.join(paths.app_home(), 'cpucheck', EXE)


def result_dir():
    return os.path.join(tool_dir(), 'result')


def ensure(cache_dir, progress=None, cancelled=None):
    """The tool's exe, its pack downloaded (and checked) when it is not here as published. Offline, a pack downloaded
    before is used. CheckError with the text to show otherwise."""
    (_name, ok, message), = packdownload.download([PACK], cache_dir, progress, cancelled=cancelled)
    found = packdownload.located(PACK, cache_dir)
    if not found or (not ok and message != packdownload.OFFLINE):
        raise CheckError(message if not ok else 'The CPU check did not download.')
    pack, _sha = found
    os.makedirs(tool_dir(), exist_ok=True)
    exe = tool_exe()
    part = exe + '.part'
    try:
        with zipfile.ZipFile(pack) as z, z.open(packdownload.exe_entry(z, EXE)) as src, open(part, 'wb') as out:
            shutil.copyfileobj(src, out, 1 << 20)
        os.replace(part, exe)
    except (zipfile.BadZipFile, OSError, ValueError) as err:
        raise CheckError(f'The CPU check does not unpack: {err}') from err
    finally:
        if os.path.exists(part):
            os.remove(part)
    return exe


def share(line, state):
    """How far the run is (0..1) after one line of its output, or None; `state` keeps the runs seen."""
    m = HYBRID.search(line)
    if m:
        state['runs'] = max(1, int(m.group(1)))
        return None
    m = STEP.match(line)
    if not m:
        return None
    labels = state.setdefault('labels', [])
    if m.group(1) not in labels:
        labels.append(m.group(1))
    runs = max(state.get('runs', 1), len(labels))
    phase = labels.index(m.group(1)) * len(INSNS) + INSNS.index(m.group(2))
    return min(1.0, (phase + int(m.group(3)) / 100) / (runs * len(INSNS)))


def run(exe, out_dir=None, progress=None, timeout=TIMEOUT, popen=subprocess.Popen):
    """Run the tool into a fresh `out_dir`; (the zip it wrote, its output). progress(share 0..1). CheckError with the
    text to show when it fails or takes longer than `timeout` seconds."""
    out_dir = out_dir or result_dir()
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)
    try:
        proc = popen([exe, '--out', out_dir, '--no-wait'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, cwd=out_dir, text=True, encoding='utf-8', errors='replace',
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError as err:
        raise CheckError(f'The CPU check did not start ({err.strerror or err}). Your antivirus may have stopped it.') \
            from err
    stopped = []

    def stop():
        stopped.append(True)
        proc.kill()
    timer = threading.Timer(timeout, stop)
    timer.daemon = True
    timer.start()
    lines, state = [], {}
    try:
        for raw in proc.stdout:
            line = raw.rstrip()
            lines.append(line)
            part = share(line, state)
            if part is not None and progress:
                progress(part)
        code = proc.wait()
    finally:
        timer.cancel()
    output = '\n'.join(lines)
    if stopped:
        raise CheckError('The CPU check took too long and was stopped.')
    if code == 2:
        raise CheckError('The CPU check needs Windows on a CPU with AVX.')
    if code:
        failed = next((x.strip() for x in reversed(lines) if x.strip().startswith('Failed:')), '')
        raise CheckError(f'The CPU check stopped ({failed or f"exit code {code}"}).')
    found = sorted(p for p in glob.glob(os.path.join(out_dir, 'cpu-estimates-*.zip')))
    if len(found) != 1:
        raise CheckError('The CPU check wrote no result.')
    return found[0], output


# --- the report -----------------------------------------------------------------------------------------------------
def report_meta(result):
    """The searchable facts of one check, for a report's meta (crashreport caps each value)."""
    runs = result['runs']
    return {'cpu_verdict': result['verdict'], 'cpu_name': result['cpu'], 'cpu_vendor_id': result['vendor'],
            'cpu_identifier': result['identifier'], 'cpu_seconds': str(result.get('seconds')),
            'cpu_core_types': len(runs), 'cpu_core_types_agree': result['core_types_agree'],
            'cpu_runs': '; '.join(f"{r['label']} like={r['like'] or '-'} "
                                  + ' '.join(f'{k}_differs={v}' for k, v in r['differs'].items()) for r in runs),
            'cpu_prints': '; '.join(f"{r['label']} " + ' '.join(f'{k}={v}' for k, v in r['prints'].items())
                                    for r in runs)}
