"""`wk read`: colour any Japanese text by what you know, and list what you don't."""

from __future__ import annotations

import json
import sys
from collections import Counter, OrderedDict
from dataclasses import dataclass, field

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .db import Database
from .models import SRS_NAMES, srs_color, srs_group


def is_kanji(ch: str) -> bool:
    o = ord(ch)
    return 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or ch == "々"


@dataclass
class Report:
    text: str
    kanji_total: int = 0
    kanji_distinct: int = 0
    by_group: Counter = field(default_factory=Counter)      # started kanji by SRS group (occurrences)
    locked: "OrderedDict[str, dict]" = field(default_factory=OrderedDict)   # in WaniKani, not started yet
    outside: Counter = field(default_factory=Counter)        # not in WaniKani at all
    vocab_known: Counter = field(default_factory=Counter)
    vocab_unknown: "OrderedDict[str, dict]" = field(default_factory=OrderedDict)
    highlighted: Text = field(default_factory=Text)

    @property
    def coverage(self) -> float:
        known = sum(self.by_group.values())
        return known / self.kanji_total if self.kanji_total else 1.0


def analyse(db: Database, text: str, with_vocab: bool = True) -> Report:
    rep = Report(text=text)
    chars = {c for c in text if is_kanji(c)}
    if not chars:
        rep.highlighted = Text(text)
        return rep
    rows = db.conn.execute(
        f"SELECT s.id, s.characters, s.level, s.data, a.srs_stage, a.started_at FROM subjects s LEFT JOIN assignments a ON a.subject_id=s.id"
        f" WHERE s.type='kanji' AND s.hidden=0 AND s.characters IN ({','.join('?' * len(chars))})", list(chars)
    ).fetchall()
    info: dict[str, dict] = {}
    for r in rows:
        d = json.loads(r["data"])
        info[r["characters"]] = {
            "id": r["id"], "level": r["level"], "stage": r["srs_stage"] if r["started_at"] else None,
            "meaning": next((m["meaning"] for m in d["meanings"] if m.get("primary")), "?"),
            "reading": ", ".join(x["reading"] for x in d.get("readings", []) if x.get("primary")),
        }
    # vocabulary: longest match over WaniKani words containing at least one kanji
    vocab: dict[str, dict] = {}
    if with_vocab:
        vrows = db.conn.execute(
            "SELECT s.id, s.characters, s.level, s.data, a.srs_stage, a.started_at FROM subjects s LEFT JOIN assignments a ON a.subject_id=s.id"
            " WHERE s.type='vocabulary' AND s.hidden=0"
        ).fetchall()
        for r in vrows:
            w = r["characters"] or ""
            if w and w in text:
                d = json.loads(r["data"])
                vocab[w] = {"level": r["level"], "stage": r["srs_stage"] if r["started_at"] else None,
                            "meaning": next((m["meaning"] for m in d["meanings"] if m.get("primary")), "?"),
                            "reading": ", ".join(x["reading"] for x in d.get("readings", []) if x.get("primary"))}
    maxlen = max((len(w) for w in vocab), default=0)

    out = Text()
    i = 0
    seen_kanji: set[str] = set()
    while i < len(text):
        ch = text[i]
        if with_vocab and is_kanji(ch):
            hit = None
            for L in range(min(maxlen, len(text) - i), 0, -1):
                cand = text[i:i + L]
                if cand in vocab:
                    hit = cand
                    break
            if hit and len(hit) > 1:
                v = vocab[hit]
                if v["stage"] is not None:
                    rep.vocab_known[hit] += 1
                    out.append(hit, style=f"underline {srs_color(v['stage'])}")
                else:
                    rep.vocab_unknown.setdefault(hit, v)
                    out.append(hit, style="underline #ffa040")
                for c in hit:
                    _count_kanji(rep, info, c, seen_kanji)
                i += len(hit)
                continue
        if is_kanji(ch):
            k = info.get(ch)
            _count_kanji(rep, info, ch, seen_kanji)
            if k is None:
                out.append(ch, style="bold #e04040")
            elif k["stage"] is None:
                out.append(ch, style="bold #ffa040")
            else:
                out.append(ch, style=f"bold {srs_color(k['stage'])}")
        else:
            out.append(ch)
        i += 1
    rep.highlighted = out
    return rep


