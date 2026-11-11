"""Draw the start-up splash (Pillow, through make_icon): the app's icon and "OVERTIME", centered as one group on its
near-black (owner 2026-11-11). PyInstaller's bootloader shows it while the onefile exe unpacks; the app closes it once its window shows.

    python packaging/make_splash.py <out.png>
"""
import io
import struct
import sys
import zlib

from PIL import Image

import make_icon

W, H = 440, 160
LOGO = 112
WORD, SCALE, GAP = 'OVERTIME', 5, 20
FONT = {    # 5 x 7
    'O': ('01110', '10001', '10001', '10001', '10001', '10001', '01110'),
    'V': ('10001', '10001', '10001', '10001', '10001', '01010', '00100'),
    'E': ('11111', '10000', '10000', '11110', '10000', '10000', '11111'),
    'R': ('11110', '10001', '10001', '11110', '10100', '10010', '10001'),
    'T': ('11111', '00100', '00100', '00100', '00100', '00100', '00100'),
    'I': ('01110', '00100', '00100', '00100', '00100', '00100', '01110'),
    'M': ('10001', '11011', '10101', '10101', '10001', '10001', '10001'),
    'S': ('01111', '10000', '10000', '01110', '00001', '00001', '11110'),
    'A': ('01110', '10001', '10001', '11111', '10001', '10001', '10001'),
    'N': ('10001', '11001', '10101', '10011', '10001', '10001', '10001'),
    'G': ('01110', '10001', '10000', '10111', '10001', '10001', '01111'),
    '.': ('00000', '00000', '00000', '00000', '00000', '00000', '00100'),
    ' ': ('00000',) * 7,
}


def width(s, scale):
    return len(s) * 6 * scale - scale


def text(pixels, s, x, y, scale, colour):
    for ch in s:
        for j, row in enumerate(FONT[ch]):
            for i, bit in enumerate(row):
                if bit == '1':
                    for dy in range(scale):
                        for dx in range(scale):
                            pixels[y + j * scale + dy][x + i * scale + dx] = colour
        x += 6 * scale


def main(out):
    pixels = [[make_icon.BG] * W for _ in range(H)]
    logo = Image.open(io.BytesIO(make_icon.render(LOGO))).convert('RGBA')
    left = (W - (LOGO + GAP + width(WORD, SCALE))) // 2     # the icon and the word, centered as one group
    top = (H - LOGO) // 2
    for j in range(LOGO):
        for i in range(LOGO):
            r, g, b, a = logo.getpixel((i, j))
            bg = make_icon.BG
            pixels[top + j][left + i] = tuple(round((c * a + k * (255 - a)) / 255) for c, k in zip((r, g, b), bg))
    text(pixels, WORD, left + LOGO + GAP, (H - 7 * SCALE) // 2, SCALE, make_icon.WHITE)
    rows = b''.join(b'\0' + bytes(c for px in row for c in px) for row in pixels)

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    with open(out, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 2, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b''))
    print(out)


if __name__ == '__main__':
    main(sys.argv[1])
