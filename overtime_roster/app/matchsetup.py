"""Match-only setup (0.80.0, owner 2026-11-08: "it just works, but for multiplayer from the lobby only").

A lobby match plays on a setup made for that match alone, and the player's own setup comes back when the game closes
(or at the next app start after a crash):

  patch   the host's netplay blocks (what must match), this player's own copy of the shared-local ones (the
          cross-vendor block: it must match too, but is too big for the recipe) and this player's local-only blocks
          (picture size, Be a Pro, the Threes guard, the server's name), written to the app's own match file and passed
          with `-p`. shadPS4 then loads that file instead of the patches folder (memory_patcher.cpp OnGameLoaded), so
          the player's own overtime.xml is never touched (docs/notes/match-setup.md 0a).
  data    a view of the player's `<game>-mods`: every file hardlinked (a copy where links fail), swapped in by rename
          for the match. Overlay writes go through a temp file and os.replace, so a write on the view replaces the
          view's link and the player's file stays as it is; the menus layer (the autoplay hook) is added on the view.
  config  the game's custom config gets the match values (network on, the match timing, DMem for 1440p, AMD math on
          Intel, a log a desync report can read); its exact bytes are kept in the journal and written back after.

The journal (`match-setup.json` in the app folder) is saved before each change, so `restore` can undo any prefix of
`apply`. Nothing here runs while shadPS4 runs. `apply` and `restore` hold one lock (the app-start thread, the
Multiplayer tab and a lobby start may all call them), and a caller that saw one journal restores only that one
(`identity`, restore's `only`): a newer apply's setup is never taken away under it. Standard library only.
"""
import json
import os
import re
import shutil
import threading
import time
from xml.sax.saxutils import quoteattr

from overtime_core import gamefiles, overlay, xmlpatch

from . import gamesetup, paths

VERSION = 1
JOURNAL = 'match-setup.json'
VIEW_SUFFIX, OWN_SUFFIX, TRASH_SUFFIX = '.match', '.own', '.match-old'
MARKER = 'overtime-match-view.json'     # in every view: restore deletes only folders that carry it
MATCH_XML = 'overtime-match.xml'
# the timing every match plays with (not the host's: a stray vblank 9999 Hz, live 2026-11-08, must not travel)
MATCH_TIMING = {'vblank_frequency': 60, 'neo_mode': False}
ALWAYS_LAYERS = ('menus',)              # the autoplay hook lives in the menus layer's boot.big
# AMD math on Intel (gamesetup.amd_math_needed): set here too, for a match on a config install() has not seen
AMD_MATH_KEY = gamesetup.AMD_MATH_KEY
# The match's shadPS4 log holds what a desync report needs: the CPU, the config, and the Core.Linker line with the AMD
# math patch counts (written at Debug). Render stays at errors so the file stays small. The player's own Log settings
# come back with the config, and each match game's log is kept in the app folder, so a crash's log survives the next
# Start (live 2026-11-08: three tests where the Intel side's log could not answer).
MATCH_LOG = {'enable': True, 'separate': False, 'append': False,
             'filter': '*:Info Core.Linker:Debug Render:Error Render.Vulkan:Error Lib.Net:Debug Lib.Http:Debug'}
KEEP_LOGS = 8

_ADDR = re.compile(r'0x[0-9A-Fa-f]{1,16}\Z')
_HEX = re.compile(r'(?:[0-9A-Fa-f]{2}){1,1024}\Z')
MAX_BLOCKS, MAX_LINES, MAX_NAME = 64, 4096, 200
_LOCK = threading.RLock()       # one apply or restore at a time (apply restores first: re-entrant)


class MatchSetupError(RuntimeError):
    pass


# ---- the recipe: what the host's game plays with ------------------------------------------------------------------
def netplay_blocks(text):
    """The blocks the host's recipe carries: every enabled block outside the local-only ones, without the server lines,
    and without the shared-local ones (each game adds its own: shared_blocks). [{'name', 'lines': [[address, hex]]}]."""
    skip = {a.upper() for a in xmlpatch.LOCAL_ONLY_LINES}
    out = []
    for b in xmlpatch.parse(text):
        if (not b['enabled'] or b['name'] in xmlpatch.LOCAL_ONLY_TITLES
                or b['name'] in xmlpatch.SHARED_LOCAL_TITLES):
            continue
        lines = [[a, v.upper()] for a, v in b['lines'] if a.upper() not in skip]
        if lines:
            out.append({'name': b['name'], 'lines': lines})
    return out


