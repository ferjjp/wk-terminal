import shutil

import wanikani_tui.platform as plat


def test_linux_defaults(monkeypatch):
    monkeypatch.setattr(plat, "IS_MAC", False)
    monkeypatch.setattr(plat, "IS_LINUX", True)
    monkeypatch.setattr(shutil, "which", lambda n: "/usr/bin/ghostty" if n == "ghostty" else None)
    assert plat.default_terminal_command().startswith("/usr/bin/ghostty") or plat.default_terminal_command().startswith("ghostty")
    assert plat.notification_backend() == "linux-dbus"
    assert plat.audio_players()[0][0] == "mpv"


def test_mac_defaults(monkeypatch):
    monkeypatch.setattr(plat, "IS_MAC", True)
    monkeypatch.setattr(plat, "IS_LINUX", False)
    monkeypatch.setattr(plat, "_mac_app_exists", lambda n: False)
    monkeypatch.setattr(shutil, "which", lambda n: None)
    assert plat.default_terminal_command() == "osascript-terminal"
    assert plat.notification_backend() == "none"
    assert plat.audio_players()[0][0] == "afplay"
    assert plat.font_candidates()[0].startswith("/System/Library/Fonts/")
    monkeypatch.setattr(shutil, "which", lambda n: f"/opt/homebrew/bin/{n}" if n in ("terminal-notifier", "kitty") else None)
    assert plat.notification_backend() == "mac-terminal-notifier"
    assert plat.default_terminal_command().startswith("kitty")


def test_popup_command_mac_terminal_app(monkeypatch):
    from wanikani_tui import daemon
    from wanikani_tui.config import Settings

    monkeypatch.setattr(daemon, "default_terminal_command", lambda: "osascript-terminal")
    monkeypatch.setattr(daemon, "wk_executable", lambda: ["/usr/local/bin/wk"])
    cmd = daemon.popup_command(Settings())
    assert cmd[0] == "osascript" and "wk pop" in cmd[2]
    monkeypatch.setattr(daemon, "default_terminal_command", lambda: "ghostty -e")
    assert daemon.popup_command(Settings()) == ["ghostty", "-e", "/usr/local/bin/wk", "pop"]
