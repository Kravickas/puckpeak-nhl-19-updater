"""What the page can call: pywebview's js_api in the window, POST /api/<name> in browser mode.

EXPOSED is every call of the parts (app/registry.py: each part's CALLS) plus `ready`: the calls in docs/ui/*.md and
beta1's names (tools and re/scripts/oneclick_run.py call those). Each name runs the part that owns it
(Controller.calls); a call not built yet answers {"error": "not built yet"}. tests/test_api_surface.py checks that
the page's calls, the contract files' calls and beta1's names are all in it.

Every method answers quickly (work that takes a while runs as a job) and never raises: an unexpected error comes
back as {"error": ...} and is logged. A call that returns nothing answers {"ok": true}.
"""
import os

from ..app import jobs, registry
from . import startlog

OWN = {'ready', 'page_up', 'log_js', 'open_start_log', 'open_in_browser'}      # the window's calls (boot.js), no part's
EXPOSED = frozenset(registry.calls()) | OWN


def _answer(run, args):
    try:
        reply = run(*args)
        return reply if reply is not None else {'ok': True}
    except Exception as err:  # never take the window down
        return {'error': jobs.log_unexpected(err)}


def _method(name):
    def call(self, *args):
        return _answer(self._c.calls[name], args)
    call.__name__ = name
    call.__qualname__ = f'Api.{name}'
    return call


class Api:
    EXPOSED = EXPOSED

    def __init__(self, controller, host):
        self._c = controller
        self._host = host
        self.way_out = None     # set by the window: (reason) closes it and opens the app in the browser

    def page_up(self):
        """The page has drawn its first data: the window works."""
        startlog.page_up.set()
        return {'ok': True}

    def log_js(self, text):
        startlog.note(f'page: {text}')
        return {'ok': True}

    def open_start_log(self):
        if os.path.exists(startlog.path()):
            self._host.open_path(startlog.path())
        return {'ok': True}

    def open_in_browser(self):
        if self.way_out:
            self.way_out('the player asked for it')
        return {'ok': True}

    def ready(self):
        """The page has loaded: start the pushes and send everything once."""
        startlog.ready_called.set()

        def first():
            self._host.start_pushing()
            return self._host.first()
        return _answer(first, ())


# one method per call (pywebview lists the class's methods for the window's js_api)
for _name in sorted(EXPOSED - OWN):
    setattr(Api, _name, _method(_name))
del _name
