"""Local SQLite cache of WaniKani resources."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,
    level INTEGER NOT NULL,
    slug TEXT NOT NULL,
    characters TEXT,
    hidden INTEGER NOT NULL DEFAULT 0,
    lesson_position INTEGER NOT NULL DEFAULT 0,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS subjects_level ON subjects(level, type);
CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL UNIQUE,
    subject_type TEXT NOT NULL,
    srs_stage INTEGER NOT NULL,
    unlocked_at TEXT, started_at TEXT, passed_at TEXT, burned_at TEXT, available_at TEXT,
    hidden INTEGER NOT NULL DEFAULT 0,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assignments_avail ON assignments(available_at);
CREATE TABLE IF NOT EXISTS study_materials (
    id INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL UNIQUE,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_statistics (
    id INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL UNIQUE,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pending (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                  -- review | start
    assignment_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    incorrect_meaning INTEGER NOT NULL DEFAULT 0,
    incorrect_reading INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS session_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    subject_type TEXT NOT NULL,
    incorrect_meaning INTEGER NOT NULL,
    incorrect_reading INTEGER NOT NULL,
    old_stage INTEGER, new_stage INTEGER,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_log (
    id INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL,
    subject_type TEXT,
    created_at TEXT NOT NULL,
    starting_srs_stage INTEGER, ending_srs_stage INTEGER,
    incorrect_meaning INTEGER NOT NULL DEFAULT 0, incorrect_reading INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS review_log_created ON review_log(created_at);
CREATE TABLE IF NOT EXISTS level_progressions (
    id INTEGER PRIMARY KEY,
    level INTEGER NOT NULL,
    data TEXT NOT NULL
);
"""

SRS_INTERVAL_HOURS = {1: 4, 2: 8, 3: 23, 4: 47, 5: 167, 6: 335, 7: 719, 8: 2879}

LEECH_THRESHOLD = 1.0

