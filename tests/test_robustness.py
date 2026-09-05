"""Inputs designed to break the tool rather than to be checked by it.

A release gate that throws a traceback is worse than no gate: it blocks the
release for a reason nobody can act on, and the fastest way past it is to stop
running it. Everything here must produce either a report or a clean error -
never a stack trace, never a hang.

The rule this encodes: a malformed *file* is a clean failure (exit 2), while
malformed *content inside a readable file* is a warning plus a best-effort
report. Losing the whole report because one entry is junk would be the wrong
trade for the releaser.
"""

from __future__ import annotations

import io
import json
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest
from rich.console import Console

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locheck.engine import analyse  # noqa: E402
from locheck.loader import LoadError, load  # noqa: E402
from locheck.report import render  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

CONTROL_BYTE = "\x07"


def _plist(path: Path, payload) -> Path:
    path.write_bytes(plistlib.dumps(payload))
    return path


def _render(report) -> str:
    """Render to a string, proving the report layer survives the content too.

    Rendering is part of what has to survive hostile input: a finding that
    cannot be printed blocks a release just as effectively as a crash in the
    analysis does.
    """
    buffer = io.StringIO()
    render(report, console=Console(width=100, file=buffer), show_all=True)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# files that cannot be read at all -> clean error, never a traceback
# --------------------------------------------------------------------------

UNREADABLE = [
    pytest.param(b"", id="empty-file"),
    pytest.param(b"not xml at all", id="plain-text"),
    pytest.param(b"<?xml version='1.0'?><plist><dict>", id="truncated-xml"),
    pytest.param(b"\x00\x01\x02\x03\xff\xfe", id="binary-noise"),
    pytest.param(
        b"<?xml version='1.0'?><plist version='1.0'><array/></plist>",
        id="top-level-is-an-array",
    ),
    pytest.param(
        b"<?xml version='1.0'?><plist version='1.0'><dict>"
        b"<key>version</key><string>1</string></dict></plist>",
        id="no-localisations-key",
    ),
    pytest.param(
        b"<?xml version='1.0'?><plist version='1.0'><dict>"
        b"<key>localisations</key><string>oops</string></dict></plist>",
        id="localisations-is-not-a-dict",
    ),
    # Control characters are illegal in XML 1.0 even written as entities, so a
    # file carrying one cannot be parsed at all. That is the right outcome - the
    # file is corrupt, and guessing at its contents would be worse than failing.
    pytest.param(
        (
            "<?xml version='1.0'?><plist version='1.0'><dict>"
            "<key>localisations</key><dict><key>k</key><dict>"
            "<key>en-US</key><string>bad" + CONTROL_BYTE + "here</string>"
            "</dict></dict></dict></plist>"
        ).encode("utf-8"),
        id="raw-control-byte",
    ),
    pytest.param(
        b"<?xml version='1.0'?><plist version='1.0'><dict>"
        b"<key>localisations</key><dict><key>k</key><dict>"
        b"<key>en-US</key><string>bad&#x07;here</string>"
        b"</dict></dict></dict></plist>",
        id="control-character-as-an-xml-entity",
    ),
]


@pytest.mark.parametrize("content", UNREADABLE)
def test_unreadable_files_raise_a_clean_error(tmp_path, content):
    path = tmp_path / "bad.plist"
    path.write_bytes(content)
    with pytest.raises(LoadError):
        load(path)


def test_tabs_and_newlines_are_legal_and_load_normally(tmp_path):
    """The counterpart to the control-character cases: these are valid XML."""
    body = "ok\there\nand here"
    path = tmp_path / "ws.plist"
    path.write_text(
        "<?xml version='1.0'?><plist version='1.0'><dict>"
        "<key>localisations</key><dict><key>k</key><dict>"
        "<key>en-US</key><string>" + body + "</string>"
        "</dict></dict></dict></plist>",
        encoding="utf-8",
    )
    assert load(path).entries["k"]["en-US"] == body


# --------------------------------------------------------------------------
# readable files with hostile content -> a report, plus warnings
# --------------------------------------------------------------------------

HOSTILE_ENTRIES = [
    pytest.param({}, id="no-entries-at-all"),
    pytest.param({"k": {}}, id="entry-with-no-languages"),
    pytest.param({"k": "a string where a dict belongs"}, id="entry-is-a-string"),
    pytest.param({"k": [1, 2, 3]}, id="entry-is-a-list"),
    pytest.param({"k": {"en-US": 42}}, id="value-is-an-integer"),
    pytest.param({"k": {"en-US": True}}, id="value-is-a-boolean"),
    pytest.param({"k": {"en-US": b"bytes"}}, id="value-is-binary-data"),
    pytest.param({"k": {"en-US": {"nested": "dict"}}}, id="value-is-a-dict"),
    pytest.param({"k": {"": "empty language code"}}, id="empty-language-code"),
    pytest.param({"": {"en-US": "empty text id"}}, id="empty-text-id"),
    pytest.param({"k": {"en-US": " " * 5000}}, id="huge-whitespace-string"),
    pytest.param({"k": {"en-US": "x" * 200_000}}, id="very-long-string"),
    pytest.param({"k": {"en-US": "%" * 500}}, id="five-hundred-percent-signs"),
    pytest.param({"k": {"en-US": "[" * 300}}, id="unbalanced-bracket-storm"),
    pytest.param({"k": {"en-US": "%1$@ %99$@ %0$@ %$@"}}, id="odd-positional-indices"),
    pytest.param({"k": {"en-US": "%"}}, id="a-single-percent"),
    pytest.param(
        {"k": {"en-US": "A:[unclosed", "fr": "A:[a/b]"}},
        id="token-broken-in-the-source-not-the-translation",
    ),
    pytest.param({"k": {"en-US": "\\n" * 400}}, id="nothing-but-line-breaks"),
    pytest.param({"k": {"en-US": "\U0001f381" * 2000}}, id="emoji-flood"),
    pytest.param(
        {f"key-{i}": {"en-US": f"String {i}", "fr": f"Chaine {i}"} for i in range(500)},
        id="five-hundred-entries",
    ),
]


