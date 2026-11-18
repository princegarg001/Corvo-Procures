"""Batch intake: parse PR rows and reject lines that cannot be processed.

Implements decisions D1 (unknown plant), D2 (quantity zero / negative / not a
number) and D23 (NOT_PROCESSED rows keep their place with a reason). Rows are
plain dicts in the sample-batch column format; input order is preserved by
`row_index` so the output has one row per input line, in input order.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime

from .models import PRLine, RejectedLine
from .money import ZERO, MoneyError, optional_decimal, to_decimal

REQUIRED_COLUMNS = (
    "pr_no", "pr_line", "created_at", "plant", "item_code", "description",
    "quantity", "uom", "need_by_date", "urgency",
)
OPTIONAL_COLUMNS = ("requester", "department", "estimated_unit_price")

_DT_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M")
_D_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y")


class BatchFormatError(ValueError):
    """The file is not a PR batch (missing columns)."""


def parse_datetime(text: str) -> datetime:
    text = text.strip()
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(text).replace(tzinfo=None)


def parse_date(text: str) -> date:
    text = text.strip()
    for fmt in _D_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return date.fromisoformat(text)


def check_columns(header: Sequence[str]) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise BatchFormatError("missing column(s): " + ", ".join(missing))


def parse_rows(rows: Sequence[Mapping[str, str | None]]) -> tuple[list[PRLine], list[RejectedLine]]:
    """Parse rows; rows that cannot be read become RejectedLine (NOT_PROCESSED)."""
    if rows:
        check_columns(list(rows[0].keys()))
    lines: list[PRLine] = []
    rejected: list[RejectedLine] = []
    seen: dict[tuple[str, int], int] = {}
    for idx, raw in enumerate(rows):
        row = {k: (v or "").strip() for k, v in raw.items() if k is not None}
        pr_no, pr_line_text = row.get("pr_no", ""), row.get("pr_line", "")

        def reject(reason: str, _idx: int = idx, _row: dict[str, str] = row) -> None:
            rejected.append(RejectedLine(_idx, _row.get("pr_no", ""), _row.get("pr_line", ""), reason, _row))

        if not pr_no:
            reject("missing pr_no")
            continue
        try:
            pr_line = int(pr_line_text)
        except ValueError:
            reject(f"invalid pr_line {pr_line_text!r}")
            continue
        if (pr_no, pr_line) in seen:
            reject(f"duplicate of input row {seen[(pr_no, pr_line)] + 1} ({pr_no}/{pr_line})")
            continue
        try:
            created = parse_datetime(row.get("created_at", ""))
        except ValueError:
            reject(f"invalid created_at {row.get('created_at')!r}")
            continue
        try:
            need_by = parse_date(row.get("need_by_date", ""))
        except ValueError:
            reject(f"invalid need_by_date {row.get('need_by_date')!r}")
            continue
        try:
            qty = to_decimal(row.get("quantity", ""))
        except MoneyError:
            reject(f"quantity is not a number ({row.get('quantity')!r})")
            continue
        try:
            est = optional_decimal(row.get("estimated_unit_price"))
        except MoneyError:
            est = None
        if not row.get("item_code") and not row.get("description"):
            reject("no item code or description")
            continue
        seen[(pr_no, pr_line)] = idx
        lines.append(PRLine(
            row_index=idx, pr_no=pr_no, pr_line=pr_line, created_at=created,
            requester=row.get("requester", ""), department=row.get("department", ""),
            plant=row.get("plant", ""), item_code=row.get("item_code", ""),
            description=row.get("description", ""), quantity=qty, uom=row.get("uom", ""),
            est_unit_price=est, need_by=need_by, urgency=row.get("urgency", "") or "Normal",
        ))
    return lines, rejected


def validate_line(line: PRLine, plants: Mapping[str, object]) -> str | None:
    """Master-data checks; returns the NOT_PROCESSED reason or None."""
    if line.quantity <= ZERO:
        return "quantity must be > 0"
    if line.plant not in plants:
        return f"unknown plant {line.plant}" if line.plant else "missing plant"
    return None
