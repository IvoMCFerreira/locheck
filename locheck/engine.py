"""Turns per-string verdicts into release findings.

The whole argument of this tool is in `_classify`. The same Problem means three
different things to a releaser depending on what the live version looked like:

    live OK     -> candidate broken   this release broke it           act now
    live broken -> candidate broken   already live, not a regression  backlog
    live broken -> candidate OK       this release fixed it           good news

A tool that only diffs cannot tell those apart, so it shouts at all three. That
is the failure mode the brief warns about, and this function is the answer to it.

Findings carry the full untruncated strings. Deciding how much of one to show is
the report's job, not this module's.
"""

from __future__ import annotations

import re

from . import langcodes, locate
from .discover import version_of
from .loader import LocFile, version_from_filename
from .model import Finding, Report, Severity
from .rules import REFERENCE_LANG, STRING_RULES, reference_for


def _classify(old_problem, new_problem, existed_before, key, lang, before, after,
              rollback=False):
    """Compare a string's problem state across the two releases.

    The verdicts are the same in both directions - what changes is what they
    mean to the reader. Shipping forward, a new problem was *introduced*; rolling
    back, the same problem *comes back*, and a "fix" is something the rollback
    would undo rather than something a translator did. Wording it for the
    direction is not decoration: read with the forward phrasing, a rollback
    report says a crash was fixed when it is about to be reintroduced.
    """
    if new_problem is None:
        if old_problem is None:
            return None
        return Finding(
            severity=Severity.RESOLVED,
            code=old_problem.code,
            title=("Rolling back fixes: " if rollback else "Fixed: ") + old_problem.title.lower(),
            detail=(
                "broken in what is live now (" + old_problem.detail + "); the older "
                "file does not have this problem"
                if rollback
                else "was broken in the live version (" + old_problem.detail + "), now correct"
            ),
            key=key,
            lang=lang,
            before=before,
            after=after,
            action=(
                "Nothing to do - rolling back happens to repair this."
                if rollback
                else "Nothing to do. Flagged so a placeholder change here is not mistaken for a break."
            ),
            spans=old_problem.spans,
        )

    if old_problem is not None and old_problem.code == new_problem.code:
        return Finding(
            severity=Severity.INFO,
            code=new_problem.code,
            title="Pre-existing: " + new_problem.title.lower(),
            detail=new_problem.detail + " - present in both files, either way",
            key=key,
            lang=lang,
            before=before,
            after=after,
            action="Worth a ticket, but it does not block this release. " + new_problem.action,
            spans=new_problem.spans,
        )

    if rollback:
        origin = "comes back if you roll back" if existed_before else "in the older file"
    else:
        origin = "introduced by this release" if existed_before else "new content"

    return Finding(
        severity=new_problem.severity,
        code=new_problem.code,
        title=new_problem.title,
        detail=new_problem.detail + " (" + origin + ")",
        key=key,
        lang=lang,
        before=before,
        after=after,
        action=new_problem.action,
        spans=new_problem.spans,
    )


def _direction_is_backwards(baseline: LocFile, candidate: LocFile) -> bool:
    """Whether the candidate is an older release than the file it replaces.

    Read from the file names rather than the declared `version` fields, because
    the field is exactly what a release forgets to bump - in the sample data both
    files declare 1.2.0, so the fields cannot tell the two apart at all.
    """
    live = version_of(baseline.path)
    new = version_of(candidate.path)
    return bool(live and new and new < live)


def _string_findings(baseline: LocFile, candidate: LocFile, index, rollback=False):
    findings = []
    changed = 0

    for key, langs in candidate.entries.items():
        base_entry = baseline.entries.get(key)
        for lang, text in sorted(langs.items()):
            before = base_entry.get(lang) if base_entry else None
            existed_before = before is not None
            if existed_before and before != text:
                changed += 1

            # Every rule runs. One string still produces one finding - the worst
            # of them - because the summary table is a ship/no-ship count and a
            # string listed twice reads as two problems. The rest ride along on
            # `also`, so whoever opens the string to fix the blocker sees
            # everything wrong with it in one pass instead of rediscovering the
            # layout issue two releases later.
            for_this_string = []
            for rule in STRING_RULES:
                new_problem = rule(key, lang, text, langs)
                old_problem = rule(key, lang, before, base_entry) if existed_before else None
                finding = _classify(
                    old_problem, new_problem, existed_before, key, lang, before, text,
                    rollback=rollback,
                )
                if finding is not None:
                    finding.line = index.string(key, lang)
                    finding.reference = reference_for(langs)
                    for_this_string.append(finding)

            if not for_this_string:
                continue
            for_this_string.sort(key=lambda f: f.severity.value)
            primary, *rest = for_this_string
            primary.also = rest
            findings.append(primary)

    return findings, changed


_COSMETIC = re.compile(r"[^\w%@]+", re.UNICODE)


