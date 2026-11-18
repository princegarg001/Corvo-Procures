"""Buyer workspace API: inbox, requirements, approve/override, POs, sourcing events."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..services import approval_service, inbox_service
from .deps import actor, db

router = APIRouter(prefix="/api", tags=["workspace"])


class OverrideIn(BaseModel):
    route: str
    supplier_id: str | None = None
    unit_price: str | float | None = None
    comment: str = ""


@router.get("/inbox")
def inbox(run_id: int | None = None, session: Session = Depends(db)) -> dict[str, Any]:
    return inbox_service.inbox(session, run_id)


@router.get("/requirements")
def requirements(run_id: int | None = None, status: str | None = None, route: str | None = None,
                 plant: str | None = None, flag: str | None = None, q: str | None = None,
                 session: Session = Depends(db)) -> list[dict[str, Any]]:
    return inbox_service.list_requirements(session, run_id=run_id, status=status, route=route, plant=plant, flag=flag, q=q)


@router.get("/requirements/{requirement_id}")
def requirement(requirement_id: int, session: Session = Depends(db)) -> dict[str, Any]:
    return inbox_service.requirement_detail(session, requirement_id)


@router.post("/requirements/{requirement_id}/approve")
def approve(requirement_id: int, session: Session = Depends(db), user: str = Depends(actor)) -> dict[str, Any]:
    try:
        return approval_service.approve(session, requirement_id, user)
    except approval_service.ActionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/requirements/{requirement_id}/override")
def override(requirement_id: int, body: OverrideIn, session: Session = Depends(db),
             user: str = Depends(actor)) -> dict[str, Any]:
    try:
        return approval_service.override(session, requirement_id, route=body.route, supplier_id=body.supplier_id,
                                         unit_price=body.unit_price, comment=body.comment, actor=user)
    except approval_service.ActionError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/purchase-orders")
def purchase_orders(run_id: int | None = None, session: Session = Depends(db)) -> list[dict[str, Any]]:
    return inbox_service.list_pos(session, run_id)


@router.get("/purchase-orders/{po_id}")
def purchase_order(po_id: int, session: Session = Depends(db)) -> dict[str, Any]:
    from ..repo.models import PurchaseOrderRow
    from ..services.policy_service import NotFound

    po = session.get(PurchaseOrderRow, po_id)
    if po is None:
        raise NotFound(f"PO {po_id} not found")
    return inbox_service.po_view(session, po)


@router.post("/purchase-orders/{po_id}/approve")
def approve_po(po_id: int, session: Session = Depends(db), user: str = Depends(actor)) -> dict[str, Any]:
    try:
        return approval_service.approve_po(session, po_id, user)
    except approval_service.ActionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/purchase-orders/{po_id}/issue")
def issue_po(po_id: int, session: Session = Depends(db), user: str = Depends(actor)) -> dict[str, Any]:
    try:
        return approval_service.issue_po(session, po_id, user)
    except approval_service.ActionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/sourcing-events")
def sourcing_events(session: Session = Depends(db)) -> list[dict[str, Any]]:
    return inbox_service.list_sourcing(session)
