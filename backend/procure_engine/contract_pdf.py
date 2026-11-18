"""Deterministic parser for signed rate-contract PDFs, plus register reconciliation.

Policy 4.4: contracts signed after the last register update exist only as signed
PDFs and are binding from their start date; policy 4.2: such contracts start with
zero consumed value. This module turns the kit's contract template into a Contract
and reports field mismatches against the register. It reads PDF *bytes*; opening
files is the caller's job.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .models import Contract, ContractLine
from .money import ZERO, MoneyError, parse_indian_amount

_DATE = r"(\d{4}-\d{2}-\d{2})"
_RE_CONTRACT_NO = re.compile(r"Contract\s+No\.?\s*[:#]?\s*([A-Z]{1,5}-\d{2,4}-\d{1,5})")
_RE_SUPPLIER = re.compile(r"\band\s+(.+?),\s*([A-Za-z .'-]+?)\s*\(\s*Supplier\s+ID\s+([A-Z]+\d+)\s*\)")
_RE_SUPPLIER_ID = re.compile(r"Supplier\s+ID\s+([A-Z]+\d+)")
_RE_TERM = re.compile(rf"valid\s+from\s+{_DATE}\s+to\s+{_DATE}")
_RE_SIGNED = re.compile(rf"entered\s+into\s+on\s+{_DATE}")
_RE_CEILING = re.compile(r"shall\s+not\s+exceed\s+(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d+)?)")
_RE_PLANTS = re.compile(r"\b([A-Z]{3}\d)\s*\(([^)]+)\)")
_RE_ROW = re.compile(r"^\s*\d+\s+([A-Z]{2,5}-\d{2,6})\s+(.+?)\s+([A-Z]{2,6})\s+([\d,]+(?:\.\d+)?)\s*$")


class ContractParseError(ValueError):
    """Raised when a PDF does not look like a rate contract."""


@dataclass
class ParsedContract:
    """Fields extracted from a PDF, before buyer review."""

    contract_id: str
    supplier_id: str
    supplier_name: str
    start: date
    end: date
    value_cap: Decimal
    signed_on: date | None
    plants: tuple[str, ...]
    lines: tuple[ContractLine, ...]
    warnings: list[str] = field(default_factory=list)
    text: str = ""

    def to_contract(self, *, consumed: Decimal = ZERO, source: str = "PDF") -> Contract:
        return Contract(
            id=self.contract_id,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            start=self.start,
            end=self.end,
            value_cap=self.value_cap,
            consumed=consumed,
            source=source,
            lines=self.lines,
            plants=self.plants,
        )


def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, list[list[list[str | None]]]]:
    """Return (text, tables) of every page using pdfplumber."""
    import pdfplumber

    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    texts: list[str] = []
    tables: list[list[list[str | None]]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            texts.append(page.extract_text() or "")
            tables.extend(page.extract_tables() or [])
    return "\n".join(texts), tables


def _lines_from_tables(tables: list[list[list[str | None]]]) -> list[ContractLine]:
    out: list[ContractLine] = []
    for table in tables:
        if not table:
            continue
        header = [(h or "").strip().lower() for h in table[0]]

        def col(*names: str, _header: list[str] = header) -> int | None:
            for i, h in enumerate(_header):
                if any(n in h for n in names):
                    return i
            return None

        i_code, i_desc, i_uom, i_rate = col("item code", "code"), col("description"), col("uom", "unit"), col("rate")
        if i_code is None or i_rate is None:
            continue
        for row in table[1:]:
            cells = [(c or "").strip() for c in row]
            code = cells[i_code] if i_code < len(cells) else ""
            if not code:
                continue
            try:
                rate = parse_indian_amount(cells[i_rate])
            except (MoneyError, IndexError):
                continue
            out.append(
                ContractLine(
                    item_code=code,
                    description=cells[i_desc] if i_desc is not None and i_desc < len(cells) else "",
                    uom=cells[i_uom] if i_uom is not None and i_uom < len(cells) else "",
                    rate=rate,
                )
            )
    return out


def _lines_from_text(text: str) -> list[ContractLine]:
    out: list[ContractLine] = []
    in_schedule = False
    for raw in text.splitlines():
        if "schedule a" in raw.lower():
            in_schedule = True
            continue
        if not in_schedule:
            continue
        m = _RE_ROW.match(raw)
        if m:
            out.append(
                ContractLine(
                    item_code=m.group(1),
                    description=m.group(2).strip(),
                    uom=m.group(3),
                    rate=parse_indian_amount(m.group(4)),
                )
            )
    return out


def parse_contract_text(text: str, tables: list[list[list[str | None]]] | None = None) -> ParsedContract:
    """Parse the kit's rate-contract template from extracted text (+ optional tables)."""
    flat = re.sub(r"\s+", " ", text)
    warnings: list[str] = []

    m_no = _RE_CONTRACT_NO.search(flat)
    if not m_no:
        raise ContractParseError("contract number not found")
    m_sup = _RE_SUPPLIER.search(flat)
    m_sid = _RE_SUPPLIER_ID.search(flat)
    if not m_sid:
        raise ContractParseError("supplier ID not found")
    m_term = _RE_TERM.search(flat)
    if not m_term:
        raise ContractParseError("contract term (valid from ... to ...) not found")
    m_cap = _RE_CEILING.search(flat)
    if not m_cap:
        raise ContractParseError("value ceiling not found")
    m_signed = _RE_SIGNED.search(flat)

    plants_clause = flat[flat.find("Rates.") :] if "Rates." in flat else flat
    plants = tuple(sorted({m.group(1) for m in _RE_PLANTS.finditer(plants_clause.split("Payment")[0])}))
    if not plants:
        warnings.append("no plant list found; contract assumed valid for all plants")

    lines = _lines_from_tables(tables or [])
    if not lines:
        lines = _lines_from_text(text)
    if not lines:
        raise ContractParseError("Schedule A has no item rows")
    codes = [ln.item_code for ln in lines]
    if len(set(codes)) != len(codes):
        warnings.append("duplicate item codes in Schedule A; the last rate wins")
    dedup = {ln.item_code: ln for ln in lines}

    start, end = date.fromisoformat(m_term.group(1)), date.fromisoformat(m_term.group(2))
    if end < start:
        warnings.append("end date is before start date")

    return ParsedContract(
        contract_id=m_no.group(1),
        supplier_id=m_sid.group(1),
        supplier_name=m_sup.group(1).strip() if m_sup else "",
        start=start,
        end=end,
        value_cap=parse_indian_amount(m_cap.group(1)),
        signed_on=date.fromisoformat(m_signed.group(1)) if m_signed else None,
        plants=plants,
        lines=tuple(sorted(dedup.values(), key=lambda ln: ln.item_code)),
        warnings=warnings,
        text=text,
    )


