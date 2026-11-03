"""The Roster tab's player card on the Python side: his values in the card's units, the checks of typed values (every
wrong field at once), one undoable change per Apply, the edits each player had (the card's "Undo my edit" and the
windows' "Take back" take back his own, not the roster's newest) and the search by name. docs/ui/roster.md.

Ages count on the game's clock. NHL 19's league year is 2018 (teams.GAME_YEAR) and an updated roster for season S
stores birth years S - 2018 earlier (teams.year_shift), so the game shows a player's real age; an age counted from
today would be 8 years too high (the 2018-19 roster showed Kesler as 42). The card shows the real birth date (stored
+ shift) and writes a typed one back shifted.

Copies: the game keeps one bio per player (name, birth, ratings, face, equipment by game_id) and one exhibitionplayers
record per card (club, All-Stars, national team, Pro-Am, Seattle's Play Now copy). Number and letter are per card
(the roster row); the rest is the same on every card. Seattle's Season and Franchise card (customrostertable team 499,
also on the free agent list) and its Play Now copy (team 399, rosterupdate.mirror_seattle) must stay alike, so a
number, letter or type edit goes to both rows.

Contract years are the seasons a deal has left, as the Front office shows them: a roster that carries the expansion
career's extra season (office.carries_expansion: the default, online and updated rosters) stores one more
(rosterupdate.expansion_contracts), so the card reads contractlength - 1 there and writes + 1.
"""
import datetime
import re
import unicodedata
import weakref

from overtime_core import rosterupdate as U, teams as T
from overtime_core.roster import ALTERNATE, CAPTAIN

from . import labels as L
from . import office
from .session import BIOS, PLAYERS, ROSTER, TEAMS, clean

FA = L.FREE_AGENTS
HEIGHT = (137, 216)         # cm the game can hold (54-85 inches)
WEIGHT = (55, 170)          # kg
CAP_MAX = 20                # $M
YEARS_MAX = 8
MIN_AGE = 14
COPY_LEAGUES = (10, 23)     # International, Pro-Am (labels.LEAGUES): the game's own copies of club players
LETTERS = ('', 'C', 'A')
ORDER = ('first', 'last', 'num', 'pos', 'shoots', 'captain', 'born', 'country', 'height', 'weight', 'salary',
         'years', 'twoway')
WORDS = {'first': 'first name', 'last': 'last name', 'num': 'number', 'pos': 'position', 'shoots': 'shoots',
         'captain': 'letter', 'born': 'born', 'country': 'country', 'height': 'height', 'weight': 'weight',
         'salary': 'cap hit', 'years': 'contract years', 'twoway': 'deal'}
_EXPANSION = weakref.WeakKeyDictionary()    # session -> ((history length, newest change), carries the extra season)
POS_ORDER = {p: i for i, p in enumerate(L.POSITIONS)}
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


# --- the game's clock ----------------------------------------------------------------------------------------------
def with_year(d, year):
    try:
        return d.replace(year=year)
    except ValueError:      # 29 February in a year without one
        return d.replace(year=year, day=28)


def clock_day(today):
    """The day of the game's 2018-19 season that matches `today` (July on: 2018, else 2019)."""
    return with_year(today, T.GAME_YEAR if today.month >= 7 else T.GAME_YEAR + 1)


def age_on(born, day):
    return day.year - born.year - ((day.month, day.day) < (born.month, born.day))


def roster_shift(db, season):
    """Years the roster's birth dates sit behind the real ones: an Overtime update put them on the game's clock
    (teams.year_shift of its season); the game's own rosters keep real ones. Its sign: Seattle is in (the update adds
    it), as rosterupdate.seattle_ready tells."""
    try:
        ready = U.seattle_ready(db)
    except (KeyError, IndexError, StopIteration, TypeError, ValueError):   # no custom team tables
        ready = False
    return T.year_shift(season) if ready else 0


class Clock:
    """Ages and birth dates of one open roster."""

    def __init__(self, session, shift):
        self.s, self.shift = session, shift
        self.day = clock_day(session.today)

    def age(self, b):
        d = self.s.birth(b)
        return age_on(d, self.day) if d else None

    def born(self, b):
        d = self.s.birth(b)
        return with_year(d, d.year + self.shift).isoformat() if d else ''

    def stored(self, real):
        return with_year(real, real.year - self.shift)


