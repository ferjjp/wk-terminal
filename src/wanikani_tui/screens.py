"""Screens: subject detail, browse, review/lesson sessions, lesson picker, summary, modals."""

from __future__ import annotations

import webbrowser
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ItemGrid, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Header, Input, OptionList, Static
from textual.widgets.option_list import Option

from .answers import Verdict, check_meaning, check_reading, to_kana_live
from .config import settings
from .db import parse_ts
from .keys import key
from .models import SRS_NAMES, Subject, fmt_reading, next_srs_stage, srs_color
from .session import Item, Part, Queue
from .widgets import CharDisplay, Chip, ImageWidget, mnemonic_text, type_badge

if TYPE_CHECKING:
    from .app import WKApp


def _rel_time(ts: datetime | None) -> str:
    if ts is None:
        return "—"
    secs = (ts - datetime.now(timezone.utc)).total_seconds()
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


def _vim() -> bool:
    return settings().ui_vim_keys


# --------------------------------------------------------------------------- subject detail


class Section(Static):
    DEFAULT_CSS = """
    Section { border: round $secondary; padding: 0 1; margin: 0 0 1 0; height: auto; }
    """

    def __init__(self, title: str, body: Text | str, **kw: Any) -> None:
        super().__init__(body, **kw)
        self.border_title = title


class ChipSection(Vertical):
    DEFAULT_CSS = """
    ChipSection { border: round $secondary; padding: 0 1; margin: 0 0 1 0; height: auto; }
    ChipSection ItemGrid { height: auto; }
    """

    def __init__(self, title: str, subjects: list[Subject], extra: str = "", **kw: Any) -> None:
        super().__init__(**kw)
        self.border_title = title
        self.subjects = subjects
        self.extra = extra

    def compose(self) -> ComposeResult:
        app: WKApp = self.app  # type: ignore[assignment]
        with ItemGrid(min_column_width=24):
            for s in self.subjects:
                yield Chip(s, fetch=app.core.fetch_bytes)
        if self.extra:
            yield Static(Text(self.extra, style="dim"))


class SubjectDetail(VerticalScroll):
    DEFAULT_CSS = """
    SubjectDetail { padding: 0 1; }
    SubjectDetail #head { height: auto; margin-bottom: 1; }
    SubjectDetail #meta { padding: 0 2; height: auto; width: 1fr; }
    """
    BINDINGS = [
        Binding(key("scroll_down"), "scroll_down", "Down", show=False),
        Binding(key("scroll_up"), "scroll_up", "Up", show=False),
    ] if _vim() else []

    def __init__(self, subject: Subject, **kw: Any) -> None:
        super().__init__(**kw)
        self.subject = subject

    @property
    def wk(self) -> "WKApp":
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        s = self.subject
        app = self.wk
        core = app.core
        assignment = core.assignment_for(s.id)
        stats = core.db.review_statistic(s.id)

        meta = Text()
        meta.append_text(type_badge(s))
        meta.append(f"  Level {s.level}\n\n")
        meta.append(s.primary_meaning, style="bold")
        alts = s.alternative_meanings
        if alts:
            meta.append(", " + ", ".join(alts), style="dim")
        if s.user_synonyms:
            meta.append("\nYour synonyms: " + ", ".join(s.user_synonyms), style="italic #77ffdd")
        if s.user_note:
            meta.append("\nYour note: " + s.user_note, style="italic #ffd77a")
        meta.append("\n")
        if s.is_kanji:
            on_ = s.readings_of_type("onyomi")
            kun = s.readings_of_type("kunyomi")
            nan = s.readings_of_type("nanori")
            prim = s.primary_reading_type
            meta.append("\nOn'yomi: ", style="bold" if prim == "onyomi" else "dim")
            meta.append(", ".join(fmt_reading(r, "onyomi") for r in on_) or "—", style="bold" if prim == "onyomi" else "dim")
            meta.append("   Kun'yomi: ", style="bold" if prim == "kunyomi" else "dim")
            meta.append(", ".join(kun) or "—", style="bold" if prim == "kunyomi" else "dim")
            if nan:
                meta.append("   Nanori: ", style="dim")
                meta.append(", ".join(nan), style="dim")
        elif s.is_vocab and s.readings:
            meta.append("\nReading: ")
            meta.append(", ".join(r["reading"] for r in s.readings), style="bold")
            if settings().ui_pitch_accent:
                from . import pitch

                if pitch.is_cached():
                    pt = pitch.describe(s.characters or "", s.primary_readings[0] if s.primary_readings else "")
                    if pt:
                        meta.append("\nPitch: ")
                        meta.append_text(pt)
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
        hints = []
        if s.audio_urls:
            hints.append(f"[{key('audio')}] audio")
        if s.is_kanji:
            hints.append(f"[{key('strokes')}] stroke order")
        hints += [f"[{key('synonym')}] add synonym", f"[{key('note')}] note", f"[{key('related')}] related", f"[{key('open')}] browser"]
        meta.append("\n" + "  ".join(hints), style="dim")

        with Horizontal(id="head"):
            yield CharDisplay(s, fetch=core.fetch_bytes, rows=app.image_rows())
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

        comps = core.subjects(s.component_ids)
        if s.is_vocab and s.type == "vocabulary" and comps:
            yield ReadingBreakdown(s, comps)
        if s.is_vocab and settings().ui_pitch_accent:
            yield PitchSection(s)
        if comps:
            yield ChipSection(("Radicals" if s.is_kanji else "Kanji") + f" in this {s.label.lower()}", comps)
        similar = core.subjects(s.similar_ids)
        if similar:
            yield ChipSection("Visually similar", similar)
        amal = core.subjects(s.amalgamation_ids[:40])
        if amal:
            title = "Kanji using this radical" if s.is_radical else "Vocabulary using this kanji"
            extra = len(s.amalgamation_ids) - len(amal)
            yield ChipSection(title, amal, f"… and {extra} more" if extra > 0 else "")
        if s.context_sentences:
            body = Text()
            for i, cs in enumerate(s.context_sentences):
                if i:
                    body.append("\n\n")
                body.append(cs.get("ja", ""), style="bold")
                body.append("\n" + cs.get("en", ""), style="dim")
            yield Section("Context sentences", body)
        if s.is_kanji and s.characters and settings().ui_community_data:
            yield KeiseiSection(s)
            yield NiaiSection(s)

    def related(self) -> list[Subject]:
        s = self.subject
        return self.wk.core.subjects(s.component_ids + s.similar_ids + s.amalgamation_ids)


