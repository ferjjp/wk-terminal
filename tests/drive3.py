"""Headless drive: override keys, self-study picker and session, browse study, Keisei/Niai sections."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("WK_IMAGES", "unicode")
sys.path.insert(0, str(Path(__file__).parent))

import resvg_py
from fixtures import FakeAPI, build_db
from wanikani_tui import extdata
from wanikani_tui.app import WKApp
from wanikani_tui.core import Core
from wanikani_tui.screens import BrowseScreen, KeiseiSection, NiaiSection, SessionScreen, StudyPickerScreen, SubjectScreen, SummaryScreen
from wanikani_tui.session import Part

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
OUT.mkdir(parents=True, exist_ok=True)
EXT = OUT / "ext"
EXT.mkdir(exist_ok=True)
extdata.ext_dir = lambda: EXT  # type: ignore[assignment]
(EXT / "keisei_kanji.json").write_text(json.dumps({"水": {"readings": ["すい"], "type": "hieroglyph"}, "一": {"readings": ["いち"], "semantic": "x", "phonetic": "水", "type": "comp_phonetic"}}, ensure_ascii=False))
(EXT / "keisei_phonetic.json").write_text(json.dumps({"水": {"readings": ["すい"], "compounds": ["一", "人"], "non_compounds": ["龍"], "wk-radical": "water"}}, ensure_ascii=False))
(EXT / "niai_noto.json").write_text(json.dumps({"水": [{"kan": "人", "score": 0.5}]}, ensure_ascii=False))
(EXT / "niai_keisei.json").write_text("{}")
(EXT / "niai_manual.json").write_text("{}")


def shot(app, name):
    (OUT / f"{name}.png").write_bytes(resvg_py.svg_to_bytes(svg_string=app.export_screenshot(), width=1400))


async def main() -> None:
    db = build_db(":memory:")
    api = FakeAPI()
    core = Core(api, db)
    app = WKApp(core, skip_sync=True)
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        shot(app, "01-dashboard-forecast")
        # item screen with community sections
        app.push_screen(SubjectScreen(core.subject(10))); await pilot.pause(1.0)
        ks = app.screen.query(KeiseiSection)
        ns = app.screen.query(NiaiSection)
        print("keisei section present:", bool(ks), "| niai present:", bool(ns))
        shot(app, "02-item-keisei-niai")
        await pilot.press("escape"); await pilot.pause()
        # overrides in a review
        await pilot.press("r"); await pilot.pause()
        scr = app.screen; assert isinstance(scr, SessionScreen)
        item, part = scr.current
        wrong = "totally wrong" if part is Part.MEANING else "か"
        await pilot.press(*list(wrong), "enter"); await pilot.pause()
        assert item.incorrect == 1 and scr.query_one("#answer").disabled, (item.incorrect, scr.awaiting)
        await pilot.press("plus"); await pilot.pause()
        assert item.incorrect == 0 and part not in item.need, (item.incorrect, item.need)
        shot(app, "03-override-accept")
        await pilot.press("minus"); await pilot.pause()
        assert item.incorrect == 1 and part in item.need
        await pilot.press("ctrl+z"); await pilot.pause()
        assert item.incorrect == 0 and not scr.awaiting and not scr.query_one("#answer").disabled
        print("override accept/reject/undo ok")
        await pilot.press("escape"); await pilot.pause(); await pilot.press("y"); await pilot.pause(0.3)
        assert not isinstance(app.screen, SessionScreen), type(app.screen)
        # self-study from the dashboard
        await pilot.press("x"); await pilot.pause()
        assert isinstance(app.screen, StudyPickerScreen)
        shot(app, "04-study-picker")
        await pilot.press("enter"); await pilot.pause()
        scr = app.screen; assert isinstance(scr, SessionScreen) and scr.mode == "study", type(scr)
        shot(app, "05-study-session")
        n = 0
        while isinstance(app.screen, SessionScreen) and n < 30:
            item, part = app.screen.current
            ans = item.subject.primary_meaning if part is Part.MEANING else item.subject.accepted_readings[0]
            await pilot.press(*list(ans), "enter"); await pilot.pause(); await pilot.press("enter"); await pilot.pause(0.2)
            n += 1
        assert isinstance(app.screen, SummaryScreen), type(app.screen)
        print("study session finished; submissions to API:", api.submitted, "| sessions:", db.recent_sessions()[0]["mode"])
        await pilot.press("escape"); await pilot.pause()
        # browse -> study these
        await pilot.press("b"); await pilot.pause(); await pilot.press("x"); await pilot.pause()
        assert isinstance(app.screen, SessionScreen) and app.screen.mode == "study"
        print("browse study set size:", app.screen.queue.total)
        await pilot.press("escape"); await pilot.pause()
        assert isinstance(app.screen, BrowseScreen)


asyncio.run(main())
