"""Paths and credentials."""

from __future__ import annotations

import os
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


def db_path() -> Path:
    return data_dir() / "cache.sqlite3"


def image_cache_dir() -> Path:
    d = data_dir() / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def token_file() -> Path:
    return config_dir() / "token"


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
        "(enable 'assignments:start' and 'reviews:create'), then either\n"
        f"  export WANIKANI_API_TOKEN=...   or   store it in {f}"
    )
