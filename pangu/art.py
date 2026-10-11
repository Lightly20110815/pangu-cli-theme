"""The Huawei mark rendered as Unicode 16 octant blocks (2x4 solid sub-pixels per cell).

Shared by the opening animation and the home overlay. Standard library only.
"""
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ART = json.loads((ROOT / 'assets/art.json').read_text(encoding='utf-8'))
QUADRANTS = ' ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█'
# Terminals known to draw octants (Unicode 16) themselves; everything else gets quadrants.
OCTANT_TERMINALS = ('ghostty',)


def glyph_table():
    """Octant bit pattern -> character. Octants need a terminal that draws them natively;
    other terminals get 2x2 quadrant blocks, which every terminal font has."""
    mode = os.environ.get('PANGU_GLYPHS', '').lower()
    term = os.environ.get('TERM_PROGRAM', '').lower()
    if mode == 'octant' or (not mode and term in OCTANT_TERMINALS):
        return ART['octants']
    table = []
    for bits in range(256):
        quad = 0
        for k, (a, b) in enumerate(((0, 2), (1, 3), (4, 6), (5, 7))):
            if bits >> a & 1 or bits >> b & 1:
                quad |= 1 << k
        table.append(QUADRANTS[quad])
    return ''.join(table)


OCTANTS = glyph_table()
# Height:width of a terminal cell. Ghostty + SF Mono with adjust-cell-height=1 is ~2.12;
# most fonts sit between 2.0 and 2.2.
CELL_RATIO = float(os.environ.get('PANGU_CELL_RATIO', '2.12'))
SUB_ASPECT = CELL_RATIO / 2

# First row the home lockup may use: below the app's header (rows 1-3) and one blank row.
HOME_TOP = 5
PLATFORM = '盘古大模型 · 昇腾计算平台'


class Brand:
    """The words under the mark, per app."""

    def __init__(self, key, tagline):
        slogan = ART['slogans'][key]
        self.key = key
        self.slogan = slogan['text']
        self.sizes = slogan['sizes']
        self.tagline = tagline
        self.platform = PLATFORM


BRANDS = {
    'codex': Brand('codex', 'CODE IT POSSIBLE'),
    'claude': Brand('claude', 'MAKE IT POSSIBLE'),
}

DARK = {
    'ink': (238, 233, 228), 'soft': (196, 189, 184), 'muted': (128, 121, 119), 'red': (232, 52, 60),
    'rule': (92, 38, 43), 'bg': (14, 15, 18),
}
LIGHT = {
    'ink': (30, 26, 27), 'soft': (70, 64, 64), 'muted': (122, 116, 114), 'red': (199, 0, 11),
    'rule': (230, 190, 192), 'bg': (250, 250, 250),
}


def palette():
    return LIGHT if os.environ.get('PANGU_THEME', '').lower() == 'light' else DARK


def palette_for(bg):
    """Palette for a terminal whose background is `bg` (r, g, b) or unknown (None)."""
    pal = dict(palette())
    if bg:
        luma = (0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2]) / 255
        if luma > 0.55:
            pal = dict(LIGHT)
        pal['bg'] = bg
    return pal


def text_width(text):
    width = 0
    for ch in text:
        o = ord(ch)
        if o < 0x1100:
            width += 1
        elif (0x1100 <= o <= 0x115f or 0x2e80 <= o <= 0xa4cf or 0xac00 <= o <= 0xd7a3
              or 0xf900 <= o <= 0xfaff or 0xfe30 <= o <= 0xfe4f or 0xff00 <= o <= 0xff60
              or 0xffe0 <= o <= 0xffe6 or 0x1f300 <= o <= 0x1faff or 0x20000 <= o <= 0x3fffd):
            width += 2
        else:
            width += 1
    return width


def mix(a, b, t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return (round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t), round(a[2] + (b[2] - a[2]) * t))


