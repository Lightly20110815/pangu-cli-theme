"""The theme without a terminal: artwork, animation frames, overlay, command handling."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pangu import apps, art, intro, overlay  # noqa: E402

SIZES = [(80, 24), (100, 30), (120, 40), (160, 48), (244, 65)]


class ArtTest(unittest.TestCase):
    def test_glyph_tables(self):
        self.assertEqual(len(art.OCTANTS), 256)
        self.assertEqual(len(art.ART['octants']), 256)

    def test_lockup_fits(self):
        for brand in art.BRANDS.values():
            for cols, rows in SIZES:
                space = rows - 10
                lock = art.choose(brand, cols, space)
                self.assertLessEqual(lock.width, cols)
                top = art.place(lock, art.HOME_TOP, art.HOME_TOP + space)
                drawn = art.home_rows(lock, top)
                self.assertTrue(drawn)
                for row, parts in drawn.items():
                    self.assertGreaterEqual(row, top)
                    for col, cells in parts:
                        self.assertGreaterEqual(col, 0)
                        width = sum(art.text_width(ch) for ch, _, _ in cells)
                        self.assertLessEqual(col + width, cols)

    def test_slogans(self):
        self.assertEqual(art.BRANDS['codex'].slogan, '让想法，码上成真')
        self.assertEqual(art.BRANDS['claude'].slogan, '从一行代码，打开新的可能')

    def test_mini_logo(self):
        logo = art.mini_logo()
        self.assertEqual(len(logo), 3)
        self.assertTrue(all(len(row) == 9 for row in logo))


class IntroTest(unittest.TestCase):
    def test_frames_stay_on_screen(self):
        pal = art.palette()
        for app in apps.APPS.values():
            for cols, rows in SIZES:
                scene = intro.Bloom(cols, rows, pal, app.brand, app.intro_line, app.bloom_length)
                if (cols, rows) == (80, 24):
                    # Too small for the mark: the intro is skipped and the home is text only.
                    self.assertFalse(scene.ok)
                    continue
                self.assertTrue(scene.ok, (app.key, cols, rows))
                t = 0.0
                while t <= scene.duration:
                    cells = scene.frame(t)
                    for (r, c), (ch, rgb) in cells.items():
                        self.assertTrue(0 <= r < rows and 0 <= c < cols, (app.key, t, r, c))
                    scene.ansi(cells).encode('utf-8')
                    t += 0.1
                final = scene.frame(scene.duration)
                self.assertGreater(len(final), 50)

    def test_durations(self):
        claude, codex = apps.APPS['claude'], apps.APPS['codex']
        pal = art.palette()
        self.assertAlmostEqual(intro.Bloom(120, 40, pal, claude.brand, claude.intro_line, claude.bloom_length).duration, 3.4)
        self.assertAlmostEqual(intro.Bloom(120, 40, pal, codex.brand, codex.intro_line, codex.bloom_length).duration, 2.95)

    def test_player(self):
        app = apps.APPS['codex']
        player = intro.Player(lambda: (120, 40), art.palette(), app.brand, reduced=True)
        frame = player.frame()
        self.assertTrue(frame.startswith(b'\x1b[2J'))


def frame(rows, cols, header, footer):
    """A synthetic full-screen app frame: header lines at the top, footer lines at the bottom."""
    out = ['\x1b[?2026h\x1b[H\x1b[2J']
    for i, text in enumerate(header):
        out.append('\x1b[%d;3H%s' % (i + 1, text))
    for i, text in enumerate(footer):
        out.append('\x1b[%d;1H%s' % (rows - len(footer) + i + 1, text))
    out.append('\x1b[?2026l')
    return ''.join(out).encode('utf-8')


class OverlayTest(unittest.TestCase):
    def run_home(self, app, cols=120, rows=40):
        ov = app.make_overlay(cols, rows)
        out = ov.feed(b'\x1b[?1049h')
        out += ov.feed(frame(rows, cols, ['header one', 'header two'], ['> prompt', 'status']))
        return ov, out

    def test_home_is_drawn(self):
        for app in apps.APPS.values():
            ov, out = self.run_home(app)
            self.assertIn('盘古大模型'.encode('utf-8'), out, app.key)
            self.assertTrue(ov.visible)

    def test_row_is_wiped_before_the_app_writes_it(self):
        ov, _ = self.run_home(apps.APPS['codex'])
        row = sorted(ov.visible)[len(ov.visible) // 2]
        out = ov.feed(('\x1b[?2026h\x1b[%d;5Hhello\x1b[?2026l' % (row + 1)).encode())
        wipe = ('\x1b[%d;1H\x1b[2K' % (row + 1)).encode()
        self.assertIn(wipe, out)
        self.assertLess(out.index(wipe), out.index(b'hello'))

    def test_conversation_hides_home(self):
        ov, _ = self.run_home(apps.APPS['codex'])
        rows = 40
        out = ov.feed(frame(rows, 120, ['header one', 'header two'] + [''] * 10 + ['a reply in the middle'],
                            ['> prompt', 'status']))
        self.assertFalse(ov.visible)
        self.assertIn(b'\x1b[2K', out)

    def test_codex_branding(self):
        ov = apps.APPS['codex'].make_overlay(120, 40)
        out = ov.feed(b'\x1b[38;2;1;2;3m>_ \x1b[1mOpenAI Co')
        out += ov.feed(b'dex\x1b[0m (v1)')
        self.assertIn('盘古 · Codex'.encode('utf-8'), out)
        self.assertNotIn(b'OpenAI', out)

    def test_claude_branding(self):
        ov = apps.APPS['claude'].make_overlay(120, 40)
        out = ov.feed(b'\x1b]0;\xe2\x9c\xb3 Claude Code\x07\x1b[1mClaude Code\x1b[22m v2')
        self.assertEqual(out.count('盘古 · Code'.encode('utf-8')), 2)

    def test_split_utf8_survives(self):
        ov = apps.APPS['codex'].make_overlay(80, 24)
        text = '中文'.encode('utf-8')
        out = ov.feed(text[:2]) + ov.feed(text[2:])
        self.assertEqual(out, text)


class ClassifyTest(unittest.TestCase):
    def test_codex(self):
        codex = apps.APPS['codex']
        self.assertEqual(codex.classify([]), 'intro')
        self.assertEqual(codex.classify(['fix the bug']), 'intro')
        self.assertEqual(codex.classify(['-m', 'gpt', 'hello']), 'intro')
        self.assertEqual(codex.classify(['resume']), 'overlay')
        self.assertEqual(codex.classify(['exec', 'hi']), 'direct')
        self.assertEqual(codex.classify(['--version']), 'direct')
        self.assertEqual(codex.classify(['-c', 'x=1', 'mcp', 'list']), 'direct')

    def test_claude(self):
        claude = apps.APPS['claude']
        self.assertEqual(claude.classify([]), 'intro')
        self.assertEqual(claude.classify(['--dangerously-skip-permissions']), 'intro')
        self.assertEqual(claude.classify(['-c']), 'overlay')
        self.assertEqual(claude.classify(['-p', 'hi']), 'direct')
        self.assertEqual(claude.classify(['--model', 'opus', 'mcp']), 'direct')
        self.assertTrue(claude.has_prompt(['explain this']))
        self.assertFalse(claude.has_prompt(['--model', 'opus']))


def fake_app(folder, name):
    """A stand-in for codex / claude that prints its arguments."""
    folder = Path(folder)
    if os.name == 'nt':
        path = folder / (name + '.cmd')
        path.write_text('@echo fake-%s %%*\r\n' % name)
    else:
        path = folder / name
        path.write_text('#!/bin/sh\necho "fake-%s $*"\n' % name)
        path.chmod(0o755)
    return path


class CliTest(unittest.TestCase):
    def run_cli(self, args, config=None):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / 'bin'
            bin_dir.mkdir()
            fake_app(bin_dir, 'codex')
            fake_app(bin_dir, 'claude')
            env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ.get('PATH', ''),
                       PANGU_HOME=tmp)
            if config is not None:
                (Path(tmp) / 'config.json').write_text(json.dumps(config))
            done = subprocess.run([sys.executable, str(ROOT / 'run.py')] + args, env=env,
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
            return done.returncode, done.stdout.strip(), done.stderr

    def test_passthrough_without_terminal(self):
        code, out, _ = self.run_cli(['codex', '--version'])
        self.assertEqual(code, 0)
        self.assertEqual(out, 'fake-codex --version')

    def test_configured_arguments(self):
        code, out, _ = self.run_cli(['claude', '-p', 'hi'], {'apps': {'claude': {'args': ['--dangerously-skip-permissions']}}})
        self.assertEqual(out, 'fake-claude --dangerously-skip-permissions -p hi')

    def test_unknown_app(self):
        code, _, err = self.run_cli(['vim'])
        self.assertEqual(code, 2)


if __name__ == '__main__':
    unittest.main()
