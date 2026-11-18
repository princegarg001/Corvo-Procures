"""Batch runs: DB snapshot → engine → persisted run (requirements, decisions with trace,
proposed POs), CSV export, and run comparison (PLAN §7, §10 'Run comparison').

Batch runs are stateless with respect to contract ceilings: they start from the
register baseline (decision D14), so Run 1 and Run 2 differ only because of the policy.
"""

from __future__ import annotations

import csv
import hashlib
import io
import time
from collections import Counter
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from procure_engine.export import DECISION_COLUMNS, decisions_csv
from procure_engine.intake import BatchFormatError, check_columns
from procure_engine.pipeline import Engine, RunResult
from procure_engine.versions import PolicyResolver

from ..repo.models import (
    DecisionRow,
    POLineRow,
    PurchaseOrderRow,
    RequirementLineRow,
    RequirementRow,
    RunRow,
)
from . import audit, masterdata_service, policy_service

MAX_ROWS = 20000


class BatchError(ValueError):
    pass


def parse_csv_text(text: str) -> list[dict[str, str]]:
    text = text.lstrip("﻿")
    if not text.strip():
        raise BatchError("the file is empty")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise BatchError("no header row")
    try:
        check_columns([f.strip() for f in reader.fieldnames])
    except BatchFormatError as exc:
        raise BatchError(str(exc)) from exc
    rows = [{(k or "").strip(): (v or "") for k, v in r.items()} for r in reader]
    if len(rows) > MAX_ROWS:
        raise BatchError(f"too many rows ({len(rows)} > {MAX_ROWS})")
    return rows


def execute(session: Session, rows: list[dict[str, str]], *, pin: str | None = None,
            resolver: PolicyResolver | None = None) -> RunResult:
    master = masterdata_service.load_master(session)
    res = resolver or policy_service.resolver(session, pin=pin)
    return Engine(master, res).run(rows)


def process_batch(session: Session, text: str, *, name: str, filename: str | None, pin: str | None,
                  actor: str, kind: str = "BATCH") -> tuple[RunRow, RunResult]:
    rows = parse_csv_text(text)
    started = time.perf_counter()
    result = execute(session, rows, pin=pin)
    elapsed = int((time.perf_counter() - started) * 1000)
    run = RunRow(
        name=name or (filename or "Batch"), kind=kind, input_file=filename,
        input_hash=hashlib.sha256(text.encode()).hexdigest(), input_text=text,
        output_csv=decisions_csv(result.rows), policy_pin=pin, created_by=actor,
        summary=result.summary, duration_ms=elapsed,
    )
    session.add(run)
    session.flush()
    persist_result(session, run, result)
    audit.record(session, actor, "run.create", "run", run.id, None,
                 {"name": run.name, "kind": kind, "rows": len(rows), "pin": pin, "summary": result.summary})
    return run, result


def persist_result(session: Session, run: RunRow, result: RunResult) -> None:
    version_rows = policy_service.all_versions(session)
    version_ids = {r.version: r.id for r in version_rows}
    urgencies = {r.version: set(policy_service.to_policy(r).requirement.emergency_urgencies) for r in version_rows}
    req_rows: dict[str, RequirementRow] = {}
    for req in result.requirements:
        d = result.decisions[req.id]
        row = RequirementRow(
            run_id=run.id, group_code=req.id, item_code=req.item_code, plant=req.plant, req_date=req.req_date,
            created_at=req.created_at, emergency=any(rl.line.urgency in urgencies[d.policy_version] for rl in req.lines),
            value=d.value, policy_version=d.policy_version, policy_version_id=version_ids.get(d.policy_version),
            status="OPEN",
        )
        for pos, rl in enumerate(req.lines):
            ln = rl.line
            row.lines.append(RequirementLineRow(
                pr_no=ln.pr_no, line=ln.pr_line, position=pos, row_index=ln.row_index,
                snapshot={
                    "created_at": ln.created_at.isoformat(timespec="minutes"), "requester": ln.requester,
                    "department": ln.department, "plant": ln.plant, "item_code": ln.item_code,
                    "description": ln.description, "qty": str(ln.quantity), "uom": ln.uom,
                    "est_unit_price": str(ln.est_unit_price) if ln.est_unit_price is not None else None,
                    "need_by": ln.need_by.isoformat(), "urgency": ln.urgency,
                    "resolved_item_code": rl.item_code, "match_method": rl.match.method,
                    "match_score": str(rl.match.score), "flags": list(rl.match.flags),
                },
            ))
        session.add(row)
        req_rows[req.id] = row
    session.flush()
    for req in result.requirements:
        d = result.decisions[req.id]
        session.add(DecisionRow(
            requirement_id=req_rows[req.id].id, decision=d.decision, route=d.route, supplier_id=d.supplier_id,
            unit_price=d.unit_price, value=d.value, suggested=list(d.suggested), rule_id=d.rule_id, clause=d.clause,
            contract_id=d.contract_id, po_code=d.po_id, flags=list(d.flags), trace=d.trace, reason=d.reason,
            status="PROPOSED", created_by="engine",
        ))
    for po in result.pos:
        por = PurchaseOrderRow(po_code=po.id, run_id=run.id, supplier_id=po.supplier_id, plant=po.plant, route=po.route,
                               policy_version=po.policy_version, status="PROPOSED", created_by="engine")
        for rid in po.requirement_ids:
            d = result.decisions[rid]
            req = next(r for r in result.requirements if r.id == rid)
            qty = req.quantity
            price = d.unit_price or Decimal(0)
            por.lines.append(POLineRow(requirement_id=req_rows[rid].id, item_code=req.item_code, qty=qty,
                                       unit_price=price, amount=qty * price))
        session.add(por)
    session.flush()


