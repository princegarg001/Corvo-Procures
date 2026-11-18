"""A1-A12 drills (PLAN §4.4): every amendment is pure data (ops), applies cleanly, reads
in plain language, round-trips through diff, and changes decisions exactly as intended,
including version resolution by requirement date (a version effective mid-batch).
"""

from __future__ import annotations

import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from procure_engine.masterdata import MasterData
from procure_engine.models import OutputRow
from procure_engine.pipeline import RunResult, run_batch
from procure_engine.policy_ops import apply_ops, describe_ops, diff_policies, policies_equal
from procure_engine.policy_schema import Policy, PolicyError
from procure_engine.suppliers import SupplierBook
from procure_engine.versions import PolicyResolver

FIX = Path(__file__).resolve().parents[3] / "fixtures" / "amendments"
IDS = [f"A{i}" for i in range(1, 13)]


def load(aid: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIX / f"{aid}.ops.json").read_text(encoding="utf-8"))
    return data


def amended(policy_v5: Policy, aid: str) -> Policy:
    return apply_ops(policy_v5, load(aid)["ops"], new_version="5.1")


def run_with(rows: list[dict[str, str]], master: MasterData, *versions: Policy) -> RunResult:
    return run_batch(rows, master, PolicyResolver(list(versions)))


def by_key(run: RunResult) -> dict[tuple[str, str], OutputRow]:
    return {(r.pr_no, r.pr_line): r for r in run.rows}


def route_changes(a: RunResult, b: RunResult) -> dict[tuple[str, str], tuple[str, str]]:
    ka, kb = by_key(a), by_key(b)
    return {k: (ka[k].route, kb[k].route) for k in ka if ka[k].route != kb[k].route}


def _edit(rows: list[dict[str, str]], pr_no: str, **changes: str) -> list[dict[str, str]]:
    out = copy.deepcopy(rows)
    for r in out:
        if r["pr_no"] == pr_no:
            r.update(changes)
    return out


# --------------------------------------------------------------------------- generic properties


@pytest.mark.parametrize("aid", IDS)
def test_applies_and_matches_expected_json(aid: str, policy_v5: Policy) -> None:
    new = amended(policy_v5, aid)
    expected = json.loads((FIX / f"{aid}.expected.json").read_text(encoding="utf-8"))
    assert json.loads(json.dumps(new.to_json_dict())) == expected
    assert new.version == "5.1"


@pytest.mark.parametrize("aid", IDS)
def test_plain_language_and_diff_round_trip(aid: str, policy_v5: Policy) -> None:
    ops = load(aid)["ops"]
    sentences = describe_ops(ops, policy_v5)
    assert len(sentences) == len(ops) and all(s["text"] for s in sentences)
    new = amended(policy_v5, aid)
    rebuilt = apply_ops(policy_v5, diff_policies(policy_v5, new), new_version="5.1")
    assert policies_equal(rebuilt, new)


def test_original_policy_is_never_mutated(policy_v5: Policy) -> None:
    before = copy.deepcopy(policy_v5.to_json_dict())
    for aid in IDS:
        amended(policy_v5, aid)
    assert policy_v5.to_json_dict() == before


def test_invalid_ops_are_rejected_with_reasons(policy_v5: Policy) -> None:
    bad = [
        {"op": "set_param", "name": "no_such_param", "value": 1},
        {"op": "add_rule", "after": "R-9.9", "rule": {"id": "X", "name": "x", "when": {"always": True},
                                                       "then": {"decision": "SOURCING_REQUEST", "route": "RFQ"}}},
    ]
    with pytest.raises(PolicyError) as exc:
        apply_ops(policy_v5, bad)
    assert len(exc.value.messages) == 2
    with pytest.raises(PolicyError, match="unknown fact"):
        apply_ops(policy_v5, [{"op": "modify_rule", "rule_id": "R-5.5",
                               "changes": {"when": {"fact": "item.colour", "op": "eq", "value": "red"}}}])
    with pytest.raises(PolicyError, match="not valid for bool"):
        apply_ops(policy_v5, [{"op": "modify_rule", "rule_id": "R-5.5",
                               "changes": {"when": {"fact": "item.is_new", "op": "lt", "value": 3}}}])


# --------------------------------------------------------------------------- per amendment


