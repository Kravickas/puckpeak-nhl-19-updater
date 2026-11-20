"""The Kravickas build straight from his GitHub (Setup's Boost performance card, Play NHL 19, Get newest): the newest
release the NHL19-Build CI of github.com/Kravickas/shadPS4 published (its workflow's nhl19-release job: tag
NHL19-Build-<date>-<short sha>, one file shadps4-win64-nhl19.zip holding shadPS4.exe). GitHub computes each release
file's sha256 itself (the API's "digest"), so the download is checked like every pack (packdownload._fetch); a file
without one is not offered.

Read with no sign-in (GitHub's public API, the per-IP limit for no sign-in): at most every REMEMBER seconds, after a
failed read every FORGET. OVERTIME_KRAVICKAS_RELEASES names another releases list (a test fixture, a fork).
Standard library only.
"""
import json
import os
import threading
import time
import urllib.request

from . import packdownload, selfupdate

REPO = 'Kravickas/shadPS4'
BRANCH = 'NHL19-Build'
TAG_PREFIX = BRANCH + '-'               # the workflow's tags: NHL19-Build-<date>-<short sha>
ASSET = 'shadps4-win64-nhl19.zip'       # the workflow's release file: one shadPS4.exe
RELEASES_URL = f'https://api.github.com/repos/{REPO}/releases?per_page=30'
PACK = packdownload.KRAVICKAS_PACK      # its name in the app's cache (not EMULATOR_PACK: onlineemu keeps that one)
REMEMBER = packdownload.REMEMBER
FORGET = packdownload.FORGET
TIMEOUT = packdownload.TIMEOUT
OFFLINE = 'GitHub does not answer. Check your internet connection, then try again.'
NONE = 'Kravickas has no NHL19-Build release on GitHub yet.'

_lock = threading.Lock()
_read = {}          # url -> (when read, ({PACK: Release} or {} or None, info or None))


def releases_url():
    return os.environ.get('OVERTIME_KRAVICKAS_RELEASES') or RELEASES_URL


def _digest(asset):
    value = asset.get('digest')
    if isinstance(value, str) and value.lower().startswith('sha256:'):
        hexa = value[7:].lower()
        if len(hexa) == 64 and all(c in '0123456789abcdef' for c in hexa):
            return hexa
    return None


def parse(data):
    """({PACK: Release} of the newest published NHL19-Build release with its file, or {} when there is none, info of
    it or None) from GitHub's releases list. Newest = latest published_at (GitHub's own "latest" goes by the commit's
    date). info: {tag, commit, date, page}."""
    best = None
    for rel in data if isinstance(data, list) else []:
        if not isinstance(rel, dict) or rel.get('draft') or not isinstance(rel.get('published_at'), str):
            continue
        tag = rel.get('tag_name')
        if not (isinstance(tag, str) and tag.startswith(TAG_PREFIX)):
            continue
        asset = next((a for a in rel.get('assets') or [] if isinstance(a, dict) and a.get('name') == ASSET
                      and a.get('state', 'uploaded') == 'uploaded'), None)
        if asset is None or not isinstance(asset.get('browser_download_url'), str):
            continue
        if best is None or rel['published_at'] > best[0]['published_at']:
            best = (rel, asset)
    if best is None:
        return {}, None
    rel, asset = best
    try:
        size = int(asset.get('size') or 0)
    except (TypeError, ValueError):
        size = 0
    release = selfupdate.Release((0, 0, 0), str(rel.get('name') or rel['tag_name']), str(rel.get('html_url') or ''),
                                 exe_url=asset['browser_download_url'], size=size, digest=_digest(asset), asset=PACK)
    commit = rel.get('target_commitish')
    if not (isinstance(commit, str) and len(commit) >= 7 and all(c in '0123456789abcdef' for c in commit.lower())):
        commit = rel['tag_name'].rsplit('-', 1)[-1]
    info = {'tag': rel['tag_name'], 'commit': commit[:7], 'date': rel['published_at'][:10],
            'page': str(rel.get('html_url') or '')}
    return {PACK: release}, info


def _fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': selfupdate.AGENT, 'Accept': 'application/vnd.github+json',
                                               'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(req, timeout=TIMEOUT,
                                context=selfupdate.tls_context() if url.startswith('https:') else None) as r:
        return r.read(4 << 20).decode('utf-8', 'replace')


def _look(max_age):
    url = releases_url()
    with _lock:
        hit = _read.get(url)
    if hit and time.time() - hit[0] < (max_age if hit[1][0] is not None else min(max_age, FORGET)):
        return hit[1]
    try:
        got = parse(json.loads(_fetch(url)))
    except Exception:           # offline, GitHub's limit for no sign-in, a broken answer
        got = (None, None)
    with _lock:
        _read[url] = (time.time(), got)
    return got


def table(max_age=REMEMBER):
    """{PACK: Release} of the newest Kravickas build ({} when GitHub has none), or None when GitHub cannot be read.
    May wait for GitHub (up to TIMEOUT s): call it outside ctl.lock."""
    return _look(max_age)[0]


def info():
    """{tag, commit, date, page} of the newest build the last read found, or None. No read of its own."""
    with _lock:
        hit = _read.get(releases_url())
    return dict(hit[1][1]) if hit and hit[1][1] else None


def forget():
    """Read GitHub again at the next table()."""
    with _lock:
        _read.clear()
