"""workers: the textures made on every core, in order, each job's error its own; the same bytes as one thread."""
import threading
import time

import pytest

from overtime_core import workers


def test_results_come_back_in_the_jobs_order_with_their_errors():
    def make(i):
        time.sleep(0.002 * (7 - i % 7))          # later jobs finish first
        if i == 5:
            raise ValueError('five')
        return i * i
    jobs = [(i, (i,)) for i in range(20)] + [('unread', OSError('no file'))]
    out = list(workers.ordered(iter(jobs), make, (ValueError,), workers=4))
    assert [k for k, _r, _e in out] == list(range(20)) + ['unread']
    assert [r for k, r, e in out if e is None] == [i * i for i in range(20) if i != 5]
    assert str(out[5][2]) == 'five' and isinstance(out[-1][2], OSError)


def test_an_error_not_named_is_raised():
    def make(i):
        raise KeyError(i)
    with pytest.raises(KeyError):
        list(workers.ordered(((i, (i,)) for i in range(3)), make, (ValueError,), workers=3))


def test_jobs_are_read_on_the_calling_thread_and_bounded():
    caller, readers, pending = threading.get_ident(), set(), []

    def jobs():
        for i in range(40):
            readers.add(threading.get_ident())
            pending.append(i)
            yield i, (i,)
    seen = 0
    for _k, _r, _e in workers.ordered(jobs(), lambda i: i, workers=3):
        seen += 1
        assert len(pending) - seen <= 3 + workers.AHEAD + 1
    assert readers == {caller} and seen == 40


def test_work_started_on_a_pool_thread_stays_on_it():
    def make(i):
        inner = list(workers.ordered(((j, (j,)) for j in range(3)), lambda j: threading.get_ident(), workers=4))
        return {r for _k, r, _e in inner} == {threading.get_ident()} and workers.in_worker()
    assert all(r for _k, r, _e in workers.ordered(((i, (i,)) for i in range(4)), make, workers=2))
    assert not workers.in_worker()


@pytest.fixture
def cores(monkeypatch):
    def use(n):
        monkeypatch.setattr(workers, 'count', lambda: n)
    return use


def test_a_texture_split_over_the_cores_is_the_same_bytes(cores, monkeypatch):
    np = pytest.importorskip('numpy')
    from overtime_core import bcn
    monkeypatch.setattr(bcn, 'CHUNK', 16)
    px = np.random.default_rng(5).integers(0, 256, (64, 64, 4)).astype(np.uint8)
    cores(1)
    one = {f: bcn.encode(f, px) for f in ('BC1', 'BC3', 'BC7')}
    cores(4)
    assert {f: bcn.encode(f, px) for f in ('BC1', 'BC3', 'BC7')} == one


def noise(pil, size, seed, mode):
    """A deterministic busy picture (every block different)."""
    np = pytest.importorskip('numpy')
    px = np.random.default_rng(seed).integers(0, 256, (size, size, len(mode)), dtype=np.uint8)
    return pil.fromarray(px, mode)


