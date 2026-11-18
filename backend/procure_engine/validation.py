"""Semantic validation and lint of a policy document (PLAN §8 'Validate' and 'Lint').

Errors (block activation): unknown fact / operator for the fact's type / param /
item set, malformed regex, duplicate rule ids, section param references that do not
exist, clubbing conditions over facts not available before clubbing.
Warnings (shown to the approver): unreachable rules, missing catch-all, new
routes, rules that can never fire, suggestion counts of zero on sourcing routes.
"""

from __future__ import annotations

import re
from typing import Any

from .facts import REGISTRY, TYPE_OPS, UnknownFact, parse_fact_name
from .policy_schema import Always, Leaf, Policy, walk_leaves


def _check_leaf(leaf: Leaf, policy: Policy, where: str, *, line_scope: bool) -> list[str]:
    errs: list[str] = []
    try:
        base, arg = parse_fact_name(leaf.fact)
    except UnknownFact as exc:
        return [f"{where}: {exc}"]
    if base not in REGISTRY:
        return [f"{where}: unknown fact {leaf.fact!r}"]
    spec = REGISTRY[base][0]
    if line_scope and spec.scope != "line":
        errs.append(f"{where}: fact {leaf.fact!r} is not available before clubbing")
    if spec.arg and not arg:
        errs.append(f"{where}: fact {base!r} needs an argument, e.g. {base}(<{spec.arg}>)")
    if not spec.arg and arg is not None:
        errs.append(f"{where}: fact {base!r} takes no argument")
    if base == "item.in_set" and arg and arg.strip() not in policy.item_sets:
        errs.append(f"{where}: unknown item set {arg.strip()!r}")
    if leaf.op not in TYPE_OPS[spec.type]:
        errs.append(f"{where}: operator {leaf.op!r} is not valid for {spec.type} fact {leaf.fact!r}")
    if leaf.param is not None and leaf.param not in policy.params:
        errs.append(f"{where}: unknown param {leaf.param!r}")
    if leaf.op == "matches" and isinstance(leaf.value, str):
        try:
            re.compile(leaf.value)
        except re.error as exc:
            errs.append(f"{where}: invalid regex {leaf.value!r}: {exc}")
    for p in spec.params:
        if p not in policy.params:
            errs.append(f"{where}: fact {base!r} needs param {p!r}, which the policy does not define")
    return errs


def semantic_errors(policy: Policy) -> list[str]:
    errs: list[str] = []
    seen: set[str] = set()
    for i, rule in enumerate(policy.rules):
        where = f"rules[{i}] {rule.id}"
        if rule.id in seen:
            errs.append(f"{where}: duplicate rule id")
        seen.add(rule.id)
        for leaf in walk_leaves(rule.when):
            errs.extend(_check_leaf(leaf, policy, where, line_scope=False))
        sup = rule.then.supplier or ""
        if sup.startswith("preferred:") and int(sup.split(":")[1]) < 1:
            errs.append(f"{where}: preferred rank must be ≥ 1")
    if policy.clubbing.never_club_when is not None:
        for leaf in walk_leaves(policy.clubbing.never_club_when):
            errs.extend(_check_leaf(leaf, policy, "clubbing.never_club_when", line_scope=True))
    refs = {
        "clubbing.created_within_param": policy.clubbing.created_within_param,
        "clubbing.need_by_within_param": policy.clubbing.need_by_within_param,
        "valuation.last_po_lookback_param": policy.valuation.last_po_lookback_param,
        "contracts.tolerance_param": policy.contracts.tolerance_param,
        "preferred_suppliers.lookback_param": policy.preferred_suppliers.lookback_param,
        "consolidation.window_param": policy.consolidation.window_param,
    }
    for where, name in refs.items():
        if name not in policy.params:
            errs.append(f"{where}: unknown param {name!r}")
    for name, s in policy.item_sets.items():
        for p in s.patterns:
            try:
                re.compile(p)
            except re.error as exc:
                errs.append(f"item_sets.{name}: invalid regex {p!r}: {exc}")
    for name, pd in policy.params.items():
        if pd.unit in ("days", "hours") and pd.value < 0:
            errs.append(f"params.{name}: must not be negative")
    w = policy.preferred_suppliers.weights
    if any(v < 0 for v in (w.frequency, w.recency, w.contract, w.on_time, w.quality)):
        errs.append("preferred_suppliers.weights: weights must not be negative")
    if policy.preferred_suppliers.rating_scales.on_time_pct <= 0 or policy.preferred_suppliers.rating_scales.quality_rating <= 0:
        errs.append("preferred_suppliers.rating_scales: scales must be positive")
    return errs


def _is_always(cond: Any) -> bool:
    return isinstance(cond, Always)


def _mentions(cond: Any) -> set[str]:
    return {leaf.fact for leaf in walk_leaves(cond)}


def lint(policy: Policy, *, known_routes: set[str] | None = None, supplier_ids: set[str] | None = None) -> list[str]:
    """Non-blocking warnings for the approver."""
    warns: list[str] = []
    active = [r for r in policy.rules if r.enabled]
    for i, rule in enumerate(active):
        if _is_always(rule.when) and i < len(active) - 1:
            later = ", ".join(r.id for r in active[i + 1 :])
            warns.append(f"Rule {rule.id} always matches, so later rules can never fire: {later}")
    if not active or not _is_always(active[-1].when):
        warns.append("There is no catch-all rule at the end; unmatched requirements will be marked NEEDS_REVIEW")
    catalogue = set(policy.routes) | (known_routes or set())
    for rule in active:
        if rule.then.route not in catalogue:
            warns.append(f"Rule {rule.id} introduces a new route {rule.then.route}")
        if rule.then.decision == "SOURCING_REQUEST" and rule.then.suggest == 0 and "item.is_new" not in _mentions(rule.when):
            warns.append(f"Rule {rule.id} raises a sourcing request without suggested suppliers")
        sup = rule.then.supplier or ""
        if sup.startswith("fixed:") and supplier_ids is not None and sup[6:] not in supplier_ids:
            warns.append(f"Rule {rule.id} names supplier {sup[6:]}, which is not in the supplier master")
    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            if a.when == b.when:
                warns.append(f"Rules {a.id} and {b.id} have identical conditions; {b.id} can never fire")
    disabled = [r.id for r in policy.rules if not r.enabled]
    if disabled:
        warns.append("Disabled rules: " + ", ".join(disabled))
    return warns
