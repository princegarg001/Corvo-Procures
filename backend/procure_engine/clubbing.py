"""Clubbing PR lines into requirements — policy 2.1 (no splitting), 2.2 (rules), 2.3
(requirement date / emergency); decisions D6, D7, D20.

Lines are taken in creation order (then PR number, then line). A line joins the
earliest open requirement with the same key (policy `clubbing.key`, default item +
plant) whose first line was created 0..N calendar days earlier and whose first
need-by date is within M days either side. The window is anchored on the first
line (no chaining). Lines matching `never_club_when` (new items) are always alone.
Windows come from the policy version in force on the candidate's first-line date.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from .conditions import evaluate
from .facts import Ctx, FactReader
from .masterdata import MasterData
from .models import ResolvedLine
from .policy_schema import Policy


@dataclass
class Group:
    lines: list[ResolvedLine]
    solo: bool
    club_version: str
    flags: list[str] = field(default_factory=list)

    @property
    def first(self) -> ResolvedLine:
        return self.lines[0]


def _key(rl: ResolvedLine, attrs: list[str]) -> tuple[str, ...]:
    out = []
    for a in attrs:
        if a == "item_code":
            out.append(rl.item_code)
        else:
            out.append(str(getattr(rl.line, a)))
    return tuple(out)


def _never_club(rl: ResolvedLine, policy: Policy, master: MasterData) -> bool:
    cond = policy.clubbing.never_club_when
    if cond is None:
        return False
    ctx = Ctx(policy=policy, master=master, item_code=rl.item_code, lines=[rl.line])
    return evaluate(cond, FactReader(ctx), policy)


def _fits(group: Group, rl: ResolvedLine, policy: Policy) -> bool:
    cfg = policy.clubbing
    if not cfg.enabled or group.solo:
        return False
    first = group.first
    if _key(first, list(cfg.key)) != _key(rl, list(cfg.key)):
        return False
    created_gap = (rl.line.created_at.date() - first.line.created_at.date()).days
    if not 0 <= created_gap <= policy.param_int(cfg.created_within_param):
        return False
    need_gap = abs((rl.line.need_by - first.line.need_by).days)
    return need_gap <= policy.param_int(cfg.need_by_within_param)


def club(
    lines: list[ResolvedLine],
    policy_for: Callable[[date], Policy],
    master: MasterData,
) -> list[Group]:
    ordered = sorted(lines, key=lambda rl: rl.line.sort_key)
    groups: list[Group] = []
    for rl in ordered:
        own_policy = policy_for(rl.line.created_at.date())
        if _never_club(rl, own_policy, master):
            groups.append(Group([rl], solo=True, club_version=own_policy.version))
            continue
        target = None
        for g in groups:  # creation order → joins the earliest (2.2)
            if _fits(g, rl, policy_for(g.first.line.created_at.date())):
                target = g
                break
        if target is None:
            groups.append(Group([rl], solo=False, club_version=own_policy.version))
        else:
            target.lines.append(rl)
    for g in groups:
        _flag_duplicates(g, policy_for(g.first.line.created_at.date()))
    return groups


def _flag_duplicates(group: Group, policy: Policy) -> None:
    """Decision D6: same requester, same item, created within N minutes → flag, never drop."""
    minutes = policy.review_flags.possible_duplicate_minutes
    if minutes <= 0:
        return
    ls = group.lines
    for i, a in enumerate(ls):
        for b in ls[i + 1 :]:
            gap = abs((b.line.created_at - a.line.created_at).total_seconds()) / 60
            if a.line.requester == b.line.requester and gap <= minutes:
                if "POSSIBLE_DUPLICATE" not in group.flags:
                    group.flags.append("POSSIBLE_DUPLICATE")
                return
