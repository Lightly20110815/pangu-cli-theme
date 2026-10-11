#!/usr/bin/env python3
"""Build pangu/assets/art.json from the vector mark and a CJK font (dev only; needs Pillow).

Only needed when the artwork or a slogan changes; the theme itself never needs a font.
The slogans are rasterised with PingFang SC Semibold (macOS); pass --font to use another.
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / 'pangu/assets/huawei-mark.svg'
OUT = ROOT / 'pangu/assets/art.json'
SLOGANS = {'codex': '让想法，码上成真', 'claude': '从一行代码，打开新的可能'}
FONT = None  # (path, index), set in main()
# Physical height of one octant sub-pixel relative to its width (cell is ~2.12:1).
SUB_ASPECT = 2.12 / 2

TOKEN = re.compile(r'[MmLlHhVvCcSsZz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')


def bezier(p0, p1, p2, p3, steps=10):
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append((u**3*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t**3*p3[0],
                    u**3*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t**3*p3[1]))
    return out


def parse_path(d):
    tokens = TOKEN.findall(d)
    subpaths, current = [], []
    x = y = sx = sy = 0.0
    last_ctrl = None
    cmd = None
    i = 0

    def num():
        nonlocal i
        value = float(tokens[i])
        i += 1
        return value

    while i < len(tokens):
        if re.fullmatch('[A-Za-z]', tokens[i]):
            cmd = tokens[i]
            i += 1
        rel = cmd.islower()
        c = cmd.upper()
        if c == 'Z':
            if current:
                subpaths.append(current)
            current = []
            x, y = sx, sy
            last_ctrl = None
            continue
        if c == 'M':
            dx, dy = num(), num()
            x, y = (x + dx, y + dy) if rel else (dx, dy)
            if current:
                subpaths.append(current)
            current = [(x, y)]
            sx, sy = x, y
            cmd = 'l' if rel else 'L'
            last_ctrl = None
        elif c == 'L':
            dx, dy = num(), num()
            x, y = (x + dx, y + dy) if rel else (dx, dy)
            current.append((x, y))
            last_ctrl = None
        elif c == 'H':
            v = num()
            x = x + v if rel else v
            current.append((x, y))
            last_ctrl = None
        elif c == 'V':
            v = num()
            y = y + v if rel else v
            current.append((x, y))
            last_ctrl = None
        elif c in 'CS':
            if c == 'C':
                vals = [num() for _ in range(6)]
                if rel:
                    vals = [vals[k] + (x if k % 2 == 0 else y) for k in range(6)]
                c1, c2, end = (vals[0], vals[1]), (vals[2], vals[3]), (vals[4], vals[5])
            else:
                vals = [num() for _ in range(4)]
                if rel:
                    vals = [vals[k] + (x if k % 2 == 0 else y) for k in range(4)]
                c1 = (2*x - last_ctrl[0], 2*y - last_ctrl[1]) if last_ctrl else (x, y)
                c2, end = (vals[0], vals[1]), (vals[2], vals[3])
            current.extend(bezier((x, y), c1, c2, end))
            last_ctrl = c2
            x, y = end
        else:
            raise ValueError('unsupported path command ' + cmd)
    if current:
        subpaths.append(current)
    return subpaths


def load_svg():
    ns = {'s': 'http://www.w3.org/2000/svg'}
    tree = ET.parse(SVG)
    petals, word = [], []
    for el in tree.iter():
        tag = el.tag.split('}')[-1]
        cls = el.get('class', '')
        if tag == 'path':
            polys = parse_path(el.get('d'))
            (petals if cls == 'cls-3' else word).extend(polys)
        elif tag == 'polygon' and cls == 'cls-2':
            nums = [float(v) for v in el.get('points').split()]
            word.append(list(zip(nums[::2], nums[1::2])))
        elif tag == 'rect' and cls == 'cls-2':
            x, y, w, h = (float(el.get(k)) for k in ('x', 'y', 'width', 'height'))
            word.append([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])
    return petals, word


def bbox(polys):
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    return [min(xs), min(ys), max(xs), max(ys)]


def octant_table():
    table = [None] * 256
    for cp in range(0x1CD00, 0x1CDE6):
        digits = unicodedata.name(chr(cp)).split('-')[1]
        table[sum(1 << (int(c) - 1) for c in digits)] = chr(cp)
    extra = {
        0: ' ', 255: '█', 15: '▀', 240: '▄', 85: '▌', 170: '▐',
        5: '▘', 10: '▝', 80: '▖', 160: '▗', 165: '▚', 90: '▞',
        95: '▛', 175: '▜', 245: '▙', 250: '▟', 192: '▂', 252: '▆',
        3: '\U0001fb82', 63: '\U0001fb85', 20: '\U0001fbe6', 40: '\U0001fbe7',
        1: '\U0001cea8', 2: '\U0001ceab', 64: '\U0001cea3', 128: '\U0001cea0',
    }
    for bits, ch in extra.items():
        assert table[bits] is None, bits
        table[bits] = ch
    assert all(table), [i for i, c in enumerate(table) if not c]
    return ''.join(table)


def text_bits(text, rows, tracking=0.06):
    """Rasterize text into an octant sub-pixel grid `rows` cells tall."""
    sub_h = rows * 4
    scale = 8
    phys_h = sub_h * SUB_ASPECT * scale
    font = ImageFont.truetype(str(FONT[0]), int(phys_h * 0.98), index=FONT[1])
    em = font.size
    advance = em * (1 + tracking)
    width = int(advance * len(text) - em * tracking) + 4
    img = Image.new('L', (width, int(phys_h)), 0)
    draw = ImageDraw.Draw(img)
    top = font.getbbox('码')[1]
    bottom = font.getbbox('码')[3]
    glyph_h = bottom - top
    y = (phys_h - glyph_h) / 2 - top
    for k, ch in enumerate(text):
        draw.text((k * advance, y), ch, font=font, fill=255)
    sub_w = max(2, round(width / (scale)))
    sub_w += sub_w % 2
    small = img.resize((sub_w, sub_h), Image.BOX)
    bits = []
    for yy in range(sub_h):
        row = 0
        for xx in range(sub_w):
            if small.getpixel((xx, yy)) >= 118:
                row |= 1 << xx
        bits.append(format(row, 'x'))
    return {'rows': rows, 'cols': sub_w // 2, 'bits': bits}


def default_font():
    pingfang = next(Path('/System/Library/AssetsV2').glob('com_apple_MobileAsset_Font*/*/AssetData/PingFang.ttc'), None)
    return (pingfang, 11) if pingfang else None


def main():
    global FONT
    parser = argparse.ArgumentParser()
    parser.add_argument('--font', help='a CJK font file (default: PingFang SC Semibold on macOS)')
    parser.add_argument('--font-index', type=int, default=0)
    opts = parser.parse_args()
    FONT = (Path(opts.font), opts.font_index) if opts.font else default_font()
    if not FONT:
        sys.exit('no CJK font found: pass --font')
    petals, word = load_svg()
    assert len(petals) == 8, len(petals)
    lb, wb = bbox(petals), bbox(word)
    cx = (lb[0] + lb[2]) / 2
    # Principal axes of the petals cross the symmetry axis at y ~= 43.
    origin = [cx, 43.0]
    data = {
        'source': 'huawei-mark.svg (vector trace of the Huawei mark)',
        'petals': [[[round(x, 3), round(y, 3)] for x, y in p] for p in petals],
        'word': [[[round(x, 3), round(y, 3)] for x, y in p] for p in word],
        'logo_bbox': [round(v, 3) for v in lb],
        'word_bbox': [round(v, 3) for v in wb],
        'origin': [round(v, 3) for v in origin],
        'gradient': {'cx': 49.46 * .95 - 6.38, 'cy': 17.01 * .95 - 7.61, 'r': 44.94 * .95,
                     'stops': [[0, [242, 150, 128]], [.43, [215, 23, 24]], [1, [151, 30, 35]]]},
        'octants': octant_table(),
        'slogans': {key: {'text': text, 'sizes': [text_bits(text, r, 0.02 if r >= 4 else 0.06) for r in (3, 4, 5, 6)]}
                    for key, text in SLOGANS.items()},
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('wrote', OUT, OUT.stat().st_size, 'bytes; logo bbox', lb, 'word bbox', wb)
    for key, slogan in data['slogans'].items():
        print(key, slogan['text'], [(s['rows'], s['cols']) for s in slogan['sizes']])


if __name__ == '__main__':
    sys.exit(main())
