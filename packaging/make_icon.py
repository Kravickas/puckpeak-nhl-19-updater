"""Draw overtime_roster/assets/app.ico from packaging/icon/NHL19_OT_v1.ico, the app's official icon (a puck clock),
in 16/24/32/48/64/128/256 px frames (needs Pillow; the build environment has it).

    python packaging/make_icon.py
"""
import io
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = os.path.join(ROOT, 'packaging', 'icon', 'NHL19_OT_v1.ico')
OUT = os.path.join(ROOT, 'overtime_roster', 'assets', 'app.ico')
SIZES = (16, 24, 32, 48, 64, 128, 256)
BG, ORANGE, WHITE = (0x11, 0x11, 0x16), (0xf2, 0x6b, 0x1d), (0xf3, 0xf1, 0xee)      # the app's colours (the splash)


def _master():
    im = Image.open(MASTER)
    im.size = max(im.info.get('sizes') or [im.size])        # the biggest frame
    return im.convert('RGBA')


def render(size):
    """The master drawing at size x size, as the bytes of an RGBA PNG."""
    buf = io.BytesIO()
    _master().resize((size, size), Image.LANCZOS).save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    _master().save(OUT, format='ICO', sizes=[(s, s) for s in SIZES])
    print(OUT)


if __name__ == '__main__':
    main()