def shared_blocks(text):
    """The enabled shared-local blocks of this player's patch, whole (the cross-vendor block): both games must have them
    (they count in the fingerprint), but each brings its own, so the recipe stays small."""
    return [{'name': b['name'], 'lines': [[a, v.upper()] for a, v in b['lines']]} for b in xmlpatch.parse(text)
            if b['enabled'] and b['name'] in xmlpatch.SHARED_LOCAL_TITLES and b['lines']]


def local_blocks(text):
    """This player's own part of a match patch: the enabled local-only blocks whole, and the server lines of the rest."""
    keep = {a.upper() for a in xmlpatch.LOCAL_ONLY_LINES}
    out = []
    for b in xmlpatch.parse(text):
        if not b['enabled']:
            continue
        if b['name'] in xmlpatch.LOCAL_ONLY_TITLES:
            lines = [[a, v.upper()] for a, v in b['lines']]
        else:
            lines = [[a, v.upper()] for a, v in b['lines'] if a.upper() in keep]
        if lines:
            out.append({'name': b['name'], 'lines': lines})
    return out


def recipe(own_text):
    """The recipe this app offers when it hosts: its netplay blocks (as one patch text: the server keeps
    `xml_blocks` as strings, docs/notes/lobby.md "Match recipe"), the layers every match needs, the match timing."""
    return {'v': VERSION, 'xml_blocks': [render(netplay_blocks(own_text), newline='\n')],
            'layers': [{'id': name, 'rev': overlay.VERSION} for name in ALWAYS_LAYERS], 'timing': dict(MATCH_TIMING)}


MAX_TEXT = 32 * 1024        # per patch text, as the server takes it


def blocks_of(r):
    """The recipe's patch blocks, [{'name', 'lines': [[address, hex]]}], read from its patch texts."""
    texts = r.get('xml_blocks') if isinstance(r, dict) else None
    if not isinstance(texts, list) or len(texts) > MAX_BLOCKS:
        raise MatchSetupError('the match setup has no patch blocks')
    out = []
    for text in texts:
        if not (isinstance(text, str) and 0 < len(text) <= MAX_TEXT):
            raise MatchSetupError('a patch text of the match setup does not read')
        try:
            parsed = xmlpatch.parse(text)
        except xmlpatch.PatchError as err:
            raise MatchSetupError(f'a patch text of the match setup does not read: {err}') from None
        out.extend({'name': b['name'], 'lines': [list(ln) for ln in b['lines']]} for b in parsed if b['enabled'])
    return out


def check(r):
    """`r` as a recipe this app can play, or MatchSetupError. A recipe comes over the wire: every field is checked."""
    if not isinstance(r, dict) or r.get('v') != VERSION:
        raise MatchSetupError('a match setup this app does not know (update the app)')
    blocks = blocks_of(r)
    if len(blocks) > MAX_BLOCKS:
        raise MatchSetupError('the match setup has too many patch blocks')
    lines = 0
    for b in blocks:
        if not (isinstance(b, dict) and isinstance(b.get('name'), str) and len(b['name']) <= MAX_NAME
                and isinstance(b.get('lines'), list)):
            raise MatchSetupError('a patch block of the match setup does not read')
        for ln in b['lines']:
            if not (isinstance(ln, (list, tuple)) and len(ln) == 2 and isinstance(ln[0], str) and isinstance(ln[1], str)
                    and _ADDR.match(ln[0]) and _HEX.match(ln[1])):
                raise MatchSetupError('a patch line of the match setup does not read')
        lines += len(b['lines'])
    if lines > MAX_LINES:
        raise MatchSetupError('the match setup has too many patch lines')
    layers = r.get('layers')
    if not isinstance(layers, list) or not all(isinstance(x, dict) and isinstance(x.get('id'), str) for x in layers):
        raise MatchSetupError('the match setup names its data layers wrongly')
    if any(x['id'] not in overlay.LAYERS for x in layers):
        raise MatchSetupError('the match setup asks for a data layer this app does not have (update the app)')
    timing = r.get('timing')
    if not isinstance(timing, dict) or set(timing) - set(MATCH_TIMING):
        raise MatchSetupError('the match setup names timing this app does not know (update the app)')
    if 'vblank_frequency' in timing and not (isinstance(timing['vblank_frequency'], int)
                                             and 30 <= timing['vblank_frequency'] <= 240):
        raise MatchSetupError('the match setup asks for an odd frame timing')
    if 'neo_mode' in timing and not isinstance(timing['neo_mode'], bool):
        raise MatchSetupError('the match setup asks for an odd PS4 Pro mode')
    return r


