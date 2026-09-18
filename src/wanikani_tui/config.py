"""Paths, credentials and the user's config.toml."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


class MissingToken(RuntimeError):
    pass


def config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    return base / "wanikani"


def data_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
    d = base / "wanikani-tui"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_dir() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser()
    d = base / "wanikani-tui"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "cache.sqlite3"


def image_cache_dir() -> Path:
    d = data_dir() / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def audio_cache_dir() -> Path:
    d = data_dir() / "audio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def token_file() -> Path:
    return config_dir() / "token"


def config_file() -> Path:
    return config_dir() / "config.toml"


def api_token() -> str:
    tok = os.environ.get("WANIKANI_API_TOKEN", "").strip()
    if tok:
        return tok
    f = token_file()
    if f.exists():
        tok = f.read_text().strip()
        if tok:
            return tok
    raise MissingToken(
        "No WaniKani API token found.\n"
        "Create one at https://www.wanikani.com/settings/personal_access_tokens\n"
        "(enable 'assignments:start', 'reviews:create' and 'study_materials:create/update'), then either\n"
        f"  export WANIKANI_API_TOKEN=...   or   store it in {f}"
    )


# --------------------------------------------------------------------------- settings

DEFAULT_CONFIG = """\
# wanikani-tui configuration. Every key is optional; these are the defaults.

[review]
anki = false                 # Anki mode: reveal the answer, then grade yourself (no typing)
lightning = false            # advance automatically after a correct answer
order = "random"             # random | level | back_to_back
show_mnemonic_on_miss = true
audio_autoplay = true        # play vocabulary audio after its reading is answered

[lessons]
batch_size = 0               # 0 = use your WaniKani preference
audio_autoplay = true

[images]
mode = "auto"                # auto | tgp | sixel | halfcell | unicode | none
height = 7                   # rows for the big character

[ui]
theme = "textual-dark"       # any Textual theme: textual-dark, textual-light, tokyo-night, nord, gruvbox, dracula, ...
colorblind = false           # Okabe-Ito palette for SRS stages
vim_keys = true              # j/k scroll, h/l navigate lessons
compact = "auto"             # auto | true | false  (small panes: shorter image, tighter layout)
katakana_onyomi = false      # show on'yomi in katakana (dictionary convention)
pitch_accent = true          # fetch Kanjium pitch-accent data (CC BY-SA 4.0) on first use for vocabulary
community_data = true        # fetch Keisei/Niai datasets (GPL-3) from GitHub on first use for the item screen

[daemon]
sync_minutes = 10            # how often the daemon refreshes assignments
interval_minutes = 30        # minimum time between notifications
min_due = 1                  # only notify when at least this many reviews are due
quiet_hours = ["23:00", "08:00"]
popup = "notify"             # notify (notification with a button) | auto (open the window directly) | none
popup_items = 1              # reviews per popup window
popup_pick = "smart"         # smart (leeches, low SRS, overdue, weak accuracy first) | oldest
popup_skip_recent_hours = 3  # never pop an item answered this recently (right or wrong)
prefer = "reviews"           # reviews | lessons | mixed  (what a popup shows when both are available)
# terminal = "ghostty --title=WaniKani -e"   # default: detected (ghostty, kitty, wezterm, …; Terminal.app on macOS)
notify_lessons = false       # also notify when lessons are waiting and nothing is due
only_when_active = true      # hold notifications while you are away from the keyboard (GNOME idle monitor)
active_idle_seconds = 120    # "at the keyboard" means an input event within this many seconds
respect_dnd = true           # stay quiet while the desktop is in do-not-disturb
snooze_minutes = 60          # the notification's "Later" button postpones the next reminder this long

[goal]
reviews_per_day = 0          # daily review target shown on the dashboard (0 = off); streak counts days that met it
evening_nudge = "20:00"      # one extra notification at this time if the goal is unmet ("" = off)

