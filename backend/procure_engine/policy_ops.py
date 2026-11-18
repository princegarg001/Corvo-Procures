"""Policy amendment operations — PLAN §4.4 and §8 (op vocabulary, plain-language diff).

`apply_ops(policy, ops)` returns a new, fully validated Policy (never mutates);
`diff_policies(a, b)` recovers the ops between two versions; `describe_ops(ops, before)`
renders deterministic plain-language sentences for the approver, e.g.
"Spot PO limit (spot_limit, clause 5.4): ₹2,00,000 → ₹3,00,000".
Every op may carry `source_quote` (the amendment text it came from).
"""

from __future__ import annotations

import contextlib
import copy
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from .explain import describe_condition, describe_outcome, describe_rule
from .money import fmt_plain, format_inr, to_decimal
from .policy_schema import Policy, PolicyError, Rule, canonical_json, load_policy, parse_policy, walk_leaves


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_quote: str = ""
    note: str = ""


class SetParam(_Op):
    op: Literal["set_param"]
    name: str
    value: Any


class AddParam(_Op):
    op: Literal["add_param"]
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value: Any
    unit: str = ""
    label: str = ""
    clause: str = ""


class AddRule(_Op):
    op: Literal["add_rule"]
    rule: dict[str, Any]
    before: str | None = None
    after: str | None = None
    index: int | None = None


class ModifyRule(_Op):
    op: Literal["modify_rule"]
    rule_id: str
    changes: dict[str, Any]


class RemoveRule(_Op):
    op: Literal["remove_rule"]
    rule_id: str


class ReorderRules(_Op):
    op: Literal["reorder_rules"]
    order: list[str]


class AddItemSet(_Op):
    op: Literal["add_item_set"]
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    set: dict[str, Any]


class SetSupplierOverride(_Op):
    op: Literal["set_supplier_override"]
    supplier_id: str
    status: str
    reason: str = ""
    effective_from: date | None = None
    effective_to: date | None = None


class SetRanking(_Op):
    op: Literal["set_ranking"]
    changes: dict[str, Any]


class SetConsolidation(_Op):
    op: Literal["set_consolidation"]
    changes: dict[str, Any]


class SetClubbing(_Op):
    op: Literal["set_clubbing"]
    changes: dict[str, Any]


class SetSuggestions(_Op):
    op: Literal["set_suggestions"]
    changes: dict[str, Any]


class SetMatching(_Op):
    op: Literal["set_matching"]
    changes: dict[str, Any]


class SetRequirement(_Op):
    op: Literal["set_requirement"]
    changes: dict[str, Any]


class SetEffectiveFrom(_Op):
    op: Literal["set_effective_from"]
    date: date


PolicyOp = Annotated[
    SetParam | AddParam | AddRule | ModifyRule | RemoveRule | ReorderRules | AddItemSet
    | SetSupplierOverride | SetRanking | SetConsolidation | SetClubbing | SetSuggestions
    | SetMatching | SetRequirement | SetEffectiveFrom,
    Field(discriminator="op"),
]
OP_ADAPTER: TypeAdapter[list[PolicyOp]] = TypeAdapter(list[PolicyOp])
OP_NAMES = (
    "set_param", "add_param", "add_rule", "modify_rule", "remove_rule", "reorder_rules", "add_item_set",
    "set_supplier_override", "set_ranking", "set_consolidation", "set_clubbing", "set_suggestions",
    "set_matching", "set_requirement", "set_effective_from",
)


def parse_ops(raw: Sequence[Mapping[str, Any]] | Sequence[Any]) -> list[Any]:
    try:
        return list(OP_ADAPTER.validate_python([o.model_dump() if isinstance(o, BaseModel) else o for o in raw]))
    except ValidationError as exc:
        msgs = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            msgs.append(f"ops.{loc}: {err['msg']}")
        raise PolicyError(msgs) from exc


def ops_json_schema() -> dict[str, Any]:
    return OP_ADAPTER.json_schema()


