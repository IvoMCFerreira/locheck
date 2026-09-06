"""Comparing a release against an older one, on purpose.

A rollback is a legitimate question - "what does going back cost us?" - and the
analysis is identical either way. What differs is what the answer *means*. Read
with forward wording, a rollback report announces that a crash was fixed at the
moment it is about to be reintroduced, which is the worst thing a release gate
can do: be correct and unreadable.
"""

from __future__ import annotations

import io
import plistlib
import sys
from pathlib import Path

import pytest
from rich.console import Console

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locheck.engine import analyse  # noqa: E402
from locheck.loader import load  # noqa: E402
from locheck.report import render  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "localisations_1_2_0.plist"
CANDIDATE = ROOT / "localisations_1_2_1.plist"


def _rendered(report) -> str:
    buffer = io.StringIO()
    render(report, console=Console(width=110, file=buffer), show_all=True)
    return buffer.getvalue()


@pytest.fixture
def forwards():
    return analyse(load(LIVE), load(CANDIDATE))


@pytest.fixture
def backwards():
    return analyse(load(CANDIDATE), load(LIVE))


# --------------------------------------------------------------------------
# detecting the direction
# --------------------------------------------------------------------------

def test_the_normal_direction_is_not_a_rollback(forwards):
    assert forwards.is_rollback is False


def test_an_older_candidate_is_a_rollback(backwards):
    assert backwards.is_rollback is True


def test_direction_comes_from_file_names_not_the_version_field(backwards):
    """Both sample files declare 1.2.0 - the field is what a release forgets.

    If direction were read from the declared version, the two would be
    indistinguishable and every rollback would be reported as a release.
    """
    assert backwards.baseline_version == backwards.candidate_version
    assert backwards.is_rollback is True


def test_unversioned_names_are_not_assumed_to_be_a_rollback(tmp_path):
    for name in ("alpha.plist", "beta.plist"):
        (tmp_path / name).write_bytes(
            plistlib.dumps({"version": "1.0.0",
                            "localisations": {"k": {"en-US": "Hi"}}})
        )
    report = analyse(load(tmp_path / "beta.plist"), load(tmp_path / "alpha.plist"))
    assert report.is_rollback is False, "no evidence either way is not evidence of backwards"


# --------------------------------------------------------------------------
# how it reads
# --------------------------------------------------------------------------

def test_the_verdict_asks_the_right_question(forwards, backwards):
    """"DO NOT SHIP" is the wrong answer to "should I roll back?".

    The reader may be rolling back *because* production is on fire. What they
    need is the price, not a refusal.
    """
    assert "DO NOT SHIP" in _rendered(forwards)

    rolled = _rendered(backwards)
    assert "DO NOT SHIP" not in rolled
    assert "ROLLING BACK BREAKS" in rolled


def test_a_clean_rollback_says_so(tmp_path):
    same = {"version": "1.0.0", "localisations": {"k": {"en-US": "Hi", "fr": "Salut"}}}
    old = tmp_path / "l_1_0_0.plist"
    new = tmp_path / "l_1_1_0.plist"
    old.write_bytes(plistlib.dumps(same))
    new.write_bytes(plistlib.dumps({**same, "version": "1.1.0"}))

    report = analyse(load(new), load(old))
    assert report.is_rollback
    assert "SAFE TO ROLL BACK" in _rendered(report)


def test_regressions_are_worded_as_coming_back_not_being_introduced(backwards):
    """The French placeholder is not "introduced" by a rollback - it returns."""
    french = [f for f in backwards.findings if f.lang == "fr"]
    assert french, "the French string differs between these files"
    assert any("comes back if you roll back" in f.detail for f in french)
    assert not any("introduced by this release" in f.detail for f in backwards.findings)


def test_a_repair_is_worded_as_something_the_rollback_does(backwards):
    """Going back removes the empty Italian string - that is the rollback's doing."""
    resolved = [f for f in backwards.findings if f.title.startswith("Rolling back fixes")]
    assert resolved
    assert not any(f.title.startswith("Fixed:") for f in backwards.findings)


