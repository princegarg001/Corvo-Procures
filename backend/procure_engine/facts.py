"""Fact registry — the extension boundary of the policy DSL (PLAN §4.3).

A fact is a named, typed, documented value computed lazily (and memoised) for one
requirement: item.* (policy 1), req.* (2.3, 3.1), contract.* (4.1-4.3),
history.* (5.3/5.4) and preferred.* (6). Rules reference facts by name, so new
conditions over existing facts need no code; a new fact is one function here.
Facts marked scope="line" are also available before clubbing (for
`clubbing.never_club_when`).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from .contracts import ContractAssessment
from .masterdata import MasterData
from .models import NEW_ITEM, Item, PRLine, Requirement
from .policy_schema import ItemSet, Policy
from .suppliers import Eligibility, RankedSupplier, SupplierBook
from .valuation import Valuation

FACT_NAME = re.compile(r"^(?P<base>[a-z_]+(?:\.[a-z_]+)+)(?:\((?P<arg>[^()]*)\))?$")

TYPE_OPS: dict[str, tuple[str, ...]] = {
    "bool": ("eq", "ne", "exists"),
    "number": ("eq", "ne", "lt", "lte", "gt", "gte", "between", "in", "not_in", "exists"),
    "money": ("eq", "ne", "lt", "lte", "gt", "gte", "between", "exists"),
    "string": ("eq", "ne", "in", "not_in", "contains", "matches", "exists"),
    "date": ("eq", "ne", "lt", "lte", "gt", "gte", "between", "exists"),
    "list": ("contains", "in", "not_in", "eq", "exists"),
}


class UnknownFact(KeyError):
    pass


@dataclass(frozen=True)
class FactSpec:
    name: str
    type: str
    label: str
    description: str
    scope: str = "requirement"  # "line" facts also work before clubbing
    params: tuple[str, ...] = ()
    arg: str | None = None  # name of the argument, e.g. "set" for item.in_set(<set>)


class Ctx:
    """Everything a fact may need. Line contexts leave requirement-level fields as None."""

    def __init__(
        self,
        *,
        policy: Policy,
        master: MasterData,
        item_code: str,
        lines: list[PRLine],
        requirement: Requirement | None = None,
        assessment: ContractAssessment | None = None,
        valuation: Valuation | None = None,
        book: SupplierBook | None = None,
    ):
        self.policy = policy
        self.master = master
        self.item_code = item_code
        self.item: Item | None = master.items.get(item_code) if item_code != NEW_ITEM else None
        self.lines = lines
        self.requirement = requirement
        self.assessment = assessment
        self.valuation = valuation
        self.book = book
        self.memo: dict[str, Any] = {}

    @property
    def req_date(self) -> date:
        return min(ln.created_at for ln in self.lines).date()

    def preferred(self) -> list[RankedSupplier]:
        if self.book is None or self.item is None:
            return []
        return self.book.preferred(self.item_code, self.req_date)


def item_in_set(ctx: Ctx, s: ItemSet) -> bool:
    if ctx.item is not None:
        if ctx.item.code in s.codes or ctx.item.category in s.categories:
            return True
        texts = [ctx.item.description]
    else:
        texts = [ln.description for ln in ctx.lines]
    return any(re.search(p, t, re.IGNORECASE) for p in s.patterns for t in texts)


def _need(ctx: Ctx, what: str) -> Any:
    value = getattr(ctx, what)
    if value is None:
        raise UnknownFact(f"fact needs {what}, which is not available in this context")
    return value


def _history(ctx: Ctx) -> list[Any]:
    if ctx.item is None:
        return []
    days = ctx.policy.param_int("bought_lookback_days")
    on = ctx.req_date
    lo = on - timedelta(days=days)
    return [p for p in ctx.master.pos_for_item(ctx.item_code) if lo <= p.po_date < on]


def _eligible(ctx: Ctx, supplier_id: str) -> bool:
    if ctx.book is not None:
        return ctx.book.eligibility.eligible(supplier_id, ctx.req_date)
    return Eligibility(ctx.policy, ctx.master).eligible(supplier_id, ctx.req_date)


def _first_pref(ctx: Ctx) -> RankedSupplier | None:
    pl = ctx.preferred()
    return pl[0] if pl else None


def _latest(ctx: Ctx) -> Any:
    h = _history(ctx)
    return max(h, key=lambda p: p.recency_key) if h else None


def _contract_ref(ctx: Ctx) -> Any:
    a: ContractAssessment = _need(ctx, "assessment")
    return a.chosen or a.lowest_applicable


Computer = Callable[[Ctx, str | None], Any]
REGISTRY: dict[str, tuple[FactSpec, Computer]] = {}


def fact(name: str, type_: str, label: str, description: str, *, scope: str = "requirement",
         params: tuple[str, ...] = (), arg: str | None = None) -> Callable[[Computer], Computer]:
    def deco(fn: Computer) -> Computer:
        REGISTRY[name] = (FactSpec(name, type_, label, description, scope, params, arg), fn)
        return fn
    return deco


# ---------------------------------------------------------------------------- item.*
fact("item.code", "string", "item code", "Resolved item master code ('NEW' for new items).", scope="line")(
    lambda c, a: c.item_code)
fact("item.description", "string", "item description", "Item master description (requester text for new items).", scope="line")(
    lambda c, a: c.item.description if c.item else c.lines[0].description)
fact("item.category", "string", "item category", "Item master category, e.g. 'Office & IT'.", scope="line")(
    lambda c, a: c.item.category if c.item else None)
fact("item.type", "string", "item type", "Item master type: Material, Service or Capex.", scope="line")(
    lambda c, a: c.item.item_type if c.item else None)
fact("item.uom", "string", "item unit", "Item master unit of measure.", scope="line")(
    lambda c, a: c.item.uom if c.item else None)
fact("item.standard_price", "money", "standard price", "Item master standard unit price (INR).", scope="line")(
    lambda c, a: c.item.standard_price if c.item else None)
fact("item.is_new", "bool", "new item", "True when the line matched no item master item (policy 1.2).", scope="line")(
    lambda c, a: c.item is None)
fact("item.sets", "list", "item sets", "Names of the policy item sets this item belongs to.", scope="line")(
    lambda c, a: sorted(n for n, s in c.policy.item_sets.items() if item_in_set(c, s)))
fact("item.in_set", "bool", "in item set", "True when the item belongs to the named policy item set.",
     scope="line", arg="set")(
    lambda c, a: item_in_set(c, c.policy.item_sets[a or ""]))

# ---------------------------------------------------------------------------- req.*
fact("req.plant", "string", "plant", "Plant code of the requirement, as in the plants master.", scope="line")(
    lambda c, a: c.lines[0].plant)
fact("req.value", "money", "requirement value", "Total quantity × unit price (policy 3.1), INR, unrounded.")(
    lambda c, a: _need(c, "valuation").value)
fact("req.unit_price", "money", "valuation unit price", "Unit price used for valuation (policy 3.1).")(
    lambda c, a: _need(c, "valuation").unit_price)
fact("req.price_source", "string", "valuation basis",
     "Which 3.1 source priced the requirement: contract_rate, contract_rate_out_of_ceiling, last_po_price, standard_price, requester_estimate.")(
    lambda c, a: _need(c, "valuation").source)
fact("req.quantity", "number", "total quantity", "Sum of the quantities of all clubbed lines.", scope="line")(
    lambda c, a: sum((ln.quantity for ln in c.lines), Decimal(0)))
fact("req.emergency", "bool", "emergency", "True when any line's urgency is an emergency urgency (policy 2.3).", scope="line")(
    lambda c, a: any(ln.urgency in c.policy.requirement.emergency_urgencies for ln in c.lines))
fact("req.urgencies", "list", "urgencies", "Distinct urgency values of the lines.", scope="line")(
    lambda c, a: sorted({ln.urgency for ln in c.lines}))
fact("req.line_count", "number", "PR lines", "Number of PR lines clubbed into the requirement.", scope="line")(
    lambda c, a: Decimal(len(c.lines)))
fact("req.date", "date", "requirement date", "Creation date of the first line (policy 2.3).", scope="line")(
    lambda c, a: c.req_date)
fact("req.need_by", "date", "need-by date", "Earliest need-by date across the lines.", scope="line")(
    lambda c, a: min(ln.need_by for ln in c.lines))
fact("req.lead_time_days", "number", "lead time (days)", "Days between the requirement date and the earliest need-by date.", scope="line")(
    lambda c, a: Decimal((min(ln.need_by for ln in c.lines) - c.req_date).days))
fact("req.departments", "list", "departments", "Departments that raised the lines.", scope="line")(
    lambda c, a: sorted({ln.department for ln in c.lines}))
fact("req.requesters", "list", "requesters", "Requesters who raised the lines.", scope="line")(
    lambda c, a: sorted({ln.requester for ln in c.lines}))
fact("req.descriptions", "string", "line descriptions", "All line descriptions joined with ' | ' (use contains / matches).", scope="line")(
    lambda c, a: " | ".join(ln.description for ln in c.lines))
fact("req.uoms", "list", "line units", "Units of measure used on the lines.", scope="line")(
    lambda c, a: sorted({ln.uom for ln in c.lines}))

# ---------------------------------------------------------------------------- contract.*
fact("contract.applicable", "bool", "contract applies", "A contract covers the item, is valid on the date and its supplier is eligible (4.1).")(
    lambda c, a: bool(_need(c, "assessment").applicable))
fact("contract.usable", "bool", "contract usable", "An applicable contract still has enough ceiling for this requirement (4.2/4.3).")(
    lambda c, a: _need(c, "assessment").chosen is not None)
fact("contract.count_applicable", "number", "applicable contracts", "Number of applicable contracts.")(
    lambda c, a: Decimal(len(_need(c, "assessment").applicable)))
fact("contract.best_rate", "money", "contract rate", "Rate of the contract that would be used (or the lowest applicable).")(
    lambda c, a: (r.rate if (r := _contract_ref(c)) else None))
fact("contract.remaining_ceiling", "money", "ceiling left", "Ceiling left on that contract before this requirement.")(
    lambda c, a: (r.remaining if (r := _contract_ref(c)) else None))
fact("contract.supplier_id", "string", "contract supplier", "Supplier of that contract.")(
    lambda c, a: (r.supplier_id if (r := _contract_ref(c)) else None))
fact("contract.id", "string", "contract", "ID of that contract.")(
    lambda c, a: (r.contract_id if (r := _contract_ref(c)) else None))

# ---------------------------------------------------------------------------- history.*
fact("history.bought_from_active", "bool", "bought from an Active supplier",
     "At least one PO for the item from an eligible supplier in the purchase-history lookback (5.3/5.4).",
     scope="line", params=("bought_lookback_days",))(
    lambda c, a: any(_eligible(c, p.supplier_id) for p in _history(c)))
fact("history.po_count", "number", "POs in lookback", "Number of POs for the item (any supplier) in the purchase-history lookback.",
     scope="line", params=("bought_lookback_days",))(
    lambda c, a: Decimal(len(_history(c))))
fact("history.days_since_last_po", "number", "days since last PO", "Days since the latest PO for the item within the lookback.",
     scope="line", params=("bought_lookback_days",))(
    lambda c, a: (Decimal((c.req_date - p.po_date).days) if (p := _latest(c)) else None))
fact("history.last_po_supplier_id", "string", "last PO supplier", "Supplier of the latest PO within the lookback.",
     scope="line", params=("bought_lookback_days",))(
    lambda c, a: (p.supplier_id if (p := _latest(c)) else None))
fact("history.last_po_supplier_status", "string", "last PO supplier status", "Master status of that supplier.",
     scope="line", params=("bought_lookback_days",))(
    lambda c, a: (c.master.suppliers[p.supplier_id].status if (p := _latest(c)) and p.supplier_id in c.master.suppliers else None))
fact("history.last_po_price", "money", "last PO price", "Unit price of the latest PO within the lookback.",
     scope="line", params=("bought_lookback_days",))(
    lambda c, a: (p.unit_price if (p := _latest(c)) else None))

# ---------------------------------------------------------------------------- preferred.*
fact("preferred.count", "number", "preferred suppliers", "Number of suppliers on the item's preferred list (6.1).")(
    lambda c, a: Decimal(len(c.preferred())))
fact("preferred.supplier_ids", "list", "preferred list", "Preferred supplier IDs in rank order.")(
    lambda c, a: [r.supplier_id for r in c.preferred()])
fact("preferred.first.supplier_id", "string", "1st preferred supplier", "Top-ranked supplier (6.2).")(
    lambda c, a: (r.supplier_id if (r := _first_pref(c)) else None))
fact("preferred.first.on_time_pct", "number", "1st preferred on-time %", "On-time delivery % of the 1st preferred supplier.")(
    lambda c, a: (c.master.suppliers[r.supplier_id].on_time_pct if (r := _first_pref(c)) else None))
fact("preferred.first.quality", "number", "1st preferred quality", "Quality rating (0-5) of the 1st preferred supplier.")(
    lambda c, a: (c.master.suppliers[r.supplier_id].quality_rating if (r := _first_pref(c)) else None))
fact("preferred.first.reference_price", "money", "1st preferred reference price", "Reference price of the 1st preferred supplier (6.3).")(
    lambda c, a: (r.reference_price if (r := _first_pref(c)) else None))
fact("preferred.first.score", "number", "1st preferred score", "Ranking score of the 1st preferred supplier.")(
    lambda c, a: (r.score if (r := _first_pref(c)) else None))


def parse_fact_name(name: str) -> tuple[str, str | None]:
    m = FACT_NAME.match(name.strip())
    if not m:
        raise UnknownFact(f"malformed fact name {name!r}")
    return m.group("base"), m.group("arg")


def spec_for(name: str) -> FactSpec:
    base, _ = parse_fact_name(name)
    if base not in REGISTRY:
        raise UnknownFact(f"unknown fact {name!r}")
    return REGISTRY[base][0]


@dataclass
class FactReader:
    """Reads facts for one context, memoising and recording every value read."""

    ctx: Ctx
    reads: dict[str, Any] = field(default_factory=dict)

    def __call__(self, name: str) -> Any:
        if name in self.ctx.memo:
            value = self.ctx.memo[name]
        else:
            base, arg = parse_fact_name(name)
            if base not in REGISTRY:
                raise UnknownFact(f"unknown fact {name!r}")
            value = REGISTRY[base][1](self.ctx, arg.strip() if arg else None)
            self.ctx.memo[name] = value
        self.reads[name] = value
        return value


def registry_listing() -> list[dict[str, Any]]:
    """Fact metadata for docs, the UI and the LLM amendment prompt."""
    out = []
    for name in sorted(REGISTRY):
        s = REGISTRY[name][0]
        out.append({
            "name": s.name + (f"(<{s.arg}>)" if s.arg else ""),
            "type": s.type,
            "label": s.label,
            "description": s.description,
            "ops": list(TYPE_OPS[s.type]),
            "scope": s.scope,
            "params": list(s.params),
        })
    return out
