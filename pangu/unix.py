"""macOS / Linux: run the app on a pty, play the intro while it starts, weave in the home page.

The app's start-up output (modes, terminal queries) goes straight through so the terminal can
answer; from its first frame on, output is held until the intro's last frame and then handed
over in one piece, so the intro turns straight into the app's screen.
"""
import errno
import fcntl
import os
import pty
import re
import select
import signal
import struct
import termios
import time
import tty

from . import art
from .common import log_error

STARTED = False
ESCAPES = re.compile(rb'\x1b\[[0-9;?<>=:]*[ -/]*[@-~]|\x1b[\]P_^X][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b[ -~]')


def winsize(fd=1):
    try:
        packed = fcntl.ioctl(fd, termios.TIOCGWINSZ, b'\0' * 8)
        rows, cols, _, _ = struct.unpack('HHHH', packed)
        return packed, cols or 80, rows or 24
    except OSError:
        return struct.pack('HHHH', 24, 80, 0, 0), 80, 24


class TerminalGone(Exception):
    """The terminal window went away (writes or reads fail with EIO)."""


GONE = (errno.EIO, errno.ENXIO, errno.EBADF, errno.EPIPE)


def write_all(fd, data):
    view = memoryview(data)
    while view:
        try:
            n = os.write(fd, view)
        except BlockingIOError:
            select.select([], [fd], [], 1)
            continue
        except InterruptedError:
            continue
        except OSError as e:
            if e.errno in GONE:
                raise TerminalGone() from e
            raise
        view = view[n:]


def query_background(fd_in, fd_out, timeout=0.15):
    """Ask the terminal for its background colour (OSC 11). Returns (r, g, b) or None."""
    try:
        os.write(fd_out, b'\x1b]11;?\x1b\\')
        deadline = time.monotonic() + timeout
        buf = b''
        while time.monotonic() < deadline:
            ready = select.select([fd_in], [], [], max(0, deadline - time.monotonic()))[0]
            if not ready:
                break
            buf += os.read(fd_in, 256)
            if b'\x07' in buf or b'\x1b\\' in buf:
                break
        start = buf.find(b'rgb:')
        if start < 0:
            return None
        body = buf[start + 4:].split(b'\x07')[0].split(b'\x1b')[0]
        parts = body.split(b'/')
        return tuple(int(p[:2], 16) for p in parts[:3])
    except (OSError, ValueError):
        return None


def supervise(command):
    """Runs in the pty's session leader. Puts the app in its own foreground process group so
    that Ctrl+Z works (a group whose parent is outside the session is orphaned and the kernel
    drops SIGTSTP), and mirrors it stopping by stopping itself so the launcher can follow."""
    signal.set_wakeup_fd(-1)
    for sig in (signal.SIGWINCH, signal.SIGCHLD):
        signal.signal(sig, signal.SIG_DFL)
    signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    child = os.fork()
    if child == 0:
        os.setpgid(0, 0)
        os.tcsetpgrp(0, os.getpgrp())
        signal.signal(signal.SIGTTOU, signal.SIG_DFL)
        os.execvp(command[0], command)
    try:
        os.setpgid(child, child)
    except OSError:
        pass
    try:
        os.tcsetpgrp(0, child)
    except OSError:
        pass

    def forward(signum, frame):
        try:
            os.killpg(child, signum)
        except OSError:
            pass

    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT, signal.SIGQUIT):
        signal.signal(sig, forward)
    while True:
        try:
            _, st = os.waitpid(child, os.WUNTRACED)
        except InterruptedError:
            continue
        except ChildProcessError:
            os._exit(1)
        if os.WIFSTOPPED(st):
            os.kill(os.getpid(), signal.SIGSTOP)
            try:
                os.tcsetpgrp(0, child)
            except OSError:
                pass
            os.killpg(child, signal.SIGCONT)
            continue
        os._exit(os.waitstatus_to_exitcode(st) if hasattr(os, 'waitstatus_to_exitcode') else st >> 8)