def gradient(x, y):
    """Huawei radial gradient at SVG coordinates."""
    g = ART['gradient']
    t = min(1.0, math.hypot(x - g['cx'], y - g['cy']) / g['r'])
    stops = g['stops']
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if t <= p1:
            return mix(c0, c1, (t - p0) / (p1 - p0))
    return tuple(stops[-1][1])


def coverage(polys, width, height, ox, oy, kx, ky, samples=4):
    """Even-odd area coverage of SVG polygons on a width x height sub-pixel grid.

    Sub-pixel (i, j) covers SVG x in [ox + i/kx, ox + (i+1)/kx), y likewise with ky.
    """
    edges = []
    for poly in polys:
        n = len(poly)
        for k in range(n):
            x0, y0 = poly[k]
            x1, y1 = poly[(k + 1) % n]
            x0, y0 = (x0 - ox) * kx, (y0 - oy) * ky
            x1, y1 = (x1 - ox) * kx, (y1 - oy) * ky
            if y0 != y1:
                edges.append((x0, y0, x1, y1) if y0 < y1 else (x1, y1, x0, y0))
    grid = [[0.0] * width for _ in range(height)]
    share = 1.0 / samples
    for j in range(height):
        row = grid[j]
        active = [e for e in edges if e[1] < j + 1 and e[3] > j]
        if not active:
            continue
        for s in range(samples):
            yy = j + (s + 0.5) * share
            xs = sorted(x0 + (yy - y0) * (x1 - x0) / (y1 - y0)
                        for x0, y0, x1, y1 in active if y0 <= yy < y1)
            for a, b in zip(xs[::2], xs[1::2]):
                a, b = max(0.0, a), min(float(width), b)
                if b <= a:
                    continue
                ia, ib = int(a), int(b)
                if ia == ib:
                    row[ia] += (b - a) * share
                    continue
                row[ia] += (ia + 1 - a) * share
                for k in range(ia + 1, min(ib, width)):
                    row[k] += share
                if ib < width:
                    row[ib] += (b - ib) * share
    return grid


def octant_cells(grid, threshold=0.5):
    """Sub-pixel coverage grid -> rows of octant bit masks (0..255) per cell."""
    height, width = len(grid), len(grid[0]) if grid else 0
    rows = []
    for cy in range(0, height, 4):
        line = []
        for cx in range(0, width, 2):
            bits = 0
            for dy in range(4):
                y = cy + dy
                if y >= height:
                    break
                r = grid[y]
                if r[cx] >= threshold:
                    bits |= 1 << (dy * 2)
                if cx + 1 < width and r[cx + 1] >= threshold:
                    bits |= 1 << (dy * 2 + 1)
            line.append(bits)
        rows.append(line)
    return rows


class Mark:
    """Logo and wordmark at a given size, positioned in cell units."""

    def __init__(self, logo_cols, word_rows):
        lb, wb = ART['logo_bbox'], ART['word_bbox']
        self.logo_cols = logo_cols
        self.kx = 2 * logo_cols / (lb[2] - lb[0])
        self.ky_sub = self.kx / SUB_ASPECT
        self.logo_rows = math.ceil((lb[3] - lb[1]) * self.ky_sub / 4)
        # Vertically centre the petals inside their rows.
        spare = self.logo_rows * 4 - (lb[3] - lb[1]) * self.ky_sub
        self.logo_ox = lb[0]
        self.logo_oy = lb[1] - spare / 2 / self.ky_sub
        self.word_rows = word_rows
        self.wky = word_rows * 4 / (wb[3] - wb[1])
        self.wkx = self.wky * SUB_ASPECT
        self.word_cols = math.ceil((wb[2] - wb[0]) * self.wkx / 2)
        self.word_ox = wb[0]
        self.word_oy = wb[1]
        self._logo = None
        self._word = None

    def logo_bits(self):
        if self._logo is None:
            grid = coverage(ART['petals'], self.logo_cols * 2, self.logo_rows * 4,
                            self.logo_ox, self.logo_oy, self.kx, self.ky_sub)
            self._logo = octant_cells(grid)
        return self._logo

    def word_bits(self):
        if self._word is None:
            grid = coverage(ART['word'], self.word_cols * 2, self.word_rows * 4,
                            self.word_ox, self.word_oy, self.wkx, self.wky)
            self._word = octant_cells(grid, 0.46)
        return self._word

    def logo_color(self, row, col):
        """Gradient colour for logo cell (row, col)."""
        x = self.logo_ox + (col * 2 + 1) / self.kx
        y = self.logo_oy + (row * 4 + 2) / self.ky_sub
        return gradient(x, y)

    def svg_to_cell(self, x, y):
        """SVG coordinates -> fractional sub-pixel coordinates in the logo box."""
        return (x - self.logo_ox) * self.kx, (y - self.logo_oy) * self.ky_sub


