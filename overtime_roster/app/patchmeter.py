"""Patch's progress bar: one share of the whole Patch that grows with the time the work takes, not with its steps.

Patch is a row of steps of very different length: a few seconds of checks, minutes of jerseys made on this PC the first
time, gigabytes of archives written and read back. A share per step (0.5, 0.6, 0.62, 0.65...) stood still for minutes
at the long ones. Here each step is planned as an amount of work in its own unit (bytes copied, written or checked;
texture bytes made, weighed by kitcompose.weight; seconds for the short steps that have no unit) and each unit has a
speed in seconds, so the plan is a time, and 1 % of the bar is 1 % of that time:

- Before the long steps run, Patch measures them (kit_jobs, clubart_work, art_layer_work, overlay.apply's plan): the
  textures to make, the bytes to check and write. Nothing is read for it but tables and pack lists.
- Each step reports its units as they are done; a step without units creeps on with its expected time, slower near
  its end (it never stands still and never runs past its share).
- When a step turns out larger or smaller than planned (its plan arrives, a pack is kept, a step is skipped) the share
  shown stays where it is and the rest of the bar is spread over the work still to do: the bar never jumps back or
  ahead, it only goes faster or slower.
- A step that runs a few seconds gives its own speed: the rest of the bar is spread again with it (a first Patch's
  guess is put right while it runs).
- The speeds are learned: after each Patch the time every kind of work took per unit on this PC is kept
  (patch_speed.json in the app's cache, half the old value and half the new), so the next Patch's 1 % is this PC's.
  The first Patch on a PC uses SPEEDS (measured on one core, 2026-11-12, see kitcompose.STEP_WORK); only their ratios
  count, and a wrong ratio only makes one stretch of the bar faster or slower than the rest.

Thread-safe: verify reports from several threads; a ticker thread pushes the share while a step without units runs.
"""
import json
import math
import os
import threading
import time

from overtime_core import durable, workers

FILE = 'patch_speed.json'
FORMAT = 1
CAP = 0.99          # the bar is full only when Patch is done
MEASURE_AFTER = 3.0     # seconds a step runs before its own speed is taken (a pool's start is not the speed)
MEASURE_SHARE = 0.02    # and the share of its units done by then
CREEP_KNEE = 0.8    # a step without units runs on its expected time up to this share of its own, then slows down
MB = 1 << 20


def _cores():
    return max(1, workers.count())


def default_speeds():
    """Seconds per unit of each kind of work on a PC Patch has not run on yet. Byte kinds: a disk of about 400 MB/s.
    Texture kinds: 3 s per MB of BCn made on one core (kitcompose.STEP_WORK's measurements, between flat colour and
    noise), the jerseys and the club logos on every core (processes). time:* kinds: seconds."""
    cores = _cores()
    return {'copy': 2.5e-9, 'write': 3.0e-9, 'verify': 1.5e-9, 'check': 2.5e-9,
            'kits': 3.0 / MB / cores, 'clubart': 3.0 / MB / cores,
            'time:prepare': 0.5, 'time:texts': 2.0, 'time:clean': 4.0, 'time:scan': 3.0, 'time:roster_quick': 1.0,
            'time:roster_update': 20.0, 'time:roster_fresh': 60.0, 'time:build': 5.0, 'time:install': 1.0,
            'time:look': 1.0}


def load(cache_dir):
    """{'speeds': {kind: seconds per unit}, 'last': {phase: units}}: the defaults with what this PC's Patches
    learned over them. A missing or broken file gives the defaults."""
    out = {'speeds': default_speeds(), 'last': {}}
    try:
        with open(os.path.join(cache_dir, FILE), encoding='utf-8') as f:
            got = json.load(f)
    except (OSError, ValueError, TypeError):
        return out
    if not isinstance(got, dict) or got.get('format') != FORMAT:
        return out
    for key, box in (('speeds', out['speeds']), ('last', out['last'])):
        for k, v in (got.get(key) or {}).items():
            if isinstance(k, str) and isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 \
                    and (key == 'last' or v > 0):
                box[k] = float(v)
    return out


