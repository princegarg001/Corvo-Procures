"""Amendment text / document → validated ops (PLAN §8).

LLM (temperature 0, JSON) with the current policy, fact registry, op vocabulary and master
lists as context → {effective_from, ops[], questions[]}, each op quoting its source sentence →
validate by applying to a copy → one repair round with the validator's messages → the same
review pipeline as the structured editor (plain-language diff, lint, impact preview).
No key or provider failure → deterministic pattern reader, clearly labelled.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from procure_engine.facts import registry_listing
from procure_engine.masterdata import MasterData
from procure_engine.policy_ops import apply_ops
from procure_engine.policy_schema import Policy, PolicyError

from ..config import today
from ..services import amendment_service, masterdata_service, policy_service
from . import gateway, heuristics
from .extract import ExtractError, extract_text

PROMPT = (Path(__file__).parent / "prompts" / "amendment.md").read_text(encoding="utf-8")


def _context(md: MasterData, base: Policy) -> str:
    ctx = {
        "today": today().isoformat(),
        "current_policy": base.to_json_dict(),
        "fact_registry": [{k: f[k] for k in ("name", "type", "description", "ops")} for f in registry_listing()],
        "plants": [{"code": p.code, "name": p.name} for p in md.plants.values()],
        "item_categories": sorted({i.category for i in md.items.values()}),
        "item_types": sorted({i.item_type for i in md.items.values()}),
        "items": [f"{i.code} {i.description}" for i in md.items.values()],
        "suppliers": [f"{s.id} {s.name} ({s.status}; {', '.join(s.categories)})" for s in md.suppliers.values()],
    }
    return json.dumps(ctx, ensure_ascii=False, default=str)


def _normalise(data: dict[str, Any]) -> tuple[str, date | None, list[dict[str, Any]], list[str]]:
    ops = [o for o in (data.get("ops") or []) if isinstance(o, dict)]
    eff: date | None = None
    raw_eff = data.get("effective_from")
    for o in list(ops):
        if o.get("op") == "set_effective_from":
            raw_eff = raw_eff or o.get("date")
            ops.remove(o)
    if raw_eff:
        try:
            eff = date.fromisoformat(str(raw_eff)[:10])
        except ValueError:
            eff = None
    questions = [str(q) for q in (data.get("questions") or []) if q]
    return str(data.get("title") or ""), eff, ops, questions


def _errors(base: Policy, ops: list[dict[str, Any]], eff: date | None) -> list[str]:
    try:
        full = list(ops) + ([{"op": "set_effective_from", "date": eff.isoformat()}] if eff else [])
        apply_ops(base, full, new_version="0.0")
    except PolicyError as exc:
        return exc.messages
    return []


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("’", "'").replace("“", '"').replace("”", '"')).strip().lower()


def _quote_warnings(text: str, ops: list[dict[str, Any]]) -> list[str]:
    body = _squash(text)
    out = []
    for i, op in enumerate(ops):
        q = _squash(str(op.get("source_quote") or ""))
        if not q:
            out.append(f"op {i + 1} ({op.get('op')}) has no source quote")
        elif q not in body:
            out.append(f"op {i + 1} ({op.get('op')}): quote not found verbatim in the amendment")
    return out


def llm_read(text: str, base: Policy, md: MasterData) -> dict[str, Any]:
    user = f"CONTEXT:\n{_context(md, base)}\n\nAMENDMENT TEXT:\n<<<\n{text}\n>>>"
    first = gateway.complete_json(PROMPT, user, purpose="amendment")
    title, eff, ops, questions = _normalise(first.data)
    errors = _errors(base, ops, eff)
    meta: dict[str, Any] = {"provider": first.provider, "model": first.model, "latency_ms": first.latency_ms,
                            "fallback_used": first.fallback_used, "attempts": first.attempts, "repaired": False}
    if errors:
        repair_user = (f"{user}\n\nYOUR PREVIOUS OUTPUT:\n{json.dumps(first.data, ensure_ascii=False)}\n\n"
                       f"THE VALIDATOR REJECTED IT:\n- " + "\n- ".join(errors) +
                       "\n\nReturn the corrected JSON object (same format). Fix only what the validator reports.")
        try:
            second = gateway.complete_json(PROMPT, repair_user, purpose="amendment-repair")
            t2, e2, o2, q2 = _normalise(second.data)
            errors2 = _errors(base, o2, e2)
            if len(errors2) <= len(errors):
                title, eff, ops, questions, errors = t2 or title, e2 or eff, o2, q2, errors2
                meta.update(repaired=True, repair_provider=second.provider, repair_latency_ms=second.latency_ms)
        except gateway.LLMUnavailable as exc:
            meta["repair_error"] = str(exc)
    meta["validator_errors_after_repair"] = errors
    meta["quote_warnings"] = _quote_warnings(text, ops)
    return {"title": title, "effective_from": eff, "ops": ops, "questions": questions, "meta": meta}


def read(session: Session, text: str, *, actor: str, source_kind: str, title: str = "",
         effective_from: date | None = None, source_file: bytes | None = None,
         filename: str | None = None) -> dict[str, Any]:
    if not text.strip():
        raise HTTPException(422, "the amendment text is empty")
    base = policy_service.to_policy(policy_service.latest_row(session))
    md = masterdata_service.load_master(session)
    result: dict[str, Any] | None = None
    llm_error = ""
    if gateway.providers():
        try:
            result = llm_read(text, base, md)
        except gateway.LLMUnavailable as exc:
            llm_error = str(exc)
    if result is None:
        h = heuristics.read(text, base, md, today())
        eff = date.fromisoformat(h["effective_from"]) if h["effective_from"] else None
        result = {"title": h["title"], "effective_from": eff, "ops": h["ops"], "questions": h["questions"],
                  "meta": {"provider": "deterministic", "note": "read without AI (pattern matching)",
                           "llm_error": llm_error or "no LLM provider configured",
                           "quote_warnings": _quote_warnings(text, h["ops"])}}
    eff = effective_from or result["effective_from"]
    questions = list(result["questions"])
    if eff is None:
        eff = today()
        questions.append(f"No effective date was stated; it defaults to today ({eff.isoformat()}). "
                         "Change it if the amendment should apply to earlier requirements.")
    row = amendment_service.create(
        session, ops=result["ops"], actor=actor, source_kind=source_kind,
        title=title or result["title"] or "Policy amendment", source_text=text, source_file=source_file,
        source_filename=filename, effective_from=eff, questions=questions, ai_meta=result["meta"],
    )
    return amendment_service.view(session, row)


def from_text(session: Session, text: str, *, actor: str, source_kind: str = "CHAT", title: str = "",
              effective_from: date | None = None) -> dict[str, Any]:
    return read(session, text, actor=actor, source_kind=source_kind, title=title, effective_from=effective_from)


def from_document(session: Session, data: bytes, filename: str, *, actor: str, title: str = "",
                  effective_from: date | None = None) -> dict[str, Any]:
    try:
        text = extract_text(data, filename)
    except ExtractError as exc:
        raise HTTPException(422, str(exc)) from exc
    return read(session, text, actor=actor, source_kind="DOC", title=title, effective_from=effective_from,
                source_file=data, filename=filename)
