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
from functools import lru_cache

from .model import Problem, Severity

REFERENCE_LANG = "en-US"


def reference_for(entry: dict[str, str]) -> str | None:
    """The source string for an entry, tolerating how the code was cased.

    `en-US`, `en-us` and `EN_US` are the same language to every client that
    parses BCP 47, and files edited by many hands drift on this. Matching the
    constant exactly meant one lowercase key turned every placeholder check in
    that entry off while reporting only "no reference language".
    """
    if REFERENCE_LANG in entry:
        return entry[REFERENCE_LANG]
    wanted = REFERENCE_LANG.lower().replace("_", "-")
    for code, text in entry.items():
        if code.lower().replace("_", "-") == wanted:
            return text
    return None


def _is_reference(lang: str) -> bool:
    return lang.lower().replace("_", "-") == REFERENCE_LANG.lower()

# printf-style placeholders, close to what Apple/Foundation accepts:
#   %@  %d  %u  %.2f  %1$@  %ld  %%
_PLACEHOLDER = re.compile(
    r"""
    %                          # start
    (?:(\d+)\$)?               # positional argument, e.g. %1$@
    [-+0#]*                    # flags - see note below on the missing space
    \d*                        # width
    (?:\.\d+)?                 # precision
    (?:hh|h|ll|l|L|z|j|t|q)?   # length modifier
    ([@diouxXeEfgGaAcsp%])     # conversion
    """,
    re.VERBOSE,
)
# printf allows a space flag ("% d" prints a leading space before positives) and
# the first version of this pattern accepted it. That made "50% off" parse as the
# octal placeholder "% o", and "50% de réduction" as "% d" - so the tool reported
# a type mismatch between two perfectly good marketing strings. The space flag is
# vanishingly rare in UI copy and "% <letter>" in prose is not, so it is dropped.
# A bare percent now falls through to the malformed branch, which is correct: in
# a format string a literal percent has to be written "%%".

# The in-house substitution syntax used for share text: A:[in Country/in the world]
_TOKEN = re.compile(r"([A-Za-z]+):\[([^\]]*)\]")


def _reads_as_percentage(text: str, index: int) -> bool:
    """Whether the '%' at `index` is a percent sign in prose.

    "50% off", "100% complete", and the French "50 %" with its non-breaking
    space are ordinary copy, and a promotions release is full of them. Reporting
    every one buries the real findings under a wall of items nobody intends to
    act on, which is precisely how a release checklist becomes something people
    skip.

    A digit immediately before the sign is a strong signal and a cheap one. It
    does not weaken the checks that matter: the two genuine corruptions in the
    sample data - "Commence dans % ..." and "До начала %..." - have a letter
    before the sign, not a digit, and are still reported.
    """
    cursor = index - 1
    if cursor >= 0 and text[cursor] in "   ":  # fr/ru put a space before %
        cursor -= 1
    return cursor >= 0 and text[cursor].isdigit()


@lru_cache(maxsize=8192)
def _scan(text: str) -> tuple[tuple[str, ...], tuple[int, ...]]:
    """The scan itself, memoised.

    Every rule compares a translation against the reference string, so on a file
    with fifteen languages the reference is scanned fifteen times per entry. The
    inputs are immutable strings and the work is pure, so caching turns that back
    into once. On a 150k-string file this is most of the runtime.
    """
    tokens: list[str] = []
    consumed: set[int] = set()
    for match in _PLACEHOLDER.finditer(text):
        consumed.update(range(match.start(), match.end()))
        if match.group(2) != "%":
            tokens.append(match.group(0))
    malformed = [
        i
        for i, ch in enumerate(text)
        if ch == "%" and i not in consumed and not _reads_as_percentage(text, i)
    ]
    return tuple(tokens), tuple(malformed)


def scan_placeholders(text: str) -> tuple[list[str], list[int]]:
    """Return (argument placeholders, offsets of stray '%' signs).

    `%%` is an escaped literal percent, so it is consumed but not returned as an
    argument - a translator writing "100%%" is not passing a value to the client.
    Any '%' the grammar could not consume is malformed, which is the failure mode
    that actually crashes clients - except a percentage in prose, see above.

    Fresh lists are handed back so a caller can never mutate the cached result.
    """
    tokens, malformed = _scan(text)
    return list(tokens), list(malformed)