def test_jerseys_and_club_art_made_on_many_cores_are_the_same_packs(cores, tmp_path):
    """Jerseys (every step kind) and club art (logos and a centre ice), made with 1 and 6 workers: the same bytes."""
    import datetime
    import hashlib
    import test_clubart as TC
    import test_kitcompose as TK
    from overtime_core import clubart, eb, gnf, kitcompose as K
    from test_gnf import template
    pil = pytest.importorskip('PIL.Image')
    day = datetime.date(2026, 11, 8)
    packs = {}
    for n in (1, 6):
        cores(n)
        root = tmp_path / str(n)
        big = root / 'NHL 19' / 'databigs'
        big.mkdir(parents=True)
        game, files, pictures = {}, {}, {}
        for i in range(12):                     # 12 jerseys, each its own picture, and the other steps
            jersey = f'nhl/rendering/jersey_rbk_t{i}_cm.gnf'
            game[jersey] = template(64, 64, ('BC1', 'BC3', 'BC7')[i % 3], mips=7)
            pic = TK.webp(noise(pil, 64, i, 'RGB'))
            member = hashlib.sha256(pic).hexdigest()[:20] + '.webp'
            pictures[member] = pic
            files[jersey] = {'op': 'make', 'picture': member}
        game[TK.NORMAL] = template(64, 64, 'BC5', 'SNORM')
        game[TK.FONT_NM] = template(64, 64, 'BC5', 'SNORM')
        game[TK.PANT] = gnf.make(template(64, 64, 'BC1'), TK.striped(pil))
        pictures['m.png'] = TK.png(pil.new('1', (K.SIZE, K.SIZE), 0))
        files.update({TK.NORMAL: {'op': 'cover', 'mask': 'm.png'}, TK.FONT_NM: {'op': 'flat'},
                      TK.PANT: {'op': 'pants', 'main': [10, 40, 120], 'trim': [200, 150, 0]}})
        eb.new_archive(str(big / 'inxp_10.big'), game)
        pack = TK.layer_pack(root / K.source_pack('nhl'), files, pictures)
        kits = str(root / 'cache' / K.local_pack('nhl'))
        counts = K.compose(K.Source(pack), str(root / 'NHL 19'), kits, K.served_name('nhl'), today=day)
        assert counts['files'] == 15 and counts['failed'] == 0

        cbig = root / 'C' / 'databigs'
        cbig.mkdir(parents=True)
        ice = pil.new('RGBA', (64, 64), (240, 241, 240, 255))
        eb.new_archive(str(cbig / 'inxp_10.big'), {
            TC.LOGO.format('large', 101): template(64, 64, 'BC7'),
            TC.LOGO.format('extrasmall', 101): template(32, 32, 'BC3'),
            TC.LOGO.format('large', 102): template(64, 64, 'BC7'),
            TC.ICE.format(102): gnf.make(template(64, 64, 'BC3'), ice)})
        source = clubart.Source(TC.source_pack(root / clubart.PACK, [
            TC.club('Henderson Silver Knights', 101, logos=('large', 'extrasmall')),
            TC.club('HC Davos', 300, league=TC.OTHER, ice=False)], {
            'c/101/large.webp': noise(pil, 256, 99, 'RGBA'),
            'c/101/extrasmall.webp': pil.new('RGBA', (64, 64), (180, 20, 30, 255)),
            'c/101/ice.webp': ice, 'c/300/large.webp': pil.new('RGBA', (256, 256), (230, 200, 20, 255))}))
        logos = str(root / 'cache' / clubart.LOCAL_PACK)
        clubart.compose(source, [TC.team(1, 101, 'Henderson Silver Knights'), TC.team(2, 102, 'HC Davos')],
                        str(root / 'C'), logos, today=day)
        packs[n] = [_members(kits), _members(logos)]
    assert packs[1] == packs[6]


def _members(path):
    """A pack's members and manifest, its `made` key left out (it hashes the source zip, whose dates differ here)."""
    import json
    import zipfile
    with zipfile.ZipFile(path) as z:
        out = {n: z.read(n) for n in z.namelist()}
    info = json.loads(out.pop('pack.json'))
    info.pop('made', None)
    return out, info


def test_threads_with_a_context_enter_and_leave_it_on_their_own_thread():
    import contextlib
    seen = []

    @contextlib.contextmanager
    def ctx():
        me = threading.get_ident()
        seen.append(('in', me))
        yield
        seen.append(('out', me))
    out = list(workers.ordered(((i, (i,)) for i in range(20)), lambda i: (i, threading.get_ident()), workers=3,
                               context=ctx))
    assert [r[0] for _k, r, _e in out] == list(range(20))
    ins = {t for k, t in seen if k == 'in'}
    assert ins == {t for k, t in seen if k == 'out'} and len(ins) == 3
    assert {r[1] for _k, r, _e in out} <= ins


def test_an_art_archive_read_on_many_cores_is_the_same_archive(cores, tmp_path):
    from overtime_core import art, eb
    files = {f'nhl/ui/kettle_assets/teamlogos/large/t{i}.gnf': b'GNF ' + bytes([i]) * (1000 + 37 * i)
             for i in range(40)}
    path = str(tmp_path / 'p.zip')
    art.write_pack(path, 'p', files, source='t', built='2026-11-08')
    pack = art.load_pack(path)
    outs = {}
    for n in (1, 5):
        cores(n)
        out = str(tmp_path / f'a{n}.big')
        with art.reading():
            sha = eb.new_archive(out, pack.files, context=art.reading)
        outs[n] = (sha, open(out, 'rb').read())
    assert outs[1] == outs[5] and outs[1][1] == eb.archive_bytes({p: files[p] for p in pack.files})   # pack order


def test_a_damaged_art_file_read_on_another_core_fails_the_archive(cores, tmp_path):
    from overtime_core import art, eb
    bad = art.Stored(10, lambda: (_ for _ in ()).throw(art.ArtError('does not match its checksum')))
    cores(4)
    with pytest.raises(art.ArtError, match='checksum'):
        eb.new_archive(str(tmp_path / 'x.big'), {'nhl/a.gnf': b'GNF 123456', 'nhl/b.gnf': bad},
                       context=art.reading)
    assert not (tmp_path / 'x.big').exists() and not (tmp_path / 'x.big.tmp').exists()


def _square(x):
    return x * x


def test_ordered_processes_in_order(monkeypatch):
    """Processes (spawned) give the same results in the same order as threads."""
    monkeypatch.setenv('OVERTIME_NO_PROCESSES', '0')
    got = list(workers.ordered(((i, (i,)) for i in range(20)), _square, workers=2, processes=True))
    assert [(k, r) for k, r, _e in got] == [(i, i * i) for i in range(20)]
