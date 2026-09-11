"""Screens: subject detail, browse, review/lesson sessions, summary, confirm."""

from __future__ import annotations

import webbrowser
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Header, Input, OptionList, Static
from textual.widgets.option_list import Option

from .answers import Verdict, check_meaning, check_reading, to_kana_live
from .api import ApiError
from .db import TYPE_ORDER, parse_ts
from .models import SRS_NAMES, Assignment, Subject, next_srs_stage, srs_color
from .session import Item, Part, Queue
from .widgets import CharDisplay, mnemonic_text, type_badge

if TYPE_CHECKING:
    from .app import WKApp


def _rel_time(ts: datetime | None) -> str:
    if ts is None:
        return "—"
    delta = ts - datetime.now(timezone.utc)
    secs = delta.total_seconds()
    if secs <= 0:
        return "now"
    if secs < 3600:
        return f"in {int(secs // 60)} min"
    if secs < 86400:
        return f"in {secs / 3600:.1f} h"
    return f"in {secs / 86400:.1f} d"


def chip(subject: Subject) -> Text:
    t = Text()
    t.append(f" {subject.display_chars} ", style=f"bold white on {subject.color}")
    t.append(f" {subject.primary_meaning}", style="dim")
    return t


def chips_line(subjects: list[Subject]) -> Text:
    out = Text()
    for i, s in enumerate(subjects):
        if i:
            out.append("   ")
        out.append_text(chip(s))
    return out


# --------------------------------------------------------------------------- subject detail


class Section(Static):
    DEFAULT_CSS = """
    Section { border: round $secondary; padding: 0 1; margin: 0 0 1 0; height: auto; }
    """

    def __init__(self, title: str, body: Text | str, **kw: Any) -> None:
        super().__init__(body, **kw)
        self.border_title = title


