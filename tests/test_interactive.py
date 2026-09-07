"""The summary-first flow, and the guarantee that it never blocks a build.

Two things are under test. The first is the feature: the summary is shown, "."
expands it, Esc finishes. The second matters more - a prompt must never appear
where nobody can answer it. In a CI log a prompt is not a feature, it is a hang:
the build sits there until it times out, with no indication why.
"""

from __future__ import annotations

import io
import os
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


def test_the_null_device_is_not_a_watching_human():
    """Output sent to the null device must never count as somebody watching.

    Windows is where this bites. `isatty()` there answers "is this a character
    device", and NUL is one, so a report sent to NUL claimed to be a terminal,
    the interactive path ran, and the tool sat on `msvcrt.getwch()` waiting for a
    keypress at a console nobody was watching. On POSIX `isatty()` says no by
    itself, so the same call is already safe there.

    The guarantee is the same on both, so this asserts the guarantee rather than
    the platform, and the premise that made it fail is checked where it applies.
    Against the real device on purpose: mocking isatty is exactly what hid this,
    because a mock answers the question the way we assumed rather than the way
    the platform does.
    """
    with open(os.devnull, "w") as sink, open(os.devnull) as source:
        if sys.platform == "win32":
            assert sink.isatty(), "premise: Windows calls the NUL device a tty"
        with mock.patch("sys.stdout", sink), mock.patch("sys.stdin", source):
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


# --------------------------------------------------------------------------
# choosing a different pair of versions
# --------------------------------------------------------------------------

def _folder_of_versions(tmp_path: Path) -> Path:
    """1.0.0 is the old file; 1.2.0 and 1.2.1 are both the candidate content.

    So comparing 1.2.0 against 1.2.1 finds almost nothing, and comparing 1.0.0
    against 1.2.1 finds the real regressions. That difference is what proves a
    re-pick actually re-analyses rather than reprinting.
    """
    import shutil

    shutil.copy(ROOT / "localisations_1_2_0.plist", tmp_path / "localisations_1_0_0.plist")
    shutil.copy(ROOT / "localisations_1_2_1.plist", tmp_path / "localisations_1_2_0.plist")
    shutil.copy(ROOT / "localisations_1_2_1.plist", tmp_path / "localisations_1_2_1.plist")
    return tmp_path


def _drive(tmp_path, keys, typed=()):
    """Run interactively in a folder of versions, feeding keys and typed lines."""
    buffer = io.StringIO()
    key_stream, typed_stream = iter(keys), iter(typed)

    def console(*args, **kwargs):
        if kwargs.get("stderr"):
            return Console(stderr=True)
        return Console(width=92, file=buffer)

    cwd = Path.cwd()
    try:
        import os
        os.chdir(_folder_of_versions(tmp_path))
        with mock.patch.object(cli, "someone_is_watching", return_value=True), \
             mock.patch.object(cli, "read_key", lambda: next(key_stream)), \
             mock.patch.object(cli, "Console", console), \
             mock.patch("locheck.picker.Console", console), \
             mock.patch("builtins.input", lambda _="": next(typed_stream)):
            code = cli.main([])
    finally:
        import os
        os.chdir(cwd)
    return buffer.getvalue(), code


def test_v_lists_every_version_and_marks_the_current_pair(tmp_path):
    output, _ = _drive(tmp_path, keys=["v", "\x1b"], typed=[""])
    assert "Versions in this folder" in output
    for version in ("1.0.0", "1.2.0", "1.2.1"):
        assert version in output
    assert "currently the live side" in output
    assert "currently the candidate" in output


def test_choosing_a_different_pair_re_runs_the_check(tmp_path):
    """The proof it re-analyses: the verdict changes because the inputs changed."""
    output, code = _drive(tmp_path, keys=["v", "\x1b"], typed=["1 3"])
    verdicts = [line for line in output.splitlines() if "SHIP" in line]
    assert "DO NOT SHIP" not in verdicts[0], "1.2.0 vs 1.2.1 are near-identical here"
    assert "DO NOT SHIP" in verdicts[-1], "1.0.0 vs 1.2.1 holds the real regressions"
    assert code == 1, "the exit code follows the comparison last shown"


def test_pressing_enter_at_the_picker_keeps_the_current_pair(tmp_path):
    output, code = _drive(tmp_path, keys=["v", "\x1b"], typed=[""])
    verdicts = [line for line in output.splitlines() if "SHIP" in line]
    assert "DO NOT SHIP" not in verdicts[-1]
    assert code == 0


def test_nonsense_at_the_picker_is_re_prompted_then_abandoned(tmp_path):
    """Three bad answers give up rather than looping forever."""
    output, _ = _drive(tmp_path, keys=["v", "\x1b"], typed=["banana", "9 9", "1"])
    assert "Two numbers between 1 and" in output


def test_the_same_version_twice_is_rejected(tmp_path):
    """Comparing a file against itself tells the reader nothing."""
    from locheck.picker import _parse

    assert _parse("2 2", 4) is None
    assert _parse("1 4", 4) == (1, 4)
    assert _parse("1,4", 4) == (1, 4)
    assert _parse("0 4", 4) is None
    assert _parse("1 5", 4) is None
    assert _parse("just one", 4) is None


# --------------------------------------------------------------------------
# fitting a console opened by double-clicking
# --------------------------------------------------------------------------