def _signature(tokens: list[str]) -> Counter:
    """Placeholders by conversion type and count, ignoring width and padding.

    `%@` vs `%u` is a type mismatch and can crash. Two `%u` vs one is a real
    difference. Width and padding are cosmetic, so they are not compared.
    """
    return Counter(tok[-1] for tok in tokens)


def _uses_positional(tokens: list[str]) -> bool:
    return any("$" in tok for tok in tokens)


def _order(tokens: list[str]) -> list[str]:
    return [tok[-1] for tok in tokens]


def _placeholders_agree(ref_tokens: list[str], tokens: list[str]) -> bool:
    """Whether a translation's placeholders are safe against the source's.

    Order matters unless the string says otherwise. A client filling
    non-positional placeholders walks them left to right, so turning
    "Give %@ to %u" into "Donne %u à %@" hands a string where an integer is
    expected. Comparing multisets alone - which this did at first - calls that
    pair identical and waves a crash through.

    Positional placeholders (`%1$@`) exist precisely so translators can reorder,
    so when either side uses them only the multiset is compared.
    """
    if _uses_positional(ref_tokens) or _uses_positional(tokens):
        return _signature(ref_tokens) == _signature(tokens)
    return _order(ref_tokens) == _order(tokens)


def _show(tokens: list[str]) -> str:
    return " ".join(tokens) if tokens else "none"


def rule_empty(key: str, lang: str, text: str, entry: dict[str, str]) -> Problem | None:
    """An empty translation renders as blank space in the client."""
    if text.strip():
        return None
    return Problem(
        code="string.empty",
        title="Empty translation",
        detail="the string is empty - players on '" + lang + "' see blank space",
        severity=Severity.BLOCKER,
        action=(
            "Restore the '" + lang + "' translation, or remove the key so the "
            "client falls back to " + REFERENCE_LANG + "."
        ),
    )


def rule_placeholders(
    key: str, lang: str, text: str, entry: dict[str, str]
) -> Problem | None:
    """Placeholders must be well formed and match the reference language."""
    if not text.strip():
        return None  # rule_empty owns this string; don't report it twice

    tokens, malformed = scan_placeholders(text)

    reference = reference_for(entry)
    ref_tokens, ref_malformed = ([], []) if reference is None else scan_placeholders(reference)
    usable_reference = (
        reference is not None and reference.strip() and not ref_malformed
        and not _is_reference(lang)
    )

    if malformed:
        near = ", ".join(repr(text[i : i + 5]) for i in malformed[:3])
        # Is this entry a format string at all? If the source language passes
        # values to the client, a stray '%' is a truncated placeholder and a
        # crash. If nothing in the entry uses placeholders, it is almost always
        # a literal percent in marketing copy - still worth escaping, not worth
        # blocking a release over.
        formatted = bool(ref_tokens) or bool(tokens)
        return Problem(
            code="placeholder.malformed",
            title="Malformed placeholder" if formatted else "Unescaped percent sign",
            detail=(
                "stray '%' near " + near
                + (
                    " - the client may crash formatting this"
                    if formatted
                    else " - harmless unless this string is format-processed"
                )
            ),
            severity=Severity.BLOCKER if formatted else Severity.LOW,
            action=(
                "Compare with " + REFERENCE_LANG + " (" + _show(ref_tokens) + ") and "
                "restore the placeholder."
                if formatted and usable_reference
                else "Write a literal percent sign as %% so it survives formatting."
            ),
            spans=tuple((i, i + 1) for i in malformed),
        )

    if not usable_reference:
        return None

    if _placeholders_agree(ref_tokens, tokens):
        return None

    if _signature(ref_tokens) == _signature(tokens):
        # Same placeholders, different order, and no positional markers to make
        # that safe. The client fills them left to right.
        return Problem(
            code="placeholder.order",
            title="Placeholders in a different order",
            detail=(
                REFERENCE_LANG + " orders them " + " ".join(_order(ref_tokens))
                + ", this one " + " ".join(_order(tokens))
                + " - values are filled in order, so they will land in the wrong slots"
            ),
            severity=Severity.BLOCKER,
            action=(
                "Restore the " + REFERENCE_LANG + " order, or make every placeholder "
                "positional (%1$..., %2$...) so the order can safely differ."
            ),
        )

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
        action="Rewrite the '" + lang + "' string: " + ", then ".join(changes) + ".",
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
                "brackets do not match: " + str(text.count("[")) + " opening, "
                + str(text.count("]")) + " closing - the client will render the raw "
                "markup to the player"
            ),
            severity=Severity.BLOCKER,
            action="Close the bracket so every X:[a/b] slot is complete.",
            spans=tuple(unclosed),
        )

    reference = reference_for(entry)
    if _is_reference(lang) or reference is None:
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


