"""Condition evaluator for the policy DSL (PLAN §4.1/§4.3; policy §5 'when' column).

Conditions are `{fact, op, value|param}` leaves combined with all / any / not / always.
Operators: eq ne in not_in lt lte gt gte between contains matches exists.
Numbers compare as Decimal, dates as dates, strings case-insensitively. A missing
fact value (None) makes every comparison false except `ne` (true) and `exists` (false).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from .money import MoneyError, to_decimal
from .policy_schema import AllOf, Always, AnyOf, Leaf, NotOf, Policy

Reader = Callable[[str], Any]


def _coerce(target: Any, value: Any) -> Any:
    """Coerce a literal from the policy to the fact value's type."""
    if isinstance(target, bool):
        if isinstance(value, str):
            return value.strip().lower() in {"true", "yes", "1"}
        return bool(value)
    if isinstance(target, Decimal | int) and not isinstance(target, bool):
        try:
            return to_decimal(value)
        except MoneyError:
            return value
    if isinstance(target, date):
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    if isinstance(target, str):
        return str(value)
    return value


def _norm(v: Any) -> Any:
    if isinstance(v, str):
        return v.strip().casefold()
    if isinstance(v, int) and not isinstance(v, bool):
        return Decimal(v)
    return v


def _cmp(fact_value: Any, op: str, raw: Any) -> bool:
    if op == "exists":
        return fact_value is not None and fact_value != []
    if fact_value is None:
        return op == "ne"
    if isinstance(fact_value, list):
        items = {_norm(x) for x in fact_value}
        values = raw if isinstance(raw, list) else [raw]
        wanted = {_norm(_coerce(next(iter(fact_value), ""), v)) for v in values}
        if op == "contains":
            return wanted <= items
        if op == "in":
            return bool(items & wanted)
        if op == "not_in":
            return not (items & wanted)
        if op == "eq":
            return items == wanted
        return False
    if op in ("in", "not_in"):
        values = raw if isinstance(raw, list) else [raw]
        hit = _norm(fact_value) in {_norm(_coerce(fact_value, v)) for v in values}
        return hit if op == "in" else not hit
    if op == "between":
        lo, hi = (_norm(_coerce(fact_value, v)) for v in raw)
        return bool(lo <= _norm(fact_value) <= hi)
    if op == "contains":
        return _norm(str(raw)) in _norm(str(fact_value))
    if op == "matches":
        return re.search(str(raw), str(fact_value), re.IGNORECASE) is not None
    a, b = _norm(fact_value), _norm(_coerce(fact_value, raw))
    if op == "eq":
        return bool(a == b)
    if op == "ne":
        return bool(a != b)
    try:
        if op == "lt":
            return bool(a < b)
        if op == "lte":
            return bool(a <= b)
        if op == "gt":
            return bool(a > b)
        if op == "gte":
            return bool(a >= b)
    except TypeError:
        return False
    raise ValueError(f"unknown operator {op!r}")


def leaf_operand(leaf: Leaf, policy: Policy) -> Any:
    if leaf.param is not None:
        return policy.param(leaf.param)
    return leaf.value


def evaluate(cond: Any, read: Reader, policy: Policy, params_used: dict[str, Decimal] | None = None) -> bool:
    """Evaluate a condition tree. `read` records facts; `params_used` collects params."""
    if isinstance(cond, Always):
        return True
    if isinstance(cond, Leaf):
        operand = leaf_operand(cond, policy)
        if cond.param is not None and params_used is not None:
            params_used[cond.param] = policy.param(cond.param)
        return _cmp(read(cond.fact), cond.op, operand)
    if isinstance(cond, AllOf):
        # evaluate every child (no short-circuit) so the trace shows all values
        results = [evaluate(c, read, policy, params_used) for c in cond.all_]
        return all(results)
    if isinstance(cond, AnyOf):
        results = [evaluate(c, read, policy, params_used) for c in cond.any_]
        return any(results)
    if isinstance(cond, NotOf):
        return not evaluate(cond.not_, read, policy, params_used)
    raise ValueError(f"unknown condition node {cond!r}")


def leaf_results(cond: Any, read: Reader, policy: Policy) -> list[tuple[Leaf, Any, bool]]:
    """Per-leaf (condition, fact value, result) for explanations."""
    out: list[tuple[Leaf, Any, bool]] = []
    if isinstance(cond, Leaf):
        value = read(cond.fact)
        out.append((cond, value, _cmp(value, cond.op, leaf_operand(cond, policy))))
    elif isinstance(cond, AllOf):
        for c in cond.all_:
            out.extend(leaf_results(c, read, policy))
    elif isinstance(cond, AnyOf):
        for c in cond.any_:
            out.extend(leaf_results(c, read, policy))
    elif isinstance(cond, NotOf):
        out.extend(leaf_results(cond.not_, read, policy))
    return out
