"""What differs between the apps: how to find them, which invocations get the intro, branding."""
import os
import shutil

from . import art
from .overlay import ClaudeOverlay, CodexOverlay


class App:
    key = ''
    title = ''
    binary = ''
    overlay = None
    intro_line = None     # a line typed before the bloom, or None
    bloom_length = 2.95
    extra_args = []       # always passed (before the user's own arguments)
    subcommands = set()   # print, configure or run headless: run untouched
    overlay_only = set()  # open an existing conversation: no intro
    direct_flags = set()
    resume_flags = set()
    value_flags = set()

    @property
    def brand(self):
        return art.BRANDS[self.key]

    def find(self, configured=None):
        """The command to run: the configured one, else the binary on PATH."""
        if configured:
            return list(configured)
        found = shutil.which(self.binary)
        return [found] if found else None

    def _walk(self, args):
        """Yield (index, arg, is_flag) over args, skipping flag values."""
        i = 0
        while i < len(args):
            a = args[i]
            if a == '--':
                return
            if a.startswith('-') and len(a) > 1:
                yield i, a, True
                i += 2 if (a in self.value_flags and '=' not in a) else 1
                continue
            yield i, a, False
            i += 1

    def classify(self, args):
        """'direct' (run untouched), 'overlay' (no intro) or 'intro'."""
        resume = False
        for _, a, is_flag in self._walk(args):
            if is_flag:
                flag = a.split('=', 1)[0]
                if flag in self.direct_flags:
                    return 'direct'
                if flag in self.resume_flags:
                    resume = True
                continue
            if a in self.overlay_only:
                return 'overlay'
            if a in self.subcommands:
                return 'direct'
            break  # an initial prompt
        return 'overlay' if resume else 'intro'

    def has_prompt(self, args):
        """True when the session opens with a prompt from the command line."""
        for i, a, is_flag in self._walk(args):
            if not is_flag:
                return a not in self.subcommands and a not in self.overlay_only
        return '--' in args and args.index('--') + 1 < len(args)

    def make_overlay(self, cols, rows, **kw):
        return self.overlay(cols, rows, self.brand, **kw)


class Codex(App):
    key = 'codex'
    title = 'Codex'
    binary = 'codex'
    overlay = CodexOverlay
    bloom_length = 2.95
    # The home replaces Codex's own welcome animation and the tooltip under the prompt.
    extra_args = ['-c', 'tui.effects.welcome=false', '-c', 'tui.show_tooltips=false']
    subcommands = {
        'agents', 'exec', 'e', 'review', 'login', 'logout', 'mcp', 'plugin', 'app-server', 'remote-control',
        'app', 'completion', 'update', 'doctor', 'sandbox', 'debug', 'apply', 'a', 'queue',
        'archive', 'delete', 'migrate-rollouts', 'unarchive', 'cloud', 'exec-server', 'features', 'help',
        'mcp-server', 'proto', 'responses-api-proxy', 'stdio-to-uds', 'generate-ts',
    }
    overlay_only = {'resume', 'fork'}
    direct_flags = {'-h', '--help', '-V', '--version', '--no-alt-screen'}
    value_flags = {
        '-c', '--config', '--enable', '--disable', '--remote', '--remote-auth-token-env', '-i', '--image',
        '-m', '--model', '--local-provider', '-p', '--profile', '-s', '--sandbox', '-C', '--cd', '--add-dir',
        '-a', '--ask-for-approval',
    }


class Claude(App):
    key = 'claude'
    title = 'Claude Code'
    binary = 'claude'
    overlay = ClaudeOverlay
    intro_line = '从一行代码'
    bloom_length = 2.85
    subcommands = {
        'doctor', 'update', 'upgrade', 'install', 'auth', 'mcp', 'plugin', 'plugins', 'project', 'agents',
        'attach', 'logs', 'stop', 'kill', 'rm', 'respawn', 'gateway', 'import', 'setup-token', 'config',
        'migrate-installer', 'api-key', 'help',
    }
    direct_flags = {
        '-p', '--print', '-h', '--help', '-v', '--version', '--safe-mode', '--bare', '--bg', '--background',
        '--desktop', '--cloud', '--ax-screen-reader', '--output-format', '--input-format',
    }
    resume_flags = {'-c', '--continue', '-r', '--resume', '--from-pr', '--teleport'}
    value_flags = {
        '--model', '--settings', '--setting-sources', '--add-dir', '--plugin-dir', '--mcp-config',
        '--append-system-prompt', '--system-prompt', '--permission-mode', '--allowedTools', '--allowed-tools',
        '--disallowedTools', '--disallowed-tools', '--agents', '--agent', '--session-id', '--fallback-model',
        '--debug-file', '--betas', '--name', '-n', '--effort', '--tools', '--max-turns', '--worktree', '-w',
    }


APPS = {'codex': Codex(), 'claude': Claude()}


def get(name):
    return APPS.get(name.lower())


def themed_off():
    return os.environ.get('PANGU', '').lower() in ('0', 'off', 'no', 'false')
