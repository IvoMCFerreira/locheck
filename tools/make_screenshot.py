"""Render the report to assets/report.svg for the README.

An SVG rather than a screenshot, because `rich` can export what it drew. That
means the image is the real output rather than a photograph of a screen: it is
crisp at any zoom, it is a text file so a diff shows what changed in it, it has
no scaling or cropping artefacts, and it cannot quietly drift out of date without
somebody regenerating it from the tool itself.

    python tools/make_screenshot.py        (or: make screenshot)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rich.console import Console  # noqa: E402

from locheck.__main__ import _legend  # noqa: E402
from locheck.engine import analyse  # noqa: E402
from locheck.loader import load  # noqa: E402
from locheck.report import render_summary  # noqa: E402

WIDTH = 100
OUT = ROOT / "assets" / "report.svg"


def main() -> int:
    baseline = load(ROOT / "localisations_1_2_0.plist")
    candidate = load(ROOT / "localisations_1_2_1.plist")
    report = analyse(baseline, candidate)

    # record=True keeps everything printed so it can be exported afterwards.
    console = Console(record=True, width=WIDTH)
    render_summary(
        report,
        console,
        note="newest two of 2 versions found here",
    )
    # The real legend, not a copy of its text. An earlier version of this script
    # hardcoded the prompt, and it went out of date the moment the prompt changed
    # - which is the exact failure an exported SVG is supposed to prevent. Every
    # line in the image now comes from the code that prints it.
    _legend(console, expandable=True)

    OUT.parent.mkdir(exist_ok=True)
    console.save_svg(str(OUT), title="locheck")
    print(f"wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
