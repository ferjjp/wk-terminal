"""The Textual application: dashboard, stats and navigation."""

from __future__ import annotations

import threading
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from .config import settings
from .core import Core
from .keys import key
from .models import SRS_COLOR, Subject, TYPE_COLOR, srs_color, srs_group
from .screens import BrowseScreen, LessonPickerScreen, LessonScreen, SessionScreen, StudyPickerScreen, SubjectScreen
from .sync import SyncCancelled


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
    DashboardScreen #actions { height: auto; min-height: 4; content-align: center middle; text-align: center; margin-bottom: 1; }
    DashboardScreen #sync { dock: bottom; height: 1; padding: 0 2; background: $panel; color: $text-muted; }
    """
    BINDINGS = [
        Binding(key("reviews"), "reviews", "Reviews"),
        Binding(key("lessons"), "lessons", "Lessons"),
        Binding(key("pick_lessons"), "pick_lessons", "Pick lessons"),
        Binding(key("browse"), "browse", "Browse"),
        Binding(key("leeches"), "leeches", "Leeches"),
        Binding(key("study"), "study", "Self-study"),
        Binding(key("stats"), "stats", "Stats"),
        Binding(key("sync"), "sync", "Sync"),
        Binding(key("quit"), "app.quit", "Quit"),
    ] + ([Binding(key("scroll_down"), "scroll_down", "Down", show=False), Binding(key("scroll_up"), "scroll_up", "Up", show=False)] if settings().ui_vim_keys else [])

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

    def action_scroll_down(self) -> None:
        self.query_one(VerticalScroll).scroll_down()

    def action_scroll_up(self) -> None:
        self.query_one(VerticalScroll).scroll_up()

    def refresh_stats(self) -> None:
        core = self.wk.core
        db = core.db
        user = core.user()
        level = user.get("level", 1)
        self.sub_title = f"{user.get('username', '?')} · level {level}"

        reviews, lessons, next_at = core.due_counts()
        act = Text()
        act.append(f"  {reviews}  ", style="bold white on #00aaff")
        act.append(" reviews available   ")
        act.append(f"  {lessons}  ", style="bold white on #ff00aa")
        act.append(" lessons available")
        if reviews == 0 and next_at:
            act.append(f"\nnext review at {next_at.astimezone().strftime('%a %H:%M')}", style="dim")
        pending = db.pending_count()
        if pending:
            act.append(f"\n{pending} submission(s) waiting to be sent — they go out on the next sync", style="bold yellow")
        leeches = len(db.leeches())
        if leeches:
            act.append(f"\n{leeches} leech(es)  [{key('leeches')}] to see them", style="dim")
        act.append(
            f"\n\n[{key('reviews')}] reviews  [{key('lessons')}] lessons  [{key('pick_lessons')}] pick lessons  [{key('browse')}] browse"
            f"  [{key('study')}] self-study  [{key('stats')}] stats  [{key('sync')}] sync  [{key('quit')}] quit", style="dim",
        )
        self.query_one("#actions", Static).update(act)

        prog = Text()
        progress = db.level_progress(level)
        for kind, (passed, total) in progress.items():
            bar_w = 24
            filled = int(bar_w * passed / total) if total else 0
            prog.append(f"{kind:<11}", style="bold")
            prog.append("█" * filled, style=TYPE_COLOR[kind])
            prog.append("░" * (bar_w - filled), style="dim")
            prog.append(f"  {passed}/{total}\n")
        kp, kt = progress.get("kanji", (0, 0))
        need = max(0, -(-kt * 9 // 10) - kp) if kt else 0
        prog.append(f"\n{need} more kanji to pass level {level}" if need else f"\nLevel {level} kanji passed", style="dim")
        ls = core.level_stats()
        if ls.get("days_on_level") is not None:
            prog.append(f"\n{ls['days_on_level']:.1f} days on this level", style="dim")
            if ls.get("median_days"):
                proj = ls["projected"]
                when = proj.astimezone().strftime("%b %d") if proj else "?"
                prog.append(f" · median {ls['median_days']:.1f} d/level · projected level-up {when}", style="dim")
        self.query_one("#progress", Panel).update(prog)

        srs = Text()
        for name, n in db.srs_distribution().items():
            srs.append(f" {n:>5} ", style=f"bold white on {SRS_COLOR[name]}")
            srs.append(f" {name}\n")
        self.query_one("#srs", Panel).update(srs)

        fc = Text()
        buckets: dict = {}
        for ts, stage in db.upcoming_reviews_by_stage(hours=24):
            hour = ts.astimezone().replace(minute=0, second=0, microsecond=0)
            buckets.setdefault(hour, Counter())[srs_group(stage)] += 1
        cum = reviews
        if not buckets:
            fc.append("Nothing due in the next 24 hours", style="dim")
        else:
            maxn = max(sum(c.values()) for c in buckets.values())
            scale = min(1.0, 40 / max(1, maxn))
        for hour in sorted(buckets):
            counts = buckets[hour]
            n = sum(counts.values())
            cum += n
            fc.append(f"{hour.strftime('%a %H:%M')}  ")
            drawn = 0
            for grp in ("apprentice", "guru", "master", "enlightened"):
                w = int(round(counts.get(grp, 0) * scale))
                if counts.get(grp, 0) and w == 0:
                    w = 1
                fc.append("▇" * w, style=SRS_COLOR[grp])
                drawn += w
            fc.append(f" +{n}  ({cum})\n", style="dim")
        if buckets:
            fc.append("\n")
            for grp in ("apprentice", "guru", "master", "enlightened"):
                fc.append("▇ ", style=SRS_COLOR[grp])
                fc.append(f"{grp}  ", style="dim")
        self.query_one("#forecast", Panel).update(fc)

        last = db.get_meta("last_sync")
        self.query_one("#sync", Static).update(f"last sync: {last[:16].replace('T', ' ') + ' UTC' if last else 'never'}")

    # -- actions -------------------------------------------------------------

    def action_reviews(self) -> None:
        items = self.wk.core.review_items()
        if not items:
            self.notify("No reviews available right now")
            return
        self.app.push_screen(SessionScreen("review", items), lambda _: self.refresh_stats())

    def action_lessons(self) -> None:
        items = self.wk.core.lesson_items()
        if not items:
            self.notify("No lessons available")
            return
        self.app.push_screen(LessonScreen(items), lambda _: self.refresh_stats())

    def action_pick_lessons(self) -> None:
        items = self.wk.core.all_lesson_items()
        if not items:
            self.notify("No lessons available")
            return

        def start(chosen: list | None) -> None:
            if chosen:
                self.app.push_screen(LessonScreen(chosen), lambda _: self.refresh_stats())

        self.app.push_screen(LessonPickerScreen(items), start)

    def action_browse(self) -> None:
        user = self.wk.core.user()
        max_level = (user.get("subscription") or {}).get("max_level_granted", 60)
        self.app.push_screen(BrowseScreen(user.get("level", 1), max_level), lambda _: self.refresh_stats())

    def action_leeches(self) -> None:
        user = self.wk.core.user()
        self.app.push_screen(BrowseScreen(user.get("level", 1), 60, flt="leech"), lambda _: self.refresh_stats())

    def action_study(self) -> None:
        sets = self.wk.core.study_sets()

        def start(set_id: str | None) -> None:
            if not set_id:
                return
            items = self.wk.core.study_set_items(set_id)
            if not items:
                self.notify("That set is empty")
                return
            self.app.push_screen(SessionScreen("study", items), lambda _: self.refresh_stats())

        self.app.push_screen(StudyPickerScreen(sets), start)

    def action_stats(self) -> None:
        self.app.push_screen(StatsScreen())

    def action_sync(self) -> None:
        self.wk.run_sync(full=False)

    def set_sync_status(self, msg: str) -> None:
        self.query_one("#sync", Static).update(msg)


class StatsScreen(Screen[None]):
    DEFAULT_CSS = """
    StatsScreen VerticalScroll { padding: 1 2; }
    StatsScreen Panel { margin: 0 0 1 0; }
    StatsScreen DataTable { height: auto; max-height: 14; margin-bottom: 1; }
    """
    BINDINGS = [Binding(key("back"), "back", "Back")]
    LEVELS = ["#2b2b2b", "#0e4429", "#006d32", "#26a641", "#39d353"]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Panel("Reviews per day (last 26 weeks)", id="heat")
            yield Panel("Accuracy by type (all time)", id="acc")
            yield Panel("Levels", id="levels")
            yield Static(Text("Recent sessions", style="bold"))
            yield DataTable(id="sessions", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Stats"
        core: Core = self.app.core  # type: ignore[attr-defined]
        db = core.db
        per_day = db.reviews_per_day(days=26 * 7 + 7)
        today = datetime.now().date()
        start = today - timedelta(days=26 * 7 + today.weekday())
        heat = Text()
        maxn = max((v[0] for v in per_day.values()), default=1)
        for dow in range(7):
            heat.append(["Mon", "   ", "Wed", "   ", "Fri", "   ", "Sun"][dow] + " ", style="dim")
            for week in range(27):
                day = start + timedelta(days=week * 7 + dow)
                if day > today:
                    heat.append("  ")
                    continue
                n = per_day.get(day.strftime("%Y-%m-%d"), (0, 0))[0]
                lvl = 0 if n == 0 else min(4, 1 + int(3 * n / max(1, maxn)))
                heat.append("■ ", style=self.LEVELS[lvl])
            heat.append("\n")
        total = sum(v[0] for v in per_day.values())
        correct = sum(v[1] for v in per_day.values())
        days = len([1 for v in per_day.values() if v[0]])
        heat.append(f"\n{total} reviews on {days} days" + (f" · {100 * correct // total}% fully correct" if total else ""), style="dim")
        self.query_one("#heat", Panel).update(heat)

        acc = Text()
        for t, (mc, mi, rc, ri) in sorted(db.accuracy_by_type().items()):
            acc.append(f"{t:<16}", style=f"bold {TYPE_COLOR.get(t, 'white')}")
            acc.append(f"meaning {100 * mc // max(1, mc + mi):>3}%  ({mc + mi} answers)")
            if rc + ri:
                acc.append(f"   reading {100 * rc // max(1, rc + ri):>3}%  ({rc + ri} answers)")
            acc.append("\n")
        if not acc.plain:
            acc.append("No review statistics yet", style="dim")
        self.query_one("#acc", Panel).update(acc)

        ls = core.level_stats()
        lv = Text()
        lv.append(f"Level {ls['level']}", style="bold")
        if ls.get("days_on_level") is not None:
            lv.append(f" · {ls['days_on_level']:.1f} days so far")
        if ls.get("levels_done"):
            lv.append(f"\n{ls['levels_done']} levels completed in {ls['total_days']:.0f} days · median {ls['median_days']:.1f} days per level")
            if ls.get("projected"):
                lv.append(f"\nProjected level-up: {ls['projected'].astimezone().strftime('%a %b %d')}")
                remaining = 60 - ls["level"]
                lv.append(f" · level 60 in about {remaining * ls['median_days'] / 30:.0f} months at this pace", style="dim")
        self.query_one("#levels", Panel).update(lv)

        table = self.query_one("#sessions", DataTable)
        table.add_columns("When", "Mode", "Items", "Correct")
        for s in db.recent_sessions(20):
            when = s["started_at"][:16].replace("T", " ")
            n, c = s["items"] or 0, s["correct"] or 0
            table.add_row(when, s["mode"], str(n), f"{100 * c // n}%" if n else "—")

    def action_back(self) -> None:
        self.dismiss()


class WKApp(App[str | None]):
    TITLE = "WaniKani"
    CSS = """
    Screen { background: $background; }
    """
    BINDINGS = [Binding("ctrl+c", "quit", "Quit", show=False, priority=True)]

    def __init__(self, core: Core, full_sync: bool = False, skip_sync: bool = False, popup: bool = False) -> None:
        super().__init__()
        self.core = core
        self.full_sync = full_sync
        self.skip_sync = skip_sync
        self.popup = popup
        self._sync_lock = threading.Lock()

    def on_mount(self) -> None:
        cfg = self.core.cfg
        try:
            self.theme = cfg.ui_theme
        except Exception:  # noqa: BLE001 - unknown theme name
            self.notify(f"Unknown theme {cfg.ui_theme!r}; using the default", severity="warning")
        if self.popup:
            self._start_popup()
            return
        self.push_screen(DashboardScreen())
        from .images import font_path

        if font_path() is None and not self.core.db.get_meta("font_warned"):
            from .platform import cjk_font_install_hint

            self.notify(f"No Japanese font found for kanji images. Install one: {cjk_font_install_hint()}", severity="warning", timeout=15)
            self.core.db.set_meta("font_warned", "1")
        if not self.skip_sync or self.core.needs_full_sync():
            self.run_sync(full=self.full_sync or self.core.needs_full_sync())

    def _start_popup(self) -> None:
        mode, items = self.core.popup_items()
        if not items:
            self.exit(message="Nothing to review or learn right now.")
            return

        def done(_: object) -> None:
            self.exit()

        if mode == "review":
            self.push_screen(SessionScreen("review", items, popup=True), done)
        else:
            self.push_screen(LessonScreen(items, popup=True), done)

    def image_rows(self) -> int:
        return max(2, self.core.cfg.images_height)

    def open_full_app(self) -> None:
        """From a popup: leave with a result the CLI turns into the full interface in the same terminal."""
        self.exit(result="full")

    # -- helpers used by screens ------------------------------------------------

    @work(thread=True, group="audio", exclusive=True)
    def play_audio(self, subject: Subject) -> None:
        from . import audio

        if not subject.audio_urls:
            self.call_from_thread(self.notify, "No audio for this item")
            return
        if audio.player() is None:
            self.call_from_thread(self.notify, "No audio player found (install mpv or ffmpeg)", severity="warning")
            return
        try:
            f = audio.audio_file(subject.audio_urls, self.core.fetch_bytes)
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self.notify, f"Audio download failed: {exc}", severity="error")
            return
        if f:
            audio.play(f)

    # -- sync ----------------------------------------------------------------

    def run_sync(self, full: bool) -> None:
        if not self._sync_lock.acquire(blocking=False):
            self.notify("Sync already running")
            return
        self._sync_worker(full)

    @work(thread=True, group="sync", exit_on_error=False)
    def _sync_worker(self, full: bool) -> None:
        from textual.worker import get_current_worker

        from .db import Database

        worker = get_current_worker()
        db = Database(self.core.db.path)  # own connection for this thread

        def say(msg: str) -> None:
            self.call_from_thread(self._sync_status, "sync: " + msg)

        try:
            self.core.sync(full=full, progress=say, cancelled=lambda: worker.is_cancelled, db=db)
            self.call_from_thread(self._sync_finished)
        except SyncCancelled:
            pass
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self.notify, f"Sync failed: {exc}", severity="error", timeout=10)
            self.call_from_thread(self._sync_status, f"offline — using cached data ({str(exc)[:60]})")
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
