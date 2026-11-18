"""Policy versions in the database: load, resolve by date, diff, retire (PLAN §8)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from procure_engine.policy_ops import describe_ops, describe_policy, diff_policies
from procure_engine.policy_schema import Policy, load_policy
from procure_engine.validation import lint
from procure_engine.versions import PolicyResolver, version_key

from ..repo.models import PolicyVersionRow
from . import audit

APPROVED = ("ACTIVE", "SUPERSEDED")
_parsed: dict[tuple[int, str], Policy] = {}



class NotFound(LookupError):
    pass


def to_policy(row: PolicyVersionRow) -> Policy:
    key = (row.id, row.body_hash + row.version)
    if key not in _parsed:
        body = json.loads(json.dumps(row.body), parse_float=Decimal)
        _parsed[key] = load_policy(body)
    return _parsed[key]


def body_of(policy: Policy) -> dict[str, Any]:
    return policy.to_json_dict()


def all_versions(session: Session) -> list[PolicyVersionRow]:
    rows = list(session.scalars(select(PolicyVersionRow)))
    return sorted(rows, key=lambda r: (r.effective_from, version_key(r.version), r.id))


def approved_rows(session: Session) -> list[PolicyVersionRow]:
    return [r for r in all_versions(session) if r.status in APPROVED]


def get_row(session: Session, version: str) -> PolicyVersionRow:
    row = session.scalar(select(PolicyVersionRow).where(PolicyVersionRow.version == version))
    if row is None:
        raise NotFound(f"policy version {version} not found")
    return row


def resolver(session: Session, *, pin: str | None = None, extra: list[Policy] | None = None) -> PolicyResolver:
    versions = [to_policy(r) for r in approved_rows(session)]
    if extra:
        versions = [v for v in versions if v.version not in {e.version for e in extra}] + list(extra)
    if pin is not None and pin not in {v.version for v in versions}:
        # allow pinning a retired/rejected version explicitly for reproduction
        versions.append(to_policy(get_row(session, pin)))
    return PolicyResolver(versions, pin=pin)


def latest_row(session: Session) -> PolicyVersionRow:
    rows = approved_rows(session)
    if not rows:
        raise NotFound("no approved policy version")
    return max(rows, key=lambda r: version_key(r.version))


def free_version_number(row: PolicyVersionRow) -> None:
    """A rejected/retired version gives its number back (history stays in audit_events)."""
    if "-x" in row.version:
        return
    new = f"{row.version}-x{row.id}"
    body = dict(row.body)
    body["version"] = new
    row.version, row.body = new, body


def next_version_number(session: Session) -> str:
    rows = [r for r in all_versions(session) if "-x" not in r.version]
    top = max((version_key(r.version) for r in rows), default=(5, 0))
    return f"{top[0]}.{(top[1] if len(top) > 1 else 0) + 1}"


def add_version(session: Session, policy: Policy, *, status: str, actor: str, parent_id: int | None = None) -> PolicyVersionRow:
    row = PolicyVersionRow(
        policy_id=policy.policy_id, version=policy.version, effective_from=policy.effective_from, status=status,
        body=body_of(policy), body_hash=policy.body_hash(), parent_id=parent_id, created_by=actor,
    )
    if status in APPROVED:
        row.approved_by, row.approved_at = actor, datetime.now(UTC)
    session.add(row)
    session.flush()
    return row


def activate(session: Session, row: PolicyVersionRow, actor: str) -> None:
    before = {"status": row.status}
    for other in approved_rows(session):
        if other.status == "ACTIVE" and other.id != row.id:
            other.status = "SUPERSEDED"
    row.status = "ACTIVE"
    row.approved_by, row.approved_at = actor, datetime.now(UTC)
    session.flush()
    audit.record(session, actor, "policy.activate", "policy_version", row.version, before,
                 {"status": "ACTIVE", "effective_from": row.effective_from.isoformat()})


def retire(session: Session, version: str, actor: str, reason: str) -> PolicyVersionRow:
    row = get_row(session, version)
    if row.status not in APPROVED:
        raise ValueError(f"version {version} is {row.status}, not active")
    if len(approved_rows(session)) <= 1:
        raise ValueError("cannot retire the only approved policy version")
    before = {"status": row.status}
    was_active = row.status == "ACTIVE"
    row.status = "REJECTED"
    free_version_number(row)
    session.flush()
    if was_active:
        latest_row(session).status = "ACTIVE"
    audit.record(session, actor, "policy.retire", "policy_version", version, before, {"status": "REJECTED", "reason": reason})
    return row


def version_view(row: PolicyVersionRow, *, with_body: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.id, "policy_id": row.policy_id, "version": row.version,
        "effective_from": row.effective_from.isoformat(), "status": row.status, "body_hash": row.body_hash,
        "parent_id": row.parent_id, "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "approved_by": row.approved_by, "approved_at": row.approved_at.isoformat() if row.approved_at else None,
    }
    if with_body:
        p = to_policy(row)
        out["body"] = row.body
        out["rules"] = describe_policy(p)
        out["params"] = [
            {"name": k, "value": str(v.value), "unit": v.unit, "label": v.label, "clause": v.clause}
            for k, v in p.params.items()
        ]
        out["lint"] = lint(p)
    return out


def diff_view(session: Session, a: str, b: str) -> dict[str, Any]:
    pa, pb = to_policy(get_row(session, a)), to_policy(get_row(session, b))
    ops = diff_policies(pa, pb)
    return {"from": a, "to": b, "ops": ops, "changes": describe_ops(ops, pa)}