class SubjectDetail(VerticalScroll):
    DEFAULT_CSS = """
    SubjectDetail { padding: 0 1; }
    SubjectDetail #head { height: auto; margin-bottom: 1; }
    SubjectDetail #meta { padding: 0 2; height: auto; width: 1fr; }
    """

    def __init__(self, subject: Subject, **kw: Any) -> None:
        super().__init__(**kw)
        self.subject = subject

    @property
    def wk(self) -> "WKApp":
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        s = self.subject
        app = self.wk
        assignment = app.assignment_for(s.id)
        stats = app.db.review_statistic(s.id)

        meta = Text()
        meta.append_text(type_badge(s))
        meta.append(f"  Level {s.level}\n\n")
        meta.append(s.primary_meaning, style="bold")
        alts = s.alternative_meanings
        if alts:
            meta.append(", " + ", ".join(alts), style="dim")
        if s.user_synonyms:
            meta.append("\nYour synonyms: " + ", ".join(s.user_synonyms), style="italic #77ffdd")
        meta.append("\n")
        if s.is_kanji:
            on = s.readings_of_type("onyomi")
            kun = s.readings_of_type("kunyomi")
            nan = s.readings_of_type("nanori")
            prim = s.primary_reading_type
            meta.append("\nOn'yomi: ", style="bold" if prim == "onyomi" else "dim")
            meta.append(", ".join(on) or "—", style="bold" if prim == "onyomi" else "dim")
            meta.append("   Kun'yomi: ", style="bold" if prim == "kunyomi" else "dim")
            meta.append(", ".join(kun) or "—", style="bold" if prim == "kunyomi" else "dim")
            if nan:
                meta.append("   Nanori: ", style="dim")
                meta.append(", ".join(nan), style="dim")
        elif s.is_vocab and s.readings:
            meta.append("\nReading: ")
            meta.append(", ".join(r["reading"] for r in s.readings), style="bold")
        if s.parts_of_speech:
            meta.append("\n" + ", ".join(s.parts_of_speech), style="italic dim")
        meta.append("\n\n")
        if assignment:
            stage = assignment.srs_stage
            meta.append(f" {SRS_NAMES.get(stage, stage)} ", style=f"bold white on {srs_color(stage)}")
            if assignment.started:
                meta.append(f"  next review {_rel_time(assignment.available_at)}", style="dim")
            elif assignment.unlocked:
                meta.append("  lesson available", style="dim")
        else:
            meta.append(" Locked ", style="bold white on #555555")
        if stats:
            mc, mi = stats.get("meaning_correct", 0), stats.get("meaning_incorrect", 0)
            rc, ri = stats.get("reading_correct", 0), stats.get("reading_incorrect", 0)
            parts = []
            if mc + mi:
                parts.append(f"meaning {100 * mc // (mc + mi)}%")
            if rc + ri:
                parts.append(f"reading {100 * rc // (rc + ri)}%")
            if parts:
                meta.append("   accuracy: " + ", ".join(parts), style="dim")

        with Horizontal(id="head"):
            yield CharDisplay(s, fetch=app.fetch_bytes, rows=7)
            yield Static(meta, id="meta")

        if s.meaning_mnemonic:
            body = mnemonic_text(s.meaning_mnemonic)
            if s.meaning_hint:
                body.append("\n\n")
                body.append_text(Text.assemble(("Hint: ", "bold"), mnemonic_text(s.meaning_hint)))
            yield Section("Meaning mnemonic", body)
        if s.reading_mnemonic:
            body = mnemonic_text(s.reading_mnemonic)
            if s.reading_hint:
                body.append("\n\n")
                body.append_text(Text.assemble(("Hint: ", "bold"), mnemonic_text(s.reading_hint)))
            yield Section("Reading mnemonic", body)

        comps = app.subjects(s.component_ids)
        if comps:
            title = "Radicals" if s.is_kanji else "Kanji"
            yield Section(f"{title} in this {s.label.lower()}", chips_line(comps))
        similar = app.subjects(s.similar_ids)
        if similar:
            yield Section("Visually similar", chips_line(similar))
        amal = app.subjects(s.amalgamation_ids[:40])
        if amal:
            title = "Kanji using this radical" if s.is_radical else "Vocabulary using this kanji"
            extra = len(s.amalgamation_ids) - len(amal)
            body = chips_line(amal)
            if extra > 0:
                body.append(f"   … and {extra} more", style="dim")
            yield Section(title, body)
        if s.context_sentences:
            body = Text()
            for i, cs in enumerate(s.context_sentences):
                if i:
                    body.append("\n\n")
                body.append(cs.get("ja", ""), style="bold")
                body.append("\n" + cs.get("en", ""), style="dim")
            yield Section("Context sentences", body)

    def related(self) -> list[Subject]:
        s = self.subject
        return self.wk.subjects(s.component_ids + s.similar_ids + s.amalgamation_ids)


