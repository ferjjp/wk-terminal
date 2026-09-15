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


def test_dependency_order():
    from wanikani_tui.core import order_by_dependency

    core, api, db = make()
    # vocabulary 水(20) uses kanji 水(10) which uses radicals 1 and 3; feed them reversed
    items = [core.subject(i) for i in (20, 10, 3, 1, 22)]
    from wanikani_tui.models import Assignment
    from wanikani_tui.session import Item
    fake = [Item.build(s, Assignment(0, {"subject_id": s.id, "srs_stage": 0})) for s in items]
    ordered = [i.subject.id for i in order_by_dependency(fake)]
    assert ordered.index(1) < ordered.index(10) < ordered.index(20)
    assert ordered.index(3) < ordered.index(10)
    assert len(ordered) == 5 and 22 in ordered


def test_smart_popup_prefers_weak_items_and_skips_recent():
    core, api, db = make()
    # subject 10 has 3 reading misses and a leech score; it should win over the others
    picked = core.pick_popup_reviews(1)
    assert picked[0].subject.id == 10
    # after answering it in a session, it is skipped
    core.begin_session("review")
    db.record_session_item(core.session_id, 10, "kanji", 0, 0, 3, 4)
    picked = core.pick_popup_reviews(1)
    assert picked[0].subject.id != 10
    # when everything was seen recently, still returns something
    for sid in (1, 2, 20):
        db.record_session_item(core.session_id, sid, "x", 0, 0, 1, 2)
    assert core.pick_popup_reviews(1)


def test_export(tmp_path):
    core, api, db = make()
    core.sync(full=True)
    core.begin_session("review")
    core.submit_review(core.review_items()[0])
    core.end_session()
    for what in ("sessions", "items", "reviews", "stats"):
        out = tmp_path / f"{what}.csv"
        msg = core.export_csv(what, str(out))
        assert out.exists() and "rows" in msg, msg
        lines = out.read_text().splitlines()
        assert len(lines) >= 2, what


def test_popup_rotation_avoids_recent_nominations():
    core, api, db = make()
    first = core.pick_popup_reviews(1)[0].subject.id
    second = core.pick_popup_reviews(1, avoid=[first])[0].subject.id
    assert second != first
    # avoiding everything still returns something
    ids = [a["data"]["subject_id"] for a in db.reviews_available()]
    assert core.pick_popup_reviews(1, avoid=ids)


def test_database_is_safe_across_threads():
    import threading

    core, api, db = make()
    errors: list[BaseException] = []

    def hammer(n: int) -> None:
        try:
            for _ in range(n):
                for raw in db.search_subjects("水", limit=5):
                    assert raw["data"]["level"] >= 1
                db.subjects_at_level(1)
                db.leeches()
                db.reviews_available()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(150,)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[:1]