def rule_line_structure(
    key: str, lang: str, text: str, entry: dict[str, str]
) -> Problem | None:
    """Line breaks are layout, not language.

    These strings carry literal `\\n` escapes that the client turns into line
    breaks, and the surrounding UI is built around that shape. A translation
    that drops them all renders as one long run of text in a box designed for
    five lines. Unlike word count, `\\n` count is not something a language can
    legitimately differ on, so this compares directly against en-US.
    """
    if not text.strip() or _is_reference(lang):
        return None
    reference = reference_for(entry)
    if reference is None or not reference.strip():
        return None

    expected, found = reference.count("\\n"), text.count("\\n")
    if expected == 0:
        return None
    # Only complain about losing most of the structure. Gaining a break is a
    # translator wrapping a longer word, and dropping one of four is a
    # legitimate re-wrap - neither is a defect. Halving or collapsing the line
    # count is not something a translation does on purpose.
    if found > expected // 2:
        return None

    return Problem(
        code="layout.line_breaks",
        title="Line breaks lost",
        detail=(
            REFERENCE_LANG + " breaks across " + str(expected + 1) + " lines, this one "
            "across " + str(found + 1) + " - it will not wrap as the UI expects"
        ),
        severity=Severity.MEDIUM,
        action="Re-add the \\n breaks so the text wraps like " + REFERENCE_LANG + ".",
    )


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def _normalise_number(raw: str) -> str:
    """`4.0`, `4`, `4,0` are the same number. `1.000` is a thousand.

    Locales disagree about decimal separators, and a tool that cannot tell
    `0,5` from `0.5` would flag every European translation of every price.
    """
    parts = raw.replace(",", ".").split(".")
    if len(parts) == 1:
        return parts[0].lstrip("0") or "0"
    if len(parts[-1]) in (1, 2):  # a 1-2 digit tail is a decimal fraction
        whole = "".join(parts[:-1]).lstrip("0") or "0"
        fraction = parts[-1].rstrip("0")
        return whole + ("." + fraction if fraction else "")
    return "".join(parts).lstrip("0") or "0"  # 3-digit groups are thousands


#: Below this, a number is as likely to be spelled out as written in digits.
#:
#: Found the hard way: the Turkish pool rules render "Rack 1" and "Rack 2" as
#: "İlk üçgen" and "İkinci üçgen" - first and second, as words. The English
#: source does the same thing itself ("every five consecutive pots"). Comparing
#: digits below ten therefore flags correct translations, and a MEDIUM section
#: full of correct translations is one the releaser stops reading.
#:
#: The cost is real: a translation that dropped "0.5" or turned 1 into 2 slips
#: through. That is the trade, and it is the right way round - this check exists
#: to catch a mistyped game rule like "3 seconds" for "30 seconds", and every
#: number worth mistyping that way has two or more digits.
_SPELLABLE_BELOW = 10


@lru_cache(maxsize=8192)
def _number_counts(text: str, significant_only: bool) -> tuple[tuple[str, int], ...]:
    found: Counter = Counter()
    for match in _NUMBER.finditer(text):
        value = _normalise_number(match.group(0))
        if significant_only and float(value) < _SPELLABLE_BELOW:
            continue
        found[value] += 1
    return tuple(found.items())


def _numbers(text: str, significant_only: bool = False) -> Counter:
    """Memoised for the same reason as the placeholder scan; see `_scan`.

    A fresh Counter is built each call so subtraction by the caller cannot
    disturb the cache.
    """
    return Counter(dict(_number_counts(text, significant_only)))


