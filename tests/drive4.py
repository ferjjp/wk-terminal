"""Headless drive: Anki mode, pitch + breakdown on the item screen, confusion hint on a miss."""

from __future__ import annotations

import asyncio
import os
import tempfile
import sys
from pathlib import Path

os.environ.setdefault("WK_IMAGES", "unicode")
os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp(prefix="wk-drive-")  # never write fixture data into the real cache
sys.path.insert(0, str(Path(__file__).parent))

import resvg_py
from fixtures import FakeAPI, build_db
from wanikani_tui import pitch
from wanikani_tui.app import WKApp
from wanikani_tui.config import settings
from wanikani_tui.core import Core
from wanikani_tui.screens import PitchSection, SessionScreen, SubjectScreen
from wanikani_tui.session import Part

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
OUT.mkdir(parents=True, exist_ok=True)
acc = OUT / "kanjium_accents.txt"
acc.write_text("新聞\tしんぶん\t0\n水\tみず\t0\n", encoding="utf-8")
pitch.path = lambda: acc  # type: ignore[assignment]
pitch._table.cache_clear()


def shot(app, name):
    (OUT / f"{name}.png").write_bytes(resvg_py.svg_to_bytes(svg_string=app.export_screenshot(), width=1400))


async def main() -> None:
    db = build_db(":memory:")
    api = FakeAPI()
    core = Core(api, db)
    app = WKApp(core, skip_sync=True)
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        app.push_screen(SubjectScreen(core.subject(21))); await pilot.pause(0.8)
        print("pitch section:", bool(app.screen.query(PitchSection)))
        shot(app, "01-vocab-pitch")
        await pilot.press("escape"); await pilot.pause()
        # confusion hint: answer "one" for whatever is asked -> only meaningful for 水; force via study set of level kanji
        settings().review_anki = False
        await pilot.press("r"); await pilot.pause()
        scr = app.screen; assert isinstance(scr, SessionScreen)
        # find the 水 kanji item by cycling wrong answers until it comes up
        for _ in range(12):
            item, part = scr.current
            if item.subject.id == 10 and part is Part.MEANING:
                await pilot.press(*"one", "enter"); await pilot.pause()
                fb = scr.query_one("#feedback").render() if hasattr(scr.query_one("#feedback"), "render") else None
                shot(app, "02-confusion-hint")
                print("confusion hint shown:", "Confused with" in str(scr.query_one("#feedback").visual if hasattr(scr.query_one("#feedback"), "visual") else ""))
                break
            ans = item.subject.primary_meaning if part is Part.MEANING else item.subject.accepted_readings[0]
            await pilot.press(*list(ans), "enter"); await pilot.pause(); await pilot.press("enter"); await pilot.pause(0.2)
            if not isinstance(app.screen, SessionScreen):
                break
        await pilot.press("escape"); await pilot.pause(); await pilot.press("y"); await pilot.pause(0.3)
        if isinstance(app.screen, SessionScreen):
            await pilot.press("escape"); await pilot.pause(); await pilot.press("y"); await pilot.pause(0.3)
        # Anki mode
        settings().review_anki = True
        await pilot.press("x"); await pilot.pause(); await pilot.press("enter"); await pilot.pause()
        scr = app.screen; assert isinstance(scr, SessionScreen) and scr.anki
        assert scr.query_one("#answer").disabled
        shot(app, "03-anki-prompt")
        await pilot.press("space"); await pilot.pause()
        assert scr.revealed
        shot(app, "04-anki-revealed")
        item, part = scr.current
        await pilot.press("1"); await pilot.pause()
        assert scr.awaiting and part not in item.need
        await pilot.press("enter"); await pilot.pause()
        await pilot.press("space"); await pilot.pause(); await pilot.press("2"); await pilot.pause()
        item2, part2 = scr.current
        assert item2.wrong[part2] == 1
        print("anki reveal/grade ok")
        await pilot.press("f3"); await pilot.pause()
        assert not scr.anki
        settings().review_anki = False


asyncio.run(main())
