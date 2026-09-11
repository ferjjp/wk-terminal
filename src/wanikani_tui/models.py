"""Convenience wrappers over raw API dicts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .db import parse_ts

TYPE_LABEL = {"radical": "Radical", "kanji": "Kanji", "vocabulary": "Vocabulary", "kana_vocabulary": "Vocabulary"}
TYPE_COLOR = {"radical": "#00aaff", "kanji": "#ff00aa", "vocabulary": "#aa00ff", "kana_vocabulary": "#aa00ff"}

SRS_NAMES = {
    0: "Locked", 1: "Apprentice I", 2: "Apprentice II", 3: "Apprentice III", 4: "Apprentice IV",
    5: "Guru I", 6: "Guru II", 7: "Master", 8: "Enlightened", 9: "Burned",
}
SRS_COLOR_WK = {
    "apprentice": "#dd0093", "guru": "#882d9e", "master": "#294ddb", "enlightened": "#0093dd", "burned": "#434343",
}
# Okabe-Ito palette, distinguishable under the common colour-vision deficiencies
SRS_COLOR_CB = {
    "apprentice": "#e69f00", "guru": "#56b4e9", "master": "#009e73", "enlightened": "#0072b2", "burned": "#7f7f7f",
}


def _palette() -> dict[str, str]:
    try:
        from .config import settings

        return SRS_COLOR_CB if settings().ui_colorblind else SRS_COLOR_WK
    except Exception:  # noqa: BLE001
        return SRS_COLOR_WK


class _Palette(dict):
    def __getitem__(self, key: str) -> str:  # type: ignore[override]
        return _palette()[key]

    def items(self):  # type: ignore[override]
        return _palette().items()


SRS_COLOR: dict[str, str] = _Palette()


def srs_group(stage: int) -> str:
    if stage <= 0:
        return "locked"
    if stage <= 4:
        return "apprentice"
    if stage <= 6:
        return "guru"
    if stage == 7:
        return "master"
    if stage == 8:
        return "enlightened"
    return "burned"


def srs_color(stage: int) -> str:
    return _palette().get(srs_group(stage), "#777777")


@dataclass
class Subject:
    id: int
    type: str
    data: dict[str, Any]
    user_synonyms: list[str] = field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: dict[str, Any], study_material: dict[str, Any] | None = None) -> "Subject":
        syn = list((study_material or {}).get("meaning_synonyms") or [])
        s = cls(id=raw["id"], type=raw["object"], data=raw["data"], user_synonyms=syn)
        s.user_note = (study_material or {}).get("meaning_note") or None
        return s

    # -- basics ---------------------------------------------------------------
    @property
    def level(self) -> int:
        return self.data["level"]

    @property
    def slug(self) -> str:
        return self.data["slug"]

    @property
    def characters(self) -> str | None:
        return self.data.get("characters")

    @property
    def display_chars(self) -> str:
        return self.characters or self.primary_meaning

    @property
    def label(self) -> str:
        return TYPE_LABEL[self.type]

    @property
    def color(self) -> str:
        return TYPE_COLOR[self.type]

    @property
    def document_url(self) -> str:
        return self.data.get("document_url", "")

    @property
    def is_radical(self) -> bool:
        return self.type == "radical"

    @property
    def is_kanji(self) -> bool:
        return self.type == "kanji"

    @property
    def is_vocab(self) -> bool:
        return self.type in ("vocabulary", "kana_vocabulary")

    @property
    def has_reading(self) -> bool:
        return self.type in ("kanji", "vocabulary")

    # -- meanings -------------------------------------------------------------
    @property
    def meanings(self) -> list[dict[str, Any]]:
        return self.data.get("meanings", [])

    @property
    def primary_meaning(self) -> str:
        for m in self.meanings:
            if m.get("primary"):
                return m["meaning"]
        return self.meanings[0]["meaning"] if self.meanings else self.slug

    @property
    def alternative_meanings(self) -> list[str]:
        return [m["meaning"] for m in self.meanings if not m.get("primary")]

    @property
    def accepted_meanings(self) -> list[str]:
        out = [m["meaning"] for m in self.meanings if m.get("accepted_answer", True)]
        out += [a["meaning"] for a in self.data.get("auxiliary_meanings", []) if a.get("type") == "whitelist"]
        out += self.user_synonyms
        return out

    @property
    def blacklisted_meanings(self) -> list[str]:
        return [a["meaning"] for a in self.data.get("auxiliary_meanings", []) if a.get("type") == "blacklist"]

    @property
    def meaning_mnemonic(self) -> str:
        return self.data.get("meaning_mnemonic", "")

    @property
    def meaning_hint(self) -> str:
        return self.data.get("meaning_hint") or ""

    # -- readings -------------------------------------------------------------
    @property
    def readings(self) -> list[dict[str, Any]]:
        return self.data.get("readings", [])

    @property
    def primary_readings(self) -> list[str]:
        return [r["reading"] for r in self.readings if r.get("primary")]

    @property
    def accepted_readings(self) -> list[str]:
        return [r["reading"] for r in self.readings if r.get("accepted_answer", True)]

    @property
    def primary_reading_type(self) -> str | None:
        for r in self.readings:
            if r.get("primary"):
                return r.get("type")
        return None

    def readings_of_type(self, kind: str) -> list[str]:
        return [r["reading"] for r in self.readings if r.get("type") == kind]

    @property
    def reading_mnemonic(self) -> str:
        return self.data.get("reading_mnemonic") or ""

    @property
    def reading_hint(self) -> str:
        return self.data.get("reading_hint") or ""

    # -- relations ------------------------------------------------------------
    @property
    def component_ids(self) -> list[int]:
        return self.data.get("component_subject_ids", [])

    @property
    def amalgamation_ids(self) -> list[int]:
        return self.data.get("amalgamation_subject_ids", [])

    @property
    def similar_ids(self) -> list[int]:
        return self.data.get("visually_similar_subject_ids", [])

    @property
    def parts_of_speech(self) -> list[str]:
        return self.data.get("parts_of_speech", [])

    @property
    def context_sentences(self) -> list[dict[str, str]]:
        return self.data.get("context_sentences", [])

    @property
    def image_url(self) -> str | None:
        images = self.data.get("character_images") or []
        preferred = [i for i in images if i.get("content_type") == "image/svg+xml" and i.get("metadata", {}).get("inline_styles")]
        svgs = preferred or [i for i in images if i.get("content_type") == "image/svg+xml"]
        return svgs[0]["url"] if svgs else None

    @property
    def audio_urls(self) -> list[dict[str, Any]]:
        return self.data.get("pronunciation_audios", [])

    user_note: str | None = None


@dataclass
class Assignment:
    id: int
    data: dict[str, Any]

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "Assignment":
        return cls(id=raw["id"], data=raw["data"])

    @property
    def subject_id(self) -> int:
        return self.data["subject_id"]

    @property
    def srs_stage(self) -> int:
        return self.data.get("srs_stage", 0)

    @property
    def available_at(self) -> datetime | None:
        return parse_ts(self.data.get("available_at"))

    @property
    def started(self) -> bool:
        return bool(self.data.get("started_at"))

    @property
    def unlocked(self) -> bool:
        return bool(self.data.get("unlocked_at"))


def next_srs_stage(stage: int, incorrect: int) -> int:
    """WaniKani's SRS transition: +1 when correct, else a penalty scaled by stage."""
    if incorrect <= 0:
        return min(stage + 1, 9)
    penalty = 2 if stage >= 5 else 1
    steps = (incorrect + 1) // 2  # ceil(incorrect / 2)
    return max(1, stage - steps * penalty)
