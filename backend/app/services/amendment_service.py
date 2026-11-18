"""Policy amendments: ops → candidate version → validate → plain-language diff → impact
preview → approve (ACTIVE from its effective date) or reject. PLAN §8.

Source can be the structured editor (ops), a document or chat text (LLM → ops, Phase 3).
Duplicate detection by body hash ("already active as v5.1"). Impact = re-run the latest
batch under the current versions vs current + candidate, and list every changed line.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from procure_engine.policy_ops import apply_ops, describe_ops, parse_ops
from procure_engine.policy_schema import Policy, PolicyError
from procure_engine.validation import lint
from procure_engine.versions import PolicyResolver

from ..config import today
from ..repo.models import PolicyAmendmentRow, PolicyVersionRow
from . import audit, masterdata_service, policy_service, run_service


class AmendmentError(ValueError):
    pass


def _supplier_names(session: Session) -> dict[str, str]:
    md = masterdata_service.load_master(session)
    return {sid: s.name for sid, s in md.suppliers.items()}


def build_candidate(session: Session, ops: list[dict[str, Any]], base: Policy, version: str,
                    effective_from: date | None) -> Policy:
    full_ops = list(ops)
    if effective_from is not None and not any(o.get("op") == "set_effective_from" for o in full_ops):
        full_ops.append({"op": "set_effective_from", "date": effective_from.isoformat()})
    return apply_ops(base, full_ops, new_version=version)


def impact(session: Session, candidate: Policy) -> dict[str, Any]:
    run = run_service.latest_batch_run(session)
    if run is None:
        return {"available": False, "message": "No batch has been processed yet, so there is nothing to compare."}
    rows = run_service.parse_csv_text(run.input_text)
    master = masterdata_service.load_master(session)
    current = policy_service.resolver(session)
    proposed = PolicyResolver([*(v for v in current.versions if v.version != candidate.version), candidate])
    from procure_engine.export import decisions_csv
    from procure_engine.pipeline import Engine

    before = Engine(master, current).run(rows)
    after = Engine(master, proposed).run(rows)
    import csv
    import io

    a = list(csv.DictReader(io.StringIO(decisions_csv(before.rows))))
    b = list(csv.DictReader(io.StringIO(decisions_csv(after.rows))))
    diff = run_service.compare_rows(a, b)
    dates = [req.req_date for req in after.requirements]
    on_or_after = sum(1 for d in dates if d >= candidate.effective_from)
    warnings = []
    if dates and on_or_after == 0:
        warnings.append(
            f"No requirement in '{run.name}' is dated on or after the effective date "
            f"{candidate.effective_from.isoformat()}, so this batch would not change. Check the effective date.")
    elif dates and on_or_after < len(dates):
        warnings.append(
            f"Only {on_or_after} of {len(dates)} requirements in '{run.name}' are dated on or after "
            f"{candidate.effective_from.isoformat()}; earlier ones keep the previous version.")
    if candidate.effective_from < today():
        warnings.append("The effective date is in the past (retroactive): it affects new runs only; "
                        "POs already approved are never changed (D28).")
    return {
        "available": True, "run_id": run.id, "run_name": run.name,
        "requirements": len(dates), "requirements_on_or_after_effective": on_or_after,
        "summary": diff["summary"], "changed": diff["changed"], "grouping_changes": diff["grouping_changes"][:200],
        "warnings": warnings,
    }


def _duplicate_of(session: Session, candidate: Policy) -> PolicyVersionRow | None:
    h = candidate.body_hash()
    return session.scalar(select(PolicyVersionRow).where(
        PolicyVersionRow.body_hash == h, PolicyVersionRow.status.in_(policy_service.APPROVED)))


def evaluate(session: Session, amendment: PolicyAmendmentRow, ops: list[dict[str, Any]],
             effective_from: date | None) -> None:
    """(Re)compute candidate, summary, lint, impact for an amendment; store errors instead of raising."""
    base_row = session.get(PolicyVersionRow, amendment.base_version_id) if amendment.base_version_id else None
    base_row = base_row or policy_service.latest_row(session)
    base = policy_service.to_policy(base_row)
    amendment.base_version_id = base_row.id
    amendment.ops = ops
    amendment.errors = []
    try:
        parse_ops(ops)
        version = (session.get(PolicyVersionRow, amendment.proposed_version_id).version
                   if amendment.proposed_version_id else policy_service.next_version_number(session))
        candidate = build_candidate(session, ops, base, version, effective_from)
    except PolicyError as exc:
        amendment.errors = exc.messages
        amendment.status = "INVALID"
        amendment.summary, amendment.impact, amendment.lint = [], {}, []
        return
    full_ops = list(ops)
    if effective_from is not None and not any(o.get("op") == "set_effective_from" for o in ops):
        full_ops.append({"op": "set_effective_from", "date": effective_from.isoformat()})
    amendment.ops = full_ops
    amendment.summary = describe_ops(full_ops, base, supplier_names=_supplier_names(session))
    md = masterdata_service.load_master(session)
    known_routes = {r.then.route for v in policy_service.resolver(session).versions for r in v.rules}
    amendment.lint = lint(candidate, known_routes=known_routes, supplier_ids=set(md.suppliers))
    dup = _duplicate_of(session, candidate)
    if dup is not None:
        amendment.lint = [f"This content is identical to approved version {dup.version} (duplicate upload).", *amendment.lint]
    if candidate.body_hash() == base.body_hash() and candidate.effective_from == base.effective_from:
        amendment.lint = ["These changes leave the policy unchanged.", *amendment.lint]
    amendment.impact = impact(session, candidate)
    if amendment.proposed_version_id:
        vrow = session.get(PolicyVersionRow, amendment.proposed_version_id)
        assert vrow is not None
        vrow.body, vrow.body_hash = candidate.to_json_dict(), candidate.body_hash()
        vrow.effective_from = candidate.effective_from
    else:
        vrow = policy_service.add_version(session, candidate, status="DRAFT", actor=amendment.created_by,
                                          parent_id=base_row.id)
        amendment.proposed_version_id = vrow.id
    amendment.status = "PROPOSED"
    session.flush()


def create(session: Session, *, ops: list[dict[str, Any]], actor: str, source_kind: str = "EDITOR",
           title: str = "", source_text: str = "", source_file: bytes | None = None,
           source_filename: str | None = None, effective_from: date | None = None,
           questions: list[Any] | None = None, ai_meta: dict[str, Any] | None = None) -> PolicyAmendmentRow:
    row = PolicyAmendmentRow(
        title=title or "Policy amendment", source_kind=source_kind, source_text=source_text,
        source_file=source_file, source_filename=source_filename, ops=[], questions=questions or [],
        ai_meta=ai_meta or {}, status="PROPOSED", created_by=actor,
    )
    session.add(row)
    session.flush()
    evaluate(session, row, ops, effective_from)
    audit.record(session, actor, "amendment.create", "policy_amendment", row.id, None,
                 {"source_kind": source_kind, "ops": row.ops, "status": row.status, "errors": row.errors})
    return row


def get(session: Session, amendment_id: int) -> PolicyAmendmentRow:
    row = session.get(PolicyAmendmentRow, amendment_id)
    if row is None:
        raise policy_service.NotFound(f"amendment {amendment_id} not found")
    return row


def update_ops(session: Session, amendment_id: int, ops: list[dict[str, Any]], actor: str,
               effective_from: date | None = None) -> PolicyAmendmentRow:
    row = get(session, amendment_id)
    if row.status not in ("PROPOSED", "INVALID"):
        raise AmendmentError(f"amendment is {row.status}; it can no longer be edited")
    before = {"ops": row.ops}
    if effective_from is not None:
        ops = [o for o in ops if o.get("op") != "set_effective_from"]
    evaluate(session, row, ops, effective_from)
    audit.record(session, actor, "amendment.edit", "policy_amendment", row.id, before, {"ops": row.ops, "errors": row.errors})
    return row


def approve(session: Session, amendment_id: int, actor: str, comment: str = "") -> PolicyAmendmentRow:
    row = get(session, amendment_id)
    if row.status != "PROPOSED":
        raise AmendmentError(f"amendment is {row.status}; only a valid proposed amendment can be approved")
    if row.errors:
        raise AmendmentError("fix the validation errors before approving")
    vrow = session.get(PolicyVersionRow, row.proposed_version_id) if row.proposed_version_id else None
    if vrow is None:
        raise AmendmentError("no candidate version")
    candidate = policy_service.to_policy(vrow)
    dup = _duplicate_of(session, candidate)
    if dup is not None and dup.effective_from == candidate.effective_from:
        raise AmendmentError(f"already active as v{dup.version}")
    policy_service.activate(session, vrow, actor)
    row.status, row.decided_by, row.decided_at, row.decision_comment = "APPROVED", actor, datetime.now(UTC), comment
    session.flush()
    audit.record(session, actor, "amendment.approve", "policy_amendment", row.id, {"status": "PROPOSED"},
                 {"status": "APPROVED", "version": vrow.version, "effective_from": vrow.effective_from.isoformat()})
    return row


def reject(session: Session, amendment_id: int, actor: str, comment: str = "") -> PolicyAmendmentRow:
    row = get(session, amendment_id)
    if row.status not in ("PROPOSED", "INVALID"):
        raise AmendmentError(f"amendment is {row.status}")
    before = {"status": row.status}
    row.status, row.decided_by, row.decided_at, row.decision_comment = "REJECTED", actor, datetime.now(UTC), comment
    if row.proposed_version_id:
        vrow = session.get(PolicyVersionRow, row.proposed_version_id)
        if vrow is not None and vrow.status == "DRAFT":
            vrow.status = "REJECTED"
            policy_service.free_version_number(vrow)
    session.flush()
    audit.record(session, actor, "amendment.reject", "policy_amendment", row.id, before, {"status": "REJECTED", "comment": comment})
    return row


def view(session: Session, row: PolicyAmendmentRow) -> dict[str, Any]:
    vrow = session.get(PolicyVersionRow, row.proposed_version_id) if row.proposed_version_id else None
    base = session.get(PolicyVersionRow, row.base_version_id) if row.base_version_id else None
    return {
        "id": row.id, "title": row.title, "source_kind": row.source_kind, "source_text": row.source_text,
        "source_filename": row.source_filename, "ops": row.ops, "questions": row.questions, "summary": row.summary,
        "impact": row.impact, "lint": row.lint, "errors": row.errors, "ai_meta": row.ai_meta, "status": row.status,
        "base_version": base.version if base else None,
        "proposed_version": vrow.version if vrow else None,
        "effective_from": vrow.effective_from.isoformat() if vrow else None,
        "created_by": row.created_by, "created_at": row.created_at.isoformat() if row.created_at else None,
        "decided_by": row.decided_by, "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "decision_comment": row.decision_comment,
    }


def list_all(session: Session) -> list[dict[str, Any]]:
    return [view(session, r) | {"impact": {"summary": (r.impact or {}).get("summary")}}
            for r in session.scalars(select(PolicyAmendmentRow).order_by(PolicyAmendmentRow.id.desc()))]
