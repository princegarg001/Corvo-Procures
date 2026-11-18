"""Requirement valuation — policy 3.1 (and 1.2 for new items).

Unit price = the first available of the policy's `valuation.sources`:
  contract_rate  → rate of the contract that will be used (4.3) or, if every
                   applicable contract is out of ceiling, the lowest applicable rate;
  last_po_price  → latest PO for the item in [date − lookback, date), any supplier
                   (decision D10), same-day tie → higher PO number (D9);
  standard_price → item master standard price.
New items: quantity × requester's estimate (missing estimate → 0, flagged; D18).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .contracts import ContractAssessment
from .masterdata import MasterData
from .models import PORecord
from .money import ZERO
from .policy_schema import Policy


@dataclass(frozen=True)
class Valuation:
    quantity: Decimal
    unit_price: Decimal
    value: Decimal
    source: str  # contract_rate | contract_rate_out_of_ceiling | last_po_price | standard_price | requester_estimate
    ref: str  # contract id, PO number, item code or ''
    latest_po: PORecord | None
    flags: tuple[str, ...] = ()

    def to_trace(self) -> dict[str, str]:
        return {
            "qty": f"{self.quantity.normalize():f}",
            "price": f"{self.unit_price}",
            "source": self.source,
            "ref": self.ref,
            "total": f"{self.value}",
        }


def latest_po(master: MasterData, item_code: str, on: date, lookback_days: int) -> PORecord | None:
    lo = on - timedelta(days=lookback_days)
    window = [p for p in master.pos_for_item(item_code) if lo <= p.po_date < on]
    return max(window, key=lambda p: p.recency_key) if window else None


def value_requirement(
    policy: Policy,
    master: MasterData,
    item_code: str,
    quantity: Decimal,
    on: date,
    assessment: ContractAssessment,
) -> Valuation:
    lookback = policy.param_int(policy.valuation.last_po_lookback_param)
    last = latest_po(master, item_code, on, lookback)
    for source in policy.valuation.sources:
        if source == "contract_rate":
            chosen = assessment.chosen
            if chosen is not None:
                return Valuation(quantity, chosen.rate, quantity * chosen.rate, "contract_rate", chosen.contract_id, last)
            low = assessment.lowest_applicable
            if low is not None:
                return Valuation(
                    quantity, low.rate, quantity * low.rate, "contract_rate_out_of_ceiling",
                    low.contract_id, last, ("CONTRACT_CEILING_EXHAUSTED",),
                )
        elif source == "last_po_price" and last is not None:
            flags: tuple[str, ...] = ()
            sup = master.suppliers.get(last.supplier_id)
            if sup is not None and sup.status not in policy.supplier_eligibility.allowed_statuses:
                flags = ("VALUED_ON_NON_ACTIVE_SUPPLIER_PO",)
            return Valuation(quantity, last.unit_price, quantity * last.unit_price, "last_po_price", last.po_number, last, flags)
        elif source == "standard_price":
            item = master.items[item_code]
            return Valuation(quantity, item.standard_price, quantity * item.standard_price, "standard_price", item.code, last)
    item = master.items[item_code]
    return Valuation(quantity, item.standard_price, quantity * item.standard_price, "standard_price", item.code, last)


def value_new_item(quantity: Decimal, estimate: Decimal | None) -> Valuation:
    if estimate is None:
        return Valuation(quantity, ZERO, ZERO, "requester_estimate", "", None, ("ESTIMATE_REQUIRED",))
    return Valuation(quantity, estimate, quantity * estimate, "requester_estimate", "", None)
