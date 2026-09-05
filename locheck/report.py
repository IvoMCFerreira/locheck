"""Renders a Report for a human with fifteen minutes and a ship/no-ship call.

The output is deliberately two-tier, because two different questions get asked
of it and they want different shapes:

  1. "Do I ship?"        -> the verdict banner and the summary table. Scannable
                            in seconds, one row per finding, worst first.
  2. "How do I fix it?"  -> a detail card per finding: the exact file and line,
                            the en-US source to mirror, live vs new with the
                            offending characters highlighted, and an imperative.

Design rules:

  * The verdict is the first thing on screen. Everything else supports it.
  * Pre-existing problems are hidden by default. They are real, but they are
    already live, so putting them in front of a releaser at release time is
    exactly the noise that trains people to ignore the tool.
  * Fixes are shown, in green. They are the evidence that a changed string is
    not automatically a risky one.
"""

from __future__ import annotations

import re
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .model import Finding, Report, Severity

STYLES = {
    Severity.BLOCKER: ("BLOCKER", "bold white on red"),
    Severity.HIGH: ("HIGH", "bold dark_orange"),
    Severity.MEDIUM: ("MEDIUM", "bold yellow"),
    Severity.LOW: ("LOW", "yellow"),
    Severity.INFO: ("EXISTING", "cyan"),
    Severity.RESOLVED: ("FIXED", "bold green"),
}

HEADINGS = {
    Severity.BLOCKER: "Do not ship until these are resolved",
    Severity.HIGH: "Confirm these are intentional",
    Severity.MEDIUM: "Likely visible to players",
    Severity.LOW: "Cosmetic",
    Severity.INFO: "Already live - not caused by this release",
    Severity.RESOLVED: "Fixed by this release - no action needed",
}

_UUID_KEY = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-", re.IGNORECASE)
_MAX_EXCERPT = 150


def _short_key(key: str | None) -> str:
    """UUID keys shorten to their first block; human-readable keys stay readable."""
    if not key:
        return "—"
    if _UUID_KEY.match(key):
        return key.split("-", 1)[0]
    return key if len(key) <= 10 else key[:9] + "…"


