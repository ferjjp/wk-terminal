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
    p_d.add_argument("--test-popup", action="store_true", help="open the popup window exactly as a notification click would")
    sub.add_parser("config", help="create the config file with defaults and print its path")
    sub.add_parser("keys", help="list every action with its current key (rebind under [keys] in the config)")
    p_r = sub.add_parser("read", help="colour a Japanese text by what you know and list the kanji/words you don't")
    p_r.add_argument("file", nargs="?", default="-", help="file to read (default: stdin)")
    p_r.add_argument("--top", type=int, default=30, help="rows per table")
    p_r.add_argument("--no-vocab", action="store_true", help="kanji only, skip vocabulary matching")
    p_r.add_argument("--summary", action="store_true", help="skip the highlighted text, print only the summary")
    sub.add_parser("today", help="one line: reviews done today, goal, streak, due")
    p_x = sub.add_parser("export", help="CSV export of your history")
    p_x.add_argument("what", choices=["sessions", "items", "reviews", "stats"],
                     help="sessions: one row per session · items: every answer you gave · reviews: WaniKani's review log · stats: per-item accuracy + leech score")
    p_x.add_argument("-o", "--output", default="-", help="file path (default: stdout)")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - keep a trace even when the terminal window closes instantly
        import traceback
        from datetime import datetime

        from .config import state_dir

        try:
            with open(state_dir() / "crash.log", "a", encoding="utf-8") as f:
                f.write(f"\n--- {datetime.now():%Y-%m-%d %H:%M:%S} {' '.join(sys.argv)}\n")
                f.write(traceback.format_exc())
        except Exception:  # noqa: BLE001
            pass
        raise


def _main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.images:
        os.environ["WK_IMAGES"] = args.images
    command = args.command or "tui"

    from .config import MissingToken, api_token, config_file, db_path, settings, write_default_config

    if command == "config":
        f = write_default_config()
        print(f)
        return 0
    if command == "keys":
        from .keys import describe, unknown_overrides

        try:
            rows = describe()
        except RuntimeError as exc:
            print(f"config error: {exc}", file=sys.stderr)
            return 2
        print(f"{'action':<16}{'key':<14}{'default':<10}where: what")
        for action, cur, default, what, overridden in rows:
            print(f"{action:<16}{cur:<14}{default:<10}{what}" + ("   (overridden)" if overridden else ""))
        bad = unknown_overrides()
        if bad:
            print(f"\nunknown actions in [keys]: {', '.join(bad)}", file=sys.stderr)
        print(f"\nrebind in {config_file()} under [keys], e.g.  reviews = \"R\"")
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
        if command == "read":
            from . import reader

            return reader.main(db, args.file, top=args.top, no_vocab=args.no_vocab, summary_only=args.summary)
        if command == "today":
            st = db.goal_status(settings().goal_reviews_per_day)
            reviews, lessons, _ = core.due_counts()
            goal = f"/{st['goal']}" if st["goal"] else ""
            print(f"today {st['today']}{goal} reviews · streak {st['streak']} · {reviews} due · {lessons} lessons")
            return 0
        if command == "export":
            msg = core.export_csv(args.what, args.output)
            if msg:
                print(msg)
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
            if args.test_popup:
                from .config import settings as _settings

                return daemon.test_popup(_settings())
            return daemon.run(core, once=args.once)

        from .app import WKApp

        if command == "pop":
            from .config import state_dir

            result = WKApp(core, skip_sync=True, popup=True).run()
            with open(state_dir() / "popup.log", "a", encoding="utf-8") as f:
                f.write(f"wk pop finished: result={result!r} reviews_due={core.due_counts()[0]}\n")
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