class ReadingBreakdown(Static):
    """Which reading each kanji contributes to a vocabulary word, coloured by how familiar it should be."""

    DEFAULT_CSS = """
    ReadingBreakdown { border: round $secondary; padding: 0 1; margin: 0 0 1 0; height: auto; }
    """

    def __init__(self, vocab: Subject, kanji: list[Subject], **kw: Any) -> None:
        super().__init__("", **kw)
        self.border_title = "Reading breakdown"
        self.vocab = vocab
        self.kanji = kanji

    def on_mount(self) -> None:
        from .analyzer import analyze
        from .models import Assignment

        core = self.app.core  # type: ignore[attr-defined]
        asg = {k.id: Assignment.from_raw(a) for k, a in ((k, core.db.assignment_for(k.id)) for k in self.kanji) if a}
        segs = analyze(self.vocab, self.kanji, asg)
        if not segs:
            self.remove()
            return
        t = Text()
        for seg in segs:
            t.append(f" {seg.text} ", style=f"bold white on {seg.colour}" if seg.kind != "kana" else "bold")
            t.append(f"{seg.reading} ", style=seg.colour if seg.kind != "kana" else "dim")
        t.append("\n")
        notes = []
        for seg in segs:
            if seg.kind == "kana" or seg.kanji is None:
                continue
            k = seg.kanji
            prim = ", ".join(fmt_reading(r, k.primary_reading_type) for r in k.primary_readings)
            how = seg.label
            if seg.kind in ("rendaku", "sokuon"):
                how += f" of {prim}"
            elif seg.kind == "exception":
                how += f", not built from {prim}"
            state = "learned" if seg.known else "not learned yet"
            notes.append(Text.assemble((f"{k.characters} ", f"bold {seg.colour}"), (f"{seg.reading}: {how} · {state}", "dim")))
        for n in notes:
            t.append("\n")
            t.append_text(n)
        t.append("\n\n")
        for kind, lbl in (("onyomi", "known reading"), ("nanori", "rare reading"), ("rendaku", "sound change"), ("exception", "exceptional")):
            t.append(" ■ ", style={"onyomi": "#2fbf5f", "nanori": "#e0b040", "rendaku": "#ffa040", "exception": "#e04040"}[kind])
            t.append(lbl + "  ", style="dim")
        self.update(t)


class PitchSection(Static):
    """Pitch accent for a vocabulary word; downloads the Kanjium table the first time."""

    DEFAULT_CSS = """
    PitchSection { border: round $secondary; padding: 0 1; margin: 0 0 1 0; height: auto; }
    """

    def __init__(self, vocab: Subject, **kw: Any) -> None:
        super().__init__(Text("loading pitch accent…", style="dim"), **kw)
        self.border_title = "Pitch accent"
        self.vocab = vocab

    def on_mount(self) -> None:
        self._load()

    @work(thread=True)
    def _load(self) -> None:
        from . import pitch

        core = self.app.core  # type: ignore[attr-defined]
        s = self.vocab
        reading = s.primary_readings[0] if s.primary_readings else (s.characters or "")
        body = Text()
        any_hit = False
        for r in s.readings or [{"reading": reading}]:
            desc = pitch.describe(s.characters or "", r["reading"], core.fetch_bytes)
            if desc:
                any_hit = True
                if body.plain:
                    body.append("\n")
                body.append_text(desc)
        if not any_hit:
            self.app.call_from_thread(self.remove)
            return
        body.append("\n\n")
        body.append("underlined morae are high, ꜜ marks the drop · " + pitch.ATTRIBUTION, style="dim")
        self.app.call_from_thread(self.update, body)


class ExtSection(Vertical):
    """A section fed by a community dataset that may need downloading first; fills itself in a worker."""

    DEFAULT_CSS = """
    ExtSection { border: round $secondary; padding: 0 1; margin: 0 0 1 0; height: auto; }
    ExtSection ItemGrid { height: auto; }
    ExtSection .ext-note { color: $text-muted; }
    """
    TITLE = ""

    def __init__(self, subject: Subject, **kw: Any) -> None:
        super().__init__(**kw)
        self.subject = subject
        self.border_title = self.TITLE

    def compose(self) -> ComposeResult:
        yield Static(Text("loading…", style="dim"), id="body")

    def on_mount(self) -> None:
        self._load()

    @work(thread=True)
    def _load(self) -> None:
        app: WKApp = self.app  # type: ignore[assignment]
        try:
            result = self.build(app)
        except Exception as exc:  # noqa: BLE001
            result = None
            self.app.call_from_thread(self._set_note, f"unavailable ({exc})")
            return
        self.app.call_from_thread(self._fill, result)

    def _set_note(self, text: str) -> None:
        self.query_one("#body", Static).update(Text(text, style="dim"))

    def build(self, app: "WKApp"):  # pragma: no cover - overridden
        raise NotImplementedError

    def _fill(self, result) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class KeiseiSection(ExtSection):
    TITLE = "Composition · Keisei"

    def build(self, app: "WKApp"):
        from . import extdata

        return extdata.keisei_info(self.subject.characters or "", app.core.fetch_bytes)

    def _fill(self, info) -> None:
        core = self.app.core  # type: ignore[attr-defined]
        if not info:
            self.remove()
            return
        body = Text()
        body.append(info.get("type_label", ""), style="bold")
        if info.get("phonetic"):
            q = info.get("quality", "")
            body.append(f"   {q} ", style="bold white on #555555")
            body.append({"天": "all readings follow the mark", "上": "mostly follows the mark",
                         "中": "sometimes follows the mark", "下": "reading unrelated to the mark"}.get(q, ""), style="dim")
            body.append("\n\nphonetic mark ", style="dim")
            body.append(f" {info['phonetic']} ", style="bold white on #ff00aa")
            body.append(" read " + ", ".join(fmt_reading(r, "onyomi") for r in info.get("mark_readings", [])), style="bold")
            if info.get("mark_wk_radical"):
                body.append(f"  (WaniKani radical “{info['mark_wk_radical']}”)", style="dim")
            if info.get("semantic"):
                body.append(f"   ·   meaning part {info['semantic']}", style="dim")
            body.append("\nthis kanji: " + ", ".join(fmt_reading(r, "onyomi") for r in info.get("readings", [])))
        elif info.get("readings"):
            body.append("   readings " + ", ".join(fmt_reading(r, "onyomi") for r in info["readings"]), style="dim")
        if info.get("comment"):
            body.append("\n" + info["comment"], style="italic dim")
        self.query_one("#body", Static).update(body)

        def chips_for(chars: list[str], title: str) -> None:
            subs = [x for x in (core.db.search_subjects(c, limit=3) for c in chars) for x in x if x["object"] == "kanji"]
            seen: set[int] = set()
            uniq = []
            for raw in subs:
                if raw["id"] not in seen and raw["data"].get("characters") in chars:
                    seen.add(raw["id"])
                    uniq.append(Subject.from_raw(raw))
            missing = [c for c in chars if c not in {u.characters for u in uniq}]
            if uniq:
                self.mount(Static(Text(title, style="bold")))
                grid = ItemGrid(min_column_width=24)
                self.mount(grid)
                grid.mount_all([Chip(u, fetch=core.fetch_bytes) for u in uniq])
            if missing:
                self.mount(Static(Text(("also, outside WaniKani: " if uniq else title + " (outside WaniKani): ") + " ".join(missing), style="dim"), classes="ext-note"))

        if info.get("compounds"):
            chips_for(info["compounds"], "Same mark, same reading")
        if info.get("non_compounds"):
            chips_for(info["non_compounds"], "Looks like it, but read differently")
        mark = info.get("as_mark")
        if mark and mark.get("compounds"):
            self.mount(Static(Text(f"This kanji is itself a phonetic mark read {', '.join(fmt_reading(r, 'onyomi') for r in mark['readings'])}", style="bold")))
            chips_for(mark["compounds"], "Kanji that borrow its reading")
        self.mount(Static(Text(f"{__import__('wanikani_tui.extdata', fromlist=['ATTRIBUTION']).ATTRIBUTION}", style="dim"), classes="ext-note"))


