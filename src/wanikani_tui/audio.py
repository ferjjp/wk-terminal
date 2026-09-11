"""Vocabulary pronunciation playback through whatever player is installed."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from .config import audio_cache_dir

from .platform import audio_players


def player() -> list[str] | None:
    for name, cmd in audio_players():
        if shutil.which(name):
            return cmd
    return None


def pick_audio(audios: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not audios:
        return None
    mp3 = [a for a in audios if a.get("content_type") == "audio/mpeg"]
    return (mp3 or audios)[0]


def audio_file(audios: list[dict[str, Any]], fetch: Callable[[str], bytes]) -> Path | None:
    a = pick_audio(audios)
    if not a:
        return None
    ext = ".mp3" if a.get("content_type") == "audio/mpeg" else ".ogg"
    f = audio_cache_dir() / (hashlib.sha1(a["url"].encode()).hexdigest()[:16] + ext)
    if not f.exists():
        f.write_bytes(fetch(a["url"]))
    return f


def play(path: Path) -> bool:
    cmd = player()
    if not cmd:
        return False
    subprocess.Popen(cmd + [str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return True
