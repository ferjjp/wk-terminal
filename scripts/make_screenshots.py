"""Generate README screenshots from the real app, headlessly.

Runs against a temporary COPY of the local cache (username replaced by "demo", nothing is ever sent to
WaniKani), exports Textual's SVG, rasterises it, and pastes the actual kanji bitmaps into the cells where a
kitty-graphics terminal would draw them.

    uv run python scripts/make_screenshots.py docs/
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["WK_IMAGES"] = "unicode"  # gives the image widgets real regions to composite onto

import httpx
import resvg_py
from PIL import Image

from wanikani_tui.app import WKApp
from wanikani_tui.config import db_path
from wanikani_tui.core import Core
from wanikani_tui.db import Database
from wanikani_tui.models import Assignment
from wanikani_tui.screens import SessionScreen, SubjectScreen
from wanikani_tui.session import Item, Part
from wanikani_tui.widgets import ImageWidget

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs")
OUT.mkdir(parents=True, exist_ok=True)
WIDTH = 1500
ORIGIN_X, ORIGIN_Y, CELL_W, CELL_H = 9.0, 41.0, 12.2, 24.4  # Rich/Textual SVG export geometry
SIZE = (112, 34)


class ReadOnlyAPI:
    """Fetches public images only; every write raises so a screenshot run can never touch the account."""

    def __init__(self) -> None:
        self._http = httpx.Client(timeout=30, follow_redirects=True)

    def fetch_bytes(self, url: str) -> bytes:
        r = self._http.get(url)
        r.raise_for_status()
        return r.content

    def __getattr__(self, name):
        raise RuntimeError(f"screenshot run tried to call the API: {name}")


def fix_text_lengths(svg: str) -> str:
    """Rich's SVG export sets textLength from len(text), not the display width, so CJK runs are declared
    half as wide as they are and get squeezed. Recompute it from the cell width."""
    import html

    from rich.cells import cell_len

    def repl(m: "re.Match[str]") -> str:
        text = html.unescape(m.group(3))
        return f'{m.group(1)}textLength="{cell_len(text) * CELL_W:g}"{m.group(2)}>{m.group(3)}</text>'

    return re.sub(r'(<text [^>]*?)textLength="[0-9.]+"([^>]*)>([^<]*)</text>', repl, svg)


def snapshot(app: WKApp, name: str) -> None:
    svg = fix_text_lengths(app.export_screenshot())
    vb = re.search(r'viewBox="0 0 ([0-9.]+) ([0-9.]+)"', svg)
    scale = WIDTH / float(vb.group(1))
    png = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg, width=WIDTH))).convert("RGBA")
    bg = png.getpixel((int((ORIGIN_X + 2) * scale), int((ORIGIN_Y + CELL_H * (SIZE[1] - 1.5)) * scale)))
    if ImageWidget is not None:
        for w in app.screen.query(ImageWidget):
            pil = getattr(w, "_image", None)
            r = w.region
            if pil is None or not isinstance(pil, Image.Image) or r.width == 0 or r.height == 0:
                continue
            x0, y0 = (ORIGIN_X + r.x * CELL_W) * scale, (ORIGIN_Y + r.y * CELL_H) * scale
            bw, bh = r.width * CELL_W * scale, r.height * CELL_H * scale
            png.paste(bg, (int(x0) - 1, int(y0) - 1, int(x0 + bw) + 2, int(y0 + bh) + 2))
            k = min(bw / pil.width, bh / pil.height)
            img = pil.convert("RGBA").resize((max(1, int(pil.width * k)), max(1, int(pil.height * k))), Image.LANCZOS)
            png.alpha_composite(img, (int(x0 + (bw - img.width) / 2), int(y0 + (bh - img.height) / 2)))
    png.convert("RGB").save(OUT / f"{name}.png", optimize=True)
    print("wrote", OUT / f"{name}.png")


def find(core: Core, chars: str, kind: str):
    return next(s for s in core.search_subjects(chars) if s.type == kind and s.characters == chars)


async def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="wk-shots-"))
    shutil.copy(db_path(), tmp / "cache.sqlite3")
    db = Database(tmp / "cache.sqlite3")
    user = db.get_user() or {}
    user["username"] = "demo"
    db.set_user(user)
    # demo-friendly level timing: the copy pretends the current level started nine days ago
    from datetime import datetime, timedelta, timezone

    for row in db.conn.execute("SELECT id, data FROM level_progressions").fetchall():
        d = json.loads(row["data"])
        if d.get("level") == user.get("level") and not d.get("passed_at"):
            d["started_at"] = (datetime.now(timezone.utc) - timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            db.conn.execute("UPDATE level_progressions SET data=? WHERE id=?", (json.dumps(d), row["id"]))
    db.conn.commit()
    core = Core(ReadOnlyAPI(), db)  # type: ignore[arg-type]

    app = WKApp(core, skip_sync=True)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause(0.5)
        snapshot(app, "dashboard")

        joshi = find(core, "女子", "vocabulary")
        item = Item.build(joshi, core.assignment_for(joshi.id) or Assignment(0, {"subject_id": joshi.id, "srs_stage": 1}))
        item.need = {Part.READING}
        scr = SessionScreen("review", [item])
        app.push_screen(scr)
        await pilot.pause(0.5)
        await pilot.press(*"joshi")
        await pilot.pause(0.2)
        snapshot(app, "review-prompt")
        await pilot.press("enter")
        await pilot.pause(0.8)
        snapshot(app, "review-feedback")
        scr.pending_submit = None  # belt and braces: nothing to flush
        scr.dismiss([])
        await pilot.pause(0.3)

        kanji = find(core, "情", "kanji")
        app.push_screen(SubjectScreen(kanji))
        await pilot.pause(2.5)  # Keisei / Niai sections fill in worker threads
        snapshot(app, "kanji-page")
        detail = app.screen.query_one("SubjectDetail")
        detail.scroll_end(animate=False)
        await pilot.pause(1.0)
        snapshot(app, "kanji-page-composition")
        await pilot.press("escape")
        await pilot.pause(0.2)

        vocab = find(core, "水道", "vocabulary") if core.search_subjects("水道") else joshi
        app.push_screen(SubjectScreen(vocab))
        await pilot.pause(2.0)
        snapshot(app, "vocab-page")

    # the text reader is plain Rich output
    from rich.console import Console

    from wanikani_tui import reader

    text = "東京の水道水は安全です。毎日、多くの人が電車で会社に行きます。今日は天気がいいので、公園で友達と昼ご飯を食べました。"
    console = Console(record=True, width=96, force_terminal=True, color_system="truecolor", file=io.StringIO())
    console.print("[dim]$ wk read article.txt[/dim]\n")
    reader.render(reader.analyse(db, text), console, top=8)
    svg = fix_text_lengths(console.export_svg(title="wk read"))
    (OUT / "reader.png").write_bytes(resvg_py.svg_to_bytes(svg_string=svg, width=WIDTH))
    print("wrote", OUT / "reader.png")
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


asyncio.run(main())
