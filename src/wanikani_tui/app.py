"""The Textual application: dashboard + navigation."""

from __future__ import annotations

import random
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from .api import WaniKani
from .db import TYPE_ORDER, Database
from .models import SRS_COLOR, Assignment, Subject
from .screens import BrowseScreen, LessonScreen, SessionScreen, SubjectScreen
from .session import Item
from .sync import SyncCancelled, needs_full_sync, sync


class Panel(Static):
    DEFAULT_CSS = """
    Panel { border: round $secondary; padding: 0 1; margin: 0 1 1 0; height: auto; }
    """

    def __init__(self, title: str, **kw: Any) -> None:
        super().__init__("", **kw)
        self.border_title = title


class DashboardScreen(Screen[None]):
    DEFAULT_CSS = """
    DashboardScreen VerticalScroll { padding: 1 2; }
    DashboardScreen #row1 { height: auto; }
    DashboardScreen #row1 > Panel { width: 1fr; }
    DashboardScreen #actions { height: 5; content-align: center middle; text-align: center; }
    DashboardScreen #sync { dock: bottom; height: 1; padding: 0 2; background: $panel; color: $text-muted; }
    """
    BINDINGS = [
        Binding("r", "reviews", "Reviews"),
        Binding("l", "lessons", "Lessons"),
        Binding("b", "browse", "Browse"),
        Binding("s", "sync", "Sync"),
        Binding("q", "app.quit", "Quit"),
    ]

    @property
    def wk(self) -> "WKApp":
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Static("", id="actions")
            with Horizontal(id="row1"):
                yield Panel("Level progress", id="progress")
                yield Panel("SRS", id="srs")
            yield Panel("Review forecast (next 24 h)", id="forecast")
        yield Static("", id="sync")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "WaniKani"
        self.refresh_stats()

    def refresh_stats(self) -> None:
        db = self.wk.db
        user = db.get_user() or {}
        level = user.get("level", 1)
        self.sub_title = f"{user.get('username', '?')} · level {level}"

        reviews = len(db.reviews_available())
        lessons = len(db.lessons_available())
        act = Text()
        act.append(f"  {reviews}  ", style="bold white on #00aaff")
        act.append(" reviews available   ")
        act.append(f"  {lessons}  ", style="bold white on #ff00aa")
        act.append(" lessons available")
        upcoming = db.upcoming_reviews(hours=24 * 14)
        if reviews == 0 and upcoming:
            act.append(f"\n\nnext review at {upcoming[0].astimezone().strftime('%a %H:%M')}", style="dim")
        act.append("\n\n[r] reviews   [l] lessons   [b] browse   [s] sync   [q] quit", style="dim")
        self.query_one("#actions", Static).update(act)

        prog = Text()
        for kind, (passed, total) in db.level_progress(level).items():
            bar_w = 24
            filled = int(bar_w * passed / total) if total else 0
            prog.append(f"{kind:<11}", style="bold")
            prog.append("█" * filled, style="#00aaff" if kind == "radical" else "#ff00aa" if kind == "kanji" else "#aa00ff")
            prog.append("░" * (bar_w - filled), style="dim")
            prog.append(f"  {passed}/{total}\n")
        kp, kt = db.level_progress(level).get("kanji", (0, 0))
        need = max(0, -(-kt * 9 // 10) - kp) if kt else 0
        prog.append(f"\n{need} more kanji to pass level {level}" if need else f"\nLevel {level} kanji passed", style="dim")
        self.query_one("#progress", Panel).update(prog)

        srs = Text()
        for name, n in db.srs_distribution().items():
            srs.append(f" {n:>5} ", style=f"bold white on {SRS_COLOR[name]}")
            srs.append(f" {name}\n")
        self.query_one("#srs", Panel).update(srs)

        fc = Text()
        buckets = Counter(ts.astimezone().replace(minute=0, second=0, microsecond=0) for ts in db.upcoming_reviews(hours=24))
        cum = reviews
        if not buckets:
            fc.append("Nothing due in the next 24 hours", style="dim")
        for hour in sorted(buckets):
            n = buckets[hour]
            cum += n
            fc.append(f"{hour.strftime('%a %H:%M')}  ")
            fc.append("▇" * min(n, 40), style="#00aaff")
            fc.append(f" +{n}  ({cum})\n", style="dim")
        self.query_one("#forecast", Panel).update(fc)

        last = db.get_meta("last_sync")
        self.query_one("#sync", Static).update(f"last sync: {last[:16].replace('T', ' ') + ' UTC' if last else 'never'}")

    # -- actions -------------------------------------------------------------

    def action_reviews(self) -> None:
        items = self.wk.review_items()
        if not items:
            self.notify("No reviews available right now")
            return
        self.app.push_screen(SessionScreen("review", items), lambda _: self.refresh_stats())

    def action_lessons(self) -> None:
        items = self.wk.lesson_items()
        if not items:
            self.notify("No lessons available")
            return
        self.app.push_screen(LessonScreen(items), lambda _: self.refresh_stats())

    def action_browse(self) -> None:
        user = self.wk.db.get_user() or {}
        max_level = (user.get("subscription") or {}).get("max_level_granted", 60)
        self.app.push_screen(BrowseScreen(user.get("level", 1), max_level), lambda _: self.refresh_stats())

    def action_sync(self) -> None:
        self.wk.run_sync(full=False)

    def set_sync_status(self, msg: str) -> None:
        self.query_one("#sync", Static).update(msg)


class WKApp(App[None]):
    TITLE = "WaniKani"
    CSS = """
    Screen { background: $background; }
    """
    BINDINGS = [Binding("ctrl+c", "quit", "Quit", show=False, priority=True)]

    def __init__(self, api: WaniKani, db: Database, full_sync: bool = False, skip_sync: bool = False) -> None:
        super().__init__()
        self.api = api
        self.db = db
        self.full_sync = full_sync
        self.skip_sync = skip_sync
        self._sync_lock = threading.Lock()

    def on_mount(self) -> None:
        self.push_screen(DashboardScreen())
        if not self.skip_sync or needs_full_sync(self.db):
            self.run_sync(full=self.full_sync or needs_full_sync(self.db))

    # -- data helpers --------------------------------------------------------

    def fetch_bytes(self, url: str) -> bytes:
        return self.api.fetch_bytes(url)

    def subject(self, subject_id: int) -> Subject:
        raw = self.db.subject(subject_id)
        if raw is None:
            raise KeyError(subject_id)
        return Subject.from_raw(raw, self.db.study_material(subject_id))

    def subjects(self, ids: Iterable[int]) -> list[Subject]:
        return [Subject.from_raw(r, self.db.study_material(r["id"])) for r in self.db.subjects_by_ids(ids)]

    def subjects_at_level(self, level: int, types: Iterable[str] | None = None) -> list[Subject]:
        return [Subject.from_raw(r, self.db.study_material(r["id"])) for r in self.db.subjects_at_level(level, types)]

    def search_subjects(self, text: str) -> list[Subject]:
        return [Subject.from_raw(r) for r in self.db.search_subjects(text)]

    def assignment_for(self, subject_id: int) -> Assignment | None:
        raw = self.db.assignment_for(subject_id)
        return Assignment.from_raw(raw) if raw else None

    def review_items(self) -> list[Item]:
        asgs = [Assignment.from_raw(a) for a in self.db.reviews_available()]
        subs = {s.id: s for s in self.subjects(a.subject_id for a in asgs)}
        return [Item.build(subs[a.subject_id], a) for a in asgs if a.subject_id in subs]

    def lesson_items(self) -> list[Item]:
        user = self.db.get_user() or {}
        prefs = user.get("preferences") or {}
        batch = int(prefs.get("lessons_batch_size") or 5)
        order = prefs.get("lessons_presentation_order") or "ascending_level_then_subject"
        max_level = (user.get("subscription") or {}).get("max_level_granted", 60)
        asgs = [Assignment.from_raw(a) for a in self.db.lessons_available()]
        subs = {s.id: s for s in self.subjects(a.subject_id for a in asgs)}
        items = [Item.build(subs[a.subject_id], a) for a in asgs if a.subject_id in subs and subs[a.subject_id].level <= max_level]
        rnd = random.random
        if order == "shuffled":
            items.sort(key=lambda _i: rnd())
        elif order == "ascending_level_then_shuffled":
            items.sort(key=lambda i: (i.subject.level, rnd()))
        else:
            items.sort(key=lambda i: (i.subject.level, TYPE_ORDER.get(i.subject.type, 9), i.subject.data.get("lesson_position", 0)))
        return items[:batch]

    # -- sync ----------------------------------------------------------------

    def run_sync(self, full: bool) -> None:
        if not self._sync_lock.acquire(blocking=False):
            self.notify("Sync already running")
            return
        self._sync_worker(full)

    @work(thread=True, group="sync", exit_on_error=False)
    def _sync_worker(self, full: bool) -> None:
        from textual.worker import get_current_worker

        worker = get_current_worker()
        db = Database(self.db.path)  # own connection for this thread

        def say(msg: str) -> None:
            self.call_from_thread(self._sync_status, "sync: " + msg)

        try:
            sync(self.api, db, full=full, progress=say, cancelled=lambda: worker.is_cancelled)
            self.call_from_thread(self._sync_finished)
        except SyncCancelled:
            pass
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self.notify, f"Sync failed: {exc}", severity="error", timeout=10)
            self.call_from_thread(self._sync_status, f"sync failed: {exc}")
        finally:
            db.close()
            self._sync_lock.release()

    def _sync_status(self, msg: str) -> None:
        for scr in self.screen_stack:
            if isinstance(scr, DashboardScreen):
                scr.set_sync_status(msg)

    def _sync_finished(self) -> None:
        for scr in self.screen_stack:
            if isinstance(scr, DashboardScreen):
                scr.refresh_stats()
        self.notify("Synced with WaniKani", timeout=3)
