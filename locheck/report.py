"""Renders a Report for a human with fifteen minutes and a ship/no-ship call.

Design rules, in priority order:

1. The verdict is the first thing on screen. Everything else is supporting
   evidence for it.
2. Groups are ordered worst-first and the section header carries the count, so
   a releaser can stop reading as soon as the blockers are clear.
3. Pre-existing problems are hidden by default. They are real, but they are
   already live, so putting them in front of a releaser at release time is
   exactly the noise that trains people to ignore the tool.
4. Fixes are shown, in green, last. They are the evidence that a changed string
   is not automatically a risky one.
"""

from __future__ import annotations

import re

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .model import Report, Severity

STYLES = {
    Severity.BLOCKER: ("BLOCKER", "bold white on red"),
    Severity.HIGH: ("HIGH", "bold red"),
    Severity.MEDIUM: ("MEDIUM", "bold yellow"),
    Severity.LOW: ("LOW", "yellow"),
    Severity.INFO: ("PRE-EXISTING", "cyan"),
    Severity.RESOLVED: ("FIXED", "bold green"),
}

HEADINGS = {
    Severity.BLOCKER: "Blockers - do not ship until these are resolved",
    Severity.HIGH: "High - confirm these are intentional",
    Severity.MEDIUM: "Medium - likely visible to players",
    Severity.LOW: "Low - cosmetic",
    Severity.INFO: "Pre-existing - already live, not caused by this release",
    Severity.RESOLVED: "Fixed by this release",
}


_UUID_KEY = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-", re.IGNORECASE)


def _short_key(key: str) -> str:
    """UUID keys shorten to their first block; human-readable keys stay readable.

    `7a794655-44e9-...` -> `7a794655`, but `welcome_banner` is left alone. The
    first block of a UUID is unique enough to grep the file for.
    """
    if _UUID_KEY.match(key):
        return key.split("-", 1)[0]
    return key if len(key) <= 20 else key[:19] + "…"


def _where(finding) -> Text:
    """Short, greppable location: `2b827952 / ru`."""
    parts = []
    if finding.key:
        parts.append(_short_key(finding.key))
    if finding.lang:
        parts.append(finding.lang)
    return Text(" / ".join(parts) if parts else "file", style="dim")


def _body(finding, style: str) -> Group:
    """Issue headline, then why it matters, then the evidence."""
    lines = [Text(finding.title, style=style), Text(finding.detail, style="default")]
    if finding.before is not None:
        lines.append(Text("live ", style="dim") + Text(finding.before or "(empty)", style="red"))
    if finding.after is not None:
        lines.append(Text("new  ", style="dim") + Text(finding.after or "(empty)", style="green"))
    return Group(*lines)


def _section(severity, findings) -> Group:
    label, style = STYLES[severity]

    heading = Text()
    heading.append(f" {label} ", style=style)
    heading.append(f"  {HEADINGS[severity]}", style="bold")
    heading.append(f"  ({len(findings)})", style="dim")

    # Two columns only. Anything more and the detail column gets squeezed into a
    # ransom note on an 80-column terminal, which is where this will be read.
    table = Table(box=box.SIMPLE_HEAD, show_header=False, show_lines=True, expand=True, padding=(0, 1))
    table.add_column("where", width=24, no_wrap=True, overflow="ellipsis")
    table.add_column("what", ratio=1, overflow="fold")

    for finding in findings:
        table.add_row(_where(finding), _body(finding, style))
    return Group(heading, table)


def _verdict(report: Report) -> Panel:
    blockers = len(report.blockers)
    high = sum(1 for f in report.findings if f.severity is Severity.HIGH)

    if blockers:
        text, style = (
            f"DO NOT SHIP  -  {blockers} blocker{'s' if blockers != 1 else ''}"
            + (f", {high} to confirm" if high else ""),
            "bold white on red",
        )
    elif high:
        text, style = (
            f"REVIEW BEFORE SHIPPING  -  {high} change{'s' if high != 1 else ''} to confirm",
            "bold black on yellow",
        )
    else:
        text, style = "SAFE TO SHIP  -  nothing flagged", "bold white on green"

    return Panel(Text(f" {text} ", style=style, justify="center"), box=box.HEAVY, style=style)


def render(report: Report, console: Console | None = None, show_all: bool = False) -> None:
    console = console or Console()

    header = Table.grid(padding=(0, 2))
    header.add_column(style="dim", justify="right")
    header.add_column()
    header.add_row("live", f"{report.baseline_path}  (version {report.baseline_version})")
    header.add_row("candidate", f"{report.candidate_path}  (version {report.candidate_version})")
    console.print(Panel(header, title="Localisation release check", box=box.ROUNDED, padding=(0, 1)))

    console.print(_verdict(report))

    if report.warnings:
        console.print()
        console.print(Text("Input warnings (recovered, but worth a look):", style="bold yellow"))
        for warning in report.warnings:
            console.print(Text("  - " + warning, style="yellow"))

    hidden = 0
    for severity in Severity:
        group = [f for f in report.findings if f.severity is severity]
        if not group:
            continue
        if severity is Severity.INFO and not show_all:
            hidden = len(group)
            continue
        console.print()
        console.print(_section(severity, group))

    # The footer is the anti-noise argument, in numbers: most changes are fine,
    # and the tool is saying so out loud.
    fixed = sum(1 for f in report.findings if f.severity is Severity.RESOLVED)
    console.print()
    summary = (
        f"{report.strings_compared} strings compared  |  "
        f"{report.strings_changed} changed  |  "
        f"{len(report.flagged)} flagged  |  "
        f"{fixed} fixed by this release"
    )
    if hidden:
        summary += f"  |  {hidden} pre-existing hidden (--all to show)"
    console.print(Text(summary, style="dim"))
