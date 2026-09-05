"""Core types shared by the rules, the engine and the report."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(Enum):
    """Ordered worst-first. The value is a sort key, not a score.

    The tiers are defined by what the *player* experiences, not by how large
    the textual change is:

        BLOCKER   the client can crash, or a player sees nothing at all
        HIGH      a player sees the wrong language, or content vanishes
        MEDIUM    a player sees wrong or badly laid out content
        LOW       cosmetic
        INFO      already broken before this release; not a regression
        RESOLVED  this release *fixed* something that was broken
    """

    BLOCKER = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    INFO = 4
    RESOLVED = 5


@dataclass(frozen=True)
class Problem:
    """A rule's verdict on a single string: something about it is wrong.

    A Problem is deliberately release-agnostic. It says "this string is bad",
    never "this release made it bad" - that judgement belongs to the engine.

    `action` is the imperative a releaser can act on without reading the code,
    and `spans` are character ranges in the offending string worth highlighting.
    """

    code: str
    title: str
    detail: str
    severity: Severity
    action: str = ""
    spans: tuple[tuple[int, int], ...] = ()


@dataclass
class Finding:
    """A Problem placed in the context of a release: worth acting on, or not."""

    severity: Severity
    code: str
    title: str
    detail: str
    key: str | None = None
    lang: str | None = None
    before: str | None = None
    after: str | None = None
    #: Where to go and fix it.
    line: int | None = None
    #: What to do about it, in the imperative.
    action: str = ""
    #: The en-US string, so the reader can see what the translation should mirror.
    reference: str | None = None
    #: Character ranges in `after` (or `before`, for fixes) worth highlighting.
    spans: tuple[tuple[int, int], ...] = ()
    #: Other problems with the same string, worst-first, below this one.
    #:
    #: A string gets one row in the summary table however many things are wrong
    #: with it - two rows for one string would inflate the ship/no-ship count.
    #: But whoever fixes it is editing that string once and should see the whole
    #: list, so the detail card carries the rest here.
    also: list = field(default_factory=list)

    @property
    def location(self) -> str:
        """`2b827952 / ru`, the short human handle for this finding."""
        parts = []
        if self.key:
            parts.append(self.key)
        if self.lang:
            parts.append(self.lang)
        return " / ".join(parts) if parts else "file"

    def as_dict(self) -> dict:
        return {
            "severity": self.severity.name,
            "code": self.code,
            "title": self.title,
            "detail": self.detail,
            "key": self.key,
            "lang": self.lang,
            "line": self.line,
            "action": self.action,
            "reference": self.reference,
            "before": self.before,
            "after": self.after,
            "also": [
                {"severity": f.severity.name, "code": f.code, "detail": f.detail}
                for f in self.also
            ],
        }


@dataclass
class Report:
    baseline_path: str
    candidate_path: str
    baseline_version: str | None
    candidate_version: str | None
    findings: list[Finding]
    strings_compared: int
    strings_changed: int
    warnings: list[str]

    @property
    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.BLOCKER]

    @property
    def flagged(self) -> list[Finding]:
        """Findings that ask the releaser to do something before shipping.

        LOW is deliberately excluded. It is shown in the report but does not
        count towards "need action" or fail --strict: an unescaped percent in a
        promo string is worth knowing about and is not worth holding a release
        for. Counting it would let a marketing-heavy release show twenty items
        of "work" that nobody intends to do, which is how a checklist becomes
        something people skip.
        """
        return [f for f in self.findings if f.severity.value <= Severity.MEDIUM.value]

    def as_dict(self) -> dict:
        return {
            "baseline": self.baseline_path,
            "candidate": self.candidate_path,
            "baseline_version": self.baseline_version,
            "candidate_version": self.candidate_version,
            "strings_compared": self.strings_compared,
            "strings_changed": self.strings_changed,
            "blocker_count": len(self.blockers),
            "flagged_count": len(self.flagged),
            "warnings": self.warnings,
            "findings": [f.as_dict() for f in self.findings],
        }