def _merge(base: dict[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in changes.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _rule_index(rules: list[dict[str, Any]], rule_id: str, errors: list[str], where: str) -> int | None:
    for i, r in enumerate(rules):
        if r.get("id") == rule_id:
            return i
    errors.append(f"{where}: unknown rule {rule_id!r}")
    return None


def apply_ops(policy: Policy, ops: Sequence[Any], *, new_version: str | None = None) -> Policy:
    """Apply ops to a copy of the policy; raise PolicyError with every problem found."""
    parsed = parse_ops(ops)
    doc = policy.to_json_dict()
    errors: list[str] = []
    for i, op in enumerate(parsed):
        where = f"op[{i}] {op.op}"
        if isinstance(op, SetParam):
            if op.name not in doc["params"]:
                errors.append(f"{where}: unknown param {op.name!r} (use add_param)")
            else:
                doc["params"][op.name]["value"] = to_decimal(op.value)
        elif isinstance(op, AddParam):
            if op.name in doc["params"]:
                errors.append(f"{where}: param {op.name!r} already exists (use set_param)")
            else:
                doc["params"][op.name] = {"value": to_decimal(op.value), "unit": op.unit, "label": op.label, "clause": op.clause}
        elif isinstance(op, AddRule):
            rid = op.rule.get("id")
            if any(r["id"] == rid for r in doc["rules"]):
                errors.append(f"{where}: rule id {rid!r} already exists")
                continue
            positions = [p for p in (op.before, op.after, op.index) if p is not None]
            if len(positions) > 1:
                errors.append(f"{where}: give only one of before / after / index")
                continue
            if op.before is not None:
                idx = _rule_index(doc["rules"], op.before, errors, where)
                if idx is not None:
                    doc["rules"].insert(idx, copy.deepcopy(op.rule))
            elif op.after is not None:
                idx = _rule_index(doc["rules"], op.after, errors, where)
                if idx is not None:
                    doc["rules"].insert(idx + 1, copy.deepcopy(op.rule))
            elif op.index is not None:
                doc["rules"].insert(max(0, min(op.index, len(doc["rules"]))), copy.deepcopy(op.rule))
            else:
                # default: just before the last (catch-all) rule
                doc["rules"].insert(max(0, len(doc["rules"]) - 1), copy.deepcopy(op.rule))
        elif isinstance(op, ModifyRule):
            idx = _rule_index(doc["rules"], op.rule_id, errors, where)
            if idx is not None:
                bad = set(op.changes) - {"name", "clause", "description", "enabled", "when", "then", "id"}
                if bad:
                    errors.append(f"{where}: cannot change {sorted(bad)}")
                    continue
                rule = doc["rules"][idx]
                for k, v in op.changes.items():
                    if k == "then" and isinstance(v, Mapping):
                        rule["then"] = {**rule["then"], **copy.deepcopy(dict(v))}
                    else:
                        rule[k] = copy.deepcopy(v)
        elif isinstance(op, RemoveRule):
            idx = _rule_index(doc["rules"], op.rule_id, errors, where)
            if idx is not None:
                doc["rules"].pop(idx)
        elif isinstance(op, ReorderRules):
            ids = [r["id"] for r in doc["rules"]]
            if sorted(ids) != sorted(op.order):
                errors.append(f"{where}: order must list exactly the existing rule ids {ids}")
            else:
                by_id = {r["id"]: r for r in doc["rules"]}
                doc["rules"] = [by_id[i] for i in op.order]
        elif isinstance(op, AddItemSet):
            doc["item_sets"][op.name] = copy.deepcopy(op.set)
        elif isinstance(op, SetSupplierOverride):
            ovs = [o for o in doc["supplier_eligibility"]["overrides"] if o["supplier_id"] != op.supplier_id]
            ovs.append({
                "supplier_id": op.supplier_id, "status": op.status, "reason": op.reason,
                "effective_from": op.effective_from.isoformat() if op.effective_from else None,
                "effective_to": op.effective_to.isoformat() if op.effective_to else None,
            })
            doc["supplier_eligibility"]["overrides"] = sorted(ovs, key=lambda o: o["supplier_id"])
        elif isinstance(op, SetRanking):
            doc["preferred_suppliers"] = _merge(doc["preferred_suppliers"], op.changes)
        elif isinstance(op, SetConsolidation):
            doc["consolidation"] = _merge(doc["consolidation"], op.changes)
        elif isinstance(op, SetClubbing):
            doc["clubbing"] = _merge(doc["clubbing"], op.changes)
        elif isinstance(op, SetSuggestions):
            doc["suggestions"] = _merge(doc["suggestions"], op.changes)
        elif isinstance(op, SetMatching):
            doc["matching"] = _merge(doc["matching"], op.changes)
        elif isinstance(op, SetRequirement):
            doc["requirement"] = _merge(doc["requirement"], op.changes)
        elif isinstance(op, SetEffectiveFrom):
            doc["effective_from"] = op.date.isoformat()
    if errors:
        raise PolicyError(errors)
    if new_version is not None:
        doc["version"] = new_version
    try:
        return load_policy(doc)
    except PolicyError as exc:
        raise PolicyError([f"resulting policy: {m}" for m in exc.messages]) from exc


def next_version(version: str) -> str:
    major, _, minor = version.partition(".")
    return f"{major}.{int(minor or '0') + 1}"


# ------------------------------------------------------------------------------------- diff

def diff_policies(a: Policy, b: Policy) -> list[dict[str, Any]]:
    """Ops that turn `a` into `b` (rule order, params, sections)."""
    ops: list[dict[str, Any]] = []
    da, db = a.to_json_dict(), b.to_json_dict()
    for name, pd in db["params"].items():
        if name not in da["params"]:
            ops.append({"op": "add_param", "name": name, **pd})
        elif da["params"][name]["value"] != pd["value"]:
            ops.append({"op": "set_param", "name": name, "value": pd["value"]})
    ra = {r["id"]: r for r in da["rules"]}
    rb = {r["id"]: r for r in db["rules"]}
    for rid in ra:
        if rid not in rb:
            ops.append({"op": "remove_rule", "rule_id": rid})
    prev: str | None = None
    for r in db["rules"]:
        if r["id"] not in ra:
            op: dict[str, Any] = {"op": "add_rule", "rule": r}
            if prev is None:
                op["index"] = 0
            else:
                op["after"] = prev
            ops.append(op)
        else:
            changes = {k: r[k] for k in ("name", "clause", "description", "enabled", "when", "then") if r.get(k) != ra[r["id"]].get(k)}
            if changes:
                ops.append({"op": "modify_rule", "rule_id": r["id"], "changes": changes})
        prev = r["id"]
    common_a = [i for i in da["rules"] if i["id"] in rb]
    common_b = [i for i in db["rules"] if i["id"] in ra]
    if [r["id"] for r in common_a] != [r["id"] for r in common_b]:
        ops.append({"op": "reorder_rules", "order": [r["id"] for r in db["rules"]]})
    for name, s in db["item_sets"].items():
        if da["item_sets"].get(name) != s:
            ops.append({"op": "add_item_set", "name": name, "set": s})
    ova = {o["supplier_id"]: o for o in da["supplier_eligibility"]["overrides"]}
    for o in db["supplier_eligibility"]["overrides"]:
        if ova.get(o["supplier_id"]) != o:
            ops.append({"op": "set_supplier_override", **{k: v for k, v in o.items() if v is not None}})
    for section, opname in (("preferred_suppliers", "set_ranking"), ("consolidation", "set_consolidation"),
                            ("clubbing", "set_clubbing"), ("suggestions", "set_suggestions"),
                            ("matching", "set_matching"), ("requirement", "set_requirement")):
        changes = {k: v for k, v in db[section].items() if da[section].get(k) != v}
        if changes:
            ops.append({"op": opname, "changes": changes})
    if da["effective_from"] != db["effective_from"]:
        ops.append({"op": "set_effective_from", "date": db["effective_from"]})
    return ops


# ------------------------------------------------------------------------------------- describe

def _fmt_param(value: Any, unit: str) -> str:
    dec = to_decimal(value)
    if unit == "INR":
        return format_inr(dec, decimals=0 if dec == dec.to_integral_value() else 2)
    if unit == "%":
        return f"{fmt_plain(dec)}%"
    return f"{fmt_plain(dec)} {unit}".strip()


def _rules_using(policy: Policy, param: str) -> list[str]:
    out = []
    for r in policy.rules:
        if any(leaf.param == param for leaf in walk_leaves(r.when)):
            out.append(f"{r.id} {r.name}")
    return out


def _change_list(old: Mapping[str, Any], new: Mapping[str, Any], prefix: str = "") -> list[str]:
    out = []
    for k, v in new.items():
        ov = old.get(k)
        if isinstance(v, Mapping) and isinstance(ov, Mapping):
            out.extend(_change_list(ov, v, f"{prefix}{k} "))
        elif ov != v:
            out.append(f"{prefix}{k.replace('_', ' ')} {_short(ov)} → {_short(v)}")
    return out


def _short(v: Any) -> str:
    if v is None:
        return "(none)"
    if isinstance(v, list):
        return "[" + ", ".join(_short(x) for x in v) + "]" if v else "[]"
    if isinstance(v, Decimal | float | int) and not isinstance(v, bool):
        return fmt_plain(to_decimal(v))
    return str(v)


def describe_ops(ops: Sequence[Any], before: Policy, *, supplier_names: Mapping[str, str] | None = None) -> list[dict[str, str]]:
    """One plain-language sentence per op (deterministic templates), with its source quote."""
    parsed = parse_ops(ops)
    names = supplier_names or {}
    current = before
    out: list[dict[str, str]] = []
    for op in parsed:
        text = _describe_one(op, current, names)
        out.append({"op": op.op, "text": text, "source_quote": op.source_quote})
        with contextlib.suppress(PolicyError):  # describe later ops against the amended policy
            current = apply_ops(current, [op])
    return out


def _describe_one(op: Any, p: Policy, names: Mapping[str, str]) -> str:
    if isinstance(op, SetParam):
        pd = p.params.get(op.name)
        if pd is None:
            return f"Set unknown parameter {op.name} to {op.value}"
        used = _rules_using(p, op.name)
        where = f" — used by {', '.join(used)}" if used else ""
        clause = f", clause {pd.clause}" if pd.clause else ""
        return f"{pd.label or op.name} ({op.name}{clause}): {_fmt_param(pd.value, pd.unit)} → {_fmt_param(op.value, pd.unit)}{where}"
    if isinstance(op, AddParam):
        return f"New parameter {op.label or op.name} ({op.name}) = {_fmt_param(op.value, op.unit)}"
    if isinstance(op, AddRule):
        try:
            rule = Rule.model_validate(op.rule)
            body = describe_rule(rule, p)
            title = f"{rule.id} '{rule.name}'"
        except ValidationError:
            body, title = "(invalid rule)", str(op.rule.get("id"))
        pos = (f"before {op.before}" if op.before else f"after {op.after}" if op.after
               else f"at position {op.index + 1}" if op.index is not None else "before the catch-all rule")
        return f"New rule {title}, evaluated {pos}: {body}"
    if isinstance(op, ModifyRule):
        try:
            old = p.rule(op.rule_id)
        except PolicyError:
            return f"Modify unknown rule {op.rule_id}"
        parts = []
        ch = op.changes
        if "when" in ch:
            try:
                new_rule = Rule.model_validate({**old.model_dump(by_alias=True), "when": ch["when"]})
                parts.append(f"condition '{describe_condition(old.when, p)}' → '{describe_condition(new_rule.when, p)}'")
            except ValidationError:
                parts.append("condition changed (invalid)")
        if "then" in ch:
            old_then = old.then.model_dump()
            new_then = {**old_then, **ch["then"]}
            for k in sorted(ch["then"]):
                if old_then.get(k) != new_then.get(k):
                    parts.append(f"{k} {_short(old_then.get(k))} → {_short(new_then.get(k))}")
        for k in ("name", "clause", "description", "enabled"):
            if k in ch:
                parts.append(f"{k} {_short(getattr(old, k))} → {_short(ch[k])}")
        return f"Rule {old.id} {old.name}: " + ("; ".join(parts) or "no change")
    if isinstance(op, RemoveRule):
        try:
            old = p.rule(op.rule_id)
            return f"Rule {old.id} '{old.name}' removed (was: {describe_rule(old, p)})"
        except PolicyError:
            return f"Remove unknown rule {op.rule_id}"
    if isinstance(op, ReorderRules):
        return "Rule order: " + " → ".join(r.id for r in p.rules) + "  becomes  " + " → ".join(op.order)
    if isinstance(op, AddItemSet):
        s = op.set
        bits = []
        if s.get("codes"):
            bits.append("items " + ", ".join(s["codes"]))
        if s.get("patterns"):
            bits.append("descriptions matching " + " or ".join(repr(x) for x in s["patterns"]))
        if s.get("categories"):
            bits.append("categories " + ", ".join(s["categories"]))
        verb = "Item set" if op.name in p.item_sets else "New item set"
        return f"{verb} '{op.name}'{' (' + s['label'] + ')' if s.get('label') else ''}: " + "; ".join(bits)
    if isinstance(op, SetSupplierOverride):
        nm = f" ({names[op.supplier_id]})" if op.supplier_id in names else ""
        when = ""
        if op.effective_from:
            when += f" from {op.effective_from.strftime('%d %b %Y')}"
        if op.effective_to:
            when += f" until {op.effective_to.strftime('%d %b %Y')}"
        why = f" — {op.reason}" if op.reason else ""
        return f"Supplier {op.supplier_id}{nm} treated as {op.status}{when}{why}"
    if isinstance(op, SetRanking):
        return "Preferred-supplier ranking: " + "; ".join(_change_list(p.preferred_suppliers.model_dump(mode="json"), op.changes))
    if isinstance(op, SetConsolidation):
        return "PO consolidation: " + "; ".join(_change_list(p.consolidation.model_dump(mode="json"), op.changes))
    if isinstance(op, SetClubbing):
        return "Clubbing: " + "; ".join(_change_list(p.clubbing.model_dump(mode="json", by_alias=True), op.changes))
    if isinstance(op, SetSuggestions):
        return "Supplier suggestions: " + "; ".join(_change_list(p.suggestions.model_dump(mode="json"), op.changes))
    if isinstance(op, SetMatching):
        return "Item matching: " + "; ".join(_change_list(p.matching.model_dump(mode="json"), op.changes))
    if isinstance(op, SetRequirement):
        return "Requirement rules: " + "; ".join(_change_list(p.requirement.model_dump(mode="json"), op.changes))
    if isinstance(op, SetEffectiveFrom):
        return f"Effective from {op.date.strftime('%a %d %b %Y')} (requirements dated on or after this use the new version)"
    return f"{op.op}"


def describe_policy(policy: Policy) -> list[dict[str, str]]:
    """Readable rule table for the Policy screen."""
    return [
        {"id": r.id, "clause": r.clause, "name": r.name, "text": describe_rule(r, policy),
         "outcome": describe_outcome(r.then, policy), "enabled": "yes" if r.enabled else "no"}
        for r in policy.rules
    ]


def policies_equal(a: Policy, b: Policy) -> bool:
    return canonical_json(a.to_json_dict()) == canonical_json(b.to_json_dict())


__all__ = [
    "OP_NAMES", "apply_ops", "describe_ops", "describe_policy", "diff_policies", "next_version",
    "ops_json_schema", "parse_ops", "parse_policy", "policies_equal",
]
