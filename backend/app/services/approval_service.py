"""Buyer actions — brief §3 'Buyer workspace', policy 8.1, decisions D27, D28.

Approve: a PO decision approves the requirement's line on its consolidated PO (the PO is
APPROVED when all its lines are) and commits contract ceiling to the ledger; a sourcing
decision launches a sourcing event (RFQ / RFP / capex / new-item request).
Override: a new decisions row (the original is kept), an overrides row with a mandatory
comment, and only eligible (Active) suppliers. Everything is audited.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from procure_engine.money import to_decimal
from procure_engine.suppliers import Eligibility

from ..repo.models import (
    ContractLedgerRow,
    DecisionRow,
    OverrideRow,
    POLineRow,
    PurchaseOrderRow,
    RequirementRow,
    SourcingEventRow,
)
from . import audit, masterdata_service, policy_service


class ActionError(ValueError):
    pass


def current_decision(session: Session, requirement_id: int) -> DecisionRow:
    row = session.scalar(select(DecisionRow).where(DecisionRow.requirement_id == requirement_id)
                         .order_by(DecisionRow.id.desc()).limit(1))
    if row is None:
        raise policy_service.NotFound(f"no decision for requirement {requirement_id}")
    return row


def get_requirement(session: Session, requirement_id: int) -> RequirementRow:
    row = session.get(RequirementRow, requirement_id)
    if row is None:
        raise policy_service.NotFound(f"requirement {requirement_id} not found")
    return row


def _event_code(session: Session, kind: str) -> str:
    n = (session.scalar(select(func.count()).select_from(SourcingEventRow)) or 0) + 1
    prefix = {"RFQ": "RFQ", "RFP": "RFP", "CAPEX_SOURCING": "CPX", "NEW_ITEM_SOURCING": "NIS"}.get(kind, "SRC")
    return f"{prefix}-{n:05d}"


def approve(session: Session, requirement_id: int, actor: str) -> dict[str, Any]:
    req = get_requirement(session, requirement_id)
    if req.status == "APPROVED":
        raise ActionError("already approved")
    d = current_decision(session, req.id)
    if not d.decision:
        raise ActionError("this requirement needs review; override it with a route first")
    result: dict[str, Any] = {"requirement_id": req.id, "decision_id": d.id}
    if d.decision == "PO":
        po = _po_for(session, req, d, actor)
        result["po"] = {"id": po.id, "code": po.po_code, "status": po.status}
        if d.contract_id:
            session.add(ContractLedgerRow(contract_id=d.contract_id, requirement_id=req.id,
                                          amount=d.value, kind="COMMIT"))
    else:
        ev = SourcingEventRow(code=_event_code(session, d.route), requirement_id=req.id, kind=d.route,
                              suggested=list(d.suggested), status="LAUNCHED", created_by=actor)
        session.add(ev)
        session.flush()
        result["sourcing_event"] = {"id": ev.id, "code": ev.code, "kind": ev.kind}
    req.status = "APPROVED"
    session.flush()
    if d.decision == "PO":
        _refresh_po_status(session, req.run_id)
    audit.record(session, actor, "requirement.approve", "requirement", req.id, {"status": "OPEN"},
                 {"status": "APPROVED", "route": d.route, "supplier": d.supplier_id, **{k: v for k, v in result.items() if k != "requirement_id"}})
    return result


def _po_for(session: Session, req: RequirementRow, d: DecisionRow, actor: str) -> PurchaseOrderRow:
    if d.po_code:
        po = session.scalar(select(PurchaseOrderRow).where(PurchaseOrderRow.run_id == req.run_id,
                                                           PurchaseOrderRow.po_code == d.po_code))
        if po is not None:
            return po
    # an overridden PO decision: its own PO
    code = f"{req.group_code}-OVR"
    po = PurchaseOrderRow(po_code=code, run_id=req.run_id, supplier_id=d.supplier_id or "", plant=req.plant,
                          route=d.route, policy_version=req.policy_version, status="PROPOSED", created_by=actor)
    qty = sum((to_decimal(ln.snapshot.get("qty", "0")) for ln in req.lines), Decimal(0))
    price = d.unit_price or Decimal(0)
    po.lines.append(POLineRow(requirement_id=req.id, item_code=req.item_code, qty=qty, unit_price=price, amount=qty * price))
    session.add(po)
    session.flush()
    return po


def _refresh_po_status(session: Session, run_id: int) -> None:
    for po in session.scalars(select(PurchaseOrderRow).where(PurchaseOrderRow.run_id == run_id,
                                                             PurchaseOrderRow.status == "PROPOSED")):
        statuses = [session.get(RequirementRow, ln.requirement_id) for ln in po.lines]
        if po.lines and all(r is not None and r.status == "APPROVED" for r in statuses):
            po.status = "APPROVED"


def approve_po(session: Session, po_id: int, actor: str) -> dict[str, Any]:
    po = session.get(PurchaseOrderRow, po_id)
    if po is None:
        raise policy_service.NotFound(f"PO {po_id} not found")
    approved = []
    for ln in po.lines:
        req = session.get(RequirementRow, ln.requirement_id)
        if req is not None and req.status != "APPROVED":
            approve(session, req.id, actor)
            approved.append(req.group_code)
    session.flush()
    return {"po_id": po.id, "code": po.po_code, "status": po.status, "approved_requirements": approved}


def issue_po(session: Session, po_id: int, actor: str) -> dict[str, Any]:
    po = session.get(PurchaseOrderRow, po_id)
    if po is None:
        raise policy_service.NotFound(f"PO {po_id} not found")
    if po.status != "APPROVED":
        raise ActionError("approve every requirement on the PO before issuing it")
    po.status, po.issued_at = "ISSUED", datetime.now(UTC)
    audit.record(session, actor, "po.issue", "purchase_order", po.po_code, {"status": "APPROVED"}, {"status": "ISSUED"})
    return {"po_id": po.id, "code": po.po_code, "status": po.status}


def override(session: Session, requirement_id: int, *, route: str, supplier_id: str | None,
             unit_price: Any, comment: str, actor: str) -> dict[str, Any]:
    if not comment or not comment.strip():
        raise ActionError("an override needs a written reason (policy 8.1)")
    req = get_requirement(session, requirement_id)
    if req.status == "APPROVED":
        raise ActionError("already approved; overrides apply to open requirements only")
    original = current_decision(session, req.id)
    policy = policy_service.to_policy(policy_service.get_row(session, req.policy_version))
    po_routes = {r.then.route for r in policy.rules if r.then.decision == "PO"}
    sourcing_routes = {r.then.route for r in policy.rules if r.then.decision == "SOURCING_REQUEST"}
    if route not in po_routes | sourcing_routes:
        raise ActionError(f"unknown route {route}; choose one of {sorted(po_routes | sourcing_routes)}")
    decision = "PO" if route in po_routes else "SOURCING_REQUEST"
    md = masterdata_service.load_master(session)
    price: Decimal | None = None
    suggested: list[str] = []
    if decision == "PO":
        if not supplier_id:
            raise ActionError("a PO override needs a supplier")
        if not Eligibility(policy, md).eligible(supplier_id, req.req_date):
            status = md.suppliers[supplier_id].status if supplier_id in md.suppliers else "unknown"
            raise ActionError(f"supplier {supplier_id} is {status}; Blocked/Inactive suppliers cannot be selected (policy 5.7)")
        try:
            price = to_decimal(unit_price)
        except Exception as exc:
            raise ActionError("a PO override needs a unit price") from exc
        if price <= 0:
            raise ActionError("unit price must be positive")
    else:
        suggested = [s for s in (original.suggested or []) if Eligibility(policy, md).eligible(s, req.req_date)]
    qty = sum((to_decimal(ln.snapshot.get("qty", "0")) for ln in req.lines), Decimal(0))
    value = qty * price if price is not None else original.value
    trace = dict(original.trace)
    trace["override"] = {"of_decision": original.id, "by": actor, "comment": comment, "route": route,
                         "supplier": supplier_id, "unit_price": str(price) if price is not None else None}
    new = DecisionRow(
        requirement_id=req.id, decision=decision, route=route, supplier_id=supplier_id if decision == "PO" else None,
        unit_price=price, value=value, suggested=suggested, rule_id="OVERRIDE", clause="8.1", contract_id=None,
        po_code=None, flags=sorted({*original.flags, "OVERRIDDEN"}), trace=trace,
        reason=f"Overridden by {actor} (policy 8.1): {comment.strip()}. Original: {original.reason}",
        status="OVERRIDDEN", override_of=original.id, created_by=actor,
    )
    session.add(new)
    session.flush()
    ov = OverrideRow(decision_id=original.id, new_decision_id=new.id, new_route=route,
                     new_supplier_id=new.supplier_id, new_price=price, comment=comment.strip(), by=actor)
    session.add(ov)
    # drop the requirement from its proposed consolidated PO
    if original.po_code:
        po = session.scalar(select(PurchaseOrderRow).where(PurchaseOrderRow.run_id == req.run_id,
                                                           PurchaseOrderRow.po_code == original.po_code))
        if po is not None:
            po.lines = [ln for ln in po.lines if ln.requirement_id != req.id]
    session.flush()
    audit.record(session, actor, "requirement.override", "requirement", req.id,
                 {"decision_id": original.id, "route": original.route, "supplier": original.supplier_id,
                  "unit_price": original.unit_price},
                 {"decision_id": new.id, "route": route, "supplier": new.supplier_id, "unit_price": price, "comment": comment})
    return {"requirement_id": req.id, "decision_id": new.id, "override_id": ov.id}
