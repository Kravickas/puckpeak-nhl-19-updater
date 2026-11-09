"""What this PC's `vrcpps` and `vrsqrtps` return for every float input, in one small file.

NHL 19 online desyncs between Intel and AMD PCs: the game normalises vectors with these two estimate instructions, and
each CPU design returns slightly different low bits (docs/notes/cross-vendor-desync.md). shadPS4 corrects Intel results
with tables measured on one Intel (Skylake) and one AMD (Zen 2). Run this on two PCs and compare the files with
`tools/cpu_estimates_compare.py`, which says whether the outputs match, raw or with shadPS4's correction.

Double-click friendly: it writes `cpu-estimates-<cpu>.zip` next to itself (or in the home folder) and waits for Enter.
Windows only, needs AVX (every CPU that runs shadPS4 has it). About a minute.

The file (zip):
- `info.json`: tool version, CPU name and identifier, Windows version, and one fingerprint per run and instruction.
- `<run>/<insn>_first.bin`: the output for the first input of each bucket of 2^11 inputs, little-endian u32, 2^21
  values. A bucket is the input's bits >> 11, the index shadPS4 uses for its correction.
- `<run>/<insn>_rel.bin`: a 16-byte blake2b per chunk of 2^22 inputs (1024 chunks) over each output XOR its bucket's
  first output. If two CPUs differ by a constant XOR inside every bucket (what shadPS4's correction assumes), these
  match and the `first` values give that XOR.
A run is one pass on one core type: hybrid CPUs (performance and efficiency cores) get one run per core type.

Build the standalone exe (about 8 MB, stdlib only):
  .venv-build\\Scripts\\pyinstaller --onefile --console --name cpu-estimates --distpath dist\\cpu-estimates tools\\cpu_estimates.py
"""
import argparse
import ctypes
import hashlib
import json
import os
import platform
import re
import struct
import sys
import time
import zipfile

TOOL = 'cpu_estimates/1'
INSNS = {'vrcpps': 0x53, 'vrsqrtps': 0x52}   # VEX.128.0F opcode byte
BUCKET = 1 << 11                              # inputs per bucket (shadPS4 indexes by input >> 11)
CHUNK = 1 << 22                               # inputs per call and per rel digest
CHUNKS = 1 << 10                              # CHUNK * CHUNKS = every 32-bit input

# fill(start u32 in ecx, count in rdx (multiple of 4, > 0), out in r8, consts in r9 -> {0,1,2,3, 4,4,4,4}):
# out[i] = estimate(bits start + i)
_FILL = ('c5f96ec1'        # vmovd    xmm0, ecx
         'c5f970c000'      # vpshufd  xmm0, xmm0, 0
         'c4c179fe01'      # vpaddd   xmm0, xmm0, [r9]
         'c4c17a6f5110'    # vmovdqu  xmm2, [r9 + 16]
         'c5f8{op:02x}c8'  # loop: vrcpps/vrsqrtps xmm1, xmm0
         'c4c1781108'      # vmovups  [r8], xmm1
         'c5f9fec2'        # vpaddd   xmm0, xmm0, xmm2
         '4983c010'        # add      r8, 16
         '4883ea04'        # sub      rdx, 4
         '75e9'            # jnz      loop
         'c3')             # ret
# rel(buf in rcx, buckets in rdx > 0): each value XOR its bucket's first value (the first becomes 0)
_REL = ('c4e2791809'       # outer: vbroadcastss xmm1, [rcx]
        'b800020000'       # mov      eax, 512 (BUCKET / 4)
        'c5f05701'         # inner: vxorps xmm0, xmm1, [rcx]
        'c5f81101'         # vmovups  [rcx], xmm0
        '4883c110'         # add      rcx, 16
        'ffc8'             # dec      eax
        '75f0'             # jnz      inner
        '48ffca'           # dec      rdx
        '75e1'             # jnz      outer
        'c3')              # ret


def kernel_bytes():
    """{name: machine code} for the tests and the loader."""
    out = {name: bytes.fromhex(_FILL.format(op=op)) for name, op in INSNS.items()}
    out['rel'] = bytes.fromhex(_REL)
    return out