def expansion(s):
    """Whether the open roster carries the expansion career's extra season (office.carries_expansion), read again
    after a change of it."""
    key = (len(s.history), id(s.history[-1]) if s.history else None)
    hit = _EXPANSION.get(s)
    if hit is None or hit[0] != key:
        hit = _EXPANSION[s] = (key, office.carries_expansion([b for b in s.rows[BIOS] if office.counts(b)]))
    return hit[1]


def stored_years(s, b, years, dollars=None):
    """contractlength for `years` left on bio b's deal (`dollars`: its new contractdollars): one more in a roster
    with the extra season, as rosterupdate.expansion_contracts gives every NHL deal."""
    if years >= 1 and expansion(s):
        after = dict(b, contractlength=years + 1, contractdollars=b['contractdollars'] if dollars is None else dollars)
        if office.lengthened(after):
            return years + 1
    return years


# --- names ---------------------------------------------------------------------------------------------------------
def plain(text):
    """Lower case without accents ('Stützle' finds 'stutzle')."""
    return ''.join(ch for ch in unicodedata.normalize('NFD', str(text or '')) if not unicodedata.combining(ch)).lower()


def find(s, text, names):
    """Players (exhibitionplayers indices) of every team and the free agent list whose name holds every typed word.
    `names`: {pi: plain name}, filled here (the caller keeps it while the roster does not change)."""
    words = plain(text).split()
    if not words:
        return []
    out = []
    for pi in list(s.entry_row) + [p for p in s.free_agents if p not in s.entry_row]:
        name = names.get(pi)
        if name is None:
            _, b = s.bio(pi)
            name = names[pi] = plain(s.name(b)) if b else ''
        if all(w in name for w in words):
            out.append(pi)
    return out


# --- where a player is ---------------------------------------------------------------------------------------------
def game_id(s, pi):
    i = s.player_row.get(pi)
    return s.rows[PLAYERS][i]['playerid'] if i is not None else None


def rail_team(s, pi):
    """The rail id he is listed under: his roster row's team, Coachella Valley (498, the custom roster only), or the
    free agents."""
    _, e = s.entry(pi)
    if e:
        return e['team']
    _, b = s.bio(pi)
    if b and b['team'] == T.SEATTLE_AHL and game_id(s, pi) in custom_rows(s, T.SEATTLE_AHL):
        return T.SEATTLE_AHL
    return FA


def custom_rows(s, team):
    """{game_id: [(table, row)]} of one custom team's roster rows (499 Seattle, 498 Coachella Valley)."""
    out = {}
    if U.CUSTOM_ROSTER in s.db:
        t = s.db[U.CUSTOM_ROSTER]
        for i in range(t.count):
            if t.get(i, 'team') == team:
                out.setdefault(game_id(s, t.get(i, 'playerindex')), []).append((U.CUSTOM_ROSTER, i))
    return out


def seattle_rows(s):
    """{game_id: [(table, row)]} of Seattle's roster rows: the custom team 499 (Season and Franchise) and its Play Now
    copy 399."""
    out = custom_rows(s, T.SEATTLE)
    for i in s.team_entries.get(T.SEATTLE_PLAY_NOW, []):
        out.setdefault(game_id(s, s.rows[ROSTER][i]['playerindex']), []).append((ROSTER, i))
    return out


def copy_kind(s, pi, sea=None):
    """'seattle' (a free agent who is Seattle's Season and Franchise card), 'play_now' (Seattle's Play Now card),
    'copy' (an All-Stars, national or Pro-Am card) or ''. `sea`: seattle_rows(s), when the caller has it."""
    _, b = s.bio(pi)
    _, e = s.entry(pi)
    if b is None:
        return ''
    if e is None:
        if b['team'] == T.SEATTLE_AHL:
            return 'coachella' if game_id(s, pi) in custom_rows(s, T.SEATTLE_AHL) else ''
        if b['team'] != T.SEATTLE:
            return ''
        return 'seattle' if game_id(s, pi) in (seattle_rows(s) if sea is None else sea) else ''
    if e['team'] == T.SEATTLE_PLAY_NOW:
        return 'play_now'
    i = s.team_row.get(e['team'])
    if i is not None and (s.rows[TEAMS][i]['league'] in COPY_LEAGUES or 'All-Stars' in s.team_name(e['team'])):
        return 'copy'
    return ''


