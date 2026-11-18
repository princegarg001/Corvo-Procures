"""Snapshot regression (PLAN §13): the full sample batch under v5.0 must not drift.

If an intentional change alters decisions, regenerate with
    python -m procure_engine.cli ../data/kit/pr_batches/sample_pr_batch.csv -o tests/snapshot/sample_batch_v5.csv
and review the diff line by line before committing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from procure_engine.export import decisions_csv
from procure_engine.pipeline import RunResult

SNAPSHOT = Path(__file__).parent / "sample_batch_v5.csv"
if not SNAPSHOT.exists():
    pytest.skip("snapshot is not included in the public repo", allow_module_level=True)


def test_sample_batch_matches_snapshot(sample_run: RunResult) -> None:
    expected = SNAPSHOT.read_text(encoding="utf-8").replace("\r\n", "\n")
    got = decisions_csv(sample_run.rows)
    if got != expected:
        diff = [(a, b) for a, b in zip(expected.splitlines(), got.splitlines(), strict=False) if a != b]
        raise AssertionError(f"{len(diff)} row(s) differ; first: {diff[:2]}")


def test_sample_profile(sample_run: RunResult) -> None:
    s = sample_run.summary
    assert s["input_rows"] == 186 and s["requirements"] == 149 and s["not_processed"] == 2
    assert s["routes_by_requirement"] == {
        "CAPEX_SOURCING": 10, "CONTRACT_PO": 30, "EMERGENCY_PO": 6, "NEW_ITEM_SOURCING": 2,
        "RFP": 4, "RFQ": 39, "SPOT_PO": 58,
    }
    assert s["purchase_orders"] == 82
