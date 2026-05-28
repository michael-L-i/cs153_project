"""
CLI entry point for the founder research pipeline.

Usage:
    python -m newsletter.cli research "Peter Steinberger" "founder of OpenClaw"
    python -m newsletter.cli research "Paul Graham"
    python -m newsletter.cli write-newsletter <founder_id>
"""

from __future__ import annotations

import argparse
import sys


def cmd_research(args: argparse.Namespace) -> None:
    from newsletter.pipeline import run
    run(name=args.name, context=args.context or "")


def cmd_write_newsletter(args: argparse.Namespace) -> None:
    from newsletter.db import get_session_factory
    from newsletter.services.newsletter import write_newsletter

    session = get_session_factory()()
    try:
        markdown = write_newsletter(session, args.subject_id)
    finally:
        session.close()
    print(markdown)


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

    p = sub.add_parser("write-newsletter", help="Write a newsletter for a founder")
    p.add_argument("subject_id", help="Founder id (subject_id) to write a newsletter for")

    args = parser.parse_args()

    if args.command == "research":
        cmd_research(args)
    elif args.command == "write-newsletter":
        cmd_write_newsletter(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
