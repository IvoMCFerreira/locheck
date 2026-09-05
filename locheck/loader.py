"""Reads a localisation plist, tolerating the mess real files arrive in.

The brief warns that these files are edited by many hands and may be missing
or contradictory in places. The policy here: anything the tool can recover
from becomes a warning printed alongside the report; only a file we genuinely
cannot compare raises.
"""

from __future__ import annotations

import plistlib
import re
from dataclasses import dataclass, field
from pathlib import Path


class LoadError(Exception):
    """The file cannot be compared at all."""


@dataclass
class LocFile:
    path: Path
    version: str | None
    entries: dict[str, dict[str, str]]
    warnings: list[str] = field(default_factory=list)

    @property
    def languages(self) -> set[str]:
        langs: set[str] = set()
        for entry in self.entries.values():
            langs |= set(entry)
        return langs

    @property
    def string_count(self) -> int:
        return sum(len(entry) for entry in self.entries.values())


_FILENAME_VERSION = re.compile(r"(\d+)[._](\d+)[._](\d+)")


def version_from_filename(path: Path) -> str | None:
    """`localisations_1_2_1.plist` -> `1.2.1`. Used to cross-check the version field."""
    match = _FILENAME_VERSION.search(path.stem)
    return ".".join(match.groups()) if match else None


def load(path: str | Path) -> LocFile:
    path = Path(path)
    try:
        raw = plistlib.loads(path.read_bytes())
    except FileNotFoundError:
        raise LoadError(f"{path}: no such file") from None
    except Exception as exc:
        raise LoadError(f"{path}: not a readable plist ({exc})") from None

    if not isinstance(raw, dict):
        raise LoadError(f"{path}: top level is {type(raw).__name__}, expected a dict")

    warnings: list[str] = []

    version = raw.get("version")
    if version is None:
        warnings.append("no 'version' field")
    elif not isinstance(version, str):
        warnings.append(f"'version' is {type(version).__name__}, coerced to string")
        version = str(version)

    block = raw.get("localisations")
    if block is None:
        raise LoadError(f"{path}: no 'localisations' dict - nothing to check")
    if not isinstance(block, dict):
        raise LoadError(
            f"{path}: 'localisations' is {type(block).__name__}, expected a dict"
        )

    entries: dict[str, dict[str, str]] = {}
    for key, langs in block.items():
        if not isinstance(langs, dict):
            warnings.append(
                f"entry {key}: is {type(langs).__name__}, not a dict - skipped"
            )
            continue
        cleaned: dict[str, str] = {}
        for lang, text in langs.items():
            if text is None:
                warnings.append(f"{key}/{lang}: null value - read as empty string")
                text = ""
            elif not isinstance(text, str):
                warnings.append(
                    f"{key}/{lang}: {type(text).__name__} value - coerced to string"
                )
                text = str(text)
            cleaned[lang] = text
        if not cleaned:
            warnings.append(f"entry {key}: no languages at all")
        entries[key] = cleaned

    return LocFile(path=path, version=version, entries=entries, warnings=warnings)
