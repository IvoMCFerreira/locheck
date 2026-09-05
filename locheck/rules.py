"""Rules that judge one string, using its siblings as reference.

A rule answers exactly one question: *is this string wrong right now?* It is
given the string, its language, and the whole entry it belongs to (so it can
compare against the reference language). It knows nothing about the previous
release.

That ignorance is deliberate. Deciding whether a problem is a regression, a
pre-existing wart, or something this release *fixed* is the engine's job. Split
that way, one rule serves all three verdicts - and the tool stops treating
"changed" as a synonym for "risky".

Each rule returns at most one Problem, so one broken string never produces
three overlapping findings.
"""

from __future__ import annotations

import re
from collections import Counter

from .model import Problem, Severity

REFERENCE_LANG = "en-US"

# printf-style placeholders, close to what Apple/Foundation accepts:
#   %@  %d  %u  %.2f  %1$@  %ld  %%
_PLACEHOLDER = re.compile(
    r"""
    %                          # start
    (?:(\d+)\$)?               # positional argument, e.g. %1$@
    [-+ 0#]*                   # flags
    \d*                        # width
    (?:\.\d+)?                 # precision
    (?:hh|h|ll|l|L|z|j|t|q)?   # length modifier
    ([@diouxXeEfgGaAcsp%])     # conversion
    """,
    re.VERBOSE,
)

# The in-house substitution syntax used for share text: A:[in Country/in the world]
_TOKEN = re.compile(r"([A-Za-z]+):\[([^\]]*)\]")


def scan_placeholders(text: str) -> tuple[list[str], list[int]]:
    """Return (argument placeholders, offsets of stray '%' signs).

    `%%` is an escaped literal percent, so it is consumed but not returned as an
    argument - a translator writing "100%%" is not passing a value to the client.
    Any '%' the grammar could not consume is malformed, which is the failure mode
    that actually crashes clients.
    """
    tokens: list[str] = []
    consumed: set[int] = set()
    for match in _PLACEHOLDER.finditer(text):
        consumed.update(range(match.start(), match.end()))
        if match.group(2) != "%":
            tokens.append(match.group(0))
    malformed = [i for i, ch in enumerate(text) if ch == "%" and i not in consumed]
    return tokens, malformed


def _signature(tokens: list[str]) -> Counter:
    """Compare placeholders by conversion type and count, ignoring width/flags.

    `%@` vs `%u` is a type mismatch and can crash. `%2$@` vs `%@` is a reordering
    the client handles. Two `%u` vs one is a real difference. Width and padding
    are cosmetic, so they are not part of the comparison.
    """
    return Counter(tok[-1] for tok in tokens)


def _show(tokens: list[str]) -> str:
    return " ".join(tokens) if tokens else "none"


def rule_empty(key: str, lang: str, text: str, entry: dict[str, str]) -> Problem | None:
    """An empty translation renders as blank space in the client."""
    if text.strip():
        return None
    return Problem(
        code="string.empty",
        title="Empty translation",
        detail="string is empty - " + lang + " players see blank space here",
        severity=Severity.BLOCKER,
        action=(
            "Restore the " + lang + " translation, or drop the " + lang + " key from "
            "this entry so the client falls back to " + REFERENCE_LANG + "."
        ),
    )


def rule_placeholders(
    key: str, lang: str, text: str, entry: dict[str, str]
) -> Problem | None:
    """Placeholders must be well formed and match the reference language."""
    if not text.strip():
        return None  # rule_empty owns this string; don't report it twice

    tokens, malformed = scan_placeholders(text)

    reference = entry.get(REFERENCE_LANG)
    ref_tokens, ref_malformed = ([], []) if reference is None else scan_placeholders(reference)
    usable_reference = (
        reference is not None and reference.strip() and not ref_malformed and lang != REFERENCE_LANG
    )

    if malformed:
        near = ", ".join(repr(text[i : i + 5]) for i in malformed[:3])
        fix = (
            "Compare with " + REFERENCE_LANG + " (" + _show(ref_tokens) + ") and restore "
            "the placeholder, or escape a literal percent sign as %%."
            if usable_reference
            else "Complete the placeholder, or escape a literal percent sign as %%."
        )
        return Problem(
            code="placeholder.malformed",
            title="Malformed placeholder",
            detail="stray '%' near " + near + " - the client may crash formatting this",
            severity=Severity.BLOCKER,
            action=fix,
            spans=tuple((i, i + 1) for i in malformed),
        )

    if not usable_reference:
        return None

    if _signature(ref_tokens) == _signature(tokens):
        return None

    missing = _signature(ref_tokens) - _signature(tokens)
    extra = _signature(tokens) - _signature(ref_tokens)
    changes = []
    if missing:
        changes.append("add " + " ".join("%" + c for c in sorted(missing.elements())))
    if extra:
        changes.append("remove " + " ".join("%" + c for c in sorted(extra.elements())))

    return Problem(
        code="placeholder.parity",
        title="Placeholder mismatch",
        detail=REFERENCE_LANG + " has " + _show(ref_tokens) + ", this has " + _show(tokens),
        severity=Severity.BLOCKER,
        action="Rewrite the " + lang + " string so it " + " and ".join(changes) + ".",
    )


def rule_tokens(
    key: str, lang: str, text: str, entry: dict[str, str]
) -> Problem | None:
    """In-house `A:[a/b]` substitution slots must stay closed and complete."""
    if not text.strip():
        return None

    if text.count("[") != text.count("]"):
        unclosed = [(m.start(), m.start() + 1) for m in re.finditer(r"\[", text)]
        return Problem(
            code="token.unbalanced",
            title="Unclosed substitution token",
            detail=(
                str(text.count("[")) + " '[' vs " + str(text.count("]")) + " ']' - "
                "the client will render the raw markup to the player"
            ),
            severity=Severity.BLOCKER,
            action="Close the bracket so every X:[a/b] slot is complete.",
            spans=tuple(unclosed),
        )

    reference = entry.get(REFERENCE_LANG)
    if lang == REFERENCE_LANG or reference is None:
        return None

    expected = {m.group(1) for m in _TOKEN.finditer(reference)}
    if not expected:
        return None

    found = {m.group(1) for m in _TOKEN.finditer(text)}
    missing = expected - found
    if missing:
        wanted = ", ".join(
            m.group(0) for m in _TOKEN.finditer(reference) if m.group(1) in missing
        )
        return Problem(
            code="token.missing",
            title="Missing substitution token",
            detail=(
                REFERENCE_LANG + " substitutes " + ", ".join(sorted(expected))
                + ", this one is missing " + ", ".join(sorted(missing))
            ),
            severity=Severity.BLOCKER,
            action="Add the missing slot, mirroring " + REFERENCE_LANG + ": " + wanted,
        )
    return None


#: Evaluated in order, one Problem per string wins.
STRING_RULES = [rule_empty, rule_placeholders, rule_tokens]
