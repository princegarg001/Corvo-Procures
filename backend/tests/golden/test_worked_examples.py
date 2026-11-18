"""The 14 worked examples (Worked_Examples.pdf) as requirement-level acceptance tests."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
import yaml

from procure_engine.money import q2
from procure_engine.pipeline import RunResult
from tests.conftest import GOLDEN

SPEC = yaml.safe_load((GOLDEN / "worked_examples.yaml").read_text(encoding="utf-8"))
EXAMPLES = {e["id"]: e for e in SPEC["examples"]}


def _req(run: RunResult, pr_no: str, line: int) -> Any:
    req = run.requirement_for_line(pr_no, line)
    assert req is not None, f"{pr_no}/{line} not in any requirement"
    return req


@pytest.mark.parametrize("ex_id", sorted(EXAMPLES))
def test_worked_example(ex_id: int, sample_run: RunResult) -> None:
    ex = EXAMPLES[ex_id]
    lines = [(p, int(n)) for p, n in ex["lines"]]
    reqs = {_req(sample_run, p, n).id for p, n in lines}
    assert len(reqs) == 1, f"example {ex_id}: lines must form one requirement, got {reqs}"
    req = _req(sample_run, *lines[0])
    assert {(rl.line.pr_no, rl.line.pr_line) for rl in req.lines} == set(lines), "clubbing differs"
    d = sample_run.decisions[req.id]
    assert req.item_code == ex["item"]
    assert d.route == ex["route"]
    assert d.decision == ex["decision"]
    assert q2(d.value) == Decimal(ex["value"]), f"value {d.value}"
    if "supplier" in ex:
        assert d.supplier_id == ex["supplier"]
        assert d.unit_price is not None and q2(d.unit_price) == Decimal(ex["unit_price"])
        assert d.po_id, "PO decisions carry a PO id"
    else:
        assert d.supplier_id is None and d.po_id is None
    if "suggested" in ex:
        assert list(d.suggested) == ex["suggested"]
    if "relies_on" in ex:
        assert d.contract_id == ex["relies_on"]
        assert ex["relies_on"] in d.reason
    if "same_po_as_example" in ex:
        other = EXAMPLES[ex["same_po_as_example"]]
        other_req = _req(sample_run, other["lines"][0][0], int(other["lines"][0][1]))
        assert sample_run.decisions[other_req.id].po_id == d.po_id
    for p, n in ex.get("not_grouped_with", []):
        assert _req(sample_run, p, int(n)).id != req.id
    assert d.policy_version == "5.0"
    assert d.clause and d.clause in d.reason


def test_po_numbers_are_our_namespace(sample_run: RunResult) -> None:
    """D30: PO ids are sequential in requirement-creation order; co-membership is what matters."""
    ids = [po.id for po in sample_run.pos]
    assert ids == [f"PO-{i:04d}" for i in range(1, len(ids) + 1)]