def card_rows(s, pi, sea=None):
    """[(table, row)] that hold his number and letter on this card: his roster row, and for Seattle both rows."""
    _, b = s.bio(pi)
    erow, e = s.entry(pi)
    rows = [(ROSTER, erow)] if e else []
    if (e and e['team'] == T.SEATTLE_PLAY_NOW) or (not e and b and b['team'] == T.SEATTLE):
        sea = seattle_rows(s) if sea is None else sea
        rows += [r for r in sea.get(game_id(s, pi), []) if r not in rows]
    elif not e and b and b['team'] == T.SEATTLE_AHL:
        rows += custom_rows(s, T.SEATTLE_AHL).get(game_id(s, pi), [])
    return rows


def style_rows(s, pi):
    """[(table, row)] of every roster row of every card he has (the type is on each)."""
    gid = game_id(s, pi)
    pis = {p['index'] for p in s.rows[PLAYERS] if p['table'] == 0 and p['playerid'] == gid}
    rows = [(ROSTER, i) for i, e in enumerate(s.rows[ROSTER]) if e['playerindex'] in pis]
    if U.CUSTOM_ROSTER in s.db:
        t = s.db[U.CUSTOM_ROSTER]
        rows += [(U.CUSTOM_ROSTER, i) for i in range(t.count) if t.get(i, 'playerindex') in pis]
    return rows


def mates(s, pi, sea=None):
    """[(pi, number, letter)] of the players who share his number and letter rules: his team (Seattle: team 399 and
    the custom team 499 alike), nobody for a free agent."""
    _, e = s.entry(pi)
    kind = copy_kind(s, pi, sea)
    if kind in ('seattle', 'play_now', 'coachella'):
        if kind == 'coachella':
            sea = custom_rows(s, T.SEATTLE_AHL)
        else:
            sea = seattle_rows(s) if sea is None else sea
        own = game_id(s, pi)
        out = []
        for gid, rows in sea.items():
            if gid == own or not rows:
                continue
            table, row = rows[0]
            r = s.db[table].row(row)
            out.append((r['playerindex'], r['jersey'], r['captain']))
        return out
    if e is None:
        return []
    return [(s.rows[ROSTER][i]['playerindex'], s.rows[ROSTER][i]['jersey'], s.rows[ROSTER][i]['captain'])
            for i in s.team_entries.get(e['team'], []) if s.rows[ROSTER][i]['playerindex'] != pi]


# --- the card's values ---------------------------------------------------------------------------------------------
def rating_groups(s, b):
    """[{title, items: [[field, label]]}] of the ratings his table has."""
    table, _row, _ai = s.ai(b)
    fields = s.db[table].by_name if table else {}
    groups = L.GOALIE_GROUPS if b['position'] == L.GOALIE else L.SKATER_GROUPS
    out = [{'title': title, 'items': [[f, label] for f, label in items if f in fields]} for title, items in groups]
    return [g for g in out if g['items']]


def values(s, clock, pi):
    """His card's values in the card's units (docs/ui/roster.md `values`)."""
    _, b = s.bio(pi)
    _, e = s.entry(pi)
    if e is None and b['team'] == T.SEATTLE_AHL:     # Coachella Valley's card is its custom roster row
        rows = custom_rows(s, T.SEATTLE_AHL).get(game_id(s, pi))
        e = s.db[rows[0][0]].row(rows[0][1]) if rows else None
    _, _, ai = s.ai(b)
    inches, lbs = b['height'] + L.HEIGHT_BASE, b['weight'] + L.WEIGHT_BASE
    keys = [f for g in rating_groups(s, b) for f, _l in g['items']]
    return {
        'first': b['firstname'], 'last': b['lastname'], 'num': e['jersey'] if e else b['jersey'],
        'pos': L.POSITIONS[b['position']] if b['position'] < len(L.POSITIONS) else str(b['position']),
        'shoots': L.HANDS[b['handedness']] if b['handedness'] < len(L.HANDS) else 'L',
        'captain': e['captain'] if e else 0, 'born': clock.born(b), 'country': b['intlcountry'],
        'height': round(inches * 2.54), 'weight': round(lbs / 2.20462),
        'salary': round(b['contractdollars'] * L.CONTRACT_UNIT / 1e6, 3),
        'years': office.years_left(b, expansion(s)), 'twoway': 1 if b.get('contractis2way') else 0,
        'ratings': {f: ai[f] for f in keys} if ai else {},
    }


