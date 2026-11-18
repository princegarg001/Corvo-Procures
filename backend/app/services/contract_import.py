"""Contracts: register listing, PDF extraction → buyer-reviewed form → save, reconcile.

Policy 4.4: contracts signed after the register update exist only as signed PDFs and
bind from their start date; 4.2: they start at zero consumption (decision D15).
Validation (PLAN §11): unknown supplier or item blocks saving; a Blocked/Inactive
supplier is a warning (the contract will not be applicable under 4.1).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from procure_engine.contract_pdf import ContractParseError, ParsedContract, parse_contract_pdf, reconcile
from procure_engine.money import to_decimal

from ..repo.models import ContractLedgerRow, ContractLineRow, ContractRow
from . import audit, masterdata_service


class ContractError(ValueError):
    pass


def parsed_to_form(p: ParsedContract) -> dict[str, Any]:
    return {
        "contract_id": p.contract_id, "supplier_id": p.supplier_id, "supplier_name": p.supplier_name,
        "start_date": p.start.isoformat(), "end_date": p.end.isoformat(), "value_cap": str(p.value_cap),
        "plants": list(p.plants), "signed_on": p.signed_on.isoformat() if p.signed_on else None,
        "lines": [{"item_code": ln.item_code, "description": ln.description, "uom": ln.uom, "rate": str(ln.rate)}
                  for ln in p.lines],
        "warnings": list(p.warnings),
    }


def validate_form(session: Session, form: dict[str, Any]) -> tuple[list[str], list[str]]:
    md = masterdata_service.load_master(session)
    errors: list[str] = []
    warnings: list[str] = []
    sid = (form.get("supplier_id") or "").strip()
    if sid not in md.suppliers:
        errors.append(f"unknown supplier {sid!r}")
    elif md.suppliers[sid].status != "Active":
        warnings.append(f"supplier {sid} is {md.suppliers[sid].status}: the contract will not be applicable (policy 4.1)")
    if not (form.get("contract_id") or "").strip():
        errors.append("contract number is required")
    try:
        start, end = date.fromisoformat(form["start_date"]), date.fromisoformat(form["end_date"])
        if end < start:
            errors.append("end date is before start date")
    except (KeyError, ValueError):
        errors.append("start and end dates are required (YYYY-MM-DD)")
    try:
        if to_decimal(form.get("value_cap", "")) <= 0:
            errors.append("value ceiling must be positive")
    except ValueError:
        errors.append("value ceiling is not a number")
    lines = form.get("lines") or []
    if not lines:
        errors.append("at least one Schedule A line is required")
    for ln in lines:
        code = (ln.get("item_code") or "").strip()
        if code not in md.items:
            errors.append(f"unknown item {code!r}")
        try:
            if to_decimal(ln.get("rate", "")) <= 0:
                errors.append(f"rate for {code} must be positive")
        except ValueError:
            errors.append(f"rate for {code} is not a number")
    for p in form.get("plants") or []:
        if p not in md.plants:
            warnings.append(f"plant {p} is not in the plants master")
    return errors, warnings


def extract(session: Session, pdf_bytes: bytes) -> dict[str, Any]:
    try:
        parsed = parse_contract_pdf(pdf_bytes)
    except ContractParseError as exc:
        raise ContractError(f"could not read this PDF as a rate contract: {exc}") from exc
    form = parsed_to_form(parsed)
    errors, warnings = validate_form(session, form)
    existing = session.get(ContractRow, parsed.contract_id)
    mismatches: list[dict[str, str]] = []
    if existing is not None:
        rep = reconcile({existing.id: masterdata_service.contract_from_row(existing)}, [parsed])
        mismatches = [m.__dict__ for m in rep.mismatches]
        warnings.append(f"{parsed.contract_id} already exists ({existing.source}); saving will attach the PDF only"
                        if not mismatches else f"{parsed.contract_id} exists and differs from this PDF")
    return {"form": form, "errors": errors, "warnings": form["warnings"] + warnings,
            "exists": existing is not None, "mismatches": mismatches}


def save(session: Session, form: dict[str, Any], *, actor: str, pdf_bytes: bytes | None = None,
         filename: str | None = None) -> ContractRow:
    errors, warnings = validate_form(session, form)
    if errors:
        raise ContractError("; ".join(errors))
    cid = form["contract_id"].strip()
    existing = session.get(ContractRow, cid)
    if existing is not None:
        if pdf_bytes and not existing.pdf_object:
            existing.pdf_object, existing.pdf_filename = pdf_bytes, filename
            audit.record(session, actor, "contract.attach_pdf", "contract", cid, None, {"filename": filename})
            session.flush()
            return existing
        raise ContractError(f"contract {cid} already exists")
    row = ContractRow(
        id=cid, supplier_id=form["supplier_id"].strip(), supplier_name=form.get("supplier_name", ""),
        start_date=date.fromisoformat(form["start_date"]), end_date=date.fromisoformat(form["end_date"]),
        value_cap=to_decimal(form["value_cap"]), consumed_at_register=Decimal(0), source="PDF",
        plants=list(form.get("plants") or []), pdf_object=pdf_bytes, pdf_filename=filename,
        register_as_of=None, created_by=actor,
    )
    for ln in form["lines"]:
        row.lines.append(ContractLineRow(item_code=ln["item_code"].strip(), description=ln.get("description", ""),
                                         uom=ln.get("uom", ""), rate=to_decimal(ln["rate"])))
    session.add(row)
    session.flush()
    masterdata_service.invalidate()
    audit.record(session, actor, "contract.create", "contract", cid, None,
                 {**form, "source": "PDF", "consumed": "0", "warnings": warnings})
    return row


def list_contracts(session: Session, *, as_of: date | None = None) -> list[dict[str, Any]]:
    committed = dict(session.execute(
        select(ContractLedgerRow.contract_id, func.sum(ContractLedgerRow.amount)).group_by(ContractLedgerRow.contract_id)
    ).all())
    md = masterdata_service.load_master(session)
    out = []
    for c in session.scalars(select(ContractRow).options(selectinload(ContractRow.lines)).order_by(ContractRow.id)):
        live = c.consumed_at_register + Decimal(committed.get(c.id) or 0)
        on = as_of or date.today()
        status = "Expired" if c.end_date < on else "Not started" if c.start_date > on else "Valid"
        sup = md.suppliers.get(c.supplier_id)
        out.append({
            "id": c.id, "supplier_id": c.supplier_id, "supplier_name": c.supplier_name or (sup.name if sup else ""),
            "supplier_status": sup.status if sup else "Unknown", "start_date": c.start_date.isoformat(),
            "end_date": c.end_date.isoformat(), "value_cap": str(c.value_cap),
            "consumed_at_register": str(c.consumed_at_register), "committed_live": str(Decimal(committed.get(c.id) or 0)),
            "consumed_live": str(live), "remaining": str(c.value_cap - live), "source": c.source,
            "plants": c.plants, "has_pdf": bool(c.pdf_object), "pdf_filename": c.pdf_filename, "validity": status,
            "register_as_of": c.register_as_of.isoformat() if c.register_as_of else None,
            "lines": [{"item_code": ln.item_code, "description": ln.description, "uom": ln.uom, "rate": str(ln.rate)}
                      for ln in c.lines],
        })
    return out


def reconcile_all(session: Session) -> dict[str, Any]:
    """Re-read every stored PDF and compare it with the register rows."""
    rows = list(session.scalars(select(ContractRow).options(selectinload(ContractRow.lines))))
    register = {c.id: masterdata_service.contract_from_row(c) for c in rows}
    parsed: list[ParsedContract] = []
    unreadable: list[str] = []
    for c in rows:
        if c.pdf_object:
            try:
                parsed.append(parse_contract_pdf(c.pdf_object))
            except ContractParseError:
                unreadable.append(c.id)
    rep = reconcile(register, parsed).to_dict()
    rep["without_pdf"] = sorted(c.id for c in rows if not c.pdf_object)
    rep["unreadable"] = unreadable
    rep["pdf_contracts"] = sorted(c.id for c in rows if c.source == "PDF")
    return rep