def test_the_summary_fits_a_thirty_line_console():
    """A console opened from Explorer is about 30 lines tall.

    Going over means the header scrolls off the top, taking the names of the two
    files being compared with it - and a report about the wrong pair reads
    exactly like a report about the right one. The sample files produce eleven
    findings, which is a realistic release, so this is the case that has to fit.
    """
    buffer = io.StringIO()

    def console(*args, **kwargs):
        if kwargs.get("stderr"):
            return Console(stderr=True)
        return Console(width=120, file=buffer)

    with mock.patch.object(cli, "someone_is_watching", return_value=True), \
         mock.patch.object(cli, "read_key", return_value="\x1b"), \
         mock.patch.object(cli, "Console", console):
        cli.main([str(ROOT / "localisations_1_2_0.plist"),
                  str(ROOT / "localisations_1_2_1.plist")])

    height = len(buffer.getvalue().splitlines())
    assert height <= 30, f"summary is {height} lines and will scroll its header away"


def test_the_files_being_compared_are_named_at_the_bottom_too():
    """Insurance for a console shorter than the summary.

    The header can always scroll off on a small enough window, so the pair is
    named again immediately above the key legend, where the reader is looking.
    """
    output = _run_interactive("\x1b")
    tail = "\n".join(output.splitlines()[-6:])
    assert "localisations_1_2_0.plist" in tail
    assert "localisations_1_2_1.plist" in tail
    assert "(older)" in tail and "(newer)" in tail


@pytest.mark.parametrize("width", [80, 100, 120, 200, 240])
def test_the_report_fills_whatever_window_it_is_given(width):
    """No forced console size: the terminal is measured on every render.

    An earlier launcher pinned the console buffer to 120 columns, so maximising
    the window left the report boxed into the left 120 with dead space beside
    it. Nothing is allowed to overflow, and nothing is allowed to fall short.
    """
    buffer = io.StringIO()

    def console(*args, **kwargs):
        if kwargs.get("stderr"):
            return Console(stderr=True)
        return Console(width=width, file=buffer)

    with mock.patch.object(cli, "someone_is_watching", return_value=True),          mock.patch.object(cli, "read_key", return_value=""),          mock.patch.object(cli, "Console", console):
        cli.main([str(ROOT / "localisations_1_2_0.plist"),
                  str(ROOT / "localisations_1_2_1.plist")])

    lines = [line.rstrip() for line in buffer.getvalue().splitlines()]
    assert not [l for l in lines if len(l) > width], "content overflowed the window"
    assert max(len(l) for l in lines) == width, "content did not use the full window"


def test_the_compared_pair_stays_on_one_line_at_eighty_columns():
    """It wrapped to a second line reading just "ship)" before being shortened."""
    buffer = io.StringIO()

    def console(*args, **kwargs):
        if kwargs.get("stderr"):
            return Console(stderr=True)
        return Console(width=80, file=buffer)

    with mock.patch.object(cli, "someone_is_watching", return_value=True),          mock.patch.object(cli, "read_key", return_value=""),          mock.patch.object(cli, "Console", console):
        cli.main([str(ROOT / "localisations_1_2_0.plist"),
                  str(ROOT / "localisations_1_2_1.plist")])

    pair = [l for l in buffer.getvalue().splitlines() if "(older)" in l]
    assert len(pair) == 1
    assert "(newer)" in pair[0], "the whole comparison must fit on the one line"


# --------------------------------------------------------------------------
# a pair chosen backwards, and a pair chosen by hand
# --------------------------------------------------------------------------

def test_a_hand_picked_pair_stops_claiming_it_was_automatic(tmp_path):
    """The header said "newest two of N" after the reader had overruled it.

    They picked something else precisely because the automatic choice was not
    what they wanted; repeating the claim back is the tool insisting on a guess
    it has already lost.
    """
    output, _ = _drive(tmp_path, keys=["v", "\x1b"], typed=["1 3"])
    headers = [line for line in output.splitlines() if "Localisation release check" in line]
    assert "newest two of" in headers[0], "the first pick really was automatic"
    assert "chosen by hand" in headers[-1]
    assert "newest two of" not in headers[-1]


def test_comparing_backwards_is_labelled_as_a_rollback(tmp_path):
    """Picking "2 1" is legitimate - it asks what shipping the old file undoes.

    But every finding then reads inverted, so it has to say so. Nothing about
    the report itself signals the direction, and a reader who does not notice
    will read regressions as fixes.
    """
    output, _ = _drive(tmp_path, keys=["v", "\x1b"], typed=["3 1"])
    # Collapsed first: the notice is prose inside a panel, so where it wraps
    # depends on how long the file names beside it happen to be. Asserting on
    # the raw text made this fail the moment the version column grew.
    flat = " ".join(output.split())
    assert "rollback" in flat
    assert "the candidate is the older release" in flat


def test_a_forwards_comparison_is_not_labelled_a_rollback(tmp_path):
    output, _ = _drive(tmp_path, keys=["v", "\x1b"], typed=["1 3"])
    assert "rollback" not in output


def test_the_rollback_notice_does_not_fire_on_the_normal_run():
    assert "rollback" not in _run_interactive("\x1b")


def test_explicit_arguments_given_backwards_are_still_labelled():
    """Two paths on the command line are honoured as typed, and still flagged."""
    buffer = io.StringIO()

    def console(*args, **kwargs):
        if kwargs.get("stderr"):
            return Console(stderr=True)
        return Console(width=110, file=buffer)

    with mock.patch.object(cli, "someone_is_watching", return_value=True), \
         mock.patch.object(cli, "read_key", return_value="\x1b"), \
         mock.patch.object(cli, "Console", console):
        cli.main([str(ROOT / "localisations_1_2_1.plist"),
                  str(ROOT / "localisations_1_2_0.plist")])

    output = buffer.getvalue()
    assert "rollback" in output
    assert "newest two of" not in output, "explicit paths were not discovered"
