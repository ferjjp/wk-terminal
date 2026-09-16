"""Is now a good moment to interrupt? Desktop idle time and do-not-disturb, best effort."""

from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger("wk.attention")


def _dbus_idle_ms(path: str, bus_name: str, interface: str, method: str) -> float | None:
    from jeepney import DBusAddress, new_method_call
    from jeepney.io.blocking import open_dbus_connection

    conn = open_dbus_connection(bus="SESSION")
    try:
        reply = conn.send_and_get_reply(new_method_call(DBusAddress(path, bus_name=bus_name, interface=interface), method))
        return float(reply.body[0])
    finally:
        conn.close()


def idle_seconds() -> float | None:
    """Seconds since the last input event, or None when unknown.

    Probes, in order: GNOME (Mutter idle monitor), KDE and other freedesktop screensaver implementations
    (GetSessionIdleTime), macOS (IOKit HIDIdleTime), then xprintidle on X11."""
    import sys

    if sys.platform.startswith("linux"):
        for args in (
            ("/org/gnome/Mutter/IdleMonitor/Core", "org.gnome.Mutter.IdleMonitor", "org.gnome.Mutter.IdleMonitor", "GetIdletime"),
            ("/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver", "org.freedesktop.ScreenSaver", "GetSessionIdleTime"),
            ("/ScreenSaver", "org.freedesktop.ScreenSaver", "org.freedesktop.ScreenSaver", "GetSessionIdleTime"),
        ):
            try:
                ms = _dbus_idle_ms(*args)
                # GetSessionIdleTime answers in seconds on KDE; GNOME's GetIdletime in milliseconds
                return ms / 1000.0 if args[3] == "GetIdletime" else ms
            except Exception:  # noqa: BLE001
                continue
    elif sys.platform == "darwin" and shutil.which("ioreg"):
        try:
            out = subprocess.run(["ioreg", "-c", "IOHIDSystem", "-d", "4"], capture_output=True, text=True, timeout=5).stdout
            for line in out.splitlines():
                if "HIDIdleTime" in line:
                    return int(line.split("=")[-1].strip()) / 1_000_000_000
        except Exception:  # noqa: BLE001
            pass
    if shutil.which("xprintidle"):
        try:
            out = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=3).stdout.strip()
            return float(out) / 1000.0
        except Exception:  # noqa: BLE001
            pass
    return None


def do_not_disturb() -> bool | None:
    """True when the desktop is in do-not-disturb, None when unknown (GNOME only for now)."""
    if shutil.which("gsettings"):
        try:
            out = subprocess.run(["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"],
                                 capture_output=True, text=True, timeout=3).stdout.strip()
            if out in ("true", "false"):
                return out == "false"
        except Exception:  # noqa: BLE001
            pass
    return None


def good_moment(active_idle_seconds: float, respect_dnd: bool = True) -> tuple[bool, str]:
    """(ok, reason). Interrupt only when someone is at the keyboard and not in DND."""
    if respect_dnd and do_not_disturb():
        return False, "do not disturb"
    idle = idle_seconds()
    if idle is None:
        return True, "idle time unknown"
    if idle > active_idle_seconds:
        return False, f"away ({int(idle // 60)} min idle)"
    return True, f"active ({int(idle)} s idle)"
