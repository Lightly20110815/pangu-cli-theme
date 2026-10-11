"""Opening animation: the Huawei flower blooms out of code.

Timeline of the bloom (seconds, after the prelude):
  0.00  a red cursor blinks where the petals meet
  0.30  the bud grows out of the cursor and fans open, inner pair first; the leading
        edge of every petal is drawn in code glyphs that settle into solid colour
  1.15  HUAWEI decodes from random code glyphs, left to right
  2.05  a light sweep crosses the mark
  end   hand-off: the mark stays exactly where the home page draws it

With a prelude line (Claude Code: 「从一行代码」) the line types out first where the petals
will meet, then breaks into 0s and 1s that rush into the point the bud grows from.
"""
import math
import random
import time

from . import art

CODE = '0101010110{}<>/=;+*#'
HOT = (255, 104, 88)
FLASH = (255, 255, 255)
SHINE = (255, 236, 226)
PRELUDE = 0.55  # how much later the bloom starts when a line is typed first


def ease_out_cubic(t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return 1 - (1 - t) ** 3


def ease_out_back(t, s=1.25):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    t -= 1
    return t * t * ((s + 1) * t + s) + 1


def ease_in_out(t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return t * t * (3 - 2 * t)


def home_anchor(brand, cols, rows):
    """Where the overlay will draw the lockup once the app is up (predicted chrome)."""
    bottom_start = rows - 5
    lock = art.choose(brand, cols, bottom_start - 1 - art.HOME_TOP)
    return lock, art.place(lock, art.HOME_TOP, bottom_start - 2)


class Bloom:
    def __init__(self, cols, rows, pal, brand, line=None, bloom_length=2.95):
        self.cols, self.rows, self.pal = cols, rows, pal
        self.line = line
        self.prelude = PRELUDE if line else 0.0
        self.duration = bloom_length + self.prelude
        self.lock, self.top = home_anchor(brand, cols, rows)
        self.mark = mark = self.lock.mark
        self.ok = mark is not None
        if not self.ok:
            return
        self.lx = self.lock.centre(mark.logo_cols)
        self.ly = self.top + self.lock.logo_top
        self.wx = self.lock.centre(mark.word_cols)
        self.wy = self.top + self.lock.word_top
        ox, oy = mark.svg_to_cell(*art.ART['origin'])
        # Origin in screen sub-pixels; physical units scale y by the sub-pixel aspect.
        self.ox = self.lx * 2 + ox
        self.oy = (self.ly * 4 + oy) * art.SUB_ASPECT
        self.petals = []
        lb = art.ART['logo_bbox']
        cx_axis = (lb[0] + lb[2]) / 2
        for poly in art.ART['petals']:
            pts = self._sample(poly)
            if not pts:
                continue
            mx = sum(p[0] for p in pts) / len(pts)
            my = sum(p[1] for p in pts) / len(pts)
            angle = math.atan2(mx, -my)  # from straight up, clockwise positive
            centroid_x = sum(p[0] for p in poly) / len(poly)
            self.petals.append({'pts': pts, 'angle': angle, 'side': centroid_x > cx_axis})
        # Inner pair opens first, the low outer pair last.
        order = sorted({round(abs(p['angle']), 1) for p in self.petals})
        for p in self.petals:
            p['rank'] = order.index(round(abs(p['angle']), 1))
        self.final = mark.logo_bits()
        self.word = mark.word_bits()
        rng = random.Random(7)
        self.word_lock = {}
        for r, line_bits in enumerate(self.word):
            for c, bits in enumerate(line_bits):
                if bits:
                    self.word_lock[(r, c)] = 1.15 + 0.62 * c / max(1, len(line_bits)) + rng.uniform(0, 0.1)
        self.born = {}
        self.rng = random.Random()
        # Region we repaint every frame (the bud overshoots the logo box a little).
        self.x0 = max(0, min(self.lx, self.wx) - 2)
        self.x1 = min(cols, max(self.lx + mark.logo_cols, self.wx + mark.word_cols) + 2)
        self.y0 = max(0, self.ly - 1)
        self.y1 = min(rows, self.wy + mark.word_rows + 1)

    def _sample(self, poly):
        """Points inside a petal at 2x sub-pixel density, relative to the origin, physical units."""
        mark = self.mark
        kx, ky = mark.kx * 2, mark.ky_sub * 2
        ox, oy = mark.logo_ox, mark.logo_oy
        edges = []
        n = len(poly)
        for k in range(n):
            x0, y0 = poly[k]
            x1, y1 = poly[(k + 1) % n]
            x0, y0, x1, y1 = (x0 - ox) * kx, (y0 - oy) * ky, (x1 - ox) * kx, (y1 - oy) * ky
            if y0 != y1:
                edges.append((x0, y0, x1, y1) if y0 < y1 else (x1, y1, x0, y0))
        ymin = int(min(e[1] for e in edges))
        ymax = int(max(e[3] for e in edges)) + 1
        pts = []
        base_x = self.lx * 2
        base_y = self.ly * 4
        for j in range(ymin, ymax):
            yy = j + 0.5
            xs = sorted(x0 + (yy - y0) * (x1 - x0) / (y1 - y0) for x0, y0, x1, y1 in edges if y0 <= yy < y1)
            for a, b in zip(xs[::2], xs[1::2]):
                for i in range(math.ceil(a - 0.5), math.floor(b - 0.5) + 1):
                    sx = base_x + (i + 0.5) / 2
                    sy = base_y + yy / 2
                    pts.append((sx - self.ox, sy * art.SUB_ASPECT - self.oy))
        return pts

    def _petal_cells(self, t):
        """Octant bits per screen cell for the blooming petals at time t."""
        grow = ease_out_cubic((t - 0.30) / 0.75)
        if grow <= 0:
            return {}
        scale = 0.22 + 0.78 * grow
        counts = {}
        aspect = art.SUB_ASPECT
        ox, oy = self.ox, self.oy
        for petal in self.petals:
            open_ = ease_out_back((t - 0.36 - 0.075 * petal['rank']) / 0.82)
            delta = -petal['angle'] * 0.94 * (1 - open_)
            c, s = math.cos(delta) * scale, math.sin(delta) * scale
            get = counts.get
            for px, py in petal['pts']:
                x = int(ox + px * c - py * s)
                y = int((oy + px * s + py * c) / aspect)
                key = (y, x)
                counts[key] = get(key, 0) + 1
        need = max(1, round(2.0 / (scale * scale) * 0.95))
        cells = {}
        for (y, x), n in counts.items():
            if n >= need and x >= 0 and y >= 0:
                key = (y >> 2, x >> 1)
                cells[key] = cells.get(key, 0) | (1 << ((y & 3) * 2 + (x & 1)))
        return cells

    def frame(self, t):
        """Cells {(row, col): (char, rgb)} at time t."""
        if self.line and t < 0.30 + self.prelude:
            return self._prelude(t)
        return self._bloom(t - self.prelude)

    def _prelude(self, t):
        """The typed line, then its collapse into the point the petals grow from."""
        out = {}
        pal = self.pal
        row = int(self.oy / art.SUB_ASPECT) >> 2
        hub = int(self.ox) >> 1
        width = art.text_width(self.line)
        left = hub - width // 2
        red = tuple(art.ART['gradient']['stops'][1][1])
        typed = min(len(self.line), int(max(0.0, t - 0.06) / 0.07))
        if t < 0.62:
            x = left
            for ch in self.line[:typed]:
                out[(row, x)] = (ch, pal['ink'])
                x += art.text_width(ch)
            if typed < len(self.line) or int(t / 0.16) % 2 == 0:
                out[(row, x)] = ('▌', red)
            return out
        p = ease_in_out((t - 0.62) / 0.21)
        for k in range(width):
            x0 = left + k
            x = round(x0 + (hub - x0) * p)
            out[(row, x)] = (self.rng.choice('01'), art.mix(pal['ink'], HOT, p))
        if p > 0.85:
            out[(row, hub)] = ('█', red)
        return out

    def _bloom(self, t):
        out = {}
        pal = self.pal
        mark = self.mark
        settled = t >= 1.62
        if t < 0.30:
            on = t < 0.11 or 0.19 <= t
            if on:
                out[(int(self.oy / art.SUB_ASPECT) >> 2, int(self.ox) >> 1)] = ('█', art.ART['gradient']['stops'][1][1])
        elif settled:
            for r, line in enumerate(self.final):
                for c, bits in enumerate(line):
                    if bits:
                        out[(self.ly + r, self.lx + c)] = (art.OCTANTS[bits], mark.logo_color(r, c))
        else:
            cells = self._petal_cells(t)
            heat = ease_out_cubic((t - 0.3) / 1.1)
            deep = tuple(art.ART['gradient']['stops'][2][1])
            born = self.born
            for key in list(born):
                if key not in cells:
                    del born[key]
            for key, bits in cells.items():
                row, col = key
                first = born.setdefault(key, t)
                base = mark.logo_color(min(max(row - self.ly, 0), mark.logo_rows - 1),
                                       min(max(col - self.lx, 0), mark.logo_cols - 1))
                colour = art.mix(deep, base, heat)
                age = t - first
                # The bud condenses out of code; afterwards only moving edges sparkle.
                if age < 0.12 and (bits != 255 or t < 0.52):
                    out[key] = (self.rng.choice(CODE), art.mix(HOT, colour, age / 0.12))
                else:
                    out[key] = (art.OCTANTS[bits], art.mix(HOT, colour, age / 0.22))
        for (r, c), lock in self.word_lock.items():
            if t < lock - 0.34:
                continue
            key = (self.wy + r, self.wx + c)
            if t < lock:
                out[key] = (self.rng.choice(CODE), art.mix(pal['bg'], (190, 70, 74), (t - lock + 0.34) / 0.2))
            else:
                out[key] = (art.OCTANTS[self.word[r][c]], art.mix(FLASH, pal['ink'], (t - lock) / 0.22))
        sweep = (t - 2.02) / 0.7
        if 0 < sweep < 1:
            centre = -0.25 + 1.5 * ease_in_out(sweep)
            span = max(1, self.x1 - self.x0)
            height = max(1, self.y1 - self.y0)
            for key, (ch, colour) in out.items():
                u = ((key[1] - self.x0) / span + (1 - (key[0] - self.y0) / height) * 0.45) / 1.45
                glow = 1 - abs(u - centre) / 0.085
                if glow > 0:
                    out[key] = (ch, art.mix(colour, SHINE, 0.7 * glow * glow))
        return out

    def ansi(self, cells):
        parts = ['\x1b[?2026h']
        for row in range(self.y0, self.y1):
            run = []
            col = self.x0
            while col < self.x1:
                ch, colour = cells.get((row, col), (' ', None))
                run.append((ch, colour, False))
                col += art.text_width(ch)
            parts.append('\x1b[%d;%dH' % (row + 1, self.x0 + 1))
            parts.append(art.render_run(run))
        parts.append('\x1b[0m\x1b[?2026l')
        return ''.join(parts)


class Player:
    """The intro as a frame source, so a launcher can run it while the app starts."""

    FRAME = 1 / 40

    def __init__(self, size_fn, pal, brand, line=None, bloom_length=2.95, reduced=False):
        self.size_fn, self.pal, self.reduced = size_fn, pal, reduced
        self.brand, self.line, self.bloom_length = brand, line, bloom_length
        cols, rows = size_fn()
        self.scene = self._scene(cols, rows)
        self.length = 1.0 if reduced else self.scene.duration
        self.start = None
        self.done = not self.scene.ok

    def _scene(self, cols, rows):
        return Bloom(cols, rows, self.pal, self.brand, self.line, self.bloom_length)

    def frame(self):
        """Bytes for the frame due now; sets `done` once the final frame is returned."""
        now = time.monotonic()
        prefix = b''
        if self.start is None:
            self.start = now
            prefix = b'\x1b[2J'
        t = now - self.start
        size = self.size_fn()
        if size != (self.scene.cols, self.scene.rows):
            self.scene = self._scene(size[0], size[1])
            prefix += b'\x1b[2J'
            if not self.scene.ok:
                self.done = True
                return prefix
        end = self.scene.duration
        if t >= self.length:
            self.done = True
            t = end
        elif self.reduced:
            t = end
        # The app's start-up output may show the cursor again; keep it hidden while we draw.
        return prefix + b'\x1b[?25l' + self.scene.ansi(self.scene.frame(t)).encode('utf-8')