class RelatedPicker(ModalScreen[int | None]):
    DEFAULT_CSS = """
    RelatedPicker { align: center middle; }
    RelatedPicker > OptionList { width: 70; max-height: 80%; border: thick $primary; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, subjects: list[Subject]) -> None:
        super().__init__()
        self.subjects = subjects

    def compose(self) -> ComposeResult:
        ol = OptionList(*[Option(chip(s), id=str(s.id)) for s in self.subjects])
        ol.border_title = "Go to related subject"
        yield ol

    @on(OptionList.OptionSelected)
    def _pick(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(int(event.option.id or 0))

    def action_cancel(self) -> None:
        self.dismiss(None)


class SubjectScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("g", "related", "Go to related"),
        Binding("o", "open", "Open on wanikani.com"),
    ]

    def __init__(self, subject: Subject) -> None:
        super().__init__()
        self.subject = subject

    def compose(self) -> ComposeResult:
        yield Header()
        yield SubjectDetail(self.subject)
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"{self.subject.display_chars} · {self.subject.primary_meaning}"
        self.sub_title = f"{self.subject.label} · level {self.subject.level}"

    def action_back(self) -> None:
        self.dismiss()

    def action_open(self) -> None:
        if self.subject.document_url:
            webbrowser.open(self.subject.document_url)

    def action_related(self) -> None:
        rel = self.query_one(SubjectDetail).related()
        if not rel:
            self.notify("No related subjects")
            return

        def go(sid: int | None) -> None:
            if sid:
                self.app.push_screen(SubjectScreen(self.app.subject(sid)))  # type: ignore[attr-defined]

        self.app.push_screen(RelatedPicker(rel), go)


# --------------------------------------------------------------------------- browse


class BrowseScreen(Screen[None]):
    DEFAULT_CSS = """
    BrowseScreen #levels { width: 14; border-right: solid $secondary; }
    BrowseScreen #table { width: 1fr; }
    BrowseScreen #search { display: none; dock: top; }
    BrowseScreen #search.shown { display: block; }
    """
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("slash", "search", "Search"),
        Binding("t", "cycle_type", "Type filter"),
    ]
    TYPE_FILTERS = [None, ("radical",), ("kanji",), ("vocabulary", "kana_vocabulary")]

    def __init__(self, level: int, max_level: int = 60) -> None:
        super().__init__()
        self.level = level
        self.max_level = max_level
        self.type_idx = 0
        self.rows: dict[str, Subject] = {}

    @property
    def wk(self) -> "WKApp":
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search characters, meaning or slug… (Enter to search, Esc to close)", id="search")
        with Horizontal():
            yield OptionList(*[Option(f"Level {n}", id=f"L{n}") for n in range(1, self.max_level + 1)], id="levels")
            table: DataTable = DataTable(id="table", cursor_type="row", zebra_stripes=True)
            yield table
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Browse"
        table = self.query_one("#table", DataTable)
        table.add_columns("Type", "Item", "Meaning", "Reading", "SRS", "Next review")
        levels = self.query_one("#levels", OptionList)
        levels.highlighted = self.level - 1
        self.load_level(self.level)
        table.focus()

    @on(OptionList.OptionHighlighted, "#levels")
    def _level_changed(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id:
            self.load_level(int(event.option.id[1:]))

    def action_cycle_type(self) -> None:
        self.type_idx = (self.type_idx + 1) % len(self.TYPE_FILTERS)
        self.load_level(self.level)

    def load_level(self, level: int) -> None:
        self.level = level
        types = self.TYPE_FILTERS[self.type_idx]
        subs = self.wk.subjects_at_level(level, types)
        self.sub_title = f"Level {level}" + (f" · {types[0]}" if types else "") + f" · {len(subs)} items"
        self.fill(subs)

    def fill(self, subs: list[Subject]) -> None:
        table = self.query_one("#table", DataTable)
        table.clear()
        self.rows = {}
        asg = self.wk.db.assignments_for(s.id for s in subs)
        for s in subs:
            a = asg.get(s.id)
            if a:
                stage = a["data"].get("srs_stage", 0)
                srs = Text(SRS_NAMES.get(stage, str(stage)), style=srs_color(stage))
                nxt = _rel_time(parse_ts(a["data"].get("available_at"))) if a["data"].get("started_at") else "lesson"
            else:
                srs = Text("Locked", style="dim")
                nxt = ""
            reading = ", ".join(s.primary_readings) if s.has_reading else ""
            key = str(s.id)
            table.add_row(type_badge(s), Text(s.display_chars, style="bold"), s.primary_meaning, reading, srs, nxt, key=key)
            self.rows[key] = s

    @on(DataTable.RowSelected)
    def _row(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        if key and key in self.rows:
            self.app.push_screen(SubjectScreen(self.rows[key]))

    def action_search(self) -> None:
        box = self.query_one("#search", Input)
        box.add_class("shown")
        box.focus()

    @on(Input.Submitted, "#search")
    def _search(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            subs = self.wk.search_subjects(text)
            self.sub_title = f"Search “{text}” · {len(subs)} results"
            self.fill(subs)
        self.query_one("#table", DataTable).focus()

    def on_key(self, event) -> None:  # close search box with Esc while it is focused
        box = self.query_one("#search", Input)
        if event.key == "escape" and box.has_focus:
            box.remove_class("shown")
            self.query_one("#table", DataTable).focus()
            event.stop()

    def action_back(self) -> None:
        self.dismiss()


# --------------------------------------------------------------------------- sessions


class ConfirmScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Static { width: 60; padding: 1 2; border: thick $warning; background: $surface; }
    """
    BINDINGS = [Binding("y", "yes", "Yes"), Binding("n", "no", "No"), Binding("escape", "no", "No")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Static(Text.assemble(self.message, "\n\n", ("y", "bold"), " yes   ", ("n", "bold"), " no"))

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class SessionScreen(Screen[list[Item]]):
    """Review session (mode='review') or lesson quiz (mode='lesson')."""

    DEFAULT_CSS = """
    SessionScreen #stage { align: center top; padding: 1 2; }
    SessionScreen CharDisplay { width: 100%; margin: 0 0 1 0; align-horizontal: center; content-align: center middle; }
    SessionScreen #prompt { width: 100%; height: 3; content-align: center middle; text-style: bold; }
    SessionScreen #prompt.meaning { background: #eeeeee; color: #222222; }
    SessionScreen #prompt.reading { background: #333333; color: #ffffff; }
    SessionScreen #answer { width: 100%; }
    SessionScreen #answer.correct { background: #1f7a3c 40%; border: tall #2fbf5f; }
    SessionScreen #answer.incorrect { background: #8a1c1c 40%; border: tall #e04040; }
    SessionScreen #feedback { width: 100%; height: auto; min-height: 3; padding: 1 2; content-align: center top; }
    SessionScreen #status { dock: bottom; height: 1; padding: 0 2; background: $panel; }
    """
    BINDINGS = [
        Binding("escape", "leave", "Wrap up / quit"),
        Binding("f1", "info", "Item info"),
        Binding("ctrl+i", "info", "Item info", show=False),
    ]

    def __init__(self, mode: str, items: list[Item]) -> None:
        super().__init__()
        self.mode = mode
        self.queue = Queue(items, active_size=10 if mode == "review" else max(1, len(items)))
        self.current: tuple[Item, Part] | None = None
        self.awaiting = False
        self.failed: list[str] = []

    @property
    def wk(self) -> "WKApp":
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="stage"):
            yield CharDisplay(None, fetch=self.wk.fetch_bytes, rows=7, id="char")
            yield Static("", id="prompt")
            yield Input(placeholder="Your response", id="answer")
            yield Static("", id="feedback")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Reviews" if self.mode == "review" else "Lesson quiz"
        self.next_prompt()

    # -- flow --------------------------------------------------------------

    def next_prompt(self) -> None:
        nxt = self.queue.next()
        if nxt is None:
            self.finish()
            return
        self.current = nxt
        item, part = nxt
        s = item.subject
        self.awaiting = False
        self.query_one("#char", CharDisplay).show(s)
        prompt = self.query_one("#prompt", Static)
        prompt.remove_class("meaning", "reading")
        prompt.add_class(part.value)
        prompt.update(Text(f"{s.label}  {part.value.title()}", style="bold"))
        box = self.query_one("#answer", Input)
        box.remove_class("correct", "incorrect")
        box.value = ""
        box.placeholder = "Your response" if part is Part.MEANING else "答え"
        box.focus()
        self.query_one("#feedback", Static).update("")
        self.update_status()

    def update_status(self) -> None:
        q = self.queue
        done = len(q.finished)
        acc = f"{100 * q.correct_count // done}%" if done else "—"
        extra = "  · wrapping up" if q.wrapping_up else ""
        self.query_one("#status", Static).update(
            f"Remaining {q.remaining}   Done {done}/{q.total}   Accuracy {acc}{extra}   [F1 info · Esc wrap up]"
        )

    @on(Input.Changed, "#answer")
    def _changed(self, event: Input.Changed) -> None:
        if self.awaiting or not self.current:
            return
        if self.current[1] is Part.READING:
            conv = to_kana_live(event.value)
            if conv != event.value:
                event.input.value = conv

    @on(Input.Submitted, "#answer")
    def _submitted(self, event: Input.Submitted) -> None:
        if not self.current:
            return
        if self.awaiting:
            self.next_prompt()
            return
        item, part = self.current
        s = item.subject
        result = check_meaning(event.value, s) if part is Part.MEANING else check_reading(event.value, s)
        fb = self.query_one("#feedback", Static)
        box = self.query_one("#answer", Input)
        if result.verdict is Verdict.RETRY:
            fb.update(Text(result.message, style="bold yellow"))
            return
        correct = result.verdict is Verdict.CORRECT
        completed = self.queue.mark(item, part, correct)
        box.add_class("correct" if correct else "incorrect")
        msg = Text()
        if correct:
            msg.append("Correct", style="bold green")
            if not result.exact:
                msg.append(f"  ·  {result.message}", style="yellow")
            if part is Part.MEANING and len(s.accepted_meanings) > 1:
                msg.append("\n" + ", ".join(s.accepted_meanings[:6]), style="dim")
            elif part is Part.READING and len(s.accepted_readings) > 1:
                msg.append("\n" + ", ".join(s.accepted_readings), style="dim")
        else:
            msg.append("Incorrect", style="bold red")
            if part is Part.MEANING:
                msg.append("\nAccepted: " + ", ".join(s.accepted_meanings[:6]))
            else:
                msg.append("\nAccepted: " + ", ".join(s.accepted_readings))
        if completed:
            if self.mode == "review":
                new_stage = next_srs_stage(item.assignment.srs_stage, item.incorrect)
                msg.append("\n")
                msg.append(f" {SRS_NAMES[new_stage]} ", style=f"bold white on {srs_color(new_stage)}")
                self.submit_review(item)
            else:
                self.start_lesson(item)
        msg.append("\n\nEnter to continue · F1 for details", style="dim")
        fb.update(msg)
        self.awaiting = True
        self.update_status()

    def finish(self) -> None:
        def close(_: None) -> None:
            self.dismiss(self.queue.finished)

        self.app.push_screen(SummaryScreen(self.mode, self.queue.finished, self.failed), close)

    # -- API side effects --------------------------------------------------

    @work(thread=True, group="submit")
    def submit_review(self, item: Item) -> None:
        try:
            resp = self.wk.api.create_review(item.assignment.id, item.wrong[Part.MEANING], item.wrong[Part.READING])
            updated = resp.get("resources_updated") or {}
            db = self.wk.db
            if updated.get("assignment"):
                db.upsert_assignment(updated["assignment"])
            if updated.get("review_statistic"):
                db.upsert_review_statistics([updated["review_statistic"]])
            item.submitted = True
        except (ApiError, Exception) as exc:  # noqa: BLE001
            self.failed.append(f"{item.subject.display_chars}: {exc}")
            self.app.call_from_thread(self.notify, f"Failed to submit {item.subject.display_chars}: {exc}", severity="error", timeout=8)

    @work(thread=True, group="submit")
    def start_lesson(self, item: Item) -> None:
        try:
            resp = self.wk.api.start_assignment(item.assignment.id)
            if resp.get("object") == "assignment":
                self.wk.db.upsert_assignment(resp)
            item.submitted = True
        except (ApiError, Exception) as exc:  # noqa: BLE001
            self.failed.append(f"{item.subject.display_chars}: {exc}")
            self.app.call_from_thread(self.notify, f"Failed to start {item.subject.display_chars}: {exc}", severity="error", timeout=8)

    # -- actions -----------------------------------------------------------

    def action_info(self) -> None:
        if not self.current:
            return
        if not self.awaiting and self.mode == "review":
            self.notify("Answer first, then check the details")
            return
        self.app.push_screen(SubjectScreen(self.current[0].subject))

    def action_leave(self) -> None:
        q = self.queue
        if self.mode == "review" and not q.wrapping_up and q.pending:
            q.wrap_up()
            self.update_status()
            self.notify(f"Wrapping up: {q.remaining} item(s) left. Esc again to quit now.")
            return

        def confirm(ok: bool | None) -> None:
            if ok:
                self.dismiss(q.finished)

        left = q.remaining
        msg = f"Quit now? {left} unfinished item(s) will simply stay in your queue." if left else "Quit?"
        self.app.push_screen(ConfirmScreen(msg), confirm)


