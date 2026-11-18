"""Boundary tests on small synthetic master data (PLAN §13): inclusive windows,
strict vs non-strict value limits, exact ceilings, lookback edges (D7, D8, D21, D22)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest

from procure_engine.masterdata import MasterData, build_master_data
from procure_engine.pipeline import RunResult, run_batch
from procure_engine.policy_schema import Policy
from procure_engine.versions import PolicyResolver

DAY0 = datetime(2026, 11, 2, 10, 0)


def synthetic_master() -> MasterData:
    items = [
        {"item_code": "T-A", "description": "Widget alpha 10mm", "uom": "NOS", "category": "Cat", "item_type": "Material", "standard_price": "100"},
        {"item_code": "T-B", "description": "Widget beta 20mm", "uom": "NOS", "category": "Cat", "item_type": "Material", "standard_price": "100"},
        {"item_code": "T-C", "description": "Contract gadget 30mm", "uom": "NOS", "category": "Cat", "item_type": "Material", "standard_price": "80"},
        {"item_code": "T-D", "description": "Lookback gizmo 40mm", "uom": "NOS", "category": "Cat", "item_type": "Material", "standard_price": "70"},
    ]
    suppliers = [
        {"supplier_id": "X1", "name": "One", "city": "Pune", "categories": "Cat", "status": "Active", "on_time_pct": "90", "quality_rating": "4"},
        {"supplier_id": "X2", "name": "Two", "city": "Pune", "categories": "Cat", "status": "Active", "on_time_pct": "80", "quality_rating": "3"},
        {"supplier_id": "X3", "name": "Three", "city": "Pune", "categories": "Cat", "status": "Active", "on_time_pct": "70", "quality_rating": "3"},
    ]
    po = [
        {"po_number": "1", "po_date": "2026-10-01", "supplier_id": "X1", "item_code": "T-A", "quantity": "1", "uom": "NOS", "unit_price": "100", "plant": "P1", "delivered_on_time": "True"},
        {"po_number": "2", "po_date": "2026-10-01", "supplier_id": "X1", "item_code": "T-B", "quantity": "1", "uom": "NOS", "unit_price": "100", "plant": "P1", "delivered_on_time": "True"},
        {"po_number": "3", "po_date": "2025-11-02", "supplier_id": "X1", "item_code": "T-D", "quantity": "1", "uom": "NOS", "unit_price": "60", "plant": "P1", "delivered_on_time": "True"},
    ]
    register = [{"contract_id": "K1", "supplier_id": "X2", "supplier_name": "Two", "start_date": "2026-01-01",
                 "end_date": "2026-12-31", "value_cap": "100000", "consumed_value": "0"}]
    lines = [{"contract_id": "K1", "item_code": "T-C", "description": "Contract gadget 30mm", "uom": "NOS", "rate": "50"}]
    return build_master_data(items=items, suppliers=suppliers, plants=[{"plant": "P1", "name": "Plant one"}],
                             po_history=po, register=register, contract_lines=lines)


MASTER = synthetic_master()


def row(n: int, item: str, qty: int | str, *, created: datetime = DAY0, need_by: date | None = None,
        urgency: str = "Normal", plant: str = "P1") -> dict[str, str]:
    return {
        "pr_no": f"T-{n:03d}", "pr_line": "1", "created_at": created.strftime("%Y-%m-%d %H:%M"),
        "requester": "r", "department": "d", "plant": plant, "item_code": item, "description": "",
        "quantity": str(qty), "uom": "NOS", "estimated_unit_price": "",
        "need_by_date": (need_by or (created.date() + timedelta(days=20))).isoformat(), "urgency": urgency,
    }


def run(policy: Policy, rows: list[dict[str, str]]) -> RunResult:
    return run_batch(rows, MASTER, PolicyResolver([policy]))


def route(res: RunResult, n: int) -> Any:
    return next(r for r in res.rows if r.pr_no == f"T-{n:03d}").route


def group(res: RunResult, n: int) -> str:
    return next(r for r in res.rows if r.pr_no == f"T-{n:03d}").group_id


@pytest.mark.parametrize(("qty", "expected"), [(1999, "SPOT_PO"), (2000, "RFQ")])
def test_spot_limit_is_strict(policy_v5: Policy, qty: int, expected: str) -> None:
    assert route(run(policy_v5, [row(1, "T-A", qty)]), 1) == expected  # ₹1,99,900 vs exactly ₹2,00,000


@pytest.mark.parametrize(("qty", "expected"), [(5000, "EMERGENCY_PO"), (5001, "RFQ")])
def test_emergency_limit_is_inclusive(policy_v5: Policy, qty: int, expected: str) -> None:
    assert route(run(policy_v5, [row(1, "T-A", qty, urgency="Emergency")]), 1) == expected


@pytest.mark.parametrize(("qty", "expected"), [(9999, "RFQ"), (10000, "RFP")])
def test_rfp_at_ten_lakh(policy_v5: Policy, qty: int, expected: str) -> None:
    assert route(run(policy_v5, [row(1, "T-A", qty)]), 1) == expected


@pytest.mark.parametrize(("qty", "expected"), [(2000, "CONTRACT_PO"), (2001, "RFQ")])
def test_ceiling_exactly_met_is_usable(policy_v5: Policy, qty: int, expected: str) -> None:
    # 2000 × ₹50 = ₹1,00,000 = the ceiling exactly; one more unit exceeds it
    res = run(policy_v5, [row(1, "T-C", qty)])
    assert route(res, 1) == expected


def test_ceiling_consumed_in_requirement_date_order(policy_v5: Policy) -> None:
    later = row(2, "T-C", 1500, created=DAY0 + timedelta(days=3), need_by=date(2027, 3, 1))
    first = row(1, "T-C", 1500)
    res = run(policy_v5, [later, first])  # input order reversed on purpose
    assert route(res, 1) == "CONTRACT_PO" and route(res, 2) != "CONTRACT_PO"


@pytest.mark.parametrize(("gap_days", "clubbed"), [(14, True), (15, False)])
def test_clubbing_creation_window_inclusive(policy_v5: Policy, gap_days: int, clubbed: bool) -> None:
    nb = date(2026, 12, 15)
    res = run(policy_v5, [row(1, "T-A", 10, need_by=nb), row(2, "T-A", 10, created=DAY0 + timedelta(days=gap_days, hours=5), need_by=nb)])
    assert (group(res, 1) == group(res, 2)) is clubbed


@pytest.mark.parametrize(("gap_days", "clubbed"), [(7, True), (8, False), (-7, True), (-8, False)])
def test_clubbing_need_by_window_either_side(policy_v5: Policy, gap_days: int, clubbed: bool) -> None:
    nb = date(2026, 12, 15)
    res = run(policy_v5, [row(1, "T-A", 10, need_by=nb),
                          row(2, "T-A", 10, created=DAY0 + timedelta(hours=1), need_by=nb + timedelta(days=gap_days))])
    assert (group(res, 1) == group(res, 2)) is clubbed


def test_clubbing_anchored_on_first_line_not_chained(policy_v5: Policy) -> None:
    nb = date(2026, 12, 15)
    res = run(policy_v5, [
        row(1, "T-A", 10, need_by=nb),
        row(2, "T-A", 10, created=DAY0 + timedelta(days=10), need_by=nb),
        row(3, "T-A", 10, created=DAY0 + timedelta(days=20), need_by=nb),  # 10 d after #2, 20 d after #1
    ])
    assert group(res, 1) == group(res, 2) != group(res, 3)


def test_clubbing_different_plant_never(policy_v5: Policy) -> None:
    master = MASTER
    assert "P2" not in master.plants
    res = run(policy_v5, [row(1, "T-A", 10), row(2, "T-A", 10, plant="P2")])
    assert route(res, 2) == "NOT_PROCESSED" and "unknown plant P2" in next(r for r in res.rows if r.pr_no == "T-002").reason


@pytest.mark.parametrize(("minutes", "same_po"), [(24 * 60, True), (24 * 60 + 1, False)])
def test_consolidation_window_inclusive(policy_v5: Policy, minutes: int, same_po: bool) -> None:
    res = run(policy_v5, [row(1, "T-A", 10), row(2, "T-B", 10, created=DAY0 + timedelta(minutes=minutes))])
    a = next(r for r in res.rows if r.pr_no == "T-001")
    b = next(r for r in res.rows if r.pr_no == "T-002")
    assert a.route == b.route == "SPOT_PO" and a.supplier_id == b.supplier_id
    assert (a.po_id == b.po_id) is same_po


@pytest.mark.parametrize(("created", "basis"), [(datetime(2026, 11, 2, 9), "latest PO 3"), (datetime(2026, 11, 3, 9), "item standard price")])
def test_valuation_lookback_window(policy_v5: Policy, created: datetime, basis: str) -> None:
    # PO 3 is dated 2025-11-02: exactly 365 days before 2026-11-02 (inside [d-365, d)), 366 before 2026-11-03
    res = run(policy_v5, [row(1, "T-D", 10, created=created)])
    assert basis in next(r for r in res.rows if r.pr_no == "T-001").reason


def test_po_on_requirement_date_is_not_history(policy_v5: Policy) -> None:
    # window is [d - N, d): a PO dated on the requirement date itself does not count
    res = run(policy_v5, [row(1, "T-A", 10, created=datetime(2026, 10, 1, 9))])
    assert "item standard price" in res.rows[0].reason