[keys]
# Any action can be rebound; `wk keys` lists them all with their current key.
# Key names: letters as-is (case matters: "L" is shift+l), "slash", "plus", "minus", "space",
# "enter", "escape", "f1".."f12", "ctrl+z", "ctrl+shift+x", "up"/"down"/"left"/"right".
# reviews = "r"          lessons = "l"        pick_lessons = "L"     browse = "b"
# leeches = "e"          study = "x"          stats = "t"            sync = "s"        quit = "q"
# back = "escape"        search = "slash"     type_filter = "t"      filter = "f"
# related = "g"          open = "o"           audio = "a"            strokes = "s"
# synonym = "y"          note = "n"           info = "f1"            undo = "ctrl+z"
# mark_correct = "plus"  mark_incorrect = "minus"                    leave = "escape"
# anki_reveal = "space"  anki_correct = "1"   anki_incorrect = "2"   anki_toggle = "f3"
# full_app = "f2"        next = "right"       prev = "left"          select = "space"  select_all = "a"
# scroll_down = "j"      scroll_up = "k"
"""


@dataclass
class Settings:
    review_anki: bool = False
    review_lightning: bool = False
    review_order: str = "random"
    review_show_mnemonic_on_miss: bool = True
    review_audio_autoplay: bool = True
    lessons_batch_size: int = 0
    lessons_audio_autoplay: bool = True
    images_mode: str = "auto"
    images_height: int = 7
    ui_theme: str = "textual-dark"
    ui_colorblind: bool = False
    ui_vim_keys: bool = True
    ui_compact: str = "auto"
    ui_katakana_onyomi: bool = False
    ui_pitch_accent: bool = True
    ui_community_data: bool = True
    daemon_sync_minutes: int = 10
    daemon_interval_minutes: int = 30
    daemon_min_due: int = 1
    daemon_quiet_hours: tuple[str, str] | None = ("23:00", "08:00")
    daemon_popup: str = "notify"
    daemon_popup_items: int = 1
    popup_pick: str = "smart"
    popup_skip_recent_hours: float = 3.0
    daemon_prefer: str = "reviews"
    daemon_terminal: str = ""  # empty = detect at runtime (see platform.default_terminal_command)
    daemon_notify_lessons: bool = False
    daemon_only_when_active: bool = True
    daemon_active_idle_seconds: float = 120.0
    daemon_respect_dnd: bool = True
    daemon_snooze_minutes: int = 60
    goal_reviews_per_day: int = 0
    goal_evening_nudge: str = "20:00"
    keys: dict[str, str] = field(default_factory=dict)


def _get(d: dict, section: str, key: str, default):
    v = (d.get(section) or {}).get(key, default)
    return v if v is not None else default


@lru_cache(maxsize=1)
def settings() -> Settings:
    f = config_file()
    raw: dict = {}
    if f.exists():
        try:
            raw = tomllib.loads(f.read_text())
        except tomllib.TOMLDecodeError as exc:
            raise RuntimeError(f"{f}: {exc}") from exc
    s = Settings()
    s.review_anki = bool(_get(raw, "review", "anki", False))
    s.review_lightning = bool(_get(raw, "review", "lightning", s.review_lightning))
    s.review_order = str(_get(raw, "review", "order", s.review_order))
    s.review_show_mnemonic_on_miss = bool(_get(raw, "review", "show_mnemonic_on_miss", True))
    s.review_audio_autoplay = bool(_get(raw, "review", "audio_autoplay", True))
    s.lessons_batch_size = int(_get(raw, "lessons", "batch_size", 0))
    s.lessons_audio_autoplay = bool(_get(raw, "lessons", "audio_autoplay", True))
    s.images_mode = str(_get(raw, "images", "mode", "auto"))
    s.images_height = int(_get(raw, "images", "height", 7))
    s.ui_theme = str(_get(raw, "ui", "theme", "textual-dark"))
    s.ui_colorblind = bool(_get(raw, "ui", "colorblind", False))
    s.ui_vim_keys = bool(_get(raw, "ui", "vim_keys", True))
    compact = _get(raw, "ui", "compact", "auto")
    s.ui_compact = "true" if compact is True else "false" if compact is False else str(compact)
    s.ui_katakana_onyomi = bool(_get(raw, "ui", "katakana_onyomi", False))
    s.ui_pitch_accent = bool(_get(raw, "ui", "pitch_accent", True))
    s.ui_community_data = bool(_get(raw, "ui", "community_data", True))
    s.daemon_sync_minutes = int(_get(raw, "daemon", "sync_minutes", 10))
    s.daemon_interval_minutes = int(_get(raw, "daemon", "interval_minutes", 30))
    s.daemon_min_due = int(_get(raw, "daemon", "min_due", 1))
    qh = _get(raw, "daemon", "quiet_hours", ["23:00", "08:00"])
    s.daemon_quiet_hours = (str(qh[0]), str(qh[1])) if qh and len(qh) == 2 else None
    s.daemon_popup = str(_get(raw, "daemon", "popup", "notify"))
    s.daemon_popup_items = int(_get(raw, "daemon", "popup_items", 1))
    s.popup_pick = str(_get(raw, "daemon", "popup_pick", "smart"))
    s.popup_skip_recent_hours = float(_get(raw, "daemon", "popup_skip_recent_hours", 3))
    s.daemon_prefer = str(_get(raw, "daemon", "prefer", "reviews"))
    s.daemon_terminal = str(_get(raw, "daemon", "terminal", "") or "")
    s.daemon_notify_lessons = bool(_get(raw, "daemon", "notify_lessons", False))
    s.daemon_only_when_active = bool(_get(raw, "daemon", "only_when_active", True))
    s.daemon_active_idle_seconds = float(_get(raw, "daemon", "active_idle_seconds", 120))
    s.daemon_respect_dnd = bool(_get(raw, "daemon", "respect_dnd", True))
    s.daemon_snooze_minutes = int(_get(raw, "daemon", "snooze_minutes", 60))
    s.goal_reviews_per_day = int(_get(raw, "goal", "reviews_per_day", 0))
    s.goal_evening_nudge = str(_get(raw, "goal", "evening_nudge", "20:00") or "")
    s.keys = {str(k): str(v) for k, v in (raw.get("keys") or {}).items()}
    return s


def write_default_config() -> Path:
    f = config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    if not f.exists():
        f.write_text(DEFAULT_CONFIG)
    return f


def save_setting(section: str, key: str, value: str) -> None:
    """Persist one key in config.toml, keeping the rest of the file (and its comments) untouched."""
    import re

    f = config_file()
    if not f.exists():
        write_default_config()
    text = f.read_text()
    line = f'{key} = "{value}"'
    sec = re.search(rf"(?m)^\[{re.escape(section)}\]\s*$", text)
    if sec:
        start = sec.end()
        nxt = re.search(r"(?m)^\[", text[start:])
        end = start + nxt.start() if nxt else len(text)
        body = text[start:end]
        pat = re.compile(rf"(?m)^{re.escape(key)}\s*=\s*[^\n#]*(#.*)?$")
        m = pat.search(body)
        if m:
            comment = f"  {m.group(1)}" if m.group(1) else ""
            body = body[:m.start()] + line + comment + body[m.end():]
        else:
            body = body.rstrip("\n") + f"\n{line}\n\n"
        text = text[:start] + body + text[end:]
    else:
        text = text.rstrip("\n") + f"\n\n[{section}]\n{line}\n"
    f.write_text(text)
    settings.cache_clear()
