"""Command line entry point.

Designed so the common case needs no arguments and no memory of which file goes
first. This is run by releasers and producers, not only by engineers, and the
cost of a fiddly invocation is that people stop running it:

    locheck                       compare the two newest versions here
    locheck new.plist             compare that against the release it replaces
    locheck live.plist new.plist  spell both out

At a terminal the summary is shown first and the per-finding detail waits behind
a keypress. Redirected, piped or asked for --json it prints everything at once
and never prompts - a prompt in a CI log is a hang, not a feature.

Whatever gets chosen is printed above the report, so a wrong guess is obvious
rather than silently producing a confident report about the wrong pair.

Exit codes are chosen so this can drop straight into CI without a wrapper:
    0  nothing blocking
    1  at least one blocker (or --strict and anything flagged)
    2  the files could not be found or read
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .discover import DiscoveryError, candidates_in, find_baseline_for, find_pair
from .engine import analyse
from .loader import LoadError, load
from .interactive import read_key, someone_is_watching
from .picker import choose, versions_like
from .report import render, render_details, render_summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="locheck",
        description=(
            "Check a localisation file against the version that is live, and say "
            "whether it is safe to ship."
        ),
        epilog=(
            "Run with no arguments in the folder holding your .plist files and it "
            "will compare the two newest versions."
        ),
    )
    parser.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help=(
            "nothing: use the two newest files here. One file: compare it against "
            "the release it replaces. Two files: the live one first."
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="also show problems that were already live before this release",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="just the table, and do not offer to expand it",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="print the full report immediately, without waiting for a keypress",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="machine-readable output, for CI",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero on anything flagged, not just blockers",
    )
    return parser


def resolve(files: list[str]) -> tuple[Path, Path, int]:
    """Turn 0, 1 or 2 arguments into (live, candidate, versions_considered).

    `versions_considered` is 0 when both paths were given explicitly, and
    otherwise how many releases were on disk to choose between - so the report
    can say "newest two of ten" rather than quietly naming two of them.
    """
    if len(files) >= 2:
        return Path(files[0]), Path(files[1]), 0
    if len(files) == 1:
        candidate = Path(files[0])
        if not candidate.exists():
            raise DiscoveryError("no such file: " + str(candidate))
        baseline = find_baseline_for(candidate)
        return baseline, candidate, len(candidates_in(candidate.parent))
    found = find_pair(Path.cwd())
    return found.live, found.candidate, found.considered


def _legend(console: Console, *, expandable: bool) -> None:
    """A key legend rather than a sentence.

    Prose that says "press any key, or V, or Esc" contradicts itself. A legend
    lists what each key does and lets the reader see the exceptions at a glance.
    """
    row = Table.grid(padding=(0, 2))
    for _ in range(3):
        row.add_column()

    def option(key: str, what: str) -> Text:
        return Text(" " + key + " ", style="reverse") + Text(" " + what, style="dim")

    cells = [option("Esc", "close"), option("V", "compare other versions")]
    if expandable:
        cells.append(option("any other key", "show the detail"))
    row.add_row(*cells)

    console.print()
    console.print(row)


def _interactive(live_path, candidate_path, considered: int, args):
    """Show the verdict, then the detail or a different pair, on request.

    A releaser deciding whether to ship needs the table. A releaser who has
    decided to fix something needs the cards. Printing both every time buries
    the first in the second, so this shows the summary and waits.

    It loops, because the automatic pick can be wrong in a way only the person
    running it knows about - a version that was built but never shipped means
    the second-newest file is not what is live. Rather than making them retype
    paths, V lists what is on disk and lets them correct it.

    Returns the report that was last on screen, so the exit code describes what
    the reader actually saw.
    """
    console = Console()
    report = analyse(load(live_path), load(candidate_path))
    showing_detail = False
    count = 0

    while True:
        if showing_detail:
            render_details(report, console, args.all)
        else:
            count = render_summary(report, console, args.all, considered)

        _legend(console, expandable=not showing_detail and bool(count))

        try:
            key = read_key()
        except KeyboardInterrupt:
            console.print()
            return report

        if key == "\x1b":  # Esc, and only Esc
            return report

        if key in ("v", "V"):
            chosen = choose(live_path, candidate_path, console)
            console.print()
            if chosen is not None:
                live_path, candidate_path = chosen
                try:
                    report = analyse(load(live_path), load(candidate_path))
                except LoadError as exc:
                    console.print(Text("  " + str(exc), style="bold red"))
                    return report
                considered = len(versions_like(candidate_path))
            showing_detail = False  # a new pair starts from its verdict
            continue

        if showing_detail or not count:
            return report

        showing_detail = True
        console.print()


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

    errors = Console(stderr=True)

    try:
        live_path, candidate_path, considered = resolve(args.files)
    except DiscoveryError as exc:
        errors.print(Text("Could not work out which files to compare.", style="bold red"))
        errors.print(Text(str(exc), style="yellow"))
        errors.print(
            Text("\nUsage:  locheck [live.plist] [new.plist]", style="dim")
        )
        return 2

    try:
        baseline = load(live_path)
        candidate = load(candidate_path)
    except LoadError as exc:
        errors.print(Text("error  ", style="bold red") + Text(str(exc)))
        return 2

    report = analyse(baseline, candidate)

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    elif not args.summary and not args.details and someone_is_watching():
        # The reader can switch to a different pair from inside, so the exit
        # code has to describe the comparison they ended on, not the first one.
        report = _interactive(live_path, candidate_path, considered, args)
    else:
        # `guessed` is surfaced inside the header rather than on a line of its
        # own: a silently mis-picked pair produces a report that looks entirely
        # plausible and is about the wrong release, so it has to be visible -
        # but it does not need a line to itself.
        render(
            report,
            console=Console(),
            show_all=args.all,
            summary_only=args.summary,
            auto_detected=considered,
        )

    if report.blockers:
        return 1
    if args.strict and report.flagged:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