def _count_kanji(rep: Report, info: dict, ch: str, seen: set[str]) -> None:
    if not is_kanji(ch) or ch == "々":
        return
    rep.kanji_total += 1
    if ch not in seen:
        seen.add(ch)
        rep.kanji_distinct += 1
    k = info.get(ch)
    if k is None:
        rep.outside[ch] += 1
    elif k["stage"] is None:
        rep.locked.setdefault(ch, k)
    else:
        rep.by_group[srs_group(k["stage"])] += 1


def render(rep: Report, console: Console, top: int = 30, show_text: bool = True) -> None:
    if show_text:
        console.print(rep.highlighted)
        console.print()
    if rep.kanji_total == 0:
        console.print("[dim]No kanji in this text.[/dim]")
        return
    known = sum(rep.by_group.values())
    head = Text()
    head.append(f"{rep.kanji_total} kanji ({rep.kanji_distinct} distinct)  ·  ", style="bold")
    head.append(f"{100 * known // rep.kanji_total}% known", style="bold green" if rep.coverage >= 0.9 else "bold yellow" if rep.coverage >= 0.7 else "bold red")
    parts = []
    for grp in ("apprentice", "guru", "master", "enlightened", "burned"):
        if rep.by_group.get(grp):
            parts.append(Text(f"{rep.by_group[grp]} {grp}", style=srs_color({"apprentice": 1, "guru": 5, "master": 7, "enlightened": 8, "burned": 9}[grp])))
    if parts:
        head.append("   ")
        for k, p in enumerate(parts):
            if k:
                head.append(" · ", style="dim")
            head.append_text(p)
    console.print(head)
    if rep.vocab_known or rep.vocab_unknown:
        console.print(Text(f"vocabulary: {sum(rep.vocab_known.values())} words you know, {len(rep.vocab_unknown)} WaniKani words you haven't learned", style="dim"))
    if rep.locked:
        t = Table(title=f"Not learned yet ({len(rep.locked)} kanji, by WaniKani level)", title_style="bold #ffa040", show_lines=False, pad_edge=False)
        t.add_column("kanji"); t.add_column("level", justify="right"); t.add_column("meaning"); t.add_column("reading")
        for ch, k in sorted(rep.locked.items(), key=lambda kv: kv[1]["level"])[:top]:
            t.add_row(Text(ch, style="bold #ffa040"), str(k["level"]), k["meaning"], k["reading"])
        console.print(t)
    if rep.vocab_unknown:
        t = Table(title=f"WaniKani vocabulary in the text you haven't learned ({len(rep.vocab_unknown)})", title_style="bold #ffa040", pad_edge=False)
        t.add_column("word"); t.add_column("level", justify="right"); t.add_column("meaning"); t.add_column("reading")
        for w, v in sorted(rep.vocab_unknown.items(), key=lambda kv: kv[1]["level"])[:top]:
            t.add_row(Text(w, style="bold #ffa040"), str(v["level"]), v["meaning"], v["reading"])
        console.print(t)
    if rep.outside:
        console.print(Text.assemble(("Not in WaniKani: ", "bold #e04040"), (" ".join(f"{c}×{n}" if n > 1 else c for c, n in rep.outside.most_common(top)), "#e04040")))


def main(db: Database, source: str | None, top: int = 30, no_vocab: bool = False, summary_only: bool = False) -> int:
    if source and source != "-":
        try:
            text = open(source, encoding="utf-8").read()
        except OSError as exc:
            print(f"cannot read {source}: {exc}", file=sys.stderr)
            return 2
    else:
        text = sys.stdin.read()
    rep = analyse(db, text, with_vocab=not no_vocab)
    render(rep, Console(), top=top, show_text=not summary_only)
    return 0
