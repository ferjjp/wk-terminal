"""Desktop notifications over D-Bus (org.freedesktop.Notifications) with clickable actions.

notify-send's --action support depends on the libnotify build; talking to the bus directly
works on any freedesktop-compliant server (GNOME Shell, KDE, mako, dunst, …).
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger("wk.notify")

IFACE = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"


def send(title: str, body: str, actions: list[tuple[str, str]] | None = None, timeout_s: int = 120,
         icon: str = "accessories-dictionary", app: str = "WaniKani", urgency: int = 1) -> str:
    """Show a notification. With actions, block until one is invoked, the notification closes, or timeout.

    Returns the invoked action id ('' if none). An action named 'default' fires when the body is clicked.
    """
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
