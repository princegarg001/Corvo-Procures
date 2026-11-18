"""Free-text item matching (policy 1.1/1.2) incl. the numeric-token guard and junk rows."""

from __future__ import annotations

import pytest
import yaml

from procure_engine.masterdata import MasterData
from procure_engine.matching import ItemMatcher
from procure_engine.pipeline import RunResult
from procure_engine.policy_schema import Policy
from tests.conftest import GOLDEN

SPEC = yaml.safe_load((GOLDEN / "free_text_matches.yaml").read_text(encoding="utf-8"))


def _resolved(run: RunResult, key: str) -> str:
    pr_no, line = key.split("/")
    for row in run.rows:
        if row.pr_no == pr_no and row.pr_line == line:
            return row.resolved_item_code
    raise AssertionError(f"{key} not in output")


@pytest.mark.parametrize("key", sorted(SPEC["matches"]))
def test_free_text_match(key: str, sample_run: RunResult) -> None:
    assert _resolved(sample_run, key) == SPEC["matches"][key]


@pytest.mark.parametrize("text", sorted(SPEC["negatives"]))
def test_negative(text: str, master: MasterData, policy_v5: Policy) -> None:
    m = ItemMatcher(master.items, policy_v5.matching).match_text(text)
    forbidden = SPEC["negatives"][text]
    if forbidden == "NEW":
        assert m.item_code == "NEW"
    else:
        assert m.item_code not in forbidden


@pytest.mark.parametrize("key", sorted(SPEC["not_processed"]))
def test_not_processed(key: str, sample_run: RunResult) -> None:
    pr_no, line = key.split("/")
    row = next(r for r in sample_run.rows if r.pr_no == pr_no and r.pr_line == line)
    assert row.route == "NOT_PROCESSED"
    assert row.decision == ""
    assert SPEC["not_processed"][key] in row.reason


def test_all_free_text_lines_covered(sample_rows: list[dict[str, str]]) -> None:
    """Every line without an item code is pinned by the fixture (no untested guesses)."""
    free = {f"{r['pr_no']}/{r['pr_line']}" for r in sample_rows if not r["item_code"].strip()}
    assert free == set(SPEC["matches"])
