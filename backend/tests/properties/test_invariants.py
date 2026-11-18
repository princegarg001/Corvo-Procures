"""Hypothesis invariants (PLAN §13) over random batches on the kit master data.

No non-eligible supplier in any PO or suggestion (rule 6, policy 5.7) even with random
suppliers blocked by a policy override; clubbed lines share item + plant; NEW items
are never clubbed; ceilings never exceeded; PO rows have supplier, price and PO id;
sourcing rows have none; output is invariant to row order and idempotent.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from procure_engine.masterdata import MasterData
from procure_engine.pipeline import run_batch
from procure_engine.policy_ops import apply_ops
from procure_engine.policy_schema import Policy
from procure_engine.suppliers import Eligibility
from procure_engine.versions import PolicyResolver

START = datetime(2026, 11, 1, 8, 0)


@st.composite
def batches(draw: Any, master: MasterData) -> list[dict[str, str]]:
    codes = sorted(master.items)
    n = draw(st.integers(min_value=1, max_value=25))
    rows = []
    for i in range(n):
        kind = draw(st.sampled_from(["code", "code", "text", "new"]))
        code = draw(st.sampled_from(codes))
        created = START + timedelta(minutes=draw(st.integers(min_value=0, max_value=60 * 24 * 25)))
        rows.append({
            "pr_no": f"PR-H-{i:04d}", "pr_line": "1", "created_at": created.strftime("%Y-%m-%d %H:%M"),
            "requester": draw(st.sampled_from(["a", "b"])), "department": "x",
            "plant": draw(st.sampled_from(["PUN1", "CHK1", "CHK1", "PUN9"])),
            "item_code": code if kind == "code" else "",
            "description": master.items[code].description if kind != "new" else draw(st.sampled_from(
                ["quantum flux capacitor", "water purifier 50 LPH", "ball bearing 6206"])),
            "quantity": str(draw(st.integers(min_value=-1, max_value=3000))),
            "uom": master.items[code].uom,
            "estimated_unit_price": draw(st.sampled_from(["", "150", "99999.5"])),
            "need_by_date": (created.date() + timedelta(days=draw(st.integers(min_value=-2, max_value=40)))).isoformat(),
            "urgency": draw(st.sampled_from(["Normal", "Normal", "Emergency"])),
        })
    return rows


def _policy_with_blocks(policy: Policy, master: MasterData, seed: int) -> Policy:
    rnd = random.Random(seed)
    blocked = rnd.sample(sorted(master.suppliers), k=6)
    ops = [{"op": "set_supplier_override", "supplier_id": s, "status": "Blocked"} for s in blocked]
    return apply_ops(policy, ops)


SETTINGS = settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


@SETTINGS
@given(data=st.data(), seed=st.integers(min_value=0, max_value=10_000))
def test_invariants(data: Any, seed: int, master: MasterData, policy_v5: Policy) -> None:
    rows = data.draw(batches(master))
    policy = _policy_with_blocks(policy_v5, master, seed)
    res = run_batch(rows, master, PolicyResolver([policy]))
    elig = Eligibility(policy, master)
    assert len(res.rows) == len(rows)
    assert [(r.pr_no, r.pr_line) for r in res.rows] == [(r["pr_no"], r["pr_line"]) for r in rows]

    for req in res.requirements:
        d = res.decisions[req.id]
        assert len({(rl.item_code, rl.line.plant) for rl in req.lines}) == 1, "clubbed lines share item + plant"
        if req.item_code == "NEW":
            assert len(req.lines) == 1 and not d.suggested
        for sid in [d.supplier_id, *d.suggested]:
            if sid:
                assert elig.eligible(sid, req.req_date), f"non-eligible {sid}"
        assert len(set(d.suggested)) == len(d.suggested)
    for r in res.rows:
        if r.decision == "PO":
            assert r.supplier_id and r.unit_price and r.po_id and not r.suggested_supplier_ids
        elif r.decision == "SOURCING_REQUEST":
            assert not r.po_id and not r.supplier_id and not r.unit_price
        else:
            assert r.route == "NOT_PROCESSED" and r.reason
    for cid, consumed in res.ledger.items():
        c = master.contracts[cid]
        assert consumed == c.consumed or consumed <= c.value_cap
    for po in res.pos:
        sups = {res.decisions[rid].supplier_id for rid in po.requirement_ids}
        assert len(sups) == 1

    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    again = run_batch(shuffled, master, PolicyResolver([policy]))
    def key(rr: Any) -> dict[tuple[str, str], tuple[str, ...]]:
        return {(r.pr_no, r.pr_line): (r.group_id, r.po_id, r.route, r.supplier_id, r.group_value_inr,
                                       r.suggested_supplier_ids, r.reason) for r in rr.rows}

    assert key(again) == key(res)


@SETTINGS
@given(data=st.data())
def test_values_are_exact_decimals(data: Any, master: MasterData, policy_v5: Policy) -> None:
    rows = data.draw(batches(master))
    res = run_batch(rows, master, PolicyResolver([policy_v5]))
    for d in res.decisions.values():
        assert isinstance(d.value, Decimal)
        assert d.value == d.value_unit_price * sum(
            (rl.line.quantity for req in res.requirements if req.id == d.requirement_id for rl in req.lines), Decimal(0)
        ) or d.trace["item_code"] == "NEW"
