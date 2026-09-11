"""Review / lesson-quiz queue logic, independent of the UI."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from .models import Assignment, Subject


class Part(Enum):
    MEANING = "meaning"
    READING = "reading"


@dataclass
class Item:
    subject: Subject
    assignment: Assignment
    need: set[Part] = field(default_factory=set)
    wrong: dict[Part, int] = field(default_factory=lambda: {Part.MEANING: 0, Part.READING: 0})
    submitted: bool = False

    @classmethod
    def build(cls, subject: Subject, assignment: Assignment) -> "Item":
        need = {Part.MEANING}
        if subject.has_reading:
            need.add(Part.READING)
        return cls(subject=subject, assignment=assignment, need=need)

    @property
    def done(self) -> bool:
        return not self.need

    @property
    def incorrect(self) -> int:
        return self.wrong[Part.MEANING] + self.wrong[Part.READING]

    @property
    def all_correct(self) -> bool:
        return self.incorrect == 0


class Queue:
    """Hands out (item, part) prompts WaniKani-style: a small active pool, random order."""

    def __init__(self, items: list[Item], active_size: int = 10, seed: int | None = None) -> None:
        self.rng = random.Random(seed)
        self.pending = list(items)
        self.rng.shuffle(self.pending)
        self.active: list[Item] = []
        self.finished: list[Item] = []
        self.active_size = active_size
        self.wrapping_up = False
        self.last: tuple[Item, Part] | None = None

    @property
    def total(self) -> int:
        return len(self.pending) + len(self.active) + len(self.finished)

    @property
    def remaining(self) -> int:
        return len(self.pending) + len(self.active)

    @property
    def correct_count(self) -> int:
        return sum(1 for i in self.finished if i.all_correct)

    def wrap_up(self) -> None:
        self.wrapping_up = True
        self.pending.clear()

    def next(self) -> tuple[Item, Part] | None:
        while len(self.active) < self.active_size and self.pending:
            self.active.append(self.pending.pop())
        if not self.active:
            return None
        candidates = list(self.active)
        # avoid asking the same item twice in a row when there is a choice
        if self.last and len(candidates) > 1:
            candidates = [c for c in candidates if c is not self.last[0]] or candidates
        item = self.rng.choice(candidates)
        part = self.rng.choice(sorted(item.need, key=lambda p: p.value))
        self.last = (item, part)
        return item, part

    def mark(self, item: Item, part: Part, correct: bool) -> bool:
        """Record an answer. Returns True when the item just became complete."""
        if correct:
            item.need.discard(part)
            if item.done:
                self.active.remove(item)
                self.finished.append(item)
                return True
            return False
        item.wrong[part] += 1
        return False
