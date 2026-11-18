"""The no-AI amendment reader (AGENTS.md rule 7 fallback): exact on the drills it can express,
and it never guesses on the ones that need a new rule (no ops, a question instead)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.ai import heuristics
from procure_engine.masterdata import MasterData
from procure_engine.policy_ops import apply_ops, policies_equal
from procure_engine.policy_schema import Policy, load_policy

FIX = Path(__file__).resolve().parents[3] / "fixtures" / "amendments"
EXACT = ["A1", "A5", "A7", "A8", "A9", "A11", "A12"]
NEEDS_RULE = ["A2", "A3", "A4", "A6", "A10"]
TODAY = date(2026, 11, 18)


@pytest.mark.parametrize("aid", EXACT)
def test_reads_param_style_amendments_exactly(aid: str, policy_v5: Policy, master: MasterData) -> None:
    text = (FIX / f"{aid}.md").read_text(encoding="utf-8")
    out = heuristics.read(text, policy_v5, master, TODAY)
    assert all(op["source_quote"] in text for op in out["ops"])
    got = apply_ops(policy_v5, [*out["ops"], {"op": "set_effective_from", "date": out["effective_from"]}],
                    new_version="5.1")
    expected = load_policy(json.loads((FIX / f"{aid}.expected.json").read_text(encoding="utf-8"), parse_float=Decimal))
    a, b = got.to_json_dict(), expected.to_json_dict()
    for doc in (a, b):
        for o in doc["supplier_eligibility"]["overrides"]:
            o.pop("reason", None)
    assert a == b or policies_equal(got, expected)


@pytest.mark.parametrize("aid", NEEDS_RULE)
def test_never_guesses_rule_amendments(aid: str, policy_v5: Policy, master: MasterData) -> None:
    out = heuristics.read((FIX / f"{aid}.md").read_text(encoding="utf-8"), policy_v5, master, TODAY)
    assert out["ops"] == []
    assert out["questions"]


@pytest.mark.parametrize(("text", "value"), [("₹3 lakh", 300000), ("Rs. 7,50,000", 750000), ("₹7.5 lakh", 750000),
                                             ("INR 1 crore", 10000000), ("2.5 lakhs", 250000)])
def test_indian_amounts(text: str, value: int) -> None:
    assert heuristics.money_values(f"limit becomes {text}") == [Decimal(value)]


def test_supplier_word_is_not_money() -> None:
    assert heuristics.money_values("suggest four suppliers, even above the threshold") == []
