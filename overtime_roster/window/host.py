"""What the controller needs from the window: pushes of state to the page, the details log, one-off events.

The controller marks a slice of state as changed; two threads send what changed, each at most 25 times a second
(the newest state wins, log lines are sent together). The quick one sends the status line, the Question, the log
lines and the events: none of their snapshots takes the controller's lock, so the Help bar moves while a job holds
it. The other sends the tabs' slices. A message goes through a transport: pywebview's evaluate_js in the window, or
the local server's event stream in browser mode. The status slice comes first in every message.

Every message carries `seq`, one higher than the one before it was taken: a slice's snapshot in it is at least as new
as that moment. The page keeps the newest seq of each slice and drops an older one (store.js): the first message (the
answer of ready) and a push run at once, and a push sent after it may reach the page before it.

`picker` (set by window/main.py in the window) shows Windows' file and folder pickers; browser mode has none.
"""
import json
import os
import subprocess
import sys
import threading
import time

from ..app import jobs, selfupdate

PUSH_EVERY = 0.04
KEEP_LINES = 5000
QUICK = ('status', 'question')  # slices whose snapshot takes no controller lock (the quick pusher sends them)


def open_file(path, popen=subprocess.Popen):
    """Open `path` with the system's own program for it: Explorer's choice on Windows, `open` on macOS, `xdg-open`
    on Linux (started with the environment from before this program, so a packed app's libraries stay out of it).
    False when the system has no opener."""
    if sys.platform == 'win32':
        os.startfile(path)  # noqa: S606 (Windows desktop app)
        return True
    try:
        popen(['open' if sys.platform == 'darwin' else 'xdg-open', path], env=selfupdate.clean_environment(),
              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    except OSError:
        return False
    return True


class WebHost:
    def __init__(self, meta=None):
        self.meta = dict(meta or {})
        self.sources = {}  # slice name -> snapshot()
        self.transports = []  # callables taking the JSON text of one message
        self._lock = threading.Lock()
        self._wake = threading.Event()        # the slices' pusher
        self._wake_quick = threading.Event()  # the quick pusher
        self._dirty = set()
        self._lines, self._clear, self._events = [], False, []
        self.lines = []
        self._pushing = False
        self._seq = 0           # the last message's (first() and take() count up under _lock)
        self.picker = None  # (folder, start, kinds) -> path, '' when cancelled; None: no window to show one in

    def register(self, name, snapshot):
        self.sources[name] = snapshot

    def add_transport(self, send):
        with self._lock:
            self.transports.append(send)

    def remove_transport(self, send):
        with self._lock:
            if send in self.transports:
                self.transports.remove(send)

    # --- what the controller calls ------------------------------------------------------------------
    def changed(self, *names):
        with self._lock:
            self._dirty.update(names)
        if any(n in QUICK for n in names):
            self._wake_quick.set()
        if any(n not in QUICK for n in names):
            self._wake.set()

    def log(self, *lines):
        stamp = time.strftime('%H:%M:%S')
        lines = [f'{stamp}  {line}' for line in lines]
        with self._lock:
            self._lines.extend(lines)
            self.lines.extend(lines)
            if len(self.lines) > KEEP_LINES:
                del self.lines[:len(self.lines) - KEEP_LINES]
        self._wake_quick.set()

    def send(self, event, payload=None):
        with self._lock:
            self._events.append([event, payload])
        self._wake_quick.set()

    def open_path(self, path):
        if path and os.path.exists(path):
            open_file(path)

    def pick(self, folder, start='', kinds=()):
        """Windows' picker for a folder (folder True) or a file of `kinds` ('shadPS4 (*.exe)'): the path, ''
        when the player cancelled, None when there is no window (browser mode: the page asks for the path)."""
        if self.picker is None:
            return None
        return self.picker(folder, start, kinds) or ''

    # --- the pushes ---------------------------------------------------------------------------------
    def _snaps(self, names):
        """{name: snapshot} with the status first (its snapshot takes no lock; the others may wait for one). A slice
        whose snapshot fails is left out (the page keeps what it had) and the error is logged: one tab's bug never
        stops the others' pushes."""
        out = {}
        for n in sorted(names, key=lambda n: (n != 'status', n not in QUICK, n)):
            if n in self.sources:
                try:
                    out[n] = self.sources[n]()
                except Exception as err:  # noqa: BLE001
                    jobs.log_unexpected(err)
        return out

    def first(self):
        """Everything, for a page that has just loaded (also after a reload)."""
        with self._lock:
            self._dirty.clear()
            self._lines, self._clear = [], False
            lines = list(self.lines)
            self._seq += 1
            seq = self._seq
        return {'meta': self.meta, 'slices': self._snaps(self.sources), 'log': {'lines': lines, 'clear': True},
                'seq': seq}

    def take(self, which='all'):
        """What changed since the last take, as one message (None: nothing). which: 'quick' (the status line, the
        Question, log lines, events), 'slices' (the rest) or 'all'."""
        with self._lock:
            names = {n for n in self._dirty if which == 'all' or (n in QUICK) == (which == 'quick')}
            self._dirty -= names
            lines, clear, events = [], False, []
            if which != 'slices':
                lines, self._lines = self._lines, []
                clear, self._clear = self._clear, False
                events, self._events = self._events, []
            if not (names or lines or clear or events):
                return None
            self._seq += 1
            seq = self._seq
        message = {'seq': seq}
        if names:
            message['slices'] = self._snaps(names)
        if lines or clear:
            message['log'] = {'lines': lines, 'clear': clear}
        if events:
            message['events'] = events
        return message

    def start_pushing(self):
        with self._lock:        # ready() can come twice at once (a reload): one pair of pushers
            if self._pushing:
                return
            self._pushing = True
        threading.Thread(target=self._pusher, args=('quick', self._wake_quick), daemon=True,
                         name='push-quick').start()
        threading.Thread(target=self._pusher, args=('slices', self._wake), daemon=True, name='push').start()

    def _pusher(self, which, wake):
        last = 0.0
        while True:
            wake.wait(0.5)
            wake.clear()
            wait = PUSH_EVERY - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            try:
                last = self._push(which) or last
            except Exception as err:  # noqa: BLE001 (the pushes go on for the rest of the session)
                jobs.log_unexpected(err)

    def _push(self, which):
        """Send what changed (one message to every transport); the time it was sent, or None (nothing to send)."""
        message = self.take(which)
        if message is None:
            return None
        sent = time.monotonic()
        try:
            text = json.dumps(message)
        except (TypeError, ValueError) as err:  # a slice that can't be sent must not stop the others
            jobs.log_unexpected(err)
            return sent
        with self._lock:
            sends = list(self.transports)
        for send in sends:
            try:
                send(text)
            except Exception:  # a closing window or a dropped browser tab
                self.remove_transport(send)
        return sent