def shown(key, v):
    """A card value as words ('#93', '188 cm', 'C')."""
    if key == 'captain':
        return LETTERS[v] if v in (1, 2) else 'no letter'
    if key == 'country':
        return L.country(v)
    if key == 'height':
        return f'{v} cm'
    if key == 'weight':
        return f'{v} kg'
    if key == 'salary':
        return f'${v:g}M'
    if key == 'num':
        return f'#{v}'
    if key == 'twoway':
        return 'two-way' if v else 'one-way'
    return str(v)


def _whole(v):
    try:
        text = str(v).strip()
        return int(text) if re.fullmatch(r'-?\d+', text) else None
    except (TypeError, ValueError):
        return None


def _text_limit(s, table, name):
    f = s.db[table].by_name[name]
    return f.depth // 8 - (0 if f.is_huff else 1)


# --- the checks ----------------------------------------------------------------------------------------------------
def check(s, clock, pi, typed):
    """(changes, problems) of typed card values: changes [(key, old, new)] in the card's units ('ratings.<field>'
    for a rating), problems [{key, text}] of every wrong field, in the card's order. A value as on his card is no
    change. A number a teammate wears and a fourth letter are allowed (the game plays them; Verify warns)."""
    _, b = s.bio(pi)
    if b is None:
        return [], [{'key': '', 'text': 'This player is not on the roster any more.'}]
    v = typed if isinstance(typed, dict) else {}
    if 'birth' in v and 'born' not in v and v.get('birth'):     # beta1's card: the stored date
        try:
            stored = datetime.date.fromisoformat(str(v['birth']).strip())
            v = dict(v, born=with_year(stored, stored.year + clock.shift).isoformat())
        except ValueError:
            v = dict(v, born=str(v['birth']))
    now = values(s, clock, pi)
    _, e = s.entry(pi)
    goalie = b['position'] == L.GOALIE
    changes, problems = [], []

    def bad(key, text):
        problems.append({'key': key, 'text': text})

    def take(key, new):
        if str(now[key]) != str(new):
            changes.append((key, now[key], new))
            return True
        return False

    for key in ORDER:
        if key not in v:
            continue
        raw = v[key]
        if key in ('first', 'last'):
            text = clean(str(raw if raw is not None else ''))
            limit = _text_limit(s, BIOS, 'firstname' if key == 'first' else 'lastname')
            if key == 'last' and not text:
                bad(key, 'The last name cannot be empty.')
            elif len(text.encode('utf-8')) > limit:
                bad(key, f'The {WORDS[key]} is too long: {limit} letters at most.')
            else:
                take(key, text)
        elif key == 'num':
            n = _whole(raw)
            if n is None or not 1 <= n <= 99:
                bad(key, 'Numbers go from 1 to 99.')
            elif n != now['num']:   # a teammate may wear it too: the game shows both (Verify warns)
                take(key, n)
        elif key == 'pos':
            pos = str(raw or '')
            if pos not in POS_ORDER:
                bad(key, f'There is no position {pos}.')
            elif (pos == 'G') != goalie:
                bad(key, 'A skater cannot become a goalie, or a goalie a skater.')
            else:
                take(key, pos)
        elif key == 'shoots':
            if raw not in L.HANDS:
                bad(key, 'Pick L or R.')
            else:
                take(key, raw)
        elif key == 'captain':
            n = _whole(raw)
            if n not in (0, CAPTAIN, ALTERNATE):
                bad(key, 'Pick no letter, C or A.')
            elif n == now['captain']:
                pass
            elif n and e is None:
                bad(key, 'A free agent has no letter.')
            else:
                take(key, n)
        elif key == 'born':
            text = str(raw or '').strip()
            if not text or text == now['born']:
                continue
            try:
                real = datetime.date.fromisoformat(text) if DATE.match(text) else None
            except ValueError:
                real = None
            if real is None:
                bad(key, 'Write the date as YYYY-MM-DD, like 1997-01-13.')
            elif clock.stored(real).year < L.YEAR_BASE or age_on(clock.stored(real), clock.day) < MIN_AGE \
                    or clock.stored(real).year - L.YEAR_BASE > 255:
                bad(key, 'That birth year cannot be right.')
            else:
                take(key, real.isoformat())
        elif key == 'country':
            n = _whole(raw)
            if n is None or not 0 <= n <= 127:
                bad(key, 'Pick a country in the list.')
            else:
                take(key, n)
        elif key == 'height':
            n = _whole(raw)
            if n is None or not HEIGHT[0] <= n <= HEIGHT[1]:
                bad(key, f'Height: {HEIGHT[0]}-{HEIGHT[1]} cm.')
            elif round(n / 2.54) - L.HEIGHT_BASE != b['height']:     # the game keeps whole inches
                take(key, n)
        elif key == 'weight':
            n = _whole(raw)
            if n is None or not WEIGHT[0] <= n <= WEIGHT[1]:
                bad(key, f'Weight: {WEIGHT[0]}-{WEIGHT[1]} kg.')
            elif round(n * 2.20462) - L.WEIGHT_BASE != b['weight']:  # and whole pounds
                take(key, n)
        elif key == 'salary':
            try:
                m = float(re.sub(r'[$mM\s,]', '', str(raw)))
            except ValueError:
                m = None
            if m is None or m != m or not 0 <= m <= CAP_MAX:
                bad(key, f'Cap hit: millions, like 1.5 (up to {CAP_MAX}).')
            else:
                units = round(m * 1e6 / L.CONTRACT_UNIT)     # the game keeps $5,000 steps
                if units != b['contractdollars']:
                    take(key, round(units * L.CONTRACT_UNIT / 1e6, 3))
        elif key == 'years':
            n = _whole(raw)
            if n is None or not 0 <= n <= YEARS_MAX:
                bad(key, f'Contract years: 0-{YEARS_MAX}.')
            else:
                take(key, n)
        elif key == 'twoway':
            n = 1 if raw in (True, 1, '1', 'two-way') else 0 if raw in (False, 0, '0', 'one-way', None) else None
            if n is None:
                bad(key, 'Pick one-way or two-way.')
            else:
                take(key, n)
    labels = {f: label for g in rating_groups(s, b) for f, label in g['items']}
    table, _row, _ai = s.ai(b)
    for f, raw in ((v.get('ratings') or {}) if isinstance(v.get('ratings'), dict) else {}).items():
        label = labels.get(f) or L.rating_label(f)
        if f not in now['ratings']:
            bad(f'ratings.{f}', f'{label} is not his rating.')
            continue
        meta = s.db[table].by_name[f]
        top = min(99, meta.low + (1 << meta.depth) - 1)
        n = _whole(raw)
        if n is None or not meta.low <= n <= top:
            bad(f'ratings.{f}', f'{label}: {meta.low}-{top}.')
        elif n != now['ratings'][f]:
            changes.append((f'ratings.{f}', now['ratings'][f], n))
    return changes, problems


