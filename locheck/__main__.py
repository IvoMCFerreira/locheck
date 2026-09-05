"""Command line entry point.

    python -m locheck localisations_1_2_0.plist localisations_1_2_1.plist

Exit codes are chosen so this can drop straight into CI without a wrapper:
    0  nothing blocking
    1  at least one blocker (or --strict and anything flagged)
    2  a file could not be read at all
"""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console

from .engine import analyse
from .loader import LoadError, load
from .report import render


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="locheck",
        description="Check a candidate localisation plist against the version that is live.",
    )
    parser.add_argument("baseline", help="the .plist currently live (the source of truth)")
    parser.add_argument("candidate", help="the .plist about to ship")
    parser.add_argument(
        "--all",
        action="store_true",
        help="also show pre-existing problems that this release did not introduce",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON instead of the report (for CI)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero on any flagged finding, not just blockers",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    # These files contain Cyrillic, Japanese and accented Latin. On a Windows
    # console that still defaults to cp1252, printing them raises
    # UnicodeEncodeError, so force UTF-8 rather than mangling the evidence.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    try:
        baseline = load(args.baseline)
        candidate = load(args.candidate)
    except LoadError as exc:
        Console(stderr=True).print(f"[bold red]error[/] {exc}")
        return 2

    report = analyse(baseline, candidate)

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        render(report, show_all=args.all)

    if report.blockers:
        return 1
    if args.strict and report.flagged:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
