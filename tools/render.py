#!/usr/bin/env python3
"""Pictures of the theme for the README (dev only; needs Pillow).

  render.py gif   codex|claude OUT.gif [COLS ROWS]     the opening animation
  render.py sheet codex|claude OUT.png [COLS ROWS]     a contact sheet of key frames
"""
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

os.environ.setdefault('PANGU_GLYPHS', 'octant')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pangu import apps, art, intro  # noqa: E402

CW, CH = 12, 25
BG = (16, 17, 21)
MONO = ImageFont.truetype('/System/Library/Fonts/SFNSMono.ttf', 20)
_pingfang = next(Path('/System/Library/AssetsV2').glob('com_apple_MobileAsset_Font*/*/AssetData/PingFang.ttc'), None)
CJK = ImageFont.truetype(str(_pingfang), 20, index=7) if _pingfang else MONO
OCTANT_BITS = {ch: bits for bits, ch in enumerate(art.ART['octants'])}


def render(cells, cols, rows, scale=1.0):
    img = Image.new('RGB', (cols * CW, rows * CH), BG)
    draw = ImageDraw.Draw(img)
    for (r, c), (ch, rgb) in cells.items():
        if not (0 <= r < rows and 0 <= c < cols) or ch == ' ':
            continue
        px, py = c * CW, r * CH
        rgb = tuple(rgb) if rgb else (220, 220, 220)
        bits = OCTANT_BITS.get(ch)
        if bits is not None:
            for k in range(8):
                if bits >> k & 1:
                    sx, sy = k % 2, k // 2
                    draw.rectangle([px + sx * CW // 2, py + round(sy * CH / 4),
                                    px + (sx + 1) * CW // 2 - 1, py + round((sy + 1) * CH / 4) - 1], fill=rgb)
            continue
        font = CJK if art.text_width(ch) == 2 else MONO
        draw.text((px, py + 2), ch, font=font, fill=rgb)
    if scale != 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    return img


def scene(app, cols, rows):
    pal = dict(art.palette(), bg=BG)
    return intro.Bloom(cols, rows, pal, app.brand, app.intro_line, app.bloom_length)


def main():
    mode, name, out = sys.argv[1], sys.argv[2], sys.argv[3]
    cols, rows = (int(sys.argv[4]), int(sys.argv[5])) if len(sys.argv) > 5 else (120, 38)
    app = apps.get(name)
    s = scene(app, cols, rows)
    # Crop to the mark's area (plus margin) so the GIF stays small.
    top, bottom = max(0, s.y0 - 3), min(rows, s.wy + s.mark.word_rows + 3)
    box = (0, top * CH, cols * CW, bottom * CH)
    if mode == 'gif':
        frames = []
        t = 0.0
        step = 1 / 25
        while t <= s.duration + 0.8:
            img = render(s.frame(min(t, s.duration)), cols, rows).crop(box)
            frames.append(img.resize((img.width * 2 // 3, img.height * 2 // 3), Image.LANCZOS)
                          .quantize(96, method=Image.MEDIANCUT))
            t += step
        frames[0].save(out, save_all=True, append_images=frames[1:], duration=int(step * 1000), loop=0,
                       optimize=True)
    else:
        times = [0.2, 0.5, 0.9, 1.3, 1.8, 2.3, 2.8, s.duration]
        shots = [render(s.frame(t), cols, rows).crop(box) for t in times]
        w, h = shots[0].size
        sheet = Image.new('RGB', (w * 2 // 2, h * 4 // 2), BG)
        for i, shot in enumerate(shots):
            shot = shot.resize((w // 2, h // 2), Image.LANCZOS)
            sheet.paste(shot, ((i % 2) * w // 2, (i // 2) * h // 2))
        sheet.save(out)
    print('wrote', out)


if __name__ == '__main__':
    main()
