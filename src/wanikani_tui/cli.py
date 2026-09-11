"""Command line entry point: `wk`."""

from __future__ import annotations

import argparse
import json
import os
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wk", description="WaniKani in your terminal")
    parser.add_argument("--full-sync", action="store_true", help="re-download everything instead of incremental sync")
    parser.add_argument("--no-sync", action="store_true", help="do not sync on startup (offline browsing)")
    parser.add_argument(
        "--images", default=None, choices=["auto", "tgp", "kitty", "sixel", "halfcell", "unicode", "none"],
        help="image rendering method (default from config; auto detects)",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("tui", help="open the full interface (default)")
    sub.add_parser("sync", help="sync the cache and send queued submissions")
    sub.add_parser("doctor", help="terminal image diagnostics")
    p_due = sub.add_parser("due", help="print how many reviews and lessons are waiting")
    p_due.add_argument("--format", choices=["plain", "short", "tmux", "json"], default="plain")
    p_due.add_argument("--sync", action="store_true", help="refresh assignments first")
    sub.add_parser("pop", help="a small window with one review (or lesson), for the daemon's notifications")
    p_d = sub.add_parser("daemon", help="background sync + desktop notifications")
    p_d.add_argument("action", nargs="?", default="run", choices=["run", "install", "uninstall", "status"])
    p_d.add_argument("--once", action="store_true", help="one cycle, then exit (for testing)")
    sub.add_parser("config", help="create the config file with defaults and print its path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.images:
        os.environ["WK_IMAGES"] = args.images
    command = args.command or "tui"

    from .config import MissingToken, api_token, config_file, db_path, settings, write_default_config

    if command == "config":
        f = write_default_config()
        print(f)
        return 0
    if command == "doctor":
        from .doctor import run

        return run()

    try:
        settings()
    except RuntimeError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    try:
        token = api_token()
    except MissingToken as exc:
        print(exc, file=sys.stderr)
        return 2

    from .api import WaniKani
    from .core import Core
    from .db import Database

    api = WaniKani(token)
    db = Database(db_path())
    core = Core(api, db)
    try:
        if command == "sync":
            counts = core.sync(full=args.full_sync or core.needs_full_sync(), progress=lambda m: print(m, flush=True))
            print(", ".join(f"{k}: {v}" for k, v in counts.items()))
            return 0
        if command == "due":
            if args.sync and not core.needs_full_sync():
                core.sync(light=True)
            reviews, lessons, next_at = core.due_counts()
            if args.format == "json":
                print(json.dumps({"reviews": reviews, "lessons": lessons, "next_review_at": next_at.isoformat() if next_at else None}))
            elif args.format == "short":
                print(f"{reviews}/{lessons}")
            elif args.format == "tmux":
                if reviews:
                    print(f"#[fg=colour39]鰐 {reviews}#[default]" + (f" +{lessons}" if lessons else ""))
                elif lessons:
                    print(f"鰐 0 +{lessons}")
                else:
                    print("鰐 0" + (f" ({next_at.astimezone().strftime('%H:%M')})" if next_at else ""))
            else:
                print(f"{reviews} reviews, {lessons} lessons" + (f"; next review {next_at.astimezone().strftime('%a %H:%M')}" if next_at and not reviews else ""))
            return 0
        if command == "daemon":
            from . import daemon

            if args.action == "install":
                unit = daemon.install_service()
                from .platform import IS_MAC

                if IS_MAC:
                    print(f"installed launch agent {unit}\nlogs: {daemon.state_dir() / 'daemon.log'}")
                else:
                    print(f"installed and started {daemon.UNIT_NAME} ({unit})\nlogs: journalctl --user -u {daemon.UNIT_NAME} -f")
                return 0
            if args.action == "uninstall":
                daemon.uninstall_service()
                print("service removed")
                return 0
            if args.action == "status":
                print(daemon.service_status())
                return 0
            return daemon.run(core, once=args.once)

        from .app import WKApp

        if command == "pop":
            result = WKApp(core, skip_sync=True, popup=True).run()
            if result == "full":
                WKApp(core).run()
            return 0
        WKApp(core, full_sync=args.full_sync, skip_sync=args.no_sync).run()
        return 0
    finally:
        db.close()
        api.close()


if __name__ == "__main__":
    sys.exit(main())