class SummaryScreen(Screen[None]):
    DEFAULT_CSS = """
    SummaryScreen #summary { padding: 1 2; height: auto; }
    """
    BINDINGS = [Binding("escape", "close", "Close"), Binding("enter", "close", "Close")]

    def __init__(self, mode: str, items: list[Item], failed: list[str]) -> None:
        super().__init__()
        self.mode = mode
        self.items = items
        self.failed = failed

    def compose(self) -> ComposeResult:
        yield Header()
        n = len(self.items)
        good = sum(1 for i in self.items if i.all_correct)
        head = Text()
        head.append(f"{'Reviews' if self.mode == 'review' else 'Lessons'} complete: {n} item(s)", style="bold")
        if n:
            head.append(f"   {100 * good // n}% correct first time")
        if self.failed:
            head.append(f"\n{len(self.failed)} submission(s) failed and were NOT recorded:\n", style="bold red")
            head.append("\n".join(self.failed), style="red")
        yield Static(head, id="summary")
        table: DataTable = DataTable(cursor_type="row", zebra_stripes=True)
        yield table
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Session summary"
        table = self.query_one(DataTable)
        cols = ["Item", "Meaning", "Result", "Wrong (m/r)"]
        if self.mode == "review":
            cols.append("SRS")
        table.add_columns(*cols)
        for it in sorted(self.items, key=lambda i: (i.all_correct, i.subject.level)):
            s = it.subject
            res = Text("✓", style="green") if it.all_correct else Text("✗", style="red")
            row = [type_badge(s), Text(f"{s.display_chars}  ·  {s.primary_meaning}"), res, f"{it.wrong[Part.MEANING]}/{it.wrong[Part.READING]}"]
            if self.mode == "review":
                old, new = it.assignment.srs_stage, next_srs_stage(it.assignment.srs_stage, it.incorrect)
                row.append(Text(f"{SRS_NAMES[old]} → {SRS_NAMES[new]}", style=srs_color(new)))
            table.add_row(*row)
        table.focus()

    def action_close(self) -> None:
        self.dismiss()


