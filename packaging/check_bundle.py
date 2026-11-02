r"""Build check: no game picture or archive goes into the exe. The folders given are what PyInstaller bundles; the only
picture allowed is the app's own logo (overtime_roster/web/img/logo.png). Exit 1 on a problem.
    python packaging\check_bundle.py overtime_roster\web overtime_roster\assets client\textpack build\defaults"""
import os
import sys

PICTURES = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tga', '.dds', '.gnf', '.big', '.zip', '.mkv', '.mp4'}
ALLOWED = {'logo.png'}


def stray(folders):
    """The picture / archive files under `folders` other than the app's own logo."""
    out = []
    for folder in folders:
        for root, _, names in os.walk(folder):
            out += [os.path.join(root, n) for n in names
                    if os.path.splitext(n)[1].lower() in PICTURES and n.lower() not in ALLOWED]
    return out


if __name__ == '__main__':
    problems = stray(sys.argv[1:])
    for p in problems[:20]:
        print('  problem: a picture or archive would go into the exe:', p)
    sys.exit(1 if problems else 0)
