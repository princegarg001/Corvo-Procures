"""Live mode: PRs raised in chat (or via the API) are decided together in one persistent LIVE
run, so they club with each other (policy 2.1) and appear in the buyer inbox.

Each refresh re-decides every live line that is not on an approved requirement; approved
requirements are never touched (decision D28). The contract ledger baseline is the register
plus ceiling already committed by approvals (decision D14, live side).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from procure_engine.export import decisions_csv
from procure_engine.pipeline import Engine, RunResult

from ..repo.models import (
    ContractLedgerRow,
    DecisionRow,
    PRHeaderRow,
    PRLineRow,
    PurchaseOrderRow,
    RequirementLineRow,
    RequirementRow,
    RunRow,
)
from . import audit, masterdata_service, policy_service, run_service

LIVE_NAME = "Live PRs (chat & API)"


def live_run(session: Session) -> RunRow:
    run = session.scalar(select(RunRow).where(RunRow.kind == "LIVE").limit(1))
    if run is None:
        run = RunRow(name=LIVE_NAME, kind="LIVE", input_hash="", input_text="", output_csv="", created_by="system",
                     summary={"refresh": 0})
        session.add(run)
        session.flush()
    return run


def _frozen_ids(session: Session, run: RunRow) -> set[int]:
    """Requirements a buyer has acted on (approved or overridden) are never re-decided."""
    approved = set(session.scalars(select(RequirementRow.id).where(RequirementRow.run_id == run.id,
                                                                    RequirementRow.status == "APPROVED")))
    overridden = set(session.scalars(
        select(DecisionRow.requirement_id).join(RequirementRow, RequirementRow.id == DecisionRow.requirement_id)
        .where(RequirementRow.run_id == run.id, DecisionRow.status == "OVERRIDDEN")))
    return approved | overridden


def _approved_lines(session: Session, run: RunRow) -> set[tuple[str, int]]:
    frozen = _frozen_ids(session, run)
    if not frozen:
        return set()
    rows = session.execute(select(RequirementLineRow.pr_no, RequirementLineRow.line)
                           .where(RequirementLineRow.requirement_id.in_(frozen))).all()
    return {(p, n) for p, n in rows}


def line_to_row(h: PRHeaderRow, ln: PRLineRow) -> dict[str, str]:
    return {
        "pr_no": h.pr_no, "pr_line": str(ln.line), "created_at": h.created_at.strftime("%Y-%m-%d %H:%M"),
        "requester": h.requester, "department": h.department, "plant": ln.plant, "item_code": ln.item_code_input,
        "description": ln.description, "quantity": f"{ln.qty.normalize():f}", "uom": ln.uom,
        "estimated_unit_price": f"{ln.est_unit_price.normalize():f}" if ln.est_unit_price is not None else "",
        "need_by_date": ln.need_by.isoformat(), "urgency": ln.urgency,
    }


def open_rows(session: Session) -> list[dict[str, str]]:
    run = live_run(session)
    approved = _approved_lines(session, run)
    out = []
    for h in session.scalars(select(PRHeaderRow).options(selectinload(PRHeaderRow.lines)).order_by(PRHeaderRow.created_at)):
        for ln in h.lines:
            if (h.pr_no, ln.line) not in approved:
                out.append(line_to_row(h, ln))
    return out


def ledger_baseline(session: Session) -> dict[str, Decimal]:
    md = masterdata_service.load_master(session)
    committed = dict(session.execute(select(ContractLedgerRow.contract_id, func.sum(ContractLedgerRow.amount))
                                     .group_by(ContractLedgerRow.contract_id)).all())
    return {cid: c.consumed + Decimal(committed.get(cid) or 0) for cid, c in md.contracts.items()}


def evaluate(session: Session, extra_rows: list[dict[str, str]] | None = None) -> RunResult:
    rows = open_rows(session) + list(extra_rows or [])
    master = masterdata_service.load_master(session)
    engine = Engine(master, policy_service.resolver(session))
    return engine.run(rows, ledger_baseline=ledger_baseline(session), req_prefix="LREQ-", po_prefix="LPO-")


def refresh(session: Session, actor: str) -> RunRow:
    run = live_run(session)
    k = int((run.summary or {}).get("refresh", 0)) + 1
    rows = open_rows(session)
    master = masterdata_service.load_master(session)
    result = Engine(master, policy_service.resolver(session)).run(
        rows, ledger_baseline=ledger_baseline(session), req_prefix=f"L{k}-REQ-", po_prefix=f"L{k}-PO-")
    frozen = _frozen_ids(session, run)
    open_ids = [i for i in session.scalars(select(RequirementRow.id).where(RequirementRow.run_id == run.id,
                                                                           RequirementRow.status == "OPEN"))
                if i not in frozen]
    if open_ids:
        open_set = set(open_ids)
        for po in session.scalars(select(PurchaseOrderRow).where(PurchaseOrderRow.run_id == run.id,
                                                                 PurchaseOrderRow.status == "PROPOSED")):
            if all(ln.requirement_id in open_set for ln in po.lines):
                session.delete(po)
            else:  # keep lines of approved requirements; drop only the ones being re-decided
                po.lines = [ln for ln in po.lines if ln.requirement_id not in open_set]
        session.flush()
        session.execute(delete(RequirementRow).where(RequirementRow.id.in_(open_ids)))
        session.flush()
    run_service.persist_result(session, run, result)
    run.summary = {**result.summary, "refresh": k}
    run.output_csv = decisions_csv(result.rows)
    run.input_text = "\n".join(",".join(r.values()) for r in rows)
    audit.record(session, actor, "run.refresh_live", "run", run.id, None, {"refresh": k, "open_lines": len(rows)})
    return run


def preview_for(result: RunResult, pr_no: str, line: int) -> dict[str, Any] | None:
    req = result.requirement_for_line(pr_no, line)
    if req is None:
        for r in result.rejected:
            if r.pr_no == pr_no and str(r.pr_line) == str(line):
                return {"not_processed": r.reason}
        return None
    d = result.decisions[req.id]
    others = [f"{rl.line.pr_no}/{rl.line.pr_line}" for rl in req.lines if rl.line.pr_no != pr_no]
    return {
        "group": req.id, "route": d.route, "decision": d.decision, "value": str(d.value.quantize(Decimal("0.01"))),
        "supplier_id": d.supplier_id, "unit_price": str(d.unit_price) if d.unit_price is not None else None,
        "suggested": list(d.suggested), "clause": d.clause, "rule": d.rule_id, "policy_version": d.policy_version,
        "joins": others, "flags": list(d.flags), "reason": d.reason,
    }
