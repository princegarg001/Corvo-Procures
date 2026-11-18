"""The decision pipeline (PLAN §5.1): PR rows + master data + policy versions → decisions.

parse/validate (D1, D2, D23) → match items (1.1/1.2) → club (2.1-2.3) → for each
requirement in requirement-date order (4.2): resolve the policy version (§8), assess
contracts (4.1-4.3), value (3.1), evaluate the rule ladder (§5), realise supplier,
price and suggestions (§6), consume contract ceiling → consolidate POs (§7) →
explain (8.1). Pure: no I/O; same inputs → identical outputs, whatever the row order.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .clubbing import club
from .conditions import leaf_operand, leaf_results
from .consolidation import PORequest, consolidate
from .contracts import ContractAssessment, Ledger, assess
from .explain import build_reason
from .facts import Ctx, FactReader
from .intake import parse_rows, validate_line
from .masterdata import MasterData
from .matching import ItemMatcher
from .models import (
    DECISION_PO,
    NEW_ITEM,
    NOT_PROCESSED,
    Decision,
    MatchResult,
    OutputRow,
    PurchaseOrder,
    RejectedLine,
    Requirement,
    ResolvedLine,
)
from .money import ZERO, fmt2
from .policy_schema import Policy
from .rules import decide, jsonable
from .suppliers import SupplierBook
from .valuation import Valuation, value_new_item, value_requirement
from .versions import PolicyResolver


class InvariantViolation(AssertionError):
    """A hard rule (e.g. AGENTS.md rule 6) would be broken; never silently emitted."""


@dataclass
class RunResult:
    rows: list[OutputRow]
    requirements: list[Requirement]
    decisions: dict[str, Decision]
    pos: list[PurchaseOrder]
    rejected: list[RejectedLine]
    matches: dict[int, MatchResult]
    versions_used: list[str]
    ledger: dict[str, Decimal]
    summary: dict[str, Any] = field(default_factory=dict)

    def decision_for_line(self, pr_no: str, pr_line: int | str) -> Decision | None:
        for req in self.requirements:
            for rl in req.lines:
                if rl.line.pr_no == pr_no and str(rl.line.pr_line) == str(pr_line):
                    return self.decisions[req.id]
        return None

    def requirement_for_line(self, pr_no: str, pr_line: int | str) -> Requirement | None:
        for req in self.requirements:
            for rl in req.lines:
                if rl.line.pr_no == pr_no and str(rl.line.pr_line) == str(pr_line):
                    return req
        return None


class Engine:
    """Holds per-version caches (matchers, supplier books) for one master-data snapshot."""

    def __init__(self, master: MasterData, resolver: PolicyResolver):
        self.master = master
        self.resolver = resolver
        self._matchers: dict[str, ItemMatcher] = {}
        self._books: dict[str, SupplierBook] = {}

    def matcher(self, policy: Policy) -> ItemMatcher:
        if policy.version not in self._matchers:
            self._matchers[policy.version] = ItemMatcher(self.master.items, policy.matching)
        return self._matchers[policy.version]

    def book(self, policy: Policy) -> SupplierBook:
        if policy.version not in self._books:
            self._books[policy.version] = SupplierBook(policy, self.master)
        return self._books[policy.version]

    # ------------------------------------------------------------------------------- run
    def run(self, rows: Sequence[Mapping[str, str | None]], *, ledger_baseline: dict[str, Decimal] | None = None,
            req_prefix: str = "REQ-", po_prefix: str = "PO-") -> RunResult:
        lines, rejected = parse_rows(rows)
        matches: dict[int, MatchResult] = {}
        valid: list[ResolvedLine] = []
        for line in lines:
            policy = self.resolver.for_date(line.created_at.date())
            m = self.matcher(policy).resolve(line, policy.review_flags.description_mismatch_below)
            matches[line.row_index] = m
            reason = validate_line(line, self.master.plants)
            if reason:
                rejected.append(RejectedLine(line.row_index, line.pr_no, str(line.pr_line), reason, {}))
            else:
                valid.append(ResolvedLine(line, m))

        groups = club(valid, self.resolver.for_date, self.master)
        requirements: list[Requirement] = []
        group_flags: dict[str, list[str]] = {}
        for i, g in enumerate(groups, start=1):
            rid = f"{req_prefix}{i:04d}"
            requirements.append(Requirement(rid, g.first.item_code, g.first.line.plant, g.lines, g.club_version))
            group_flags[rid] = g.flags

        ledger = Ledger(self.master, ledger_baseline)
        decisions: dict[str, Decision] = {}
        for req in sorted(requirements, key=lambda r: r.sort_key):
            decisions[req.id] = self._decide(req, ledger, group_flags.get(req.id, []))

        po_requests = [
            PORequest(req.id, req.created_at, req.sort_key, d.supplier_id or "", req.plant, d.route)
            for req in requirements
            if (d := decisions[req.id]).decision == DECISION_PO
        ]
        pos = consolidate(po_requests, self.resolver.for_date, id_prefix=po_prefix)
        for po in pos:
            for rid in po.requirement_ids:
                decisions[rid].po_id = po.id
                decisions[rid].trace["po_id"] = po.id

        self._check_invariants(requirements, decisions)
        rows_out = self._rows(rows, requirements, decisions, rejected, matches)
        versions = sorted({d.policy_version for d in decisions.values()})
        result = RunResult(rows_out, requirements, decisions, pos, sorted(rejected, key=lambda r: r.row_index),
                           matches, versions, ledger.snapshot())
        result.summary = summarise(result)
        return result

    # ------------------------------------------------------------------------- per requirement
    def _decide(self, req: Requirement, ledger: Ledger, extra_flags: list[str]) -> Decision:
        policy = self.resolver.for_date(req.req_date)
        book = self.book(policy)
        prlines = [rl.line for rl in req.lines]
        if req.item_code == NEW_ITEM:
            assessment = ContractAssessment((), ())
            vals = [value_new_item(ln.quantity, ln.est_unit_price) for ln in prlines]
            total = sum((v.value for v in vals), ZERO)
            qty = req.quantity
            unit = total / qty if qty else ZERO
            flags = tuple(sorted({f for v in vals for f in v.flags}))
            valuation = Valuation(qty, unit, total, "requester_estimate", "", None, flags)
        else:
            tol = policy.param(policy.contracts.tolerance_param)
            assessment = assess(req.item_code, req.quantity, req.req_date, req.plant, self.master, ledger,
                                book.eligibility, tol)
            valuation = value_requirement(policy, self.master, req.item_code, req.quantity, req.req_date, assessment)

        ctx = Ctx(policy=policy, master=self.master, item_code=req.item_code, lines=prlines, requirement=req,
                  assessment=assessment, valuation=valuation, book=book)
        result = decide(policy, ctx, book)
        realised = result.realised
        if realised.contract is not None:
            ledger.consume(realised.contract.contract_id, req.quantity * realised.contract.rate, req.id)

        flags = self._flags(req, policy, valuation, realised.flags, extra_flags)
        leafs: list[tuple[str, str, Any, Any, str | None]] = []
        if result.rule is not None:
            reader = FactReader(ctx)
            for leaf, value, _ok in leaf_results(result.rule.when, reader, policy):
                leafs.append((leaf.fact, leaf.op, value, leaf_operand(leaf, policy), leaf.param))
        suggested = [s.supplier_id for s in realised.suggestions]
        reason = build_reason(
            policy=policy, result=result, valuation=valuation, assessment=assessment, leafs=leafs,
            suggestions=suggested, suggestion_sources=[s.source for s in realised.suggestions],
        )
        trace = self._trace(req, policy, book, valuation, assessment, result, flags)
        return Decision(
            requirement_id=req.id, policy_version=policy.version, decision=result.decision, route=result.route,
            rule_id=result.rule.id if result.rule else None, clause=result.rule.clause if result.rule else None,
            supplier_id=realised.supplier_id, unit_price=realised.unit_price, value=valuation.value,
            value_unit_price=valuation.unit_price, suggested=tuple(suggested), flags=flags, reason=reason,
            trace=trace, contract_id=realised.contract.contract_id if realised.contract else None,
        )

    def _flags(self, req: Requirement, policy: Policy, valuation: Valuation, outcome_flags: list[str],
               extra: list[str]) -> tuple[str, ...]:
        flags: list[str] = []
        for rl in req.lines:
            flags.extend(rl.match.flags)
            if rl.line.need_by < rl.line.created_at.date():
                flags.append("NEED_BY_IN_PAST")
            item = self.master.items.get(rl.item_code)
            if item is not None and rl.line.uom and rl.line.uom.upper() != item.uom.upper():
                flags.append("UOM_MISMATCH")
        flags.extend(valuation.flags)
        flags.extend(outcome_flags)
        flags.extend(extra)
        if len(req.lines) > 1:
            flags.append("CLUBBED")
        return tuple(sorted(set(flags)))

    def _trace(self, req: Requirement, policy: Policy, book: SupplierBook, valuation: Valuation,
               assessment: ContractAssessment, result: Any, flags: tuple[str, ...]) -> dict[str, Any]:
        realised = result.realised
        preferred = book.preferred(req.item_code, req.req_date) if req.item_code != NEW_ITEM else []
        return {
            "requirement_id": req.id,
            "policy_version": policy.version,
            "club_policy_version": req.club_policy_version,
            "item_code": req.item_code,
            "plant": req.plant,
            "requirement_date": req.req_date.isoformat(),
            "lines": [
                {
                    "pr_no": rl.line.pr_no, "pr_line": rl.line.pr_line,
                    "created_at": rl.line.created_at.isoformat(timespec="minutes"),
                    "qty": jsonable(rl.line.quantity), "uom": rl.line.uom, "need_by": rl.line.need_by.isoformat(),
                    "urgency": rl.line.urgency, "description": rl.line.description,
                    "requester": rl.line.requester, "department": rl.line.department,
                    "match": {"method": rl.match.method, "score": jsonable(rl.match.score.quantize(Decimal("0.001"))),
                              "candidates": [[c, jsonable(s.quantize(Decimal("0.001")))] for c, s in rl.match.candidates]},
                }
                for rl in req.lines
            ],
            "value": valuation.to_trace(),
            "contracts": {
                "applicable": [o.to_trace() for o in assessment.applicable],
                "excluded": [{"id": cid, "why": why} for cid, why in assessment.excluded],
                "chosen": assessment.chosen.contract_id if assessment.chosen else None,
            },
            "ladder": [s.to_trace() for s in result.steps],
            "outcome": {
                "decision": result.decision, "route": result.route,
                "rule": result.rule.id if result.rule else None,
                "clause": result.rule.clause if result.rule else None,
                "supplier": realised.supplier_id,
                "unit_price": jsonable(realised.unit_price) if realised.unit_price is not None else None,
                "price_source": realised.price_source, "price_ref": realised.price_ref,
                "contract": realised.contract.contract_id if realised.contract else None,
                "suggested": [{"supplier": s.supplier_id, "source": s.source, "why": s.why} for s in realised.suggestions],
            },
            "preferred": [
                {
                    "rank": r.rank, "supplier": r.supplier_id, "score": jsonable(r.score.quantize(Decimal("0.000001"))),
                    "components": {k: jsonable(v.quantize(Decimal("0.000001"))) for k, v in r.components.items()},
                    "po_count": r.po_count,
                    "last_po_date": r.last_po_date.isoformat() if r.last_po_date else None,
                    "contracts": list(r.contract_ids),
                    "reference_price": jsonable(r.reference_price) if r.reference_price is not None else None,
                    "reference_ref": r.reference_ref,
                    "explanation": r.explanation(int(r.raw["max_po_count"])),
                }
                for r in preferred
            ],
            "flags": list(flags),
        }

    # ------------------------------------------------------------------------- checks & output
    def _check_invariants(self, requirements: list[Requirement], decisions: dict[str, Decision]) -> None:
        for req in requirements:
            d = decisions[req.id]
            book = self.book(self.resolver.for_date(req.req_date))
            for sid in [d.supplier_id, *d.suggested]:
                if sid and not book.eligibility.eligible(sid, req.req_date):
                    raise InvariantViolation(f"{req.id}: non-eligible supplier {sid} in outcome")
            if d.decision == DECISION_PO and (not d.supplier_id or d.unit_price is None):
                raise InvariantViolation(f"{req.id}: PO without supplier or price")

    def _version_for_raw(self, raw: Mapping[str, str | None]) -> str:
        """Version in force on the line's creation date (latest version if the date is unreadable)."""
        from .intake import parse_datetime

        try:
            return self.resolver.for_date(parse_datetime(raw.get("created_at") or "").date()).version
        except ValueError:
            return self.resolver.latest.version

    def _rows(self, rows: Sequence[Mapping[str, str | None]], requirements: list[Requirement],
              decisions: dict[str, Decision], rejected: list[RejectedLine],
              matches: dict[int, MatchResult]) -> list[OutputRow]:
        by_row: dict[int, tuple[Requirement, Decision]] = {}
        for req in requirements:
            for rl in req.lines:
                by_row[rl.line.row_index] = (req, decisions[req.id])
        rej = {r.row_index: r for r in rejected}
        out: list[OutputRow] = []
        for idx, raw in enumerate(rows):
            pr_no = (raw.get("pr_no") or "").strip()
            pr_line = (raw.get("pr_line") or "").strip()
            if idx in rej:
                m = matches.get(idx)
                code = m.item_code if m else (raw.get("item_code") or "").strip()
                version = self._version_for_raw(raw)
                out.append(OutputRow(idx, pr_no, pr_line, code, "", "", "", NOT_PROCESSED, "", "", "", "", version,
                                     f"Policy v{version}: not processed - {rej[idx].reason}"))
                continue
            req, d = by_row[idx]
            is_po = d.decision == DECISION_PO
            out.append(OutputRow(
                row_index=idx, pr_no=pr_no, pr_line=pr_line, resolved_item_code=req.item_code,
                group_id=req.id, po_id=d.po_id or "", decision=d.decision, route=d.route,
                supplier_id=(d.supplier_id or "") if is_po else "",
                unit_price=fmt2(d.unit_price) if is_po else "",
                group_value_inr=fmt2(d.value), suggested_supplier_ids=";".join(d.suggested),
                policy_version=d.policy_version, reason=d.reason,
            ))
        return out


def summarise(result: RunResult) -> dict[str, Any]:
    routes = Counter(d.route for d in result.decisions.values())
    routes_lines = Counter(r.route for r in result.rows)
    flags = Counter(f for d in result.decisions.values() for f in d.flags)
    return {
        "input_rows": len(result.rows),
        "requirements": len(result.requirements),
        "purchase_orders": len(result.pos),
        "not_processed": len(result.rejected),
        "routes_by_requirement": dict(sorted(routes.items())),
        "routes_by_line": dict(sorted(routes_lines.items())),
        "flags": dict(sorted(flags.items())),
        "total_value": fmt2(sum((d.value for d in result.decisions.values()), ZERO)),
        "policy_versions_used": result.versions_used,
    }


def run_batch(rows: Sequence[Mapping[str, str | None]], master: MasterData, resolver: PolicyResolver,
              **kwargs: Any) -> RunResult:
    return Engine(master, resolver).run(rows, **kwargs)