def parse_contract_pdf(pdf_bytes: bytes) -> ParsedContract:
    text, tables = extract_pdf_text(pdf_bytes)
    return parse_contract_text(text, tables)


@dataclass(frozen=True)
class Mismatch:
    contract_id: str
    field: str
    register_value: str
    pdf_value: str


@dataclass
class ReconcileReport:
    """Result of comparing every parsed PDF with the register (PLAN §11)."""

    matched: list[str] = field(default_factory=list)
    pdf_only: list[str] = field(default_factory=list)
    register_only: list[str] = field(default_factory=list)
    mismatches: list[Mismatch] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "matched": self.matched,
            "pdf_only": self.pdf_only,
            "register_only": self.register_only,
            "mismatches": [m.__dict__ for m in self.mismatches],
        }


def reconcile(register: dict[str, Contract], parsed: list[ParsedContract]) -> ReconcileReport:
    """Report contracts that are PDF-only, register-only, or disagree field by field."""
    report = ReconcileReport()
    seen: set[str] = set()
    for pc in sorted(parsed, key=lambda p: p.contract_id):
        seen.add(pc.contract_id)
        reg = register.get(pc.contract_id)
        if reg is None or reg.source == "PDF":
            report.pdf_only.append(pc.contract_id)
            continue
        before = len(report.mismatches)

        def diff(name: str, a: object, b: object, _cid: str = pc.contract_id) -> None:
            if a != b:
                report.mismatches.append(Mismatch(_cid, name, str(a), str(b)))

        diff("supplier_id", reg.supplier_id, pc.supplier_id)
        diff("start_date", reg.start, pc.start)
        diff("end_date", reg.end, pc.end)
        diff("value_cap", reg.value_cap, pc.value_cap)
        reg_rates = {ln.item_code: ln.rate for ln in reg.lines}
        pdf_rates = {ln.item_code: ln.rate for ln in pc.lines}
        for code in sorted(set(reg_rates) | set(pdf_rates)):
            diff(f"rate[{code}]", reg_rates.get(code, "absent"), pdf_rates.get(code, "absent"))
        if len(report.mismatches) == before:
            report.matched.append(pc.contract_id)
    report.register_only = sorted(cid for cid, c in register.items() if cid not in seen and c.source != "PDF")
    return report