def get_run(session: Session, run_id: int) -> RunRow:
    run = session.get(RunRow, run_id)
    if run is None:
        raise policy_service.NotFound(f"run {run_id} not found")
    return run


def latest_batch_run(session: Session) -> RunRow | None:
    return session.scalar(select(RunRow).where(RunRow.kind == "BATCH").order_by(RunRow.id.desc()).limit(1))


def run_view(run: RunRow) -> dict[str, Any]:
    return {
        "id": run.id, "name": run.name, "kind": run.kind, "input_file": run.input_file, "input_hash": run.input_hash,
        "policy_pin": run.policy_pin, "created_by": run.created_by,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "summary": run.summary, "duration_ms": run.duration_ms,
    }


def list_runs(session: Session) -> list[dict[str, Any]]:
    counts = dict(session.execute(
        select(RequirementRow.run_id, func.count()).where(RequirementRow.status == "APPROVED").group_by(RequirementRow.run_id)
    ).all())
    out = []
    for r in session.scalars(select(RunRow).where(RunRow.kind != "IMPACT").order_by(RunRow.id.desc())):
        v = run_view(r)
        v["approved_requirements"] = counts.get(r.id, 0)
        out.append(v)
    return out


def rows_of(run: RunRow) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(run.output_csv)))


def result_json(run: RunRow) -> dict[str, Any]:
    return {**run_view(run), "columns": list(DECISION_COLUMNS), "decisions": rows_of(run)}


# ----------------------------------------------------------------------------------- comparison

COMPARE_FIELDS = ("resolved_item_code", "group_id", "po_id", "decision", "route", "supplier_id", "unit_price",
                  "group_value_inr", "suggested_supplier_ids", "policy_version")


def compare_rows(a: list[dict[str, str]], b: list[dict[str, str]]) -> dict[str, Any]:
    ka = {(r["pr_no"], r["pr_line"]): r for r in a}
    kb = {(r["pr_no"], r["pr_line"]): r for r in b}
    changed = []
    for key in ka:
        if key not in kb:
            continue
        ra, rb = ka[key], kb[key]
        diffs = {f: [ra[f], rb[f]] for f in COMPARE_FIELDS if ra.get(f) != rb.get(f) and f not in ("group_id", "po_id")}
        if diffs:
            changed.append({"pr_no": key[0], "pr_line": key[1], "changes": diffs,
                            "old_reason": ra["reason"], "new_reason": rb["reason"],
                            "old_route": ra["route"], "new_route": rb["route"]})
    route_moves = Counter(f"{c['old_route']} → {c['new_route']}" for c in changed if c["old_route"] != c["new_route"])
    only_a = sorted(set(ka) - set(kb))
    only_b = sorted(set(kb) - set(ka))
    grouping_changed = _grouping_changes(a, b)
    return {
        "changed": changed,
        "summary": {
            "lines_compared": len(set(ka) & set(kb)), "lines_changed": len(changed),
            "route_moves": dict(sorted(route_moves.items())),
            "only_in_a": len(only_a), "only_in_b": len(only_b),
            "grouping_changes": len(grouping_changed),
        },
        "grouping_changes": grouping_changed,
    }


def _grouping_changes(a: list[dict[str, str]], b: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Lines whose requirement or PO co-members differ (IDs themselves are namespaces)."""
    def members(rows: list[dict[str, str]], col: str) -> dict[tuple[str, str], frozenset[tuple[str, str]]]:
        groups: dict[str, set[tuple[str, str]]] = {}
        for r in rows:
            if r[col]:
                groups.setdefault(r[col], set()).add((r["pr_no"], r["pr_line"]))
        return {k: frozenset(g) for g in groups.values() for k in g}
    out = []
    for col in ("group_id", "po_id"):
        ma, mb = members(a, col), members(b, col)
        for key in sorted(set(ma) | set(mb)):
            if ma.get(key, frozenset()) != mb.get(key, frozenset()):
                out.append({"pr_no": key[0], "pr_line": key[1], "kind": "requirement" if col == "group_id" else "po",
                            "old": sorted(f"{p}/{n}" for p, n in ma.get(key, frozenset())),
                            "new": sorted(f"{p}/{n}" for p, n in mb.get(key, frozenset()))})
    return out


def compare_runs(session: Session, a_id: int, b_id: int) -> dict[str, Any]:
    a, b = get_run(session, a_id), get_run(session, b_id)
    out = compare_rows(rows_of(a), rows_of(b))
    out["a"], out["b"] = run_view(a), run_view(b)
    return out


def compare_csv(diff: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["pr_no", "pr_line", "field", "run_a", "run_b", "new_reason"])
    for c in diff["changed"]:
        for f, (old, new) in c["changes"].items():
            w.writerow([c["pr_no"], c["pr_line"], f, old, new, c["new_reason"]])
    return buf.getvalue()


def requirements_for_run(session: Session, run_id: int) -> list[RequirementRow]:
    return list(session.scalars(
        select(RequirementRow).where(RequirementRow.run_id == run_id).options(selectinload(RequirementRow.lines))
        .order_by(RequirementRow.group_code)))
