"""Policy versions, diffs, fact registry and amendments (PLAN §7, §8)."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from procure_engine.facts import TYPE_OPS, registry_listing
from procure_engine.policy_ops import OP_NAMES, ops_json_schema
from procure_engine.policy_schema import OPS

from ..services import amendment_service, policy_service
from .deps import actor, db, read_upload

router = APIRouter(prefix="/api/policy", tags=["policy"])


class AmendmentIn(BaseModel):
    ops: list[dict[str, Any]] | None = None
    text: str | None = None
    title: str = ""
    effective_from: date | None = None


class AmendmentEdit(BaseModel):
    ops: list[dict[str, Any]]
    effective_from: date | None = None


class Decide(BaseModel):
    comment: str = ""


class Retire(BaseModel):
    reason: str = Field(min_length=1)


@router.get("/versions")
def versions(session: Session = Depends(db)) -> list[dict[str, Any]]:
    return [policy_service.version_view(r) for r in policy_service.all_versions(session)]


@router.get("/active")
def active(session: Session = Depends(db)) -> dict[str, Any]:
    return policy_service.version_view(policy_service.latest_row(session), with_body=True)


@router.get("/versions/{version}")
def version(version: str, session: Session = Depends(db)) -> dict[str, Any]:
    return policy_service.version_view(policy_service.get_row(session, version), with_body=True)


@router.post("/versions/{version}/retire")
def retire(version: str, body: Retire, session: Session = Depends(db), user: str = Depends(actor)) -> dict[str, Any]:
    try:
        row = policy_service.retire(session, version, user, body.reason)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return policy_service.version_view(row)


@router.get("/diff")
def diff(request: Request, session: Session = Depends(db)) -> dict[str, Any]:
    a, b = request.query_params.get("from"), request.query_params.get("to")
    if not a or not b:
        raise HTTPException(422, "query parameters 'from' and 'to' are required")
    return policy_service.diff_view(session, a, b)


@router.get("/facts")
def facts() -> dict[str, Any]:
    return {"facts": registry_listing(), "operators": list(OPS), "type_ops": TYPE_OPS, "ops": list(OP_NAMES),
            "supplier_strategies": ["contract", "preferred:N", "fixed:<supplier id>", "none"],
            "price_strategies": ["contract_rate", "reference_price", "last_po_price", "standard_price"]}


@router.get("/ops-schema")
def ops_schema() -> dict[str, Any]:
    return ops_json_schema()


@router.get("/amendments")
def amendments(session: Session = Depends(db)) -> list[dict[str, Any]]:
    return amendment_service.list_all(session)


@router.post("/amendments")
async def create_amendment(request: Request, session: Session = Depends(db), user: str = Depends(actor)) -> dict[str, Any]:
    """JSON `{ops, title, effective_from}` (structured editor), JSON `{text}` (chat), or a
    multipart document upload (PDF/DOCX/TXT/MD) — text and documents are read by the AI gateway."""
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        data, filename, fields = await read_upload(request)
        from ..ai import amendment_reader

        return amendment_reader.from_document(session, data, filename or "amendment", actor=user,
                                              title=fields.get("title", ""),
                                              effective_from=_date(fields.get("effective_from")))
    try:
        body = AmendmentIn.model_validate(await request.json())
    except Exception as exc:
        raise HTTPException(422, f"invalid body: {exc}") from exc
    if body.ops is not None:
        row = amendment_service.create(session, ops=body.ops, actor=user, source_kind="EDITOR", title=body.title,
                                       effective_from=body.effective_from)
        return amendment_service.view(session, row)
    if body.text:
        from ..ai import amendment_reader

        return amendment_reader.from_text(session, body.text, actor=user, source_kind="CHAT", title=body.title,
                                          effective_from=body.effective_from)
    raise HTTPException(422, "give either 'ops' or 'text'")


def _date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(422, f"invalid date {value!r}") from exc


@router.get("/amendments/{amendment_id}")
def get_amendment(amendment_id: int, session: Session = Depends(db)) -> dict[str, Any]:
    return amendment_service.view(session, amendment_service.get(session, amendment_id))


@router.put("/amendments/{amendment_id}")
def edit_amendment(amendment_id: int, body: AmendmentEdit, session: Session = Depends(db),
                   user: str = Depends(actor)) -> dict[str, Any]:
    try:
        row = amendment_service.update_ops(session, amendment_id, body.ops, user, body.effective_from)
    except amendment_service.AmendmentError as exc:
        raise HTTPException(409, str(exc)) from exc
    return amendment_service.view(session, row)


@router.post("/amendments/{amendment_id}/approve")
def approve(amendment_id: int, body: Decide | None = None, session: Session = Depends(db),
            user: str = Depends(actor)) -> dict[str, Any]:
    try:
        row = amendment_service.approve(session, amendment_id, user, (body or Decide()).comment)
    except amendment_service.AmendmentError as exc:
        raise HTTPException(409, str(exc)) from exc
    return amendment_service.view(session, row)


@router.post("/amendments/{amendment_id}/reject")
def reject(amendment_id: int, body: Decide | None = None, session: Session = Depends(db),
           user: str = Depends(actor)) -> dict[str, Any]:
    try:
        row = amendment_service.reject(session, amendment_id, user, (body or Decide()).comment)
    except amendment_service.AmendmentError as exc:
        raise HTTPException(409, str(exc)) from exc
    return amendment_service.view(session, row)
