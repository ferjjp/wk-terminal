"""Is now a good moment to interrupt? Desktop idle time and do-not-disturb, best effort."""

from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger("wk.attention")


def idle_seconds() -> float | None:
    """Seconds since the last input event, or None when unknown."""
    try:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection

        conn = open_dbus_connection(bus="SESSION")
        try:
            addr = DBusAddress("/org/gnome/Mutter/IdleMonitor/Core", bus_name="org.gnome.Mutter.IdleMonitor",
                               interface="org.gnome.Mutter.IdleMonitor")
            reply = conn.send_and_get_reply(new_method_call(addr, "GetIdletime"))
            return float(reply.body[0]) / 1000.0
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - not GNOME, or no bus
        pass
    if shutil.which("xprintidle"):
        try:
            out = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=3).stdout.strip()
            return float(out) / 1000.0
        except Exception:  # noqa: BLE001
            pass
    return None


def do_not_disturb() -> bool | None:
    """True when the desktop is in do-not-disturb, None when unknown."""
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
