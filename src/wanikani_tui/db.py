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
"""

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
            " AND available_at IS NOT NULL AND available_at <= ? ORDER BY available_at",
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

    def lessons_available(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id,data FROM assignments WHERE hidden=0 AND unlocked_at IS NOT NULL AND started_at IS NULL"
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
