"""Run the app in a pty with the fake API, press keys, and dump the kitty-graphics traffic."""

from __future__ import annotations

import os
import pty
import re
import select
import sys
import time

KEYS = sys.argv[1] if len(sys.argv) > 1 else "r"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/dev/null"

child_code = r'''
import sys, os
sys.path.insert(0, "tests")
os.environ["WK_IMAGES"] = "tgp"
os.environ["TEXTUAL_CELL_WIDTH"] = "10"
os.environ["TEXTUAL_CELL_HEIGHT"] = "20"
from fixtures import FakeAPI, build_db
import wanikani_tui.screens as scr
from wanikani_tui.answers import Result, Verdict
scr.check_meaning = lambda a, s: Result(Verdict.CORRECT)
scr.check_reading = lambda a, s: Result(Verdict.CORRECT)
from wanikani_tui.app import WKApp
WKApp(FakeAPI(), build_db(":memory:"), skip_sync=True).run()
'''

pid, fd = pty.fork()
if pid == 0:
    os.environ["TERM"] = "xterm-kitty"
    os.environ["COLUMNS"] = "100"
    os.environ["LINES"] = "35"
    os.execvp(".venv/bin/python", [".venv/bin/python", "-c", child_code])

import fcntl, struct, termios
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 35, 100, 1000, 700))

buf = bytearray()


def pump(seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                data = os.read(fd, 65536)
            except OSError:
                return
            if not data:
                return
            buf.extend(data)


pump(2.5)
marks = []
for i, key in enumerate(KEYS.split(",")):
    marks.append((key, len(buf)))
    os.write(fd, key.encode() if len(key) == 1 else {"enter": b"\r", "esc": b"\x1b"}[key])
    pump(1.5)
os.write(fd, b"\x11")  # ctrl+q
pump(1.0)
os.kill(pid, 9)

raw = bytes(buf)
open(OUT, "wb").write(raw)
text = raw.decode("utf-8", "replace")
# marks were byte offsets; convert to character offsets in the decoded text
marks = [(key, len(raw[:at].decode("utf-8", "replace"))) for key, at in marks]
text = text.replace("\x1bPtmux;\x1b\x1b_G", "\x1b_G").replace("\x1b\x1b\\\x1b\\", "\x1b\\")

# kitty graphics commands (possibly tmux-wrapped, not here)
cmds = [(m.start(), m.group(1)) for m in re.finditer(r"\x1b_G([^\x1b;]*)(?:;[^\x1b]*)?\x1b\\", text)]
# placeholder cells: fg colour set before U+10EEEE
cells = [(m.start(), tuple(map(int, m.groups()))) for m in re.finditer(r"38;2;(\d+);(\d+);(\d+)(?:;[^m]*)?m[^\x1b]*?\U0010EEEE", text)]

def phase(pos):
    name = "startup"
    for key, at in marks:
        if pos >= at:
            name = f"after '{key}'"
    return name

print("== kitty commands ==")
for pos, c in cmds:
    if "m=1" in c and "a=" not in c.split(",")[0]:
        continue  # skip continuation chunks
    fields = dict(kv.split("=") for kv in c.split(",") if "=" in kv)
    if fields.get("m") == "1":
        continue
    print(f"  [{phase(pos):14}] {c}")
print("== placeholder cell runs per phase (image id low 24 bits, count of runs) ==")
from collections import Counter
counts = Counter((phase(pos), r << 16 | g << 8 | b) for pos, (r, g, b) in cells)
for (ph, ident), n in sorted(counts.items(), key=lambda kv: kv[0][0]):
    print(f"  [{ph:14}] id low24={ident}  runs={n}")
