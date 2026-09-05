"""File formats, encodings, filesystem oddities and code validation.

Everything here was found by probing rather than by reading. The two real bugs
it turned up are locked at the bottom: a padded language key reported as an
unknown language, and a table of "country codes mistaken for languages" that
listed three genuine language codes.
"""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locheck import langcodes  # noqa: E402
from locheck.engine import analyse  # noqa: E402
from locheck.loader import LoadError, load  # noqa: E402
from locheck.rules import _normalise_number, scan_placeholders  # noqa: E402

PAYLOAD = {"version": "1.0.1", "localisations": {"k": {"en-US": "Buy %@", "fr": "Achete %@"}}}


# --------------------------------------------------------------------------
# formats and encodings
# --------------------------------------------------------------------------

def test_a_binary_plist_is_read_like_any_other(tmp_path):
    """plist is a format, not a syntax - and Xcode writes binary by default."""
    path = tmp_path / "binary.plist"
    path.write_bytes(plistlib.dumps(PAYLOAD, fmt=plistlib.FMT_BINARY))
    assert load(path).entries["k"]["en-US"] == "Buy %@"


def test_a_utf8_byte_order_mark_is_tolerated(tmp_path):
    """Windows editors add one silently."""
    path = tmp_path / "bom.plist"
    path.write_bytes(b"\xef\xbb\xbf" + plistlib.dumps(PAYLOAD))
    assert load(path).entries["k"]["en-US"] == "Buy %@"


def test_a_lying_encoding_declaration_fails_cleanly(tmp_path):
    path = tmp_path / "lying.plist"
    path.write_bytes(plistlib.dumps(PAYLOAD).replace(b'encoding="UTF-8"', b'encoding="UTF-16"'))
    with pytest.raises(LoadError):
        load(path)


def test_a_directory_is_not_mistaken_for_a_file(tmp_path):
    with pytest.raises(LoadError):
        load(tmp_path)


def test_unicode_paths_and_file_names_work(tmp_path):
    folder = tmp_path / "dossier_\u00e9\u4e2d\u6587"
    folder.mkdir()
    path = folder / "localisations_\u00e9_1_2_0.plist"
    path.write_bytes(plistlib.dumps(PAYLOAD))
    assert load(path).entries


def test_a_read_only_file_is_readable(tmp_path):
    """The tool never writes, so a checked-out read-only file must still work."""
    path = tmp_path / "ro.plist"
    path.write_bytes(plistlib.dumps(PAYLOAD))
    os.chmod(path, 0o444)
    assert load(path).entries


def test_a_language_key_repeated_inside_one_entry_is_reported(tmp_path):
    """plistlib keeps the last silently; the whole first translation vanishes."""
    live = tmp_path / "live.plist"
    live.write_bytes(plistlib.dumps({"version": "1.0.0",
                                     "localisations": {"k": {"en-US": "First"}}}))
    cand = tmp_path / "cand.plist"
    cand.write_text(
        "<?xml version='1.0'?><plist version='1.0'><dict>"
        "<key>version</key><string>1.0.1</string>"
        "<key>localisations</key><dict><key>k</key><dict>"
        "<key>en-US</key><string>First</string>"
        "<key>en-US</key><string>Second</string>"
        "</dict></dict></dict></plist>",
        encoding="utf-8",
    )
    codes = {f.code for f in analyse(load(live), load(cand)).findings}
    assert "key.duplicated" in codes


# --------------------------------------------------------------------------
# number and placeholder parsing at the edges
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0", "0"), ("000", "0"), ("0.0", "0"), ("1.", "1"), ("007", "7"),
        ("00.50", "0.5"), ("0.50", "0.5"),
        ("1.000.000", "1000000"), ("1,234,567", "1234567"),
    ],
)
def test_number_normalisation_edges(raw, expected):
    assert _normalise_number(raw) == expected


@pytest.mark.parametrize(
    "text, tokens, malformed",
    [
        ("%", [], 1),
        ("%%", [], 0),
        ("%%%", [], 1),          # the third has nothing to pair with
        ("%%%%", [], 0),
        ("%@%@", ["%@", "%@"], 0),
        ("%1$", [], 1),          # positional marker with no conversion
        ("%-10.4f", ["%-10.4f"], 0),
        ("%#x", ["%#x"], 0),
        ("50%%off", [], 0),
        ("%\u00a0", [], 1),      # percent then a non-breaking space
    ],
)
def test_placeholder_parsing_edges(text, tokens, malformed):
    found, stray = scan_placeholders(text)
    assert found == tokens
    assert len(stray) == malformed


# --------------------------------------------------------------------------
# language codes - the two bugs probing found
# --------------------------------------------------------------------------

@pytest.mark.parametrize("code", ["jp", "cn", "gr", "cz", "dk", "ua", "vn", "ir", "rs"])
def test_country_codes_that_are_not_languages_are_named(code):
    reason, action = langcodes.problem_with(code)
    assert "country code" in reason
    assert langcodes.COMMON_MISTAKES[code] in action


@pytest.mark.parametrize("code", ["kr", "se", "uk", "tk"])
def test_codes_that_are_ambiguous_but_valid_are_left_alone(code):
    """kr is Kanuri, se is Northern Sami, uk is Ukrainian, tk is Turkmen.

    Each is also a country abbreviation someone might mean instead, but each is
    a real ISO 639-1 code - so flagging one would report a correct file as
    broken. An earlier version listed all three as mistakes, and described `uk`
    as "United Kingdom, use en", which is simply wrong.
    """
    assert code in langcodes.ISO_639_1
    assert langcodes.problem_with(code) is None


@pytest.mark.parametrize(
    "code", ["en", "EN-us", "pt_BR", "zh-Hans-CN", "en-US-POSIX", "  fr  ",
             "fil", "haw", "eng", "x-custom"],
)
def test_well_formed_codes_are_not_flagged(code):
    """Including three-letter subtags and keys padded by sloppy hand-editing.

    `fil` and `haw` have no two-letter equivalent, and `"  fr  "` is French with
    a whitespace typo - not an unknown language, which is how it once read.
    """
    assert langcodes.problem_with(code) is None


@pytest.mark.parametrize("code", ["zz", "qq"])
def test_unknown_two_letter_codes_are_flagged(code):
    assert langcodes.problem_with(code) is not None


@pytest.mark.parametrize("code", ["123", "12", "", "   "])
def test_keys_that_are_not_codes_at_all_are_flagged(code):
    assert langcodes.problem_with(code) is not None


def test_the_mistakes_table_holds_no_real_language_codes():
    """A guard on the data, not the logic.

    Any entry that is also a valid ISO 639-1 code is unreachable - the validity
    check runs first - so it is dead weight that reads as coverage.
    """
    overlap = sorted(set(langcodes.COMMON_MISTAKES) & langcodes.ISO_639_1)
    assert not overlap, f"unreachable and misleading entries: {overlap}"
