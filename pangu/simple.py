"""Windows (and the fallback everywhere): play the opening animation, then start the app.

Without a pty there is no way to sit between the app and the terminal, so the app's own
screen is left as it is: no home page, no header branding. The animation itself is the same.
"""
import os
import shutil
import signal
import subprocess
import sys
import time

from . import art, intro

WINDOWS = os.name == 'nt'


def enable_vt():
    """Let the Windows console understand escape sequences and UTF-8."""
    if not WINDOWS:
        return True
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # ENABLE_PROCESSED_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0001 | 0x0004))
    except Exception:
        return False


def terminal_size():
    size = shutil.get_terminal_size((80, 24))
    return size.columns, size.lines


class Screen:
    """Writes to the terminal; on Unix also turns off echo so typed keys stay invisible."""

    def __init__(self):
        self.out = sys.stdout.buffer
        self.saved = None
        if not WINDOWS:
            try:
                import termios
                import tty
                self.saved = termios.tcgetattr(0)
                tty.setcbreak(0)  # no echo, no line buffering, Ctrl+C still interrupts
            except Exception:
                self.saved = None

    def write(self, data):
        self.out.write(data)
        self.out.flush()

    def close(self):
        if self.saved is not None:
            import termios
            termios.tcsetattr(0, termios.TCSADRAIN, self.saved)


def background():
    """The terminal's background colour, where it can be asked for (not on Windows)."""
    if WINDOWS:
        return None
    try:
        from .unix import query_background
        return query_background(0, 1)
    except Exception:
        return None


def play(app, reduced=False):
    """Play the intro on the alternate screen. Returns False if Ctrl+C cancelled it."""
    if not enable_vt():
        return True  # an old console that cannot draw it: just start the app
    screen = Screen()
    finished = True
    try:
        screen.write(b'\x1b[?1049h\x1b[?25l\x1b[2J')
        pal = art.palette_for(background())
        player = intro.Player(terminal_size, pal, app.brand, app.intro_line, app.bloom_length, reduced)
        while not player.done:
            started = time.monotonic()
            screen.write(player.frame())
            time.sleep(max(0.005, player.FRAME - (time.monotonic() - started)))
        time.sleep(0.12)  # let the last frame land before the app clears it
    except KeyboardInterrupt:
        finished = False
    finally:
        try:
            screen.write(b'\x1b[0m\x1b[2J\x1b[?25h\x1b[?1049l')
        finally:
            screen.close()
    return finished


def run_app(command):
    """Start the app in this terminal and return its exit status."""
    if not WINDOWS:
        os.execvp(command[0], command)
    # Ctrl+C belongs to the app now; the launcher just waits for it.
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        return subprocess.call(command)
    finally:
        signal.signal(signal.SIGINT, previous)


def run(app, command, args, mode, reduced=False):
    if mode == 'intro' and not play(app, reduced):
        return 130
    return run_app(command)