class Kernels:
    """The machine code above in an executable page (written, then made read+execute)."""

    def __init__(self):
        k32 = self.k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.VirtualAlloc.restype = ctypes.c_void_p
        k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
        k32.VirtualProtect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        k32.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
        k32.FlushInstructionCache.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        code = kernel_bytes()
        blob, offsets = b'', {}
        for name, b in code.items():
            offsets[name] = len(blob)
            blob += b + b'\xcc' * (-len(b) % 64)
        self.size = len(blob)
        self.base = k32.VirtualAlloc(None, self.size, 0x3000, 0x04)   # MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
        if not self.base:
            raise OSError(ctypes.get_last_error(), 'VirtualAlloc failed')
        ctypes.memmove(self.base, blob, len(blob))
        old = ctypes.c_uint32()
        if not k32.VirtualProtect(self.base, self.size, 0x20, ctypes.byref(old)):   # PAGE_EXECUTE_READ
            raise OSError(ctypes.get_last_error(), 'VirtualProtect failed')
        k32.FlushInstructionCache(k32.GetCurrentProcess(), self.base, self.size)
        fill_t = ctypes.CFUNCTYPE(None, ctypes.c_uint32, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_void_p)
        rel_t = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint64)
        self.fill = {name: fill_t(self.base + offsets[name]) for name in INSNS}
        self.rel = rel_t(self.base + offsets['rel'])
        self._consts = (ctypes.c_uint32 * 8)(0, 1, 2, 3, 4, 4, 4, 4)

    def estimates(self, insn, start, count, buf=None):
        """bytearray of `count` u32 outputs of `insn` for the input bits start, start+1, ... (count % 4 == 0)."""
        if count <= 0 or count % 4 or start < 0 or start + count > 1 << 32:
            raise ValueError('count must be a positive multiple of 4 inside the 32-bit range')
        buf = buf if buf is not None else bytearray(count * 4)
        cbuf = (ctypes.c_char * len(buf)).from_buffer(buf)
        self.fill[insn](start, count, ctypes.addressof(cbuf), ctypes.addressof(self._consts))
        del cbuf
        return buf

    def relative(self, buf):
        """XOR every value in buf (whole buckets) with its bucket's first value, in place."""
        if not buf or len(buf) % (BUCKET * 4):
            raise ValueError('buf must hold whole buckets')
        cbuf = (ctypes.c_char * len(buf)).from_buffer(buf)
        self.rel(ctypes.addressof(cbuf), len(buf) // (BUCKET * 4))
        del cbuf

    def close(self):
        if self.base:
            self.k32.VirtualFree(self.base, 0, 0x8000)   # MEM_RELEASE
            self.base = None


def measure(kernels, insn, chunks=CHUNKS, progress=None):
    """(first bytes, rel digests) for the inputs 0 .. chunks * CHUNK - 1."""
    buf = bytearray(CHUNK * 4)
    view = memoryview(buf)
    words = view.cast('I')
    first, rel = bytearray(), bytearray()
    for c in range(chunks):
        kernels.estimates(insn, c * CHUNK, CHUNK, buf)
        first += words[::BUCKET].tobytes()
        kernels.relative(buf)
        rel += hashlib.blake2b(view, digest_size=16).digest()
        if progress:
            progress(c + 1, chunks)
    words.release()
    view.release()
    return bytes(first), bytes(rel)


def fingerprint(first, rel):
    return hashlib.blake2b(first + rel, digest_size=8).hexdigest()


def cpu_info():
    info = {'name': platform.processor(), 'vendor': '', 'identifier': platform.processor()}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as k:
            for key, field in (('ProcessorNameString', 'name'), ('VendorIdentifier', 'vendor'), ('Identifier', 'identifier')):
                try:
                    info[field] = str(winreg.QueryValueEx(k, key)[0]).strip()
                except OSError:
                    pass
    except (ImportError, OSError):
        pass
    return info


def core_types():
    """[(efficiency class, logical processor)] one per core type in processor group 0, or [] when unknown.
    Hybrid CPUs report two classes (higher = performance cores)."""
    try:
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        get = k32.GetSystemCpuSetInformation
        get.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p, ctypes.c_uint32]
        n = ctypes.c_uint32(0)
        get(None, 0, ctypes.byref(n), k32.GetCurrentProcess(), 0)
        if not n.value:
            return []
        raw = ctypes.create_string_buffer(n.value)
        if not get(raw, n.value, ctypes.byref(n), k32.GetCurrentProcess(), 0):
            return []
        data, off, seen = raw.raw[:n.value], 0, {}
        while off + 20 <= len(data):
            size, kind = struct.unpack_from('<II', data, off)
            if size < 20:
                break
            if kind == 0:   # CpuSetInformation: Id, Group, LogicalProcessorIndex, CoreIndex, LLC, Numa, EfficiencyClass
                group, = struct.unpack_from('<H', data, off + 12)
                lp, eff = data[off + 14], data[off + 18]
                if group == 0 and lp < 64:
                    seen.setdefault(eff, lp)
            off += size
        return sorted(seen.items())
    except (AttributeError, OSError):
        return []


