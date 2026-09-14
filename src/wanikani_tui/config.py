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
community_data = true        # fetch Keisei/Niai datasets (GPL-3) from GitHub on first use for the item screen

[daemon]
sync_minutes = 10            # how often the daemon refreshes assignments
interval_minutes = 30        # minimum time between notifications
min_due = 1                  # only notify when at least this many reviews are due
quiet_hours = ["23:00", "08:00"]
popup = "notify"             # notify (notification with a button) | auto (open the window directly) | none
popup_items = 1              # reviews per popup window
popup_pick = "smart"         # smart (leeches, low SRS, overdue, weak accuracy first) | oldest
popup_skip_recent_hours = 1  # never pop an item answered this recently
prefer = "reviews"           # reviews | lessons | mixed  (what a popup shows when both are available)
# terminal = "ghostty --title=WaniKani -e"   # default: detected (ghostty, kitty, wezterm, …; Terminal.app on macOS)
notify_lessons = false       # also notify when lessons are waiting and nothing is due

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
# full_app = "f2"        next = "right"       prev = "left"          select = "space"  select_all = "a"
# scroll_down = "j"      scroll_up = "k"
"""


@dataclass
class Settings:
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
    ui_community_data: bool = True
    daemon_sync_minutes: int = 10
    daemon_interval_minutes: int = 30
    daemon_min_due: int = 1
    daemon_quiet_hours: tuple[str, str] | None = ("23:00", "08:00")
    daemon_popup: str = "notify"
    daemon_popup_items: int = 1
    popup_pick: str = "smart"
    popup_skip_recent_hours: float = 1.0
    daemon_prefer: str = "reviews"
    daemon_terminal: str = ""  # empty = detect at runtime (see platform.default_terminal_command)
    daemon_notify_lessons: bool = False
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
    s.ui_community_data = bool(_get(raw, "ui", "community_data", True))
    s.daemon_sync_minutes = int(_get(raw, "daemon", "sync_minutes", 10))
    s.daemon_interval_minutes = int(_get(raw, "daemon", "interval_minutes", 30))
    s.daemon_min_due = int(_get(raw, "daemon", "min_due", 1))
    qh = _get(raw, "daemon", "quiet_hours", ["23:00", "08:00"])
    s.daemon_quiet_hours = (str(qh[0]), str(qh[1])) if qh and len(qh) == 2 else None
    s.daemon_popup = str(_get(raw, "daemon", "popup", "notify"))
    s.daemon_popup_items = int(_get(raw, "daemon", "popup_items", 1))
    s.popup_pick = str(_get(raw, "daemon", "popup_pick", "smart"))
    s.popup_skip_recent_hours = float(_get(raw, "daemon", "popup_skip_recent_hours", 1))
    s.daemon_prefer = str(_get(raw, "daemon", "prefer", "reviews"))
    s.daemon_terminal = str(_get(raw, "daemon", "terminal", "") or "")
    s.daemon_notify_lessons = bool(_get(raw, "daemon", "notify_lessons", False))
    s.keys = {str(k): str(v) for k, v in (raw.get("keys") or {}).items()}
    return s


def write_default_config() -> Path:
    f = config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    if not f.exists():
        f.write_text(DEFAULT_CONFIG)
    return f
