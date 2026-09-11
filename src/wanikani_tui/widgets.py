"""Shared widgets: the big character display and WaniKani mnemonic markup."""

from __future__ import annotations

import os
import re
from typing import Callable

from rich.markup import escape
from rich.text import Text
from textual.widgets import Static
from textual import work

from .models import Subject, TYPE_COLOR

from .config import settings

IMAGE_MODE = (os.environ.get("WK_IMAGES") or settings().images_mode or "auto").lower()


def _kitty_capable_outer_terminal() -> bool:
    """Inside tmux the capability query never comes back, so look at the environment instead."""
    env = os.environ
    return bool(
        env.get("GHOSTTY_RESOURCES_DIR")
        or env.get("GHOSTTY_BIN_DIR")
        or env.get("KITTY_WINDOW_ID")
        or env.get("KITTY_PID")
        or env.get("WEZTERM_EXECUTABLE")
    )


if IMAGE_MODE != "none":
    from textual_image.widget import HalfcellImage, Image as AutoImage, TGPImage, UnicodeImage, SixelImage

    # Inside tmux the capability queries are answered by tmux itself (tmux 3.6 advertises Sixel, which
    # ghostty and kitty cannot draw) and ghostty's kitty-graphics answer never comes back. So under tmux,
    # trust the outer terminal's identity instead of the negotiation.
    if IMAGE_MODE == "auto" and os.environ.get("TMUX") and _kitty_capable_outer_terminal():
        AutoImage = TGPImage  # type: ignore[misc]
    _Base = {
        "tgp": TGPImage, "kitty": TGPImage, "halfcell": HalfcellImage, "unicode": UnicodeImage, "sixel": SixelImage,
    }.get(IMAGE_MODE, AutoImage)

    class ImageWidget(_Base, Renderable=_Base._Renderable):  # type: ignore[misc,valid-type]
        """textual-image's widget deletes the terminal image and creates a fresh renderable on *every*
        render() call, while the re-transmit only happens lazily when the compositor consumes it. Any
        re-render (a keystroke in a neighbouring Input is enough) therefore wipes the picture until the
        next full repaint. Keep one renderable per (image, size) instead and only replace it on change."""

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._stable_key: tuple | None = None

        def render(self):
            if not self._image:
                return ""
            styled = self._get_styled_size()
            key = (id(self._image), styled, self.content_size)
            if self._renderable is None or key != self._stable_key:
                if self._renderable is not None:
                    self._renderable.cleanup()
                self._renderable = self._Renderable(self._image, *styled)
                self._stable_key = key
            return self._renderable
else:
    ImageWidget = None  # type: ignore[assignment]


TAG_STYLES = {
    "radical": "bold #00aaff",
    "kanji": "bold #ff00aa",
    "vocabulary": "bold #aa00ff",
    "reading": "bold white on #333333",
    "ja": "bold",
    "meaning": "bold underline",
}
_TAG_RE = re.compile(r"<(/?)(radical|kanji|vocabulary|reading|ja|meaning)>")


def mnemonic_text(raw: str) -> Text:
    """Turn WaniKani's <radical>/<kanji>/… markup into Rich markup."""
    if not raw:
        return Text("")
    out = []
    pos = 0
    for m in _TAG_RE.finditer(raw):
        out.append(escape(raw[pos:m.start()]))
        closing, tag = m.group(1), m.group(2)
        out.append("[/]" if closing else f"[{TAG_STYLES[tag]}]")
        pos = m.end()
    out.append(escape(raw[pos:]))
    return Text.from_markup("".join(out))


class CharDisplay(Static):
    """Large rendition of a subject's characters (image when the terminal allows, styled text otherwise)."""

    DEFAULT_CSS = """
    CharDisplay { width: auto; height: auto; content-align: center middle; }
    CharDisplay .wk-image { width: auto; height: 100%; }
    """

    def __init__(self, subject: Subject | None = None, fetch: Callable[[str], bytes] | None = None, rows: int = 7, **kw) -> None:
        super().__init__(**kw)
        self.subject = subject
        self.fetch = fetch
        self.rows = rows
        self._img = None

    def compose(self):
        if ImageWidget is not None:
            self._img = ImageWidget(None, classes="wk-image")
            self._img.styles.height = self.rows
            yield self._img

    def on_mount(self) -> None:
        self.show(self.subject)

    def set_rows(self, rows: int) -> None:
        self.rows = rows
        if self._img is not None:
            self._img.styles.height = rows

    def show(self, subject: Subject | None) -> None:
        self.subject = subject
        if subject is None:
            self.update("")
            if self._img is not None:
                self._img.image = None
            return
        if self._img is None:
            pad = " " * (len(subject.display_chars) + 4)
            self.update(Text(f"{pad}\n  {subject.display_chars}  \n{pad}", style=f"bold white on {subject.color}"))
            return
        from .images import text_image

        if subject.characters:
            self._img.image = text_image(subject.characters, subject.color)
        else:
            self._img.image = text_image(subject.primary_meaning, subject.color, px=48, pad=16)
            url = subject.image_url
            if url and self.fetch:
                self._load_radical(subject, url)

    @work(thread=True, exclusive=True, group="radical-image")
    def _load_radical(self, subject: Subject, url: str) -> None:
        from .images import radical_image

        try:
            img = radical_image(url, subject.color, self.fetch)
        except Exception:  # noqa: BLE001 - keep the text placeholder on any failure
            return
        if self.subject is subject and self._img is not None:
            self.app.call_from_thread(setattr, self._img, "image", img)


def type_badge(subject: Subject) -> Text:
    return Text(f" {subject.label} ", style=f"bold white on {TYPE_COLOR[subject.type]}")


class Chip(Static, can_focus=True):
    """A related-subject chip: coloured characters + meaning; Enter opens it. Image radicals get a small picture."""

    DEFAULT_CSS = """
    Chip { width: auto; height: auto; padding: 0 1; }
    Chip:focus { background: $accent 35%; }
    Chip .wk-image { width: auto; height: 2; }
    """
    BINDINGS = [("enter", "open", "Open")]

    def __init__(self, subject: Subject, fetch: Callable[[str], bytes] | None = None, **kw) -> None:
        super().__init__(**kw)
        self.subject = subject
        self.fetch = fetch
        self._img = None

    def compose(self):
        s = self.subject
        if ImageWidget is not None and not s.characters and s.image_url and self.fetch:
            self._img = ImageWidget(None, classes="wk-image")
            yield self._img

    def on_mount(self) -> None:
        s = self.subject
        t = Text()
        if self._img is None:
            t.append(f" {s.display_chars} ", style=f"bold white on {s.color}")
            t.append(f" {s.primary_meaning}", style="dim")
        else:
            t.append(f" {s.primary_meaning}", style="dim")
            self._load(s, s.image_url)
        self.update(t)

    @work(thread=True)
    def _load(self, subject: Subject, url: str) -> None:
        from .images import radical_image

        try:
            img = radical_image(url, subject.color, self.fetch, px=40, pad=8)
        except Exception:  # noqa: BLE001
            return
        if self._img is not None:
            self.app.call_from_thread(setattr, self._img, "image", img)

    def action_open(self) -> None:
        from .screens import SubjectScreen

        self.app.push_screen(SubjectScreen(self.subject))
