"""Headless drive of the newer screens: stats, lesson picker, undo, synonyms, filters, popup mode."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("WK_IMAGES", "unicode")
sys.path.insert(0, str(Path(__file__).parent))

import resvg_py
from fixtures import FakeAPI, build_db
from wanikani_tui.app import StatsScreen, WKApp
from wanikani_tui.core import Core
from wanikani_tui.screens import BrowseScreen, LessonPickerScreen, LessonScreen, SessionScreen, SubjectScreen, TextPrompt
from wanikani_tui.session import Part

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
OUT.mkdir(parents=True, exist_ok=True)


def shot(app, name):
    (OUT / f"{name}.png").write_bytes(resvg_py.svg_to_bytes(svg_string=app.export_screenshot(), width=1400))


async def main() -> None:
    db = build_db(":memory:")
    api = FakeAPI()
    core = Core(api, db)
    core.sync(full=True)  # pulls reviews + level progressions from the fake
    app = WKApp(core, skip_sync=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        shot(app, "01-dashboard")
        await pilot.press("t"); await pilot.pause()
        assert isinstance(app.screen, StatsScreen)
        shot(app, "02-stats")
        await pilot.press("escape"); await pilot.pause()
        # lesson picker
        await pilot.press("L"); await pilot.pause()
        assert isinstance(app.screen, LessonPickerScreen)
        await pilot.press("space"); await pilot.pause()
        shot(app, "03-picker")
        await pilot.press("enter"); await pilot.pause()
        assert isinstance(app.screen, LessonScreen), type(app.screen)
        assert len(app.screen.items) == 1
        shot(app, "04-lesson-with-chips")
        await pilot.press("escape"); await pilot.press("y"); await pilot.pause()
        # browse filters + leeches
        await pilot.press("e"); await pilot.pause()
        assert isinstance(app.screen, BrowseScreen)
        shot(app, "05-leeches")
        await pilot.press("f"); await pilot.pause()
        print("filter after f:", app.screen.sub_title)
        await pilot.press("escape"); await pilot.pause()
        # synonym via subject screen
        app.push_screen(SubjectScreen(core.subject(11))); await pilot.pause()
        await pilot.press("y"); await pilot.pause()
        assert isinstance(app.screen, TextPrompt)
        await pilot.press(*"uno", "enter"); await pilot.pause(0.5)
        assert "uno" in core.subject(11).user_synonyms, core.subject(11).user_synonyms
        shot(app, "06-subject-synonym")
        await pilot.press("s"); await pilot.pause(0.5)  # strokes (fake SVG)
        shot(app, "07-strokes")
        await pilot.press("escape"); await pilot.press("escape"); await pilot.pause()
        # review with undo
        await pilot.press("r"); await pilot.pause()
        scr = app.screen
        assert isinstance(scr, SessionScreen)
        item, part = scr.current
        wrong = "totally wrong" if part is Part.MEANING else "か"
        await pilot.press(*list(wrong), "enter"); await pilot.pause()
        assert scr.awaiting and item.incorrect == 1
        await pilot.press("ctrl+z"); await pilot.pause()
        assert not scr.awaiting and item.incorrect == 0 and scr.current == (item, part)
        shot(app, "08-undo")
        ans = item.subject.primary_meaning if part is Part.MEANING else item.subject.accepted_readings[0]
        await pilot.press(*list(ans), "enter"); await pilot.pause()
        shot(app, "09-after-undo-correct")
        await pilot.press("escape"); await pilot.pause(); await pilot.press("escape"); await pilot.pause(); await pilot.press("y"); await pilot.pause(0.5)
        print("submitted after quit:", api.submitted)
    # popup mode
    app2 = WKApp(Core(api, db), skip_sync=True, popup=True)
    async with app2.run_test(size=(72, 24)) as pilot:
        await pilot.pause()
        scr = app2.screen
        assert isinstance(scr, SessionScreen) and scr.popup and scr.queue.total == 1
        shot(app2, "10-popup")
        for _ in range(3):
            if not isinstance(app2.screen, SessionScreen):
                break
            item, part = app2.screen.current
            ans = item.subject.primary_meaning if part is Part.MEANING else item.subject.accepted_readings[0]
            await pilot.press(*list(ans), "enter"); await pilot.pause(); await pilot.press("enter"); await pilot.pause(0.5)
        await pilot.press("escape"); await pilot.pause(0.5)  # close the one-more prompt
    print("popup exited:", not app2.is_running, "| submitted:", api.submitted[-1:])


asyncio.run(main())