# --- writing -------------------------------------------------------------------------------------------------------
def write(s, clock, pi, changes, setter, model=None):
    """Write checked changes (check) of player pi through `setter` (RosterSession.edit's). Returns the name of the old
    captain who lost the C, or ''. Ratings: his skill_* (the overall and the summary) move as `model`
    (ratings.Model of his table) says the new ratings move them."""
    brow, b = s.bio(pi)
    erow, e = s.entry(pi)
    new = {k: n for k, _o, n in changes}
    lost = ''
    sea = seattle_rows(s)
    kind = copy_kind(s, pi, sea)
    rows = card_rows(s, pi, sea)

    def on_card(field, value):
        for table, row in rows:
            setter(table, row, field, value)

    if 'first' in new:
        setter(BIOS, brow, 'firstname', new['first'])
    if 'last' in new:
        setter(BIOS, brow, 'lastname', new['last'])
    if 'num' in new:
        on_card('jersey', new['num'])
        if kind != 'copy':          # the bio's number is his club card's (an All-Star copy keeps it)
            setter(BIOS, brow, 'jersey', new['num'])
    if 'pos' in new:
        setter(BIOS, brow, 'position', L.POSITIONS.index(new['pos']))
    if 'shoots' in new:
        setter(BIOS, brow, 'handedness', L.HANDS.index(new['shoots']))
    if 'born' in new:
        d = clock.stored(datetime.date.fromisoformat(new['born']))
        setter(BIOS, brow, 'year', d.year - L.YEAR_BASE)
        setter(BIOS, brow, 'month', d.month - 1)
        setter(BIOS, brow, 'day', d.day - 1)
    if 'country' in new:
        setter(BIOS, brow, 'intlcountry', new['country'])
    if 'height' in new:
        setter(BIOS, brow, 'height', round(new['height'] / 2.54) - L.HEIGHT_BASE)
    if 'weight' in new:
        setter(BIOS, brow, 'weight', round(new['weight'] * 2.20462) - L.WEIGHT_BASE)
    dollars = round(new['salary'] * 1e6 / L.CONTRACT_UNIT) if 'salary' in new else None
    if dollars is not None:
        setter(BIOS, brow, 'contractdollars', dollars)
    if 'years' in new:
        setter(BIOS, brow, 'contractlength', stored_years(s, b, new['years'], dollars))
    if 'twoway' in new:
        setter(BIOS, brow, 'contractis2way', new['twoway'])
    if 'captain' in new:
        if new['captain'] == CAPTAIN:      # one C per team: the old captain gets no letter
            for mate, _n, letter in mates(s, pi, sea):
                if letter == CAPTAIN:
                    for table, row in card_rows(s, mate, sea):
                        setter(table, row, 'captain', 0)
                    other = s.bio(mate)[1]
                    lost = s.name(other) if other else 'another player'
        on_card('captain', new['captain'])
    ratings = {k[len('ratings.'):]: n for k, n in new.items() if k.startswith('ratings.')}
    if ratings:
        table, arow, ai = s.ai(s.rows[BIOS][brow])
        before = dict(ai)
        for f, n in ratings.items():
            setter(table, arow, f, n)
        if model is not None:
            after = dict(before, **ratings)
            old, now = model.predict(before), model.predict(after)
            for f in model.targets:
                if f in before and old[f] != now[f]:
                    setter(table, arow, f, max(0, min(99, before[f] + now[f] - old[f])))
    return lost


