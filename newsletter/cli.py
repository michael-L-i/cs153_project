"""
CLI entry point for the founder research pipeline.

Usage:
    python -m newsletter.cli research "Peter Steinberger" "founder of OpenClaw"
    python -m newsletter.cli research "Paul Graham"
"""

from __future__ import annotations

import argparse
import sys


def cmd_research(args: argparse.Namespace) -> None:
    from newsletter.pipeline import run
    run(name=args.name, context=args.context or "")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="newsletter",
        description="Founder research pipeline — give a name, get a knowledge base.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("research", help="Run the full pipeline for a founder")
    p.add_argument("name", help='Founder full name  e.g. "Peter Steinberger"')
    p.add_argument(
        "context",
        nargs="?",
        default="",
        help='Optional context to help Exa find the right person  e.g. "founder of OpenClaw"',
    )

    args = parser.parse_args()

    if args.command == "research":
        cmd_research(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
