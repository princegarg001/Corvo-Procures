"""Buyer workspace queries: inbox queues, requirement detail (with trace and history),
PO and sourcing-event views, and preferred-supplier lists (policy §6, brief §3)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from procure_engine.export import preferred_csv, preferred_table
from procure_engine.money import fmt2
from procure_engine.suppliers import SupplierBook

from ..repo.models import (
    AuditEventRow,
    DecisionRow,
    OverrideRow,
    PurchaseOrderRow,
    RequirementRow,
    RunRow,
    SourcingEventRow,
)
from . import masterdata_service, policy_service, run_service

REVIEW_FLAGS = {
    "NO_RULE_MATCHED", "POSSIBLE_DUPLICATE", "AMBIGUOUS_MATCH", "FUZZY_MATCH", "UOM_MISMATCH",
    "DESCRIPTION_MISMATCH", "ESTIMATE_REQUIRED", "SHORT_LIST", "NEED_BY_IN_PAST", "URGENT_IN_TEXT",
    "UNKNOWN_ITEM_CODE", "CONTRACT_CEILING_EXHAUSTED", "VALUED_ON_NON_ACTIVE_SUPPLIER_PO", "CAPEX_APPROVAL",
}


def _latest_decisions(session: Session, req_ids: list[int]) -> dict[int, DecisionRow]:
    out: dict[int, DecisionRow] = {}
    if not req_ids:
        return out
    for d in session.scalars(select(DecisionRow).where(DecisionRow.requirement_id.in_(req_ids)).order_by(DecisionRow.id)):
        out[d.requirement_id] = d
    return out


def requirement_summary(req: RequirementRow, d: DecisionRow, names: dict[str, str], items: dict[str, str]) -> dict[str, Any]:
    return {
        "id": req.id, "run_id": req.run_id, "group_code": req.group_code, "item_code": req.item_code,
        "item_description": items.get(req.item_code) or (req.lines[0].snapshot.get("description") if req.lines else ""),
        "plant": req.plant, "req_date": req.req_date.isoformat(), "created_at": req.created_at.isoformat(timespec="minutes"),
        "emergency": req.emergency, "value": fmt2(d.value), "status": req.status, "policy_version": req.policy_version,
        "decision": d.decision, "route": d.route, "supplier_id": d.supplier_id,
        "supplier_name": names.get(d.supplier_id or "", ""),
        "unit_price": fmt2(d.unit_price) if d.unit_price is not None else None, "suggested": d.suggested,
        "rule_id": d.rule_id, "clause": d.clause, "contract_id": d.contract_id, "po_code": d.po_code,
        "flags": d.flags, "review_flags": sorted(set(d.flags) & REVIEW_FLAGS), "overridden": d.status == "OVERRIDDEN",
        "line_count": len(req.lines),
        "lines": [{"pr_no": ln.pr_no, "line": ln.line, "requester": ln.snapshot.get("requester"),
                   "qty": ln.snapshot.get("qty"), "uom": ln.snapshot.get("uom")} for ln in req.lines],
    }


def default_run_id(session: Session) -> int | None:
    run = session.scalar(select(RunRow).where(RunRow.kind.in_(("BATCH", "LIVE"))).order_by(RunRow.id.desc()).limit(1))
    return run.id if run else None


def list_requirements(session: Session, *, run_id: int | None, status: str | None = None, route: str | None = None,
                      plant: str | None = None, flag: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
    rid = run_id or default_run_id(session)
    if rid is None:
        return []
    reqs = list(session.scalars(select(RequirementRow).where(RequirementRow.run_id == rid)
                                .options(selectinload(RequirementRow.lines)).order_by(RequirementRow.group_code)))
    decisions = _latest_decisions(session, [r.id for r in reqs])
    md = masterdata_service.load_master(session)
    names = {k: v.name for k, v in md.suppliers.items()}
    items = {k: v.description for k, v in md.items.items()}
    out = []
    for r in reqs:
        d = decisions[r.id]
        if status and r.status != status:
            continue
        if route and d.route != route:
            continue
        if plant and r.plant != plant:
            continue
        if flag and flag not in d.flags:
            continue
        s = requirement_summary(r, d, names, items)
        if q:
            hay = " ".join(str(v) for v in (s["group_code"], s["item_code"], s["item_description"], s["supplier_id"],
                                             *[ln["pr_no"] for ln in s["lines"]])).lower()
            if q.lower() not in hay:
                continue
        out.append(s)
    return out


def inbox(session: Session, run_id: int | None) -> dict[str, Any]:
    rid = run_id or default_run_id(session)
    if rid is None:
        return {"run": None, "queues": {}}
    reqs = list_requirements(session, run_id=rid)
    by_po: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sourcing, review, done = [], [], []
    for r in reqs:
        if r["status"] == "APPROVED":
            done.append(r)
            continue
        if r["review_flags"] or not r["decision"]:
            review.append(r)
        if r["decision"] == "PO":
            by_po[r["po_code"] or f"{r['group_code']}-OVR"].append(r)
        elif r["decision"] == "SOURCING_REQUEST":
            sourcing.append(r)
    pos = {p.po_code: p for p in session.scalars(select(PurchaseOrderRow).where(PurchaseOrderRow.run_id == rid))}
    po_queue = []
    for code, rs in sorted(by_po.items()):
        po = pos.get(code)
        po_queue.append({
            "po_code": code, "po_id": po.id if po else None, "supplier_id": rs[0]["supplier_id"],
            "supplier_name": rs[0]["supplier_name"], "plant": rs[0]["plant"], "route": rs[0]["route"],
            "requirements": rs, "total": fmt2(sum((Decimal(r["value"]) for r in rs), Decimal(0))),
            "flags": sorted({f for r in rs for f in r["review_flags"]}),
        })
    total = lambda rs: fmt2(sum((Decimal(r["value"]) for r in rs), Decimal(0)))  # noqa: E731
    run = run_service.get_run(session, rid)
    return {
        "run": run_service.run_view(run),
        "queues": {
            "pos": {"count": len(po_queue), "requirements": sum(len(p["requirements"]) for p in po_queue),
                    "total": fmt2(sum((Decimal(p["total"]) for p in po_queue), Decimal(0))), "items": po_queue},
            "sourcing": {"count": len(sourcing), "total": total(sourcing), "items": sourcing},
            "review": {"count": len(review), "total": total(review), "items": review},
            "done": {"count": len(done), "total": total(done), "items": done},
        },
    }


def requirement_detail(session: Session, requirement_id: int) -> dict[str, Any]:
    req = session.get(RequirementRow, requirement_id)
    if req is None:
        raise policy_service.NotFound(f"requirement {requirement_id} not found")
    history = list(session.scalars(select(DecisionRow).where(DecisionRow.requirement_id == req.id).order_by(DecisionRow.id)))
    d = history[-1]
    md = masterdata_service.load_master(session)
    names = {k: v.name for k, v in md.suppliers.items()}
    items = {k: v.description for k, v in md.items.items()}
    overrides = list(session.scalars(select(OverrideRow).where(OverrideRow.decision_id.in_([h.id for h in history]))))
    events = list(session.scalars(select(SourcingEventRow).where(SourcingEventRow.requirement_id == req.id)))
    audit_rows = list(session.scalars(select(AuditEventRow).where(AuditEventRow.entity == "requirement",
                                                                  AuditEventRow.entity_id == str(req.id))
                                      .order_by(AuditEventRow.id)))
    po = None
    if d.decision == "PO":
        code = d.po_code or f"{req.group_code}-OVR"
        por = session.scalar(select(PurchaseOrderRow).where(PurchaseOrderRow.run_id == req.run_id, PurchaseOrderRow.po_code == code))
        if por is not None:
            po = po_view(session, por)
    item = md.items.get(req.item_code)
    contracts = []
    for opt in d.trace.get("contracts", {}).get("applicable", []):
        contracts.append(opt)
    eligible = []
    policy = policy_service.to_policy(policy_service.get_row(session, req.policy_version)) if req.policy_version else None
    if policy is not None:
        book = SupplierBook(policy, md)
        eligible = [{"id": sid, "name": s.name, "categories": list(s.categories)}
                    for sid, s in md.suppliers.items() if book.eligibility.eligible(sid, req.req_date)]
        po_routes = sorted({r.then.route for r in policy.rules if r.then.decision == "PO"})
        src_routes = sorted({r.then.route for r in policy.rules if r.then.decision == "SOURCING_REQUEST"})
    else:
        po_routes, src_routes = [], []
    return {
        **requirement_summary(req, d, names, items),
        "item": {"code": item.code, "description": item.description, "uom": item.uom, "category": item.category,
                 "type": item.item_type, "standard_price": str(item.standard_price)} if item else None,
        "lines": [{"pr_no": ln.pr_no, "line": ln.line, **ln.snapshot} for ln in req.lines],
        "decision_id": d.id, "reason": d.reason, "trace": d.trace,
        "history": [{"id": h.id, "status": h.status, "route": h.route, "supplier_id": h.supplier_id,
                     "unit_price": fmt2(h.unit_price) if h.unit_price is not None else None, "value": fmt2(h.value),
                     "reason": h.reason, "created_by": h.created_by,
                     "created_at": h.created_at.isoformat() if h.created_at else None, "override_of": h.override_of}
                    for h in history],
        "overrides": [{"id": o.id, "decision_id": o.decision_id, "new_decision_id": o.new_decision_id,
                       "route": o.new_route, "supplier_id": o.new_supplier_id,
                       "price": fmt2(o.new_price) if o.new_price is not None else None, "comment": o.comment,
                       "by": o.by, "at": o.at.isoformat() if o.at else None} for o in overrides],
        "sourcing_events": [{"id": e.id, "code": e.code, "kind": e.kind, "suggested": e.suggested, "status": e.status,
                             "created_by": e.created_by} for e in events],
        "audit": [{"actor": a.actor, "action": a.action, "at": a.at.isoformat() if a.at else None, "after": a.after}
                  for a in audit_rows],
        "po": po, "contracts": contracts, "eligible_suppliers": eligible,
        "routes": {"po": po_routes, "sourcing": src_routes},
        "supplier_names": {sid: names.get(sid, "") for sid in [d.supplier_id, *(d.suggested or [])] if sid},
    }


def po_view(session: Session, po: PurchaseOrderRow) -> dict[str, Any]:
    md = masterdata_service.load_master(session)
    lines = []
    for ln in po.lines:
        req = session.get(RequirementRow, ln.requirement_id)
        lines.append({"requirement_id": ln.requirement_id, "group_code": req.group_code if req else "",
                      "item_code": ln.item_code, "description": md.items[ln.item_code].description if ln.item_code in md.items else "",
                      "uom": md.items[ln.item_code].uom if ln.item_code in md.items else "",
                      "qty": str(ln.qty.normalize()), "unit_price": fmt2(ln.unit_price), "amount": fmt2(ln.amount),
                      "status": req.status if req else "", "pr_lines": [f"{x.pr_no}/{x.line}" for x in (req.lines if req else [])]})
    sup = md.suppliers.get(po.supplier_id)
    return {
        "id": po.id, "code": po.po_code, "run_id": po.run_id, "supplier_id": po.supplier_id,
        "supplier_name": sup.name if sup else "", "supplier_city": sup.city if sup else "", "plant": po.plant,
        "plant_name": md.plants[po.plant].name if po.plant in md.plants else po.plant, "route": po.route,
        "policy_version": po.policy_version, "status": po.status,
        "created_at": po.created_at.isoformat() if po.created_at else None,
        "issued_at": po.issued_at.isoformat() if po.issued_at else None,
        "total": fmt2(sum((ln.amount for ln in po.lines), Decimal(0))), "lines": lines,
    }


def list_pos(session: Session, run_id: int | None) -> list[dict[str, Any]]:
    rid = run_id or default_run_id(session)
    if rid is None:
        return []
    return [po_view(session, p) for p in session.scalars(
        select(PurchaseOrderRow).where(PurchaseOrderRow.run_id == rid).options(selectinload(PurchaseOrderRow.lines))
        .order_by(PurchaseOrderRow.po_code))]


def list_sourcing(session: Session) -> list[dict[str, Any]]:
    out = []
    for e in session.scalars(select(SourcingEventRow).order_by(SourcingEventRow.id.desc())):
        req = session.get(RequirementRow, e.requirement_id)
        out.append({"id": e.id, "code": e.code, "kind": e.kind, "suggested": e.suggested, "status": e.status,
                    "requirement_id": e.requirement_id, "group_code": req.group_code if req else "",
                    "item_code": req.item_code if req else "", "value": fmt2(req.value) if req else "",
                    "created_by": e.created_by, "created_at": e.created_at.isoformat() if e.created_at else None})
    return out


# ----------------------------------------------------------------------------------- preferred suppliers

def preferred_export(session: Session, as_of: date, top: int | None) -> str:
    md = masterdata_service.load_master(session)
    return preferred_csv(md, policy_service.resolver(session), as_of, top)


def preferred_for_item(session: Session, item_code: str, as_of: date) -> dict[str, Any]:
    md = masterdata_service.load_master(session)
    if item_code not in md.items:
        raise policy_service.NotFound(f"unknown item {item_code}")
    res = policy_service.resolver(session)
    policy = res.for_date(as_of)
    book = SupplierBook(policy, md)
    ranked = book.preferred(item_code, as_of)
    max_count = max((r.po_count for r in ranked), default=0)
    excluded = []
    lookback = policy.param_int(policy.preferred_suppliers.lookback_param)
    for po in md.pos_for_item(item_code):
        if (as_of - po.po_date).days <= lookback and po.po_date < as_of and not book.eligibility.eligible(po.supplier_id, as_of):
            excluded.append(po.supplier_id)
    item = md.items[item_code]
    return {
        "item": {"code": item.code, "description": item.description, "category": item.category, "uom": item.uom},
        "as_of": as_of.isoformat(), "policy_version": policy.version,
        "weights": {k: str(v) for k, v in policy.preferred_suppliers.weights.model_dump().items()},
        "ranked": [{
            "rank": r.rank, "supplier_id": r.supplier_id, "name": md.suppliers[r.supplier_id].name,
            "score": f"{r.score:.4f}", "components": {k: f"{v:.4f}" for k, v in r.components.items()},
            "po_count": r.po_count, "last_po_date": r.last_po_date.isoformat() if r.last_po_date else None,
            "days_since_last_po": r.raw["days_since_last_po"], "recency": str(r.raw["recency"]),
            "has_contract": r.has_contract, "contracts": list(r.contract_ids),
            "on_time_pct": str(md.suppliers[r.supplier_id].on_time_pct),
            "quality_rating": str(md.suppliers[r.supplier_id].quality_rating),
            "reference_price": fmt2(r.reference_price) if r.reference_price is not None else None,
            "reference_ref": r.reference_ref, "explanation": r.explanation(max_count),
        } for r in ranked],
        "excluded": [{"supplier_id": s, "name": md.suppliers[s].name if s in md.suppliers else "",
                      "status": book.eligibility.status(s, as_of)} for s in sorted(set(excluded))],
    }


def preferred_overview(session: Session, as_of: date, top: int | None = None) -> list[dict[str, Any]]:
    md = masterdata_service.load_master(session)
    table = preferred_table(md, policy_service.resolver(session), as_of, top)
    return [{"item_code": code, "description": md.items[code].description, "category": md.items[code].category,
             "suppliers": [{"rank": r.rank, "supplier_id": r.supplier_id, "name": md.suppliers[r.supplier_id].name,
                            "reference_price": fmt2(r.reference_price) if r.reference_price is not None else None,
                            "score": f"{r.score:.4f}"} for r in ranked]}
            for code, ranked in table]