class NiaiSection(ExtSection):
    TITLE = "More look-alikes · Niai"

    def build(self, app: "WKApp"):
        from . import extdata

        sims = extdata.niai_similar(self.subject.characters or "", app.core.fetch_bytes)
        if sims is None:
            return None
        own = {x.characters for x in app.core.subjects(self.subject.similar_ids)}
        out = []
        for ch, score in sims:
            if ch in own:
                continue
            for raw in app.core.db.search_subjects(ch, limit=3):
                if raw["object"] == "kanji" and raw["data"].get("characters") == ch:
                    out.append((Subject.from_raw(raw), score))
                    break
        return out[:12]

    def _fill(self, result) -> None:
        if not result:
            self.remove()
            return
        self.query_one("#body", Static).update(Text("Beyond WaniKani's own list, by visual similarity", style="dim"))
        grid = ItemGrid(min_column_width=24)
        self.mount(grid)
        core = self.app.core  # type: ignore[attr-defined]
        grid.mount_all([Chip(sub, fetch=core.fetch_bytes) for sub, _ in result])


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


class TextPrompt(ModalScreen[str | None]):
    DEFAULT_CSS = """
    TextPrompt { align: center middle; }
    TextPrompt > Vertical { width: 70; height: auto; border: thick $primary; background: $surface; padding: 1 2; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, value: str = "", placeholder: str = "") -> None:
        super().__init__()
        self.title_text = title
        self.value = value
        self.placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text(self.title_text, style="bold"))
            yield Input(value=self.value, placeholder=self.placeholder)
            yield Static(Text("Enter to save · Esc to cancel", style="dim"))

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted)
    def _done(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class StrokeScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    StrokeScreen { align: center middle; }
    StrokeScreen > Vertical { width: auto; height: auto; border: thick $primary; background: $surface; padding: 1 2; align: center middle; }
    StrokeScreen .wk-image { width: auto; height: 16; }
    """
    BINDINGS = [Binding("escape", "close", "Close"), Binding("s", "close", "Close", show=False)]

    def __init__(self, subject: Subject) -> None:
        super().__init__()
        self.subject = subject

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text(f"Stroke order · {self.subject.characters}", style="bold"))
            if ImageWidget is not None:
                yield ImageWidget(None, classes="wk-image", id="strokes")
            yield Static(Text("loading from KanjiVG…", style="dim"), id="note")

    def on_mount(self) -> None:
        self._load()

    @work(thread=True)
    def _load(self) -> None:
        from .images import stroke_image

        app: WKApp = self.app  # type: ignore[assignment]
        img = stroke_image(self.subject.characters or "", app.core.fetch_bytes)
        if img is None or ImageWidget is None:
            self.app.call_from_thread(self.query_one("#note", Static).update, Text("No stroke data available", style="red"))
            return
        self.app.call_from_thread(setattr, self.query_one("#strokes"), "image", img)
        self.app.call_from_thread(self.query_one("#note", Static).update, Text("Strokes numbered in drawing order · data: KanjiVG (CC BY-SA)", style="dim"))

    def action_close(self) -> None:
        self.dismiss()


