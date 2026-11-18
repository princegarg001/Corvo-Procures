"""Policy version resolution by effective date — PLAN §8, decision D20.

The version in force on a date is the one with the latest `effective_from` that is
on or before the date (ties → the later version number). A resolver can be pinned to
one version (decision D29) so Run 1 can be reproduced after an amendment is active.
Callers decide which date to resolve: requirement date for rules/valuation, the
first line's date for clubbing, the PO's first requirement for consolidation.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from .policy_schema import Policy


def version_key(version: str) -> tuple[int, ...]:
    parts = []
    for p in version.split("."):
        parts.append(int(p) if p.isdigit() else 0)
    return tuple(parts)


class PolicyResolver:
    def __init__(self, versions: Iterable[Policy], *, pin: str | None = None):
        self.versions = sorted(versions, key=lambda p: (p.effective_from, version_key(p.version)))
        if not self.versions:
            raise ValueError("at least one policy version is required")
        self.pin = pin
        self._pinned: Policy | None = None
        if pin is not None:
            matches = [p for p in self.versions if p.version == pin]
            if not matches:
                raise ValueError(f"unknown policy version {pin!r}")
            self._pinned = matches[0]

    def for_date(self, on: date) -> Policy:
        if self._pinned is not None:
            return self._pinned
        chosen = self.versions[0]
        for p in self.versions:
            if p.effective_from <= on:
                chosen = p
        return chosen

    def by_version(self, version: str) -> Policy:
        for p in self.versions:
            if p.version == version:
                return p
        raise KeyError(version)

    @property
    def latest(self) -> Policy:
        return self._pinned or self.versions[-1]
