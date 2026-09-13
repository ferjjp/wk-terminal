"""Validate the real WaniKani data shapes, using the user's own cache when present (skipped otherwise)."""

import os
from pathlib import Path

import pytest

from wanikani_tui.answers import check_meaning, check_reading, Verdict
from wanikani_tui.db import Database
from wanikani_tui.models import Assignment, Subject

CACHE = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser() / "wanikani-tui" / "cache.sqlite3"


@pytest.fixture(scope="module")
def db():
    if not CACHE.exists():
        pytest.skip("no real cache synced yet")
    d = Database(CACHE)
    if d.count_subjects() < 100:
        pytest.skip("cache not populated")
    yield d
    d.close()


def test_every_subject_parses(db):
    n = 0
    for level in range(1, 61):
        for raw in db.subjects_at_level(level):
            s = Subject.from_raw(raw, db.study_material(raw["id"]))
            assert s.primary_meaning and s.accepted_meanings
            assert s.display_chars
            if s.has_reading:
                assert s.accepted_readings, s.slug
                assert check_reading(s.accepted_readings[0], s).verdict is Verdict.CORRECT
            assert check_meaning(s.primary_meaning, s).verdict is Verdict.CORRECT
            if s.is_radical and not s.characters:
                assert s.image_url and s.image_url.startswith("https://")
            n += 1
    assert n > 100


def test_assignments_and_stats(db):
    asgs = db.all_assignments()
    assert asgs
    for a in asgs[:500]:
        A = Assignment.from_raw(a)
        assert 0 <= A.srs_stage <= 9
    for sid, score in db.leeches()[:20]:
        assert db.subject(sid) is not None and score >= 1
    db.reviews_per_day()
    db.accuracy_by_type()
    db.level_progress((db.get_user() or {}).get("level", 1))


def test_smart_picker_on_real_data(db):
    from wanikani_tui.core import Core

    core = Core(api=None, db=db)  # type: ignore[arg-type]
    if not db.reviews_available():
        pytest.skip("nothing due")
    picks = core.pick_popup_reviews(3)
    assert 1 <= len(picks) <= 3
    assert all(p.subject.id != q.subject.id for p in picks for q in picks if p is not q)
