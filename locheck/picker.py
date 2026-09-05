"""Choosing which two releases to compare, from the ones on disk.

The tool defaults to the newest two versions, which is right most of the time
and wrong in one common case: the second-newest file is not always what is
actually live. A version can be built and never shipped, or a release can be
rolled back, and nothing in the file names records that. Only the person
running the check knows.

So rather than trying to be cleverer about the guess, this lets them correct it
without retyping paths or knowing where the files live.
"""

from __future__ import annotations

from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .discover import families_in, family_of, version_of


def versions_like(path: Path) -> list[Path]:
    """Every release of the same family as `path`, oldest first.

    Same grouping the automatic pick uses, so the list offered here is exactly
    the set of files that could sensibly be compared - a `gameconfig_9_0_0.plist`
    in the folder is not one of the options.
    """
    return families_in(path.parent).get(family_of(path), [])


def _table(versions: list[Path], live: Path, candidate: Path) -> Table:
    table = Table(box=box.SIMPLE, header_style="bold", padding=(0, 1))
    table.add_column("#", justify="right", width=3, style="dim")
    table.add_column("VERSION", width=10)
    table.add_column("FILE")
    table.add_column("", style="dim")

    for number, path in enumerate(versions, start=1):
        found = version_of(path)
        marker = ""
        if path == live:
            marker = "currently the live side"
        elif path == candidate:
            marker = "currently the candidate"
        table.add_row(
            str(number),
            Text(".".join(str(p) for p in found) if found else "?", style="bold"),
            path.name,
            marker,
        )
    return table


def choose(live: Path, candidate: Path, console: Console) -> tuple[Path, Path] | None:
    """Ask which two releases to compare. Returns None to keep the current pair."""
    versions = versions_like(candidate)
    if len(versions) < 2:
        console.print()
        console.print(Text("  Only one version of this file here - nothing to choose between.",
                           style="yellow"))
        return None

    console.print()
    console.print(Panel(
        _table(versions, live, candidate),
        title="Versions in this folder",
        title_align="left",
        box=box.ROUNDED,
        padding=(0, 1),
    ))
    console.print(
        Text("  Enter two numbers, live one first", style="dim")
        + Text("  (e.g. ", style="dim")
        + Text("1 " + str(len(versions)), style="bold cyan")
        + Text("), or press Enter to keep the current pair.", style="dim")
    )

    for _ in range(3):
        try:
            answer = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return None

        if not answer:
            return None

        chosen = _parse(answer, len(versions))
        if chosen is None:
            console.print(
                Text("  Two numbers between 1 and " + str(len(versions))
                     + ", separated by a space. Enter alone keeps the current pair.",
                     style="yellow")
            )
            continue

        first, second = chosen
        return versions[first - 1], versions[second - 1]

    return None


def _parse(answer: str, count: int) -> tuple[int, int] | None:
    """Read '2 4', '2,4' or '2-4' as a pair of valid, distinct indices."""
    parts = [p for p in answer.replace(",", " ").replace("-", " ").split() if p]
    if len(parts) != 2:
        return None
    try:
        first, second = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (1 <= first <= count and 1 <= second <= count):
        return None
    if first == second:
        return None  # comparing a file against itself says nothing
    return first, second
