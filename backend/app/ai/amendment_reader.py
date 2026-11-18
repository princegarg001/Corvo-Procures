"""Amendment text/document → ops. Phase 3 replaces this stub with the LLM gateway."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session


def from_text(session: Session, text: str, *, actor: str, source_kind: str = "CHAT", title: str = "",
              effective_from: date | None = None) -> dict[str, Any]:
    raise HTTPException(501, "Reading amendment text is not available yet; use the structured editor (ops).")


def from_document(session: Session, data: bytes, filename: str, *, actor: str, title: str = "",
                  effective_from: date | None = None) -> dict[str, Any]:
    raise HTTPException(501, "Reading amendment documents is not available yet; use the structured editor (ops).")