def render(blocks, newline='\r\n'):
    """A patch file of `blocks` ([{'name', 'lines'}]), every block enabled."""
    out = [xmlpatch.HEADER]
    for b in blocks:
        out.append(f'  <Metadata Name={quoteattr(b["name"])} AppVer="{xmlpatch.APP_VER}" AppElf="eboot.bin" '
                   f'isEnabled="true">\n    <PatchList>\n')
        out.extend(f'      <Line Type="bytes" Address="{a}" Value="{v.upper()}"/>\n' for a, v in b['lines'])
        out.append('    </PatchList>\n  </Metadata>\n')
    out.append(xmlpatch.FOOTER)
    return ''.join(out).replace('\n', newline)


def match_xml(r, own_text):
    """The patch this game plays the match with: the recipe's blocks, this player's shared-local ones (always this app's
    own: a recipe's block of that name is dropped), then this player's local-only ones."""
    blocks = [b for b in blocks_of(check(r)) if b['name'] not in xmlpatch.SHARED_LOCAL_TITLES]
    return render(blocks + shared_blocks(own_text) + local_blocks(own_text))


# ---- the journal ----------------------------------------------------------------------------------------------------
def journal_path():
    return paths.app_dir(JOURNAL)


def load():
    try:
        with open(journal_path(), encoding='utf-8') as f:
            j = json.load(f)
        return j if isinstance(j, dict) else None
    except (OSError, ValueError):
        return None


def tag():
    """The tag of the setup in place (apply's `tag`), or None."""
    j = load()
    return j.get('tag') if j else None


def active():
    """True while a match setup is in place (the game runs on it, or a restore is still due)."""
    return load() is not None


def identity(j=None):
    """Which match setup is in place (the journal's id, start time and tag), or None: restore(only=...) takes back
    that one and no newer one."""
    j = load() if j is None else j
    return (j.get('id'), j.get('started'), j.get('tag')) if j else None


def _save(j):
    path = journal_path()
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(j, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _drop_journal():
    try:
        os.remove(journal_path())
    except FileNotFoundError:
        pass


# ---- the data view --------------------------------------------------------------------------------------------------
def _link_tree(src, dst):
    """`dst` as a copy of `src` made of hardlinks (a plain copy per file where a link fails: exFAT, FAT32, another
    volume). Returns 'link', 'copy' or 'mixed'."""
    kinds = set()
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target = dst if rel == '.' else os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)
        for name in files:
            a, b = os.path.join(root, name), os.path.join(target, name)
            try:
                os.link(a, b)
                kinds.add('link')
            except OSError:
                shutil.copy2(a, b)
                kinds.add('copy')
    return kinds.pop() if len(kinds) == 1 else ('mixed' if kinds else 'link')


def _mark(folder, game_dir):
    with open(os.path.join(folder, MARKER), 'w', encoding='utf-8') as f:
        json.dump({'v': VERSION, 'game_dir': game_dir, 'made': int(time.time())}, f)


def _remove_view(folder):
    """Delete a view folder, only when it carries our marker (never a player's own folder)."""
    if not os.path.isdir(folder):
        return True
    if not os.path.isfile(os.path.join(folder, MARKER)):
        return False
    shutil.rmtree(folder)     # hardlinks: only the view's links go; the player's files stay
    return True


# ---- apply / restore ------------------------------------------------------------------------------------------------
def _config_values(cfg, user, xml_text, timing):
    general = cfg.setdefault('General', {})
    if not isinstance(cfg.get('Network'), dict):
        cfg.pop('Network', None)
    section = cfg.get('Network') or {}
    general.update(gamesetup.NETWORK)
    filled = {k: v for k, v in gamesetup._servers(user).items()
              if not (isinstance(section.get(k), str) and section[k].strip())}
    cfg['Network'] = dict(section, **filled, **gamesetup.NETWORK)
    gpu = cfg['GPU'] = dict(cfg['GPU']) if isinstance(cfg.get('GPU'), dict) else {}
    # Precise readbacks + readback linear images in every match (owner 2026-11-10), the player's display mode with
    # exclusive fullscreen as borderless (the HUD needs it)
    gpu.update(gamesetup.gpu_wanted(match=True))
    if 'vblank_frequency' in timing:
        gpu['vblank_frequency'] = timing['vblank_frequency']
    if 'neo_mode' in timing:
        general['neo_mode'] = timing['neo_mode']
    if gamesetup.amd_math_needed():
        general[AMD_MATH_KEY] = True
    cfg['Log'] = dict(cfg['Log'] if isinstance(cfg.get('Log'), dict) else {}, **MATCH_LOG)
    if xmlpatch.res1440(xml_text):
        dmem = general.get(gamesetup.DMEM_KEY)
        if not (isinstance(dmem, int) and dmem >= gamesetup.DMEM_1440):
            general[gamesetup.DMEM_KEY] = gamesetup.DMEM_1440
    return cfg


