"""The summary-first flow, and the guarantee that it never blocks a build.

Two things are under test. The first is the feature: the summary is shown, "."
expands it, Esc finishes. The second matters more - a prompt must never appear
where nobody can answer it. In a CI log a prompt is not a feature, it is a hang:
the build sits there until it times out, with no indication why.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest
from rich.console import Console

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locheck import __main__ as cli  # noqa: E402
from locheck.interactive import someone_is_watching  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# Text that only ever appears once the detail cards are rendered.
A_DETAIL_CARD = "Do not ship until"
A_FIX_INSTRUCTION = "Rename 'jp' to 'ja'"


def _run_interactive(keypress: str, argv=()) -> str:
    """Run the CLI as if a person were watching, and press one key."""
    buffer = io.StringIO()

    def console(*args, **kwargs):
        if kwargs.get("stderr"):
            return Console(stderr=True)
        return Console(width=90, file=buffer)

    with mock.patch.object(cli, "someone_is_watching", return_value=True), \
         mock.patch.object(cli, "read_key", return_value=keypress), \
         mock.patch.object(cli, "Console", console):
        cli.main([str(ROOT / "localisations_1_2_0.plist"),
                  str(ROOT / "localisations_1_2_1.plist"), *argv])
    return buffer.getvalue()


# --------------------------------------------------------------------------
# the feature
# --------------------------------------------------------------------------

def test_the_summary_is_shown_before_any_key_is_pressed():
    output = _run_interactive("\x1b")
    assert "SEVERITY" in output, "the table is the point of the summary"
    assert "DO NOT SHIP" in output, "the verdict must not wait for a keypress"


def test_escape_finishes_without_expanding():
    output = _run_interactive("\x1b")
    assert A_DETAIL_CARD not in output


def test_a_dot_expands_into_the_detail():
    output = _run_interactive(".")
    assert A_DETAIL_CARD in output
    assert A_FIX_INSTRUCTION in output, "expanding must show how to fix things"


def test_expanding_shows_strictly_more_than_the_summary():
    assert len(_run_interactive(".")) > len(_run_interactive("\x1b"))


@pytest.mark.parametrize("key", [".", "\r", "\n", " ", "x", "q", "Q", ""])
def test_every_key_except_escape_expands(key):
    """Esc is the only way out - `q` included, despite the pager habit.

    Erring towards showing too much: a stray key costs a scroll, whereas closing
    costs the reader the report they were about to read.
    """
    assert A_DETAIL_CARD in _run_interactive(key)


def test_interrupting_at_the_prompt_exits_cleanly():
    buffer = io.StringIO()
    with mock.patch.object(cli, "someone_is_watching", return_value=True), \
         mock.patch.object(cli, "read_key", side_effect=KeyboardInterrupt), \
         mock.patch.object(cli, "Console",
                           lambda *a, **k: Console(stderr=True) if k.get("stderr")
                           else Console(width=90, file=buffer)):
        code = cli.main([str(ROOT / "localisations_1_2_0.plist"),
                         str(ROOT / "localisations_1_2_1.plist")])
    assert code == 1, "Ctrl-C at the prompt still reports the blockers it found"
    assert A_DETAIL_CARD not in buffer.getvalue()


# --------------------------------------------------------------------------
# never prompting where nobody can answer
# --------------------------------------------------------------------------

def test_a_piped_stdout_is_not_a_watching_human():
    with mock.patch("sys.stdout") as fake:
        fake.isatty.return_value = False
        assert someone_is_watching() is False


def test_a_detached_stream_is_not_a_watching_human():
    """Some hosts hand over a stream whose isatty() raises rather than answers."""
    with mock.patch("sys.stdin") as fake:
        fake.isatty.side_effect = ValueError("I/O operation on closed file")
        assert someone_is_watching() is False


def _run_subprocess(*args, timeout=30) -> subprocess.CompletedProcess:
    """A real subprocess with pipes - exactly what CI gives the tool."""
    return subprocess.run(
        [sys.executable, "-m", "locheck", *args],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        stdin=subprocess.DEVNULL, timeout=timeout,
    )


def test_a_piped_run_neither_hangs_nor_prompts():
    """The regression that would silently break every pipeline using this."""
    result = _run_subprocess("localisations_1_2_0.plist", "localisations_1_2_1.plist")
    assert result.returncode == 1
    assert "Press" not in result.stdout, "a prompt in a CI log is a hang"
    assert A_DETAIL_CARD in result.stdout, "piped output must be complete"


@pytest.mark.parametrize("flag", ["--summary", "--details", "--json"])
def test_explicit_output_flags_never_prompt(flag):
    result = _run_subprocess("localisations_1_2_0.plist", "localisations_1_2_1.plist", flag)
    assert "Press" not in result.stdout
    assert result.returncode == 1


def test_details_flag_prints_everything_at_once():
    result = _run_subprocess("localisations_1_2_0.plist", "localisations_1_2_1.plist", "--details")
    assert A_DETAIL_CARD in result.stdout
    assert A_FIX_INSTRUCTION in result.stdout


def test_summary_flag_stops_at_the_table():
    result = _run_subprocess("localisations_1_2_0.plist", "localisations_1_2_1.plist", "--summary")
    assert "SEVERITY" in result.stdout
    assert A_DETAIL_CARD not in result.stdout
