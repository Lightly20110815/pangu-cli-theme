#!/usr/bin/env python3
"""Run a command in a pty, emulate the screen with pyte, dump text + optional PNG.

usage: ptyshot.py COLS ROWS SECONDS OUTPREFIX [--keys 'k1@t1' ...] -- cmd args...
"""
import os, pty, select, sys, time, signal, struct, fcntl, termios, json
import pyte

argv = sys.argv[1:]
cols, rows, secs, out = int(argv[0]), int(argv[1]), float(argv[2]), argv[3]
rest = argv[4:]
keys = []
snaps = []
resizes = []
while rest and rest[0] != '--':
    if rest[0] == '--keys':
        k, t = rest[1].rsplit('@', 1)
        keys.append((float(t), k.encode().decode('unicode_escape').encode('latin1')))
        rest = rest[2:]
    elif rest[0] == '--resize':
        sz, t = rest[1].rsplit('@', 1); c, r = map(int, sz.split('x'))
        resizes.append((float(t), c, r)); rest = rest[2:]
    elif rest[0] == '--snap':
        snaps.append(float(rest[1])); rest = rest[2:]
    else:
        raise SystemExit('bad arg ' + rest[0])
cmd = rest[1:]

screen = pyte.Screen(cols, rows)
stream = pyte.ByteStream(screen)
raw = bytearray()

pid, fd = pty.fork()
if pid == 0:
    os.environ['TERM'] = os.environ.get('PTYSHOT_TERM', 'xterm-256color')
    os.environ['COLORTERM'] = 'truecolor'
    if os.environ.get('PTYSHOT_TERM_PROGRAM'):
        os.environ['TERM_PROGRAM'] = os.environ['PTYSHOT_TERM_PROGRAM']
    else:
        os.environ.pop('TERM_PROGRAM', None)
    os.execvp(cmd[0], cmd)
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
os.kill(pid, signal.SIGWINCH)

def respond(data):
    os.write(fd, data.encode() if isinstance(data, str) else data)
screen.write_process_input = respond

def dump(prefix):
    with open(prefix + '.txt', 'w') as f:
        for y in range(rows):
            f.write(''.join(screen.buffer[y][x].data for x in range(cols)).rstrip() + '\n')
    cells = []
    for y in range(rows):
        row = []
        for x in range(cols):
            c = screen.buffer[y][x]
            row.append([c.data, c.fg, c.bg, c.bold])
        cells.append(row)
    with open(prefix + '.json', 'w') as f:
        json.dump(cells, f)

start = time.monotonic()
pending = sorted(keys)
resizes.sort()
snaps = sorted(snaps)
n = 0
while True:
    now = time.monotonic() - start
    if now > secs:
        break
    while pending and pending[0][0] <= now:
        os.write(fd, pending.pop(0)[1])
    while resizes and resizes[0][0] <= now:
        _, cols, rows = resizes.pop(0)
        screen.resize(rows, cols)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
        os.kill(pid, signal.SIGWINCH)
    while snaps and snaps[0] <= now:
        snaps.pop(0); dump('%s.snap%02d' % (out, n)); n += 1
    r, _, _ = select.select([fd], [], [], 0.02)
    if r:
        try:
            data = os.read(fd, 65536)
        except OSError:
            break
        if not data:
            break
        raw.extend(data)
        # answer cursor position / OSC color queries pyte doesn't
        if b'\x1b]11;?' in data:
            respond('\x1b]11;rgb:0d0d/0f0f/1212\x1b\\')
        for mode in (b'2026', b'2027'):
            if b'\x1b[?' + mode + b'$p' in data:
                respond(b'\x1b[?' + mode + (b';2$y' if mode == b'2026' else b';0$y'))
        if b'\x1b]10;?' in data:
            respond('\x1b]10;rgb:eeee/eeee/eeee\x1b\\')
        stream.feed(bytes(data))
dump(out)
open(out + '.raw', 'wb').write(raw)
try:
    os.kill(pid, signal.SIGKILL)
except Exception:
    pass