def _substantive_change(old: str, new: str) -> bool:
    """Whether a source edit could plausibly invalidate its translations.

    Retyping "Play now" as "Play now!" does not make the French wrong, and
    reporting it teaches the releaser that this check is noise. Only casing,
    punctuation and whitespace are treated as cosmetic - every word, digit and
    placeholder still counts, so "30 seconds" becoming "3 seconds" is a
    substantive change even though it is a one-character edit.
    """
    normalise = lambda s: _COSMETIC.sub(" ", s.lower()).strip()
    return normalise(old) != normalise(new)


def _file_findings(baseline: LocFile, candidate: LocFile, index, rollback=False):
    findings = []

    # --- version -----------------------------------------------------------
    expected = version_from_filename(candidate.path)
    if candidate.version and candidate.version == baseline.version:
        detail = "candidate declares the same version as the live file"
        action = "Bump the version string before shipping."
        if expected and expected != candidate.version:
            detail += ", but the filename says " + expected
            action = "Set the version string to " + expected + " to match the filename."
        findings.append(
            Finding(
                severity=Severity.HIGH,
                code="version.not_bumped",
                title="Version not bumped",
                detail=detail + " - clients and CDN caches may never pick this up",
                before=baseline.version,
                after=candidate.version,
                line=index.of("version"),
                action=action,
            )
        )

    # --- languages dropped across the whole file ---------------------------
    # Reported once per language, not once per key. A language dropped from every
    # entry is one decision by one person, and should read as one line.
    dropped_everywhere = baseline.languages - candidate.languages
    for lang in sorted(dropped_everywhere):
        affected = sorted(k for k, e in baseline.entries.items() if lang in e)
        findings.append(
            Finding(
                severity=Severity.BLOCKER,
                code="language.dropped",
                title="Language removed from the whole file",
                detail=(
                    "in {n} of {total} entries on the live side and none on the other"
                    " - {verb}"
                ).format(
                    n=len(affected), total=len(baseline.entries),
                    verb=("rolling back takes this language away from every "
                          + lang + " player")
                    if rollback
                    else "every " + lang + " player loses all of this text",
                ),
                lang=lang,
                action=(
                    "Confirm the rollback is worth losing " + lang + " for."
                    if rollback
                    else "Confirm this was intended. If not, restore " + lang + " in: "
                    + ", ".join(k[:8] for k in affected)
                ),
            )
        )

    # --- languages dropped from individual keys ----------------------------
    for key, base_entry in baseline.entries.items():
        cand_entry = candidate.entries.get(key)
        if cand_entry is None:
            continue
        lost = set(base_entry) - set(cand_entry) - dropped_everywhere
        for lang in sorted(lost):
            findings.append(
                Finding(
                    severity=Severity.HIGH,
                    code="language.missing_from_key",
                    title="Language lost from a key",
                    detail="translated here in the live version, absent in the candidate",
                    key=key,
                    lang=lang,
                    before=base_entry[lang],
                    line=index.entry(key),
                    action=(
                        "Restore the " + lang + " string, or confirm this key is meant "
                        "to fall back to " + REFERENCE_LANG + " for " + lang + " players."
                    ),
                )
            )

    # --- keys removed ------------------------------------------------------
    for key in sorted(set(baseline.entries) - set(candidate.entries)):
        findings.append(
            Finding(
                severity=Severity.HIGH,
                code="key.removed",
                title="Text ID removed",
                detail=(
                    "rolling back removes this text ID - any client requesting it "
                    "shows a blank"
                    if rollback
                    else "was live and is gone - any client still requesting it shows a blank"
                ),
                key=key,
                before=reference_for(baseline.entries[key]),
                action=(
                    "Confirm no shipped client build still requests this ID. Old app "
                    "versions outlive content updates."
                ),
            )
        )

    # --- keys defined twice in the same file -------------------------------
    for path_parts, first, repeat in index.duplicates:
        name = path_parts[-1]
        findings.append(
            Finding(
                severity=Severity.HIGH,
                code="key.duplicated",
                title="Defined twice in the file",
                detail=(
                    "'" + name + "' appears at line " + str(first) + " and again at line "
                    + str(repeat) + " - the parser keeps the second and discards the first"
                ),
                key=name if len(path_parts) > 1 else None,
                line=repeat,
                action=(
                    "Delete or merge the duplicate. Whichever copy comes first is "
                    "being thrown away without warning."
                ),
            )
        )

    # --- source reworded, translations left behind -------------------------
    # The blind spot every per-string rule shares: each translation can be
    # perfectly well-formed and still be wrong, because it answers a question
    # the English text no longer asks. Nothing about the stale string itself
    # looks broken - only its relationship to a source that moved.
    for key, base_entry in baseline.entries.items():
        cand_entry = candidate.entries.get(key)
        if cand_entry is None:
            continue
        old_source = reference_for(base_entry)
        new_source = reference_for(cand_entry)
        if not old_source or not new_source or old_source == new_source:
            continue
        if not _substantive_change(old_source, new_source):
            continue  # a typo or punctuation fix does not invalidate a translation

        stale = sorted(
            lang
            for lang, text in cand_entry.items()
            if lang != REFERENCE_LANG
            and lang in base_entry
            and base_entry[lang] == text
        )
        if not stale:
            continue

        findings.append(
            Finding(
                severity=Severity.HIGH,
                code="content.stale_translation",
                title="Source changed, translations did not",
                detail=(
                    REFERENCE_LANG + " was reworded but " + str(len(stale)) + " translation"
                    + ("s" if len(stale) != 1 else "") + " (" + ", ".join(stale) + ") "
                    "still say what the old English said"
                ),
                key=key,
                line=index.string(key, REFERENCE_LANG),
                before=old_source,
                after=new_source,
                action=(
                    "Send the new " + REFERENCE_LANG + " text for retranslation, or "
                    "confirm the reword was cosmetic and the existing translations "
                    "still hold."
                ),
            )
        )

    # --- a language present on some keys but not others --------------------
    # A language the client believes it supports but which only covers part of
    # the file gives players a screen of their own language and then a screen of
    # English. Only reported for languages this release added or extended, since
    # a long-standing partial language is a product decision, not a regression.
    for lang in sorted(candidate.languages):
        if reference_for({lang: ""}) is not None:
            continue  # missing en-US is key.no_reference's finding, not this one
        covered = {k for k, e in candidate.entries.items() if lang in e}
        gaps = sorted(set(candidate.entries) - covered)
        if not gaps or not covered:
            continue
        was_complete = lang in baseline.languages and not [
            k for k in baseline.entries if lang not in baseline.entries[k]
        ]
        if lang in baseline.languages and not was_complete:
            continue  # already patchy before this release

        findings.append(
            Finding(
                severity=Severity.MEDIUM,
                code="language.partial_coverage",
                title="Language covers only part of the file",
                detail=(
                    "present in " + str(len(covered)) + " of "
                    + str(len(candidate.entries)) + " entries - these players see "
                    + REFERENCE_LANG + " on the rest"
                ),
                lang=lang,
                action=(
                    "Translate the missing entries (" + ", ".join(k[:8] for k in gaps[:4])
                    + ("…" if len(gaps) > 4 else "")
                    + "), or confirm the fallback is acceptable."
                ),
            )
        )

    # --- language codes the client will never ask for ----------------------
    # Graded by whether this release introduced it. A bad code that is already
    # live is someone else's ticket; a bad code shipping today means a whole
    # language reaches nobody, and it is invisible in a diff.
    for lang in sorted(candidate.languages):
        verdict = langcodes.problem_with(lang)
        if verdict is None:
            continue
        reason, action = verdict
        is_new = lang not in baseline.languages
        entries = sorted(k for k, e in candidate.entries.items() if lang in e)
        findings.append(
            Finding(
                severity=Severity.HIGH if is_new else Severity.INFO,
                code="language.invalid_code",
                title="Language code is not valid",
                detail=(
                    reason
                    + (
                        " - added by this release, so these "
                        + str(len(entries))
                        + " translations reach no one"
                        if is_new
                        else " - already live, not introduced here"
                    )
                ),
                lang=lang,
                line=index.string(entries[0], lang) if entries else None,
                action=action,
            )
        )

    # --- keys with no reference language -----------------------------------
    for key, entry in candidate.entries.items():
        if reference_for(entry) is None:
            findings.append(
                Finding(
                    severity=Severity.HIGH,
                    code="key.no_reference",
                    title="No reference language",
                    detail=(
                        "no " + REFERENCE_LANG + " string, so placeholders and tokens in "
                        "the other languages cannot be verified"
                    ),
                    key=key,
                    line=index.entry(key),
                    action="Add the " + REFERENCE_LANG + " source string for this entry.",
                )
            )

    return findings


def analyse(baseline: LocFile, candidate: LocFile) -> Report:
    index = locate.build(candidate.path)
    rollback = _direction_is_backwards(baseline, candidate)

    findings, changed = _string_findings(baseline, candidate, index, rollback)
    findings += _file_findings(baseline, candidate, index, rollback)
    findings.sort(key=lambda f: (f.severity.value, f.key or "", f.lang or ""))

    return Report(
        baseline_path=str(baseline.path),
        candidate_path=str(candidate.path),
        baseline_version=baseline.version,
        candidate_version=candidate.version,
        findings=findings,
        strings_compared=candidate.string_count,
        strings_changed=changed,
        warnings=[baseline.path.name + ": " + w for w in baseline.warnings]
        + [candidate.path.name + ": " + w for w in candidate.warnings],
        is_rollback=rollback,
    )
