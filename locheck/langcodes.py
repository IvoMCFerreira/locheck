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
#:
#: Every entry here is a string that is NOT a language code, so naming it is
#: unambiguously helpful. The tempting additions are the ones left out:
#:
#:   kr  Korea, but also Kanuri
#:   se  Sweden, but also Northern Sami
#:   uk  United Kingdom, but also - and officially - Ukrainian
#:
#: Those three are real ISO 639-1 codes, so flagging them would report a correct
#: file as broken. The check gives them up rather than risk that, which is the
#: same call made for `tk` (Turkmen) in the sample data: valid code, suspicious
#: content, not something a list of names can settle.
COMMON_MISTAKES = {
    "jp": "ja",  # Japan    -> Japanese
    "cn": "zh",  # China    -> Chinese
    "gr": "el",  # Greece   -> Greek
    "cz": "cs",  # Czechia  -> Czech
    "dk": "da",  # Denmark  -> Danish
    "ua": "uk",  # Ukraine  -> Ukrainian
    "vn": "vi",  # Vietnam  -> Vietnamese
    "ir": "fa",  # Iran     -> Persian
    "rs": "sr",  # Serbia   -> Serbian
}


def problem_with(code: str) -> tuple[str, str] | None:
    """Return (reason, suggested action) for a bad code, or None if it is fine.

    Region subtags are accepted: `pt-BR`, `en-US` and `zh-Hans-CN` are normal,
    well-formed BCP 47 tags. Only the primary language subtag is validated.

    Only *two-letter* primary subtags are judged. That is where the mistake this
    check exists for lives - `jp` for Japanese, `cn` for Chinese, `kr` for
    Korean - because two-letter country codes and two-letter language codes look
    identical and are constantly confused. Three-letter subtags are left alone:
    `fil` for Filipino and `haw` for Hawaiian are legitimate ISO 639-2 codes with
    no two-letter equivalent, and flagging them would be a false alarm on a
    correct file. `x-` private-use tags are left alone for the same reason.
    """
    if not code or not code.strip():
        return ("empty language code", "Remove the empty key or give it a real code.")

    # Sloppy hand-editing leaves whitespace around keys. A padded "  fr  " is
    # French with a typo in the file, not an unknown language.
    primary = code.strip().replace("_", "-").split("-")[0].lower()

    if primary in ISO_639_1:
        return None

    if primary in COMMON_MISTAKES:
        correct = COMMON_MISTAKES[primary]
        return (
            "'" + primary + "' is a country code, not a language code",
            "Rename '" + code.strip() + "' to '" + correct + "'. Clients ask for '"
            + correct + "', so nothing currently reaches these players.",
        )

    if len(primary) == 2 and primary.isalpha():
        return (
            "'" + primary + "' is not an ISO 639-1 language code",
            "Check what the client actually requests for this language and rename the key.",
        )

    if not any(character.isalpha() for character in primary):
        return (
            "'" + code.strip() + "' is not a language code at all",
            "Replace this key with the language code the client asks for.",
        )

    return None
