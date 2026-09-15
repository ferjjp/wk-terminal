"""Answer checking that mirrors WaniKani's rules closely enough to trust."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

import wanakana

from .models import Subject


class Verdict(Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    RETRY = "retry"  # WaniKani "shakes" the input and asks again without penalty


@dataclass
class Result:
    verdict: Verdict
    message: str = ""
    exact: bool = True  # False when accepted with a typo


_NN = re.compile(r"nn|n'")


def _pre(text: str) -> str:
    """Standard IME rule, as on WaniKani: 'nn' (or n') is always ん, so おんな is typed 'onnna' and
    'tanni' gives たんい. This port of wanakana lacks IME mode, so fold it before converting."""
    return _NN.sub("ん", text)


_TAIL = re.compile(r"[b-df-hj-np-tv-z']+$")  # an unfinished syllable: trailing consonants (incl. n, y)


def to_kana_live(text: str) -> str:
    """Convert romaji to kana as the user types. The trailing consonant run is left alone until a
    vowel completes it, so 'ny' stays 'ny' and becomes にゅ, instead of turning into ん+y."""
    if not text:
        return text
    text = _pre(text)
    m = _TAIL.search(text)
    head, tail = (text[: m.start()], m.group(0)) if m else (text, "")
    return (wanakana.to_kana(head) if head else "") + tail


def to_kana_final(text: str) -> str:
    text = _pre(text.strip())
    return wanakana.to_kana(text) if text else ""


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower().strip()
    s = re.sub(r"[^\w\s'-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def levenshtein(a: str, b: str) -> int:
    """Optimal string alignment distance: insert/delete/substitute/transpose each cost 1."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if not la:
        return lb
    if not lb:
        return la
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


def meaning_tolerance(n: int) -> int:
    if n <= 3:
        return 0
    if n <= 5:
        return 1
    if n <= 8:
        return 2
    return 3


def check_meaning(answer: str, subject: Subject) -> Result:
    raw = answer.strip()
    if not raw:
        return Result(Verdict.RETRY, "Type an answer")
    if wanakana.is_japanese(raw) or any(wanakana.is_char_japanese(c) for c in raw):
        return Result(Verdict.RETRY, "The meaning is expected in English")
    a = _normalize(raw)
    if not a:
        return Result(Verdict.RETRY, "Type an answer")
    for bad in subject.blacklisted_meanings:
        if _normalize(bad) == a:
            return Result(Verdict.INCORRECT)
    accepted = [_normalize(m) for m in subject.accepted_meanings]
    if a in accepted:
        return Result(Verdict.CORRECT)
    best = None
    for m in accepted:
        d = levenshtein(a, m)
        if d <= meaning_tolerance(len(m)) and (best is None or d < best):
            best = d
    if best is not None:
        return Result(Verdict.CORRECT, "Close enough, but check your spelling", exact=False)
    return Result(Verdict.INCORRECT)


def check_reading(answer: str, subject: Subject) -> Result:
    kana = to_kana_final(answer)
    if not kana:
        return Result(Verdict.RETRY, "Type an answer")
    if not wanakana.is_kana(kana.replace("ー", "")):
        return Result(Verdict.RETRY, "The reading is expected in kana")
    norm = wanakana.to_hiragana(kana)
    accepted = {wanakana.to_hiragana(r) for r in subject.accepted_readings}
    if norm in accepted:
        return Result(Verdict.CORRECT)
    if subject.is_kanji:
        other = {wanakana.to_hiragana(r["reading"]): r.get("type") for r in subject.readings if not r.get("accepted_answer", True)}
        if norm in other:
            want = subject.primary_reading_type or "onyomi"
            typed_type = (other[norm] or "other").replace("yomi", "'yomi")
            return Result(Verdict.RETRY, f"{kana} is the {typed_type} — WaniKani wants the {want.replace('yomi', "'yomi")} here")
    return Result(Verdict.INCORRECT)