def apply(game_dir, user_dir, r, own_text, add_layers=None, running=None, log=lambda m: None, tag=None):
    """Put the match setup in place for `game_dir` / `user_dir` with recipe `r` (checked) and this player's own patch
    text (for the local-only blocks). `add_layers(game_dir, layers)` adds missing layers on the swapped-in view
    (default: overlay.apply with the view's layers plus the missing ones). Returns {'patch': match xml path, 'view':
    'link' | 'copy' | 'mixed' | 'empty'}. A setup still in place is restored first. `tag` (the lobby's match_id) goes into the
    journal: tag() tells a running game set up for this match from one that was not."""
    with _LOCK:
        return _apply(game_dir, user_dir, r, own_text, add_layers, running, log, tag)


def _apply(game_dir, user_dir, r, own_text, add_layers, running, log, tag):
    if (running or overlay.emulator_running)():
        raise MatchSetupError('shadPS4 is running: close the game first')
    check(r)
    if active():
        restore(running=running, log=log)
    xml_text = match_xml(r, own_text)
    if not xmlpatch.targets(xml_text)['redirector']:     # an unpatched game: the caller passes a built patch instead
        raise MatchSetupError('the match patch names no server (pass a patch built for the server)')
    cfg_path = gamesetup.custom_config_path(user_dir)
    cfg = gamesetup._game_config(cfg_path, user_dir)        # refuses a config it could not put back
    mods = gamefiles.mods_dir(game_dir)
    view, own = mods + VIEW_SUFFIX, mods + OWN_SUFFIX
    for leftover in (view, mods + TRASH_SUFFIX):
        if os.path.exists(leftover) and not _remove_view(leftover):
            raise MatchSetupError(f'{leftover} is in the way and is not a match folder of this app; move it away')
    if os.path.exists(own):
        raise MatchSetupError(f'{own} is in the way (an earlier match setup that was not put back?); move it away')
    j = {'v': VERSION, 'game_dir': game_dir, 'mods': mods, 'view': view, 'own': own, 'user_dir': user_dir,
         'started': int(time.time()), 'steps': [], 'tag': tag, 'id': os.urandom(8).hex()}
    _save(j)
    # 1. the view, beside the player's folder
    os.makedirs(view)
    _mark(view, game_dir)                                   # first: a half-built view is still ours to delete
    kind = _link_tree(mods, view) if os.path.isdir(mods) else 'empty'
    j['steps'].append('view')
    _save(j)
    # 2. the swap (two renames; the journal knows which went through)
    if os.path.isdir(mods):
        j['steps'].append('own_moving')
        _save(j)
        os.rename(mods, own)
        j['steps'].append('own_moved')
        _save(j)
    j['steps'].append('view_moving')
    _save(j)
    os.rename(view, mods)
    j['steps'].append('view_in')
    _save(j)
    # 3. the layers every match needs, on the view
    have = set((overlay.status(game_dir).get('layers') or {}).keys())
    want = [x['id'] for x in r['layers']]
    missing = [name for name in want if name not in have]
    if missing:
        log(f'Match setup: adding {", ".join(missing)} on the match view')
        (add_layers or _add_layers)(game_dir, sorted(have) + missing)
    # 4. the config (its exact bytes kept first)
    before = gamesetup._read(cfg_path) if os.path.exists(cfg_path) else None
    j['config'] = {'path': cfg_path, 'existed': before is not None,
                   'text': before.decode('utf-8', 'surrogateescape') if before is not None else None}
    j['steps'].append('config_writing')
    _save(j)
    cfg = _config_values(cfg, user_dir, xml_text, r['timing'])
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    gamesetup._write(cfg_path, json.dumps(cfg, indent=4).encode('utf-8'))
    j['steps'].append('config_written')
    # 5. the match patch, in the app's own folder
    patch = paths.app_dir('match', MATCH_XML)
    xmlpatch.write(patch, xml_text)
    j['patch'] = patch
    j['steps'].append('applied')
    _save(j)
    return {'patch': patch, 'view': kind}


