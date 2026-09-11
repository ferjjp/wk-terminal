"""`wk doctor`: show what the terminal negotiates and draw a test kanji with each method."""

from __future__ import annotations

import os
import sys


def run() -> int:
    print(f"TERM={os.environ.get('TERM')}  TERM_PROGRAM={os.environ.get('TERM_PROGRAM')}  inside tmux: {bool(os.environ.get('TMUX'))}")
    print(f"stdout is a tty: {sys.__stdout__.isatty()}")

    from textual_image import renderable
    from textual_image._terminal import get_cell_size
    from textual_image.renderable import sixel, tgp

    print(f"renderer negotiated with the terminal: {renderable.Image.__module__.rsplit('.', 1)[-1]}")
    from .widgets import ImageWidget

    print(f"renderer wk will actually use: {ImageWidget._Renderable.__module__.rsplit('.', 1)[-1] if ImageWidget else 'none'}")
    print(f"cell size (px): {get_cell_size()}")
    print(f"kitty graphics query answered OK: {tgp.query_terminal_support()}")
    print(f"sixel query answered OK: {sixel.query_terminal_support()}")

    from rich.console import Console
    from textual_image.renderable.halfcell import Image as Half
    from textual_image.renderable.tgp import Image as TGP

    from .images import font_path, text_image

    print(f"CJK font: {font_path()}")
    img = text_image("水", "#ff00aa")
    console = Console()
    for name, cls in (("kitty graphics (tgp)", TGP), ("half cells", Half)):
        print(f"\n--- {name}: you should see a pink box with 水 below ---")
        try:
            console.print(cls(img, width=12, height=6))
        except Exception as exc:  # noqa: BLE001
            print(f"   failed: {exc}")
    print("\nIf only one of them is visible, start with:  wk --images tgp   or   wk --images halfcell")
    return 0
