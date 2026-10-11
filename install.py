#!/usr/bin/env python3
"""One-step installer for pangu-cli-theme (macOS, Linux, Windows). Standard library only.

  python3 install.py                 install for every app found (codex, claude)
  python3 install.py --apps codex    only Codex
  python3 install.py --status        what is installed where
  python3 install.py --uninstall     remove everything this installer added
  python3 install.py --dry-run       show what would change, change nothing

It copies the theme to ~/.pangu-cli-theme and adds a small marked block to your shell's
startup file (zsh, bash, fish, PowerShell) that makes `codex` / `claude` start through the
theme. Nothing of Codex or Claude Code themselves is changed.
"""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

NAME = 'pangu-cli-theme'
REPO = 'https://github.com/Lightly20110815/pangu-cli-theme'
START = '# >>> %s >>>' % NAME
END = '# <<< %s <<<' % NAME
APPS = ('codex', 'claude')
SHELLS = ('zsh', 'bash', 'fish', 'powershell')
SOURCE = Path(__file__).resolve().parent
PAYLOAD = ('pangu', 'run.py', 'install.py', 'README.md', 'LICENSE')
WINDOWS = os.name == 'nt'
BLOCK_RE = re.compile(r'\n?' + re.escape(START) + r'.*?' + re.escape(END) + r'[ \t]*\n?', re.S)


# --------------------------------------------------------------------------- output
def say(msg=''):
    try:
        print(msg)
    except UnicodeEncodeError:  # a legacy Windows console code page
        print(msg.encode('ascii', 'replace').decode('ascii'))


# --------------------------------------------------------------------------- places
class Places:
    def __init__(self, home=None, prefix=None, profiles=None):
        self.home = Path(home or Path.home()).expanduser()
        self.prefix = Path(prefix).expanduser() if prefix else self.home / ('.' + NAME)
        self._profiles = [Path(p) for p in profiles] if profiles else None
        self.custom_home = home is not None

    def rc(self, shell):
        """Startup files to edit for a shell (list)."""
        h = self.home
        if shell == 'zsh':
            zdot = os.environ.get('ZDOTDIR') if not self.custom_home else None
            return [Path(zdot or h) / '.zshrc']
        if shell == 'bash':
            files = [h / '.bashrc']
            # macOS terminals start login shells, which read ~/.bash_profile, not ~/.bashrc.
            profile = h / '.bash_profile'
            if sys.platform == 'darwin' and profile.exists() and '.bashrc' not in read(profile):
                files.append(profile)
            return files
        if shell == 'fish':
            return [h / '.config/fish/conf.d' / (NAME + '.fish')]
        if shell == 'powershell':
            return self.powershell_profiles()
        return []

    def powershell_profiles(self):
        if self._profiles is not None:
            return self._profiles
        found = []
        if not self.custom_home:
            for exe in ('pwsh', 'powershell'):
                if not shutil.which(exe):
                    continue
                try:
                    out = subprocess.run([exe, '-NoProfile', '-NonInteractive', '-Command',
                                          '$PROFILE.CurrentUserCurrentHost'],
                                         capture_output=True, text=True, timeout=20).stdout.strip()
                except (OSError, subprocess.SubprocessError):
                    out = ''
                if out:
                    found.append(Path(out))
        if not found and (WINDOWS or self.custom_home):
            docs = self.home / 'Documents'
            found = [docs / 'PowerShell/Microsoft.PowerShell_profile.ps1']
            if WINDOWS:
                found.append(docs / 'WindowsPowerShell/Microsoft.PowerShell_profile.ps1')
        unique = []
        for p in found:
            if p not in unique:
                unique.append(p)
        return unique


def read(path):
    try:
        return Path(path).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return ''


def detect_shells(places):
    """Shells to set up: the login shell, plus any whose startup file already exists."""
    shells = []
    login = Path(os.environ.get('SHELL', '')).name
    if WINDOWS or shutil.which('pwsh'):
        shells.append('powershell')
    if login == 'zsh' or (places.home / '.zshrc').exists():
        shells.append('zsh')
    if login == 'bash' or (places.home / '.bashrc').exists() or (WINDOWS and shutil.which('bash')):
        shells.append('bash')
    if login == 'fish' or shutil.which('fish') or (places.home / '.config/fish').exists():
        shells.append('fish')
    return shells


