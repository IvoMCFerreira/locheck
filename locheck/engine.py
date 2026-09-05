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

from . import locate
from .loader import LocFile, version_from_filename
from .model import Finding, Report, Severity
from .rules import REFERENCE_LANG, STRING_RULES


def _classify(old_problem, new_problem, existed_before, key, lang, before, after):
    """Compare a string's problem state across the two releases."""
    if new_problem is None:
        if old_problem is None:
            return None
        return Finding(
            severity=Severity.RESOLVED,
            code=old_problem.code,
            title="Fixed: " + old_problem.title.lower(),
            detail="was broken in the live version (" + old_problem.detail + "), now correct",
            key=key,
            lang=lang,
            before=before,
            after=after,
            action="Nothing to do. Flagged so a placeholder change here is not mistaken for a break.",
            spans=old_problem.spans,
        )

    if old_problem is not None and old_problem.code == new_problem.code:
        return Finding(
            severity=Severity.INFO,
            code=new_problem.code,
            title="Pre-existing: " + new_problem.title.lower(),
            detail=new_problem.detail + " - already live, not caused by this release",
            key=key,
            lang=lang,
            before=before,
            after=after,
            action="Worth a ticket, but it does not block this release. " + new_problem.action,
            spans=new_problem.spans,
        )

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


def _string_findings(baseline: LocFile, candidate: LocFile, index):
    findings = []
    changed = 0

    for key, langs in candidate.entries.items():
        base_entry = baseline.entries.get(key)
        for lang, text in sorted(langs.items()):
            before = base_entry.get(lang) if base_entry else None
            existed_before = before is not None
            if existed_before and before != text:
                changed += 1

            for rule in STRING_RULES:
                new_problem = rule(key, lang, text, langs)
                old_problem = rule(key, lang, before, base_entry) if existed_before else None
                finding = _classify(
                    old_problem, new_problem, existed_before, key, lang, before, text
                )
                if finding is not None:
                    finding.line = index.string(key, lang)
                    finding.reference = langs.get(REFERENCE_LANG)
                    findings.append(finding)
                    break  # one finding per string: don't stack overlapping causes

    return findings, changed


def _file_findings(baseline: LocFile, candidate: LocFile, index):
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
                    "was in {n} of {total} live entries and is now in none"
                    " - every {lang} player loses all of this text"
                ).format(n=len(affected), total=len(baseline.entries), lang=lang),
                lang=lang,
                action=(
                    "Confirm this was intended. If not, restore " + lang + " in: "
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
                detail="was live and is gone - any client still requesting it shows a blank",
                key=key,
                before=baseline.entries[key].get(REFERENCE_LANG),
                action=(
                    "Confirm no shipped client build still requests this ID. Old app "
                    "versions outlive content updates."
                ),
            )
        )

    # --- keys with no reference language -----------------------------------
    for key, entry in candidate.entries.items():
        if REFERENCE_LANG not in entry:
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

    findings, changed = _string_findings(baseline, candidate, index)
    findings += _file_findings(baseline, candidate, index)
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
    )
