"""The service layer shared by the TUI, the popup, `wk due` and the daemon."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from .api import ApiError, WaniKani
from .config import Settings, settings
from .db import TYPE_ORDER, Database, now_utc, parse_ts
from .models import Assignment, Subject, next_srs_stage
from .session import Item, Part
from .sync import SyncCancelled, needs_full_sync, sync


def order_by_dependency(items: list[Item]) -> list[Item]:
    """Within a lesson batch, put components before what they build: radicals before the kanji that use
    them, kanji before the vocabulary that contains them. Ties keep the original order (stable)."""
    by_id = {i.subject.id: i for i in items}
    placed: list[Item] = []
    done: set[int] = set()
    visiting: set[int] = set()

    def visit(item: Item) -> None:
        sid = item.subject.id
        if sid in done or sid in visiting:
            return
        visiting.add(sid)
        for cid in item.subject.component_ids:
            if cid in by_id:
                visit(by_id[cid])
        visiting.discard(sid)
        done.add(sid)
        placed.append(item)

    for item in items:
        visit(item)
    return placed


class Core:
    def __init__(self, api: WaniKani, db: Database, cfg: Settings | None = None) -> None:
        self.api = api
        self.db = db
        self.cfg = cfg or settings()
        self.session_id: int | None = None

    # -- data --------------------------------------------------------------------

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

    def subjects_filtered(self, flt: str) -> list[Subject]:
        return [Subject.from_raw(r, self.db.study_material(r["id"])) for r in self.db.subjects_filtered(flt)]

    def search_subjects(self, text: str) -> list[Subject]:
        return [Subject.from_raw(r) for r in self.db.search_subjects(text)]

    def assignment_for(self, subject_id: int) -> Assignment | None:
        raw = self.db.assignment_for(subject_id)
        return Assignment.from_raw(raw) if raw else None

    def user(self) -> dict[str, Any]:
        return self.db.get_user() or {}

    # -- sync ----------------------------------------------------------------------

    def needs_full_sync(self) -> bool:
        return needs_full_sync(self.db)

    def sync(self, full: bool = False, light: bool = False, progress: Callable[[str], None] | None = None,
             cancelled: Callable[[], bool] | None = None, db: Database | None = None) -> dict[str, int]:
        db = db or self.db
        flushed, failed = self.flush_pending(db)
        if progress and (flushed or failed):
            progress(f"queued submissions: {flushed} sent, {failed} still failing")
        return sync(self.api, db, full=full, light=light, progress=progress, cancelled=cancelled)

    # -- queues --------------------------------------------------------------------

    def review_items(self, limit: int | None = None, order: str | None = None) -> list[Item]:
        asgs = [Assignment.from_raw(a) for a in self.db.reviews_available()]  # oldest due first
        subs = {s.id: s for s in self.subjects(a.subject_id for a in asgs)}
        items = [Item.build(subs[a.subject_id], a) for a in asgs if a.subject_id in subs]
        order = order or self.cfg.review_order
        if order == "level":
            items.sort(key=lambda i: (i.subject.level, TYPE_ORDER.get(i.subject.type, 9)))
        elif order == "oldest":
            pass
        else:
            random.shuffle(items)
        return items[:limit] if limit else items

    def lesson_items(self, batch: int | None = None, ids: Iterable[int] | None = None) -> list[Item]:
        user = self.user()
        prefs = user.get("preferences") or {}
        batch = batch or self.cfg.lessons_batch_size or int(prefs.get("lessons_batch_size") or 5)
        order = prefs.get("lessons_presentation_order") or "ascending_level_then_subject"
        max_level = (user.get("subscription") or {}).get("max_level_granted", 60)
        asgs = [Assignment.from_raw(a) for a in self.db.lessons_available()]
        subs = {s.id: s for s in self.subjects(a.subject_id for a in asgs)}
        items = [Item.build(subs[a.subject_id], a) for a in asgs if a.subject_id in subs and subs[a.subject_id].level <= max_level]
        if ids is not None:
            wanted = set(ids)
            items = [i for i in items if i.subject.id in wanted]
        rnd = random.random
        if order == "shuffled":
            items.sort(key=lambda _i: rnd())
        elif order == "ascending_level_then_shuffled":
            items.sort(key=lambda i: (i.subject.level, rnd()))
        else:
            items.sort(key=lambda i: (i.subject.level, TYPE_ORDER.get(i.subject.type, 9), i.subject.data.get("lesson_position", 0)))
        chosen = items if ids is not None else items[:batch]
        return order_by_dependency(chosen)

    def all_lesson_items(self) -> list[Item]:
        return self.lesson_items(ids=[a["data"]["subject_id"] for a in self.db.lessons_available()])

    def popup_items(self) -> tuple[str, list[Item]]:
        """What a popup window should show: ('review', items) or ('lesson', items) or ('', [])."""
        n = max(1, self.cfg.daemon_popup_items)
        reviews = self.pick_popup_reviews(n) if self.cfg.popup_pick == "smart" else self.review_items(limit=n, order="oldest")
        lessons = self.lesson_items(batch=1)
        prefer = self.cfg.daemon_prefer
        if prefer == "lessons" and lessons:
            return "lesson", lessons
        if prefer == "mixed" and lessons and reviews and random.random() < 0.3:
            return "lesson", lessons
        if reviews:
            return "review", reviews
        if lessons:
            return "lesson", lessons
        return "", []

    def pick_popup_reviews(self, n: int = 1) -> list[Item]:
        """Choose the reviews a popup interrupts you with.

        Prefers what you are actually at risk of forgetting: leeches, low SRS stages, items overdue for
        long, poor accuracy. Skips anything answered in the last hour, and varies types so it is not
        always vocabulary. Deterministic scoring with a small random jitter to avoid the same item twice.
        """
        due = [Assignment.from_raw(a) for a in self.db.reviews_available()]
        if not due:
            return []
        seen = self.db.recently_seen(hours=self.cfg.popup_skip_recent_hours)
        candidates = [a for a in due if a.subject_id not in seen] or due
        subs = {s.id: s for s in self.subjects(a.subject_id for a in candidates)}
        stats = self.db.review_stats_map(subs)
        leech = self.db.leech_scores()
        now = now_utc()
        scored: list[tuple[float, Assignment]] = []
        for a in candidates:
            s = subs.get(a.subject_id)
            if s is None:
                continue
            score = 0.0
            score += 3.0 * min(leech.get(a.subject_id, 0.0), 3.0)            # leeches first
            score += {1: 2.5, 2: 2.0, 3: 1.5, 4: 1.0, 5: 0.6, 6: 0.4, 7: 0.2, 8: 0.1}.get(a.srs_stage, 0)
            st = stats.get(a.subject_id)
            if st:
                pct = st.get("percentage_correct", 100)
                score += (100 - pct) / 25.0                                  # 0..4 for poor accuracy
            if a.available_at:
                overdue_h = max(0.0, (now - a.available_at).total_seconds() / 3600)
                score += min(overdue_h / 24.0, 2.0)                          # up to +2 for days overdue
            score += {"radical": 0.3, "kanji": 0.6}.get(s.type, 0.0)        # kanji gate level-ups
            score += random.random() * 0.5
            scored.append((score, a))
        scored.sort(key=lambda t: -t[0])
        chosen = [a for _, a in scored[:n]]
        return [Item.build(subs[a.subject_id], a) for a in chosen]

    # -- self-study (never touches the SRS) --------------------------------------------

    def study_items(self, subjects: list[Subject]) -> list[Item]:
        asg = self.db.assignments_for(s.id for s in subjects)
        items = []
        for s in subjects:
            raw = asg.get(s.id)
            a = Assignment.from_raw(raw) if raw else Assignment(0, {"subject_id": s.id, "srs_stage": 0})
            items.append(Item.build(s, a))
        random.shuffle(items)
        return items

    def study_sets(self) -> list[tuple[str, str, int]]:
        """(id, label, count) presets for the self-study picker."""
        level = self.user().get("level", 1)
        sets = []
        lvl_kanji = self.db.subjects_at_level(level, ("kanji",))
        lvl_all = self.db.subjects_at_level(level)
        sets.append(("level_kanji", f"Level {level} kanji", len(lvl_kanji)))
        sets.append(("level_all", f"Level {level} everything", len(lvl_all)))
        sets.append(("leeches", "Leeches", len(self.db.leeches())))
        sets.append(("mistakes", "Recent mistakes (24 h)", len(self.db.recent_mistakes())))
        sets.append(("apprentice", "Apprentice items", len(self.db.subjects_filtered("apprentice", limit=100000))))
        sets.append(("due", "Due in the next 24 h", len(self.db.subjects_filtered("due", limit=100000))))
        sets.append(("random", "20 random learned items", min(20, len(self.db.all_assignments()))))
        sets.append(("burned", "20 random burned items", 20))
        return sets

    def study_set_items(self, set_id: str) -> list[Item]:
        level = self.user().get("level", 1)
        if set_id == "level_kanji":
            subs = self.subjects_at_level(level, ("kanji",))
        elif set_id == "level_all":
            subs = self.subjects_at_level(level)
        elif set_id == "leeches":
            subs = self.subjects_filtered("leech")
        elif set_id == "mistakes":
            subs = self.subjects(self.db.recent_mistakes())
        elif set_id == "apprentice":
            subs = self.subjects_filtered("apprentice")
        elif set_id == "due":
            subs = self.subjects_filtered("due")
        elif set_id == "random":
            subs = self.subjects(self.db.random_learned(20, burned=None))
        elif set_id == "burned":
            subs = self.subjects(self.db.random_learned(20, burned=True))
        else:
            subs = []
        return self.study_items(subs)

    def record_study(self, item: Item) -> None:
        if self.session_id is not None:
            self.db.record_session_item(self.session_id, item.subject.id, item.subject.type,
                                        item.wrong[Part.MEANING], item.wrong[Part.READING], None, None)

    def due_counts(self) -> tuple[int, int, datetime | None]:
        reviews = len(self.db.reviews_available())
        lessons = len(self.db.lessons_available())
        upcoming = self.db.upcoming_reviews(hours=24 * 30)
        return reviews, lessons, (upcoming[0] if upcoming else None)

    # -- submissions ---------------------------------------------------------------

    def begin_session(self, mode: str) -> None:
        self.session_id = self.db.begin_session(mode)

    def end_session(self) -> None:
        if self.session_id is not None:
            self.db.end_session(self.session_id)
            self.session_id = None

    def submit_review(self, item: Item) -> str:
        """Send a finished review. Returns '' on success or the error text (the item is queued for retry)."""
        im, ir = item.wrong[Part.MEANING], item.wrong[Part.READING]
        old = item.assignment.srs_stage
        new = next_srs_stage(old, im + ir)
        if self.session_id is not None:
            self.db.record_session_item(self.session_id, item.subject.id, item.subject.type, im, ir, old, new)
        try:
            resp = self.api.create_review(item.assignment.id, im, ir)
        except Exception as exc:  # noqa: BLE001
            self.db.enqueue("review", item.assignment.id, item.subject.id, im, ir, str(exc))
            self.db.apply_local_review(item.assignment.id, new)
            item.submitted = True
            return str(exc)
        updated = resp.get("resources_updated") or {}
        if updated.get("assignment"):
            self.db.upsert_assignment(updated["assignment"])
        if updated.get("review_statistic"):
            self.db.upsert_review_statistics([updated["review_statistic"]])
        item.submitted = True
        return ""

    def start_lesson(self, item: Item) -> str:
        if self.session_id is not None:
            self.db.record_session_item(self.session_id, item.subject.id, item.subject.type,
                                        item.wrong[Part.MEANING], item.wrong[Part.READING], 0, 1)
        try:
            resp = self.api.start_assignment(item.assignment.id)
        except Exception as exc:  # noqa: BLE001
            self.db.enqueue("start", item.assignment.id, item.subject.id, error=str(exc))
            self.db.apply_local_start(item.assignment.id)
            item.submitted = True
            return str(exc)
        if resp.get("object") == "assignment":
            self.db.upsert_assignment(resp)
        item.submitted = True
        return ""

    def flush_pending(self, db: Database | None = None) -> tuple[int, int]:
        db = db or self.db
        ok = failed = 0
        for p in db.pending():
            try:
                if p["kind"] == "review":
                    resp = self.api.create_review(p["assignment_id"], p["incorrect_meaning"], p["incorrect_reading"])
                    updated = resp.get("resources_updated") or {}
                    if updated.get("assignment"):
                        db.upsert_assignment(updated["assignment"])
                    if updated.get("review_statistic"):
                        db.upsert_review_statistics([updated["review_statistic"]])
                else:
                    resp = self.api.start_assignment(p["assignment_id"])
                    if resp.get("object") == "assignment":
                        db.upsert_assignment(resp)
                db.pending_done(p["id"])
                ok += 1
            except ApiError as exc:
                text = str(exc)
                # 422 means WaniKani rejected it for good (already reviewed, not available): drop it
                if "-> 422" in text or "-> 404" in text:
                    db.pending_done(p["id"])
                else:
                    db.pending_failed(p["id"], text)
                failed += 1
            except Exception as exc:  # noqa: BLE001
                db.pending_failed(p["id"], str(exc))
                failed += 1
        return ok, failed

    # -- study materials -----------------------------------------------------------

    def add_synonym(self, subject: Subject, synonym: str) -> None:
        row = self.db.study_material_row(subject.id)
        current = list((row or {}).get("data", {}).get("meaning_synonyms") or [])
        if synonym in current:
            return
        current.append(synonym)
        self._save_material(subject, row, synonyms=current)

    def remove_synonym(self, subject: Subject, synonym: str) -> None:
        row = self.db.study_material_row(subject.id)
        current = [s for s in (row or {}).get("data", {}).get("meaning_synonyms") or [] if s != synonym]
        self._save_material(subject, row, synonyms=current)

    def set_note(self, subject: Subject, note: str) -> None:
        row = self.db.study_material_row(subject.id)
        self._save_material(subject, row, note=note)

    def _save_material(self, subject: Subject, row: dict[str, Any] | None, synonyms=None, note=None) -> None:
        if row:
            resp = self.api.update_study_material(row["id"], synonyms=synonyms, note=note)
        else:
            resp = self.api.create_study_material(subject.id, synonyms=synonyms, note=note)
        if resp.get("object") == "study_material":
            self.db.upsert_study_materials([resp])
            subject.user_synonyms = list(resp["data"].get("meaning_synonyms") or [])

    # -- stats -----------------------------------------------------------------------

    def level_stats(self) -> dict[str, Any]:
        """Time on the current level and a projection from the median of recent levels."""
        progs = self.db.level_progressions()
        user = self.user()
        level = user.get("level", 1)
        durations = []
        current_started = None
        for p in progs:
            started, passed = parse_ts(p.get("started_at")), parse_ts(p.get("passed_at"))
            if p.get("abandoned_at"):
                continue
            if started and passed:
                durations.append((passed - started).total_seconds() / 86400)
            if p.get("level") == level and started and not passed:
                current_started = started
        recent = sorted(durations[-10:])
        median = recent[len(recent) // 2] if recent else None
        days_on_level = (now_utc() - current_started).total_seconds() / 86400 if current_started else None
        projected = None
        if median is not None and current_started is not None:
            from datetime import timedelta

            projected = current_started + timedelta(days=median)
        return {
            "level": level, "days_on_level": days_on_level, "median_days": median, "levels_done": len(durations),
            "projected": projected, "total_days": sum(durations),
        }

    # -- export -------------------------------------------------------------------

    def export_csv(self, what: str, path: str | None = None) -> str:
        import csv
        import sys

        header, rows = self.db.export_rows(what)
        if path and path != "-":
            from pathlib import Path

            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
            with open(Path(path).expanduser(), "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(header)
                w.writerows(rows)
            return f"{len(rows)} rows -> {path}"
        w = csv.writer(sys.stdout)
        w.writerow(header)
        w.writerows(rows)
        return ""
