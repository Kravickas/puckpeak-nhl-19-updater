"""The shell: the Help bar's status line, the app's flags (which tab it opens on), the Question dialog and the calls
every tab shares (the tab in view, a folder or file to open, the web site, the error log, a folder picker).
docs/ui/CONTRACT.md "The shell's slices and calls".

The status slice never takes the controller's lock: a job that holds it (a save, the update) must not hold up the
Help bar (window/host.py sends status first). The Question has its own small lock for the same reason.
"""
import datetime
import os
import threading
import webbrowser

from .. import DISCORD, KOFI, SITE
from . import paths
from .registry import Part

TEAM_TABS = ('roster', 'lines', 'strategy', 'jerseys', 'calendar', 'office')
TAB_LABELS = {'setup': 'Setup', 'patch': 'Game patch', 'update': 'Update', 'roster': 'Roster', 'lines': 'Lines',
              'strategy': 'Strategy', 'jerseys': 'Jerseys & gear', 'calendar': 'Calendar', 'office': 'Front office',
              'multiplayer': 'Multiplayer'}
OPEN_KINDS = ('.txt', '.log', '.html', '.htm', '.csv', '.json', '.md')  # files open_path may open (never a program)
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def friendly_date(stamp, now=None):
    """'2026-10-20 21:14' (or a time.time()) in words: today at 21:14, yesterday at 21:14, 20 Oct at 21:14, 2 Oct 2025
    at 18:11 in another year. A date alone loses the 'at'. '' for nothing; a stamp it cannot read comes back as it is."""
    if stamp in (None, ''):
        return ''
    try:
        if isinstance(stamp, (int, float)):
            when, clock = datetime.datetime.fromtimestamp(stamp), True
        else:
            text = str(stamp).strip()
            when, clock = datetime.datetime.fromisoformat(text), len(text) > 10
    except (ValueError, OSError, OverflowError):
        return str(stamp)
    now = now or datetime.datetime.now()
    at = f' at {when:%H:%M}' if clock else ''
    if when.date() == now.date():
        return f'today{at}'
    if when.date() == now.date() - datetime.timedelta(days=1):
        return f'yesterday{at}'
    day = f'{when.day} {MONTHS[when.month - 1]}' + (f' {when.year}' if when.year != now.year else '')
    return day + at


