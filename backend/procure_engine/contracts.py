"""Rate contracts — policy 4.1 (applicability), 4.2 (ceiling, consumption order),
4.3 (lowest rate that still has enough ceiling), 4.4 (PDF-only contracts).

Applicable = covers the item ∧ start ≤ requirement date ≤ end ∧ supplier eligible.
Usable     = consumed + qty × rate ≤ cap × (1 + tolerance%).
A run-scoped Ledger starts from the register baseline (PDF-only contracts at 0)
and is consumed in requirement-date order by the pipeline (decision D14).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .masterdata import MasterData
from .money import HUNDRED, ONE
from .suppliers import Eligibility


class Ledger:
    """Consumed value per contract during one run."""

    def __init__(self, master: MasterData, baseline: dict[str, Decimal] | None = None):
        self._consumed: dict[str, Decimal] = {cid: c.consumed for cid, c in master.contracts.items()}
        if baseline:
            self._consumed.update(baseline)
        self.events: list[tuple[str, str, Decimal]] = []

    def consumed(self, contract_id: str) -> Decimal:
        return self._consumed.get(contract_id, Decimal(0))

    def consume(self, contract_id: str, amount: Decimal, requirement_id: str) -> None:
        self._consumed[contract_id] = self.consumed(contract_id) + amount
        self.events.append((contract_id, requirement_id, amount))

    def snapshot(self) -> dict[str, Decimal]:
        return dict(sorted(self._consumed.items()))


@dataclass(frozen=True)
class ContractOption:
    contract_id: str
    supplier_id: str
    rate: Decimal
    cap: Decimal
    consumed: Decimal
    required: Decimal
    limit: Decimal
    usable: bool
    source: str

    @property
    def remaining(self) -> Decimal:
        return self.limit - self.consumed

    def to_trace(self) -> dict[str, str | bool]:
        return {
            "id": self.contract_id,
            "supplier": self.supplier_id,
            "rate": f"{self.rate}",
            "cap": f"{self.cap}",
            "consumed": f"{self.consumed}",
            "remaining": f"{self.remaining}",
            "required": f"{self.required}",
            "usable": self.usable,
            "source": self.source,
        }


@dataclass(frozen=True)
class ContractAssessment:
    applicable: tuple[ContractOption, ...]
    excluded: tuple[tuple[str, str], ...]  # (contract_id, why) for covering-but-not-applicable

    @property
    def usable(self) -> tuple[ContractOption, ...]:
        return tuple(o for o in self.applicable if o.usable)

    @property
    def chosen(self) -> ContractOption | None:
        """Policy 4.3: lowest rate that still has enough ceiling (ties → contract id)."""
        return self.usable[0] if self.usable else None

    @property
    def lowest_applicable(self) -> ContractOption | None:
        return self.applicable[0] if self.applicable else None


def assess(
    item_code: str,
    quantity: Decimal,
    on: date,
    plant: str,
    master: MasterData,
    ledger: Ledger,
    eligibility: Eligibility,
    tolerance_pct: Decimal,
) -> ContractAssessment:
    options: list[ContractOption] = []
    excluded: list[tuple[str, str]] = []
    factor = ONE + tolerance_pct / HUNDRED
    for c in master.contracts_for_item(item_code):
        rate = c.rate_for(item_code)
        if rate is None:
            continue
        if not (c.start <= on <= c.end):
            excluded.append((c.id, f"not valid on {on.isoformat()} ({c.start.isoformat()} to {c.end.isoformat()})"))
            continue
        if c.plants and plant not in c.plants:
            excluded.append((c.id, f"does not cover plant {plant}"))
            continue
        if not eligibility.eligible(c.supplier_id, on):
            excluded.append((c.id, f"supplier {c.supplier_id} is {eligibility.status(c.supplier_id, on)}"))
            continue
        consumed = ledger.consumed(c.id)
        required = quantity * rate
        limit = c.value_cap * factor
        options.append(ContractOption(
            contract_id=c.id, supplier_id=c.supplier_id, rate=rate, cap=c.value_cap,
            consumed=consumed, required=required, limit=limit,
            usable=consumed + required <= limit, source=c.source,
        ))
    options.sort(key=lambda o: (o.rate, o.contract_id))
    return ContractAssessment(tuple(options), tuple(excluded))
