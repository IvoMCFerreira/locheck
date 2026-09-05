"""Validation for the language codes used as keys in a localisation file.

This exists because of a failure mode that is invisible to every other check in
this tool: a translation that is present, complete, correct - and delivered
under a code the client never asks for.

The client requests a language by its BCP 47 tag, which starts with an ISO 639-1
code. `ja` is Japanese. `jp` is the ISO 3166 *country* code for Japan and is not
a language code at all. A file that ships its Japanese under `jp` looks fine in
every diff and every spot check, and reaches no one.

Country-for-language is by far the most common way to get this wrong, so those
cases get named explicitly in the message rather than a generic "unknown code".
"""

from __future__ import annotations

# ISO 639-1. Two letters, one per language.
ISO_639_1 = frozenset("""
aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr
cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu
gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv ka kg ki kj kk
kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms
mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro
ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl
tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu
""".split())

#: Country codes routinely mistaken for the language spoken there.
COMMON_MISTAKES = {
    "jp": "ja",  # Japan  -> Japanese
    "cn": "zh",  # China  -> Chinese
    "kr": "ko",  # Korea  -> Korean
    "gr": "el",  # Greece -> Greek
    "cz": "cs",  # Czechia-> Czech
    "dk": "da",  # Denmark-> Danish
    "se": "sv",  # Sweden -> Swedish
    "ua": "uk",  # Ukraine-> Ukrainian
    "uk": "en",  # United Kingdom is not a language code; English is `en`
    "vn": "vi",  # Vietnam-> Vietnamese
    "ir": "fa",  # Iran   -> Persian
    "rs": "sr",  # Serbia -> Serbian
}


def problem_with(code: str) -> tuple[str, str] | None:
    """Return (reason, suggested action) for a bad code, or None if it is fine.

    Region subtags are accepted: `pt-BR` and `en-US` are normal, well-formed
    BCP 47 tags. Only the language part is validated.
    """
    if not code:
        return ("empty language code", "Remove the empty key or give it a real code.")

    primary = code.split("-")[0].split("_")[0].lower()

    if primary in ISO_639_1:
        return None

    if primary in COMMON_MISTAKES:
        correct = COMMON_MISTAKES[primary]
        return (
            "'" + primary + "' is a country code, not a language code",
            "Rename '" + code + "' to '" + correct + "'. Clients ask for '"
            + correct + "', so nothing currently reaches these players.",
        )

    return (
        "'" + primary + "' is not an ISO 639-1 language code",
        "Check what the client actually requests for this language and rename the key.",
    )
