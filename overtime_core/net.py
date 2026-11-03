"""HTTPS for the app's own calls: Windows' trusted certificates plus Mozilla's list (certifi, which the exe carries).

A PC can lack the root a site's certificate chains to (Let's Encrypt's newer roots on a Windows that never fetched
them). A browser asks Windows to fetch a missing root; Python does not, so without Mozilla's list the lobby check, the
data pack and NHL.com fail on such a PC while the browser opens the same address (a tester's "SERVER not reachable",
2026-11-03; NHL Legacy 0.7.0 had the same). Standard library only, certifi when it is there.
"""
import ssl
import urllib.error
import urllib.request

_tls = None
_certifi = False


def tls_context():
    """Windows' trusted certificates, plus Mozilla's list when certifi is there."""
    global _tls, _certifi
    if _tls is None:
        ctx = ssl.create_default_context()
        try:
            import certifi
            ctx.load_verify_locations(certifi.where())
            _certifi = True
        except Exception:
            pass
        _tls = ctx
    return _tls


def certifi_loaded():
    """True when Mozilla's list is in the context (the exe's selftest checks it)."""
    tls_context()
    return _certifi


def urlopen(req, timeout):
    """`urllib.request.urlopen` with `tls_context()` for an https address."""
    url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
    return urllib.request.urlopen(req, timeout=timeout,  # noqa: S310 (callers pass their own fixed bases)
                                  context=tls_context() if url.startswith('https:') else None)


def certificate_failed(err):
    """True when `err` (an exception, or a URLError around one) is a failed certificate check."""
    reason = getattr(err, 'reason', err) if isinstance(err, urllib.error.URLError) else err
    return isinstance(reason, ssl.SSLCertVerificationError) or 'CERTIFICATE_VERIFY_FAILED' in str(err)