# --------------------------------------------------------------------------- lessons


class LessonScreen(Screen[None]):
    DEFAULT_CSS = """
    LessonScreen #page { height: 1fr; }
    LessonScreen #nav { dock: bottom; height: 1; padding: 0 2; background: $panel; }
    """
    BINDINGS = [
        Binding("right", "next", "Next"),
        Binding("n", "next", "Next", show=False),
        Binding("left", "prev", "Previous"),
        Binding("p", "prev", "Previous", show=False),
        Binding("escape", "leave", "Quit lessons"),
    ]

    def __init__(self, items: list[Item]) -> None:
        super().__init__()
        self.items = items
        self.index = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(id="page")
        yield Static("", id="nav")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Lessons"
        self.show(0)

    def show(self, index: int) -> None:
        self.index = index
        page = self.query_one("#page", Vertical)
        page.remove_children()
        s = self.items[index].subject
        page.mount(SubjectDetail(s))
        self.sub_title = f"{index + 1} / {len(self.items)} · {s.label} {s.display_chars}"
        last = index == len(self.items) - 1
        self.query_one("#nav", Static).update(
            f"Lesson {index + 1}/{len(self.items)}   ←/→ navigate   " + ("→ or Enter: start quiz" if last else "")
        )

    def action_next(self) -> None:
        if self.index + 1 < len(self.items):
            self.show(self.index + 1)
        else:
            self.start_quiz()

    def action_prev(self) -> None:
        if self.index > 0:
            self.show(self.index - 1)

    def on_key(self, event) -> None:
        if event.key == "enter" and self.index == len(self.items) - 1:
            self.start_quiz()

    def start_quiz(self) -> None:
        def close(_: object) -> None:
            self.dismiss()

        self.app.push_screen(SessionScreen("lesson", self.items), close)

    def action_leave(self) -> None:
        def maybe_close(ok: bool | None) -> None:
            if ok:
                self.dismiss()

        self.app.push_screen(ConfirmScreen("Leave lessons? Nothing has been recorded yet."), maybe_close)
