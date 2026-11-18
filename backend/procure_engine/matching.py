"""Item identification — policy 1.1 (use the code if given, else match the description) and
1.2 (no match → NEW item).

Normalise (lowercase, policy noise phrases, replacements such as '"' → ' inch',
abbreviation map), score candidates by token Jaccard, and apply a numeric-token
guard: every token containing a digit in the query must appear in the candidate,
so 'bearing 6206' can never match 'bearing 6205' (decision D5). All tunables
(threshold, phrases, abbreviations) come from the policy's `matching` section.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from .models import NEW_ITEM, Item, MatchResult, PRLine
from .money import ZERO
from .policy_schema import MatchingSection

_NON_TOKEN = re.compile(r"[^a-z0-9./]+")
_DIGIT = re.compile(r"\d")


@dataclass(frozen=True)
class Normalised:
    tokens: frozenset[str]
    flags: tuple[str, ...]
    text: str


class Normaliser:
    """Turns free text into a comparable token set according to the policy."""

    def __init__(self, cfg: MatchingSection):
        self.cfg = cfg
        self._noise = [
            (re.compile(re.escape(n.pattern.lower())), n.flag) for n in cfg.noise_phrases
        ]
        self._phrases = sorted(
            ((k.lower(), v.lower()) for k, v in cfg.abbreviations.items() if " " in k.strip()),
            key=lambda kv: -len(kv[0]),
        )
        self._words = {k.lower(): v.lower() for k, v in cfg.abbreviations.items() if " " not in k.strip()}

    def normalise(self, text: str) -> Normalised:
        s = text.lower()
        flags: list[str] = []
        for rep in self.cfg.replacements:
            s = s.replace(rep.find.lower(), rep.replace.lower())
        for pattern, flag in self._noise:
            if pattern.search(s):
                s = pattern.sub(" ", s)
                if flag and flag not in flags:
                    flags.append(flag)
        s = _NON_TOKEN.sub(" ", s)
        s = " ".join(x for x in (t.strip(".") for t in s.split()) if x)
        for phrase, repl in self._phrases:
            s = re.sub(rf"\b{re.escape(phrase)}\b", repl, s)
        tokens = [self._words.get(t, t) for t in s.split()]
        expanded: list[str] = []
        for t in tokens:
            expanded.extend(t.split())
        return Normalised(frozenset(t for t in expanded if t), tuple(flags), " ".join(expanded))


def jaccard(a: frozenset[str], b: frozenset[str]) -> Decimal:
    union = a | b
    if not union:
        return ZERO
    return Decimal(len(a & b)) / Decimal(len(union))


def numeric_tokens(tokens: frozenset[str]) -> frozenset[str]:
    return frozenset(t for t in tokens if _DIGIT.search(t))


@dataclass(frozen=True)
class Candidate:
    item_code: str
    score: Decimal
    guard_ok: bool
    missing_numbers: tuple[str, ...]


class ItemMatcher:
    """Deterministic description → item matcher over one item master and policy config."""

    def __init__(self, items: Mapping[str, Item], cfg: MatchingSection):
        self.items = items
        self.cfg = cfg
        self.norm = Normaliser(cfg)
        self._index = {code: self.norm.normalise(item.description).tokens for code, item in sorted(items.items())}

    def rank(self, description: str, *, limit: int | None = None) -> tuple[Normalised, list[Candidate]]:
        q = self.norm.normalise(description)
        q_nums = numeric_tokens(q.tokens)
        out: list[Candidate] = []
        for code, toks in self._index.items():
            score = jaccard(q.tokens, toks)
            if score == ZERO:
                continue
            missing = tuple(sorted(q_nums - toks))
            out.append(Candidate(code, score, not missing or not self.cfg.numeric_guard, missing))
        out.sort(key=lambda c: (not c.guard_ok, -c.score, c.item_code))
        return q, out[:limit] if limit else out

    def match_text(self, description: str) -> MatchResult:
        q, ranked = self.rank(description)
        top = [(c.item_code, c.score) for c in ranked[:5]]
        accepted = [c for c in ranked if c.guard_ok and c.score >= self.cfg.threshold]
        flags = list(q.flags)
        if not accepted:
            flags.append("NEW_ITEM")
            best_score = ranked[0].score if ranked else ZERO
            return MatchResult(NEW_ITEM, "NEW", best_score, tuple(top), tuple(flags))
        best = accepted[0]
        ties = [c for c in accepted if c.score == best.score]
        if len(ties) > 1:
            flags.append("AMBIGUOUS_MATCH")
        if best.score < 1:
            flags.append("FUZZY_MATCH")
        return MatchResult(best.item_code, "TEXT", best.score, tuple(top), tuple(flags))

    def description_similarity(self, description: str, item_code: str) -> Decimal:
        q = self.norm.normalise(description)
        return jaccard(q.tokens, self._index.get(item_code, frozenset()))

    def resolve(self, line: PRLine, mismatch_below: Decimal) -> MatchResult:
        """Policy 1.1: a given item code wins; otherwise match the description."""
        code = line.item_code.strip()
        if code and code in self.items:
            q = self.norm.normalise(line.description) if line.description else None
            flags = list(q.flags) if q else []
            score = Decimal(1)
            if line.description.strip():
                score = self.description_similarity(line.description, code)
                if score < mismatch_below:
                    flags.append("DESCRIPTION_MISMATCH")
            return MatchResult(code, "CODE", score, (), tuple(flags))
        result = self.match_text(line.description)
        if code:
            return MatchResult(
                result.item_code, result.method, result.score, result.candidates,
                (*result.flags, "UNKNOWN_ITEM_CODE"),
            )
        return result

