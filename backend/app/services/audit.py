"""Append-only audit trail (AGENTS.md rule 8, policy 8.1): who did what, when, before/after."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from ..repo.models import AuditEventRow


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    return value


def record(session: Session, actor: str, action: str, entity: str, entity_id: object,
           before: dict[str, Any] | None = None, after: dict[str, Any] | None = None) -> AuditEventRow:
    row = AuditEventRow(actor=actor or "anonymous", action=action, entity=entity, entity_id=str(entity_id),
                        before=_jsonable(before) if before is not None else None,
                        after=_jsonable(after) if after is not None else None)
    session.add(row)
    session.flush()
    return row
