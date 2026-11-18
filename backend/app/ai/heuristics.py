"""Deterministic amendment reader used when no LLM is configured or every provider fails.

Conservative by design: it proposes only ops it can tie to one exact sentence — a number
change on a named limit / window / tolerance, an effective date, a supplier block (with its
own date), a suggestion count, ranking weights, routes excluded from consolidation. A change
scoped to part of the business (one plant, a category, "only") needs a new rule, so it is
returned as a question for the structured editor instead of being guessed.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from procure_engine.masterdata import MasterData
from procure_engine.money import to_decimal
from procure_engine.policy_schema import Policy

WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
GENERIC = {"po", "limit", "window", "the", "of", "and", "for", "a", "list", "lookback", "boundary", "threshold", "inr"}

MONEY = re.compile(
    r"(?:₹|\brs\.?|\binr)\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|l\b|crores?|cr\b|k\b)?"
    r"|\b(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr\b)",
    re.IGNORECASE,
)
DAYS = re.compile(r"(\d+)\s*(?:calendar\s+|working\s+)?days?\b", re.IGNORECASE)
HOURS = re.compile(r"(\d+)\s*hours?\b", re.IGNORECASE)
PCT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|per\s*cent|percent)", re.IGNORECASE)
EFFECTIVE = re.compile(
    r"(?:effective|with effect|takes? effect|in force|comes? into force)\s*(?:from|on|date|as of)?\s*[:\-]?\s*([^;\n]+)"
    r"|^\s*(?:from|starting|beginning)\s+([^;\n]+)",
    re.IGNORECASE,
)
DATE_TEXT = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?[A-Za-z]{3,9}\.?,?\s+\d{4}\b"
    r"|\b[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?[A-Za-z]{3,9}\b"
    r"|\b(?:today|tomorrow|next\s+\w+)\b",
    re.IGNORECASE,
)
WEIGHT_WORDS = [("frequency", r"frequency"), ("recency", r"recency"), ("contract", r"contract"),
                ("on_time", r"on[- ]?time(?:\s+delivery)?|delivery"), ("quality", r"quality")]
SCOPE = re.compile(r"\bonly\b|\bexcept\b|\bwhose\b|\bwhere\b|\bitems? (?:in|of|whose)\b|\bservices?\b|\bcapex\b",
                   re.IGNORECASE)
UNCHANGED = re.compile(r"\bunchanged\b|\bcontinues? to\b|\bremains?\b|\bas usual\b", re.IGNORECASE)


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z(\"'₹])|\n+", text)
    return [p.strip(" -•*\t") for p in parts if p and p.strip(" -•*\t")]


def money_values(s: str) -> list[Decimal]:
    out = []
    for m in MONEY.finditer(s):
        num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        value = to_decimal(num)
        u = (unit or "").lower()
        if u.startswith(("lakh", "lac")) or u == "l":
            value *= Decimal(100000)
        elif u.startswith(("crore", "cr")):
            value *= Decimal(10000000)
        elif u == "k":
            value *= Decimal(1000)
        out.append(value)
    return out


def parse_date(text: str, today: date) -> date | None:
    import dateparser

    cleaned = re.sub(r"\b(the|of)\b", " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", cleaned)
    parsed = dateparser.parse(cleaned.strip(), settings={
        "RELATIVE_BASE": datetime(today.year, today.month, today.day), "PREFER_DATES_FROM": "future",
        "DATE_ORDER": "DMY"})
    return parsed.date() if parsed else None


def find_date(text: str, today: date) -> date | None:
    """First date-like phrase in the text, resolved against today."""
    for m in DATE_TEXT.finditer(text):
        d = parse_date(m.group(0), today)
        if d is not None:
            return d
    return None


def _keywords(policy: Policy, name: str) -> set[str]:
    pd = policy.params[name]
    words = set(re.findall(r"[a-z0-9]+", (pd.label or name).lower())) | set(name.split("_"))
    return {w for w in words if w not in GENERIC and not w.isdigit() and len(w) > 1}


def best_param(policy: Policy, s: str, unit: str) -> str | None:
    tokens = set(re.findall(r"[a-z0-9]+", s.lower()))
    scored = []
    for name, pd in policy.params.items():
        if pd.unit != unit:
            continue
        kw = _keywords(policy, name) - {"days", "hours", "inr", "pct"}
        hits = len(kw & tokens)
        if pd.clause and re.search(rf"(?<![\d.]){re.escape(pd.clause)}(?![\d])", s):
            hits += 1
        if hits:
            scored.append((hits, -len(kw), name))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][2]


def read(text: str, policy: Policy, master: MasterData, today: date) -> dict[str, Any]:
    ops: list[dict[str, Any]] = []
    questions: list[str] = []
    effective: date | None = None
    plant_words = {p.code.lower() for p in master.plants.values()} | {
        w for p in master.plants.values() for w in re.findall(r"[a-z]+", p.name.lower()) if w not in ("plant", "pune")}
    for s in sentences(text):
        low = s.lower()
        m = EFFECTIVE.search(s)
        if m and effective is None:
            effective = find_date(m.group(1) or m.group(2) or "", today)
        if UNCHANGED.search(s):
            continue
        amounts = money_values(s)
        if "weight" in low:
            weights: dict[str, str] = {}
            for key, rx in WEIGHT_WORDS:
                wm = re.search(rf"(?:{rx})\D{{0,25}}?(\d+(?:\.\d+)?)\s*(%?)", low)
                if wm:
                    v = to_decimal(wm.group(1))
                    weights[key] = str(v / 100 if (wm.group(2) or v > 1) else v)
            if len(weights) >= 2:
                ops.append({"op": "set_ranking", "changes": {"weights": weights}, "source_quote": s})
                continue
        scoped = bool(SCOPE.search(s)) or any(re.search(rf"\b{re.escape(w)}\b", low) for w in plant_words)
        has_number = bool(amounts or DAYS.search(s) or HOURS.search(s) or PCT.search(s))
        if scoped and has_number:
            questions.append(f"'{s[:160]}' applies to part of the business only; it needs a new rule. "
                             "Enter it in the structured editor (or configure an AI provider).")
            continue
        if amounts:
            name = best_param(policy, s, "INR")
            if name and amounts[-1] != policy.params[name].value:
                ops.append({"op": "set_param", "name": name, "value": str(amounts[-1]), "source_quote": s})
        for unit, rx in (("days", DAYS), ("hours", HOURS), ("%", PCT)):
            if amounts and unit == "%":
                continue
            found = rx.findall(s)
            if found:
                name = best_param(policy, s, unit)
                if name and to_decimal(found[-1]) != policy.params[name].value:
                    ops.append({"op": "set_param", "name": name, "value": found[-1], "source_quote": s})
        sids = set(re.findall(r"\b([A-Z]\d{3})\b", s)) | {sid for sid, sup in master.suppliers.items() if sup.name.lower() in low}
        if re.search(r"block|suspend|blacklist|debar|inactive|quality hold|not to be used", low):
            for sid in sorted(sids):
                if sid not in master.suppliers:
                    continue
                op: dict[str, Any] = {"op": "set_supplier_override", "supplier_id": sid,
                                      "status": "Inactive" if "inactive" in low else "Blocked",
                                      "reason": s[:200], "source_quote": s}
                fm = re.search(r"\b(?:from|with effect from|effective)\s+(.+)", s, re.IGNORECASE)
                when = find_date(fm.group(1), today) if fm else None
                if when is not None:
                    op["effective_from"] = when.isoformat()
                ops.append(op)
        cnt = re.search(r"\b(\d+|" + "|".join(WORD_NUM) + r")\s+(?:\w+\s+)?suppliers?\b", low)
        if cnt and re.search(r"\bsuggest|\b(rfq|rfp|quotation|proposal|capex)\b", low):
            n = int(cnt.group(1)) if cnt.group(1).isdigit() else WORD_NUM[cnt.group(1)]
            for rule in policy.rules:
                route = rule.then.route.lower()
                label = policy.route_label(rule.then.route).lower()
                if rule.then.decision == "SOURCING_REQUEST" and (re.search(rf"\b{re.escape(route.split('_')[0])}\b", low)
                                                                 or label in low) and rule.then.suggest != n:
                    ops.append({"op": "modify_rule", "rule_id": rule.id, "changes": {"then": {"suggest": n}},
                                "source_quote": s})
                    break
        if re.search(r"not\s+(?:be\s+)?(?:consolidated|combined)", low):
            routes = sorted({r.then.route for r in policy.rules if r.then.decision == "PO"
                             and re.search(rf"\b{re.escape(r.then.route.split('_')[0].lower())}\b", low)})
            if routes:
                ops.append({"op": "set_consolidation", "changes": {"exclude_routes": routes}, "source_quote": s})
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for op in ops:
        key = repr(sorted((k, repr(v)) for k, v in op.items() if k not in ("source_quote", "reason")))
        if key not in seen:
            seen.add(key)
            unique.append(op)
    if effective is None:
        questions.append("No effective date was found in the text. From which date should the change apply?")
    if not unique and not questions:
        questions.append("No change could be read without AI. Use the structured editor to enter the change.")
    elif unique:
        questions.append("These changes were read without AI (pattern matching). Check every op against its quote.")
    first = sentences(text)
    return {"title": first[0][:120] if first else "Policy amendment",
            "effective_from": effective.isoformat() if effective else None, "ops": unique, "questions": questions}
