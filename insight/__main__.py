"""Command-line entry point: `insight serve` and `insight healthcheck`."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insight", description="Insight by 50N Systems")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run Insight")
    sub.add_parser("healthcheck", help="exit 0 if the running instance is healthy")
    args = parser.parse_args(argv)

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
