"""The installer, in a throw-away home folder."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_theme import fake_app  # noqa: E402

START = '# >>> pangu-cli-theme >>>'


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / 'home'
        self.home.mkdir()
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        fake_app(self.bin, 'codex')
        fake_app(self.bin, 'claude')
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ.get('PATH', ''),
                        PYTHONIOENCODING='utf-8')
        self.profile = self.home / 'ps' / 'profile.ps1'

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def install(self, *extra):
        cmd = [sys.executable, str(ROOT / 'install.py'), '--home', str(self.home),
               '--shells', 'zsh,bash,fish,powershell', '--powershell-profile', str(self.profile)] + list(extra)
        done = subprocess.run(cmd, env=self.env, capture_output=True, text=True, encoding='utf-8', timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return done.stdout

    def read(self, path):
        return Path(path).read_text(encoding='utf-8') if Path(path).exists() else ''

    def test_install_twice_then_uninstall(self):
        (self.home / '.zshrc').write_text("export A=1\nalias codex='codex --no-daemon'\n", encoding='utf-8')
        self.install()
        self.install()
        prefix = self.home / '.pangu-cli-theme'
        self.assertTrue((prefix / 'run.py').exists())
        self.assertTrue((prefix / 'pangu' / 'art.py').exists())
        for rc in (self.home / '.zshrc', self.home / '.bashrc', self.profile):
            self.assertEqual(self.read(rc).count(START), 1, rc)
        fish = self.home / '.config/fish/conf.d/pangu-cli-theme.fish'
        self.assertIn('function codex', self.read(fish))
        self.assertIn('"--no-daemon"', self.read(prefix / 'config.json'))
        self.assertIn('function codex {', self.read(self.profile))
        self.assertTrue(self.read(self.profile).isascii())

        self.install('--uninstall')
        self.assertEqual(self.read(self.home / '.zshrc'), "export A=1\nalias codex='codex --no-daemon'\n")
        self.assertNotIn(START, self.read(self.home / '.bashrc'))
        self.assertNotIn(START, self.read(self.profile))
        self.assertFalse(fish.exists())
        self.assertFalse(prefix.exists())

    def test_dry_run_changes_nothing(self):
        self.install('--dry-run')
        self.assertFalse((self.home / '.pangu-cli-theme').exists())
        self.assertFalse((self.home / '.zshrc').exists())

    def test_only_one_app(self):
        self.install('--apps', 'claude', '--claude-args=--dangerously-skip-permissions')
        text = self.read(self.home / '.bashrc')
        self.assertIn('claude()', text)
        self.assertNotIn('codex()', text)

    @unittest.skipIf(os.name == 'nt' or not shutil.which('bash'), 'needs a POSIX bash')
    def test_bash_function_runs_the_theme(self):
        self.install('--codex-args=--flag')
        script = 'source "%s"; type codex >/dev/null && codex --version' % (self.home / '.bashrc')
        done = subprocess.run(['bash', '-c', script], env=self.env, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(done.stdout.strip(), 'fake-codex --flag --version', done.stderr)

    @unittest.skipIf(os.name == 'nt' or not shutil.which('zsh'), 'needs zsh')
    def test_zsh_syntax(self):
        self.install()
        done = subprocess.run(['zsh', '-n', str(self.home / '.zshrc')], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    @unittest.skipIf(not shutil.which('pwsh'), 'needs PowerShell 7')
    def test_powershell_function_runs_the_theme(self):
        self.install('--codex-args=--flag')
        script = ". '%s'; codex --version" % self.profile
        done = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-Command', script], env=self.env,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(done.stdout.strip(), 'fake-codex --flag --version', done.stderr)

    @unittest.skipIf(not shutil.which('fish'), 'needs fish')
    def test_fish_function_runs_the_theme(self):
        self.install('--codex-args=--flag')
        fish = self.home / '.config/fish/conf.d/pangu-cli-theme.fish'
        done = subprocess.run(['fish', '-c', 'source %s; codex --version' % fish], env=self.env,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(done.stdout.strip(), 'fake-codex --flag --version', done.stderr)


if __name__ == '__main__':
    unittest.main()
