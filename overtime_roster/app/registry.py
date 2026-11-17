"""The page's Python side in one table: which part owns which slice and which call.

Each part is a class in its own module (one per tab, plus the shell and the rail), made once with the Controller.
It declares its whole page interface in one place, at the top of the class:

    SLICES = {'lines': 'view'}           slice name -> the method that builds it (plain data, ready to send)
    CALLS = {'lines_slot': 'slot', ...}  call name -> the method the page's call runs; None: not built yet
    TAB = 'lines'                        the tab it draws (the rail's followers: follow, hide, roster_changed)

attach(ctl) makes every part (ctl.parts[key]), registers its slices with the host and returns {call: function}:
what window/api.py dispatches to (its EXPOSED is calls() plus 'ready'). A call not built yet answers
{'error': 'not built yet'} and says so on the Help bar; every slice the page reads is registered from the start, with
a minimal shape the page can draw.

A new part: its module in PARTS and in part_classes' import (written out: PyInstaller finds only imports it can read).
"""
NOT_BUILT = {'error': 'not built yet'}
NOT_BUILT_TEXT = 'This comes in the next update of Overtime Roster.'

# (key, module, class), in the order they are made: the shell and the rail first (the others read them)
PARTS = (
    ('shell', 'shell', 'Shell'),
    ('rail', 'rail', 'Rail'),
    ('rosters', 'rosters_ctl', 'RostersCtl'),
    ('setup', 'setup_controller', 'SetupController'),
    ('update', 'update_ctl', 'UpdateCtl'),
    ('save', 'save_ctl', 'SaveCtl'),
    ('patch', 'patch_ctl', 'PatchCtl'),
    ('patchall', 'patchall_ctl', 'PatchAllCtl'),
    ('roster', 'roster_ctl', 'RosterCtl'),
    ('faces', 'faces_ctl', 'FacesCtl'),
    ('gear', 'gear_ctl', 'GearCtl'),
    ('jerseys', 'jerseys_ctl', 'JerseysCtl'),
    ('lines', 'lines_ctl', 'LinesCtl'),
    ('strategy', 'strategy_ctl', 'StrategyCtl'),
    ('calendar', 'calendar_ctl', 'CalendarCtl'),
    ('office', 'office_ctl', 'OfficeCtl'),
    ('multiplayer', 'multiplayer_ctl', 'MultiplayerCtl'),
)


class Part:
    """One tab's (or the shell's) piece of the controller. It works on the Controller's shared state (`self.ctl`:
    the lock, the open roster, the status line) and keeps its own state on itself."""
    SLICES = {}
    CALLS = {}
    TAB = None
    rail_unit = 'players'   # the word over the rail's numbers while this tab shows

    def __init__(self, ctl):
        self.ctl = ctl

    # the rail's followers, for the six team tabs; called only while the part's tab shows
    def follow(self, team):
        """The rail's team (a rail id; rail.Rail.map_id gives the id this tab's tables know)."""

    def hide(self):
        """Another tab shows now."""

    def roster_changed(self):
        """Another roster was opened (or the open one was saved as another). Called under ctl.lock."""

    def rail_number(self, team):
        """The rail's small number for one team ({text, tone, tip}) while this tab shows; None: its players."""
        return None

    def drafts(self):
        """Changes made on the tab but not applied yet (Save asks "Apply your changes first?"): a short text, or ''."""
        return ''

    def dirty(self, team):
        """True while the tab holds changes for this rail team that are not in the roster yet (the rail's dot; the
        applied ones Save counts already light it). Called under ctl.lock."""
        return False


def part_classes():
    """[(key, class)] of every part. The modules are imported here, not at the top (each imports Part from this
    module), and by name (not importlib): the exe's builder must see them."""
    from . import (calendar_ctl, faces_ctl, gear_ctl, jerseys_ctl, lines_ctl, multiplayer_ctl, office_ctl, patch_ctl,
                   patchall_ctl, rail, roster_ctl, rosters_ctl, save_ctl, setup_controller, shell, strategy_ctl,
                   update_ctl)
    modules = {m.__name__.rsplit('.', 1)[-1]: m for m in (
        calendar_ctl, faces_ctl, gear_ctl, jerseys_ctl, lines_ctl, multiplayer_ctl, office_ctl, patch_ctl,
        patchall_ctl, rail, roster_ctl, rosters_ctl, save_ctl, setup_controller, shell, strategy_ctl, update_ctl)}
    return [(key, getattr(modules[module], name)) for key, module, name in PARTS]


def not_built_reply(ctl):
    """What a call that is not built yet answers; the Help bar tells the player."""
    if ctl is not None:
        ctl.say(NOT_BUILT_TEXT)
    return dict(NOT_BUILT)


def not_built(name, ctl=None):
    def call(*_args):
        return not_built_reply(ctl)
    call.__name__ = name
    return call


def attach(ctl):
    """Make the parts (ctl.parts), register their slices with ctl.host; returns {call name: function}."""
    calls = {}
    owner = {}
    for key, cls in part_classes():
        part = cls(ctl)
        ctl.parts[key] = part
        for name, method in cls.SLICES.items():
            if name in owner:
                raise ValueError(f'slice {name} is claimed by {owner[name]} and {key}')
            owner[name] = key
            ctl.host.register(name, getattr(part, method))
        for name, method in cls.CALLS.items():
            if name in calls:
                raise ValueError(f'call {name} is claimed twice ({key})')
            calls[name] = getattr(part, method) if method else not_built(name, ctl)
    return calls


def slices():
    """{slice name: part key} of every registered slice (for tests)."""
    return {name: key for key, cls in part_classes() for name in cls.SLICES}


def calls():
    """{call name: (part key, method or None)} (for tests)."""
    return {name: (key, method) for key, cls in part_classes() for name, method in cls.CALLS.items()}


def tabs():
    """{tab id: part key} of the parts that draw a tab."""
    return {cls.TAB: key for key, cls in part_classes() if cls.TAB}


def tab_parts(ctl):
    """{tab id: part} of a Controller's parts."""
    return {part.TAB: part for part in ctl.parts.values() if part.TAB}
