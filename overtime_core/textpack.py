"""Overtime text pack: replace in-game strings (loc database `nhl/data/kettle/loc/<lang>.db`) without touching
the game folder.

The pack is the `text` layer of the game patch overlay (overtime_core.overlay): shadPS4's mods overlay serves a
copy of the archive that wins for the loc database (`databigs/patch_inxp_56.big` in v1.60) with the edited
database appended. The game folder is only read. `undo` drops the layer; deleting the whole `-mods` folder also
returns the game to normal.

Older versions edited the game archive in place and left `<archive>.overtime-text.json`; `undo` still restores
those (`restore_in_place`).
"""
import json
import os

from . import eb, gamefiles
from .schema import parse_schema
from .tdb import Database

STATE_SUFFIX = '.overtime-text.json'
PACK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'client', 'textpack')
LOC_DIR = 'nhl/data/kettle/loc/'
LANG = 'eng_us'     # the text file the patch was made on (CUSA11126); the English pack serves another English too


def loc_paths(lang):
    return f'{LOC_DIR}{lang}.db', f'{LOC_DIR}{lang}-meta.xml'


def loc_files(game_dir):
    """(languages with a text file, languages with a meta) in the game's archives, sorted."""
    dbs, metas = set(), set()
    for p in gamefiles.winning(game_dir):
        name = p[len(LOC_DIR):] if p.startswith(LOC_DIR) else ''
        if name.endswith('-meta.xml'):
            metas.add(name[:-len('-meta.xml')])
        elif name.endswith('.db'):
            dbs.add(name[:-len('.db')])
    return sorted(dbs), sorted(metas)


def game_language(game_dir, files=None):
    """The text file the text layers edit: eng_us when the game has it, else another English (the European disc,
    CUSA11116, may have its own), else None (no English: the text and names layers stay off). `files`: loc_files."""
    langs = (files or loc_files(game_dir))[0]
    if LANG in langs:
        return LANG
    return next(iter(sorted(lang for lang in langs if lang.startswith('eng_'))), None)


def loc_meta(game_dir, lang):
    """The meta XML that reads `lang`'s text file. A game without that language's own meta (the update holds the text
    files of every language, the base only its own metas) reads it with another language's: every language has the
    same LanguageStrings table, only the database name differs (CUSA11126's seven metas, 2026-11-03)."""
    try:
        return gamefiles.read_latest(game_dir, loc_paths(lang)[1])[0]
    except FileNotFoundError:
        other = sorted(p for p in gamefiles.winning(game_dir) if p.startswith(LOC_DIR) and p.endswith('-meta.xml'))
        if not other:
            raise
        return gamefiles.read_latest(game_dir, other[0])[0]


def overlay_dir(game_dir):
    return gamefiles.mods_dir(game_dir)


def load_pack(path=None, lang=LANG):
    """The pack of `lang`; another English without a pack of its own takes the English one."""
    if path is None:
        path = os.path.join(PACK_DIR, f'{lang}.json')
        if not os.path.exists(path) and lang.startswith('eng_'):
            path = os.path.join(PACK_DIR, f'{LANG}.json')
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def edit_database(raw, meta_xml, strings):
    """Return (new database bytes, string ids not found). `strings` maps stringid -> text."""
    db = Database.parse(raw, parse_schema(meta_xml))
    t = db['LanguageStrings']
    todo = dict(strings)
    for row in range(t.count):
        sid = t.get(row, 'stringid')
        if sid in todo:
            t.set(row, 'sourcetext', todo.pop(sid))
    return db.to_bytes(), sorted(todo)


def read_strings(raw, meta_xml, ids):
    db = Database.parse(raw, parse_schema(meta_xml))
    t = db['LanguageStrings']
    ids = set(ids)
    return {t.get(r, 'stringid'): t.get(r, 'sourcetext') for r in range(t.count) if t.get(r, 'stringid') in ids}


def _winner(game_dir, path):
    found = None
    for big in gamefiles.archives(game_dir):
        with eb.EbArchive(big) as arc:
            if path in arc.entries:
                found = big
    if found is None:
        raise FileNotFoundError(f'{path} not in {game_dir}')
    return found


def _load_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _target(game_dir, archive):
    return os.path.join(overlay_dir(game_dir), *gamefiles.rel(game_dir, archive).split('/'))


def status(game_dir, pack):
    db_path = loc_paths(pack['language'])[0]
    archive = _winner(game_dir, db_path)
    target = _target(game_dir, archive)
    live_file = target if os.path.exists(target) else archive
    with eb.EbArchive(live_file) as arc:
        live = read_strings(arc.read(db_path), loc_meta(game_dir, pack['language']), pack['strings'])
    from . import overlay
    text = ((overlay._load_state(game_dir) or {}).get('layers') or {}).get('text') or {}
    legacy = _load_json(target + STATE_SUFFIX) or {}
    return {'overlay': target, 'applied': os.path.exists(target),
            'pack_sha256': text.get('pack_sha256') or legacy.get('pack_sha256'),
            'game_archive_edited_in_place': os.path.exists(archive + STATE_SUFFIX),
            'strings': len(pack['strings']),
            'not_current': sorted(k for k, v in pack['strings'].items() if live.get(k) != v)}


def _other_layers(game_dir):
    from . import overlay
    state = overlay._load_state(game_dir) or {}
    return overlay, [name for name in overlay.LAYERS if name != 'text' and name in state.get('layers', {})]


def apply(game_dir, pack, **kw):
    """Serve the pack through the game patch overlay (overtime_core.overlay), keeping the patch's other layers.
    The game folder is opened read-only."""
    overlay, others = _other_layers(game_dir)
    overlay.apply(game_dir, ['text'] + others, pack=pack, lang=pack['language'], **kw)
    target = _target(game_dir, _winner(game_dir, loc_paths(pack['language'])[0]))
    return {'overlay': target, 'strings': len(pack['strings'])}


def restore_in_place(archive):
    """Undo an old in-place edit of a game archive (record in `<archive>.overtime-text.json`)."""
    state = _load_json(archive + STATE_SUFFIX)
    if not state:
        return False
    if os.path.getsize(archive) != state['patched_size']:
        raise RuntimeError(f'{archive} changed since the text pack was applied (game update?); '
                           f'delete {archive + STATE_SUFFIX} after checking the archive')
    eb.restore_entry(archive, state['record'])
    os.remove(archive + STATE_SUFFIX)
    return True


def undo(game_dir, lang='eng_us', **kw):
    """Stop serving the text pack (the patch's other layers stay; with none left the overlay is removed, and an
    old in-place edit of the game archive is restored). Returns what was undone."""
    overlay, others = _other_layers(game_dir)
    if others:
        overlay.apply(game_dir, others, lang=lang, **kw)
        return [_target(game_dir, _winner(game_dir, loc_paths(lang)[0])) + ' (text layer)']
    return overlay.undo(game_dir, **kw)
