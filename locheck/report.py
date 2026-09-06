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

    # Shortened the same way as the header: auto-discovery hands back an
    # absolute path, and a full Windows path pushes the line number - the
    # part the reader is here for - off the edge of the card.
    location = _friendly(candidate_path) + (f":{finding.line}" if finding.line else "")
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


def _is_rollback(report: Report) -> bool:
    """Whether the candidate is an older release than the file it is replacing.

    Legitimate - it answers "what would shipping the old file undo?" - but it
    inverts how the whole report reads, because the fixes and regressions are
    those of going backwards. Worth saying out loud rather than leaving the
    reader to work out why every finding looks upside down.
    """
    from .discover import version_of

    live = version_of(Path(report.baseline_path))
    candidate = version_of(Path(report.candidate_path))
    return bool(live and candidate and candidate < live)


def _header(report: Report, note: str | None = None) -> Panel:
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
    if _is_rollback(report):
        grid.add_row(
            "",
            Text("rollback: the candidate is the OLDER release", style="bold yellow")
            + Text("  -  findings describe what shipping it would undo", style="dim"),
            "",
        )

    # The note goes in the title rather than on a row of its own: naming two
    # files out of ten without mentioning the other eight invites the reader to
    # assume these were the only candidates. It has to be said; it does not need
    # a line, and the whole summary has to fit a 30-line console.
    title = "Localisation release check"
    if note:
        title += "   " + note
    return Panel(grid, title=title, title_align="left",
                 box=box.ROUNDED, padding=(0, 1))


def _footer(report: Report, hidden: int) -> Group:
    """Which two files were compared, and the counts, in two lines.

    This was four boxed tiles, which is four lines to carry four numbers. The
    whole summary has to fit a console opened by double-clicking - about thirty
    lines - and going over means the header scrolls off the top, taking the names
    of the files being compared with it.

    So the pair is named here as well, at the bottom where the reader is already
    looking. It is the one piece of context that makes the rest of the report
    mean anything: a report about the wrong two files reads exactly like a report
    about the right two.
    """
    fixed = sum(1 for f in report.findings if f.severity is Severity.RESOLVED)
    stats = [
        ("strings compared", report.strings_compared, "white"),
        ("changed", report.strings_changed, "white"),
        ("need action", len(report.flagged), "red" if report.flagged else "green"),
        ("fixed", fixed, "green"),
    ]
    if hidden:
        stats.append(("pre-existing", hidden, "cyan"))

    # Kept short enough to survive an 80-column console. "(about to ship)" read
    # better but pushed the line to 81 characters, so it wrapped onto a second
    # line reading just "ship)" - which is worse than a terser label.
    pair = (
        Text("  ")
        + Text(_friendly(report.baseline_path), style="bold")
        + Text(" (live)", style="dim")
        + Text("  ->  ", style="dim")
        + Text(_friendly(report.candidate_path), style="bold")
        + Text(" (new)", style="dim")
    )

    counts = Text("  ")
    for index, (label, value, colour) in enumerate(stats):
        if index:
            counts.append("   ", style="dim")
        counts.append(str(value), style=f"bold {colour}")
        counts.append(" " + label, style="dim")

    return Group(pair, counts)


def _shown(report: Report, show_all: bool):
    """The findings to display, numbered, plus how many were held back."""
    visible = [f for f in report.findings if show_all or f.severity is not Severity.INFO]
    hidden = len(report.findings) - len(visible)
    numbers = {id(f): i for i, f in enumerate(visible, start=1)}
    return visible, hidden, numbers


def render_summary(
    report: Report,
    console: Console,
    show_all: bool = False,
    note: str | None = None,
    with_footer: bool = True,
) -> int:
    """The ship/no-ship view. Returns how many findings have detail to expand."""
    console.print(_header(report, note))
    console.print(_verdict(report))

    if report.warnings:
        console.print()
        console.print(Panel(
            Group(*[Text("- " + w) for w in report.warnings]),
            title="Input warnings - recovered, but worth a look",
            title_align="left", box=box.ROUNDED, style="yellow", padding=(0, 2),
        ))

    visible, hidden, numbers = _shown(report, show_all)
    if visible:
        console.print(_summary_table(visible, numbers))

    if with_footer:
        console.print()
        console.print(_footer(report, hidden))
    return len(visible)


def render_details(report: Report, console: Console, show_all: bool = False) -> None:
    """A card per finding: where it is, what it should say, and what to do.

    Ordered *least* severe first, which is the opposite of the summary table
    above it. That is deliberate. The table is for scanning, so it leads with
    the worst. The cards are read after deciding to act, and a terminal leaves
    you at the bottom of what it printed - so the blockers go last, where the
    cursor already is, instead of scrolled off the top.

    The verdict is restated underneath them, so the final line on screen is the
    ship/no-ship call rather than the last card that happened to print.
    """
    visible, _, numbers = _shown(report, show_all)
    for severity in reversed(list(Severity)):
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

    if visible:
        console.print()
        console.print(_verdict(report))


def render(
    report: Report,
    console: Console | None = None,
    show_all: bool = False,
    summary_only: bool = False,
    note: str | None = None,
) -> None:
    """The whole report at once, for anything that is not a live terminal."""
    console = console or Console()
    render_summary(report, console, show_all, note, with_footer=True)
    if not summary_only:
        render_details(report, console, show_all)
