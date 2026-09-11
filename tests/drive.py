"""Drive the app headlessly, saving screenshots as PNG for inspection."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("WK_IMAGES", "none")
sys.path.insert(0, str(Path(__file__).parent))

import resvg_py
from fixtures import FakeAPI, build_db
from wanikani_tui.app import WKApp
from wanikani_tui.core import Core

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
OUT.mkdir(parents=True, exist_ok=True)


def shot(app: WKApp, name: str) -> None:
    svg = app.export_screenshot()
    (OUT / f"{name}.png").write_bytes(resvg_py.svg_to_bytes(svg_string=svg, width=1400))


async def main() -> None:
    dbfile = OUT / "fixture.sqlite3"
    if dbfile.exists():
        dbfile.unlink()
    db = build_db(dbfile)
    api = FakeAPI()
    app = WKApp(Core(api, db), skip_sync=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        shot(app, "01-dashboard")
        await pilot.press("b")
        await pilot.pause()
        shot(app, "02-browse")
        await pilot.press("enter")
        await pilot.pause()
        shot(app, "03-subject-radical")
        await pilot.press("escape")
        await pilot.press("down", "down", "down", "enter")
        await pilot.pause()
        shot(app, "04-subject-kanji")
        await pilot.press("g")
        await pilot.pause()
        shot(app, "05-related")
        await pilot.press("escape", "escape", "escape")
        await pilot.pause()
        # reviews: answer everything correctly except one meaning
        await pilot.press("r")
        await pilot.pause()
        shot(app, "06-review-prompt")
        from wanikani_tui.screens import SessionScreen
        from wanikani_tui.session import Part
        scr = app.screen
        assert isinstance(scr, SessionScreen), type(scr)
        first_wrong = True
        for _ in range(20):
            if not isinstance(app.screen, SessionScreen):
                break
            item, part = scr.current
            s = item.subject
            if part is Part.MEANING:
                ans = "totally wrong" if first_wrong else s.primary_meaning
                first_wrong = False
            else:
                ans = s.accepted_readings[0]
            await pilot.press(*list(ans))
            await pilot.press("enter")
            await pilot.pause()
            if _ == 0:
                shot(app, "07-review-feedback")
            await pilot.press("enter")
            await pilot.pause()
        await pilot.pause(0.5)
        shot(app, "08-review-summary")
        await pilot.press("escape")
        await pilot.pause()
        print("reviews submitted:", api.submitted)
        # lessons
        await pilot.press("l")
        await pilot.pause()
        shot(app, "09-lesson-page")
        await pilot.press("right", "right")
        await pilot.pause()
        for _ in range(10):
            if not isinstance(app.screen, SessionScreen):
                break
            item, part = app.screen.current
            ans = item.subject.primary_meaning if part is Part.MEANING else item.subject.accepted_readings[0]
            await pilot.press(*list(ans))
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
        await pilot.pause(0.5)
        shot(app, "10-lesson-summary")
        await pilot.press("escape")
        await pilot.pause()
        shot(app, "11-dashboard-after")
        print("lessons started:", api.started)
        print("reviews now:", len(db.reviews_available()), "lessons now:", len(db.lessons_available()))


asyncio.run(main())