def save(cache_dir, speeds, last):
    """Keep the speeds and the last units (durable.replace; a failure loses only the learning)."""
    if not cache_dir:
        return
    try:
        os.makedirs(cache_dir, exist_ok=True)
        tmp = os.path.join(cache_dir, FILE + '.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'format': FORMAT, 'speeds': speeds, 'last': last}, f, indent=1, sort_keys=True)
        durable.replace(tmp, os.path.join(cache_dir, FILE))
    except OSError:
        pass


def patched_text(n):
    """The Help bar's count beside the %: "Patched 850 MB", "Patched 10.3 GB" (2^30 bytes, as the app's other sizes)."""
    return f'Patched {n / 2**30:.1f} GB' if n >= 2**30 else f'Patched {int(n / MB)} MB'


def _creep(x):
    """The share of a step without units after `x` of its expected time: x up to CREEP_KNEE, then nearer and nearer
    to 1 (as fast at the knee, then slower as 1 / x: a step that takes ten times its time still moves; never 1)."""
    if x <= CREEP_KNEE:
        return max(0.0, x)
    rest = 1 - CREEP_KNEE
    return 1 - rest / (1 + (x - CREEP_KNEE) / rest)


class _Phase:
    __slots__ = ('key', 'kind', 'units', 'done', 'state', 't0', 't1', 'text', 'per_unit')

    def __init__(self, key, kind, units, text, writes=False):
        self.key, self.kind, self.units, self.text = key, kind, max(0.0, float(units)), text
        self.done, self.state, self.t0, self.t1 = 0.0, 'todo', None, None
        self.per_unit = 1.0 if writes else None     # bytes the patch writes per unit done (None: it writes none)

    @property
    def timed(self):
        return self.kind.startswith('time:')


class Meter:
    """The plan of one Patch and the share done. `say(text, share)` shows it (run_job's step); `speeds`: load()'s."""

    def __init__(self, say, speeds=None, clock=time.monotonic, interval=0.2, amount=None):
        """`amount(bytes)`: the text of the bytes the patch has written so far (patched_text), said beside the share:
        say(text, share, amount); without it say(text, share)."""
        self._say, self._clock, self._interval, self._amount = say, clock, interval, amount
        self.speeds = dict(speeds or default_speeds())
        self._known = dict(self.speeds)     # the speeds Patch started with: learned() blends into these
        self._fixed = {}                    # kind: when its speed was last set from the step running (once a second)
        self._phases = {}           # key: _Phase, in plan order
        self._lock = threading.RLock()
        self._anchor = (0.0, 0.0, None)     # (share shown, work credited, work left) when the plan last changed
        self._shown = 0.0
        self._text = ''
        self._pushed = (None, None, 0.0, None)  # (text, share, when, amount) last said
        self._stop = threading.Event()
        self._thread = None
        self.finished = False

    # --- the plan ---------------------------------------------------------------------------------------------------
    def plan(self, key, kind, units=1.0, text='', writes=False):
        """Add the step `key` (or replace its plan): `units` of `kind` (time:* kinds: 1). `writes`: what the step does
        is written by the patch, a byte a unit (else written_bytes), and counts in the bytes patched."""
        with self._lock:
            self._change(lambda: self._phases.__setitem__(key, _Phase(key, kind, units, text, writes)))

    def written_bytes(self, key, total):
        """The bytes a step whose units are not bytes (a jersey family: weighed texture bytes) writes when all is done:
        each unit done counts its share of them."""
        with self._lock:
            ph = self._phases.get(key)
            if ph is not None and ph.per_unit is not None:
                ph.per_unit = total / ph.units if ph.units else 0.0

    def written(self):
        """The bytes the patch has written so far (the steps planned with `writes`)."""
        with self._lock:
            return sum(min(ph.done, ph.units) * ph.per_unit for ph in self._phases.values()
                       if ph.per_unit is not None)

    def resize(self, key, units):
        """The step's real size, known now."""
        with self._lock:
            ph = self._phases.get(key)
            if ph is not None and ph.units != units:
                self._change(lambda: setattr(ph, 'units', max(0.0, float(units))))

    def skip(self, key):
        """The step will not run (its work is none): the rest of the bar takes its share."""
        with self._lock:
            ph = self._phases.get(key)
            if ph is not None and ph.state != 'done':
                def gone():
                    ph.state, ph.units = 'done', 0.0
                self._change(gone)

    def kind(self, key):
        """The kind of work the step is planned as (None: no such step)."""
        with self._lock:
            ph = self._phases.get(key)
            return ph.kind if ph is not None else None

    def rekind(self, key, kind):
        """The step turned out to be another kind of work (the default roster rebuilt, not read)."""
        with self._lock:
            ph = self._phases.get(key)
            if ph is not None and ph.kind != kind:
                self._change(lambda: setattr(ph, 'kind', kind))

    def begin(self, key, text=None):
        """The step runs now (the one running before it ends); `text` (else its planned one, else the text as it is)
        is said. Nothing happens for a step that runs already, so a step's reports may begin it (any thread)."""
        with self._lock:
            ph = self._phases[key]
            if ph.state == 'run':
                return
            for other in self._phases.values():
                if other.state == 'run':
                    self._end(other)
            if ph.state == 'todo':
                ph.state, ph.t0 = 'run', self._clock()
            self._text = text if text is not None else (ph.text or self._text)
        self.push(force=True)

    def tick(self, key, n):
        """`n` more units of the step done (any thread). More than planned: the step grows (never stands still)."""
        with self._lock:
            ph = self._phases.get(key)
            if ph is None or ph.state != 'run':
                return
            ph.done += n
            if ph.done > ph.units:
                self._change(lambda: setattr(ph, 'units', ph.done * 1.05))
            self._measure(ph)
        self.push()

    def share_of(self, key, share):
        """The step's share done (0..1), for steps that report a share."""
        with self._lock:
            ph = self._phases.get(key)
            if ph is None or ph.state != 'run':
                return
            ph.done = max(ph.done, min(1.0, max(0.0, share)) * ph.units)
            self._measure(ph)
        self.push()

    def end(self, key=None):
        """The step `key` (else the one running) is done."""
        with self._lock:
            for ph in self._phases.values():
                if ph.state == 'run' and (key is None or ph.key == key):
                    self._end(ph)
        self.push()

    def say(self, text):
        """Say `text` with the share as it is (a step's own words, e.g. a jersey family's %)."""
        with self._lock:
            self._text = text
        self.push(force=True)

    def finish(self):
        """Patch's work is done: every step ends, the bar is full."""
        with self._lock:
            for ph in self._phases.values():
                if ph.state == 'run':
                    self._end(ph)
            self.finished = True
            self._shown = 1.0
        self.push(force=True)

    def _measure(self, ph):
        """This PC's speed of the step's kind, from the step running (MEASURE_AFTER seconds and units in): the rest of
        the bar is spread again with it, so a first Patch's wrong guess is put right while it runs. Once a second at
        most; only a change over 10 % counts."""
        now = self._clock()
        took = now - ph.t0
        if took < MEASURE_AFTER or ph.done < MEASURE_SHARE * ph.units or ph.done <= 0:
            return
        if now - self._fixed.get(ph.kind, -1e9) < 1.0:
            return
        self._fixed[ph.kind] = now
        speed, old = took / ph.done, self.speeds.get(ph.kind, 0.0)
        if old <= 0 or abs(speed - old) > 0.1 * old:
            self._change(lambda: self.speeds.__setitem__(ph.kind, speed))

    def _end(self, ph):
        def done():
            ph.state, ph.t1 = 'done', self._clock()
        self._change(done)

    # --- the share --------------------------------------------------------------------------------------------------
    def _est(self, ph):
        return ph.units * self.speeds.get(ph.kind, 0.0)

    def _credit(self, ph, now):
        est = self._est(ph)
        if ph.state == 'done':
            return est
        if ph.state != 'run' or est <= 0:
            return 0.0
        if ph.timed:
            return est * _creep((now - ph.t0) / est)
        return min(ph.done, ph.units) * self.speeds.get(ph.kind, 0.0)

    def _work(self, now):
        """(work credited, work left) in seconds of the plan."""
        credited = left = 0.0
        for ph in self._phases.values():
            c = self._credit(ph, now)
            credited += c
            left += max(0.0, self._est(ph) - c)
        return credited, left

    def _raw(self, now):
        a, w0, r0 = self._anchor
        if r0 is None:
            credited, left = self._work(now)
            self._anchor = (a, credited, left)
            a, w0, r0 = self._anchor
        if r0 <= 0:
            return a
        credited, _left = self._work(now)
        return a + (1 - a) * max(0.0, credited - w0) / r0

    def _change(self, fn):
        """Change the plan with the share shown kept: it is the new anchor, the rest spread over the work left."""
        now = self._clock()
        before = self._current(now)
        fn()
        credited, left = self._work(now)
        self._anchor = (before, credited, left)

    def _current(self, now):
        if self.finished:
            return 1.0
        self._shown = max(self._shown, min(CAP, self._raw(now)))
        return self._shown

    def share(self):
        with self._lock:
            return self._current(self._clock())

    # --- showing it -------------------------------------------------------------------------------------------------
    def push(self, force=False):
        """Say the text and share when either changed (the share by 0.1 % or more), at most every interval / 4."""
        with self._lock:
            now = self._clock()
            share = self._current(now)
            amount = self._amount(self.written()) if self._amount else None
            text, last, when, said = self._pushed
            if not force and text == self._text and last is not None and now - when < self._interval / 4:
                return
            if not force and text == self._text and last is not None and share - last < 0.001 and amount == said:
                return
            self._pushed = (self._text, share, now, amount)
            out = self._text
        if self._amount:
            self._say(out, share, amount)
        else:
            self._say(out, share)

    def start(self):
        """Push the share every interval while Patch runs (steps without units move by time alone)."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name='patch-meter')
            self._thread.start()
        return self

    def _run(self):
        while not self._stop.wait(self._interval) and not self.finished:
            try:
                self.push()
            except Exception:  # noqa: BLE001 - the bar never stops a patch
                return

    def stop(self):
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    # --- learning ---------------------------------------------------------------------------------------------------
    def report(self):
        """[(key, kind, units, planned seconds, seconds taken)] of the steps that ran, for the log."""
        with self._lock:
            return [(ph.key, ph.kind, ph.units, self._est(ph), ph.t1 - ph.t0)
                    for ph in self._phases.values() if ph.state == 'done' and ph.t0 is not None and ph.t1 is not None]

    def learned(self, old_last=None, min_seconds=0.3):
        """(speeds, last): the speeds with this Patch's own per kind (half and half; a kind whose steps took under
        `min_seconds` or had no units keeps its speed) and each step's units, for load() next time."""
        took, units = {}, {}
        last = dict(old_last or {})
        with self._lock:
            for ph in self._phases.values():
                if ph.state != 'done':
                    continue
                last[ph.key] = ph.units     # a step skipped (kept, nothing to do) did none: 0 next time too
                if ph.t0 is None or ph.t1 is None:
                    continue
                n = 1.0 if ph.timed else min(ph.done, ph.units)
                if n <= 0:
                    continue
                took[ph.kind] = took.get(ph.kind, 0.0) + (ph.t1 - ph.t0)
                units[ph.kind] = units.get(ph.kind, 0.0) + n
            speeds = dict(self._known)
        for kind, seconds in took.items():
            if seconds < min_seconds or units[kind] <= 0:
                continue
            now = seconds / units[kind]
            old = speeds.get(kind, now)
            now = min(max(now, old / 100), old * 100)     # one odd Patch never throws the speed far off
            speeds[kind] = old / 2 + now / 2
        return speeds, last