def _add_layers(game_dir, layers):
    """overlay.apply on the view, with the text file the player's patch was made on (Patch passes the game's own:
    patch_ctl.game_text); overlay.apply's default eng_us would rebuild the text layers on another file."""
    served = overlay.status(game_dir).get('layers') or {}
    lang = next((served[k]['file'] for k in ('text', 'names')
                 if isinstance(served.get(k), dict) and isinstance(served[k].get('file'), str)), None)
    overlay.apply(game_dir, tuple(layers), **({'lang': lang} if lang else {}))


def restore(running=None, log=lambda m: None, only=None):
    """Put the player's own setup back (any prefix of apply). Returns 'none' (nothing to do), 'done', or 'later'
    (shadPS4 runs: it holds the files; call again once it closed). Raises MatchSetupError when something is in the
    way (the journal stays, so a later call can finish). `only` (an identity()): restore that setup alone; another
    one in place now (a newer apply's) is left to whoever made it ('none')."""
    with _LOCK:
        return _restore(running, log, only)


def _restore(running, log, only):
    j = load()
    if j is None or (only is not None and identity(j) != only):
        return 'none'
    if (running or overlay.emulator_running)():
        return 'later'
    kept = keep_log(j)
    if kept:
        log(f'Match setup: the game\'s log is kept as {kept}')
    steps = set(j.get('steps') or ())
    mods, view, own = j.get('mods'), j.get('view'), j.get('own')
    if not (mods and view and own and view == mods + VIEW_SUFFIX and own == mods + OWN_SUFFIX):
        raise MatchSetupError('the match journal does not read; nothing was moved back')
    # the config first: its bytes as they were
    c = j.get('config')
    if c and c.get('path') and ('config_writing' in steps):
        if c.get('existed'):
            gamesetup._write(c['path'], c['text'].encode('utf-8', 'surrogateescape'))
        elif os.path.exists(c['path']):
            os.remove(c['path'])
        j['config'] = None
        _save(j)
    # the view out of the game's way
    if os.path.isdir(mods) and os.path.isfile(os.path.join(mods, MARKER)):
        trash = mods + TRASH_SUFFIX
        if os.path.exists(trash) and not _remove_view(trash):
            raise MatchSetupError(f'{trash} is in the way; move it away')
        os.rename(mods, trash)
    # the player's own folder back
    if os.path.isdir(own):
        if os.path.exists(mods):
            raise MatchSetupError(f'{mods} exists beside {own}; the player\'s own folder was not put back')
        os.rename(own, mods)
    for folder in (view, mods + TRASH_SUFFIX):
        if not _remove_view(folder):
            log(f'Match setup: {folder} was left (not a match folder of this app)')
    _drop_journal()
    log('Match setup: your own setup is back')
    return 'done'


def keep_log(j):
    """Copy the shadPS4 log of a game that ran on this match setup (written after the setup started) into
    app_dir('match', 'logs'), named by its last write, keeping the newest KEEP_LOGS. Returns the copy's path or None.
    Never raises: a log must never stop the player's setup from coming back."""
    try:
        user = j.get('user_dir')
        src = os.path.join(user, gamesetup.LOG_FILE) if user else None
        if not src or not os.path.isfile(src) or os.path.getmtime(src) < (j.get('started') or 0):
            return None
        folder = paths.app_dir('match', 'logs')
        stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime(os.path.getmtime(src)))
        dst = os.path.join(folder, f'shad_log-{stamp}.txt')
        shutil.copy2(src, dst)
        old = sorted(n for n in os.listdir(folder) if n.startswith('shad_log-') and n.endswith('.txt'))
        for n in old[:-KEEP_LOGS]:
            os.remove(os.path.join(folder, n))
        return dst
    except (OSError, TypeError, ValueError):
        return None


def restore_when_closed(running=None, log=lambda m: None, sleep=time.sleep, every=10.0):
    """At app start (a thread): put a match setup left by a crash or a closed app back, once shadPS4 is closed. Returns
    restore's last answer ('none', 'done') or 'failed' (logged; the journal stays for the next start). Only the setup
    in place when it started: a lobby start that made a new one meanwhile puts its own back."""
    seen = identity()
    if seen is None:
        return 'none'
    while True:
        try:
            got = restore(running=running, log=log, only=seen)
        except (MatchSetupError, OSError) as err:
            log(f'Match setup: your own setup could not be put back yet ({err})')
            return 'failed'
        if got != 'later':
            return got
        sleep(every)
