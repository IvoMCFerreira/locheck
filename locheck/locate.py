"""Maps entries in a plist back to their line numbers in the source file.

`plistlib` gives you the data and throws the positions away, which is fine for
parsing and useless for fixing. A releaser who is told "the Russian countdown
string is broken" still has to search a 400-line XML file for it. A releaser who
is told `localisations_1_2_1.plist:18` just goes there.

So the file gets parsed a second time with expat, which does expose line numbers,
building an index of dict-key paths:

    ("version",)                        -> 6
    ("localisations", "2b82...")        -> 10
    ("localisations", "2b82...", "ru")  -> 18

This is best-effort. If the second parse fails for any reason the index comes
back empty and the report simply omits line numbers rather than failing.
"""

from __future__ import annotations

from pathlib import Path
from xml.parsers import expat

# Element names that hold a value rather than containing more structure.
_SCALARS = {"string", "integer", "real", "true", "false", "data", "date", "array"}


class LineIndex:
    """Line numbers for dict-key paths in a plist, keyed by path tuple."""

    def __init__(
        self,
        lines: dict[tuple[str, ...], int] | None = None,
        duplicates: list[tuple[tuple[str, ...], int, int]] | None = None,
    ):
        self._lines = lines or {}
        #: (path, first line, repeat line) for keys that appear twice.
        self.duplicates = duplicates or []

    def __bool__(self) -> bool:
        return bool(self._lines)

    def of(self, *path: str) -> int | None:
        """Line number for a key path, or None if it could not be resolved."""
        return self._lines.get(tuple(p for p in path if p is not None))

    def entry(self, key: str) -> int | None:
        return self.of("localisations", key)

    def string(self, key: str, lang: str) -> int | None:
        return self.of("localisations", key, lang)


def build(path: str | Path) -> LineIndex:
    lines: dict[tuple[str, ...], int] = {}
    duplicates: list[tuple[tuple[str, ...], int, int]] = []
    key_path: list[str | None] = []
    pending: list[str | None] = [None]  # the key whose value we are about to meet
    buffer: list[str] = []

    parser = expat.ParserCreate()

    def record(name: str | None, line: int) -> None:
        if name is None:
            return
        full = tuple(p for p in key_path if p is not None) + (name,)
        # A repeated key is silent data loss: plistlib keeps the last one and
        # says nothing, so a text ID pasted twice quietly discards a whole
        # entry's worth of translation. This walk is the only place that can
        # see it, because the parsed dict has already thrown the evidence away.
        if full in lines:
            duplicates.append((full, lines[full], line))
            return
        lines[full] = line

    def start(name: str, _attrs: dict) -> None:
        if name == "key":
            buffer.clear()
            return
        if name == "dict":
            record(pending[0], parser.CurrentLineNumber)
            key_path.append(pending[0])  # None for the unnamed root dict
            pending[0] = None
            return
        if name in _SCALARS:
            record(pending[0], parser.CurrentLineNumber)
            pending[0] = None

    def characters(data: str) -> None:
        buffer.append(data)

    def end(name: str) -> None:
        if name == "key":
            pending[0] = "".join(buffer).strip()
            buffer.clear()
        elif name == "dict" and key_path:
            key_path.pop()

    parser.StartElementHandler = start
    parser.CharacterDataHandler = characters
    parser.EndElementHandler = end

    try:
        parser.Parse(Path(path).read_bytes(), True)
    except (expat.ExpatError, OSError):
        return LineIndex()  # line numbers are a nicety, never a reason to fail

    return LineIndex(lines, _outermost(duplicates))


def _outermost(
    duplicates: list[tuple[tuple[str, ...], int, int]]
) -> list[tuple[tuple[str, ...], int, int]]:
    """Drop duplicates that are merely inside another duplicate.

    Repeating an entry repeats every language key inside it, so a single
    duplicated text ID otherwise reports once for the ID and once for each of
    its languages. Only the outermost repeat is a decision someone made; the
    rest are its shadow.
    """
    kept: list[tuple[tuple[str, ...], int, int]] = []
    for entry in sorted(duplicates, key=lambda d: len(d[0])):
        path = entry[0]
        if any(path[: len(seen[0])] == seen[0] for seen in kept):
            continue
        kept.append(entry)
    return kept