def slogan_bits(brand, rows):
    for size in brand.sizes:
        if size['rows'] == rows:
            width = size['cols'] * 2
            grid = []
            for hexrow in size['bits']:
                v = int(hexrow, 16)
                grid.append([1.0 if v >> x & 1 else 0.0 for x in range(width)])
            return octant_cells(grid), size['cols']
    return None, 0


def platform_line(brand):
    return '──  ' + brand.platform + '  ──'


class Lockup:
    """Home composition: positions of every element relative to the block's top-left.

    `word_rows` picks the scale (0 = text only); the petals are sized to the wordmark's
    width as in the official lockup.
    """

    def __init__(self, brand, word_rows, slogan_rows, cols):
        self.brand = brand
        self.cols = cols
        self.word_rows = word_rows
        self.slogan_rows = slogan_rows
        if word_rows:
            probe = Mark(20, word_rows)
            logo_cols = int(probe.word_cols * 1.04 + 1) // 2 * 2
            self.mark = Mark(logo_cols, word_rows)
            lr = self.mark.logo_rows
            self.gap_logo = max(1, round(lr * 0.12))
            self.gap_word = (3 if slogan_rows else 2) if word_rows >= 3 else 1
            self.gap_platform = 2 if word_rows >= 3 else 1
        else:
            self.mark = None
            lr = self.gap_logo = self.gap_word = 0
            self.gap_platform = 1
        if slogan_rows:
            self.slogan_cells, self.slogan_cols = slogan_bits(brand, slogan_rows)
            slogan_h = slogan_rows
        else:
            self.slogan_cells, self.slogan_cols = None, text_width(brand.slogan)
            slogan_h = 1
        self.gap_tag = 1 if slogan_rows else 0
        mark_w = max(self.mark.logo_cols, self.mark.word_cols) if self.mark else 0
        self.width = max(mark_w, self.slogan_cols, text_width(platform_line(brand)))
        self.logo_top = 0
        self.word_top = lr + self.gap_logo
        self.slogan_top = self.word_top + word_rows + self.gap_word
        self.tag_top = self.slogan_top + slogan_h + self.gap_tag
        self.platform_top = self.tag_top + 1 + self.gap_platform
        self.height = self.platform_top + 1

    def centre(self, width):
        return (self.cols - width) // 2


def choose(brand, cols, rows):
    """Largest lockup that fits a cols x rows area (always returns one, maybe text-only)."""
    # A large pixel slogan reads better than a bigger mark over a small text slogan.
    for word_rows, slogan_rows in ((6, 4), (5, 4), (6, 0), (5, 0), (4, 0), (3, 0), (2, 0)):
        lock = Lockup(brand, word_rows, slogan_rows, cols)
        if lock.width <= cols - 4 and lock.height <= rows:
            return lock
    return Lockup(brand, 0, 0, cols)