TYPE_ORDER = {"radical": 0, "kanji": 1, "vocabulary": 2, "kana_vocabulary": 2}


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.DatabaseError:
            pass
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # -- meta ----------------------------------------------------------------

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, value))

    def get_user(self) -> dict[str, Any] | None:
        raw = self.get_meta("user")
        return json.loads(raw) if raw else None

    def set_user(self, user: dict[str, Any]) -> None:
        self.set_meta("user", json.dumps(user))

    # -- upserts -------------------------------------------------------------

    def upsert_subjects(self, items: Iterable[dict[str, Any]]) -> int:
        n = 0
        with self.conn:
            for item in items:
                d = item["data"]
                self.conn.execute(
                    "INSERT OR REPLACE INTO subjects(id,type,level,slug,characters,hidden,lesson_position,data)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (
                        item["id"], item["object"], d["level"], d["slug"], d.get("characters"),
                        1 if d.get("hidden_at") else 0, d.get("lesson_position", 0), json.dumps(d),
                    ),
                )
                n += 1
        return n

    def upsert_assignments(self, items: Iterable[dict[str, Any]]) -> int:
        n = 0
        with self.conn:
            for item in items:
                self.upsert_assignment(item, commit=False)
                n += 1
        return n

    def upsert_assignment(self, item: dict[str, Any], commit: bool = True) -> None:
        d = item["data"]
        self.conn.execute(
            "INSERT OR REPLACE INTO assignments(id,subject_id,subject_type,srs_stage,unlocked_at,started_at,"
            "passed_at,burned_at,available_at,hidden,data) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                item["id"], d["subject_id"], d["subject_type"], d["srs_stage"], d.get("unlocked_at"),
                d.get("started_at"), d.get("passed_at"), d.get("burned_at"), d.get("available_at"),
                1 if d.get("hidden") else 0, json.dumps(d),
            ),
        )
        if commit:
            self.conn.commit()

    def upsert_study_materials(self, items: Iterable[dict[str, Any]]) -> int:
        n = 0
        with self.conn:
            for item in items:
                self.conn.execute(
                    "INSERT OR REPLACE INTO study_materials(id,subject_id,data) VALUES(?,?,?)",
                    (item["id"], item["data"]["subject_id"], json.dumps(item["data"])),
                )
                n += 1
        return n

    def upsert_review_statistics(self, items: Iterable[dict[str, Any]]) -> int:
        n = 0
        with self.conn:
            for item in items:
                self.conn.execute(
                    "INSERT OR REPLACE INTO review_statistics(id,subject_id,data) VALUES(?,?,?)",
                    (item["id"], item["data"]["subject_id"], json.dumps(item["data"])),
                )
                n += 1
        return n

    # -- queries -------------------------------------------------------------

    def count_subjects(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]

    def subject(self, subject_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT id,type,data FROM subjects WHERE id=?", (subject_id,)).fetchone()
        return self._subject_row(row) if row else None

    def subjects_by_ids(self, ids: Iterable[int]) -> list[dict[str, Any]]:
        ids = list(ids)
        if not ids:
            return []
        out: dict[int, dict[str, Any]] = {}
        for chunk_start in range(0, len(ids), 500):
            chunk = ids[chunk_start:chunk_start + 500]
            q = f"SELECT id,type,data FROM subjects WHERE id IN ({','.join('?' * len(chunk))})"
            for row in self.conn.execute(q, chunk):
                out[row["id"]] = self._subject_row(row)
        return [out[i] for i in ids if i in out]

    def subjects_at_level(self, level: int, types: Iterable[str] | None = None) -> list[dict[str, Any]]:
        q = "SELECT id,type,data FROM subjects WHERE level=? AND hidden=0"
        params: list[Any] = [level]
        if types:
            types = list(types)
            q += f" AND type IN ({','.join('?' * len(types))})"
            params += types
        rows = self.conn.execute(q + " ORDER BY lesson_position", params).fetchall()
        subs = [self._subject_row(r) for r in rows]
        subs.sort(key=lambda s: (TYPE_ORDER.get(s["object"], 9), s["data"].get("lesson_position", 0)))
        return subs

    def search_subjects(self, text: str, limit: int = 200) -> list[dict[str, Any]]:
        text = text.strip()
        if not text:
            return []
        like = f"%{text}%"
        rows = self.conn.execute(
            "SELECT id,type,data FROM subjects WHERE hidden=0 AND (characters LIKE ? OR slug LIKE ? OR data LIKE ?)"
            " ORDER BY level, lesson_position LIMIT ?",
            (like, like, f'%"meaning": "%{text}%', limit),
        ).fetchall()
        return [self._subject_row(r) for r in rows]

    @staticmethod
    def _subject_row(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "object": row["type"], "data": json.loads(row["data"])}

    def assignment_for(self, subject_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT id,data FROM assignments WHERE subject_id=?", (subject_id,)).fetchone()
        return {"id": row["id"], "data": json.loads(row["data"])} if row else None

    def assignments_for(self, subject_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
        ids = list(subject_ids)
        out: dict[int, dict[str, Any]] = {}
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            q = f"SELECT id,subject_id,data FROM assignments WHERE subject_id IN ({','.join('?' * len(chunk))})"
            for row in self.conn.execute(q, chunk):
                out[row["subject_id"]] = {"id": row["id"], "data": json.loads(row["data"])}
        return out

    def all_assignments(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT id,data FROM assignments WHERE hidden=0").fetchall()
        return [{"id": r["id"], "data": json.loads(r["data"])} for r in rows]

    def reviews_available(self, at: datetime | None = None) -> list[dict[str, Any]]:
        at = at or now_utc()
        rows = self.conn.execute(
            "SELECT id,data FROM assignments WHERE hidden=0 AND started_at IS NOT NULL AND burned_at IS NULL"
            " AND available_at IS NOT NULL AND available_at <= ?"
            " AND id NOT IN (SELECT assignment_id FROM pending) ORDER BY available_at",
            (at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),),
        ).fetchall()
        return [{"id": r["id"], "data": json.loads(r["data"])} for r in rows]

    def upcoming_reviews(self, after: datetime | None = None, hours: int = 48) -> list[datetime]:
        after = after or now_utc()
        rows = self.conn.execute(
            "SELECT available_at FROM assignments WHERE hidden=0 AND started_at IS NOT NULL AND burned_at IS NULL"
            " AND available_at > ? ORDER BY available_at",
            (after.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),),
        ).fetchall()
        out = []
        for r in rows:
            ts = parse_ts(r["available_at"])
            if ts and (ts - after).total_seconds() <= hours * 3600:
                out.append(ts)
        return out

    def upcoming_reviews_by_stage(self, after: datetime | None = None, hours: int = 24) -> list[tuple[datetime, int]]:
        after = after or now_utc()
        rows = self.conn.execute(
            "SELECT available_at, srs_stage FROM assignments WHERE hidden=0 AND started_at IS NOT NULL AND burned_at IS NULL"
            " AND available_at > ? ORDER BY available_at",
            (after.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),),
        ).fetchall()
        out = []
        for r in rows:
            ts = parse_ts(r["available_at"])
            if ts and (ts - after).total_seconds() <= hours * 3600:
                out.append((ts, r["srs_stage"]))
        return out

    def recent_mistakes(self, hours: int = 24) -> list[int]:
        """Subject ids answered wrong recently (local sessions plus the synced review log)."""
        from datetime import timedelta

        since = (now_utc() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        ids: dict[int, None] = {}
        for r in self.conn.execute(
            "SELECT subject_id FROM session_items WHERE at >= ? AND incorrect_meaning+incorrect_reading > 0 ORDER BY at DESC", (since,)
        ):
            ids.setdefault(r["subject_id"], None)
        for r in self.conn.execute(
            "SELECT subject_id FROM review_log WHERE created_at >= ? AND incorrect_meaning+incorrect_reading > 0 ORDER BY created_at DESC", (since,)
        ):
            ids.setdefault(r["subject_id"], None)
        return list(ids)

    def random_learned(self, n: int = 20, burned: bool | None = None) -> list[int]:
        where = "hidden=0 AND started_at IS NOT NULL"
        if burned is True:
            where += " AND burned_at IS NOT NULL"
        elif burned is False:
            where += " AND burned_at IS NULL"
        rows = self.conn.execute(f"SELECT subject_id FROM assignments WHERE {where} ORDER BY RANDOM() LIMIT ?", (n,)).fetchall()
        return [r["subject_id"] for r in rows]

    def lessons_available(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id,data FROM assignments WHERE hidden=0 AND unlocked_at IS NOT NULL AND started_at IS NULL"
            " AND id NOT IN (SELECT assignment_id FROM pending)"
        ).fetchall()
        return [{"id": r["id"], "data": json.loads(r["data"])} for r in rows]

    def srs_distribution(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT srs_stage, COUNT(*) AS n FROM assignments WHERE hidden=0 AND started_at IS NOT NULL GROUP BY srs_stage"
        ).fetchall()
        dist = {"apprentice": 0, "guru": 0, "master": 0, "enlightened": 0, "burned": 0}
        for r in rows:
            s = r["srs_stage"]
            if 1 <= s <= 4:
                dist["apprentice"] += r["n"]
            elif s in (5, 6):
                dist["guru"] += r["n"]
            elif s == 7:
                dist["master"] += r["n"]
            elif s == 8:
                dist["enlightened"] += r["n"]
            elif s == 9:
                dist["burned"] += r["n"]
        return dist

    def level_progress(self, level: int) -> dict[str, tuple[int, int]]:
        """Return {type: (passed, total)} for the given level."""
        out = {}
        for t in ("radical", "kanji", "vocabulary"):
            types = (t,) if t != "vocabulary" else ("vocabulary", "kana_vocabulary")
            subs = self.subjects_at_level(level, types)
            asg = self.assignments_for(s["id"] for s in subs)
            passed = sum(1 for s in subs if (asg.get(s["id"]) or {}).get("data", {}).get("passed_at"))
            out[t] = (passed, len(subs))
        return out

    def study_material(self, subject_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT data FROM study_materials WHERE subject_id=?", (subject_id,)).fetchone()
        return json.loads(row["data"]) if row else None

    def review_statistic(self, subject_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT data FROM review_statistics WHERE subject_id=?", (subject_id,)).fetchone()
        return json.loads(row["data"]) if row else None

    # -- pending submissions (retry queue) ------------------------------------

    def enqueue(self, kind: str, assignment_id: int, subject_id: int, im: int = 0, ir: int = 0, error: str = "") -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO pending(kind,assignment_id,subject_id,incorrect_meaning,incorrect_reading,created_at,attempts,last_error)"
                " VALUES(?,?,?,?,?,?,1,?)",
                (kind, assignment_id, subject_id, im, ir, now_utc().strftime("%Y-%m-%dT%H:%M:%S.%fZ"), error),
            )

    def pending(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM pending ORDER BY id").fetchall()]

    def pending_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM pending").fetchone()[0]

    def pending_done(self, pending_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM pending WHERE id=?", (pending_id,))

    def pending_failed(self, pending_id: int, error: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE pending SET attempts=attempts+1, last_error=? WHERE id=?", (error[:500], pending_id))

    def apply_local_review(self, assignment_id: int, new_stage: int) -> None:
        """Optimistic local update while a submission waits in the queue."""
        row = self.conn.execute("SELECT id,data FROM assignments WHERE id=?", (assignment_id,)).fetchone()
        if not row:
            return
        data = json.loads(row["data"])
        data["srs_stage"] = new_stage
        hours = SRS_INTERVAL_HOURS.get(new_stage)
        from datetime import timedelta

        data["available_at"] = (now_utc() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.%fZ") if hours else None
        if new_stage >= 9:
            data["burned_at"] = now_utc().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self.upsert_assignment({"id": assignment_id, "data": data})

    def apply_local_start(self, assignment_id: int) -> None:
        row = self.conn.execute("SELECT id,data FROM assignments WHERE id=?", (assignment_id,)).fetchone()
        if not row:
            return
        data = json.loads(row["data"])
        data["started_at"] = now_utc().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        data["srs_stage"] = 1
        from datetime import timedelta

        data["available_at"] = (now_utc() + timedelta(hours=SRS_INTERVAL_HOURS[1])).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self.upsert_assignment({"id": assignment_id, "data": data})

    # -- session history ------------------------------------------------------

    def begin_session(self, mode: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO sessions(mode,started_at) VALUES(?,?)", (mode, now_utc().strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
            )
            return int(cur.lastrowid)

    def end_session(self, session_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE sessions SET finished_at=? WHERE id=?", (now_utc().strftime("%Y-%m-%dT%H:%M:%S.%fZ"), session_id))

    def record_session_item(self, session_id: int, subject_id: int, subject_type: str, im: int, ir: int, old: int | None, new: int | None) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO session_items(session_id,subject_id,subject_type,incorrect_meaning,incorrect_reading,old_stage,new_stage,at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (session_id, subject_id, subject_type, im, ir, old, new, now_utc().strftime("%Y-%m-%dT%H:%M:%S.%fZ")),
            )

    def recent_sessions(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT s.id, s.mode, s.started_at, s.finished_at, COUNT(i.id) AS items,"
            " SUM(CASE WHEN i.incorrect_meaning+i.incorrect_reading=0 THEN 1 ELSE 0 END) AS correct"
            " FROM sessions s LEFT JOIN session_items i ON i.session_id=s.id GROUP BY s.id ORDER BY s.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- review log (from the API) --------------------------------------------

    def upsert_reviews(self, items: Iterable[dict[str, Any]]) -> int:
        n = 0
        with self.conn:
            for item in items:
                d = item["data"]
                self.conn.execute(
                    "INSERT OR REPLACE INTO review_log(id,subject_id,subject_type,created_at,starting_srs_stage,ending_srs_stage,"
                    "incorrect_meaning,incorrect_reading) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        item["id"], d["subject_id"], None, d["created_at"], d.get("starting_srs_stage"),
                        d.get("ending_srs_stage"), d.get("incorrect_meaning_answers", 0), d.get("incorrect_reading_answers", 0),
                    ),
                )
                n += 1
        return n

    def reviews_per_day(self, days: int = 365) -> dict[str, tuple[int, int]]:
        """{YYYY-MM-DD (local): (reviews, correct)} from the API log plus local sessions not yet in it."""
        from datetime import timedelta

        since = (now_utc() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        out: dict[str, list[int]] = {}
        for r in self.conn.execute(
            "SELECT created_at, incorrect_meaning+incorrect_reading AS wrong FROM review_log WHERE created_at >= ?", (since,)
        ):
            day = parse_ts(r["created_at"]).astimezone().strftime("%Y-%m-%d")
            cell = out.setdefault(day, [0, 0])
            cell[0] += 1
            cell[1] += 1 if r["wrong"] == 0 else 0
        last_api = self.conn.execute("SELECT MAX(created_at) FROM review_log").fetchone()[0] or ""
        for r in self.conn.execute(
            "SELECT i.at, i.incorrect_meaning+i.incorrect_reading AS wrong FROM session_items i JOIN sessions s ON s.id=i.session_id"
            " WHERE s.mode='review' AND i.at > ? AND i.at >= ?", (last_api, since)
        ):
            day = parse_ts(r["at"]).astimezone().strftime("%Y-%m-%d")
            cell = out.setdefault(day, [0, 0])
            cell[0] += 1
            cell[1] += 1 if r["wrong"] == 0 else 0
        return {k: (v[0], v[1]) for k, v in out.items()}

    def accuracy_by_type(self) -> dict[str, tuple[int, int, int, int]]:
        """{type: (meaning_correct, meaning_incorrect, reading_correct, reading_incorrect)} from review statistics."""
        out: dict[str, list[int]] = {}
        for r in self.conn.execute(
            "SELECT rs.data AS data, s.type AS stype FROM review_statistics rs LEFT JOIN subjects s ON s.id = rs.subject_id"
        ):
            d = json.loads(r["data"])
            cell = out.setdefault(d.get("subject_type") or r["stype"] or "?", [0, 0, 0, 0])
            cell[0] += d.get("meaning_correct", 0)
            cell[1] += d.get("meaning_incorrect", 0)
            cell[2] += d.get("reading_correct", 0)
            cell[3] += d.get("reading_incorrect", 0)
        return {k: tuple(v) for k, v in out.items()}  # type: ignore[return-value]

    # -- level progressions -----------------------------------------------------

    def upsert_level_progressions(self, items: Iterable[dict[str, Any]]) -> int:
        n = 0
        with self.conn:
            for item in items:
                self.conn.execute(
                    "INSERT OR REPLACE INTO level_progressions(id,level,data) VALUES(?,?,?)",
                    (item["id"], item["data"]["level"], json.dumps(item["data"])),
                )
                n += 1
        return n

    def level_progressions(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT data FROM level_progressions ORDER BY level, id").fetchall()
        return [json.loads(r["data"]) for r in rows]

    # -- leeches and filters ----------------------------------------------------

    def leeches(self) -> list[tuple[int, float]]:
        """[(subject_id, score)] for started, unburned items with a leech score >= threshold."""
        out = []
        started = {
            r["subject_id"] for r in self.conn.execute(
                "SELECT subject_id FROM assignments WHERE hidden=0 AND started_at IS NOT NULL AND burned_at IS NULL"
            )
        }
        for r in self.conn.execute("SELECT data FROM review_statistics"):
            d = json.loads(r["data"])
            if d["subject_id"] not in started:
                continue
            score = 0.0
            for part in ("meaning", "reading"):
                inc = d.get(f"{part}_incorrect", 0)
                streak = max(1, d.get(f"{part}_current_streak", 1))
                score = max(score, inc / (streak ** 1.5))
            if score >= LEECH_THRESHOLD:
                out.append((d["subject_id"], score))
        out.sort(key=lambda t: -t[1])
        return out

    def subjects_filtered(self, flt: str, limit: int = 400) -> list[dict[str, Any]]:
        """Cross-level subject lists: due (next 24h), leech, or an SRS group name."""
        from datetime import timedelta

        if flt == "leech":
            ids = [sid for sid, _ in self.leeches()][:limit]
            return self.subjects_by_ids(ids)
        if flt == "due":
            until = (now_utc() + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            rows = self.conn.execute(
                "SELECT subject_id FROM assignments WHERE hidden=0 AND started_at IS NOT NULL AND burned_at IS NULL"
                " AND available_at <= ? ORDER BY available_at LIMIT ?", (until, limit)
            ).fetchall()
            return self.subjects_by_ids([r["subject_id"] for r in rows])
        groups = {"apprentice": (1, 4), "guru": (5, 6), "master": (7, 7), "enlightened": (8, 8), "burned": (9, 9)}
        if flt in groups:
            lo, hi = groups[flt]
            rows = self.conn.execute(
                "SELECT subject_id FROM assignments WHERE hidden=0 AND started_at IS NOT NULL AND srs_stage BETWEEN ? AND ?"
                " ORDER BY available_at LIMIT ?", (lo, hi, limit)
            ).fetchall()
            return self.subjects_by_ids([r["subject_id"] for r in rows])
        return []

    def study_material_row(self, subject_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT id,data FROM study_materials WHERE subject_id=?", (subject_id,)).fetchone()
        return {"id": row["id"], "data": json.loads(row["data"])} if row else None

    # -- popup selection support ------------------------------------------------

    def recently_seen(self, hours: float = 1.0) -> set[int]:
        """Subject ids answered in a session within the last `hours`."""
        from datetime import timedelta

        since = (now_utc() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return {r["subject_id"] for r in self.conn.execute("SELECT subject_id FROM session_items WHERE at >= ?", (since,))}

    def leech_scores(self) -> dict[int, float]:
        return dict(self.leeches())

    def review_stats_map(self, subject_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
        ids = list(subject_ids)
        out: dict[int, dict[str, Any]] = {}
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            q = f"SELECT subject_id, data FROM review_statistics WHERE subject_id IN ({','.join('?' * len(chunk))})"
            for r in self.conn.execute(q, chunk):
                out[r["subject_id"]] = json.loads(r["data"])
        return out

    # -- export -------------------------------------------------------------------

    def export_rows(self, what: str) -> tuple[list[str], list[list[Any]]]:
        """Rows for CSV export: sessions | items | reviews | stats."""
        if what == "sessions":
            rows = self.recent_sessions(limit=100000)
            return (["session_id", "mode", "started_at", "finished_at", "items", "correct"],
                    [[r["id"], r["mode"], r["started_at"], r["finished_at"], r["items"], r["correct"]] for r in rows])
        if what == "items":
            cur = self.conn.execute(
                "SELECT i.session_id, s.mode, i.at, i.subject_id, i.subject_type, sub.characters, sub.slug, sub.level,"
                " i.incorrect_meaning, i.incorrect_reading, i.old_stage, i.new_stage"
                " FROM session_items i JOIN sessions s ON s.id=i.session_id LEFT JOIN subjects sub ON sub.id=i.subject_id ORDER BY i.id"
            )
            return ([d[0] for d in cur.description], [list(r) for r in cur.fetchall()])
        if what == "reviews":
            cur = self.conn.execute(
                "SELECT r.id, r.created_at, r.subject_id, sub.type, sub.characters, sub.slug, sub.level,"
                " r.starting_srs_stage, r.ending_srs_stage, r.incorrect_meaning, r.incorrect_reading"
                " FROM review_log r LEFT JOIN subjects sub ON sub.id=r.subject_id ORDER BY r.created_at"
            )
            return ([d[0] for d in cur.description], [list(r) for r in cur.fetchall()])
        if what == "stats":
            header = ["subject_id", "type", "characters", "slug", "level", "srs_stage", "meaning_correct", "meaning_incorrect",
                      "meaning_max_streak", "meaning_current_streak", "reading_correct", "reading_incorrect",
                      "reading_max_streak", "reading_current_streak", "percentage_correct", "leech_score"]
            leech = self.leech_scores()
            out = []
            for r in self.conn.execute(
                "SELECT rs.data AS data, sub.type AS t, sub.characters AS c, sub.slug AS slug, sub.level AS lvl, a.srs_stage AS stage"
                " FROM review_statistics rs LEFT JOIN subjects sub ON sub.id=rs.subject_id"
                " LEFT JOIN assignments a ON a.subject_id=rs.subject_id ORDER BY sub.level, sub.lesson_position"
            ):
                d = json.loads(r["data"])
                out.append([d["subject_id"], r["t"], r["c"], r["slug"], r["lvl"], r["stage"],
                            d.get("meaning_correct"), d.get("meaning_incorrect"), d.get("meaning_max_streak"), d.get("meaning_current_streak"),
                            d.get("reading_correct"), d.get("reading_incorrect"), d.get("reading_max_streak"), d.get("reading_current_streak"),
                            d.get("percentage_correct"), round(leech.get(d["subject_id"], 0.0), 2)])
            return header, out
        raise ValueError(what)