def test_section_headings_follow_the_direction(forwards, backwards):
    assert "Do not ship until these are resolved" in _rendered(forwards)

    rolled = _rendered(backwards)
    assert "Rolling back would break these" in rolled
    assert "Rolling back would repair these" in rolled
    assert "Do not ship until these are resolved" not in rolled


def test_the_footer_names_the_two_files_by_age_in_both_directions(backwards, forwards):
    """Age is a fact about the files; which one is live is not.

    "(live)" was a claim the tool cannot make - a version can be built and never
    shipped. Direction is carried by the verdict and the rollback notice, so the
    footer only has to be true.
    """
    for report in (forwards, backwards):
        rendered = _rendered(report)
        assert "(older)" in rendered and "(newer)" in rendered
        assert "(live)" not in rendered


def test_forward_wording_never_leaks_into_a_rollback(backwards):
    """A single forward phrase left in place is what makes the report mislead."""
    rolled = _rendered(backwards)
    for phrase in ("introduced by this release", "DO NOT SHIP", "SAFE TO SHIP",
                   "Fixed by this release"):
        assert phrase not in rolled, f"forward wording leaked: {phrase!r}"


def test_rollback_wording_never_leaks_into_a_release(forwards):
    rolled_phrases = ("rolling back", "Rolling back", "ROLLING BACK",
                      "(rolling back to)", "comes back if you roll back")
    rendered = _rendered(forwards)
    for phrase in rolled_phrases:
        assert phrase not in rendered, f"rollback wording leaked: {phrase!r}"


def test_the_direction_is_in_the_json_for_ci(backwards, forwards):
    assert backwards.as_dict()["is_rollback"] is True
    assert forwards.as_dict()["is_rollback"] is False


# --------------------------------------------------------------------------
# a declared version that disagrees with the file name
# --------------------------------------------------------------------------

def test_the_header_says_when_a_declared_version_is_not_the_expected_one(forwards):
    """Both sample files declare 1.2.0, so the header shows it twice.

    That is accurate - the candidate really did not bump - but two identical
    version numbers beside files named 1_2_0 and 1_2_1 read as the tool printing
    the same line twice. Naming the discrepancy turns a line that looks like a
    rendering fault into the first sign of the actual problem.
    """
    rendered = _rendered(forwards)
    assert "expected 1.2.1" in rendered
    assert "version.not_bumped" in {f.code for f in forwards.findings}


def test_a_matching_version_says_nothing_extra(tmp_path):
    for name, version in [("l_1_0_0.plist", "1.0.0"), ("l_1_1_0.plist", "1.1.0")]:
        (tmp_path / name).write_bytes(
            plistlib.dumps({"version": version,
                            "localisations": {"k": {"en-US": "Hi"}}})
        )
    report = analyse(load(tmp_path / "l_1_0_0.plist"), load(tmp_path / "l_1_1_0.plist"))
    assert "expected" not in _rendered(report)


def test_the_rollback_notice_survives_narrow_windows(backwards):
    """It once wrapped across three lines and split "OLDER release" in half.

    It is the one sentence that stops the whole report being read backwards, so
    it must arrive intact at any width the reader might have.
    """
    for width in (80, 100, 140, 200):
        buffer = io.StringIO()
        render(backwards, console=Console(width=width, file=buffer), show_all=True)
        flat = " ".join(buffer.getvalue().split())
        assert "the candidate is the older release" in flat, f"broken up at {width}"


def test_the_word_live_never_appears_in_the_report(forwards, backwards):
    """The tool knows which file is older. It does not know what production serves.

    A version can be built and never shipped, or rolled back, and nothing in the
    files records that - so calling the second-newest file "live" states as fact
    something nobody has checked. The files are described by age instead, which
    is true whichever direction the comparison runs.
    """
    for report in (forwards, backwards):
        rendered = _rendered(report).lower()
        assert " live " not in rendered
        assert "(live)" not in rendered
        assert "live version" not in rendered
        assert "live file" not in rendered
