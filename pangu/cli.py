"""python3 run.py codex|claude [args...]: start the app with the Huawei theme.

  PANGU=off               run the app untouched this time
  PANGU_MOTION=reduce     a still frame (1 s) instead of the animation
  PANGU_MODE=simple       animation first, then the app, without the pty layer
  PANGU_GLYPHS=octant|quadrant, PANGU_THEME=light, PANGU_CELL_RATIO=2.1
"""
import os
import subprocess
import sys

from . import apps
from .common import LOG, app_config, log_error

WINDOWS = os.name == 'nt'


def usage():
    sys.stderr.write('用法：run.py codex|claude [参数…]\n')
    return 2


def exec_direct(command):
    if WINDOWS:
        import signal
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            return subprocess.call(command)
        except OSError as e:
            sys.stderr.write('无法启动 %s：%s\n' % (command[0], e))
            return 127
    try:
        os.execvp(command[0], command)
    except OSError as e:
        sys.stderr.write('无法启动 %s：%s\n' % (command[0], e))
        return 127


def interactive():
    try:
        return os.isatty(0) and os.isatty(1) and os.environ.get('TERM') != 'dumb'
    except Exception:
        return False


def use_pty():
    if WINDOWS or os.environ.get('PANGU_MODE', '').lower() == 'simple':
        return False
    try:
        import pty  # noqa: F401
        import termios  # noqa: F401
        return True
    except ImportError:
        return False


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help'):
        return usage()
    app = apps.get(argv[0])
    if app is None:
        return usage()
    cfg = app_config(app.key)
    base = app.find(cfg.get('command'))
    if not base:
        sys.stderr.write('找不到 %s：请先安装它，或在 config.json 里写明 command。\n' % app.binary)
        return 127
    args = [str(a) for a in cfg.get('args', [])] + argv[1:]
    mode = app.classify(args)
    if apps.themed_off() or not interactive():
        mode = 'direct'
    if mode == 'direct':
        return exec_direct(base + args)
    reduced = os.environ.get('PANGU_MOTION', '').lower() == 'reduce'
    if not use_pty():
        from . import simple
        return simple.run(app, base + args, args, mode, reduced)
    # The home page takes the place of the app's own welcome extras.
    command = base + app.extra_args + args
    from . import unix
    try:
        return unix.run(app, command, args, mode, reduced)
    except Exception:
        log_error('launcher')
        if unix.started():
            sys.stderr.write('盘古主题出错（详情见 %s）\n' % LOG)
            return 1
        sys.stderr.write('盘古主题出错，已直接启动 %s（详情见 %s）\n' % (app.title, LOG))
        return exec_direct(base + args)