class SubjectScreen(Screen[None]):
    BINDINGS = [
        Binding(key("back"), "back", "Back"),
        Binding(key("related"), "related", "Related"),
        Binding(key("audio"), "audio", "Audio"),
        Binding(key("strokes"), "strokes", "Strokes"),
        Binding(key("synonym"), "synonym", "Synonym"),
        Binding(key("note"), "note", "Note"),
        Binding(key("open"), "open", "Browser"),
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

    @property
    def wk(self) -> "WKApp":
        return self.app  # type: ignore[return-value]

    def rebuild(self) -> None:
        old = self.query_one(SubjectDetail)
        self.subject = self.wk.core.subject(self.subject.id)
        old.remove()
        self.mount(SubjectDetail(self.subject), before=self.query_one(Footer))

    def action_back(self) -> None:
        self.dismiss()

    def action_open(self) -> None:
        if self.subject.document_url:
            webbrowser.open(self.subject.document_url)

    def action_audio(self) -> None:
        self.wk.play_audio(self.subject)

    def action_strokes(self) -> None:
        if self.subject.is_kanji and self.subject.characters:
            self.app.push_screen(StrokeScreen(self.subject))
        else:
            self.notify("Stroke order is available for kanji")

    def action_synonym(self) -> None:
        def save(text: str | None) -> None:
            if text and text.strip():
                self._save_material("synonym", text.strip())

        self.app.push_screen(TextPrompt(f"Add a meaning synonym for {self.subject.display_chars}", placeholder="e.g. h2o"), save)

    def action_note(self) -> None:
        def save(text: str | None) -> None:
            if text is not None:
                self._save_material("note", text.strip())

        self.app.push_screen(TextPrompt(f"Your note for {self.subject.display_chars}", value=self.subject.user_note or ""), save)

    @work(thread=True)
    def _save_material(self, kind: str, text: str) -> None:
        try:
            if kind == "synonym":
                self.wk.core.add_synonym(self.subject, text)
            else:
                self.wk.core.set_note(self.subject, text)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self.notify, f"Could not save: {exc}", severity="error")
            return
        self.app.call_from_thread(self.rebuild)
        self.app.call_from_thread(self.notify, "Saved to WaniKani")

    def action_related(self) -> None:
        rel = self.query_one(SubjectDetail).related()
        if not rel:
            self.notify("No related subjects")
            return

        def go(sid: int | None) -> None:
            if sid:
                self.app.push_screen(SubjectScreen(self.wk.core.subject(sid)))

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
        Binding(key("back"), "back", "Back"),
        Binding(key("search"), "search", "Search"),
        Binding(key("type_filter"), "cycle_type", "Type"),
        Binding(key("filter"), "cycle_filter", "Filter"),
        Binding(key("study"), "study", "Study these"),
    ]
    TYPE_FILTERS = [None, ("radical",), ("kanji",), ("vocabulary", "kana_vocabulary")]
    FILTERS = ["all", "due", "leech", "apprentice", "guru", "master", "enlightened", "burned"]

    def __init__(self, level: int, max_level: int = 60, flt: str = "all") -> None:
        super().__init__()
        self.level = level
        self.max_level = max_level
        self.type_idx = 0
        self.filter_idx = self.FILTERS.index(flt) if flt in self.FILTERS else 0
        self.rows: dict[str, Subject] = {}

    @property
    def wk(self) -> "WKApp":
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search characters, meaning or slug… (Enter to search, Esc to close)", id="search")
        with Horizontal():
            yield OptionList(*[Option(f"Level {n}", id=f"L{n}") for n in range(1, self.max_level + 1)], id="levels")
            yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Browse"
        table = self.query_one("#table", DataTable)
        table.add_columns("Type", "Item", "Meaning", "Reading", "SRS", "Next review")
        levels = self.query_one("#levels", OptionList)
        levels.highlighted = self.level - 1
        self.reload()
        table.focus()

    @on(OptionList.OptionHighlighted, "#levels")
    def _level_changed(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id:
            self.level = int(event.option.id[1:])
            if self.FILTERS[self.filter_idx] == "all":
                self.reload()

    def action_cycle_type(self) -> None:
        self.type_idx = (self.type_idx + 1) % len(self.TYPE_FILTERS)
        self.reload()

    def action_cycle_filter(self) -> None:
        self.filter_idx = (self.filter_idx + 1) % len(self.FILTERS)
        self.reload()

    def reload(self) -> None:
        types = self.TYPE_FILTERS[self.type_idx]
        flt = self.FILTERS[self.filter_idx]
        if flt == "all":
            subs = self.wk.core.subjects_at_level(self.level, types)
            where = f"Level {self.level}"
        else:
            subs = self.wk.core.subjects_filtered(flt)
            if types:
                subs = [s for s in subs if s.type in types]
            where = {"due": "Due in 24 h", "leech": "Leeches"}.get(flt, flt.title())
        self.sub_title = where + (f" · {types[0]}" if types else "") + f" · {len(subs)} items"
        self.fill(subs)

    def fill(self, subs: list[Subject]) -> None:
        table = self.query_one("#table", DataTable)
        table.clear()
        self.rows = {}
        asg = self.wk.core.db.assignments_for(s.id for s in subs)
        for s in subs:
            a = asg.get(s.id)
            if a:
                stage = a["data"].get("srs_stage", 0)
                srs = Text(SRS_NAMES.get(stage, str(stage)), style=srs_color(stage))
                nxt = _rel_time(parse_ts(a["data"].get("available_at"))) if a["data"].get("started_at") else "lesson"
            else:
                srs = Text("Locked", style="dim")
                nxt = ""
            reading = ", ".join(fmt_reading(r, s.primary_reading_type) for r in s.primary_readings) if s.has_reading else ""
            table.add_row(type_badge(s), Text(s.display_chars, style="bold"), s.primary_meaning, reading, srs, nxt, key=str(s.id))
            self.rows[str(s.id)] = s

    @on(DataTable.RowSelected)
    def _row(self, event: DataTable.RowSelected) -> None:
        k = event.row_key.value
        if k and k in self.rows:
            self.app.push_screen(SubjectScreen(self.rows[k]))

    def action_study(self) -> None:
        subs = list(self.rows.values())
        if not subs:
            self.notify("Nothing to study here")
            return
        items = self.wk.core.study_items(subs[:200])
        self.app.push_screen(SessionScreen("study", items))

    def action_search(self) -> None:
        box = self.query_one("#search", Input)
        box.add_class("shown")
        box.focus()

    @on(Input.Submitted, "#search")
    def _search(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            subs = self.wk.core.search_subjects(text)
            self.sub_title = f"Search “{text}” · {len(subs)} results"
            self.fill(subs)
        self.query_one("#table", DataTable).focus()

    def on_key(self, event) -> None:
        box = self.query_one("#search", Input)
        if event.key == "escape" and box.has_focus:
            box.remove_class("shown")
            self.query_one("#table", DataTable).focus()
            event.stop()

    def action_back(self) -> None:
        self.dismiss()


# --------------------------------------------------------------------------- sessions


class OneMoreScreen(ModalScreen[bool]):
    """After a popup review: keep going or close."""

    DEFAULT_CSS = """
    OneMoreScreen { align: center middle; }
    OneMoreScreen > Static { width: 56; padding: 1 2; border: thick $success; background: $surface; }
    """
    BINDINGS = [
        Binding("enter", "more", "One more", priority=True),
        Binding("space", "more", "One more", show=False),
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close", show=False),
        Binding("f2", "full", "Open full WaniKani"),
    ]

    def __init__(self, done: int, correct: int, remaining: int) -> None:
        super().__init__()
        self.done, self.correct, self.remaining = done, correct, remaining

    def compose(self) -> ComposeResult:
        t = Text()
        t.append(f"{self.done} done", style="bold")
        t.append(f" · {self.correct} correct first time\n\n")
        if self.remaining:
            t.append(f"{self.remaining} more due.  ", style="dim")
            t.append("Enter", style="bold")
            t.append(" one more   ")
        else:
            t.append("Queue empty.  ", style="dim")
        t.append("Esc", style="bold")
        t.append(" close   ")
        t.append("F2", style="bold")
        t.append(" full app")
        yield Static(t)

    def action_more(self) -> None:
        self.dismiss(True if self.remaining else False)

    def action_close(self) -> None:
        self.dismiss(False)

    def action_full(self) -> None:
        self.app.open_full_app()  # type: ignore[attr-defined]


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
    SessionScreen #answer:disabled { opacity: 1.0; }
    SessionScreen #answer.correct { background: #1f7a3c 40%; border: tall #2fbf5f; }
    SessionScreen #answer.incorrect { background: #8a1c1c 40%; border: tall #e04040; }
    SessionScreen #feedback { width: 100%; height: auto; min-height: 3; padding: 1 2; content-align: center top; }
    SessionScreen #status { dock: bottom; height: 1; padding: 0 2; background: $panel; }
    SessionScreen.compact #stage { padding: 0 1; }
    SessionScreen.compact CharDisplay { margin: 0; }
    SessionScreen.compact #prompt { height: 1; }
    SessionScreen.compact #feedback { min-height: 1; padding: 0 1; }
    """
    BINDINGS = [
        Binding(key("leave"), "leave", "Wrap up / quit"),
        Binding(key("info"), "info", "Info"),
        Binding(key("undo"), "undo", "Undo"),
        Binding(key("mark_correct"), "mark_correct", "Accept", show=False, priority=True),
        Binding(key("mark_incorrect"), "mark_incorrect", "Reject", show=False, priority=True),
        Binding(key("anki_reveal"), "anki_reveal", "Reveal", show=False, priority=True),
        Binding(key("anki_correct"), "anki_correct", "Knew it", show=False, priority=True),
        Binding(key("anki_incorrect"), "anki_incorrect", "Didn't know", show=False, priority=True),
        Binding(key("anki_toggle"), "anki_toggle", "Anki mode", show=False),
        Binding("enter", "continue", "Continue", show=False),
        Binding(key("full_app"), "full_app", "Open full WaniKani"),
        Binding(key("audio").replace("a", "ctrl+a") if key("audio") == "a" else key("audio"), "audio", "Audio", show=False),
    ]

    def __init__(self, mode: str, items: list[Item], popup: bool = False) -> None:
        super().__init__()
        self.mode = mode
        self.popup = popup
        cfg = settings()
        self.cfg = cfg
        self.queue = Queue(
            items, active_size=10 if mode == "review" else max(1, len(items)),
            back_to_back=(cfg.review_order == "back_to_back"),
        )
        self.current: tuple[Item, Part] | None = None
        self.awaiting = False
        self.anki = cfg.review_anki
        self.revealed = False
        self.popup_done = 0
        self.popup_correct = 0
        self.last_answer: tuple[Item, Part, bool] | None = None
        self.pending_submit: Item | None = None
        self.failed: list[str] = []

    @property
    def wk(self) -> "WKApp":
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="stage"):
            yield CharDisplay(None, fetch=self.wk.core.fetch_bytes, rows=self.wk.image_rows(), id="char")
            yield Static("", id="prompt")
            yield Input(placeholder="Your response", id="answer")
            yield Static("", id="feedback")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = {"review": "Reviews", "lesson": "Lesson quiz", "study": "Self-study"}[self.mode]
        if self.mode == "study":
            self.sub_title = "practice only · nothing is sent to WaniKani"
        self.wk.core.begin_session(self.mode)
        self.apply_compact()
        self.next_prompt()

    def on_resize(self, _event) -> None:
        self.apply_compact()

    def apply_compact(self) -> None:
        cfg = self.cfg
        height = self.size.height or self.app.size.height
        compact = cfg.ui_compact == "true" or (cfg.ui_compact == "auto" and height and height < 28)
        self.set_class(compact, "compact")
        self.query_one("#char", CharDisplay).set_rows(min(4, self.wk.image_rows()) if compact else self.wk.image_rows())

    # -- flow --------------------------------------------------------------

    def next_prompt(self) -> None:
        nxt = self.queue.next()
        if nxt is None:
            self.finish()  # flushes synchronously: the screen is about to close
            return
        self.flush_submit()
        self.current = nxt
        item, part = nxt
        s = item.subject
        self.awaiting = False
        self.last_answer = None
        self.query_one("#char", CharDisplay).show(s)
        prompt = self.query_one("#prompt", Static)
        prompt.remove_class("meaning", "reading")
        prompt.add_class(part.value)
        prompt.update(Text(f"{s.label}  {part.value.title()}", style="bold"))
        box = self.query_one("#answer", Input)
        box.remove_class("correct", "incorrect")
        box.value = ""
        self.revealed = False
        if self.anki:
            box.disabled = True
            box.placeholder = f"Anki mode · {key('anki_reveal')} to reveal"
            self.query_one("#feedback", Static).update(Text(f"Think of the answer, then press {key('anki_reveal')}", style="dim"))
        else:
            box.disabled = False
            box.placeholder = "Your response" if part is Part.MEANING else "答え"
            box.focus()
            self.query_one("#feedback", Static).update("")
        self.update_status()

    def load_more(self) -> None:
        """Popup: pull the next best item into a fresh queue and keep the session going."""
        items = self.wk.core.pick_popup_reviews(max(1, self.cfg.daemon_popup_items))
        if not items:
            self.wk.core.end_session()
            self.dismiss(self.queue.finished)
            return
        self.queue = Queue(items, active_size=len(items), back_to_back=(self.cfg.review_order == "back_to_back"))
        self.next_prompt()

    def flush_submit(self, blocking: bool = False) -> None:
        item = self.pending_submit
        self.pending_submit = None
        if item is None:
            return
        if blocking:  # the screen is about to close: an app exit would cancel a background worker
            self._submit_now(item)
        else:
            self.submit(item)

    def _submit_now(self, item: Item) -> None:
        core = self.wk.core
        err = core.submit_review(item) if self.mode == "review" else core.start_lesson(item)
        if err:
            self.failed.append(f"{item.subject.display_chars}: {err}")

    def update_status(self) -> None:
        q = self.queue
        done = len(q.finished)
        acc = f"{100 * q.correct_count // done}%" if done else "—"
        extra = "  · wrapping up" if q.wrapping_up else ""
        if self.popup:
            total_due = self.wk.core.due_counts()[0]
            done_all = self.popup_done + done
            more = f" · {total_due - done} more due" if total_due - done > 0 else ""
            self.query_one("#status", Static).update(
                f"Quick review · {done_all} done{more}   [F2 open full WaniKani · {key('leave')} close]"
            )
            return
        keys = f"[{key('info')} info · {key('undo')} undo · {key('leave')} {'quit' if self.popup else 'wrap up'}]"
        self.query_one("#status", Static).update(f"Remaining {q.remaining}   Done {done}/{q.total}   Accuracy {acc}{extra}   {keys}")

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
        typed = event.value
        result = check_meaning(typed, s) if part is Part.MEANING else check_reading(typed, s)
        fb = self.query_one("#feedback", Static)
        box = self.query_one("#answer", Input)
        if result.verdict is Verdict.RETRY:
            fb.update(Text(result.message, style="bold yellow"))
            return
        self._apply_verdict(item, part, result.verdict is Verdict.CORRECT, typed, result)

    def _apply_verdict(self, item: Item, part: Part, correct: bool, typed: str, result=None, override: bool = False) -> None:
        s = item.subject
        fb = self.query_one("#feedback", Static)
        box = self.query_one("#answer", Input)
        completed = self.queue.mark(item, part, correct)
        self.last_answer = (item, part, correct)
        box.remove_class("correct", "incorrect")
        box.add_class("correct" if correct else "incorrect")
        box.disabled = True  # keys now go to the screen: Enter continues, +/- override, ctrl+z undoes
        msg = Text()
        rtype = s.primary_reading_type if s.is_kanji else None
        if correct:
            msg.append("Correct", style="bold green")
            if override and not self.anki:
                msg.append("  ·  accepted by you", style="yellow")
            elif result is not None and not result.exact:
                msg.append(f"  ·  {result.message}", style="yellow")
            if part is Part.MEANING and len(s.accepted_meanings) > 1:
                msg.append("\n" + ", ".join(s.accepted_meanings[:6]), style="dim")
            elif part is Part.READING and len(s.accepted_readings) > 1:
                msg.append("\n" + ", ".join(fmt_reading(r, rtype) for r in s.accepted_readings), style="dim")
            if part is Part.READING and s.is_vocab and s.audio_urls and self.cfg.review_audio_autoplay:
                self.wk.play_audio(s)
            self._append_pitch(msg, s, part)
        else:
            msg.append("Incorrect", style="bold red")
            if override and not self.anki:
                msg.append("  ·  rejected by you", style="yellow")
            if typed.strip():
                msg.append(f"   you typed: {typed.strip()}", style="dim")
            if part is Part.MEANING:
                msg.append("\nAccepted: " + ", ".join(s.accepted_meanings[:6]), style="bold")
            else:
                want = f" ({rtype.replace('yomi', "'yomi")})" if rtype else ""
                msg.append("\nAccepted: " + ", ".join(fmt_reading(r, rtype) for r in s.accepted_readings) + want, style="bold")
            self._append_pitch(msg, s, part)
            if typed.strip() and not override:
                from .confusion import guess

                for other, why in guess(self.wk.core.db, s, part, typed):
                    msg.append("\n")
                    msg.append("Confused with ", style="dim")
                    msg.append(f" {other.display_chars} ", style=f"bold white on {other.color}")
                    msg.append(f" {other.primary_meaning}? {why}", style="dim")
            if self.cfg.review_show_mnemonic_on_miss:
                mn = s.meaning_mnemonic if part is Part.MEANING else s.reading_mnemonic
                if mn:
                    body = mnemonic_text(mn)
                    if len(body) > 420:
                        body.truncate(420, overflow="ellipsis")
                    msg.append("\n\n")
                    msg.append_text(body)
        if completed:
            if self.mode == "review":
                new_stage = next_srs_stage(item.assignment.srs_stage, item.incorrect)
                msg.append("\n")
                msg.append(f" {SRS_NAMES[new_stage]} ", style=f"bold white on {srs_color(new_stage)}")
            if self.mode == "study":
                self.wk.core.record_study(item)
            else:
                self.pending_submit = item  # sent when you continue, so undo stays possible until then
        else:
            self.pending_submit = None
        msg.append(f"\n\nEnter to continue · {key('info')} details · {key('undo')} undo · {key('mark_correct')} accept / {key('mark_incorrect')} reject", style="dim")
        fb.update(msg)
        self.awaiting = True
        self.last_typed = typed
        self.update_status()
        if correct and self.cfg.review_lightning and not override:
            self.set_timer(0.5, self._lightning_advance)

    def _append_pitch(self, msg: Text, s: Subject, part: Part) -> None:
        if part is not Part.READING or not s.is_vocab or not self.cfg.ui_pitch_accent:
            return
        from . import pitch

        if not pitch.is_cached():
            return
        pt = pitch.describe(s.characters or "", s.primary_readings[0] if s.primary_readings else "")
        if pt:
            msg.append("\npitch: ", style="dim")
            msg.append_text(pt)

    # -- Anki mode -----------------------------------------------------------

    def action_anki_toggle(self) -> None:
        self.anki = not self.anki
        self.notify("Anki mode " + ("on: reveal, then grade yourself" if self.anki else "off"))
        if not self.awaiting:
            self.next_prompt_same()

    def next_prompt_same(self) -> None:
        """Re-show the current prompt after a mode change."""
        cur = self.current
        if cur:
            self.queue.last = cur
            item, part = cur
            self.current = None
            # rebuild the prompt widgets without advancing the queue
            self.awaiting = False
            nxt = (item, part)
            self.current = nxt
            box = self.query_one("#answer", Input)
            box.value = ""
            self.revealed = False
            if self.anki:
                box.disabled = True
                box.placeholder = f"Anki mode · {key('anki_reveal')} to reveal"
                self.query_one("#feedback", Static).update(Text(f"Think of the answer, then press {key('anki_reveal')}", style="dim"))
            else:
                box.disabled = False
                box.placeholder = "Your response" if part is Part.MEANING else "答え"
                box.focus()
                self.query_one("#feedback", Static).update("")

    def action_anki_reveal(self) -> None:
        if not self.anki or self.awaiting or not self.current or self.revealed:
            return
        item, part = self.current
        s = item.subject
        self.revealed = True
        msg = Text()
        if part is Part.MEANING:
            msg.append(", ".join(s.accepted_meanings[:6]), style="bold")
        else:
            rtype = s.primary_reading_type if s.is_kanji else None
            msg.append(", ".join(fmt_reading(r, rtype) for r in s.accepted_readings), style="bold")
            if rtype:
                msg.append(f"  ({rtype.replace('yomi', "'yomi")})", style="dim")
            self._append_pitch(msg, s, part)
            if s.is_vocab and s.audio_urls and self.cfg.review_audio_autoplay:
                self.wk.play_audio(s)
        msg.append(f"\n\n{key('anki_correct')} knew it   {key('anki_incorrect')} didn't know", style="dim")
        self.query_one("#feedback", Static).update(msg)
        self.query_one("#answer", Input).value = "(revealed)"

    def action_anki_correct(self) -> None:
        if self.anki and self.revealed and not self.awaiting and self.current:
            item, part = self.current
            self._apply_verdict(item, part, True, "", override=True)

    def action_anki_incorrect(self) -> None:
        if self.anki and self.revealed and not self.awaiting and self.current:
            item, part = self.current
            self._apply_verdict(item, part, False, "", override=True)

    def action_continue(self) -> None:
        if self.awaiting:
            self.next_prompt()

    def _override(self, correct: bool) -> None:
        """Double-Check style: flip the last verdict. Reverses the mark, then re-applies it the other way."""
        if not self.awaiting or not self.last_answer:
            return
        item, part, was_correct = self.last_answer
        if was_correct == correct:
            self.notify("Already marked that way")
            return
        self.queue.unmark(item, part, was_correct)
        self.pending_submit = None
        self._apply_verdict(item, part, correct, getattr(self, "last_typed", ""), override=True)

    def action_mark_correct(self) -> None:
        self._override(True)

    def action_mark_incorrect(self) -> None:
        self._override(False)

    def _lightning_advance(self) -> None:
        if self.awaiting:
            self.next_prompt()

    def action_undo(self) -> None:
        if not self.awaiting or not self.last_answer:
            self.notify("Nothing to undo")
            return
        item, part, was_correct = self.last_answer
        self.queue.unmark(item, part, was_correct)
        self.pending_submit = None
        self.last_answer = None
        self.awaiting = False
        self.current = (item, part)
        box = self.query_one("#answer", Input)
        box.remove_class("correct", "incorrect")
        box.value = ""
        self.revealed = False
        if self.anki:
            box.disabled = True
            self.query_one("#feedback", Static).update(Text(f"Undone — press {key('anki_reveal')} to reveal again", style="yellow"))
        else:
            box.disabled = False
            box.focus()
            self.query_one("#feedback", Static).update(Text("Undone — answer again", style="yellow"))
        self.update_status()

    def finish(self) -> None:
        self.flush_submit(blocking=True)
        if self.popup:
            self.popup_done += len(self.queue.finished)
            self.popup_correct += self.queue.correct_count
            remaining = len(self.wk.core.db.reviews_available())

            def decide(more: bool | None) -> None:
                if more:
                    self.load_more()
                else:
                    self.wk.core.end_session()
                    self.dismiss(self.queue.finished)

            self.app.push_screen(OneMoreScreen(self.popup_done, self.popup_correct, remaining), decide)
            return
        self.wk.core.end_session()

        def close(_: None) -> None:
            self.dismiss(self.queue.finished)

        self.app.push_screen(SummaryScreen(self.mode, self.queue.finished, self.failed), close)

    # -- API side effects --------------------------------------------------

    @work(thread=True, group="submit")
    def submit(self, item: Item) -> None:
        core = self.wk.core
        err = core.submit_review(item) if self.mode == "review" else core.start_lesson(item)
        if err:
            self.failed.append(f"{item.subject.display_chars}: {err}")
            self.app.call_from_thread(
                self.notify, f"{item.subject.display_chars}: queued for retry ({err[:60]})", severity="warning", timeout=6
            )

    # -- actions -----------------------------------------------------------

    def action_audio(self) -> None:
        if self.current and self.awaiting:
            self.wk.play_audio(self.current[0].subject)

    def action_full_app(self) -> None:
        self.flush_submit(blocking=True)
        self.wk.core.end_session()
        self.wk.open_full_app()

    def action_info(self) -> None:
        if not self.current:
            return
        if not self.awaiting and self.mode == "review":
            self.notify("Answer first, then check the details")
            return
        self.app.push_screen(SubjectScreen(self.current[0].subject))

    def action_leave(self) -> None:
        q = self.queue
        if self.mode == "study":
            self.wk.core.end_session()
            self.dismiss(q.finished)
            return
        if self.mode == "review" and not self.popup and not q.wrapping_up and q.pending:
            q.wrap_up()
            self.update_status()
            self.notify(f"Wrapping up: {q.remaining} item(s) left. Esc again to quit now.")
            return

        def confirm(ok: bool | None) -> None:
            if ok:
                self.flush_submit(blocking=True)
                self.wk.core.end_session()
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
        head.append(f"{ {'review': 'Reviews', 'lesson': 'Lessons', 'study': 'Self-study'}[self.mode] } complete: {n} item(s)", style="bold")
        if n:
            head.append(f"   {100 * good // n}% correct first time")
        if self.failed:
            head.append(f"\n{len(self.failed)} submission(s) could not be sent and are queued; they go out on the next sync.\n", style="bold yellow")
        yield Static(head, id="summary")
        yield DataTable(cursor_type="row", zebra_stripes=True)
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


class StudyPickerScreen(ModalScreen[str | None]):
    """Choose a set to drill without touching the SRS."""

    DEFAULT_CSS = """
    StudyPickerScreen { align: center middle; }
    StudyPickerScreen > OptionList { width: 60; border: thick $primary; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, sets: list[tuple[str, str, int]]) -> None:
        super().__init__()
        self.sets = sets

    def compose(self) -> ComposeResult:
        ol = OptionList(*[Option(Text.assemble((f"{label:<28}", "bold"), (f"{n} items", "dim")), id=sid, disabled=n == 0) for sid, label, n in self.sets])
        ol.border_title = "Self-study · practice only, nothing is sent to WaniKani"
        yield ol

    @on(OptionList.OptionSelected)
    def _pick(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class LessonPickerScreen(Screen[list[Item] | None]):
    """Choose which available lessons to take."""

    DEFAULT_CSS = """
    LessonPickerScreen #hint { dock: bottom; height: 1; padding: 0 2; background: $panel; }
    """
    BINDINGS = [
        Binding(key("back"), "cancel", "Cancel"),
        Binding(key("select"), "toggle", "Toggle"),
        Binding(key("select_all"), "all", "All/none"),
        Binding(key("type_filter"), "cycle_type", "Type"),
        Binding("enter", "start", "Start", priority=True),
    ]
    TYPES = [None, "radical", "kanji", "vocabulary"]

    def __init__(self, items: list[Item]) -> None:
        super().__init__()
        self.items = items
        self.selected: set[int] = set()
        self.type_idx = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(cursor_type="row", zebra_stripes=True)
        yield Static("Space select · a all/none · t type filter · Enter start selected", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Pick lessons"
        table = self.query_one(DataTable)
        table.add_columns("", "Type", "Item", "Meaning", "Level")
        self.fill()
        table.focus()

    def visible(self) -> list[Item]:
        t = self.TYPES[self.type_idx]
        return [i for i in self.items if t is None or i.subject.type == t or (t == "vocabulary" and i.subject.type == "kana_vocabulary")]

    def fill(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for it in self.visible():
            s = it.subject
            mark = Text("●", style="green") if s.id in self.selected else Text("○", style="dim")
            table.add_row(mark, type_badge(s), Text(s.display_chars, style="bold"), s.primary_meaning, str(s.level), key=str(s.id))
        self.sub_title = f"{len(self.selected)} selected of {len(self.items)} available"

    def _current_id(self) -> int | None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        k = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return int(k) if k else None

    def action_toggle(self) -> None:
        sid = self._current_id()
        if sid is None:
            return
        self.selected ^= {sid}
        table = self.query_one(DataTable)
        row = table.cursor_coordinate.row
        self.fill()
        table.move_cursor(row=min(row + 1, table.row_count - 1))

    def action_all(self) -> None:
        vis = {i.subject.id for i in self.visible()}
        self.selected = set() if vis <= self.selected else self.selected | vis
        self.fill()

    def action_cycle_type(self) -> None:
        self.type_idx = (self.type_idx + 1) % len(self.TYPES)
        self.fill()

    def action_start(self) -> None:
        chosen = [i for i in self.items if i.subject.id in self.selected]
        if not chosen:
            sid = self._current_id()
            chosen = [i for i in self.items if i.subject.id == sid]
        if chosen:
            self.dismiss(chosen)

    def action_cancel(self) -> None:
        self.dismiss(None)


class LessonScreen(Screen[None]):
    DEFAULT_CSS = """
    LessonScreen #page { height: 1fr; }
    LessonScreen #nav { dock: bottom; height: 1; padding: 0 2; background: $panel; }
    """
    BINDINGS = [
        Binding(key("next"), "next", "Next"),
        Binding(key("next_alt"), "next", "Next", show=False),
        Binding(key("prev"), "prev", "Previous"),
        Binding(key("prev_alt"), "prev", "Previous", show=False),
        Binding(key("audio"), "audio", "Audio"),
        Binding(key("strokes"), "strokes", "Strokes"),
        Binding(key("full_app"), "full_app", "Open full WaniKani"),
        Binding(key("leave"), "leave", "Quit lessons"),
    ] + ([Binding("l", "next", "Next", show=False), Binding("h", "prev", "Previous", show=False)] if _vim() else [])

    def __init__(self, items: list[Item], popup: bool = False) -> None:
        super().__init__()
        self.items = items
        self.popup = popup
        self.index = 0

    @property
    def wk(self) -> "WKApp":
        return self.app  # type: ignore[return-value]

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
        label = "New item" if self.popup else "Lesson"
        builds_on = [self.items[j].subject for j in range(index) if self.items[j].subject.id in s.component_ids]
        hint = ("   builds on " + " ".join(b.display_chars for b in builds_on)) if builds_on else ""
        self.query_one("#nav", Static).update(
            f"{label} {index + 1}/{len(self.items)}{hint}   ←/→ navigate   " + ("→ or Enter: start quiz" if last else "")
            + ("   [F2 open full WaniKani]" if self.popup else "")
        )
        if s.is_vocab and s.audio_urls and settings().lessons_audio_autoplay:
            self.wk.play_audio(s)

    def action_next(self) -> None:
        if self.index + 1 < len(self.items):
            self.show(self.index + 1)
        else:
            self.start_quiz()

    def action_prev(self) -> None:
        if self.index > 0:
            self.show(self.index - 1)

    def action_audio(self) -> None:
        self.wk.play_audio(self.items[self.index].subject)

    def action_strokes(self) -> None:
        s = self.items[self.index].subject
        if s.is_kanji and s.characters:
            self.app.push_screen(StrokeScreen(s))

    def on_key(self, event) -> None:
        if event.key == "enter" and self.index == len(self.items) - 1:
            self.start_quiz()

    def start_quiz(self) -> None:
        def close(_: object) -> None:
            self.dismiss()

        self.app.push_screen(SessionScreen("lesson", self.items, popup=self.popup), close)

    def action_full_app(self) -> None:
        self.wk.open_full_app()

    def action_leave(self) -> None:
        if self.popup:
            self.dismiss()
            return

        def maybe_close(ok: bool | None) -> None:
            if ok:
                self.dismiss()

        self.app.push_screen(ConfirmScreen("Leave lessons? Nothing has been recorded yet."), maybe_close)
