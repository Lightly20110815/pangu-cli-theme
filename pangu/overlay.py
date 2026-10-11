"""Home page drawn into the blank middle of a full-screen (alternate-screen) TUI.

Codex (ratatui) and Claude Code's fullscreen renderer only repaint cells they believe changed,
so cells they think are blank keep whatever we draw there. The overlay follows the app's
output to know which rows it uses, draws the lockup only on rows that are blank to it, and
wipes an art row right before the app writes into it. Inserted sequences are wrapped in
DECSC/DECRC so the app's cursor and colours are untouched, and placed inside its own
synchronized-update frames.

Anything the tracker does not understand (scrolling, insert/delete line, a cursor save by the
app inside the alternate screen) wipes the art and pauses the overlay until the app clears
the screen again. Apps that stay on the main screen (inline renderers) only get the header
branding.

Each app has a subclass for its header branding and for what counts as "header" above the
home (Claude Code's startup notices, Codex's "To get started" list).
"""
import os
import re
import time
import unicodedata
from functools import lru_cache

from . import art

TEXT = re.compile(rb'[^\x00-\x1f\x7f]+')
REVEAL_SECONDS = 1.1
KEY_ESCAPES = re.compile(rb'\x1b\[[0-9;:?<>=]*[ -/]*[@-~]|\x1bO.|\x1b[\]P_^X][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b.?')
DEBUG = os.environ.get('PANGU_DEBUG')
ASCII_CONTENT = bytes(0 if b == 0x20 else 1 for b in range(256))
ASCII_FILLED = bytes(1 for _ in range(256))


def debug(*parts):
    if DEBUG:
        with open(DEBUG, 'a') as f:
            f.write('%.3f %s\n' % (time.monotonic(), ' '.join(str(p) for p in parts)))


@lru_cache(maxsize=4096)
def cwidth(ch):
    o = ord(ch)
    if o < 0x300:
        return 1
    if unicodedata.combining(ch) or 0x200b <= o <= 0x200f or 0xfe00 <= o <= 0xfe0f or 0xe0100 <= o <= 0xe01ef:
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1


def partial_suffix(data, word):
    """Length of the longest proper prefix of `word` that `data` ends with."""
    for k in range(min(len(word) - 1, len(data)), 0, -1):
        if data.endswith(word[:k]):
            return k
    return 0


