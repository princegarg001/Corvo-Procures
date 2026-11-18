"""Explanations — policy 8.1 (every decision records the clause applied and the contract
or PO relied on) and PLAN §5.3 / §10 (plain-language rules and reasons).

Two audiences: `describe_*` produce plain-language sentences for buyers and
approvers (₹ Indian format); `build_reason` produces the ASCII `reason` column of
the decisions CSV. Both are deterministic templates, never LLM prose.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from .contracts import ContractAssessment
from .facts import REGISTRY, parse_fact_name
from .money import fmt2, fmt_plain, format_inr
from .policy_schema import AllOf, Always, AnyOf, Leaf, NotOf, Outcome, Policy, Rule
from .rules import RuleResult
from .valuation import Valuation

OP_WORDS = {
    "eq": "is", "ne": "is not", "lt": "below", "lte": "at or below", "gt": "above",
    "gte": "at or above", "in": "is one of", "not_in": "is not one of", "between": "between",
    "contains": "contains", "matches": "matches", "exists": "is known",
}
OP_SYMBOLS = {"eq": "=", "ne": "!=", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}


def fact_label(name: str) -> str:
    base, arg = parse_fact_name(name)
    if base in REGISTRY:
        label = REGISTRY[base][0].label
        return f"{label} '{arg}'" if arg else label
    return name


def _fmt_value(fact: str, value: Any, *, ascii_only: bool = False) -> str:
    base, _ = parse_fact_name(fact)
    ftype = REGISTRY[base][0].type if base in REGISTRY else "string"
    if isinstance(value, list):
        return ", ".join(_fmt_value(fact, v, ascii_only=ascii_only) for v in value)
    if isinstance(value, bool):
        return "yes" if value else "no"
    if ftype == "money" and value is not None:
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
        return f"INR {fmt2(dec)}" if ascii_only else format_inr(dec, decimals=0 if dec == dec.to_integral_value() else 2)
    if isinstance(value, Decimal):
        return fmt_plain(value)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def describe_leaf(leaf: Leaf, policy: Policy) -> str:
    label = fact_label(leaf.fact)
    base, _ = parse_fact_name(leaf.fact)
    ftype = REGISTRY[base][0].type if base in REGISTRY else "string"
    if leaf.op == "exists":
        return f"{label} is known"
    if ftype == "bool" and leaf.op in ("eq", "ne") and leaf.param is None:
        truthy = bool(leaf.value) if not isinstance(leaf.value, str) else leaf.value.lower() == "true"
        positive = truthy if leaf.op == "eq" else not truthy
        return label if positive else f"not {label}"
    if leaf.param is not None:
        pd = policy.params.get(leaf.param)
        shown = _fmt_value(leaf.fact, pd.value) if pd else leaf.param
        if pd and pd.unit and pd.unit not in ("INR",):
            shown = f"{fmt_plain(pd.value)} {pd.unit}"
        operand = f"{shown} ({pd.label if pd and pd.label else leaf.param})"
    elif leaf.op == "between" and isinstance(leaf.value, list):
        operand = " and ".join(_fmt_value(leaf.fact, v) for v in leaf.value)
    else:
        operand = _fmt_value(leaf.fact, leaf.value)
    return f"{label} {OP_WORDS[leaf.op]} {operand}"


def describe_condition(cond: Any, policy: Policy) -> str:
    if isinstance(cond, Always):
        return "always"
    if isinstance(cond, Leaf):
        return describe_leaf(cond, policy)
    if isinstance(cond, AllOf):
        return " and ".join(describe_condition(c, policy) for c in cond.all_)
    if isinstance(cond, AnyOf):
        return "(" + " or ".join(describe_condition(c, policy) for c in cond.any_) + ")"
    if isinstance(cond, NotOf):
        return f"not ({describe_condition(cond.not_, policy)})"
    return str(cond)


def describe_supplier_strategy(strategy: str | None) -> str:
    s = strategy or "none"
    if s == "contract":
        return "the contract supplier"
    if s.startswith("preferred:"):
        n = int(s.split(":")[1])
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n if n < 20 else n % 10, "th")
        return f"the {n}{suffix} preferred supplier"
    if s.startswith("fixed:"):
        return f"supplier {s.split(':', 1)[1]}"
    return "no supplier"


PRICE_WORDS = {
    "contract_rate": "the contract rate",
    "reference_price": "its reference price",
    "last_po_price": "the latest PO price",
    "standard_price": "the item standard price",
}


def describe_outcome(then: Outcome, policy: Policy) -> str:
    route = f"{policy.route_label(then.route)} ({then.route})"
    if then.decision == "PO":
        text = f"PO via {route} to {describe_supplier_strategy(then.supplier)} at {PRICE_WORDS.get(then.price or '', then.price or '')}"
    else:
        text = f"Sourcing request {route}"
        text += f", suggest {then.suggest} supplier{'s' if then.suggest != 1 else ''}" if then.suggest else ", no supplier suggestions"
    if then.flags:
        text += "; flags " + ", ".join(then.flags)
    if then.requires_approval:
        text += "; needs approval by " + ", ".join(then.requires_approval)
    return text


def describe_rule(rule: Rule, policy: Policy) -> str:
    return f"If {describe_condition(rule.when, policy)} → {describe_outcome(rule.then, policy)}"


# ----------------------------------------------------------------------------- CSV reason

BASIS = {
    "contract_rate": "contract rate {ref}",
    "contract_rate_out_of_ceiling": "lowest applicable contract rate {ref} (all applicable contracts out of ceiling)",
    "last_po_price": "latest PO {ref}",
    "standard_price": "item standard price",
    "requester_estimate": "requester estimate",
}


def _leaf_text(leaf_fact: str, op: str, value: Any, operand: Any, param: str | None, policy: Policy) -> str:
    label = fact_label(leaf_fact)
    shown = _fmt_value(leaf_fact, value, ascii_only=True)
    if isinstance(value, bool) and op in ("eq", "ne") and param is None:
        return f"{label}: {shown}"
    if param is not None:
        pd = policy.params[param]
        rhs = (f"INR {fmt2(pd.value)}" if pd.unit == "INR" else f"{fmt_plain(pd.value)} {pd.unit}".strip()) + f" ({param})"
    else:
        rhs = _fmt_value(leaf_fact, operand, ascii_only=True)
    sym = OP_SYMBOLS.get(op, OP_WORDS.get(op, op))
    return f"{label} {shown} {sym} {rhs}"


def build_reason(
    *,
    policy: Policy,
    result: RuleResult,
    valuation: Valuation,
    assessment: ContractAssessment | None,
    leafs: list[tuple[str, str, Any, Any, str | None]],
    suggestions: list[str],
    suggestion_sources: list[str],
) -> str:
    parts: list[str] = []
    rule = result.rule
    if rule is None:
        parts.append(f"Policy v{policy.version}: no rule matched -> NEEDS_REVIEW")
    else:
        parts.append(f"Policy v{policy.version} clause {rule.clause} ({rule.name}) -> {rule.then.route}")
        conds = [_leaf_text(f, op, v, operand, param, policy) for f, op, v, operand, param in leafs]
        if conds:
            parts.append("because " + "; ".join(conds))
    r = result.realised
    if rule is not None and rule.then.decision == "PO":
        if r.contract is not None:
            text = f"supplier {r.supplier_id} under contract {r.contract.contract_id} at INR {fmt2(r.unit_price or Decimal(0))}"
            skipped = [o for o in (assessment.applicable if assessment else ()) if not o.usable and o.rate <= r.contract.rate]
            if skipped:
                text += " (" + ", ".join(f"{o.contract_id} rate {fmt2(o.rate)} lacks ceiling" for o in skipped) + f"; cl. {policy.contracts.clause})"
            parts.append(text)
        else:
            parts.append(
                f"supplier {r.supplier_id} (rank 1 on preferred list, cl. {policy.preferred_suppliers.clause}) "
                f"at reference price INR {fmt2(r.unit_price or Decimal(0))} from {r.price_ref or r.price_source}"
            )
    elif suggestions:
        pref = suggestion_sources.count("preferred")
        top = len(suggestions) - pref
        parts.append(
            f"suggested {';'.join(suggestions)} ({pref} from preferred list"
            + (f" + {top} category top-up" if top else "") + f", cl. {policy.suggestions.clause})"
        )
    elif rule is not None and rule.then.decision == "SOURCING_REQUEST":
        parts.append("no supplier suggestions")
    basis = BASIS.get(valuation.source, valuation.source).format(ref=valuation.ref)
    parts.append(
        f"value {fmt_plain(valuation.quantity)} x INR {fmt2(valuation.unit_price)} = INR {fmt2(valuation.value)} "
        f"[{basis}; cl. {policy.valuation.clause}]"
    )
    return ". ".join(parts)
