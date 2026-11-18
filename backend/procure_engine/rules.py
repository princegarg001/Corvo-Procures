"""First-match rule evaluation with a full trace 'ladder' — policy §5 ("apply the rules
in this order; the first rule that fits decides"), §5.7 (never a non-eligible supplier),
§6.4 (suggestions), PLAN §5.3 (trace).

Outcome strategies (data, not code):
  supplier: contract | preferred:N | fixed:<id> | none
  price:    contract_rate | reference_price | last_po_price | standard_price
  suggest:  N suppliers (preferred list, topped up from the category)
If a matched rule's outcome cannot be realised (e.g. no eligible preferred supplier),
the rule is recorded as 'matched, outcome unavailable' and evaluation continues.
No rule fires → route NEEDS_REVIEW with a flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from .conditions import evaluate
from .contracts import ContractOption
from .facts import Ctx, FactReader
from .models import NEEDS_REVIEW
from .policy_schema import Outcome, Policy, Rule
from .suppliers import Suggestion, SupplierBook


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{value.normalize():f}" if value == value.to_integral_value() else f"{value}"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    return value


@dataclass
class LadderStep:
    rule_id: str
    clause: str
    name: str
    route: str
    matched: bool
    fired: bool
    facts: dict[str, Any]
    params: dict[str, Any]
    note: str = ""

    def to_trace(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule": self.rule_id, "clause": self.clause, "name": self.name, "route": self.route,
            "matched": self.matched, "fired": self.fired, "facts": self.facts, "params": self.params,
        }
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class Realised:
    supplier_id: str | None = None
    unit_price: Decimal | None = None
    price_source: str = ""
    price_ref: str = ""
    contract: ContractOption | None = None
    suggestions: list[Suggestion] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


@dataclass
class RuleResult:
    rule: Rule | None
    steps: list[LadderStep]
    realised: Realised

    @property
    def route(self) -> str:
        return self.rule.then.route if self.rule else NEEDS_REVIEW

    @property
    def decision(self) -> str:
        return self.rule.then.decision if self.rule else ""


class Unfulfillable(Exception):
    pass


def _supplier(strategy: str, ctx: Ctx, book: SupplierBook) -> tuple[str | None, ContractOption | None]:
    on = ctx.req_date
    if strategy == "contract":
        chosen = ctx.assessment.chosen if ctx.assessment else None
        if chosen is None:
            raise Unfulfillable("no usable contract")
        return chosen.supplier_id, chosen
    if strategy.startswith("preferred:"):
        n = int(strategy.split(":", 1)[1])
        pl = ctx.preferred()
        if len(pl) < n:
            raise Unfulfillable(f"preferred list has {len(pl)} eligible supplier(s); rank {n} needed")
        return pl[n - 1].supplier_id, None
    if strategy.startswith("fixed:"):
        sid = strategy.split(":", 1)[1]
        if not book.eligibility.eligible(sid, on):
            raise Unfulfillable(f"supplier {sid} is not eligible ({book.eligibility.status(sid, on)})")
        return sid, None
    return None, None


def _price(strategy: str, supplier_id: str | None, contract: ContractOption | None, ctx: Ctx,
           book: SupplierBook) -> tuple[Decimal, str, str]:
    if strategy == "contract_rate":
        if contract is None:
            raise Unfulfillable("contract rate needs a contract")
        return contract.rate, "contract_rate", contract.contract_id
    if strategy == "reference_price":
        if supplier_id is None or ctx.item is None:
            raise Unfulfillable("reference price needs a supplier")
        price, source, ref = book.reference_for(supplier_id, ctx.item_code, ctx.req_date)
        if price is None:
            raise Unfulfillable(f"supplier {supplier_id} has no reference price for the item")
        return price, source, ref
    if strategy == "last_po_price":
        last = ctx.valuation.latest_po if ctx.valuation else None
        if last is None:
            raise Unfulfillable("no PO in the valuation lookback")
        return last.unit_price, "last_po_price", f"PO {last.po_number}"
    if strategy == "standard_price":
        if ctx.item is None:
            raise Unfulfillable("new items have no standard price")
        return ctx.item.standard_price, "standard_price", ctx.item.code
    raise Unfulfillable(f"unknown price strategy {strategy}")


def realise(then: Outcome, ctx: Ctx, book: SupplierBook) -> Realised:
    out = Realised(flags=list(then.flags))
    if then.decision == "PO":
        sid, contract = _supplier(then.supplier or "none", ctx, book)
        if sid is None or not book.eligibility.eligible(sid, ctx.req_date):  # §5.7 belt and braces
            raise Unfulfillable("no eligible supplier")
        price, source, ref = _price(then.price or "", sid, contract, ctx, book)
        out.supplier_id, out.contract = sid, contract
        out.unit_price, out.price_source, out.price_ref = price, source, ref
    elif then.suggest > 0 and ctx.item is not None:
        out.suggestions = book.suggest(ctx.item_code, ctx.req_date, then.suggest)
        if len(out.suggestions) < then.suggest:
            out.flags.append("SHORT_LIST")
    return out


def decide(policy: Policy, ctx: Ctx, book: SupplierBook) -> RuleResult:
    steps: list[LadderStep] = []
    for rule in policy.rules:
        if not rule.enabled:
            continue
        reader = FactReader(ctx)
        params: dict[str, Decimal] = {}
        matched = evaluate(rule.when, reader, policy, params)
        step = LadderStep(
            rule.id, rule.clause, rule.name, rule.then.route, matched, False,
            jsonable(reader.reads), jsonable(params),
        )
        steps.append(step)
        if not matched:
            continue
        try:
            realised = realise(rule.then, ctx, book)
        except Unfulfillable as exc:
            step.note = f"conditions met but outcome unavailable: {exc}"
            continue
        step.fired = True
        return RuleResult(rule, steps, realised)
    return RuleResult(None, steps, Realised(flags=["NO_RULE_MATCHED"]))
