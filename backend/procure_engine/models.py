"""Immutable value objects shared by every engine module.

Master data (items, suppliers, PO history, plants, contracts — policy §1, §4, §6),
PR lines (the input of §2) and the result objects of a run (requirements,
decisions, POs — §2.3, §5, §7, §8.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

NEW_ITEM = "NEW"
NOT_PROCESSED = "NOT_PROCESSED"
NEEDS_REVIEW = "NEEDS_REVIEW"

DECISION_PO = "PO"
DECISION_SOURCING = "SOURCING_REQUEST"


# --------------------------------------------------------------------------- master data


@dataclass(frozen=True, slots=True)
class Item:
    code: str
    description: str
    uom: str
    category: str
    item_type: str
    standard_price: Decimal


@dataclass(frozen=True, slots=True)
class Supplier:
    id: str
    name: str
    city: str
    categories: tuple[str, ...]
    status: str
    on_time_pct: Decimal
    quality_rating: Decimal


@dataclass(frozen=True, slots=True)
class PORecord:
    po_number: str
    po_date: date
    supplier_id: str
    item_code: str
    quantity: Decimal
    uom: str
    unit_price: Decimal
    plant: str
    delivered_on_time: bool

    @property
    def recency_key(self) -> tuple[date, int, str]:
        """Most-recent ordering: later date first, then higher PO number (decision D9)."""
        digits = int(self.po_number) if self.po_number.isdigit() else -1
        return (self.po_date, digits, self.po_number)


@dataclass(frozen=True, slots=True)
class Plant:
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class ContractLine:
    item_code: str
    description: str
    uom: str
    rate: Decimal


@dataclass(frozen=True, slots=True)
class Contract:
    id: str
    supplier_id: str
    supplier_name: str
    start: date
    end: date
    value_cap: Decimal
    consumed: Decimal
    source: str  # "REGISTER" | "PDF"
    lines: tuple[ContractLine, ...]
    plants: tuple[str, ...] = ()

    def rate_for(self, item_code: str) -> Decimal | None:
        for line in self.lines:
            if line.item_code == item_code:
                return line.rate
        return None

    def covers(self, item_code: str) -> bool:
        return self.rate_for(item_code) is not None


# --------------------------------------------------------------------------- PR input


@dataclass(frozen=True, slots=True)
class PRLine:
    """One validated PR line from a batch or from chat intake."""

    row_index: int
    pr_no: str
    pr_line: int
    created_at: datetime
    requester: str
    department: str
    plant: str
    item_code: str  # as given; '' when the requester gave none
    description: str
    quantity: Decimal
    uom: str
    est_unit_price: Decimal | None
    need_by: date
    urgency: str

    @property
    def sort_key(self) -> tuple[datetime, str, int]:
        """Policy 2.2: creation time, then PR number, then line number."""
        return (self.created_at, self.pr_no, self.pr_line)


@dataclass(frozen=True, slots=True)
class RejectedLine:
    """A row that is NOT_PROCESSED (decisions D1, D2, D23)."""

    row_index: int
    pr_no: str
    pr_line: str
    reason: str
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Outcome of item identification for one line (policy 1.1 / 1.2)."""

    item_code: str  # an item master code or NEW_ITEM
    method: str  # "CODE" | "TEXT" | "NEW"
    score: Decimal
    candidates: tuple[tuple[str, Decimal], ...] = ()
    flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedLine:
    line: PRLine
    match: MatchResult

    @property
    def item_code(self) -> str:
        return self.match.item_code


# --------------------------------------------------------------------------- run results


@dataclass(slots=True)
class Requirement:
    """A clubbed group of PR lines (policy 2.1-2.3)."""

    id: str
    item_code: str
    plant: str
    lines: list[ResolvedLine]
    club_policy_version: str

    @property
    def first(self) -> PRLine:
        return self.lines[0].line

    @property
    def created_at(self) -> datetime:
        return self.first.created_at

    @property
    def req_date(self) -> date:
        """Policy 2.3: the creation date of the first line."""
        return self.first.created_at.date()

    @property
    def quantity(self) -> Decimal:
        return sum((rl.line.quantity for rl in self.lines), Decimal(0))

    @property
    def sort_key(self) -> tuple[datetime, str, int]:
        return self.first.sort_key


@dataclass(slots=True)
class Decision:
    """The engine's outcome for one requirement, with its full trace (policy 8.1)."""

    requirement_id: str
    policy_version: str
    decision: str  # PO | SOURCING_REQUEST | '' (needs review)
    route: str
    rule_id: str | None
    clause: str | None
    supplier_id: str | None
    unit_price: Decimal | None
    value: Decimal
    value_unit_price: Decimal
    suggested: tuple[str, ...]
    flags: tuple[str, ...]
    reason: str
    trace: dict[str, Any]
    contract_id: str | None = None
    po_id: str | None = None


@dataclass(slots=True)
class PurchaseOrder:
    """A consolidated PO (policy 7.1/7.2)."""

    id: str
    supplier_id: str
    plant: str
    route: str
    first_created_at: datetime
    policy_version: str
    requirement_ids: list[str]


@dataclass(frozen=True, slots=True)
class OutputRow:
    """One CSV row per input PR line (brief section 4)."""

    row_index: int
    pr_no: str
    pr_line: str
    resolved_item_code: str
    group_id: str
    po_id: str
    decision: str
    route: str
    supplier_id: str
    unit_price: str
    group_value_inr: str
    suggested_supplier_ids: str
    policy_version: str
    reason: str
