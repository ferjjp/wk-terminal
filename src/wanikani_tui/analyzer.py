"""Vocabulary reading breakdown: which reading each kanji contributes, and whether you know it."""

from __future__ import annotations

from dataclasses import dataclass

import wanakana

from .models import Assignment, Subject

RENDAKU = {"か": "が", "き": "ぎ", "く": "ぐ", "け": "げ", "こ": "ご", "さ": "ざ", "し": "じ", "す": "ず", "せ": "ぜ", "そ": "ぞ",
           "た": "だ", "ち": "ぢ", "つ": "づ", "て": "で", "と": "ど", "は": "ば", "ひ": "び", "ふ": "ぶ", "へ": "べ", "ほ": "ぼ"}
HANDAKU = {"は": "ぱ", "ひ": "ぴ", "ふ": "ぷ", "へ": "ぺ", "ほ": "ぽ"}


@dataclass
class Segment:
    text: str                 # the characters of the word covered by this segment
    reading: str              # the kana they contribute
    kind: str                 # kana | onyomi | kunyomi | nanori | rendaku | sokuon | exception
    kanji: Subject | None = None
    known: bool = False       # you have started (learned) this kanji
    primary: bool = False     # the kanji's primary WaniKani reading

    @property
    def colour(self) -> str:
        return {"kana": "#888888", "onyomi": "#2fbf5f", "kunyomi": "#2fbf5f", "nanori": "#e0b040",
                "rendaku": "#ffa040", "sokuon": "#ffa040", "exception": "#e04040"}[self.kind]

    @property
    def label(self) -> str:
        if self.kind == "kana":
            return ""
        base = {"onyomi": "on'yomi", "kunyomi": "kun'yomi", "nanori": "nanori", "rendaku": "rendaku",
                "sokuon": "sokuon", "exception": "exceptional"}[self.kind]
        if self.kind in ("onyomi", "kunyomi") and not self.primary:
            base += " (alternative)"
        return base


def _variants(reading: str) -> list[tuple[str, str]]:
    """(kana, kind) forms a kanji reading can take inside a word."""
    out = [(reading, "base")]
    if reading and reading[0] in RENDAKU:
        out.append((RENDAKU[reading[0]] + reading[1:], "rendaku"))
    if reading and reading[0] in HANDAKU:
        out.append((HANDAKU[reading[0]] + reading[1:], "rendaku"))
    if len(reading) >= 2 and reading[-1] in "つちくき":
        out.append((reading[:-1] + "っ", "sokuon"))
        if reading[0] in RENDAKU:
            out.append((RENDAKU[reading[0]] + reading[1:-1] + "っ", "sokuon"))
    return out


def analyze(vocab: Subject, kanji: list[Subject], assignments: dict[int, Assignment]) -> list[Segment]:
    """Split the vocabulary reading over its characters. Returns [] when no clean split exists."""
    word = vocab.characters or ""
    reading = wanakana.to_hiragana(vocab.primary_readings[0]) if vocab.primary_readings else ""
    by_char = {k.characters: k for k in kanji if k.characters}
    if not word or not reading:
        return []

    def options(ch: str) -> list[tuple[str, str, str, bool]]:
        """(kana, kind, reading_type, primary) candidates for one kanji, longest first."""
        k = by_char.get(ch)
        if k is None:
            return []
        opts = []
        for r in k.readings:
            base = wanakana.to_hiragana(r["reading"])
            for kana, form in _variants(base):
                kind = r.get("type", "onyomi") if form == "base" else form
                opts.append((kana, kind, r.get("type", "onyomi"), bool(r.get("primary"))))
        opts.sort(key=lambda o: -len(o[0]))
        return opts

    def solve(i: int, j: int) -> list[Segment] | None:
        if i == len(word):
            return [] if j == len(reading) else None
        ch = word[i]
        if ch == "々" and i > 0 and word[i - 1] in by_char:  # iteration mark: reuse the previous kanji
            prev = by_char[word[i - 1]]
            for kana, kind, _rt, primary in options(word[i - 1]):
                if reading.startswith(kana, j):
                    rest = solve(i + 1, j + len(kana))
                    if rest is not None:
                        return [Segment(ch, kana, kind, kanji=prev, known=bool(assignments.get(prev.id) and assignments[prev.id].started), primary=primary)] + rest
            return None
        if ch not in by_char:  # kana / okurigana: must match literally
            h = wanakana.to_hiragana(ch)
            if reading.startswith(h, j):
                rest = solve(i + 1, j + len(h))
                if rest is not None:
                    return [Segment(ch, h, "kana")] + rest
            return None
        k = by_char[ch]
        a = assignments.get(k.id)
        known = bool(a and a.started)
        for kana, kind, _rtype, primary in options(ch):
            if reading.startswith(kana, j):
                rest = solve(i + 1, j + len(kana))
                if rest is not None:
                    return [Segment(ch, kana, kind, kanji=k, known=known, primary=primary)] + rest
        # exceptional reading: consume up to the next literal kana that appears later in the word
        nxt = i + 1
        while nxt < len(word) and word[nxt] in by_char:
            nxt += 1
        if nxt < len(word):
            h = wanakana.to_hiragana(word[nxt])
            cut = reading.find(h, j + 1)
            if cut != -1:
                rest = solve(nxt, cut)
                if rest is not None:
                    return [Segment(word[i:nxt], reading[j:cut], "exception", kanji=k, known=known)] + rest
        elif i == len(word) - 1 or all(c in by_char for c in word[i:]):
            return [Segment(word[i:], reading[j:], "exception", kanji=k, known=known)]
        return None

    return solve(0, 0) or []
