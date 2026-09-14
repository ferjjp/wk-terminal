"""Key bindings by action name, overridable from [keys] in config.toml."""

from __future__ import annotations

from .config import settings

# action -> (default key, where it applies, what it does). Textual key names: letters as-is, "slash",
# "plus", "minus", "space", "enter", "escape", "f1".."f12", "ctrl+z", "shift+..." etc.
ACTIONS: dict[str, tuple[str, str, str]] = {
    "reviews": ("r", "dashboard", "start reviews"),
    "lessons": ("l", "dashboard", "start the next lesson batch"),
    "pick_lessons": ("L", "dashboard", "choose which lessons to take"),
    "browse": ("b", "dashboard", "browse items by level"),
    "leeches": ("e", "dashboard", "your leeches"),
    "study": ("x", "dashboard / browse", "self-study quiz (no SRS impact)"),
    "stats": ("t", "dashboard", "statistics"),
    "sync": ("s", "dashboard", "sync now"),
    "quit": ("q", "dashboard", "quit"),
    "scroll_down": ("j", "scrollable screens", "scroll down (vim)"),
    "scroll_up": ("k", "scrollable screens", "scroll up (vim)"),
    "back": ("escape", "everywhere", "go back / close"),
    "search": ("slash", "browse", "search"),
    "type_filter": ("t", "browse / lesson picker", "cycle item type"),
    "filter": ("f", "browse", "cycle filter (due, leeches, SRS group)"),
    "related": ("g", "item", "jump to a related item"),
    "open": ("o", "item", "open on wanikani.com"),
    "audio": ("a", "item / lessons", "play audio"),
    "strokes": ("s", "item / lessons", "stroke order"),
    "synonym": ("y", "item", "add a meaning synonym"),
    "note": ("n", "item", "edit your note"),
    "info": ("f1", "reviews", "item details after answering"),
    "undo": ("ctrl+z", "reviews", "undo the last answer"),
    "mark_correct": ("plus", "reviews", "override: accept the last answer"),
    "mark_incorrect": ("minus", "reviews", "override: reject the last answer"),
    "leave": ("escape", "reviews / lessons", "wrap up or quit"),
    "full_app": ("f2", "popup", "open the full app"),
    "next": ("right", "lessons", "next item"),
    "prev": ("left", "lessons", "previous item"),
    "next_alt": ("n", "lessons", "next item (alternative)"),
    "prev_alt": ("p", "lessons", "previous item (alternative)"),
    "select": ("space", "lesson picker", "select / deselect"),
    "select_all": ("a", "lesson picker", "select all / none"),
}
DEFAULTS = {name: spec[0] for name, spec in ACTIONS.items()}


def key(action: str) -> str:
    return settings().keys.get(action, DEFAULTS[action])


def unknown_overrides() -> list[str]:
    return sorted(k for k in settings().keys if k not in ACTIONS)


def describe() -> list[tuple[str, str, str, str, bool]]:
    """(action, current key, default, description/where, overridden) for `wk keys`."""
    cfg = settings().keys
    return [(a, cfg.get(a, d), d, f"{where}: {what}", a in cfg) for a, (d, where, what) in ACTIONS.items()]
