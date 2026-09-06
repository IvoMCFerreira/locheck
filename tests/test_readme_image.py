"""The README image has to be the tool's real output, not a picture of it once.

The whole argument for exporting an SVG instead of screenshotting is that it
cannot quietly go stale. That argument is only true if something checks. It was
not, and the image immediately fell out of date: the generator hardcoded the
prompt text rather than calling the code that prints it, so the picture still
showed a prompt the tool had stopped using.

These tests fail when the committed image no longer matches what the tool
produces. The fix is always the same one line, and the failure message says so.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "assets" / "report.svg"

REGENERATE = "the README image is stale - run `make screenshot`"


@pytest.fixture(scope="module")
def rendered() -> str:
    """The text content of the committed SVG, whitespace normalised.

    rich writes non-breaking spaces between words, so a naive substring search
    reports text as missing when it is there.
    """
    if not IMAGE.exists():
        pytest.skip("no README image committed")
    root = ET.fromstring(IMAGE.read_text(encoding="utf-8"))
    text = " ".join(t for t in root.itertext() if "font-face" not in t)
    return re.sub(r"\s+", " ", text.replace("\u00a0", " "))


def test_the_image_is_well_formed_svg():
    ET.fromstring(IMAGE.read_text(encoding="utf-8"))


def test_the_image_shows_the_current_key_legend(rendered):
    """The line that went stale. Every word of it comes from `_legend` now."""
    for word in ("Esc", "close", "compare other versions", "any other key",
                 "show the detail"):
        assert word in rendered, f"{REGENERATE} (missing {word!r})"


def test_the_image_shows_the_verdict_and_the_counts(rendered):
    assert "DO NOT SHIP" in rendered, REGENERATE
    assert "4 blockers" in rendered, REGENERATE
    assert "32 strings compared" in rendered, REGENERATE


def test_the_image_shows_every_finding_the_tool_currently_reports(rendered):
    """If a check is added, renamed or removed, the picture has to be redrawn."""
    from locheck.engine import analyse
    from locheck.loader import load

    report = analyse(
        load(ROOT / "localisations_1_2_0.plist"),
        load(ROOT / "localisations_1_2_1.plist"),
    )
    visible = [f for f in report.findings if f.severity.name != "INFO"]

    for finding in visible:
        assert finding.title in rendered, f"{REGENERATE} (missing {finding.title!r})"

    # And nothing the tool has stopped saying.
    assert "Press any key to see what each finding" not in rendered, REGENERATE