class Proxy:
    """Runs the app on a pty and relays bytes both ways, passing output through the overlay."""

    def __init__(self, command, overlay, cooked, player=None):
        self.command, self.overlay, self.cooked = command, overlay, cooked
        self.events = []
        self.player = player
        self.held = None
        self.next_frame = 0.0
        self.aborted = False

    def _signal(self, signum, frame):
        self.events.append(signum)

    def run(self):
        try:
            return self._run()
        except TerminalGone:
            return self._hangup()

    def _run(self):
        global STARTED
        packed, _, _ = winsize()
        STARTED = True
        pid, master = pty.fork()
        if pid == 0:
            try:
                if os.environ.get('PANGU_SUPERVISE') == '0':
                    os.execvp(self.command[0], self.command)
                supervise(self.command)
            finally:
                os._exit(127)
        self.pid, self.master = pid, master
        fcntl.ioctl(master, termios.TIOCSWINSZ, packed)
        flags = fcntl.fcntl(master, fcntl.F_GETFL)
        fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        wake_r, wake_w = os.pipe()
        for fd in (wake_r, wake_w):
            fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)
        signal.set_wakeup_fd(wake_w)
        for sig in (signal.SIGWINCH, signal.SIGCHLD, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT, signal.SIGINT):
            signal.signal(sig, self._signal)
        pending = bytearray()
        stdin_open = True
        status = None
        while status is None:
            intro = self.player is not None and not self.player.done
            reads = [master, wake_r] + ([0] if stdin_open else [])
            writes = [master] if pending else []
            if intro:
                timeout = max(0.0, self.next_frame - time.monotonic())
            else:
                timeout = 0.03 if self._overlay_animating() else None
            try:
                ready_r, ready_w, _ = select.select(reads, writes, [], timeout)
            except InterruptedError:
                ready_r, ready_w = [], []
            if wake_r in ready_r:
                try:
                    os.read(wake_r, 4096)
                except BlockingIOError:
                    pass
            status = self._handle_events()
            if status is not None:
                break
            if 0 in ready_r:
                try:
                    data = os.read(0, 65536)
                except OSError as e:
                    if e.errno in GONE:
                        raise TerminalGone() from e
                    raise
                if not data:
                    stdin_open = False
                elif intro and (b'\x03' in data or b'\x1b[99;5u' in data):
                    # Ctrl+C during the intro cancels the launch (other keys are typed ahead).
                    self.aborted = True
                    status = self._abort()
                    break
                else:
                    pending += data
                    self._note_input(data)
            if master in ready_w and pending:
                try:
                    n = os.write(master, pending)
                    del pending[:n]
                except BlockingIOError:
                    pass
                except OSError:
                    pending.clear()
            if master in ready_r:
                try:
                    data = os.read(master, 65536)
                except BlockingIOError:
                    data = None
                except OSError as e:
                    if e.errno != errno.EIO:
                        raise
                    data = b''
                if data == b'':
                    self._finish_intro()
                    status = self._wait(block=True)
                    break
                if data:
                    self._emit(self._feed(data), intro)
            if intro and time.monotonic() >= self.next_frame:
                self.next_frame = time.monotonic() + self.player.FRAME
                try:
                    frame = self.player.frame()
                except Exception:
                    log_error('intro')
                    self.player.done = True
                    frame = b''
                write_all(1, frame)
                if self.player.done:
                    self._finish_intro()
            tick = self._tick()
            if tick:
                write_all(1, tick)
        if self.aborted:
            self.held = None
        else:
            self._finish_intro()  # whatever ended the loop, hand over what was held back
        self._drain()
        signal.set_wakeup_fd(-1)
        return status

    def _emit(self, out, intro):
        if not intro:
            write_all(1, out)
            return
        if self.held is None:
            split = self.overlay.split_at if self.overlay else None
            if split is None:
                write_all(1, out)  # still start-up output: modes, queries, title
                return
            self.overlay.split_at = None
            write_all(1, out[:split])
            self.held = bytearray(out[split:])
        else:
            self.held += out

    def _finish_intro(self):
        if self.player is None:
            return
        self.player.done = True
        if self.held:
            write_all(1, bytes(self.held))
        self.held = None
        if self.overlay:
            try:
                self.overlay.release()
            except Exception:
                log_error('overlay.release')

    def _abort(self):
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                pid, _ = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                break
            if pid:
                break
            time.sleep(0.02)
        else:
            try:
                os.kill(self.pid, signal.SIGKILL)
                os.waitpid(self.pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
        return 130

    # Overlay calls are fenced: if the overlay ever fails, the app keeps running untouched.
    def _feed(self, data):
        if self.overlay:
            try:
                return self.overlay.feed(data)
            except Exception:
                log_error('overlay.feed')
                self.overlay = None
                return data
        return data

    def _tick(self):
        if self.overlay:
            try:
                return self.overlay.tick()
            except Exception:
                log_error('overlay.tick')
                self.overlay = None
        return b''

    def _note_input(self, data):
        if self.overlay:
            try:
                self.overlay.note_input(data)
            except Exception:
                log_error('overlay.note_input')

    def _overlay_animating(self):
        return bool(self.overlay and self.overlay.animating())

    def _drain(self):
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            try:
                data = os.read(self.master, 65536)
            except (BlockingIOError, OSError):
                break
            if not data:
                break
            write_all(1, self._feed(data))
        try:
            os.close(self.master)
        except OSError:
            pass

    def _hangup(self):
        """The window closed under us: tell the app (as a closing terminal would) and leave."""
        signal.set_wakeup_fd(-1)
        try:
            os.kill(self.pid, signal.SIGHUP)
        except (ProcessLookupError, AttributeError):
            return 129
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                pid, _ = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                return 129
            if pid:
                return 129
            time.sleep(0.05)
        try:
            os.kill(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return 129

    def _wait(self, block=False):
        try:
            pid, st = os.waitpid(self.pid, 0 if block else os.WNOHANG | os.WUNTRACED)
        except ChildProcessError:
            return 1
        if pid == 0:
            return None
        if os.WIFSTOPPED(st):
            self._suspend()
            return None
        return os.waitstatus_to_exitcode(st) if hasattr(os, 'waitstatus_to_exitcode') else (st >> 8)

    def _suspend(self):
        """The app stopped itself (Ctrl+Z): stop the launcher too, resume both on `fg`."""
        termios.tcsetattr(0, termios.TCSADRAIN, self.cooked)
        os.kill(os.getpid(), signal.SIGSTOP)
        tty.setraw(0)
        packed, cols, rows = winsize()
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, packed)
        if self.overlay:
            self.overlay.resize(cols, rows)
        os.kill(self.pid, signal.SIGCONT)

    def _handle_events(self):
        events, self.events = self.events, []
        for sig in events:
            if sig == signal.SIGWINCH:
                packed, cols, rows = winsize()
                fcntl.ioctl(self.master, termios.TIOCSWINSZ, packed)
                if self.overlay:
                    self.overlay.resize(cols, rows)
            elif sig == signal.SIGCHLD:
                status = self._wait()
                if status is not None:
                    return status
            else:
                try:
                    os.kill(self.pid, sig)
                except ProcessLookupError:
                    pass
        return None


def run(app, command, args, mode, reduced=False):
    """Run `command` (already including the user's arguments) with the theme. Returns the
    exit status."""
    from . import intro
    cooked = termios.tcgetattr(0)
    in_alt = False
    ov = None
    status = 1
    try:
        tty.setraw(0)
        pal = dict(art.palette())
        player = None
        if mode == 'intro':
            write_all(1, b'\x1b[?1049h\x1b[?25l\x1b[2J')
            in_alt = True
            pal = art.palette_for(query_background(0, 1))
            try:
                player = intro.Player(lambda: winsize()[1:], pal, app.brand, app.intro_line,
                                      app.bloom_length, reduced)
            except Exception:
                log_error('intro')
                player = None
        _, cols, rows = winsize()
        try:
            ov = app.make_overlay(cols, rows, in_alt=in_alt, reveal=(mode == 'intro'), pal=pal,
                                  strict=(mode == 'overlay' or app.has_prompt(args)))
        except Exception:
            log_error('overlay init')
            ov = None
        proxy = Proxy(command, ov, cooked, player)
        status = proxy.run()
        ov = proxy.overlay
        if proxy.aborted:
            ov = None
    finally:
        try:
            restore_terminal(cooked, in_alt, ov)
        except (OSError, termios.error, TerminalGone):
            pass  # the terminal itself is gone (window closed)
    return status


def restore_terminal(cooked, in_alt, ov):
    termios.tcsetattr(0, termios.TCSADRAIN, cooked)
    if in_alt and ov is None:
        # Cancelled during the intro (or no overlay): undo whatever modes the app switched on.
        write_all(1, b'\x1b[0m\x1b[<u\x1b[?2004l\x1b[?1004l\x1b[?2031l\x1b[?1000l\x1b[?1002l'
                     b'\x1b[?1003l\x1b[?1006l\x1b[?25h\x1b[?1049l')
    elif in_alt and not ov.entered_alt and ov.awaiting_app:
        # The app never took over the screen (e.g. it failed to start): leave the intro's
        # screen and show whatever it printed.
        write_all(1, b'\x1b[0m\x1b[?25h\x1b[?1049l')
        if ov.passthrough_log:
            # Only the words: replaying its start-up queries would make the terminal answer
            # into the shell prompt.
            write_all(1, ESCAPES.sub(b'', bytes(ov.passthrough_log)))
    elif ov is not None and ov.alt:
        write_all(1, b'\x1b[0m\x1b[?25h\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?2004l\x1b[?1049l')


def started():
    return STARTED
