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
    """pt-BR gained an accent (`videos` -> `vídeos`). Changed, but not a risk.

    Scoped to the one string: pt-BR is legitimately flagged elsewhere in this
    file for a mistyped game rule, and that finding is not this test's business.
    """
    report = analyse(load(LIVE), load(CANDIDATE))
    accent_fix = "d8225439-0a23-404c-857d-8cd37032a606"
    assert not [
        f for f in report.findings if f.lang == "pt-BR" and f.key == accent_fix
    ]


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
# the quieter checks - these are the ones most at risk of crying wolf
# --------------------------------------------------------------------------

def test_country_code_masquerading_as_a_language_is_caught():
    """`jp` is Japan, `ja` is Japanese. A file shipping the former reaches nobody."""
    from locheck import langcodes

    reason, action = langcodes.problem_with("jp")
    assert "country code" in reason
    assert "'ja'" in action

    assert langcodes.problem_with("ja") is None
    assert langcodes.problem_with("pt-BR") is None  # region subtags are fine
    assert langcodes.problem_with("en-US") is None
    assert langcodes.problem_with("tk") is None  # Turkmen: odd here, but valid


def test_the_japanese_language_code_is_flagged_in_the_sample():
    report = analyse(load(LIVE), load(CANDIDATE))
    jp = [f for f in report.findings if f.code == "language.invalid_code"]
    assert [f.lang for f in jp] == ["jp"]
    assert jp[0].severity is Severity.HIGH  # added by this release


@pytest.mark.parametrize(
    "raw, expected",
    [("4.0", "4"), ("4", "4"), ("0,5", "0.5"), ("1.0", "1"), ("30", "30"), ("1.000", "1000")],
)
def test_decimal_separators_do_not_confuse_the_number_check(raw, expected):
    """`0,5` and `0.5` are the same number; a tool that disagrees flags all of Europe."""
    from locheck.rules import _normalise_number

    assert _normalise_number(raw) == expected


def test_small_numbers_spelled_as_words_are_not_flagged():
    """The regression this locks: Turkish writes "Rack 1"/"Rack 2" as words.

    `İlk üçgen` and `İkinci üçgen` are first and second. An earlier version of
    this rule reported that correct translation as a missing number.
    """
    from locheck.rules import rule_numbers

    entry = {
        "en-US": "Rack 1 gives 10 seconds, Rack 2 gives 9, and a 30 second penalty.",
        "tk": "İlk üçgen 10 saniye, İkinci üçgen 9 saniye, 30 saniye ceza.",
    }
    assert rule_numbers("k", "tk", entry["tk"], entry) is None


def test_a_mistyped_game_rule_is_still_caught():
    from locheck.rules import rule_numbers

    entry = {
        "en-US": "Potting the Cue Ball will result in a 30 seconds penalty.",
        "pt-BR": "Encaçapar a bola branca resultará em uma penalidade de 3 segundos.",
    }
    problem = rule_numbers("k", "pt-BR", entry["pt-BR"], entry)
    assert problem is not None
    assert "30" in problem.detail
    assert "penalty" in problem.detail  # names the sentence, not just the number


def test_shorter_translations_are_never_flagged_for_length():
    """Japanese is routinely a third the length of its English source."""
    from locheck.rules import rule_length

    entry = {"en-US": "Watch a short video and earn 15 coins today", "jp": "動画で15コイン"}
    assert rule_length("k", "jp", entry["jp"], entry) is None


def test_a_translation_that_will_overflow_its_button_is_flagged():
    from locheck.rules import rule_length

    entry = {"en-US": "Play as Guest", "de": "Als Gast ohne Registrierung weiterspielen bitte"}
    problem = rule_length("k", "de", entry["de"], entry)
    assert problem is not None and problem.severity is Severity.MEDIUM


def test_losing_line_breaks_is_flagged_but_gaining_them_is_not():
    from locheck.rules import rule_line_structure

    entry = {"en-US": r"one\ntwo\nthree", "jp": "onetwothree", "de": r"one\ntwo\nthree\nmore"}
    assert rule_line_structure("k", "jp", entry["jp"], entry) is not None
    assert rule_line_structure("k", "de", entry["de"], entry) is None


# --------------------------------------------------------------------------
# line numbers - the difference between "something is wrong" and "go fix line 22"
# --------------------------------------------------------------------------

def test_line_index_points_at_the_real_source_line():
    from locheck import locate

    index = locate.build(CANDIDATE)
    source = CANDIDATE.read_text(encoding="utf-8").splitlines()
    key = "2b827952-8d1a-4c31-9283-8753d1fc51be"

    line = index.string(key, "ru")
    assert "До начала %..." in source[line - 1]

    assert index.of("version") is not None
    assert "1.2.0" in source[index.of("version") - 1]


def test_line_index_degrades_quietly_on_unparseable_input():
    from locheck import locate

    assert not locate.build(ROOT / "tests" / "fixtures" / "garbage.txt")


def test_every_actionable_finding_tells_the_reader_what_to_do():
    """A finding without an action is a finding the releaser cannot act on."""
    report = analyse(load(LIVE), load(CANDIDATE))
    assert all(f.action for f in report.findings)


def test_blockers_in_a_string_carry_a_line_number():
    report = analyse(load(LIVE), load(CANDIDATE))
    located = [f for f in report.blockers if f.key and f.lang]
    assert located and all(f.line for f in located)


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
