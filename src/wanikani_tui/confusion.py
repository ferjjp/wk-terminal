"""When an answer is wrong, guess which other item it belonged to."""

from __future__ import annotations

import json

import wanakana

from .answers import _normalize, levenshtein, meaning_tolerance
from .db import Database
from .models import Subject
from .session import Part


def guess(db: Database, subject: Subject, part: Part, typed: str, limit: int = 3) -> list[tuple[Subject, str]]:
    typed = typed.strip()
    if not typed:
        return []
    out: list[tuple[Subject, str]] = []
    seen = {subject.id}
    if part is Part.MEANING:
        norm = _normalize(typed)
        if not norm:
            return []
        like = f'%"meaning": "{typed[:1].upper()}{typed[1:]}%'
        rows = db.conn.execute(
            "SELECT id,type,data FROM subjects WHERE hidden=0 AND (data LIKE ? OR data LIKE ?) LIMIT 200", (like, f'%"meaning": "{typed}%')
        ).fetchall()
        for r in rows:
            if r["id"] in seen:
                continue
            s = Subject.from_raw({"id": r["id"], "object": r["type"], "data": json.loads(r["data"])}, db.study_material(r["id"]))
            for m in s.accepted_meanings:
                mn = _normalize(m)
                if mn == norm or levenshtein(mn, norm) <= meaning_tolerance(len(mn)):
                    out.append((s, f"its meaning is “{m}”"))
                    seen.add(s.id)
                    break
    else:
        kana = wanakana.to_hiragana(typed)
        if not wanakana.is_kana(kana.replace("ー", "")):
            return []
        # subject JSON is stored with ASCII escapes, so match the escaped form of the kana
        rows = db.conn.execute(
            "SELECT id,type,data FROM subjects WHERE hidden=0 AND type IN ('kanji','vocabulary') AND (data LIKE ? OR data LIKE ?) LIMIT 200",
            (f'%"reading": {json.dumps(kana)}%', f'%"reading": "{kana}"%'),
        ).fetchall()
        for r in rows:
            if r["id"] in seen:
                continue
            s = Subject.from_raw({"id": r["id"], "object": r["type"], "data": json.loads(r["data"])})
            if kana in {wanakana.to_hiragana(x["reading"]) for x in s.readings}:
                why = f"it is read {kana}"
                if s.is_kanji and s.id in subject.similar_ids:
                    why += " and looks similar"
                out.append((s, why))
                seen.add(s.id)
    # prefer items that look like this one, then same type, then lower level
    similar = set(subject.similar_ids) | set(subject.component_ids)
    out.sort(key=lambda t: (t[0].id not in similar, t[0].type != subject.type, t[0].level))
    return out[:limit]
