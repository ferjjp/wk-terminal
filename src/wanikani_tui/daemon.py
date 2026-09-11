"""`wk daemon`: keep the cache fresh and nudge with desktop notifications; `wk pop` opens one item."""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import Settings, config_dir, settings, state_dir
from .core import Core
from .platform import IS_MAC, default_terminal_command, notification_backend

log = logging.getLogger("wk.daemon")

UNIT_NAME = "wanikani-tui.service"


def in_quiet_hours(cfg: Settings, now: datetime | None = None) -> bool:
    if not cfg.daemon_quiet_hours:
        return False
    now = now or datetime.now()
    start_s, end_s = cfg.daemon_quiet_hours
    sh, sm = map(int, start_s.split(":"))
    eh, em = map(int, end_s.split(":"))
    start, end = now.replace(hour=sh, minute=sm, second=0, microsecond=0), now.replace(hour=eh, minute=em, second=0, microsecond=0)
    if start <= end:
        return start <= now < end
    return now >= start or now < end  # spans midnight


def wk_executable() -> list[str]:
    exe = shutil.which("wk")
    if exe:
        return [exe]
    return [sys.executable, "-m", "wanikani_tui.cli"]


def popup_command(cfg: Settings) -> list[str]:
    term = cfg.daemon_terminal or default_terminal_command()
    if term == "osascript-terminal":  # macOS without a graphics-capable terminal: Terminal.app
        inner = " ".join(shlex.quote(p) for p in wk_executable() + ["pop"])
        return ["osascript", "-e", f'tell application "Terminal" to do script "{inner}"', "-e", 'tell application "Terminal" to activate']
    return shlex.split(term) + wk_executable() + ["pop"]


def open_popup(cfg: Settings) -> subprocess.Popen | None:
    cmd = popup_command(cfg)
    log.info("opening popup: %s", " ".join(cmd))
    try:
        return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        log.error("could not start terminal: %s", exc)
        return None


def notify(title: str, body: str, action: bool, timeout_s: int = 120, icon: str | None = None) -> str:
    """Desktop notification; with `action`, block until clicked/closed and return the action id."""
    from . import notify as dbus_notify

    actions = [("default", "Review now"), ("review", "Review now"), ("later", "Later")] if action else None
    return dbus_notify.send(title, body, actions=actions, timeout_s=timeout_s, icon=icon or "accessories-dictionary",
                            click_command=popup_command(settings()) if action else None)


def notification_icon(core: Core) -> str | None:
    """A PNG of the item the popup would show, in its WaniKani colour, for the notification."""
    try:
        from .images import text_image

        mode, items = core.popup_items()
        if items:
            s = items[0].subject
            img = text_image(s.characters or s.primary_meaning, s.color, px=96 if s.characters else 28, pad=14)
        else:
            img = text_image("鰐", "#00aaff", px=96, pad=14)
        path = state_dir() / "notification.png"
        img.save(path)
        return str(path)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not render notification icon: %s", exc)
        return None


def run(core: Core, once: bool = False) -> int:
    cfg = core.cfg
    log_file = state_dir() / "daemon.log"
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    )
    log.info("daemon started on %s (notifications: %s; sync every %d min, notify at most every %d min)",
             sys.platform, notification_backend(), cfg.daemon_sync_minutes, cfg.daemon_interval_minutes)
    if notification_backend() == "mac-osascript":
        log.warning("clicks on notifications need terminal-notifier (brew install terminal-notifier); using plain notifications")
    last_sync = datetime.min
    last_notify = datetime.min
    while True:
        now = datetime.now()
        if now - last_sync >= timedelta(minutes=cfg.daemon_sync_minutes):
            try:
                counts = core.sync(light=not core.needs_full_sync(), full=core.needs_full_sync())
                log.info("synced: %s", counts)
            except Exception as exc:  # noqa: BLE001
                log.warning("sync failed: %s", exc)
            last_sync = now
        reviews, lessons, next_at = core.due_counts()
        want_reviews = reviews >= cfg.daemon_min_due
        want_lessons = cfg.daemon_notify_lessons and reviews == 0 and lessons > 0
        if (want_reviews or want_lessons) and not in_quiet_hours(cfg) and now - last_notify >= timedelta(minutes=cfg.daemon_interval_minutes):
            last_notify = now
            if want_reviews:
                title, body = f"{reviews} review{'s' if reviews != 1 else ''} waiting", "Open a quick review window?"
            else:
                title, body = f"{lessons} lesson{'s' if lessons != 1 else ''} available", "Learn one new item?"
            icon = notification_icon(core)
            if cfg.daemon_popup == "auto":
                notify(title, "Opening a review window…", action=False, timeout_s=5, icon=icon)
                open_popup(cfg)
            elif cfg.daemon_popup == "notify":
                choice = notify(title, body, action=True, icon=icon)
                log.info("notification answered: %r", choice or "(closed or expired)")
                if choice in ("review", "default"):
                    open_popup(cfg)
                # 'launched': the macOS notifier runs the popup itself on click
            else:
                notify(title, body, action=False, icon=icon)
        elif next_at and reviews == 0:
            log.debug("nothing due; next at %s", next_at.astimezone().strftime("%H:%M"))
        if once:
            return 0
        time.sleep(60)


SYSTEMD_UNIT = """\
[Unit]
Description=WaniKani terminal companion (sync + review reminders)
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart={exe} daemon
Restart=on-failure
RestartSec=30
Environment=PATH={path}

[Install]
WantedBy=graphical-session.target
"""


LAUNCHD_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{label}</string>
    <key>ProgramArguments</key><array>{args}</array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>EnvironmentVariables</key><dict><key>PATH</key><string>{path}</string></dict>
    <key>StandardOutPath</key><string>{log}</string>
    <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""
LAUNCHD_LABEL = "com.wanikani-tui.daemon"


def _launchd_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def install_service() -> Path:
    if IS_MAC:
        plist = _launchd_plist()
        plist.parent.mkdir(parents=True, exist_ok=True)
        args = "".join(f"<string>{a}</string>" for a in wk_executable() + ["daemon"])
        plist.write_text(LAUNCHD_PLIST.format(
            label=LAUNCHD_LABEL, args=args, path=os.environ.get("PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"),
            log=state_dir() / "launchd.log",
        ))
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        subprocess.run(["launchctl", "load", "-w", str(plist)], check=False)
        return plist
    unit_dir = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit = unit_dir / UNIT_NAME
    exe = " ".join(shlex.quote(p) for p in wk_executable())
    unit.write_text(SYSTEMD_UNIT.format(exe=exe, path=os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now", UNIT_NAME], check=False)
    return unit


def uninstall_service() -> None:
    if IS_MAC:
        plist = _launchd_plist()
        subprocess.run(["launchctl", "unload", "-w", str(plist)], capture_output=True)
        if plist.exists():
            plist.unlink()
        return
    subprocess.run(["systemctl", "--user", "disable", "--now", UNIT_NAME], check=False)
    unit = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "systemd" / "user" / UNIT_NAME
    if unit.exists():
        unit.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)


def service_status() -> str:
    if IS_MAC:
        out = subprocess.run(["launchctl", "list", LAUNCHD_LABEL], capture_output=True, text=True)
        return out.stdout or out.stderr or "not loaded"
    out = subprocess.run(["systemctl", "--user", "--no-pager", "status", UNIT_NAME], capture_output=True, text=True)
    return out.stdout or out.stderr
