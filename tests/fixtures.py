"""Synthetic WaniKani data + fake API for offline testing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from wanikani_tui.db import Database

NOW = datetime.now(timezone.utc)


def ts(delta_hours: float) -> str:
    return (NOW + timedelta(hours=delta_hours)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def subj(id_, obj, level, slug, chars, meanings, readings=None, pos=1, **extra):
    d = {
        "level": level, "slug": slug, "characters": chars, "hidden_at": None, "lesson_position": pos,
        "document_url": f"https://www.wanikani.com/{obj}/{slug}", "created_at": ts(-9999),
        "meanings": [{"meaning": m, "primary": i == 0, "accepted_answer": True} for i, m in enumerate(meanings)],
        "auxiliary_meanings": [], "meaning_mnemonic": f"Mnemonic for <{obj if obj != 'kana_vocabulary' else 'vocabulary'}>{slug}</...>",
        "spaced_repetition_system_id": 1,
    }
    d["meaning_mnemonic"] = extra.pop("meaning_mnemonic", f"This is the <radical>ground</radical>. The <kanji>{slug}</kanji> is here.")
    if readings is not None:
        d["readings"] = readings
    d.update(extra)
    return {"id": id_, "object": obj, "data": d}


SUBJECTS = [
    subj(1, "radical", 1, "ground", "一", ["Ground"], amalgamation_subject_ids=[10, 11]),
    subj(2, "radical", 1, "gun", None, ["Gun"], amalgamation_subject_ids=[11],
         character_images=[{"url": "https://files.wanikani.com/fake-gun.svg", "content_type": "image/svg+xml", "metadata": {"inline_styles": True}}]),
    subj(3, "radical", 1, "drop", "丶", ["Drop"], amalgamation_subject_ids=[]),
    subj(10, "kanji", 1, "水", "水", ["Water"], pos=1,
         readings=[{"reading": "すい", "type": "onyomi", "primary": True, "accepted_answer": True},
                   {"reading": "みず", "type": "kunyomi", "primary": False, "accepted_answer": False}],
         component_subject_ids=[1, 3], amalgamation_subject_ids=[20, 21], visually_similar_subject_ids=[11],
         meaning_hint="Think of water.", reading_mnemonic="Water goes <reading>すい</reading>sh.", reading_hint="Swish."),
    subj(11, "kanji", 1, "一", "一", ["One"], pos=2,
         readings=[{"reading": "いち", "type": "onyomi", "primary": True, "accepted_answer": True},
                   {"reading": "いつ", "type": "onyomi", "primary": False, "accepted_answer": True},
                   {"reading": "ひと", "type": "kunyomi", "primary": False, "accepted_answer": False}],
         component_subject_ids=[1], amalgamation_subject_ids=[22], reading_mnemonic="One <reading>いち</reading>."),
    subj(20, "vocabulary", 1, "水", "水", ["Water"], pos=1,
         readings=[{"reading": "みず", "primary": True, "accepted_answer": True}],
         component_subject_ids=[10], parts_of_speech=["noun"],
         context_sentences=[{"ja": "水を飲みます。", "en": "I drink water."}],
         reading_mnemonic="It's the kun'yomi <reading>みず</reading>."),
    subj(21, "vocabulary", 1, "新聞", "新聞", ["Newspaper"], pos=2,
         readings=[{"reading": "しんぶん", "primary": True, "accepted_answer": True}],
         component_subject_ids=[10], parts_of_speech=["noun"], reading_mnemonic="<reading>しんぶん</reading>"),
    subj(22, "kana_vocabulary", 1, "こんにちは", "こんにちは", ["Hello", "Good Afternoon"], pos=3, parts_of_speech=["expression"]),
    subj(30, "kanji", 2, "人", "人", ["Person"], pos=1,
         readings=[{"reading": "にん", "type": "onyomi", "primary": True, "accepted_answer": True},
                   {"reading": "じん", "type": "onyomi", "primary": False, "accepted_answer": True},
                   {"reading": "ひと", "type": "kunyomi", "primary": False, "accepted_answer": False}],
         component_subject_ids=[], amalgamation_subject_ids=[]),
]


def asg(id_, sid, stype, stage, unlocked=-100, started=-90, available=-1, passed=None):
    return {"id": id_, "object": "assignment", "data": {
        "subject_id": sid, "subject_type": stype, "srs_stage": stage,
        "unlocked_at": ts(unlocked) if unlocked is not None else None,
        "started_at": ts(started) if started is not None else None,
        "passed_at": ts(passed) if passed is not None else None, "burned_at": None,
        "available_at": ts(available) if available is not None else None, "resurrected_at": None, "hidden": False,
    }}


ASSIGNMENTS = [
    asg(101, 1, "radical", 5, passed=-10),
    asg(102, 2, "radical", 2, available=-1),          # review now
    asg(103, 3, "radical", 1, available=3),           # review in 3h
    asg(110, 10, "kanji", 3, available=-2),           # review now
    asg(111, 11, "kanji", 4, available=1.5),
    asg(120, 20, "vocabulary", 1, available=-0.5),    # review now
    asg(121, 21, "vocabulary", 0, started=None, available=None),  # lesson
    asg(122, 22, "kana_vocabulary", 0, started=None, available=None),  # lesson
]

USER = {"username": "tester", "level": 1, "subscription": {"max_level_granted": 60},
        "preferences": {"lessons_batch_size": 5, "lessons_presentation_order": "ascending_level_then_subject"}}

STUDY = [{"id": 900, "object": "study_material", "data": {"subject_id": 10, "meaning_synonyms": ["h2o"]}}]
STATS = [{"id": 800, "object": "review_statistic", "data": {"subject_id": 10, "meaning_correct": 9, "meaning_incorrect": 1, "reading_correct": 7, "reading_incorrect": 3}}]

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M20 20 L80 20 L50 80 Z" fill="none" stroke="#000" stroke-width="6"/></svg>'


def build_db(path) -> Database:
    db = Database(path)
    db.upsert_subjects(SUBJECTS)
    db.upsert_assignments(ASSIGNMENTS)
    db.upsert_study_materials(STUDY)
    db.upsert_review_statistics(STATS)
    db.set_user(USER)
    db.set_meta("synced:subjects", ts(-1))
    db.set_meta("last_sync", ts(-1))
    return db


class FakeAPI:
    def __init__(self):
        self.submitted = []
        self.started = []

    def user(self):
        return USER

    def subjects(self, updated_after=None):
        return iter([])

    def assignments(self, updated_after=None):
        return iter([])

    def study_materials(self, updated_after=None):
        return iter([])

    def review_statistics(self, updated_after=None):
        return iter([])

    def reviews(self, updated_after=None):
        return iter([{"id": 5000 + i, "object": "review", "data": {"subject_id": 10, "created_at": ts(-24 * i), "starting_srs_stage": 2,
                      "ending_srs_stage": 3 if i % 3 else 1, "incorrect_meaning_answers": 0 if i % 3 else 1, "incorrect_reading_answers": 0}}
                     for i in range(1, 40)])

    def level_progressions(self, updated_after=None):
        return iter([{"id": 7001, "object": "level_progression", "data": {"level": 1, "unlocked_at": ts(-24 * 20), "started_at": ts(-24 * 20),
                      "passed_at": None, "completed_at": None, "abandoned_at": None}}])

    materials = {}

    def create_study_material(self, subject_id, synonyms=None, note=None):
        d = {"subject_id": subject_id, "meaning_synonyms": synonyms or [], "meaning_note": note}
        self.materials[subject_id] = d
        return {"id": 9000 + subject_id, "object": "study_material", "data": d}

    def update_study_material(self, material_id, synonyms=None, note=None):
        sid = material_id - 9000 if material_id >= 9000 else 10
        d = self.materials.get(sid, {"subject_id": sid, "meaning_synonyms": [], "meaning_note": None})
        if synonyms is not None:
            d["meaning_synonyms"] = synonyms
        if note is not None:
            d["meaning_note"] = note
        self.materials[sid] = d
        return {"id": material_id, "object": "study_material", "data": d}

    fail = False

    def create_review(self, assignment_id, incorrect_meaning, incorrect_reading):
        if self.fail:
            from wanikani_tui.api import ApiError
            raise ApiError("POST reviews: connection refused")
        self.submitted.append((assignment_id, incorrect_meaning, incorrect_reading))
        a = next(x for x in ASSIGNMENTS if x["id"] == assignment_id)
        new = {"id": a["id"], "object": "assignment", "data": dict(a["data"], srs_stage=a["data"]["srs_stage"] + 1, available_at=ts(8))}
        return {"id": 1, "object": "review", "data": {}, "resources_updated": {"assignment": new}}

    def start_assignment(self, assignment_id):
        if self.fail:
            from wanikani_tui.api import ApiError
            raise ApiError("PUT start: connection refused")
        self.started.append(assignment_id)
        a = next(x for x in ASSIGNMENTS if x["id"] == assignment_id)
        return {"id": a["id"], "object": "assignment", "data": dict(a["data"], started_at=ts(0), srs_stage=1, available_at=ts(4))}

    def fetch_bytes(self, url):
        return SVG

    def close(self):
        pass