def _excerpt(text: str, spans=(), limit: int = _MAX_EXCERPT) -> Text:
    """A window of the string with the offending characters marked.

    Long strings are windowed around the first problem rather than truncated from
    the left, so the thing being complained about is always on screen. The raw
    `\\n` escapes are left exactly as they appear in the file - this text is meant
    to be matched against what the reader sees in their editor.
    """
    if not text:
        return Text("(empty)", style="italic dim")

    offset = 0
    if len(text) > limit:
        anchor = spans[0][0] if spans else 0
        offset = max(0, min(anchor - limit // 3, len(text) - limit))
        text_window = text[offset : offset + limit]
    else:
        text_window = text

    rendered = Text(text_window, overflow="fold")
    for start, end in spans:
        s, e = start - offset, end - offset
        if 0 <= s < len(text_window):
            rendered.stylize("bold white on red", s, min(e, len(text_window)))

    if offset:
        rendered = Text("…", style="dim") + rendered
    if offset + len(text_window) < len(text):
        rendered.append("…", style="dim")
    return rendered


# --------------------------------------------------------------------------
# tier 1: the summary table
# --------------------------------------------------------------------------


def _summary_table(findings: list[Finding], numbers: dict[int, int]) -> Table:
    table = Table(
        box=box.SIMPLE_HEAVY,
        expand=True,
        header_style="bold",
        row_styles=["", "on grey11"],
        padding=(0, 1),
    )
    table.add_column("#", justify="right", width=3, style="dim")
    table.add_column("SEVERITY", width=8, no_wrap=True)
    table.add_column("LINE", justify="right", width=5, style="dim")
    table.add_column("TEXT ID", width=10, no_wrap=True)
    table.add_column("LANG", width=5, no_wrap=True)
    table.add_column("ISSUE", ratio=1)

    for finding in findings:
        label, style = STYLES[finding.severity]
        table.add_row(
            str(numbers[id(finding)]),
            Text(label, style=style),
            str(finding.line) if finding.line else "—",
            Text(_short_key(finding.key), style="dim"),
            Text(finding.lang or "—", style="bold" if finding.lang else "dim"),
            Text(finding.title)
            + (Text(f"  +{len(finding.also)} more", style="dim") if finding.also else Text("")),
        )
    return table


# --------------------------------------------------------------------------
# tier 2: the detail cards
# --------------------------------------------------------------------------


def _card(finding: Finding, number: int, candidate_path: str) -> Panel:
    label, style = STYLES[finding.severity]

    where = Table.grid(padding=(0, 2))
    where.add_column(style="dim", justify="right", width=8)
    where.add_column(overflow="fold")

    location = candidate_path + (f":{finding.line}" if finding.line else "")
    where.add_row("file", Text(location, style="bold cyan"))
    if finding.key:
        where.add_row("text id", Text(finding.key, style="dim"))
    if finding.lang:
        where.add_row("language", Text(finding.lang, style="bold"))

    body: list = [where, Text(""), Text(finding.detail)]

    strings = Table.grid(padding=(0, 2))
    strings.add_column(style="dim", justify="right", width=8)
    strings.add_column(overflow="fold")

    shown = False
    # For a fix, the interesting characters are in the OLD string; for a break,
    # in the new one. Highlight whichever one the spans actually describe.
    fixed = finding.severity is Severity.RESOLVED
    if finding.reference is not None and finding.lang != "en-US":
        strings.add_row("en-US", _excerpt(finding.reference))
        shown = True
    if finding.before is not None:
        strings.add_row("live", _excerpt(finding.before, finding.spans if fixed else ()))
        shown = True
    if finding.after is not None:
        strings.add_row("new", _excerpt(finding.after, () if fixed else finding.spans))
        shown = True

    if shown:
        body += [Text(""), strings]

    if finding.also:
        extra = Table.grid(padding=(0, 1))
        extra.add_column(width=9, no_wrap=True)
        extra.add_column(overflow="fold")
        for other in finding.also:
            other_label, other_style = STYLES[other.severity]
            extra.add_row(Text(other_label, style=other_style), Text(other.detail))
        body += [
            Text(""),
            Text("also wrong with this string:", style="dim"),
            extra,
        ]

    if finding.action:
        # A grid rather than a prefixed Text, so a wrapped action hangs under
        # itself instead of running back to the left margin.
        action = Table.grid(padding=(0, 1))
        action.add_column(width=1, style=style)
        action.add_column(overflow="fold")
        action.add_row("▸", Text(finding.action, style="bold"))
        body += [Text(""), action]

    title = Text(f" {number} ", style=style) + Text(f" {finding.title}", style="bold")
    return Panel(Group(*body), title=title, title_align="left", box=box.ROUNDED, padding=(0, 2))


# --------------------------------------------------------------------------


def _verdict(report: Report) -> Panel:
    blockers = len(report.blockers)
    high = sum(1 for f in report.findings if f.severity is Severity.HIGH)

    if blockers:
        headline = f"DO NOT SHIP  ·  {blockers} blocker{'s' if blockers != 1 else ''}"
        if high:
            headline += f"  ·  {high} to confirm"
        style = "bold white on red"
    elif high:
        headline = f"REVIEW BEFORE SHIPPING  ·  {high} change{'s' if high != 1 else ''} to confirm"
        style = "bold black on yellow"
    else:
        headline = "SAFE TO SHIP  ·  nothing flagged"
        style = "bold white on green"

    return Panel(Text(headline, style=style, justify="center"), box=box.HEAVY, style=style)


def _friendly(path_text: str) -> str:
    """Show a path the way the reader typed it, not the way the OS stores it.

    Auto-discovery hands back absolute paths, and a full Windows path wraps the
    header onto three lines for no benefit - the reader is standing in that
    directory.
    """
    path = Path(path_text)
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return path.name


def _header(report: Report, auto_detected: int = 0) -> Panel:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", justify="right")
    grid.add_column()
    grid.add_column(style="dim")
    grid.add_row(
        "live",
        Text(_friendly(report.baseline_path), style="bold"),
        f"version {report.baseline_version}",
    )
    grid.add_row(
        "candidate",
        Text(_friendly(report.candidate_path), style="bold"),
        f"version {report.candidate_version}",
    )
    if auto_detected:
        # Say how many were on disk. Naming two files out of ten without
        # mentioning the other eight invites the reader to assume these were the
        # only candidates - and their idea of what is live may not be the newest
        # file sitting in the folder.
        note = "newest two of " + str(auto_detected) + " versions found here"
        grid.add_row("", Text(note, style="dim italic"), "")
    return Panel(grid, title="Localisation release check", title_align="left",
                 box=box.ROUNDED, padding=(0, 1))


def _footer(report: Report, hidden: int) -> Table:
    fixed = sum(1 for f in report.findings if f.severity is Severity.RESOLVED)
    stats = [
        ("strings compared", report.strings_compared, "white"),
        ("changed", report.strings_changed, "white"),
        ("need action", len(report.flagged), "red" if report.flagged else "green"),
        ("fixed", fixed, "green"),
    ]
    if hidden:
        stats.append(("pre-existing", hidden, "cyan"))

    # A ratio grid rather than Columns: Columns sizes to content, which leaves
    # the tiles ragged and wrapping on a narrow terminal.
    row = Table.grid(expand=True)
    tiles = []
    for label, value, colour in stats:
        row.add_column(ratio=1)
        tile = Table.grid(expand=True)
        tile.add_column(justify="center")
        tile.add_row(Text(str(value), style=f"bold {colour}"))
        tile.add_row(Text(label, style="dim"))
        tiles.append(Panel(tile, box=box.ROUNDED, padding=(0, 1)))
    row.add_row(*tiles)
    return row


def render(
    report: Report,
    console: Console | None = None,
    show_all: bool = False,
    summary_only: bool = False,
    auto_detected: int = 0,
) -> None:
    console = console or Console()

    console.print(_header(report, auto_detected))
    console.print(_verdict(report))

    if report.warnings:
        console.print()
        console.print(Panel(
            Group(*[Text("• " + w) for w in report.warnings]),
            title="Input warnings — recovered, but worth a look",
            title_align="left", box=box.ROUNDED, style="yellow", padding=(0, 2),
        ))

    visible = [
        f for f in report.findings
        if show_all or f.severity is not Severity.INFO
    ]
    hidden = len(report.findings) - len(visible)

    if not visible:
        console.print()
        console.print(_footer(report, hidden))
        return

    numbers = {id(f): i for i, f in enumerate(visible, start=1)}

    console.print()
    console.print(_summary_table(visible, numbers))

    if not summary_only:
        for severity in Severity:
            group = [f for f in visible if f.severity is severity]
            if not group:
                continue
            label, style = STYLES[severity]
            console.print()
            console.print(
                Text(f" {label} ", style=style)
                + Text(f"  {HEADINGS[severity]}", style="bold")
                + Text(f"  ({len(group)})", style="dim")
            )
            for finding in group:
                console.print()
                console.print(_card(finding, numbers[id(finding)], report.candidate_path))

    console.print()
    console.print(_footer(report, hidden))