# --------------------------------------------------------------------------- blocks
def python_command(shell):
    """How the shell function starts Python."""
    if WINDOWS:
        # The interpreter running this installer (a bare `python` may be the Store stub).
        return sys.executable if shell == 'powershell' else sys.executable.replace('\\', '/')
    return 'python3' if shutil.which('python3') else sys.executable


def home_relative(path, places, shell):
    """`path` written relative to $HOME when it is under the real home folder."""
    if places.custom_home:
        return str(path)
    try:
        rel = Path(path).relative_to(places.home)
    except ValueError:
        return str(path)
    if shell == 'powershell' and WINDOWS:
        return '$HOME\\' + str(rel).replace('/', '\\')
    return '$HOME/' + rel.as_posix()


def block(shell, apps, places):
    run = home_relative(places.prefix / 'run.py', places, shell)
    py = python_command(shell)
    if shell == 'powershell':
        # ASCII only: Windows PowerShell 5.1 reads a profile without BOM in the ANSI code page.
        lines = [START, '# Huawei opening animation (%s). Plain this once: $env:PANGU="off"' % REPO]
    else:
        lines = [START, '# 华为开屏动画（%s）。本次不用主题：PANGU=off %s' % (REPO, apps[0])]
    if shell in ('zsh', 'bash'):
        lines.append('# 卸载：python3 "%s" --uninstall' % home_relative(places.prefix / 'install.py', places, shell))
        q = '"%s"' % py if ' ' in py or '\\' in py else py
        for app in apps:
            lines.append('unalias %s 2>/dev/null' % app)
            lines.append('%s() { %s "%s" %s "$@"; }' % (app, q, run, app))
    elif shell == 'fish':
        lines.append('# 卸载：python3 "%s" --uninstall' % (places.prefix / 'install.py'))
        for app in apps:
            lines += ['function %s' % app, '    %s "%s" %s $argv' % (py if ' ' not in py else '"%s"' % py, run, app), 'end']
    else:  # powershell
        lines.append('# Uninstall: python "%s" --uninstall' % (places.prefix / 'install.py'))
        for app in apps:
            lines.append('Remove-Item Alias:%s -Force -ErrorAction SilentlyContinue' % app)
            lines.append('function %s { & "%s" "%s" %s @args }' % (app, py, run, app))
    lines.append(END)
    return '\n'.join(lines) + '\n'


def strip_block(text):
    return BLOCK_RE.sub('\n', text).rstrip('\n') + '\n' if START in text else text


def with_block(text, new_block):
    base = strip_block(text) if START in text else text
    if base and not base.endswith('\n'):
        base += '\n'
    sep = '\n' if base.strip() else ''
    return (base if base.strip() else '') + sep + new_block


# --------------------------------------------------------------------------- aliases
ALIAS_POSIX = re.compile(r'^\s*alias\s+(%s)=(.+?)\s*$' % '|'.join(APPS), re.M)


def existing_alias_args(places, app):
    """Arguments carried by an existing `alias codex='codex --flag'`, so they are kept."""
    for path in [places.home / '.zshrc', places.home / '.bashrc', places.home / '.bash_profile']:
        for m in ALIAS_POSIX.finditer(strip_block(read(path))):
            if m.group(1) != app:
                continue
            try:
                value = shlex.split(m.group(2))
                value = shlex.split(value[0]) if len(value) == 1 else value
            except ValueError:
                continue
            for i, tok in enumerate(value):
                if tok.startswith('-'):
                    return value[i:], path, m.group(0).strip()
            return [], path, m.group(0).strip()
    return None


# --------------------------------------------------------------------------- actions
class Plan:
    def __init__(self, dry):
        self.dry = dry
        self.stamp = time.strftime('%Y%m%d-%H%M%S')

    def write(self, path, text, places, note):
        path = Path(path)
        old = read(path) if path.exists() else None
        if old == text:
            say('  = %s（无变化）' % path)
            return
        say('  %s %s：%s' % ('~' if old is not None else '+', path, note))
        if self.dry:
            return
        if old is not None:
            backup = places.prefix / 'backup' / ('%s.%s' % (path.name, self.stamp))
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(path), str(backup))
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n' if path.suffix != '.ps1' else None) as f:
            f.write(text)


