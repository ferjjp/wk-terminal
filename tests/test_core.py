import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import FakeAPI, build_db
from wanikani_tui.core import Core
from wanikani_tui.session import Part


def make():
    db = build_db(":memory:")
    api = FakeAPI()
    return Core(api, db), api, db


def test_retry_queue_roundtrip():
    core, api, db = make()
    items = core.review_items(order="oldest")
    assert len(items) == 4
    api.fail = True
    item = items[0]
    item.wrong[Part.MEANING] = 1
    err = core.submit_review(item)
    assert err and db.pending_count() == 1
    # queued item is hidden from the queue and locally advanced
    assert all(i.assignment.id != item.assignment.id for i in core.review_items())
    assert db.assignment_for(item.subject.id)["data"]["srs_stage"] == max(1, item.assignment.srs_stage - 1)
    api.fail = False
    ok, failed = core.flush_pending()
    assert (ok, failed) == (1, 0) and db.pending_count() == 0
    assert api.submitted == [(item.assignment.id, 1, 0)]


def test_lesson_start_queue():
    core, api, db = make()
    api.fail = True
    item = core.lesson_items(batch=1)[0]
    assert core.start_lesson(item)
    assert db.pending_count() == 1 and db.assignment_for(item.subject.id)["data"]["started_at"]
    api.fail = False
    assert core.flush_pending() == (1, 0)
    assert api.started == [item.assignment.id]


def test_popup_choice_and_due():
    core, api, db = make()
    mode, items = core.popup_items()
    assert mode == "review" and len(items) == 1
    r, l, nxt = core.due_counts()
    assert (r, l) == (4, 2) and nxt is not None


def test_synonyms_and_notes():
    core, api, db = make()
    s = core.subject(11)
    core.add_synonym(s, "uno")
    assert "uno" in core.subject(11).user_synonyms
    core.set_note(s, "remember this")
    assert db.study_material(11)["meaning_note"] == "remember this"
    core.remove_synonym(s, "uno")
    assert core.subject(11).user_synonyms == []


def test_sync_extras_and_stats():
    core, api, db = make()
    counts = core.sync(full=True)
    assert counts["reviews"] == 39 and counts["level_progressions"] == 1
    days = db.reviews_per_day()
    assert sum(v[0] for v in days.values()) == 39
    st = core.level_stats()
    assert st["level"] == 1 and st["days_on_level"] and st["days_on_level"] > 19
    assert db.leeches()[0][0] == 10  # 3 reading misses, no streak
    core.begin_session("review")
    core.submit_review(core.review_items()[0])
    core.end_session()
    assert db.recent_sessions()[0]["items"] == 1