@pytest.mark.parametrize("entries", HOSTILE_ENTRIES)
def test_hostile_content_still_produces_a_report(tmp_path, entries):
    live = _plist(tmp_path / "live.plist", {"version": "1.0.0", "localisations": {}})
    cand = _plist(tmp_path / "cand.plist", {"version": "1.0.1", "localisations": entries})

    report = analyse(load(live), load(cand))
    assert isinstance(report.findings, list)
    assert _render(report)
    # A finding a human cannot act on is not a finding.
    assert all(f.action for f in report.findings)


@pytest.mark.parametrize("entries", HOSTILE_ENTRIES)
def test_hostile_content_survives_being_the_baseline(tmp_path, entries):
    """The same junk on the other side of the comparison."""
    live = _plist(tmp_path / "live.plist", {"version": "1.0.0", "localisations": entries})
    cand = _plist(tmp_path / "cand.plist", {"version": "1.0.1", "localisations": {}})
    assert _render(analyse(load(live), load(cand)))


def test_a_file_compared_against_itself_reports_no_blockers():
    for name in ("localisations_1_2_0.plist", "localisations_1_2_1.plist"):
        loaded = load(ROOT / name)
        report = analyse(loaded, loaded)
        assert not report.blockers
        assert _render(report)


def test_reversing_the_comparison_does_not_crash():
    """Running it backwards is a plausible mistake, not a reason to blow up."""
    live = load(ROOT / "localisations_1_2_0.plist")
    candidate = load(ROOT / "localisations_1_2_1.plist")
    assert _render(analyse(candidate, live))


def test_rich_markup_in_content_is_not_interpreted(tmp_path):
    """A translator writing [bold] must not restyle the report or crash it.

    Everything user-supplied goes through rich's Text(), which does not parse
    markup. Passing a raw string to console.print() would, and an unclosed tag
    would then raise while rendering.
    """
    live = _plist(
        tmp_path / "live.plist",
        {"version": "1.0.0", "localisations": {"k": {"en-US": "Buy %@", "fr": "Achete %@"}}},
    )
    cand = _plist(
        tmp_path / "cand.plist",
        {
            "version": "1.0.1",
            "localisations": {"k": {"en-US": "Buy %@", "fr": "[bold red]Achete[/] [/oops"}},
        },
    )
    report = analyse(load(live), load(cand))
    assert report.blockers
    # The markup survives as literal text rather than being consumed as styling.
    assert "[bold red]" in _render(report)


# --------------------------------------------------------------------------
# the command line contract
# --------------------------------------------------------------------------

def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "locheck", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def test_exit_codes_are_stable():
    live, cand = "localisations_1_2_0.plist", "localisations_1_2_1.plist"

    blocked = _run(live, cand)
    assert blocked.returncode == 1, "blockers must fail the build"

    clean = _run(live, live)
    assert clean.returncode == 0, "no blockers must pass"

    missing = _run(live, "does-not-exist.plist")
    assert missing.returncode == 2
    assert "Traceback" not in missing.stderr


@pytest.mark.parametrize("flag", ["--summary", "--all", "--json", "--strict"])
def test_every_flag_runs_without_a_traceback(flag):
    result = _run("localisations_1_2_0.plist", "localisations_1_2_1.plist", flag)
    assert "Traceback" not in result.stderr
    assert result.returncode in (0, 1)


def test_output_survives_being_redirected_away_from_a_terminal():
    """A Windows console defaults to cp1252 and these files are full of Cyrillic.

    Piping the report into a file is how it gets attached to a ticket, so it has
    to survive losing the terminal's encoding.
    """
    result = _run("localisations_1_2_0.plist", "localisations_1_2_1.plist")
    assert "Traceback" not in result.stderr
    assert "До начала" in result.stdout


def test_json_output_is_valid_and_every_finding_is_actionable():
    result = _run("localisations_1_2_0.plist", "localisations_1_2_1.plist", "--json")
    payload = json.loads(result.stdout)

    assert payload["blocker_count"] == 4
    assert payload["findings"], "a blocked release must explain itself"
    for finding in payload["findings"]:
        assert finding["severity"]
        assert finding["code"]
        assert finding["action"], f"{finding['code']} tells the reader nothing to do"
