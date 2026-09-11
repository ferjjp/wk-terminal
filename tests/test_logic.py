from wanikani_tui.answers import Verdict, check_meaning, check_reading, to_kana_final, to_kana_live
from wanikani_tui.models import Subject, next_srs_stage
from wanikani_tui.session import Item, Part, Queue
from wanikani_tui.models import Assignment
from fixtures import SUBJECTS, ASSIGNMENTS, STUDY


def S(id_):
    raw = next(s for s in SUBJECTS if s["id"] == id_)
    sm = next((m["data"] for m in STUDY if m["data"]["subject_id"] == id_), None)
    return Subject.from_raw(raw, sm)


def test_meaning():
    water = S(10)
    assert check_meaning("water", water).verdict is Verdict.CORRECT
    assert check_meaning("Watre", water).verdict is Verdict.CORRECT   # 1 typo on 5 letters
    assert check_meaning("h2o", water).verdict is Verdict.CORRECT     # user synonym
    assert check_meaning("fire", water).verdict is Verdict.INCORRECT
    assert check_meaning("みず", water).verdict is Verdict.RETRY
    assert check_meaning("one", S(11)).verdict is Verdict.CORRECT
    assert check_meaning("on", S(11)).verdict is Verdict.INCORRECT    # no tolerance on 3 letters
    assert check_meaning("good afternoon", S(22)).verdict is Verdict.CORRECT


def test_reading():
    water = S(10)
    assert check_reading("sui", water).verdict is Verdict.CORRECT
    assert check_reading("みず", water).verdict is Verdict.RETRY       # right reading, wrong type
    assert check_reading("ka", water).verdict is Verdict.INCORRECT
    assert check_reading("water", water).verdict is Verdict.RETRY     # not kana
    assert check_reading("shinbun", S(21)).verdict is Verdict.CORRECT
    assert check_reading("shinnbunn", S(21)).verdict is Verdict.CORRECT
    assert check_reading("jin", S(30)).verdict is Verdict.CORRECT


def test_kana():
    assert to_kana_live("shin") == "しn"
    assert to_kana_final("shin") == "しん"
    assert to_kana_final("konnnichiha") == "こんにちは"
    assert to_kana_live("") == ""


def test_srs():
    assert next_srs_stage(3, 0) == 4
    assert next_srs_stage(3, 1) == 2
    assert next_srs_stage(3, 3) == 1
    assert next_srs_stage(6, 1) == 4
    assert next_srs_stage(6, 3) == 2
    assert next_srs_stage(9, 0) == 9


def test_queue():
    items = [Item.build(S(10), Assignment.from_raw(ASSIGNMENTS[3])), Item.build(S(1), Assignment.from_raw(ASSIGNMENTS[0]))]
    q = Queue(items, seed=1)
    assert q.total == 2
    seen = 0
    while (nxt := q.next()) is not None:
        item, part = nxt
        q.mark(item, part, True)
        seen += 1
    assert seen == 3  # kanji needs 2 parts, radical 1
    assert q.remaining == 0 and q.correct_count == 2
