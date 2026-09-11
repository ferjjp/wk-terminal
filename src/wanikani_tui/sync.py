"""Pull WaniKani data into the local cache, incrementally when possible."""

from __future__ import annotations

from typing import Callable

from .api import WaniKani, utcnow_iso
from .db import Database

Progress = Callable[[str], None]


class SyncCancelled(Exception):
    pass


def _checked(items, cancelled: Callable[[], bool]):
    for item in items:
        if cancelled():
            raise SyncCancelled()
        yield item


def sync(
    api: WaniKani,
    db: Database,
    full: bool = False,
    progress: Progress | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, int]:
    """Sync subjects, assignments, study materials and review stats. Returns counts."""
    say = progress or (lambda _msg: None)
    stop = cancelled or (lambda: False)
    counts: dict[str, int] = {}

    say("Fetching user…")
    db.set_user(api.user())

    resources = [
        ("subjects", api.subjects, db.upsert_subjects),
        ("assignments", api.assignments, db.upsert_assignments),
        ("study_materials", api.study_materials, db.upsert_study_materials),
        ("review_statistics", api.review_statistics, db.upsert_review_statistics),
    ]
    for name, fetch, store in resources:
        key = f"synced:{name}"
        since = None if full else db.get_meta(key)
        started = utcnow_iso()
        say(f"Syncing {name}" + (f" since {since[:19]}" if since else " (full)") + "…")
        n = store(_checked(fetch(since), stop))
        db.set_meta(key, started)
        counts[name] = n
        say(f"{name}: {n} updated")
    db.set_meta("last_sync", utcnow_iso())
    return counts


def needs_full_sync(db: Database) -> bool:
    return db.count_subjects() == 0 or db.get_meta("synced:subjects") is None
