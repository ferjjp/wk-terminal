"""OS-specific choices for Linux and macOS: terminal command, audio player, fonts, autostart."""

from __future__ import annotations

import shutil
import sys

IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def os_name() -> str:
    return "macos" if IS_MAC else "linux" if IS_LINUX else sys.platform


def default_terminal_command() -> str:
    """Command prefix that runs `wk pop` in a new small window, for the daemon's popup."""
    if IS_MAC:
        if shutil.which("ghostty") or _mac_app_exists("Ghostty"):
            exe = shutil.which("ghostty") or "/Applications/Ghostty.app/Contents/MacOS/ghostty"
            return f"{exe} --title=WaniKani --window-width=72 --window-height=24 -e"
        if shutil.which("kitty"):
            return "kitty --title WaniKani -o remember_window_size=no -o initial_window_width=72c -o initial_window_height=24c"
        if shutil.which("wezterm"):
            return "wezterm start --"
        return "osascript-terminal"  # handled specially: Terminal.app via AppleScript
    if shutil.which("ghostty"):
        return "ghostty --title=WaniKani --class=wanikani-popup --window-width=72 --window-height=24 -e"
    if shutil.which("kitty"):
        return "kitty --title WaniKani -o remember_window_size=no -o initial_window_width=72c -o initial_window_height=24c"
    if shutil.which("wezterm"):
        return "wezterm start --"
    for t in ("foot", "alacritty", "gnome-terminal", "xterm"):
        if shutil.which(t):
            return {"gnome-terminal": "gnome-terminal --"}.get(t, f"{t} -e")
    return "xterm -e"


def _mac_app_exists(name: str) -> bool:
    from pathlib import Path

    return Path(f"/Applications/{name}.app").exists()


def audio_players() -> list[tuple[str, list[str]]]:
    players = [
        ("mpv", ["mpv", "--no-video", "--really-quiet"]),
        ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]),
    ]
    if IS_MAC:
        players.insert(0, ("afplay", ["afplay"]))
    else:
        players.append(("paplay", ["paplay"]))
    return players


def font_candidates() -> list[str]:
    if IS_MAC:
        return [
            "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
            "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/PingFang.ttc",
        ]
    return [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ]


def notification_backend() -> str:
    """linux-dbus | mac-terminal-notifier (clickable) | mac-osascript (not clickable) | none"""
    if IS_LINUX:
        return "linux-dbus"
    if IS_MAC:
        if shutil.which("terminal-notifier"):
            return "mac-terminal-notifier"
        if shutil.which("osascript"):
            return "mac-osascript"
    return "none"
