"""Chat intake API: sessions and messages (PLAN §7, §9); plus the live run refresh."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..services import chat_service, live_service
from .deps import actor, db

router = APIRouter(prefix="/api", tags=["chat"])


class MessageIn(BaseModel):
    text: str = ""
    value: str | None = None


@router.post("/chat/sessions")
def create_session(session: Session = Depends(db), user: str = Depends(actor)) -> dict[str, Any]:
    return chat_service.create_session(session, user)


@router.get("/chat/sessions/{sid}")
def get_session(sid: int, session: Session = Depends(db)) -> dict[str, Any]:
    return chat_service.session_view(session, chat_service.get_session_row(session, sid))


@router.post("/chat/sessions/{sid}/messages")
def post_message(sid: int, body: MessageIn, session: Session = Depends(db), user: str = Depends(actor)) -> dict[str, Any]:
    if len(body.text) > 2000:
        raise HTTPException(413, "message too long")
    try:
        return chat_service.post_message(session, sid, body.text, body.value, user)
    except chat_service.ChatError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/live/refresh")
def refresh_live(session: Session = Depends(db), user: str = Depends(actor)) -> dict[str, Any]:
    run = live_service.refresh(session, user)
    return {"run_id": run.id, "summary": run.summary}
