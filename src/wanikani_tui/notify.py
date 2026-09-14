"""Desktop notifications over D-Bus (org.freedesktop.Notifications) with clickable actions.

notify-send's --action support depends on the libnotify build; talking to the bus directly
works on any freedesktop-compliant server (GNOME Shell, KDE, mako, dunst, …).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

log = logging.getLogger("wk.notify")

IFACE = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"


def send(title: str, body: str, actions: list[tuple[str, str]] | None = None, timeout_s: int = 120,
         icon: str = "accessories-dictionary", app: str = "WaniKani", urgency: int = 1,
         click_command: list[str] | None = None) -> str:
    """Show a notification. With actions, block until one is invoked, the notification closes, or timeout.

    Returns the invoked action id ('' if none). An action named 'default' fires when the body is clicked.
    On macOS with terminal-notifier the click runs `click_command` directly and 'launched' is returned.
    """
    from .platform import notification_backend

    backend = notification_backend()
    if backend == "mac-terminal-notifier":
        return _mac_terminal_notifier(title, body, icon, click_command, bool(actions))
    if backend == "mac-osascript":
        return _mac_osascript(title, body)
    if backend != "linux-dbus":
        log.warning("no notification backend on this platform")
        return ""
    try:
        from jeepney import DBusAddress, MatchRule, message_bus, new_method_call
        from jeepney.io.blocking import Proxy, open_dbus_connection
    except ImportError:
        log.error("jeepney not installed")
        return ""
    try:
        conn = open_dbus_connection(bus="SESSION")
    except Exception as exc:  # noqa: BLE001
        log.error("cannot connect to the session bus: %s", exc)
        return ""
    try:
        addr = DBusAddress(PATH, bus_name=IFACE, interface=IFACE)
        flat: list[str] = []
        for aid, label in actions or []:
            flat += [aid, label]
        hints = {"urgency": ("y", urgency)}
        if icon.startswith("/"):
            hints["image-path"] = ("s", icon)
            icon = "file://" + icon
        msg = new_method_call(addr, "Notify", "susssasa{sv}i", (app, 0, icon, title, body, flat, hints, timeout_s * 1000))
        if actions:
            # subscribe before sending so we cannot miss a fast click
            rules = [
                MatchRule(type="signal", interface=IFACE, member="ActionInvoked", path=PATH),
                MatchRule(type="signal", interface=IFACE, member="NotificationClosed", path=PATH),
            ]
            bus = Proxy(message_bus, conn)
            for r in rules:
                bus.AddMatch(r)
        reply = conn.send_and_get_reply(msg)
        nid = reply.body[0]
        if not actions:
            return ""
        deadline = time.time() + timeout_s + 2
        while time.time() < deadline:
            try:
                sig = conn.receive(timeout=max(0.1, deadline - time.time()))
            except TimeoutError:
                break
            member = sig.header.fields.get(3)  # MEMBER
            if member == "ActionInvoked" and sig.body[0] == nid:
                return str(sig.body[1])
            if member == "NotificationClosed" and sig.body[0] == nid:
                return ""
        return ""
    except Exception as exc:  # noqa: BLE001
        log.error("notification failed: %s", exc)
        return ""
    finally:
        conn.close()


def _mac_terminal_notifier(title: str, body: str, icon: str, click_command: list[str] | None, clickable: bool) -> str:
    import shlex
    import subprocess

    cmd = ["terminal-notifier", "-title", "WaniKani", "-subtitle", title, "-message", body, "-group", "wanikani-tui"]
    if icon.startswith("/"):
        cmd += ["-contentImage", icon]
    if clickable and click_command:
        cmd += ["-execute", " ".join(shlex.quote(p) for p in click_command)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=15)
    except Exception as exc:  # noqa: BLE001
        log.error("terminal-notifier failed: %s", exc)
        return ""
    return "launched" if clickable and click_command else ""


def _mac_osascript(title: str, body: str) -> str:
    import subprocess

    def q(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    script = f'display notification "{q(body)}" with title "WaniKani" subtitle "{q(title)}"'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=15)
    except Exception as exc:  # noqa: BLE001
        log.error("osascript failed: %s", exc)
    return ""


class Listener:
    """Persistent subscriber for ActionInvoked / NotificationClosed, so a click on a notification that is
    still sitting in the desktop's tray minutes later still reaches us. Runs in its own thread."""

    def __init__(self) -> None:
        self._callbacks: dict[int, Callable[[str], None]] = {}
        self._lock = threading.Lock()
        self._conn = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        try:
            from jeepney import MatchRule, message_bus
            from jeepney.io.blocking import Proxy, open_dbus_connection
        except ImportError:
            return False
        try:
            self._conn = open_dbus_connection(bus="SESSION")
            bus = Proxy(message_bus, self._conn)
            bus.AddMatch(MatchRule(type="signal", interface=IFACE, member="ActionInvoked", path=PATH))
            bus.AddMatch(MatchRule(type="signal", interface=IFACE, member="NotificationClosed", path=PATH))
        except Exception as exc:  # noqa: BLE001
            log.error("notification listener could not connect: %s", exc)
            return False
        self._thread = threading.Thread(target=self._run, name="wk-notify-listener", daemon=True)
        self._thread.start()
        return True

    def _run(self) -> None:
        while True:
            try:
                sig = self._conn.receive()
            except Exception as exc:  # noqa: BLE001
                log.warning("notification listener stopped: %s", exc)
                return
            member = sig.header.fields.get(3)
            if member == "ActionInvoked":
                nid, action = sig.body[0], str(sig.body[1])
                with self._lock:
                    cb = self._callbacks.pop(nid, None)
                if cb:
                    try:
                        cb(action)
                    except Exception as exc:  # noqa: BLE001
                        log.error("notification callback failed: %s", exc)
            elif member == "NotificationClosed":
                with self._lock:
                    self._callbacks.pop(sig.body[0], None)

    def send(self, title: str, body: str, actions: list[tuple[str, str]], on_action: Callable[[str], None],
             icon: str = "accessories-dictionary", app: str = "WaniKani", timeout_s: int = 0, replaces: int = 0) -> int:
        """Show a notification and register the click handler. Returns the notification id (0 on failure).
        timeout_s=0 keeps it until dismissed; `replaces` closes/updates a previous one."""
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection

        flat: list[str] = []
        for aid, label in actions:
            flat += [aid, label]
        hints = {"urgency": ("y", 1)}
        if icon.startswith("/"):
            hints["image-path"] = ("s", icon)
            icon = "file://" + icon
        try:
            conn = open_dbus_connection(bus="SESSION")
            try:
                reply = conn.send_and_get_reply(new_method_call(
                    DBusAddress(PATH, bus_name=IFACE, interface=IFACE), "Notify", "susssasa{sv}i",
                    (app, replaces, icon, title, body, flat, hints, timeout_s * 1000)))
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            log.error("notification failed: %s", exc)
            return 0
        nid = int(reply.body[0])
        with self._lock:
            self._callbacks[nid] = on_action
        return nid

    def close(self, nid: int) -> None:
        if not nid:
            return
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection

        try:
            conn = open_dbus_connection(bus="SESSION")
            try:
                conn.send(new_method_call(DBusAddress(PATH, bus_name=IFACE, interface=IFACE), "CloseNotification", "u", (nid,)))
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            pass
        with self._lock:
            self._callbacks.pop(nid, None)
