import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import FakeAPI, build_db
from wanikani_tui import pitch
from wanikani_tui.analyzer import analyze
from wanikani_tui.confusion import guess
from wanikani_tui.models import Assignment, Subject
from wanikani_tui.session import Part

ACCENTS = "新聞\tしんぶん\t0\n水\tすい\t1\n水\tみず\t0\n日本\tにっぽん\t3\n日本\tにほん\t2\n入力\tにゅうりょく\t0,1\n女子\tじょし\t1\n"


@pytest.fixture(autouse=True)
def accents_file(tmp_path, monkeypatch):
    f = tmp_path / "kanjium_accents.txt"
    f.write_text(ACCENTS, encoding="utf-8")
    monkeypatch.setattr(pitch, "path", lambda: f)
    pitch._table.cache_clear()


def test_pitch_lookup_and_render():
    assert pitch.lookup("新聞", "しんぶん") == [0]
    assert pitch.lookup("入力", "にゅうりょく") == [0, 1]
    assert pitch.lookup("龍", "りゅう") is None
    assert pitch.render("にほん", 2).plain == "にほꜜん"
    assert pitch.render("しんぶん", 0).plain == "しんぶん"
    assert pitch.pattern_name(3, 3) == "odaka 尾高"
    d = pitch.describe("日本", "にほん")
    assert "nakadaka" in d.plain and "ꜜ" in d.plain


def K(id_, ch, readings):
    return Subject(id_, "kanji", {"level": 1, "slug": ch, "characters": ch, "meanings": [{"meaning": ch, "primary": True, "accepted_answer": True}],
                                  "readings": [{"reading": r, "type": t, "primary": p, "accepted_answer": True} for r, t, p in readings]})


def V(ch, reading):
    return Subject(99, "vocabulary", {"level": 1, "slug": ch, "characters": ch, "meanings": [{"meaning": "x", "primary": True, "accepted_answer": True}],
                                      "readings": [{"reading": reading, "primary": True, "accepted_answer": True}]})


def started(*ids):
    return {i: Assignment(i, {"subject_id": i, "srs_stage": 3, "started_at": "2026-01-01T00:00:00.000000Z"}) for i in ids}


def test_analyzer_plain_and_okurigana():
    shin = K(1, "新", [("しん", "onyomi", True), ("あたら", "kunyomi", False)])
    bun = K(2, "聞", [("ぶん", "onyomi", True), ("き", "kunyomi", False)])
    segs = analyze(V("新聞", "しんぶん"), [shin, bun], started(1))
    assert [(s.text, s.reading, s.kind, s.known) for s in segs] == [("新", "しん", "onyomi", True), ("聞", "ぶん", "onyomi", False)]
    taberu = analyze(V("食べる", "たべる"), [K(3, "食", [("しょく", "onyomi", True), ("た", "kunyomi", False)])], {})
    assert [(s.text, s.kind) for s in taberu] == [("食", "kunyomi"), ("べ", "kana"), ("る", "kana")]
    assert not taberu[0].primary and "alternative" in taberu[0].label


def test_analyzer_rendaku_sokuon_exception():
    gaku = K(4, "学", [("がく", "onyomi", True)])
    kou = K(5, "校", [("こう", "onyomi", True)])
    segs = analyze(V("学校", "がっこう"), [gaku, kou], {})
    assert [(s.text, s.reading, s.kind) for s in segs] == [("学", "がっ", "sokuon"), ("校", "こう", "onyomi")]
    hito = K(6, "人", [("にん", "onyomi", True), ("じん", "onyomi", False), ("ひと", "kunyomi", False)])
    segs = analyze(V("人々", "ひとびと"), [hito], {})
    assert [(s.text, s.reading, s.kind) for s in segs] == [("人", "ひと", "kunyomi"), ("々", "びと", "rendaku")]
    dai = K(7, "大", [("だい", "onyomi", True), ("おお", "kunyomi", False)])
    segs = analyze(V("大人", "おとな"), [dai, hito], {})
    assert segs and segs[0].kind == "exception" and segs[0].text == "大人"


def test_confusion_guess():
    db = build_db(":memory:")
    water = Subject.from_raw(db.subject(10))
    out = guess(db, water, Part.MEANING, "one")
    assert out and out[0][0].id == 11 and "One" in out[0][1]
    out = guess(db, water, Part.READING, "いち")
    assert out and out[0][0].id == 11 and "looks similar" in out[0][1]
    assert guess(db, water, Part.MEANING, "zzzz") == []


def test_reading_mixup_hint():
    from wanikani_tui.analyzer import reading_mixup

    mizu_k = K(8, "水", [("すい", "onyomi", True), ("みず", "kunyomi", False)])
    v = V("水", "みず")
    segs = analyze(v, [mizu_k], {})
    assert reading_mixup("すい", v, [mizu_k], segs) == "すい is the on'yomi of 水; this word uses みず (kun'yomi)"
    assert reading_mixup("か", v, [mizu_k], segs) is None
    onna = K(9, "女", [("じょ", "onyomi", True), ("にょ", "onyomi", False), ("おんな", "kunyomi", False)])
    ko = K(10, "子", [("し", "onyomi", True), ("こ", "kunyomi", False)])
    v = V("女子", "じょし")
    segs = analyze(v, [onna, ko], {})
    hint = reading_mixup("おんなこ", v, [onna, ko], segs)
    assert hint and hint.startswith("you combined 女 おんな (kun'yomi), 子 こ (kun'yomi)")


def test_kanji_wrong_type_message():
    from wanikani_tui.answers import Verdict, check_reading

    water = K(8, "水", [("すい", "onyomi", True), ("みず", "kunyomi", False)])
    water.data["readings"][1]["accepted_answer"] = False
    r = check_reading("みず", water)
    assert r.verdict is Verdict.RETRY and "kun'yomi" in r.message and "on'yomi" in r.message
