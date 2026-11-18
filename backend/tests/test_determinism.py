"""Rule 5 (AGENTS.md): same inputs → identical outputs; input row order must not matter."""

from __future__ import annotations

import random

from procure_engine.export import decisions_csv
from procure_engine.masterdata import MasterData
from procure_engine.pipeline import RunResult, run_batch
from procure_engine.versions import PolicyResolver


def _by_key(run: RunResult) -> dict[tuple[str, str], tuple[str, ...]]:
    return {
        (r.pr_no, r.pr_line): (r.resolved_item_code, r.group_id, r.po_id, r.decision, r.route, r.supplier_id,
                               r.unit_price, r.group_value_inr, r.suggested_supplier_ids, r.policy_version, r.reason)
        for r in run.rows
    }


def test_shuffle_invariance(sample_rows: list[dict[str, str]], master: MasterData, resolver: PolicyResolver,
                            sample_run: RunResult) -> None:
    expected = _by_key(sample_run)
    rng = random.Random(20261119)
    for _ in range(5):
        rows = list(sample_rows)
        rng.shuffle(rows)
        got = run_batch(rows, master, resolver)
        assert _by_key(got) == expected
        assert [(r.pr_no, r.pr_line) for r in got.rows] == [(r["pr_no"], r["pr_line"]) for r in rows]


def test_idempotent_bytes(sample_rows: list[dict[str, str]], master: MasterData, resolver: PolicyResolver,
                          sample_run: RunResult) -> None:
    again = run_batch(sample_rows, master, resolver)
    assert decisions_csv(again.rows) == decisions_csv(sample_run.rows)
    assert again.decisions["REQ-0001"].trace == sample_run.decisions["REQ-0001"].trace