def copy_payload(places, dry):
    if places.prefix.resolve() == SOURCE:
        say('  = 已在 %s 运行，代码无需复制' % places.prefix)
        return
    say('  + 复制主题代码到 %s' % places.prefix)
    if dry:
        return
    places.prefix.mkdir(parents=True, exist_ok=True)
    for name in PAYLOAD:
        src, dst = SOURCE / name, places.prefix / name
        if not src.exists():
            continue
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(str(dst))
            shutil.copytree(str(src), str(dst), ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            shutil.copy2(str(src), str(dst))


def write_config(places, apps, settings, dry):
    path = places.prefix / 'config.json'
    try:
        config = json.loads(read(path)) if path.exists() else {}
    except ValueError:
        config = {}
    if not isinstance(config, dict):
        config = {}
    config.setdefault('apps', {})
    for app in apps:
        entry = config['apps'].setdefault(app, {})
        entry.update({k: v for k, v in settings.get(app, {}).items() if v is not None})
    text = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
    say('  %s %s' % ('=' if read(path) == text else '+', path))
    if not dry:
        places.prefix.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


def execution_policy_hint():
    if not WINDOWS or not shutil.which('powershell'):
        return
    try:
        policy = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', 'Get-ExecutionPolicy'],
                                capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return
    if policy in ('Restricted', 'AllSigned'):
        say('\n注意：PowerShell 的执行策略是 %s，不会加载配置文件。请运行一次：' % policy)
        say('  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned')


def install(opts, places):
    apps = opts.apps or [a for a in APPS if shutil.which(a)]
    if not apps:
        say('没找到 codex 或 claude。先安装它们，或用 --apps codex,claude 强制安装。')
        return 1
    missing = [a for a in apps if not shutil.which(a) and not getattr(opts, a + '_command')]
    shells = opts.shells or detect_shells(places)
    if not shells:
        say('没识别到可配置的 shell，用 --shells zsh,bash,fish,powershell 指定。')
        return 1
    say('%s：为 %s 安装，shell：%s' % (NAME, '、'.join(apps), '、'.join(shells)))
    if missing:
        say('  ! 现在找不到 %s，装好之后就能用' % '、'.join(missing))
    plan = Plan(opts.dry_run)
    copy_payload(places, opts.dry_run)
    settings = {}
    for app in apps:
        entry = {}
        extra = getattr(opts, app + '_args')
        if extra is not None:
            entry['args'] = shlex.split(extra)
        else:
            found = existing_alias_args(places, app)
            if found:
                entry['args'] = found[0]
                say('  · 沿用 %s 里原有的 alias 参数：%s' % (found[1].name, ' '.join(found[0]) or '（无）'))
        command = getattr(opts, app + '_command')
        if command:
            entry['command'] = shlex.split(command, posix=not WINDOWS)
        settings[app] = entry
    write_config(places, apps, settings, opts.dry_run)
    for shell in shells:
        text = block(shell, apps, places)
        for path in places.rc(shell):
            if shell == 'fish':
                plan.write(path, text, places, 'fish 函数')
            else:
                plan.write(path, with_block(read(path), text), places, '加入 %s 段落' % NAME)
    if 'powershell' in shells:
        execution_policy_hint()
    say('')
    if opts.dry_run:
        say('（--dry-run：以上都没有真正执行）')
        return 0
    say('装好了。新开一个终端，直接敲 %s。' % ' 或 '.join(apps))
    say('本次不用主题：PANGU=off %s；卸载：python3 "%s" --uninstall' % (apps[0], places.prefix / 'install.py'))
    return 0


def all_profile_files(places):
    files = [places.home / '.zshrc', places.home / '.bashrc', places.home / '.bash_profile', places.home / '.profile']
    zdot = os.environ.get('ZDOTDIR')
    if zdot and not places.custom_home:
        files.append(Path(zdot) / '.zshrc')
    return files + places.powershell_profiles()


def uninstall(opts, places):
    say('%s：卸载' % NAME)
    plan = Plan(opts.dry_run)
    touched = False
    for path in all_profile_files(places):
        text = read(path)
        if START in text:
            touched = True
            plan.write(path, strip_block(text), places, '去掉 %s 段落' % NAME)
    fish = places.home / '.config/fish/conf.d' / (NAME + '.fish')
    if fish.exists():
        touched = True
        say('  - %s' % fish)
        if not opts.dry_run:
            fish.unlink()
    if places.prefix.exists() and not opts.keep_files:
        touched = True
        say('  - %s' % places.prefix)
        if not opts.dry_run:
            shutil.rmtree(str(places.prefix), ignore_errors=True)
    if not touched:
        say('  没有找到安装痕迹。')
    elif not opts.dry_run:
        say('\n已卸载。新开的终端里 codex / claude 就是原样了。')
    return 0


def status(opts, places):
    say('%s 状态' % NAME)
    say('  代码：%s %s' % (places.prefix, '✓' if (places.prefix / 'run.py').exists() else '（未安装）'))
    config = read(places.prefix / 'config.json')
    if config:
        say('  设置：%s' % ' '.join(config.split()))
    for app in APPS:
        say('  %s：%s' % (app, shutil.which(app) or '没找到'))
    for path in all_profile_files(places) + [places.home / '.config/fish/conf.d' / (NAME + '.fish')]:
        if START in read(path):
            say('  已接入：%s' % path)
    return 0


def parse(argv):
    p = argparse.ArgumentParser(prog='install.py', description='华为开屏动画（Codex / Claude Code）安装器')
    p.add_argument('--uninstall', action='store_true', help='卸载')
    p.add_argument('--status', action='store_true', help='查看安装状态')
    p.add_argument('--dry-run', action='store_true', help='只显示会改什么')
    p.add_argument('--keep-files', action='store_true', help='卸载时保留 ~/.pangu-cli-theme')
    p.add_argument('--apps', help='逗号分隔：codex,claude（默认：装了哪个就配哪个）')
    p.add_argument('--shells', help='逗号分隔：zsh,bash,fish,powershell（默认：自动识别）')
    p.add_argument('--prefix', help='安装位置（默认 ~/.pangu-cli-theme）')
    p.add_argument('--home', help=argparse.SUPPRESS)
    p.add_argument('--powershell-profile', action='append', help=argparse.SUPPRESS)
    for app in APPS:
        p.add_argument('--%s-args' % app, dest='%s_args' % app,
                       help='每次启动 %s 都带上的参数，例如 "--dangerously-skip-permissions"' % app)
        p.add_argument('--%s-command' % app, dest='%s_command' % app,
                       help='启动 %s 的命令（默认用 PATH 里的 %s）' % (app, app))
    p.add_argument('-y', '--yes', action='store_true', help='不询问（本来也不询问，留给脚本用）')
    opts = p.parse_args(argv)
    if opts.apps:
        opts.apps = [a.strip().lower() for a in opts.apps.split(',') if a.strip()]
        bad = [a for a in opts.apps if a not in APPS]
        if bad:
            p.error('不认识的应用：%s' % ', '.join(bad))
    if opts.shells:
        opts.shells = [('powershell' if s.strip().lower() in ('pwsh', 'ps') else s.strip().lower())
                       for s in opts.shells.split(',') if s.strip()]
        bad = [s for s in opts.shells if s not in SHELLS]
        if bad:
            p.error('不支持的 shell：%s' % ', '.join(bad))
    return opts


def main(argv=None):
    opts = parse(sys.argv[1:] if argv is None else argv)
    places = Places(opts.home, opts.prefix, opts.powershell_profile)
    if sys.version_info < (3, 8):
        say('需要 Python 3.8 或更新的版本。')
        return 1
    if opts.uninstall:
        return uninstall(opts, places)
    if opts.status:
        return status(opts, places)
    return install(opts, places)


if __name__ == '__main__':
    sys.exit(main())