def rule_numbers(key: str, lang: str, text: str, entry: dict[str, str]) -> Problem | None:
    """Numbers in the source that vanished from the translation.

    Game rules live in these strings - "30 seconds penalty", "150 points". A
    translated rule that disagrees with the English one is a support ticket, not
    a crash, but it is still wrong in the player's face.

    Deliberately one-directional: only numbers *missing* from the translation are
    reported. Languages routinely add digits the source spells out ("five
    consecutive" becomes "5 連続"), and flagging that would bury the real signal.
    """
    if not text.strip() or _is_reference(lang):
        return None
    reference = reference_for(entry)
    if reference is None or not reference.strip():
        return None

    missing = _numbers(reference, significant_only=True) - _numbers(text)
    if not missing:
        return None

    lost = sorted(set(missing.elements()))
    quoted = ", ".join(
        n + ' ("' + phrase + '")' if (phrase := _phrase_around(reference, n)) else n
        for n in lost
    )
    return Problem(
        code="content.numbers",
        title="Number missing from translation",
        detail=REFERENCE_LANG + " mentions " + quoted + ", this translation does not",
        severity=Severity.MEDIUM,
        action=(
            "Check the '" + lang + "' text states the same values as " + REFERENCE_LANG
            + " - a mistyped game rule reads as a bug to the player."
        ),
    )


def _phrase_around(text: str, number: str, width: int = 34) -> str | None:
    """The words either side of a number in the source.

    Without this the reader is told "en-US mentions 30" and left to find which
    of several numbers that is in a 500-character rules blob. With it they get
    "a 30 seconds penalty" and know exactly which sentence to compare.
    """
    for match in _NUMBER.finditer(text):
        if _normalise_number(match.group(0)) != number:
            continue
        start = max(0, match.start() - width // 2)
        end = min(len(text), match.end() + width // 2)
        return ("…" if start else "") + text[start:end].replace("\\n", " ").strip() + (
            "…" if end < len(text) else ""
        )
    return None


def rule_token_options(
    key: str, lang: str, text: str, entry: dict[str, str]
) -> Problem | None:
    """Each `X:[a/b/c]` slot must offer as many choices as the source does.

    The client picks slot N by index. If en-US offers three options and the
    translation offers two, the client either indexes out of bounds or silently
    shows the wrong one.
    """
    if not text.strip() or _is_reference(lang):
        return None
    reference = reference_for(entry)
    if reference is None:
        return None

    expected = {m.group(1): m.group(2).count("/") + 1 for m in _TOKEN.finditer(reference)}
    if not expected:
        return None
    found = {m.group(1): m.group(2).count("/") + 1 for m in _TOKEN.finditer(text)}

    for label, count in sorted(expected.items()):
        if label in found and found[label] != count:
            return Problem(
                code="token.option_count",
                title="Wrong number of options in a token",
                detail=(
                    label + ":[...] offers " + str(found[label]) + " choices, "
                    + REFERENCE_LANG + " offers " + str(count)
                    + " - the client selects by index"
                ),
                severity=Severity.MEDIUM,
                action=(
                    "Make " + label + ":[...] offer " + str(count) + " options in the "
                    "same order as " + REFERENCE_LANG + "."
                ),
            )
    return None


#: A translation this much longer than the source will not fit a UI built for it.
_OVERFLOW_RATIO = 2.5


def rule_length(key: str, lang: str, text: str, entry: dict[str, str]) -> Problem | None:
    """Translations far longer than the source overflow the box they live in.

    Only *longer* is reported. Languages legitimately differ in density - a
    Japanese string is routinely a third the length of its English source - so
    flagging short translations would fire on every CJK entry and teach the
    releaser to skim past this check.

    The threshold is generous on purpose. German runs ~30% longer than English
    as a matter of course; 2.5x is well past normal variation.
    """
    if not text.strip() or _is_reference(lang):
        return None
    reference = reference_for(entry)
    if reference is None or len(reference.strip()) < 10:
        return None

    ratio = len(text) / len(reference)
    if ratio < _OVERFLOW_RATIO:
        return None

    return Problem(
        code="layout.too_long",
        title="Much longer than the source",
        detail=(
            str(len(text)) + " characters against " + str(len(reference)) + " in "
            + REFERENCE_LANG + " (" + f"{ratio:.1f}" + "x) - likely to overflow its UI"
        ),
        severity=Severity.MEDIUM,
        action="Check this still fits its button or label, or ask for a shorter phrasing.",
    )


#: Evaluated in order; the first rule to fire owns the string, so one broken
#: string never produces three overlapping findings. Ordered by severity, so a
#: crash is reported ahead of a layout wobble on the same string.
STRING_RULES = [
    rule_empty,
    rule_placeholders,
    rule_tokens,
    rule_token_options,
    rule_line_structure,
    rule_numbers,
    rule_length,
]
