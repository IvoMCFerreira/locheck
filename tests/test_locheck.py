"""Tests for the parts that would quietly ruin the tool if they broke.

Not aiming for coverage. Two things are worth locking down:

1. The placeholder scanner, because every blocker verdict depends on it and its
   failure mode is silent (a missed stray `%` is a shipped crash).
2. The regression classifier, because it is the whole argument of the tool. If
   `fixed` ever starts reading as `broken`, the tool becomes the thing the brief
   warns against - one that flags every change and gets ignored.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locheck.engine import analyse  # noqa: E402
from locheck.loader import LoadError, load  # noqa: E402
from locheck.model import Severity  # noqa: E402
from locheck.rules import scan_placeholders  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "localisations_1_2_0.plist"
CANDIDATE = ROOT / "localisations_1_2_1.plist"


# --------------------------------------------------------------------------
# placeholder scanner
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, tokens, malformed",
    [
        ("Starting in %u...", ["%u"], 0),
        ("Buy %1$@ for %2$u", ["%1$@", "%2$u"], 0),
        ("%.2f coins", ["%.2f"], 0),
        ("plain text", [], 0),
        ("", [], 0),
        # %% is an escaped literal percent, not an argument the client fills in.
        ("Sale: 50%% off", [], 0),
        # The two real corruptions in the sample data.
        ("Commence dans % ...", [], 1),
        ("До начала %...", [], 1),
        # A bare trailing % is undefined behaviour if the string is formatted.
        ("Win 100%", [], 1),
    ],
)
def test_scan_placeholders(text, tokens, malformed):
    found, stray = scan_placeholders(text)
    assert found == tokens
    assert len(stray) == malformed


# --------------------------------------------------------------------------
# the classifier: same problem, three different verdicts
# --------------------------------------------------------------------------

def _write(tmp_path: Path, name: str, version: str, entries: dict) -> Path:
    path = tmp_path / name
    path.write_bytes(
        plistlib.dumps({"version": version, "localisations": entries})
    )
    return path


def _analyse(tmp_path, live_text, candidate_text):
    """Compare one string across two releases and return its finding, if any."""
    live = _write(tmp_path, "live.plist", "1.0.0",
                  {"k": {"en-US": "Starting in %u...", "fr": live_text}})
    cand = _write(tmp_path, "cand.plist", "1.0.1",
                  {"k": {"en-US": "Starting in %u...", "fr": candidate_text}})
    findings = [f for f in analyse(load(live), load(cand)).findings if f.lang == "fr"]
    return findings[0] if findings else None


def test_broken_string_that_was_fine_is_a_blocker(tmp_path):
    finding = _analyse(tmp_path, "Commence dans %u...", "Commence dans %...")
    assert finding.severity is Severity.BLOCKER
    assert "introduced by this release" in finding.detail


def test_repaired_string_is_reported_as_fixed_not_as_a_risk(tmp_path):
    """The calibration case: placeholders changed, but the change is an improvement."""
    finding = _analyse(tmp_path, "Commence dans % ...", "Commence dans %u...")
    assert finding.severity is Severity.RESOLVED


def test_problem_that_was_already_live_is_not_this_release_s_problem(tmp_path):
    finding = _analyse(tmp_path, "Commence dans % ...", "Commence dans % ...")
    assert finding.severity is Severity.INFO


def test_unchanged_healthy_string_produces_nothing(tmp_path):
    assert _analyse(tmp_path, "Commence dans %u...", "Commence dans %u...") is None


def test_reworded_but_healthy_string_produces_nothing(tmp_path):
    """A translator rewriting a string is not, by itself, a finding."""
    assert _analyse(tmp_path, "Commence dans %u...", "Ça démarre dans %u secondes !") is None


# --------------------------------------------------------------------------
# the real files
# --------------------------------------------------------------------------

def test_sample_release_is_blocked_for_the_expected_reasons():
    report = analyse(load(LIVE), load(CANDIDATE))
    codes = {(f.code, f.lang) for f in report.blockers}
    assert ("language.dropped", "es") in codes
    assert ("placeholder.malformed", "ru") in codes
    assert ("string.empty", "it") in codes
    assert ("token.unbalanced", "it") in codes


def test_the_french_fix_is_never_reported_as_a_risk():
    report = analyse(load(LIVE), load(CANDIDATE))
    french = [f for f in report.findings if f.lang == "fr"]
    assert [f.severity for f in french] == [Severity.RESOLVED]


def test_a_harmless_change_is_not_flagged():
    """pt-BR gained an accent (`videos` -> `vídeos`). Changed, but not a risk."""
    report = analyse(load(LIVE), load(CANDIDATE))
    assert not [f for f in report.findings if f.lang == "pt-BR"]


def test_most_changed_strings_are_not_flagged():
    """The anti-noise claim, asserted: four strings changed, two deserve attention.

    `fr` was repaired and `pt-BR` gained an accent. Neither is a risk, and a tool
    that said otherwise would be training the releaser to skim past it.
    """
    live, candidate = load(LIVE), load(CANDIDATE)
    report = analyse(live, candidate)

    changed = {
        (key, lang)
        for key, entry in candidate.entries.items()
        if key in live.entries
        for lang, text in entry.items()
        if lang in live.entries[key] and live.entries[key][lang] != text
    }
    flagged = {(f.key, f.lang) for f in report.flagged} & changed

    assert len(changed) == 4
    assert {lang for _, lang in flagged} == {"it", "ru"}


# --------------------------------------------------------------------------
# hostile input
# --------------------------------------------------------------------------

def test_garbage_input_fails_cleanly():
    with pytest.raises(LoadError):
        load(ROOT / "tests" / "fixtures" / "garbage.txt")


def test_missing_file_fails_cleanly():
    with pytest.raises(LoadError):
        load(ROOT / "does-not-exist.plist")


def test_malformed_entries_are_recovered_with_warnings():
    loaded = load(ROOT / "tests" / "fixtures" / "hostile.plist")
    assert loaded.warnings, "hostile fixture should produce warnings"
    assert "not-a-dict-entry" not in loaded.entries  # skipped, not crashed on
    assert loaded.entries["non-string-value"]["fr"] == "42"  # coerced, not dropped
