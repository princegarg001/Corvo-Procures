"""Contracts, preferred suppliers, master data, item matching, audit, users and health."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from procure_engine.matching import ItemMatcher

from ..config import get_settings, today
from ..repo.models import AuditEventRow, ContractRow, User
from ..services import contract_import, inbox_service, masterdata_service, policy_service
from .deps import actor, db, read_upload

router = APIRouter(tags=["master"])


# ------------------------------------------------------------------------------------- contracts

@router.get("/api/contracts")
def contracts(as_of: date | None = None, session: Session = Depends(db)) -> list[dict[str, Any]]:
    return contract_import.list_contracts(session, as_of=as_of or today())


@router.post("/api/contracts/import-pdf")
async def import_pdf(request: Request, session: Session = Depends(db)) -> dict[str, Any]:
    """Extract fields from a signed contract PDF for buyer review (nothing is saved)."""
    data, filename, _ = await read_upload(request)
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "please upload a PDF")
    try:
        out = contract_import.extract(session, data)
    except contract_import.ContractError as exc:
        raise HTTPException(422, str(exc)) from exc
    out["filename"] = filename
    return out


@router.post("/api/contracts")
async def save_contract(request: Request, session: Session = Depends(db), user: str = Depends(actor)) -> dict[str, Any]:
    """Save a reviewed contract: JSON form, or multipart with `form` (JSON) and the `file` PDF."""
    pdf: bytes | None = None
    filename: str | None = None
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        data, filename, fields = await read_upload(request)
        pdf = data
        form = json.loads(fields.get("form", "{}"))
    else:
        form = await request.json()
    try:
        row = contract_import.save(session, form, actor=user, pdf_bytes=pdf, filename=filename)
    except contract_import.ContractError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"id": row.id, "source": row.source}


@router.get("/api/contracts/reconcile")
def reconcile(session: Session = Depends(db)) -> dict[str, Any]:
    return contract_import.reconcile_all(session)


@router.get("/api/contracts/{contract_id}/pdf")
def contract_pdf(contract_id: str, session: Session = Depends(db)) -> Response:
    row = session.get(ContractRow, contract_id)
    if row is None or not row.pdf_object:
        raise HTTPException(404, "no PDF stored for this contract")
    return Response(row.pdf_object, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{row.pdf_filename or contract_id + ".pdf"}"'})


# ------------------------------------------------------------------------------------- suppliers

@router.get("/api/preferred-suppliers/export.csv")
def preferred_export(as_of: date = Query(..., description="YYYY-MM-DD"), top: int = Query(3, ge=1, le=20),
                     session: Session = Depends(db)) -> PlainTextResponse:
    text_ = inbox_service.preferred_export(session, as_of, top)
    return PlainTextResponse(text_, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="preferred_suppliers_{as_of.isoformat()}.csv"'})


@router.get("/api/preferred-suppliers")
def preferred_overview(as_of: date | None = None, top: int = 3, session: Session = Depends(db)) -> list[dict[str, Any]]:
    return inbox_service.preferred_overview(session, as_of or today(), top)


@router.get("/api/preferred-suppliers/{item_code}")
def preferred_item(item_code: str, as_of: date | None = None, session: Session = Depends(db)) -> dict[str, Any]:
    return inbox_service.preferred_for_item(session, item_code, as_of or today())


@router.get("/api/suppliers")
def suppliers(session: Session = Depends(db)) -> list[dict[str, Any]]:
    md = masterdata_service.load_master(session)
    return [{"id": s.id, "name": s.name, "city": s.city, "categories": list(s.categories), "status": s.status,
             "on_time_pct": str(s.on_time_pct), "quality_rating": str(s.quality_rating)} for s in md.suppliers.values()]


@router.get("/api/items")
def items(session: Session = Depends(db)) -> list[dict[str, Any]]:
    md = masterdata_service.load_master(session)
    return [{"code": i.code, "description": i.description, "uom": i.uom, "category": i.category, "type": i.item_type,
             "standard_price": str(i.standard_price)} for i in md.items.values()]


@router.get("/api/plants")
def plants(session: Session = Depends(db)) -> list[dict[str, str]]:
    md = masterdata_service.load_master(session)
    return [{"code": p.code, "name": p.name} for p in md.plants.values()]


@router.get("/api/items/match")
def match(q: str = Query(..., min_length=1), k: int = Query(5, ge=1, le=20), session: Session = Depends(db)) -> dict[str, Any]:
    md = masterdata_service.load_master(session)
    policy = policy_service.resolver(session).for_date(today())
    matcher = ItemMatcher(md.items, policy.matching)
    result = matcher.match_text(q)
    _, ranked = matcher.rank(q, limit=k)
    return {
        "query": q, "resolved": result.item_code, "score": str(result.score.quantize(__import__("decimal").Decimal("0.001"))),
        "flags": list(result.flags),
        "candidates": [{"code": c.item_code, "description": md.items[c.item_code].description, "uom": md.items[c.item_code].uom,
                        "score": f"{c.score:.3f}", "numeric_guard_ok": c.guard_ok, "missing_numbers": list(c.missing_numbers)}
                       for c in ranked],
    }


# ------------------------------------------------------------------------------------- audit, users, health

@router.get("/api/audit")
def audit_log(entity: str | None = None, id: str | None = None, actor_name: str | None = Query(None, alias="actor"),
              limit: int = Query(200, le=2000), session: Session = Depends(db)) -> list[dict[str, Any]]:
    stmt = select(AuditEventRow).order_by(AuditEventRow.id.desc()).limit(limit)
    if entity:
        stmt = stmt.where(AuditEventRow.entity == entity)
    if id:
        stmt = stmt.where(AuditEventRow.entity_id == id)
    if actor_name:
        stmt = stmt.where(AuditEventRow.actor == actor_name)
    return [{"id": a.id, "actor": a.actor, "action": a.action, "entity": a.entity, "entity_id": a.entity_id,
             "before": a.before, "after": a.after, "at": a.at.isoformat() if a.at else None}
            for a in session.scalars(stmt)]


@router.get("/api/users")
def users(session: Session = Depends(db)) -> list[dict[str, Any]]:
    return [{"id": u.id, "name": u.name, "role": u.role} for u in session.scalars(select(User).order_by(User.id))]


@router.get("/api/meta")
def meta(session: Session = Depends(db)) -> dict[str, Any]:
    s = get_settings()
    latest = policy_service.latest_row(session)
    return {"active_policy": latest.version, "effective_from": latest.effective_from.isoformat(),
            "llm_available": s.llm_available, "today": today().isoformat(), "timezone": s.app_tz,
            "database": "sqlite" if s.is_sqlite else "postgresql"}


@router.get("/healthz", tags=["health"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", tags=["health"])
def readyz(session: Session = Depends(db)) -> dict[str, Any]:
    try:
        session.execute(text("SELECT 1"))
        version = policy_service.latest_row(session).version
    except Exception as exc:  # pragma: no cover - only on a broken DB
        raise HTTPException(503, f"database not ready: {exc}") from exc
    return {"status": "ready", "active_policy": version}