def test_a1_spot_limit_split_by_effective_date(sample_rows: list[dict[str, str]], master: MasterData,
                                               policy_v5: Policy, sample_run: RunResult) -> None:
    new = amended(policy_v5, "A1")
    run = run_with(sample_rows, master, policy_v5, new)
    eff = date(2026, 11, 10)
    expected: set[tuple[str, str]] = set()
    for req in sample_run.requirements:
        d = sample_run.decisions[req.id]
        bought = any(s["facts"].get("history.bought_from_active") for s in d.trace["ladder"])
        if req.req_date >= eff and d.route == "RFQ" and Decimal(200000) <= d.value < Decimal(300000) and bought:
            expected |= {(rl.line.pr_no, str(rl.line.pr_line)) for rl in req.lines}
    changes = route_changes(sample_run, run)
    assert expected and set(changes) == expected
    assert all(v == ("RFQ", "SPOT_PO") for v in changes.values())
    for req in run.requirements:
        assert run.decisions[req.id].policy_version == ("5.1" if req.req_date >= eff else "5.0")
    # D29: a run pinned to 5.0 reproduces Run 1 exactly even with 5.1 active
    pinned = run_batch(sample_rows, master, PolicyResolver([policy_v5, new], pin="5.0"))
    assert pinned.rows == sample_run.rows


def test_a2_plant_only_emergency_limit(sample_rows: list[dict[str, str]], master: MasterData, policy_v5: Policy,
                                       sample_run: RunResult) -> None:
    new = amended(policy_v5, "A2")
    assert route_changes(sample_run, run_with(sample_rows, master, policy_v5, new)) == {}
    rows = _edit(sample_rows, "PR-26-00058", quantity="3000")  # a Chakan emergency worth about ₹6.4 L
    k = ("PR-26-00058", "1")
    assert by_key(run_with(rows, master, policy_v5))[k].route == "RFQ"
    assert by_key(run_with(rows, master, policy_v5, new))[k].route == "EMERGENCY_PO"
    pune = _edit(rows, "PR-26-00058", plant="PUN1")  # in Pune it also clubs with PR-26-00122
    assert by_key(run_with(pune, master, policy_v5, new))[k].route != "EMERGENCY_PO"


def test_a3_office_it_always_rfq(sample_rows: list[dict[str, str]], master: MasterData, policy_v5: Policy,
                                 sample_run: RunResult) -> None:
    run = run_with(sample_rows, master, policy_v5, amended(policy_v5, "A3"))
    changes = route_changes(sample_run, run)
    assert changes
    rows = by_key(run)
    for key, (old, new_route) in changes.items():
        assert master.items[rows[key].resolved_item_code].category == "Office & IT"
        assert old != "CONTRACT_PO" and new_route == "RFQ"
    for r in run.rows:
        if r.resolved_item_code in master.items and master.items[r.resolved_item_code].category == "Office & IT":
            assert r.route in ("RFQ", "CONTRACT_PO")


def test_a4_new_route_and_item_set_without_code(sample_rows: list[dict[str, str]], master: MasterData,
                                                policy_v5: Policy, sample_run: RunResult) -> None:
    run = run_with(sample_rows, master, policy_v5, amended(policy_v5, "A4"))
    changes = route_changes(sample_run, run)
    assert changes and all(new == "PROPRIETARY_PO" for _, new in changes.values())
    rows = by_key(run)
    for key in changes:
        desc = master.items[rows[key].resolved_item_code].description.lower()
        assert "(vertex" in desc or "(hydrax" in desc
    row = rows[next(iter(changes))]
    assert row.decision == "PO" and row.po_id and row.supplier_id


def test_a5_wider_clubbing_only_merges(sample_rows: list[dict[str, str]], master: MasterData, policy_v5: Policy,
                                       sample_run: RunResult) -> None:
    run = run_with(sample_rows, master, policy_v5, amended(policy_v5, "A5"))
    old = [{(rl.line.pr_no, rl.line.pr_line) for rl in req.lines} for req in sample_run.requirements]
    new = [{(rl.line.pr_no, rl.line.pr_line) for rl in req.lines} for req in run.requirements]
    assert len(new) < len(old)
    for group in new:  # every new group is a union of old groups
        assert all(part <= group for part in old if part & group)