class Overlay:
    # The app's own name in its output; a chunk ending in part of it is held back so the
    # branding can replace it whole.
    NAME = b''

    def __init__(self, cols, rows, brand, in_alt=False, reveal=False, pal=None, strict=False):
        self.brand = brand
        self.pal = pal or art.palette()
        self.carry = b''
        self.alt = in_alt
        self.drop_first_alt = in_alt
        # The intro left us on the alternate screen. If the app draws without entering it
        # (inline renderer), step back to the main screen first so the session keeps its
        # scrollback.
        self.awaiting_app = in_alt
        self.entered_alt = False
        self.sync = False
        self.dirty = False
        self.disabled = False
        self.bg = False
        self.reverse = False
        self.saved = (0, 0)
        self.reveal_from = None
        self.want_reveal = reveal
        # While the intro is still on screen nothing we paint is seen yet: hold the fade-in.
        self.reveal_hold = reveal
        # Where in feed()'s output the app's first alternate-screen entry was replaced, so the
        # launcher can let the start-up queries through and hold back the first frame.
        self.split_request = False
        self.split_at = None
        self.passthrough_log = bytearray()
        self.dynamic_rows = set()
        self.rows_used = set()
        self.resize(cols, rows)

    # ------------------------------------------------------------- per-app hooks
    def rebrand(self, data):
        return data

    def note_input(self, data):
        """Keys the person typed (passed on by the launcher)."""

    def _layout(self):
        """(top_end, bottom_start) if the screen is an empty session's home, else None."""
        return self._scan(4)

    def _new_screen(self):
        """The app cleared the whole screen."""

    def _saw_text(self, run):
        """A run of printable bytes is about to be drawn at (cy, cx)."""

    # ----------------------------------------------------------------- geometry
    def resize(self, cols, rows):
        self.cols, self.rows = cols, rows
        self.grid = [bytearray(cols) for _ in range(rows)]
        self.count = [0] * rows
        self.cx = self.cy = 0
        self.known = False
        self.visible = set()
        self.anchor = None

    def _clear_rows(self, start, stop, filled=False):
        for r in range(max(0, start), min(self.rows, stop)):
            self.grid[r][:] = (ASCII_FILLED[:self.cols] if filled else bytes(self.cols))
            self.count[r] = self.cols if filled else 0

    def _set_span(self, r, c0, c1, filled):
        if not 0 <= r < self.rows:
            return
        c0, c1 = max(0, c0), min(self.cols, c1)
        if c1 <= c0:
            return
        row = self.grid[r]
        before = row.count(1, c0, c1)
        row[c0:c1] = (b'\x01' if filled else b'\x00') * (c1 - c0)
        self.count[r] += (c1 - c0 if filled else 0) - before

    def _scan(self, limit, extend=None):
        """Split the used rows into a header block (rows <= limit, small gaps) and a bottom
        block, with nothing in between. `extend(top_end, used)` may grow the header."""
        used = [r for r in range(self.rows) if self.count[r]]
        if len(used) < 2 or used[0] > 2:
            return None
        top_end = used[0]
        for r in used[1:]:
            if r <= limit and r - top_end <= 2:
                top_end = r
            else:
                break
        if extend:
            top_end = extend(top_end, used)
        bottom_start = used[-1]
        for r in reversed(used[:-1]):
            if r > top_end and bottom_start - r <= 2:
                bottom_start = r
            else:
                break
        if bottom_start <= top_end or any(top_end < r < bottom_start for r in used):
            return None
        return top_end, bottom_start

    # ------------------------------------------------------------------ painting
    def _wrap(self, body):
        return ('\x1b7\x1b[0m' + body + '\x1b[0m\x1b8').encode('utf-8') if body else b''

    def _erase(self, rows):
        rows = sorted(r for r in rows if r in self.visible)
        if not rows:
            return b''
        self.visible.difference_update(rows)
        return self._wrap(''.join('\x1b[%d;1H\x1b[2K' % (r + 1) for r in rows))

    def _erase_all(self):
        return self._erase(list(self.visible))

    def _reveal(self):
        if not self.want_reveal:
            return 1.0
        if self.reveal_from is None:
            return 0.0
        return min(1.0, (time.monotonic() - self.reveal_from) / REVEAL_SECONDS)

    def release(self):
        """The intro has handed over: start the slogan fade-in if the home is up."""
        self.reveal_hold = False
        if self.want_reveal and self.visible and self.reveal_from is None:
            self.reveal_from = time.monotonic()

    def _paint(self, rows):
        if not rows or not self.anchor:
            return b''
        lock, top, _ = self.anchor
        content = art.home_rows(lock, top, self._reveal(), self.pal)
        parts = []
        for r in sorted(rows):
            parts.append('\x1b[%d;1H\x1b[2K' % (r + 1))
            for col, cells in content.get(r, []):
                parts.append('\x1b[%d;%dH' % (r + 1, col + 1))
                parts.append(art.render_run(cells))
            self.visible.add(r)
        return self._wrap(''.join(parts))

    def _frame_end(self):
        """Bring the art in line with the screen the app just finished drawing."""
        if self.disabled or not self.alt:
            return b''
        if not self.known:
            return self._erase_all()
        layout = self._layout()
        if layout is None:
            if DEBUG:
                debug('no home layout; used rows', [r for r in range(self.rows) if self.count[r]])
            return self._erase_all()
        top_end, bottom_start = layout
        if DEBUG:
            debug('frame', layout, 'used', [r for r in range(self.rows) if self.count[r]])
        if self.anchor and top_end + 2 > self.anchor[1]:
            out = self._erase_all()
            self.anchor = None
            return out + self._frame_end()
        if self.anchor is None or (not self.visible and self.anchor[2] != (self.cols, self.rows)):
            # Fixed top edge (the header is at most rows 1-3) so the anchor matches the intro's
            # prediction whether or not every header line has arrived yet.
            gap_top = max(top_end + 2, art.HOME_TOP)
            lock = art.choose(self.brand, self.cols, bottom_start - 1 - gap_top)
            top = art.place(lock, gap_top, bottom_start - 2)
            self.anchor = (lock, top, (self.cols, self.rows))
            self.rows_used = set(art.home_rows(lock, top, 1.0, self.pal))
            self.dynamic_rows = {r for r in self.rows_used if r >= top + lock.slogan_top}
        want = {r for r in self.rows_used if top_end < r < bottom_start - 1 and not self.count[r]}
        out = self._erase(self.visible - want)
        missing = want - self.visible
        if DEBUG:
            debug('want', sorted(want), 'missing', sorted(missing), 'visible', sorted(self.visible))
        if missing and self.want_reveal and self.reveal_from is None and not self.reveal_hold:
            self.reveal_from = time.monotonic()
        return out + self._paint(missing)

    def tick(self):
        """Timer-driven repaint for the slogan fade-in. Returns bytes to write (may be empty)."""
        if self.reveal_from is None or self.sync or self.carry or not self.visible:
            return b''
        reveal = self._reveal()
        rows = self.visible & self.dynamic_rows
        out = self._paint(rows)
        if reveal >= 1.0:
            self.reveal_from = None
            self.want_reveal = False
        return b'\x1b[?2026h' + out + b'\x1b[?2026l' if out else b''

    def animating(self):
        return self.reveal_from is not None

    # ------------------------------------------------------------------- parsing
    def feed(self, chunk):
        """App output in, terminal output out (with the overlay woven in)."""
        data = self.carry + chunk
        self.carry = b''
        hold = partial_suffix(data, self.NAME) if self.NAME else 0
        if hold:
            data, held = data[:-hold], data[-hold:]
        else:
            held = b''
        data = self.rebrand(data)
        out = self._parse(data)
        self.carry += held
        if not self.sync and self.dirty:
            extra = self._frame_end()
            self.dirty = False
            if extra:
                out += b'\x1b[?2026h' + extra + b'\x1b[?2026l'
        if not self.entered_alt:
            self.passthrough_log += out
            del self.passthrough_log[:-262144]
        return out

    def _parse(self, data):
        out = []
        emit = 0
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            if b == 0x1b:
                j = self._seq_end(data, i)
                if j < 0:
                    self.carry = data[i:]
                    out.append(data[emit:i])
                    return b''.join(out)
                pre, repl = self._escape(data[i:j])
                self._mark_split(out, i - emit)
                if pre or repl is not None:
                    out.append(data[emit:i])
                    if pre:
                        out.append(pre)
                    out.append(data[i:j] if repl is None else repl)
                    emit = j
                i = j
            elif b < 0x20 or b == 0x7f:
                pre = self._control(b)
                self._mark_split(out, i - emit)
                if pre:
                    out.append(data[emit:i])
                    out.append(pre)
                    emit = i
                i += 1
            else:
                m = TEXT.match(data, i)
                j = m.end()
                run = data[i:j]
                if j == n and run[-1] >= 0x80:
                    # Possibly a split UTF-8 sequence: keep the incomplete tail for next time.
                    k = len(run)
                    back = 0
                    while back < 4 and k - back - 1 >= 0 and 0x80 <= run[k - back - 1] < 0xc0:
                        back += 1
                    lead = run[k - back - 1] if k - back - 1 >= 0 else 0
                    need = 2 if lead >= 0xc0 else 0
                    need = 3 if lead >= 0xe0 else need
                    need = 4 if lead >= 0xf0 else need
                    if need and back + 1 < need:
                        cut = k - back - 1
                        self.carry = run[cut:]
                        run = run[:cut]
                        j = i + cut
                        n = j
                pre = self._text(run)
                self._mark_split(out, i - emit)
                if pre:
                    out.append(data[emit:i])
                    out.append(pre)
                    emit = i
                i = j
        out.append(data[emit:n])
        return b''.join(out)

    def _mark_split(self, out, pending):
        """Record where (in this feed's output) the app's first screen output starts."""
        if self.split_request:
            self.split_request = False
            self.split_at = sum(len(x) for x in out) + pending

    @staticmethod
    def _seq_end(data, i):
        n = len(data)
        if i + 1 >= n:
            return -1
        c = data[i + 1]
        if c == 0x5b:  # CSI
            j = i + 2
            while j < n and 0x20 <= data[j] <= 0x3f:
                j += 1
            if j >= n:
                return -1
            return j + 1
        if c in (0x5d, 0x50, 0x5f, 0x5e, 0x58):  # OSC DCS APC PM SOS
            st = data.find(b'\x1b\\', i + 2)
            if c == 0x5d:
                bel = data.find(b'\x07', i + 2)
                if bel >= 0 and (st < 0 or bel < st):
                    return bel + 1
            return st + 2 if st >= 0 else -1
        if c in b'()*+-./# %':
            return i + 3 if i + 2 < n else -1
        return i + 2

    # ------------------------------------------------------------------ handlers
    def _touch(self, rows):
        hit = [r for r in rows if r in self.visible]
        if hit and DEBUG:
            debug('touch', hit, 'cursor', (self.cy, self.cx))
        self.dirty = True
        return self._erase(hit) if hit else b''

    def _uncertain(self):
        if DEBUG:
            debug('uncertain at', (self.cy, self.cx))
        self.known = False
        self.dirty = True
        return self._erase_all()

    def _leave_intro_screen(self):
        self.split_request = True
        self.awaiting_app = False
        self.drop_first_alt = False
        self.alt = False
        self.known = False
        self.visible.clear()
        return b'\x1b[?1049l'

    def _text(self, run):
        if self.awaiting_app:
            return self._leave_intro_screen()
        self._saw_text(run)
        if self.cx >= self.cols:
            self.cx = 0
            self.cy += 1
        if run.isascii():
            width = len(run)
            first, last = self.cy, self.cy + (self.cx + width - 1) // self.cols
            pre = self._touch(range(first, last + 1))
            if last >= self.rows:
                pre += self._uncertain()
            table = ASCII_FILLED if (self.bg or self.reverse) else ASCII_CONTENT
            pos = 0
            while pos < width and self.cy < self.rows:
                take = min(width - pos, self.cols - self.cx)
                piece = run[pos:pos + take].translate(table)
                row = self.grid[self.cy]
                before = row.count(1, self.cx, self.cx + take)
                row[self.cx:self.cx + take] = piece
                self.count[self.cy] += piece.count(1) - before
                pos += take
                self.cx += take
                if pos < width:
                    self.cx = 0
                    self.cy += 1
            self.cy = min(self.cy, self.rows - 1)
            return pre
        text = run.decode('utf-8', 'replace')
        width = sum(cwidth(ch) for ch in text)
        first, last = self.cy, self.cy + (self.cx + max(width, 1) - 1) // self.cols
        pre = self._touch(range(first, last + 1))
        if last >= self.rows:
            pre += self._uncertain()
        filled = self.bg or self.reverse
        for ch in text:
            w = cwidth(ch)
            if w == 0:
                continue
            if self.cx + w > self.cols:
                self.cx = 0
                self.cy += 1
                if self.cy >= self.rows:
                    self.cy = self.rows - 1
            self._set_span(self.cy, self.cx, self.cx + w, filled or ch != ' ')
            self.cx += w
        return pre

    def _control(self, b):
        if self.awaiting_app and b in (0x0a, 0x0b, 0x0c, 0x0d, 0x08, 0x09):
            return self._leave_intro_screen()
        if b in (0x0a, 0x0b, 0x0c):
            if self.cy + 1 >= self.rows:
                return self._uncertain()
            self.cy += 1
        elif b == 0x0d:
            self.cx = 0
        elif b == 0x08:
            self.cx = max(0, self.cx - 1)
        elif b == 0x09:
            self.cx = min(self.cols - 1, (self.cx // 8 + 1) * 8)
        return b''

    def _sgr(self, raw):
        params = raw.split(b';') if raw else [b'0']
        i = 0
        while i < len(params):
            token = params[i]
            colon = b':' in token
            try:
                v = int(token.split(b':')[0] or b'0')
            except ValueError:
                v = -1
            if v == 0:
                self.bg = self.reverse = False
            elif v == 7:
                self.reverse = True
            elif v == 27:
                self.reverse = False
            elif 40 <= v <= 47 or 100 <= v <= 107:
                self.bg = True
            elif v == 49:
                self.bg = False
            if v in (38, 48, 58) and not colon:
                mode = params[i + 1] if i + 1 < len(params) else b''
                skip = 2 if mode == b'5' else 4 if mode == b'2' else 0
                if v == 48:
                    self.bg = True
                i += skip
            elif v == 48:
                self.bg = True
            i += 1

    def _save_cursor(self):
        if not (self.alt and self.entered_alt):
            self.saved = (self.cx, self.cy)
            return b''
        # A cursor save by the app inside the alternate screen would collide with ours.
        self.disabled = True
        return self._erase_all()

    def _escape(self, seq):
        """Returns (bytes to insert before seq, replacement for seq or None to keep it)."""
        kind = seq[1]
        if kind == 0x5b:
            return self._csi(seq)
        if kind == 0x37:  # DECSC
            return self._save_cursor(), None
        if kind == 0x38:  # DECRC
            self.cx, self.cy = self.saved
            return b'', None
        if kind == 0x4d:  # RI
            if self.cy == 0:
                return self._uncertain(), None
            self.cy -= 1
        elif kind in (0x44, 0x45):  # IND, NEL
            if self.cy + 1 >= self.rows:
                return self._uncertain(), None
            self.cy += 1
            if kind == 0x45:
                self.cx = 0
        elif kind == 0x63:  # RIS
            pre = self._erase_all()
            self.alt = False
            self.known = False
            return pre, None
        return b'', None

    def _csi(self, seq):
        body = seq[2:-1]
        final = seq[-1]
        priv = body[:1] if body[:1] in (b'?', b'<', b'>', b'=') else b''
        if priv:
            body = body[1:]
        inter = b''
        while body and 0x20 <= body[-1] <= 0x2f:
            inter = body[-1:] + inter
            body = body[:-1]
        if inter:
            return b'', None
        if final == 0x6d and not priv:  # SGR
            self._sgr(body)
            return b'', None
        try:
            nums = [int(x.split(b':')[0]) if x else 0 for x in body.split(b';')] if body else []
        except ValueError:
            return (self._uncertain() if not priv else b''), None
        a = nums[0] if nums else 0
        if priv == b'?':
            if final in (0x68, 0x6c):
                return self._modes(nums, final == 0x68)
            return b'', None
        if priv:
            return b'', None
        if self.awaiting_app and final in b'HfABCDEFG`dJKXL@PMST':
            return self._leave_intro_screen(), None
        n1 = max(1, a)
        rows, cols = self.rows, self.cols
        if final in (0x48, 0x66):  # CUP
            self.cy = min(rows - 1, max(0, (a or 1) - 1))
            self.cx = min(cols - 1, max(0, ((nums[1] if len(nums) > 1 else 0) or 1) - 1))
        elif final == 0x41:
            self.cy = max(0, self.cy - n1)
        elif final in (0x42, 0x65):
            self.cy = min(rows - 1, self.cy + n1)
        elif final in (0x43, 0x61):
            self.cx = min(cols - 1, self.cx + n1)
        elif final == 0x44:
            self.cx = max(0, self.cx - n1)
        elif final == 0x45:
            self.cy, self.cx = min(rows - 1, self.cy + n1), 0
        elif final == 0x46:
            self.cy, self.cx = max(0, self.cy - n1), 0
        elif final in (0x47, 0x60):
            self.cx = min(cols - 1, n1 - 1)
        elif final == 0x64:
            self.cy = min(rows - 1, n1 - 1)
        elif final == 0x4a:  # ED
            filled = self.bg or self.reverse
            if a == 0:
                pre = self._touch(range(self.cy, rows))
                self._set_span(self.cy, self.cx, cols, filled)
                self._clear_rows(self.cy + 1, rows, filled)
                if self.cy == 0 and self.cx == 0 and self.alt:
                    self.known = True
                    self._new_screen()
            elif a == 1:
                pre = self._touch(range(0, self.cy + 1))
                self._clear_rows(0, self.cy, filled)
                self._set_span(self.cy, 0, self.cx + 1, filled)
            elif a == 2:
                pre = self._touch(range(rows))
                self._clear_rows(0, rows, filled)
                if self.alt:
                    self.known = True
                    self._new_screen()
            else:
                return b'', None
            return pre, None
        elif final == 0x4b:  # EL
            pre = self._touch([self.cy])
            filled = self.bg or self.reverse
            if a == 0:
                self._set_span(self.cy, self.cx, cols, filled)
            elif a == 1:
                self._set_span(self.cy, 0, self.cx + 1, filled)
            else:
                self._set_span(self.cy, 0, cols, filled)
            return pre, None
        elif final == 0x58:  # ECH
            pre = self._touch([self.cy])
            self._set_span(self.cy, self.cx, self.cx + n1, self.bg or self.reverse)
            return pre, None
        elif final == 0x72:  # DECSTBM: only a full-screen region is harmless
            top = a or 1
            bottom = (nums[1] if len(nums) > 1 else 0) or rows
            self.cx = self.cy = 0
            if top != 1 or bottom != rows:
                return self._uncertain(), None
        elif final == 0x73 and not body:
            return self._save_cursor(), None
        elif final == 0x75 and not body:
            self.cx, self.cy = self.saved
        elif final in (0x40, 0x50, 0x4c, 0x4d, 0x53, 0x54, 0x62):  # ICH DCH IL DL SU SD REP
            return self._uncertain(), None
        return b'', None

    def _modes(self, nums, on):
        pre, repl = b'', None
        for mode in nums:
            if mode in (1049, 1047, 47):
                if on:
                    self.awaiting_app = False
                    if self.drop_first_alt:
                        # Our intro is already on the alternate screen; entering again would
                        # overwrite the main screen's saved cursor. Clear instead.
                        self.drop_first_alt = False
                        self.split_request = True
                        repl = b'\x1b[2J'
                        self._clear_rows(0, self.rows)
                        self.known = True
                    else:
                        self.known = False
                    self.alt = True
                    self.entered_alt = True
                    self.visible.clear()
                else:
                    self.alt = False
                    self.known = False
                    self.visible.clear()
                self.dirty = True
            elif mode == 2026:
                if on:
                    self.sync = True
                else:
                    self.sync = False
                    if self.dirty:
                        self.dirty = False
                        pre += self._frame_end()
        if repl is not None and len(nums) > 1:
            repl = None  # mixed mode list: leave it alone
        return pre, repl


class CodexOverlay(Overlay):
    """Codex: `OpenAI Codex` in the header becomes `盘古 · Codex` (same width) with a red `>_`."""

    NAME = b'OpenAI Codex'
    NEW_NAME = '盘古 · Codex'.encode('utf-8')
    HEADER = re.compile(rb'\x1b\[38;2;\d+;\d+;\d+(;49)?m>_ ((?:\x1b\[[0-9;]*m)*)OpenAI Codex')
    # Codex prints a short "To get started..." command list under the header in some
    # directories; it belongs to the empty home (a user message never says this).
    HELP_MARK = b'To get started'
    HELP_SPAN = 7

    def resize(self, cols, rows):
        super().resize(cols, rows)
        self.help_row = None

    def rebrand(self, data):
        data = self.HEADER.sub(lambda m: b'\x1b[38;2;232;52;60' + (m.group(1) or b'') + b'm>_ '
                               + m.group(2) + self.NEW_NAME, data)
        return data.replace(self.NAME, self.NEW_NAME)

    def _saw_text(self, run):
        if self.HELP_MARK in run:
            self.help_row = self.cy

    def _new_screen(self):
        self.help_row = None

    def _layout(self):
        def help_block(top_end, used):
            if self.help_row is not None and top_end < self.help_row <= top_end + 3:
                return max([r for r in used if self.help_row <= r <= self.help_row + self.HELP_SPAN] or [top_end])
            return top_end
        return self._scan(4, help_block)


class ClaudeOverlay(Overlay):
    """Claude Code: `Claude Code` in the header and title becomes `盘古 · Code` (same width),
    and the mascot beside it a tiny Huawei flower."""

    NAME = b'Claude Code'
    NEW_NAME = '盘古 · Code'.encode('utf-8')
    HEADER = re.compile(rb'\x1b\[1mClaude Code')
    TITLE = re.compile(rb'(\x1b\]0;[^\x07\x1b]{0,64}?)Claude Code')
    # The three rows of the mascot beside the header, in the bytes Claude Code draws them with.
    MASCOT = [
        (re.compile(rb'\x1b\[38;2;\d+;\d+;\d+m \xe2\x96\x90(?:\x1b\[48;2;\d+;\d+;\d+m)?'
                    rb'\xe2\x96\x9b\xe2\x96\x88\xe2\x96\x88\xe2\x96\x88\xe2\x96\x9b\xe2\x96\x88'), 8),
        (re.compile(rb'\x1b\[38;2;\d+;\d+;\d+m\xe2\x96\x9d\xe2\x96\x9c(?:\x1b\[48;2;\d+;\d+;\d+m)?'
                    rb'(?:\xe2\x96\x88){5}(?:\x1b\[49m)?\xe2\x96\x88\xe2\x96\x80'), 9),
        (re.compile(rb'\x1b\[38;2;\d+;\d+;\d+m \xe2\x96\x9d\xe2\x96\x9d   \xe2\x96\x9d\xe2\x96\x9d '), 9),
    ]
    # Lowest row (0-based) a startup notice under the header may reach and still count as header.
    NOTICE_LIMIT = 10
    CLEAR_COMMANDS = ('/clear', '/reset', '/new')

    def __init__(self, cols, rows, brand, in_alt=False, reveal=False, pal=None, strict=False):
        # Until the person submits something, short notices under the header ("Using Opus ...
        # from settings", update notes) belong to the empty home; the home sits below them.
        # After a submission only those rows are allowed: anything new is the conversation.
        # `strict` starts in the second state (a prompt given on the command line).
        self.submitted = strict
        self.notice_end = 4 if strict else None
        # What the person is typing (to spot /clear) and when a clear was asked for.
        self.typed = ''
        self.fresh_pending = None
        self._mascot = None
        super().__init__(cols, rows, brand, in_alt, reveal, pal, strict)

    def _mascot_rows(self):
        if self._mascot is None:
            rows = []
            for (pattern, width), cells in zip(self.MASCOT, art.mini_logo()):
                run = art.render_run([(ch, rgb, False) for ch, rgb in cells[:width]])
                rows.append((pattern, ('\x1b[49m' + run).encode('utf-8')))
            self._mascot = rows
        return self._mascot

    def rebrand(self, data):
        if b'Claude Code' in data:
            data = self.HEADER.sub(b'\x1b[1m' + self.NEW_NAME, data)
            data = self.TITLE.sub(lambda m: m.group(1) + self.NEW_NAME, data)
        if b'\xe2\x96' in data:
            for pattern, replacement in self._mascot_rows():
                data = pattern.sub(replacement, data)
        return data

    def note_input(self, data):
        """Enter in the session submits; remember /clear so the home can come back."""
        if not (self.alt and self.entered_alt):
            return
        for ch in KEY_ESCAPES.sub(b'', data).decode('utf-8', 'ignore'):
            if ch == '\r':
                if self.typed.strip() in self.CLEAR_COMMANDS:
                    self.fresh_pending = time.monotonic()
                self.typed = ''
                self.submitted = True
            elif ch in '\x7f\x08':
                self.typed = self.typed[:-1]
            elif ch == '\x15' or ch == '\x03':
                self.typed = ''
            elif ch >= ' ':
                self.typed = (self.typed + ch)[-32:]

    def _new_screen(self):
        """A full clear: a fresh session (/clear) gets its startup notices back."""
        self.submitted = False
        self.notice_end = None

    def _layout(self):
        fresh = self.fresh_pending is not None and time.monotonic() - self.fresh_pending < 10
        if self.submitted and not fresh:
            limit = self.notice_end if self.notice_end is not None else 4
        else:
            limit = self.NOTICE_LIMIT
        layout = self._scan(limit)
        if layout is None:
            return None
        if fresh:
            # /clear left the header, its notices and the "❯ /clear" row: a new empty session.
            self.submitted = False
            self.fresh_pending = None
        if not self.submitted:
            self.notice_end = layout[0]
        return layout
