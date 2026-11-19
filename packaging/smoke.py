"""A built app's smoke run, for .github/workflows/build-desktop.yml: start the program with --selftest (the modules
import, the page's files and the data it carries are there) and with --selftest-window (the real window starts,
hidden, and the page draws its data), print what they said, exit 1 when either failed.

    python packaging/smoke.py <program> [--nodata] [--no-window] [--timeout 300]

<program>: the AppImage, or the program inside the .app (Contents/MacOS/...).
--nodata:  a build without the private data (build_unix.py without --inputs): the default roster's lines may fail.
Standard library only.
"""
import argparse
import subprocess
import sys

EXPECTED_WITHOUT_DATA = ('default roster', 'photos.zip')


def unexpected(text, nodata=False):
    """The FAIL lines of a selftest's output that count: all of them, less those a build without data must have."""
    fails = [line for line in text.splitlines() if line.startswith('FAIL  ')]
    if nodata:
        fails = [line for line in fails if not any(word in line for word in EXPECTED_WITHOUT_DATA)]
    return fails


def passed(text, code, nodata=False):
    """Did this run pass? Its last line says PASS (exit 0), or every failure is one a build without data has."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    if code == 0 and lines[-1] == 'PASS':
        return True
    return bool(nodata and lines[-1].startswith('FAIL') and not unexpected(text, True)
                and any(line.startswith('FAIL  ') for line in lines))


def run(program, switch, timeout, runner=subprocess.run):
    """(what it printed, what it wrote to stderr, exit code) of `program switch`; a start that failed or hung is
    ('', '<why>', 1). The two are kept apart: Qt and its web view write warnings to stderr on a healthy start, and
    the verdict is the report's last line."""
    try:
        done = runner([program, switch], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as err:
        said = err.stderr.decode(errors='replace') if isinstance(err.stderr, bytes) else (err.stderr or '')
        return '', f'{said}{switch}: no answer within {timeout} s', 1
    except OSError as err:
        return '', f'{switch}: did not start ({err})', 1
    return done.stdout or '', done.stderr or '', done.returncode


def main(argv=None, runner=subprocess.run):
    ap = argparse.ArgumentParser(description="Smoke run of a built app.")
    ap.add_argument('program')
    ap.add_argument('--nodata', action='store_true')
    ap.add_argument('--no-window', action='store_true')
    ap.add_argument('--timeout', type=int, default=300)
    args = ap.parse_args(argv)
    bad = 0
    for switch, nodata in (('--selftest', args.nodata), ('--selftest-window', False)):
        if switch == '--selftest-window' and args.no_window:
            continue
        text, errors, code = run(args.program, switch, args.timeout, runner)
        print(f'--- {switch} (exit {code})\n{text}', flush=True)
        if errors.strip():
            print(f'--- {switch} stderr\n{errors}', flush=True)
        if not passed(text, code, nodata):
            bad += 1
            print(f'smoke: {switch} failed', flush=True)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
