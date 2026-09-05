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
        detail="string is empty - this language renders blank",
        severity=Severity.BLOCKER,
    )


def rule_placeholders(
    key: str, lang: str, text: str, entry: dict[str, str]
) -> Problem | None:
    """Placeholders must be well formed and match the reference language."""
    if not text.strip():
        return None  # rule_empty owns this string; don't report it twice

    tokens, malformed = scan_placeholders(text)

    if malformed:
        near = ", ".join(repr(text[i : i + 5]) for i in malformed[:3])
        return Problem(
            code="placeholder.malformed",
            title="Malformed placeholder",
            detail=f"stray '%' near {near} - the client may crash formatting this",
            severity=Severity.BLOCKER,
        )

    reference = entry.get(REFERENCE_LANG)
    if lang == REFERENCE_LANG or reference is None or not reference.strip():
        return None

    ref_tokens, ref_malformed = scan_placeholders(reference)
    if ref_malformed:
        return None  # reference itself is broken; comparing to it is meaningless

    if _signature(ref_tokens) == _signature(tokens):
        return None

    return Problem(
        code="placeholder.parity",
        title="Placeholder mismatch",
        detail=f"{REFERENCE_LANG} has {_show(ref_tokens)}, this has {_show(tokens)}",
        severity=Severity.BLOCKER,
    )


def rule_tokens(
    key: str, lang: str, text: str, entry: dict[str, str]
) -> Problem | None:
    """In-house `A:[a/b]` substitution slots must stay closed and complete."""
    if not text.strip():
        return None

    if text.count("[") != text.count("]"):
        return Problem(
            code="token.unbalanced",
            title="Unclosed substitution token",
            detail=(
                f"{text.count('[')} '[' vs {text.count(']')} ']' - "
                "the client will render the raw markup"
            ),
            severity=Severity.BLOCKER,
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
        return Problem(
            code="token.missing",
            title="Missing substitution token",
            detail=(
                f"{REFERENCE_LANG} substitutes {sorted(expected)}, "
                f"this is missing {sorted(missing)}"
            ),
            severity=Severity.BLOCKER,
        )
    return None


#: Evaluated in order, one Problem per string wins.
STRING_RULES = [rule_empty, rule_placeholders, rule_tokens]