def place(lockup, gap_top, gap_bottom):
    """Top row (0-based) of the lockup centred in rows [gap_top, gap_bottom]."""
    space = gap_bottom - gap_top + 1
    return gap_top + max(0, (space - lockup.height) // 2)


def home_rows(lockup, top, reveal=1.0, pal=None):
    """Render the home lockup -> {row: [(col, [(char, rgb, bold), ...]), ...]}.

    `reveal` (0..1) fades in the slogan block; the mark is always fully drawn.
    """
    pal = pal or palette()
    brand = lockup.brand
    mark = lockup.mark
    out = {}

    def put(row, col, cells):
        out.setdefault(row, []).append((col, cells))

    if mark:
        x = lockup.centre(mark.logo_cols)
        for r, line in enumerate(mark.logo_bits()):
            cells = [(OCTANTS[b], mark.logo_color(r, c), False) if b else (' ', None, False)
                     for c, b in enumerate(line)]
            put(top + lockup.logo_top + r, x, cells)
        x = lockup.centre(mark.word_cols)
        for r, line in enumerate(mark.word_bits()):
            put(top + lockup.word_top + r, x, [(OCTANTS[b], pal['ink'], False) for b in line])

    def fade(colour, delay, span=0.45):
        t = (reveal - delay) / span
        return mix(pal['bg'], colour, t) if t < 1 else colour

    if lockup.slogan_cells:
        x = lockup.centre(lockup.slogan_cols)
        for r, line in enumerate(lockup.slogan_cells):
            cells = []
            for c, b in enumerate(line):
                t = (reveal - 0.45 * c / max(1, len(line))) / 0.4
                cells.append((OCTANTS[b], mix(pal['bg'], pal['soft'], t), False) if b and t > 0
                             else (' ', None, False))
            put(top + lockup.slogan_top + r, x, cells)
    else:
        text = brand.slogan
        x = lockup.centre(text_width(text))
        put(top + lockup.slogan_top, x, [(ch, fade(pal['ink'], 0.08 * i / len(text)), True)
                                         for i, ch in enumerate(text)])
    tag = ' '.join(brand.tagline)
    put(top + lockup.tag_top, lockup.centre(len(tag)), [(ch, fade(pal['muted'], 0.3), False) for ch in tag])
    line = platform_line(brand)
    cells = []
    for ch in line:
        colour = pal['rule'] if ch == '─' else pal['red']
        cells.append((ch, fade(colour, 0.45), False))
    put(top + lockup.platform_top, lockup.centre(text_width(line)), cells)
    return out


def sgr(rgb, bold=False):
    return '\x1b[%s38;2;%d;%d;%dm' % ('1;' if bold else '22;', rgb[0], rgb[1], rgb[2])


def render_run(cells):
    """[(char, rgb, bold)] -> string with minimal SGR changes. Wide chars occupy one entry."""
    out, last = [], None
    for ch, rgb, bold in cells:
        if rgb is None:
            out.append(ch)
            continue
        key = (rgb, bold)
        if key != last:
            out.append(sgr(rgb, bold))
            last = key
        out.append(ch)
    return ''.join(out)


def mini_logo(cols=9, rows=3, height_px=12.5, shrink=0.8, threshold=0.42):
    """A tiny mark for a header badge (where Claude Code's mascot sits): rows of (char, rgb).

    At this size the petals merge, so each one is shrunk toward its own centre first,
    which keeps the gaps between them open.
    """
    lb = ART['logo_bbox']
    petals = []
    for poly in ART['petals']:
        cx = sum(p[0] for p in poly) / len(poly)
        cy = sum(p[1] for p in poly) / len(poly)
        petals.append([(cx + (x - cx) * shrink, cy + (y - cy) * shrink) for x, y in poly])
    ky = height_px / (lb[3] - lb[1])
    kx = ky * SUB_ASPECT
    ox = lb[0] - ((cols * 2 - (lb[2] - lb[0]) * kx) / 2) / kx
    oy = lb[1] - ((rows * 4 - height_px) / 2) / ky
    grid = coverage(petals, cols * 2, rows * 4, ox, oy, kx, ky, samples=8)
    out = []
    for r, line in enumerate(octant_cells(grid, threshold)):
        out.append([(OCTANTS[b], gradient(ox + (c * 2 + 1) / kx, oy + (r * 4 + 2) / ky)) for c, b in enumerate(line)])
    return out
