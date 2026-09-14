"""Community datasets fetched on demand: Keisei (phonetic-semantic composition) and Niai (visually
similar kanji), both from https://github.com/mwil/wanikani-userscripts (GPL-3.0). Downloaded to the
local cache on first use, never bundled."""

from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from .config import data_dir

# pinned to the commit the userscripts themselves load from, so the schema cannot drift under us
_COMMIT = "8ee517737d604f1df0ff103a33b69f1f07218815"
_BASE = f"https://raw.githubusercontent.com/mwil/wanikani-userscripts/{_COMMIT}/"
FILES = {
    "keisei_kanji": "wanikani-phonetic-compounds/db/kanji_esc.json",
    "keisei_phonetic": "wanikani-phonetic-compounds/db/phonetic_esc.json",
    "niai_noto": "wanikani-similar-kanji/db/wk_niai_noto_esc.json",
    "niai_keisei": "wanikani-similar-kanji/db/from_keisei_esc.json",
    "niai_manual": "wanikani-similar-kanji/db/manual_esc.json",
}
ATTRIBUTION = "data: Keisei/Niai by mwil (GPL-3.0), similarity from L. Yencken's thesis (CC BY 3.0)"

KTYPE_LABEL = {
    "hieroglyph": "pictograph (象形)",
    "indicative": "indicative (指事)",
    "comp_indicative": "compound of meanings (会意)",
    "comp_phonetic": "phonetic-semantic compound (形声)",
    "derivative": "derivative (転注)",
    "rebus": "phonetic loan (仮借)",
    "kokuji": "made in Japan (国字)",
    "shinjitai": "simplified form (新字体)",
    "unknown": "unknown origin",
    "unprocessed": "not yet classified",
}

_lock = threading.Lock()


def ext_dir() -> Path:
    d = data_dir() / "ext"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_cached(name: str) -> bool:
    return (ext_dir() / f"{name}.json").exists()


def all_cached(names: tuple[str, ...]) -> bool:
    return all(is_cached(n) for n in names)


def load(name: str, fetch: Callable[[str], bytes] | None) -> dict[str, Any] | None:
    """Return the dataset, downloading it if needed. None when unavailable and no fetcher/offline."""
    path = ext_dir() / f"{name}.json"
    with _lock:
        if not path.exists():
            if fetch is None:
                return None
            try:
                raw = fetch(_BASE + FILES[name])
                json.loads(raw)  # validate before caching
                path.write_bytes(raw)
            except Exception:  # noqa: BLE001 - offline or upstream gone: stay silent, retry next time
                return None
        return _read(str(path))


@lru_cache(maxsize=8)
def _read(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- keisei


def _strip_dakuten(s: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def keisei_quality(kanji_readings: list[str], mark_readings: list[str]) -> str:
    """天 all readings match the mark, 上 most, 中 some, 下 none (dakuten differences count as a match)."""
    if not kanji_readings or not mark_readings:
        return "下"
    marks = {_strip_dakuten(r) for r in mark_readings}
    hits = sum(1 for r in kanji_readings if _strip_dakuten(r) in marks)
    if hits == len(kanji_readings):
        return "天"
    if hits * 2 >= len(kanji_readings):
        return "上"
    if hits:
        return "中"
    return "下"


def keisei_info(kanji: str, fetch: Callable[[str], bytes] | None) -> dict[str, Any] | None:
    """Composition info for one kanji, or None when the datasets are unavailable / kanji unknown."""
    kdb = load("keisei_kanji", fetch)
    pdb = load("keisei_phonetic", fetch)
    if kdb is None or pdb is None:
        return None
    out: dict[str, Any] = {"kanji": kanji}
    entry = kdb.get(kanji)
    if entry:
        out["type"] = entry.get("type", "unknown")
        out["type_label"] = KTYPE_LABEL.get(entry.get("type", "unknown"), entry.get("type"))
        out["readings"] = entry.get("readings", [])
        out["comment"] = entry.get("comment", "")
        if entry.get("type") == "comp_phonetic" and entry.get("phonetic"):
            mark = entry["phonetic"]
            pm = pdb.get(mark, {})
            out["semantic"] = entry.get("semantic")
            out["phonetic"] = mark
            out["mark_readings"] = pm.get("readings", [])
            out["mark_wk_radical"] = pm.get("wk-radical")
            out["compounds"] = [c for c in pm.get("compounds", []) if c != kanji]
            out["non_compounds"] = pm.get("non_compounds", [])
            out["quality"] = keisei_quality(out["readings"], out["mark_readings"])
    if kanji in pdb:  # the kanji itself serves as a phonetic mark for others
        pm = pdb[kanji]
        out["as_mark"] = {
            "readings": pm.get("readings", []),
            "compounds": pm.get("compounds", []),
            "non_compounds": pm.get("non_compounds", []),
        }
    return out if len(out) > 1 else None


# --------------------------------------------------------------------------- niai

NIAI_SOURCES = (("niai_manual", 0.9), ("niai_keisei", 0.65), ("niai_noto", 0.1))
NIAI_MIN_SCORE = 0.3


def niai_similar(kanji: str, fetch: Callable[[str], bytes] | None) -> list[tuple[str, float]] | None:
    """[(kanji, score)] merged the way the Niai script does it (max score per candidate, cutoff 0.3)."""
    scores: dict[str, float] = {}
    got_any = False
    for name, base in NIAI_SOURCES:
        db = load(name, fetch)
        if db is None:
            continue
        got_any = True
        for cand in db.get(kanji, []) or []:
            if isinstance(cand, dict):
                ch, sc = cand.get("kan"), float(cand.get("score", 0.0)) + base
            else:
                ch, sc = cand, base
            if not ch or ch == kanji:
                continue
            scores[ch] = max(scores.get(ch, 0.0), sc)
    if not got_any:
        return None
    return sorted(((k, v) for k, v in scores.items() if v >= NIAI_MIN_SCORE), key=lambda t: -t[1])
