"""Command-line entry point: `insight serve` and `insight healthcheck`."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insight", description="Insight by 50N Systems")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run Insight")
    sub.add_parser("healthcheck", help="exit 0 if the running instance is healthy")
    sub.add_parser("backups", help="list the automatic pre-migration database backups")
    restore = sub.add_parser(
        "restore-backup", help="restore a database backup (Insight must be stopped)"
    )
    restore.add_argument("name", help="backup file name, as listed by 'insight backups'")
    args = parser.parse_args(argv)

    if args.command in ("backups", "restore-backup"):
        from insight.settings import Settings
        from insight.storage.db import Database

        db = Database(Settings.from_env().data_dir / "insight.db")
        if args.command == "backups":
            for path in db.backups():
                print(path.name)
            return 0
        db.restore(args.name)
        print(f"Restored {args.name}. Start Insight with the matching version.")
        return 0

    if args.command == "serve":
        from insight.server import serve

        serve()
        return 0
    if args.command == "healthcheck":
        from insight.server import healthcheck

        return healthcheck()
    return 2


if __name__ == "__main__":
    sys.exit(main())
