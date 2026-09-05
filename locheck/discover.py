"""Works out which two files to compare so nobody has to type them.

Release files are named `localisations_1_2_0.plist`, so the tool can read the
versions off the filenames, sort them, and pick the newest as the candidate and
the one before it as the live baseline. That turns the command into `locheck`.

Two things this is careful about:

* It never guesses silently. Whatever it picks is printed before the report, so
  a wrong guess is visible rather than quietly producing a report about the
  wrong pair of files.
* It refuses rather than guesses badly. If the versions are ambiguous it says
  so and asks for the two paths, which is a worse experience for five seconds
  and a better one than a confident report about the wrong release.

Getting the order backwards is the failure that matters most here: every
regression would read as a fix and every fix as a regression, and the report
would look plausible. Sorting by version rather than by argument order removes
that whole class of mistake.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

PATTERN = "*.plist"

_VERSION = re.compile(r"(\d+)[._](\d+)[._](\d+)")


class DiscoveryError(Exception):
    """No sensible pair of files could be found."""


def version_of(path: Path) -> tuple[int, ...] | None:
    """`localisations_1_2_10.plist` -> (1, 2, 10), or None if unversioned.

    Compared as integers, so 1.2.10 correctly sorts after 1.2.9 - which sorting
    the filenames as text would get wrong.
    """
    match = _VERSION.search(path.stem)
    return tuple(int(part) for part in match.groups()) if match else None


def family_of(path: Path) -> str:
    """The file name with its version stripped out.

    `localisations_1_2_0` and `localisations_1_2_1` are the same family;
    `gameconfig_9_0_0` is not. Without this, a folder holding both a
    localisation file and any other versioned plist sorts them into one list by
    version alone - and a `gameconfig_9_0_0.plist` sitting beside
    `localisations_1_2_1.plist` gets picked as the candidate, producing a
    confident report comparing two unrelated files.
    """
    return _VERSION.sub("", path.stem).strip("_-. ").lower()


def candidates_in(directory: Path) -> list[Path]:
    """Versioned plist files in a directory, oldest release first."""
    versioned = [(version_of(p), p) for p in sorted(directory.glob(PATTERN))]
    return [p for version, p in sorted(v for v in versioned if v[0] is not None)]


def families_in(directory: Path) -> dict[str, list[Path]]:
    """Versioned files grouped by name, each group oldest release first."""
    grouped: dict[str, list[Path]] = {}
    for path in candidates_in(directory):
        grouped.setdefault(family_of(path), []).append(path)
    return grouped


class Selection(NamedTuple):
    live: Path
    candidate: Path
    #: How many releases of this family were on disk, so the report can say so.
    considered: int


def find_pair(directory: Path) -> Selection:
    """Pick the two newest releases of a single family of files."""
    families = families_in(directory)
    comparable = {name: files for name, files in families.items() if len(files) >= 2}

    if len(comparable) == 1:
        files = next(iter(comparable.values()))
        return Selection(files[-2], files[-1], len(files))

    if len(comparable) > 1:
        names = ", ".join(sorted(comparable))
        raise DiscoveryError(
            "found several sets of versioned files here (" + names + ") and "
            "cannot tell which one you mean. Pass the two paths explicitly, "
            "live one first."
        )

    everything = sorted(directory.glob(PATTERN))
    if not everything:
        raise DiscoveryError(
            "no .plist files here. Run this from the folder holding your "
            "localisation files, or drag the two files onto it."
        )
    if len(everything) == 1:
        raise DiscoveryError(
            "only one .plist file here (" + everything[0].name + "). Two are "
            "needed: the version that is live, and the one about to ship."
        )
    if families:
        only = sorted(families)[0]
        raise DiscoveryError(
            "only one version of '" + only + "' here. Two are needed: the "
            "version that is live, and the one about to ship."
        )
    raise DiscoveryError(
        "found " + str(len(everything)) + " .plist files but could not read "
        "version numbers from their names, so it is not clear which is live "
        "and which is new. Pass the two paths explicitly, live one first."
    )


def find_baseline_for(candidate: Path) -> Path:
    """Given the file about to ship, find the release it replaces."""
    target = version_of(candidate)
    if target is None:
        raise DiscoveryError(
            "no version number in the name '" + candidate.name + "', so the "
            "release it replaces cannot be identified. Pass both paths, live "
            "one first."
        )

    family = family_of(candidate)
    earlier = [
        path
        for path in candidates_in(candidate.parent)
        if family_of(path) == family
        and (found := version_of(path)) is not None
        and found < target
    ]
    if not earlier:
        raise DiscoveryError(
            "nothing older than " + candidate.name + " to compare against. "
            "Pass the live file explicitly as the first argument."
        )
    return earlier[-1]
