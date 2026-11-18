"""CSV exports in the exact formats of brief §4 and §3 (preferred suppliers).

Decisions: one row per input PR line, in input order, columns DECISION_COLUMNS.
Preferred suppliers: item_code,rank,supplier_id,reference_price — top N per item as
of a date (policy §6). Free-text cells that could be read as spreadsheet formulas
are prefixed with an apostrophe (CSV formula-injection guard).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from datetime import date

from .masterdata import MasterData
from .models import OutputRow
from .money import fmt2
from .suppliers import RankedSupplier, SupplierBook
from .versions import PolicyResolver

DECISION_COLUMNS = (
    "pr_no", "pr_line", "resolved_item_code", "group_id", "po_id", "decision", "route", "supplier_id",
    "unit_price", "group_value_inr", "suggested_supplier_ids", "policy_version", "reason",
)
PREFERRED_COLUMNS = ("item_code", "rank", "supplier_id", "reference_price")
_FORMULA_START = ("=", "+", "@", "\t", "\r")


def safe_cell(text: str) -> str:
    if text.startswith(_FORMULA_START) or (text.startswith("-") and not text[1:2].isdigit()):
        return "'" + text
    return text


def _writer(buf: io.StringIO) -> csv.DictWriter[str]:
    return csv.DictWriter(buf, fieldnames=[], lineterminator="\n")


def decisions_csv(rows: Iterable[OutputRow]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(DECISION_COLUMNS)
    for r in sorted(rows, key=lambda r: r.row_index):
        w.writerow([
            r.pr_no, r.pr_line, r.resolved_item_code, r.group_id, r.po_id, r.decision, r.route,
            r.supplier_id, r.unit_price, r.group_value_inr, r.suggested_supplier_ids, r.policy_version,
            safe_cell(r.reason),
        ])
    return buf.getvalue()


def preferred_table(master: MasterData, resolver: PolicyResolver, as_of: date,
                    top: int | None = None) -> list[tuple[str, list[RankedSupplier]]]:
    policy = resolver.for_date(as_of)
    book = SupplierBook(policy, master)
    n = top if top is not None else policy.preferred_suppliers.export_top
    return [(code, book.preferred(code, as_of)[:n]) for code in sorted(master.items)]


def preferred_csv(master: MasterData, resolver: PolicyResolver, as_of: date, top: int | None = None) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(PREFERRED_COLUMNS)
    for code, ranked in preferred_table(master, resolver, as_of, top):
        for r in ranked:
            w.writerow([code, r.rank, r.supplier_id, fmt2(r.reference_price) if r.reference_price is not None else ""])
    return buf.getvalue()
