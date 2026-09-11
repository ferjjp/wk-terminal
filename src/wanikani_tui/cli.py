"""Command line entry point: `wk`."""

from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wk", description="WaniKani in your terminal")
    parser.add_argument("command", nargs="?", default="tui", choices=["tui", "sync", "doctor"], help="tui (default), sync, or doctor (terminal image diagnostics)")
    parser.add_argument("--full-sync", action="store_true", help="re-download everything instead of incremental sync")
    parser.add_argument("--no-sync", action="store_true", help="do not sync on startup (offline browsing)")
    parser.add_argument(
        "--images", default=os.environ.get("WK_IMAGES", "auto"),
        choices=["auto", "tgp", "kitty", "sixel", "halfcell", "unicode", "none"],
        help="image rendering method (auto detects; use tgp inside tmux if detection fails)",
    )
    args = parser.parse_args(argv)
    os.environ["WK_IMAGES"] = args.images

    if args.command == "doctor":
        from .doctor import run

        return run()

    from .api import WaniKani
    from .config import MissingToken, api_token, db_path
    from .db import Database

    try:
        token = api_token()
    except MissingToken as exc:
        print(exc, file=sys.stderr)
        return 2

    api = WaniKani(token)
    db = Database(db_path())
    try:
        if args.command == "sync":
            from .sync import needs_full_sync, sync

            counts = sync(api, db, full=args.full_sync or needs_full_sync(db), progress=lambda m: print(m, flush=True))
            print(", ".join(f"{k}: {v}" for k, v in counts.items()))
            return 0

        from .app import WKApp

        WKApp(api, db, full_sync=args.full_sync, skip_sync=args.no_sync).run()
        return 0
    finally:
        db.close()
        api.close()


if __name__ == "__main__":
    sys.exit(main())
