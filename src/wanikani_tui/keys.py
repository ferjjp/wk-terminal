"""Key bindings by action name, overridable from [keys] in config.toml."""

from __future__ import annotations

from .config import settings

DEFAULTS = {
    "reviews": "r", "lessons": "l", "browse": "b", "sync": "s", "stats": "t", "quit": "q",
    "back": "escape", "search": "slash", "type_filter": "t", "filter": "f",
    "related": "g", "open": "o", "audio": "a", "strokes": "s", "synonym": "y", "note": "n",
    "info": "f1", "undo": "ctrl+z", "leave": "escape", "next": "right", "prev": "left",
}


def key(action: str) -> str:
    return settings().keys.get(action, DEFAULTS[action])
