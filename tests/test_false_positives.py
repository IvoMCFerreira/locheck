"""A corpus of localisation content that is CORRECT, asserted to stay silent.

The failure that actually kills a tool like this is not a missed bug, it is a
false alarm. A releaser who is shown one bogus blocker learns that the tool
cries wolf, and the next real blocker gets waved through. Every check here
earns its place by being quiet on content that is fine.

Each case is a pattern that turns up in real game localisation: prices in
locales that use a comma for decimals, percentages in promo copy, CJK text with
no spaces, right-to-left scripts, markup, emoji, and the ordinary fact that
languages are different lengths.

If a case in this file starts failing, the tool has become noisier - which is a
regression even though nothing crashed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locheck.rules import STRING_RULES  # noqa: E402

REF = "en-US"


def problems_for(entry: dict[str, str], lang: str) -> list:
    """Every problem the rules find with one string, as codes."""
    return [
        p.code
        for rule in STRING_RULES
        if (p := rule("k", lang, entry[lang], entry)) is not None
    ]


# --------------------------------------------------------------------------
# money, percentages and numbers - where locale conventions differ most
# --------------------------------------------------------------------------

GOOD_CONTENT = [
    pytest.param(
        {REF: "Get 1,000 coins for $4.99", "de": "Hol dir 1.000 Münzen für 4,99 $"},
        "de",
        id="thousands-and-decimal-separators-swap-in-german",
    ),
    pytest.param(
        {REF: "Save 50% today", "fr": "Économisez 50 % aujourd'hui"},
        "fr",
        id="percent-sign-spacing-differs-in-french",
    ),
    pytest.param(
        {REF: "Sale ends in 12:30", "pt-BR": "A promoção termina em 12:30"},
        "pt-BR",
        id="clock-times",
    ),
    pytest.param(
        {REF: "You are 100% complete", "es": "Has completado el 100%"},
        "es",
        id="percent-in-both-source-and-translation",
    ),
    pytest.param(
        {REF: "Reach level 25 to unlock", "ru": "Достигните 25 уровня, чтобы открыть"},
        "ru",
        id="same-number-different-word-order",
    ),
    pytest.param(
        {REF: "1st place", "pt-BR": "1º lugar"},
        "pt-BR",
        id="ordinal-suffixes-differ",
    ),
    # The source spells a small number out; the translation uses a digit.
    pytest.param(
        {REF: "Pot five balls in a row", "jp": "5 球連続でポケット"},
        "jp",
        id="source-spells-out-what-translation-digitises",
    ),
    # And the reverse - this is the Turkish "İlk üçgen" case from the real file.
    pytest.param(
        {REF: "Rack 1 and Rack 2 give bonuses", "tk": "İlk ve İkinci üçgen bonus verir"},
        "tk",
        id="translation-spells-out-what-source-digitises",
    ),
]


# --------------------------------------------------------------------------
# placeholders that are fine
# --------------------------------------------------------------------------

GOOD_CONTENT += [
    pytest.param(
        {REF: "Welcome back, %@!", "fr": "Bon retour, %@ !"},
        "fr",
        id="single-placeholder-with-french-spacing",
    ),
    pytest.param(
        {REF: "%@ sent you %u coins", "de": "%@ hat dir %u Münzen geschickt"},
        "de",
        id="two-placeholders-same-order",
    ),
    pytest.param(
        {REF: "Give %1$@ to %2$u players", "fr": "Pour %2$u joueurs, donne %1$@"},
        "fr",
        id="positional-placeholders-legitimately-reordered",
    ),
    pytest.param(
        {REF: "You earned %.2f gems", "es": "Has ganado %.2f gemas"},
        "es",
        id="precision-specifier",
    ),
    pytest.param(
        {REF: "Boost is %d%% stronger", "it": "Il potenziamento è %d%% più forte"},
        "it",
        id="escaped-percent-next-to-a-placeholder",
    ),
    pytest.param(
        {REF: "Level %ld", "ru": "Уровень %ld"},
        "ru",
        id="length-modifier",
    ),
    # Same conversion type twice - swapping them is harmless, so do not flag it.
    pytest.param(
        {REF: "%@ beat %@", "de": "%@ schlug %@"},
        "de",
        id="two-placeholders-of-identical-type",
    ),
]


# --------------------------------------------------------------------------
# scripts, length and layout
# --------------------------------------------------------------------------

GOOD_CONTENT += [
    pytest.param(
        {REF: "Watch a short video to earn coins", "jp": "動画を見てコインを獲得"},
        "jp",
        id="japanese-is-far-shorter-than-english",
    ),
    pytest.param(
        {
            REF: "Settings and notifications",
            "de": "Einstellungen und Benachrichtigungen",
        },
        "de",
        id="german-is-longer-but-well-within-normal",
    ),
    pytest.param(
        {REF: "Play now", "ar": "العب الآن"},
        "ar",
        id="right-to-left-script",
    ),
    pytest.param(
        {REF: r"Line one\nline two\nline three", "fr": r"Ligne un\nligne deux\nligne trois"},
        "fr",
        id="line-breaks-preserved",
    ),
    # Dropping one break of four is a re-wrap, not a defect.
    pytest.param(
        {
            REF: r"one\ntwo\nthree\nfour\nfive",
            "de": r"eins\nzwei\ndrei\nvier fünf",
        },
        "de",
        id="one-line-break-fewer-after-rewrap",
    ),
    pytest.param(
        {REF: "Claim your reward 🎁", "pt-BR": "Resgate sua recompensa 🎁"},
        "pt-BR",
        id="emoji",
    ),
    pytest.param(
        {REF: "Press [OK] to continue", "es": "Pulsa [OK] para continuar"},
        "es",
        id="square-brackets-that-are-not-substitution-tokens",
    ),
    pytest.param(
        {REF: "<b>Bonus</b> round", "fr": "Manche <b>bonus</b>"},
        "fr",
        id="inline-markup",
    ),
    pytest.param(
        {
            REF: "Rank 1 A:[at home/worldwide] B:[today/this week/all time]",
            "de": "Platz 1 A:[zu Hause/weltweit] B:[heute/diese Woche/insgesamt]",
        },
        "de",
        id="substitution-tokens-fully-mirrored",
    ),
]


@pytest.mark.parametrize("entry, lang", GOOD_CONTENT)
def test_correct_content_is_not_flagged(entry, lang):
    found = problems_for(entry, lang)
    assert found == [], (
        "This content is correct but the tool complained: " + ", ".join(found)
    )


@pytest.mark.parametrize("entry, lang", GOOD_CONTENT)
def test_the_source_string_is_not_flagged_either(entry, lang):
    """The reference language runs through the same rules and must also be clean."""
    found = problems_for(entry, REF)
    assert found == [], (
        "The en-US source was flagged: " + ", ".join(found)
    )


# --------------------------------------------------------------------------
# whitespace at the edges of a string
# --------------------------------------------------------------------------

def test_edge_whitespace_is_reported_when_the_source_has_none():
    """Found by auditing the sample data: jp in 1981dc5a starts with a space.

    Almost always a stray keystroke while editing - invisible in a diff, and
    nobody reads a translated string closely enough to notice.
    """
    from locheck.rules import rule_edge_whitespace

    entry = {REF: "Rank 1", "jp": " 1 \u4f4d"}
    problem = rule_edge_whitespace("k", "jp", entry["jp"], entry)
    assert problem is not None
    assert problem.severity.name == "LOW", "an indent does not hold up a release"


def test_edge_whitespace_matching_the_source_is_left_alone():
    """A source that ends in a space is one the client concatenates onto."""
    from locheck.rules import rule_edge_whitespace

    entry = {REF: "Hello ", "fr": "Bonjour "}
    assert rule_edge_whitespace("k", "fr", entry["fr"], entry) is None


def test_ordinary_strings_are_not_reported_for_whitespace():
    from locheck.rules import rule_edge_whitespace

    entry = {REF: "Play now", "fr": "Jouer maintenant"}
    assert rule_edge_whitespace("k", "fr", entry["fr"], entry) is None