class Shell(Part):
    SLICES = {'status': 'status', 'app': 'app', 'question': 'question'}
    CALLS = {'tab': 'tab', 'answer': 'answer', 'open_site': 'open_site', 'open_discord': 'open_discord',
             'open_kofi': 'open_kofi', 'open_error_log': 'open_error_log',
             'open_path': 'open_path', 'ask_unsaved': 'ask_unsaved', 'friendly_date': 'friendly_date',
             'pick_folder': 'pick_folder'}

    def __init__(self, ctl):
        super().__init__(ctl)
        self._lock = threading.Lock()
        self.asking = None      # the question shown: {id, title, lines, buttons, tone}
        self._answers = {}      # answer -> what it does
        self._asked = 0

    # --- the tab in view -------------------------------------------------------------------------------------------
    def tab(self, name):
        """The page shows another tab: the one it leaves hides, the one it shows follows the rail. Game patch and
        Setup look at the game again, as beta1 did; Update looks once when nothing has yet."""
        c = self.ctl
        old, c.tab_name = c.tab_name, name
        if old != name and c.tab_parts.get(old):
            c.tab_parts[old].hide()
        if name == 'patch' or (name == 'update' and c.patch_status is None and c.parts['patch'].eboot is None):
            c.parts['patch'].patch_refresh()    # Update's patch bar needs one look at the game
        if name == 'setup':
            c.setup.setup_refresh()
        if name == 'multiplayer':
            c.parts['multiplayer'].shown()
        c.rail.shown(name)

    # --- slices ------------------------------------------------------------------------------------------------------
    def status(self):
        c = self.ctl
        return dict(c.status, busy=bool(c.busy))   # no lock: c.status is replaced whole, never changed in place

    def app(self):
        c = self.ctl
        with c.lock:
            emulator = c.setup.known_emulator()
            rosters = c.parts['rosters']
            roster = rosters.open_roster()
            known = roster is not None or rosters.remembered() is not None
            return {'emulator_known': bool(emulator), 'roster_known': known,
                    'start': 'setup',
                    'roster': {'id': roster['id'], 'name': roster['name']} if roster else None,
                    'busy': bool(c.busy), 'play': c.setup.play_state()}

    def question(self):
        with self._lock:
            return dict(self.asking) if self.asking else None

    # --- the Question dialog -----------------------------------------------------------------------------------------
    def ask(self, title, lines, buttons, answers=None, tone=''):
        """Show a question. buttons: [(label, answer, style: 'primary' | 'danger' | 'plain')]; answers: {answer: what
        to do} (run outside every lock once the player answered; an answer without one only closes the dialog).
        Returns the question's id. A new question replaces one still shown."""
        with self._lock:
            self._asked += 1
            self.asking = {'id': self._asked, 'title': title, 'lines': list(lines), 'tone': tone,
                           'buttons': [{'label': label, 'answer': answer, 'style': style}
                                       for label, answer, style in buttons]}
            self._answers = dict(answers or {})
            ident = self._asked
        self.ctl.changed('question')
        return ident

    def answer(self, ident, answer):
        with self._lock:
            if self.asking is None or str(self.asking['id']) != str(ident):
                return None     # an old dialog's answer (a double click)
            todo = self._answers.get(answer)
            self.asking, self._answers = None, {}
        self.ctl.changed('question')
        return todo() if todo else None

    def ask_unsaved(self, what, go=None):
        """The one question before a step that loses unsaved edits (`what`: 'open the other roster', 'run the
        update', ...): Save first (saves, then goes on), Lose them (goes on: the caller drops them, as opening another
        roster does) or Cancel. Without edits it goes on at once. From the page (no `go`) the answer comes back as
        the event 'unsaved' {answer: 'go' | 'cancel'}."""
        c = self.ctl
        n = c.parts['save'].unsaved()
        if not n:
            return go() if go else {'answer': 'go'}
        roster = (c.parts['rosters'].open_roster() or {}).get('name') or 'the open roster'

        def told(answer):
            c.host.send('unsaved', {'answer': answer})
        go_on = go or (lambda: told('go'))
        edits = f'{n} edits in {roster} are' if n != 1 else f'1 edit in {roster} is'
        ident = self.ask('Your edits are not saved', [f'{edits} not saved yet.', f'Save first, or {what} and lose them.'],
                         [('Save first', 'save', 'primary'), ('Lose them', 'lose', 'danger'), ('Cancel', 'cancel', 'plain')],
                         {'save': lambda: c.parts['save'].save(None, then=go_on), 'lose': go_on,
                          'cancel': None if go else (lambda: told('cancel'))}, tone='caution')
        return {'asked': ident}

    # --- shared calls ------------------------------------------------------------------------------------------------
    def open_site(self):
        webbrowser.open(SITE)
        return {'ok': True}

    def open_discord(self):
        webbrowser.open(DISCORD)
        return {'ok': True}

    def open_kofi(self):
        webbrowser.open(KOFI)
        return {'ok': True}

    def open_error_log(self):
        path = os.path.join(paths.app_home(), 'logs', 'error.log')
        if not os.path.isfile(path):
            self.ctl.say('No errors were written down.', 'good')
            return {'ok': True}
        self.ctl.host.open_path(path)
        return {'ok': True}

    def open_path(self, what):
        """Open a folder (or a report file) in Windows: beta1's names (saves, game, home, result, report) or a path
        the page was given. Programs are never opened."""
        c = self.ctl
        result = c.result or {}
        target = {'saves': c.save_dir, 'game': c.game_dir, 'home': paths.app_home(), 'result': result.get('folder', ''),
                  'report': result.get('report', '')}.get(what)
        if target is None:
            path = os.path.normpath(str(what or '').strip().strip('"')) if what else ''
            if path and (os.path.isdir(path) or (os.path.isfile(path)
                                                 and os.path.splitext(path)[1].lower() in OPEN_KINDS)):
                target = path
            else:
                c.say('That folder is not there any more.', 'bad')
                return {'error': 'That folder is not there any more.'}
        c.host.open_path(target)
        return None

    def friendly_date(self, stamp):
        return friendly_date(stamp)

    def pick_folder(self, start=''):
        """Windows' folder picker: {path}, {cancelled}, or {type: true} in browser mode (no window to show it in:
        the page asks for the path instead)."""
        pick = getattr(self.ctl.host, 'pick', None)
        path = pick(True, start or '') if pick else None
        if path is None:
            return {'type': True}
        return {'path': path} if path else {'cancelled': True}
