"""Tests for working out which two files to compare.

The failure that matters here is getting the order backwards. If the candidate
is treated as the baseline, every regression reads as a fix and every fix as a
regression - and the report looks entirely plausible. Sorting by version rather
than by argument order removes that whole class of mistake, so it is worth
testing properly.

The second thing under test is that ambiguity produces a refusal rather than a
guess. A confident report about the wrong pair of files is worse than being
asked to type two paths.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locheck.__main__ import resolve  # noqa: E402
from locheck.discover import (  # noqa: E402
    DiscoveryError,
    find_baseline_for,
    find_pair,
    version_of,
)


def _make(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_bytes(
        plistlib.dumps({"version": "0.0.0", "localisations": {"k": {"en-US": "Hi"}}})
    )
    return path


# --------------------------------------------------------------------------
# reading versions off file names
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("localisations_1_2_0.plist", (1, 2, 0)),
        ("localisations_1.2.0.plist", (1, 2, 0)),
        ("loc_10_20_30.plist", (10, 20, 30)),
        ("no-version-here.plist", None),
        ("localisations.plist", None),
    ],
)
def test_version_is_read_from_the_file_name(name, expected):
    assert version_of(Path(name)) == expected


def test_versions_sort_numerically_not_alphabetically():
    """1.2.10 comes after 1.2.9. Sorting the names as text would get this wrong."""
    assert version_of(Path("l_1_2_9.plist")) < version_of(Path("l_1_2_10.plist"))


# --------------------------------------------------------------------------
# picking the pair
# --------------------------------------------------------------------------

def test_the_two_newest_are_picked_in_the_right_order(tmp_path):
    for name in ("l_1_0_0.plist", "l_1_2_0.plist", "l_1_2_1.plist"):
        _make(tmp_path, name)

    live, candidate, considered = find_pair(tmp_path)
    assert live.name == "l_1_2_0.plist"
    assert candidate.name == "l_1_2_1.plist"
    assert considered == 3


def test_double_digit_versions_are_ordered_correctly(tmp_path):
    """The case alphabetical sorting gets wrong, and the one that ships in a year."""
    for name in ("l_1_2_8.plist", "l_1_2_9.plist", "l_1_2_10.plist"):
        _make(tmp_path, name)

    live, candidate, _ = find_pair(tmp_path)
    assert live.name == "l_1_2_9.plist"
    assert candidate.name == "l_1_2_10.plist"


def test_one_argument_finds_the_release_it_replaces(tmp_path):
    for name in ("l_1_0_0.plist", "l_1_2_0.plist", "l_1_2_1.plist"):
        _make(tmp_path, name)

    assert find_baseline_for(tmp_path / "l_1_2_1.plist").name == "l_1_2_0.plist"
    # Asking about an older file compares it against what came before *it*.
    assert find_baseline_for(tmp_path / "l_1_2_0.plist").name == "l_1_0_0.plist"


# --------------------------------------------------------------------------
# refusing rather than guessing
# --------------------------------------------------------------------------

def test_an_empty_directory_is_refused(tmp_path):
    with pytest.raises(DiscoveryError, match="no .plist files"):
        find_pair(tmp_path)


def test_a_single_file_is_refused(tmp_path):
    _make(tmp_path, "l_1_2_0.plist")
    with pytest.raises(DiscoveryError, match="only one"):
        find_pair(tmp_path)


def test_unversioned_names_are_refused_rather_than_guessed(tmp_path):
    """Modification time is not evidence of which release is newer."""
    _make(tmp_path, "alpha.plist")
    _make(tmp_path, "beta.plist")
    with pytest.raises(DiscoveryError, match="version numbers"):
        find_pair(tmp_path)


def test_the_oldest_file_has_nothing_to_compare_against(tmp_path):
    _make(tmp_path, "l_1_2_0.plist")
    _make(tmp_path, "l_1_2_1.plist")
    with pytest.raises(DiscoveryError, match="nothing older"):
        find_baseline_for(tmp_path / "l_1_2_0.plist")


def test_an_unversioned_candidate_is_refused(tmp_path):
    _make(tmp_path, "l_1_2_0.plist")
    _make(tmp_path, "whatever.plist")
    with pytest.raises(DiscoveryError, match="no version number"):
        find_baseline_for(tmp_path / "whatever.plist")


# --------------------------------------------------------------------------
# the argument contract
# --------------------------------------------------------------------------

def test_two_arguments_are_taken_literally_and_not_reordered(tmp_path, monkeypatch):
    """Explicit beats clever: if someone passes both, honour exactly what they said.

    Reordering them "helpfully" would make it impossible to deliberately compare
    a release against a newer one, which is how you check a rollback.
    """
    monkeypatch.chdir(tmp_path)
    older = _make(tmp_path, "l_1_2_0.plist")
    newer = _make(tmp_path, "l_1_2_1.plist")

    live, candidate, considered = resolve([str(newer), str(older)])
    assert (live.name, candidate.name) == (newer.name, older.name)
    assert considered == 0, "nothing was guessed, so nothing to report"


def test_no_arguments_discovers_and_says_so(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make(tmp_path, "l_1_2_0.plist")
    _make(tmp_path, "l_1_2_1.plist")

    live, candidate, considered = resolve([])
    assert (live.name, candidate.name) == ("l_1_2_0.plist", "l_1_2_1.plist")
    assert considered == 2, "a guess must be reported to the reader"


def test_a_missing_single_argument_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(DiscoveryError, match="no such file"):
        resolve(["not-here.plist"])


# --------------------------------------------------------------------------
# folders holding more than one kind of file
# --------------------------------------------------------------------------

def test_unrelated_versioned_plists_are_not_treated_as_releases(tmp_path):
    """The bug this locks: a game config outranked the real candidate.

    Sorting every versioned .plist together by version alone meant a
    `gameconfig_9_0_0.plist` sitting in the folder was picked as the newest
    "release", and the tool produced a confident report comparing a localisation
    file against a config file. Files are grouped by name first now.
    """
    _make(tmp_path, "localisations_1_2_0.plist")
    _make(tmp_path, "localisations_1_2_1.plist")
    _make(tmp_path, "gameconfig_9_0_0.plist")
    _make(tmp_path, "Info.plist")

    live, candidate, considered = find_pair(tmp_path)
    assert live.name == "localisations_1_2_0.plist"
    assert candidate.name == "localisations_1_2_1.plist"
    assert considered == 2, "the config file is not one of the versions considered"


def test_one_argument_ignores_other_families_too(tmp_path):
    _make(tmp_path, "localisations_1_2_0.plist")
    _make(tmp_path, "localisations_1_2_1.plist")
    _make(tmp_path, "gameconfig_1_2_0.plist")

    found = find_baseline_for(tmp_path / "localisations_1_2_1.plist")
    assert found.name == "localisations_1_2_0.plist"


def test_two_comparable_families_are_refused_rather_than_guessed(tmp_path):
    """Both could plausibly be what the reader meant, so ask instead of picking."""
    for name in ("localisations_1_2_0.plist", "localisations_1_2_1.plist",
                 "gameconfig_1_0_0.plist", "gameconfig_1_1_0.plist"):
        _make(tmp_path, name)

    with pytest.raises(DiscoveryError, match="several sets"):
        find_pair(tmp_path)


def test_ten_versions_pick_the_newest_two_and_report_the_count(tmp_path):
    for minor, patch in [(0, 0), (1, 0), (1, 1), (1, 2), (2, 0),
                         (2, 1), (2, 2), (2, 9), (2, 10), (3, 0)]:
        _make(tmp_path, f"localisations_1_{minor}_{patch}.plist")

    live, candidate, considered = find_pair(tmp_path)
    assert live.name == "localisations_1_2_10.plist"
    assert candidate.name == "localisations_1_3_0.plist"
    assert considered == 10


def test_a_single_version_beside_other_files_explains_itself(tmp_path):
    _make(tmp_path, "localisations_1_2_0.plist")
    _make(tmp_path, "Info.plist")
    with pytest.raises(DiscoveryError, match="only one version"):
        find_pair(tmp_path)
