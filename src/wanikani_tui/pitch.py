"""Pitch accent from the Kanjium project's accents file (CC BY-SA 4.0), fetched on first use."""

from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path
from typing import Callable

from rich.text import Text

from .config import data_dir

# Kanjium: https://github.com/mifunetoshiro/kanjium — data/source_files/raw/accents.txt, CC BY-SA 4.0
URL = "https://raw.githubusercontent.com/mifunetoshiro/kanjium/master/data/source_files/raw/accents.txt"
ATTRIBUTION = "pitch accent: Kanjium (CC BY-SA 4.0), built on EDRDG and other sources"

_lock = threading.Lock()
_SMALL = set("ゃゅょャュョぁぃぅぇぉァィゥェォゎヮ")


def path() -> Path:
    d = data_dir() / "ext"
    d.mkdir(parents=True, exist_ok=True)
    return d / "kanjium_accents.txt"


def is_cached() -> bool:
    return path().exists()


def ensure(fetch: Callable[[str], bytes] | None) -> bool:
    p = path()
    with _lock:
        if p.exists():
            return True
        if fetch is None:
            return False
        try:
            raw = fetch(URL)
            if b"\t" not in raw[:200]:
                return False
            p.write_bytes(raw)
            return True
        except Exception:  # noqa: BLE001
            return False


@lru_cache(maxsize=1)
def _table() -> dict[tuple[str, str], list[int]]:
    table: dict[tuple[str, str], list[int]] = {}
    try:
        with open(path(), encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 3:
                    continue
                word, reading, acc = parts
                nums = []
                for a in acc.split(","):
                    a = a.strip().split("(")[0]  # entries like "1(2)" carry a secondary form
                    if a.isdigit():
                        nums.append(int(a))
                if nums:
                    table[(word, reading)] = nums
    except OSError:
        pass
    return table


def lookup(word: str, reading: str, fetch: Callable[[str], bytes] | None = None) -> list[int] | None:
    """Accent positions (mora index of the downstep; 0 = heiban) for a word+reading, or None."""
    if not ensure(fetch):
        return None
    t = _table()
    hit = t.get((word, reading))
    if hit is None and word != reading:
        hit = t.get((reading, reading))
    return hit


def morae(reading: str) -> list[str]:
    out: list[str] = []
    for ch in reading:
        if ch in _SMALL and out:
            out[-1] += ch
        else:
            out.append(ch)
    return out


def pattern_name(accent: int, n_morae: int) -> str:
    if accent == 0:
        return "heiban 平板"
    if accent == 1:
        return "atamadaka 頭高"
    if accent >= n_morae:
        return "odaka 尾高"
    return "nakadaka 中高"


def render(reading: str, accent: int, high_style: str = "bold underline", low_style: str = "dim") -> Text:
    """The reading with high morae underlined and a ꜜ after the downstep: the usual textbook shape."""
    ms = morae(reading)
    t = Text()
    for i, m in enumerate(ms, start=1):
        if accent == 0:
            high = i >= 2
        elif accent == 1:
            high = i == 1
        else:
            high = 2 <= i <= accent
        t.append(m, style=high_style if high else low_style)
        if accent and i == accent:
            t.append("ꜜ", style="bold red")
    return t


def describe(word: str, reading: str, fetch: Callable[[str], bytes] | None = None) -> Text | None:
    accents = lookup(word, reading, fetch)
    if not accents:
        return None
    t = Text()
    n = len(morae(reading))
    for k, a in enumerate(accents):
        if k:
            t.append("  or  ", style="dim")
        t.append_text(render(reading, a))
        t.append(f" [{a}] {pattern_name(a, n)}", style="dim")
    return t
