"""Output format (AGENTS.md rule 9): exact columns, one row per input line, in input order."""

from __future__ import annotations

import csv
import io
from datetime import date

from procure_engine.export import DECISION_COLUMNS, decisions_csv, preferred_csv
from procure_engine.masterdata import MasterData
from procure_engine.pipeline import RunResult
from procure_engine.versions import PolicyResolver


def test_decisions_csv_shape(sample_run: RunResult, sample_rows: list[dict[str, str]]) -> None:
    text = decisions_csv(sample_run.rows)
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    assert header == list(DECISION_COLUMNS)
    body = list(reader)
    assert len(body) == len(sample_rows) == 186
    assert [(r[0], r[1]) for r in body] == [(r["pr_no"], r["pr_line"]) for r in sample_rows]
    for r in body:
        row = dict(zip(header, r, strict=True))
        if row["route"] == "NOT_PROCESSED":
            assert row["decision"] == "" and row["reason"]
            continue
        assert row["decision"] in ("PO", "SOURCING_REQUEST")
        if row["decision"] == "PO":
            assert row["po_id"] and row["supplier_id"] and row["unit_price"]
            assert row["suggested_supplier_ids"] == ""
        else:
            assert not row["po_id"] and not row["supplier_id"] and not row["unit_price"]
        assert row["policy_version"] == "5.0"
        assert "." in row["group_value_inr"] and len(row["group_value_inr"].split(".")[1]) == 2


def test_preferred_csv(master: MasterData, resolver: PolicyResolver) -> None:
    text = preferred_csv(master, resolver, date(2026, 11, 1))
    rows = list(csv.DictReader(io.StringIO(text)))
    assert list(rows[0].keys()) == ["item_code", "rank", "supplier_id", "reference_price"]
    per_item: dict[str, int] = {}
    for r in rows:
        per_item[r["item_code"]] = per_item.get(r["item_code"], 0) + 1
        assert master.suppliers[r["supplier_id"]].status == "Active"
    assert max(per_item.values()) <= 3
    nitrile = [r["supplier_id"] for r in rows if r["item_code"] == "ITM-1048"]
    assert nitrile == ["S029", "S030"]
