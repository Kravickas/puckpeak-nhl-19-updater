"""packdownload.download: the packs come down at the same time, and a pack whose files do not read back as stored
(CRC32) is downloaded again (TRIES) and then refused."""
import hashlib
import json
import struct
import threading
import time
import zipfile

import pytest

from overtime_core import art
from overtime_roster.app import packdownload as P

PACKS = ('looks.zip', 'rink.zip', 'ice_all.zip')


def _pack(path, tag):
    art.write_pack(str(path), tag, {f'nhl/{tag}/a.gnf': b'GNF ' + tag.encode() * 4000,
                                    f'nhl/{tag}/b.gnf': b'GNF ' + b'B' * 9000})
    return path.read_bytes()


def _spoil(data, member):
    """The zip's bytes with one byte of `member`'s stored data changed: the zip opens, that file's CRC32 is off."""
    raw = bytearray(data)
    with zipfile.ZipFile(__import__('io').BytesIO(data)) as z:
        info = z.getinfo(member)
    at = info.header_offset
    name_len, extra_len = struct.unpack_from('<HH', raw, at + 26)
    raw[at + 30 + name_len + extra_len + 5] ^= 0xFF
    return bytes(raw)


def _release(root, packs):
    """latest.json (a file:// URL) publishing {name: bytes} with their sha256 and size."""
    (root / 'packs').mkdir(parents=True, exist_ok=True)
    listed = {}
    for name, data in packs.items():
        (root / 'packs' / name).write_bytes(data)
        listed[name] = {'file': f'packs/{name}', 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
    (root / 'latest.json').write_text(json.dumps({'version': '0.99.0', 'packs': listed}))
    return (root / 'latest.json').as_uri()


@pytest.fixture
def opened(monkeypatch):
    """P._open with a slow read; notes how many downloads run at once and each pack's opens."""
    state = {'now': 0, 'peak': 0, 'opens': [], 'lock': threading.Lock()}
    real = P._open

    class Slow:
        def __init__(self, r):
            self.r, self.headers = r, r.headers

        def read(self, n):
            time.sleep(0.02)
            return self.r.read(n)

        def __enter__(self):
            with state['lock']:
                state['now'] += 1
                state['peak'] = max(state['peak'], state['now'])
            return self

        def __exit__(self, *exc):
            with state['lock']:
                state['now'] -= 1
            self.r.close()

    def slow_open(url):
        state['opens'].append(url.rsplit('/', 1)[-1])
        return Slow(real(url))
    monkeypatch.setattr(P, '_open', slow_open)
    monkeypatch.setattr(P, 'CHUNK', 4096)
    return state


def test_the_packs_come_down_at_the_same_time_each_checked(tmp_path, opened):
    made = {name: _pack(tmp_path / f'made_{name}', name.split('.')[0]) for name in PACKS}
    url = _release(tmp_path / 'site', made)
    cache = tmp_path / 'cache'
    got = P.download(list(PACKS), str(cache), release=url)
    assert got == [(name, True, 'Downloaded.') for name in PACKS]
    assert opened['peak'] > 1
    assert all((cache / name).read_bytes() == made[name] for name in PACKS)
    assert not list(cache.glob('*.part'))


def test_a_pack_published_with_a_damaged_file_is_tried_three_times_then_refused(tmp_path, opened):
    good = _pack(tmp_path / 'good.zip', 'looks')
    bad = _spoil(good, 'nhl/looks/a.gnf')
    url = _release(tmp_path / 'site', {'looks.zip': bad, 'rink.zip': _pack(tmp_path / 'r.zip', 'rink')})
    cache = tmp_path / 'cache'
    got = dict((n, (ok, msg)) for n, ok, msg in P.download(['looks.zip', 'rink.zip'], str(cache), release=url))
    assert got['looks.zip'] == (False, P.DAMAGED.format(name='nhl/looks/a.gnf'))
    assert got['rink.zip'] == (True, 'Downloaded.')
    assert opened['opens'].count('looks.zip') == P.TRIES
    assert not (cache / 'looks.zip').exists() and not (cache / 'looks.zip.part').exists()


def test_a_download_damaged_on_the_way_comes_down_again(tmp_path, opened, monkeypatch):
    data = _pack(tmp_path / 'made.zip', 'looks')
    url = _release(tmp_path / 'site', {'looks.zip': data})
    real, calls = P.damaged, []

    def once(path, workers=None):       # the first copy read back damaged (a disk, a line), the second is fine
        calls.append(path)
        return 'nhl/looks/a.gnf' if len(calls) == 1 else real(path, workers)
    monkeypatch.setattr(P, 'damaged', once)
    got = P.download(['looks.zip'], str(tmp_path / 'cache'), release=url)
    assert got == [('looks.zip', True, 'Downloaded.')] and opened['opens'].count('looks.zip') == 2
    assert (tmp_path / 'cache' / 'looks.zip').read_bytes() == data


def test_damaged_names_the_first_file_that_does_not_read_back(tmp_path):
    data = _pack(tmp_path / 'made.zip', 'looks')
    (tmp_path / 'ok.zip').write_bytes(data)
    (tmp_path / 'bad.zip').write_bytes(_spoil(data, 'nhl/looks/b.gnf'))
    (tmp_path / 'junk.zip').write_bytes(b'not a zip')
    assert P.damaged(str(tmp_path / 'ok.zip')) is None
    assert P.damaged(str(tmp_path / 'bad.zip'), workers=2) == 'nhl/looks/b.gnf'
    assert P.damaged(str(tmp_path / 'junk.zip')) == '(the zip)'