def change_words(changes):
    """['number #93 to #94', 'speed 85 to 88'] (two ratings or more: 'N ratings')."""
    plain_ones = [(k, o, n) for k, o, n in changes if not k.startswith('ratings.')]
    rated = [(k, o, n) for k, o, n in changes if k.startswith('ratings.')]
    words = [f'{WORDS[k]} {shown(k, o)} to {shown(k, n)}' for k, o, n in plain_ones]
    if len(rated) == 1:
        k, o, n = rated[0]
        words.append(f'{L.rating_label(k[len("ratings."):]).lower()} {o} to {n}')
    elif rated:
        words.append(f'{len(rated)} ratings')
    return words


def change_short(changes):
    """The words of the row's "Edited: ..." and the card's "Take back: ...": ['number', 'ratings']."""
    out = [WORDS[k] for k, _o, _n in changes if not k.startswith('ratings.')]
    rated = sum(1 for k, _o, _n in changes if k.startswith('ratings.'))
    if rated:
        out.append('a rating' if rated == 1 else 'ratings')
    return out


# --- each player's edits -------------------------------------------------------------------------------------------
class Edits:
    """The Roster tab's applied changes, per player: [{ch, pi, what: 'card' | 'face' | 'gear', short, keys, ident,
    kept}] (for My edits: ident, who he was before it; kept, the fields, face parts or choices it changed). Only the
    ones Save has not written yet count (`unsaved`: ids of those changes)."""

    def __init__(self):
        self.items = []

    def add(self, ch, pi, what, short, keys, ident=None, kept=None):
        self.items.append({'ch': ch, 'pi': pi, 'what': what, 'short': list(short), 'keys': list(keys),
                           'ident': ident, 'kept': list(keys if kept is None else kept)})

    def of(self, pi, unsaved, what=None):
        """His edits that are not saved yet, oldest first."""
        return [it for it in self.items
                if it['pi'] == pi and id(it['ch']) in unsaved and (what is None or it['what'] == what)]

    def prune(self, history):
        """Forget the edits the roster no longer has (taken back, or an Undo of the whole roster)."""
        live = {id(ch) for ch in history}
        self.items = [it for it in self.items if id(it['ch']) in live]


def take_back(s, ch):
    """Take back one change of the roster's history, not only the newest (RosterSession.drop): it puts back the
    records it changed, so no newer change may have touched them (nor a bulk change, which keeps the whole database).
    Returns '' when done (or when the roster no longer has it), else the label of the newer change in the way."""
    if not any(x is ch for x in s.history):
        return ''
    if s.drop([ch]):
        return ''
    at = next(i for i, x in enumerate(s.history) if x is ch)
    keys = set(ch.snaps)
    later = next((x for x in s.history[at + 1:] if x.kept is not None or keys & set(x.snaps)), None)
    return later.label if later is not None else 'a newer change'