def test_a6_services_above_limit_rfp(sample_rows: list[dict[str, str]], master: MasterData, policy_v5: Policy,
                                     sample_run: RunResult) -> None:
    run = run_with(sample_rows, master, policy_v5, amended(policy_v5, "A6"))
    changes = route_changes(sample_run, run)
    assert changes
    rows = by_key(run)
    for key, (_, new_route) in changes.items():
        assert master.items[rows[key].resolved_item_code].item_type == "Service"
        assert Decimal(rows[key].group_value_inr) > Decimal(500000) and new_route == "RFP"


def test_a7_supplier_blocked_from_date(sample_rows: list[dict[str, str]], master: MasterData, policy_v5: Policy,
                                       sample_run: RunResult) -> None:
    run = run_with(sample_rows, master, policy_v5, amended(policy_v5, "A7"))
    eff = date(2026, 11, 10)
    seen_before = False
    for req in run.requirements:
        d = run.decisions[req.id]
        involved = {d.supplier_id, *d.suggested}
        if req.req_date >= eff:
            assert "S013" not in involved
            assert d.contract_id != "RC-2026-002"
        elif "S013" in involved:
            seen_before = True
    assert seen_before
    assert route_changes(sample_run, run)


def test_a8_ceiling_tolerance(sample_rows: list[dict[str, str]], master: MasterData, policy_v5: Policy,
                              sample_run: RunResult) -> None:
    run = run_with(sample_rows, master, policy_v5, amended(policy_v5, "A8"))
    assert ("RFQ", "CONTRACT_PO") in route_changes(sample_run, run).values()
    for cid, consumed in run.ledger.items():
        c = master.contracts[cid]
        assert consumed == c.consumed or consumed <= c.value_cap * Decimal("1.10")


def test_a9_emergency_not_consolidated(sample_rows: list[dict[str, str]], master: MasterData, policy_v5: Policy) -> None:
    twin = dict(next(r for r in sample_rows if r["pr_no"] == "PR-26-00058"))
    twin.update(pr_no="PR-26-90058", created_at="2026-11-12 13:15", need_by_date="2026-12-20", quantity="100")
    rows = [*sample_rows, twin]
    a, b = ("PR-26-00058", "1"), ("PR-26-90058", "1")
    base = by_key(run_with(rows, master, policy_v5))
    assert base[a].route == base[b].route == "EMERGENCY_PO" and base[a].po_id == base[b].po_id
    new = by_key(run_with(rows, master, policy_v5, amended(policy_v5, "A9")))
    assert new[a].route == new[b].route == "EMERGENCY_PO" and new[a].po_id != new[b].po_id


def test_a10_short_lead_time_is_emergency(sample_rows: list[dict[str, str]], master: MasterData,
                                          policy_v5: Policy) -> None:
    rows = _edit(sample_rows, "PR-26-00089", need_by_date="2026-11-07")
    k = ("PR-26-00089", "1")
    assert by_key(run_with(rows, master, policy_v5))[k].route == "RFQ"
    assert by_key(run_with(rows, master, policy_v5, amended(policy_v5, "A10")))[k].route == "EMERGENCY_PO"


def test_a11_rfq_suggests_four(sample_rows: list[dict[str, str]], master: MasterData, policy_v5: Policy,
                               sample_run: RunResult) -> None:
    run = run_with(sample_rows, master, policy_v5, amended(policy_v5, "A11"))
    base = by_key(sample_run)
    grew = 0
    for k, r in by_key(run).items():
        if r.route == "RFQ":
            old, new = base[k].suggested_supplier_ids.split(";"), r.suggested_supplier_ids.split(";")
            assert new[: len(old)] == old and len(new) <= 4
            grew += len(new) > len(old)
    assert grew > 0


def test_a12_ranking_weights(master: MasterData, policy_v5: Policy) -> None:
    new = amended(policy_v5, "A12")
    on = date(2026, 11, 15)
    old_book, new_book = SupplierBook(policy_v5, master), SupplierBook(new, master)
    changed = [c for c in master.items
               if [r.supplier_id for r in old_book.preferred(c, on)] != [r.supplier_id for r in new_book.preferred(c, on)]]
    assert changed
    assert new.preferred_suppliers.weights.quality == Decimal("0.20")