def pin(lp):
    """Pin this thread to logical processor lp (None: any). Returns the old mask or None."""
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.GetCurrentThread.restype = ctypes.c_void_p
    k32.SetThreadAffinityMask.restype = ctypes.c_size_t
    k32.SetThreadAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    if lp is None:
        return None
    return k32.SetThreadAffinityMask(k32.GetCurrentThread(), 1 << lp) or None


def has_avx():
    try:
        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(39))   # PF_AVX_INSTRUCTIONS_AVAILABLE
    except (AttributeError, OSError):
        return False


def file_name(cpu_name):
    s = re.sub(r'\((R|TM)\)|\bCPU\b|@.*$', ' ', cpu_name or 'cpu')
    s = re.sub(r'[^A-Za-z0-9]+', '-', s).strip('-')[:48] or 'cpu'
    return f'cpu-estimates-{s}.zip'


def write_dump(path, info, results):
    """results: {run label: {insn: (first, rel)}}."""
    tmp = path + '.part'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_LZMA) as z:
        z.writestr('info.json', json.dumps(info, indent=1))
        for label, insns in results.items():
            for insn, (first, rel) in insns.items():
                z.writestr(f'{label}/{insn}_first.bin', first)
                z.writestr(f'{label}/{insn}_rel.bin', rel)
    os.replace(tmp, path)


def run(out_dir, chunks=CHUNKS, say=print):
    """Measure on every core type and write the zip. Returns its path."""
    cpu = cpu_info()
    say(f'CPU: {cpu["name"]} ({cpu["identifier"]})')
    types = core_types()
    runs = [(f'class{eff}', eff, lp) for eff, lp in types] if len(types) > 1 else [('cpu', None, None)]
    if len(runs) > 1:
        say(f'Hybrid CPU: {len(runs)} core types, one pass on each')
    kernels = Kernels()
    t0 = time.time()
    results, run_info = {}, []
    try:
        for label, eff, lp in runs:
            old = pin(lp)
            try:
                results[label], prints = {}, {}
                for insn in INSNS:
                    def progress(done, total, insn=insn, label=label):
                        if done % 128 == 0 or done == total:
                            say(f'  {label} {insn}: {done * 100 // total}%')
                    first, rel = measure(kernels, insn, chunks, progress)
                    results[label][insn] = (first, rel)
                    prints[insn] = fingerprint(first, rel)
                    say(f'  {label} {insn} fingerprint {prints[insn]}')
            finally:
                if old:
                    pin_mask(old)
            run_info.append({'label': label, 'efficiency_class': eff, 'logical_processor': lp, 'fingerprints': prints})
    finally:
        kernels.close()
    info = {'tool': TOOL, 'cpu': cpu, 'platform': platform.platform(), 'chunks': chunks,
            'seconds': round(time.time() - t0, 1), 'runs': run_info}
    path = os.path.join(out_dir, file_name(cpu['name']))
    write_dump(path, info, results)
    return path


def pin_mask(mask):
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.GetCurrentThread.restype = ctypes.c_void_p
    k32.SetThreadAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    k32.SetThreadAffinityMask(k32.GetCurrentThread(), mask)


def default_out_dir():
    here = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    for d in (here, os.path.expanduser('~')):
        try:
            probe = os.path.join(d, '.cpu-estimates-probe')
            with open(probe, 'w'):
                pass
            os.remove(probe)
            return d
        except OSError:
            continue
    return os.getcwd()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', help='folder for the zip (default: next to this program)')
    ap.add_argument('--chunks', type=int, default=CHUNKS, help=argparse.SUPPRESS)
    ap.add_argument('--no-wait', action='store_true', help='exit without waiting for Enter')
    a = ap.parse_args(argv)
    try:                # each progress line goes out at once, also into a pipe (the app's Check my CPU reads them)
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    wait = getattr(sys, 'frozen', False) and not a.no_wait
    code = 0
    try:
        if os.name != 'nt' or not has_avx():
            print('This test needs Windows on a CPU with AVX.')
            code = 2
        else:
            print('Measuring this CPU\'s estimate instructions (about a minute)...')
            path = os.path.abspath(run(a.out or default_out_dir(), max(1, min(CHUNKS, a.chunks))))
            print(f'\nDone. Send this file: {path}')
    except Exception as e:   # noqa: BLE001 - a double-clicked console should say what broke
        print(f'\nFailed: {e!r}')
        code = 1
    if wait:
        input('\nPress Enter to close.')
    return code


if __name__ == '__main__':
    sys.exit(main())
