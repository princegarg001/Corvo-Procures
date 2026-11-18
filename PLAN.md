# PLAN.md — Corvo PR-to-PO: Policy-Driven Procurement App

> Cantill.ai Full-stack Intern, Round 1 · Build freeze **Thu 19 Nov 2026, 10:00 IST** · Blind test 10:00–12:00
> **Revision 1.1** (Tue 17 Nov 23:10): blind-test path first (hosted by Wed 15:00), ranking robustness check, interpretation stress test, demo seed, Run comparison screen. See §16.
> Goal: not "a working submission" but **the submission the reviewers remember**: highest blind-test accuracy, an amendment that applies cleanly through the app, and a codebase and DECISIONS.md that read like a senior engineer wrote them.

---

## Contents

0. [How we win (strategy)](#0-how-we-win)
1. [What the graders will actually measure](#1-score-map)
2. [Ground truth from data reconnaissance](#2-ground-truth)
3. [Architecture](#3-architecture)
4. [Policy-as-data: the DSL](#4-policy-dsl)
5. [Decision engine design](#5-engine)
6. [Data model](#6-data-model)
7. [API](#7-api)
8. [Policy amendment pipeline](#8-amendments)
9. [Chat intake](#9-chat)
10. [Buyer workspace & other screens](#10-ui)
11. [Contracts & PDF import](#11-contracts)
12. [Preferred supplier ranking](#12-ranking)
13. [Testing strategy](#13-testing)
14. [Production readiness](#14-prod)
15. [Repository layout](#15-repo)
16. [Build timeline (35 h)](#16-timeline)
17. [DECISIONS.md register](#17-decisions)
18. [Blind-test runbook](#18-runbook)
19. [Risk register](#19-risks)
20. [Definition of done](#20-dod)

---

<a id="0-how-we-win"></a>
## 0. How we win (strategy)

Everyone who applied will build "chat + table + LLM". The ones who score highest will do five things others won't:

| # | Principle | Why it wins |
|---|---|---|
| 1 | **Deterministic core, AI only at the edges.** The engine is a pure function: `(PR lines, policy versions, master data) → decisions`. LLMs only *translate* (chat → slots, amendment text → policy ops, PDF → contract fields), and a human confirms each one. | 40% of the score is automated accuracy. LLM-in-the-loop decisions are non-reproducible and will drift between Run 1 and Run 2. |
| 2 | **The policy is a real DSL, not a config file.** Ordered rules, typed conditions over a fact registry, named parameters, new routes, item sets, plant scopes, effective dating. | "Can a new kind of rule be added without code?" is explicitly scored. Most candidates will only externalise the numbers. |
| 3 | **Every decision explains itself with numbers.** A "rule ladder" shows each rule evaluated top-down (✗/✓) with the actual values, the clause, the policy version, and the contract or PO relied on. | UX (20%) plus record keeping (8.1). Buyers can act in seconds. |
| 4 | **Amendments show their impact before approval.** Plain-language diff plus a *decision-delta preview* ("these 11 requirements would change route"). | Policy-as-data (15%). Nobody else will simulate before approving. |
| 5 | **Rehearse the blind test.** 12 synthetic amendments as fixtures, a timed runbook, version-pinned re-runs, and a hosted app that survives redeploys. | The blind test is the exam. Preparation beats talent here. |

**Non-negotiables:** zero blocked or inactive suppliers in any PO or suggestion (penalised), output CSV exactly to spec, `POST /api/process-batch` works on the hosted URL, and the amendment is applied **through the app's own feature**.

---

<a id="1-score-map"></a>
## 1. What the graders will actually measure

| Weight | Area | What earns full marks | Where it is built |
|---|---|---|---|
| **40%** | Decisions (automated) | Route, clubbing, PO consolidation, item matching, values, supplier and price, suggestions, the amendment taking effect, preferred lists | §5, §12, §13, §18 |
| **20%** | Chat intake & UX | Right follow-ups, never inventing items, buyer can act on each decision fast, one obvious next action per screen | §9, §10 |
| **15%** | Policy as data | Captured (doc/chat), shown (plain-language diff), approved, versioned, dated; new rule types without code | §4, §8 |
| **15%** | DECISIONS.md & judgment | Notices the gaps, decides sensibly, ranking well reasoned | §12, §17 |
| **10%** | Engineering & delivery | Data model, API, engine/UI separation, tests, README, hosted demo | §3, §6, §7, §13, §14 |

**Round 2 hint:** "make a change live". The code must be small, obvious and modular. Every module is something we can explain in one sentence.

---

<a id="2-ground-truth"></a>
## 2. Ground truth from data reconnaissance

A prototype engine (built Mon night) **reproduces all 14 worked examples** (route, supplier, unit price, value, suggested suppliers, clubbing, consolidation) and **all 3 preferred-supplier tables**. Facts that shape the design:

### 2.1 Planted traps in the kit
| Trap | Where | Correct handling |
|---|---|---|
| PDF-only contracts | RC-2026-031 (from 15 Nov), RC-2026-033 (from 20 Nov) | Import via the app; consumed starts at 0. The laptop requirement's date is 16 Nov (first line), so RC-2026-033 does **not** apply: RFQ of about ₹7.1 L. |
| Contract with a Blocked supplier | RC-2026-005 / S004 | Not "applicable" (4.1), so it is also excluded from valuation's "lowest applicable rate". |
| Expired contract | RC-2025-020 ended 30 Sep | Not usable, but its supplier stays on the preferred list (6.1b). |
| Near-exhausted ceilings | RC-2026-002 (₹38k left), RC-2026-015 (₹12k left) | Ceiling is checked at the contract rate and consumed in requirement-date order across the run. |
| Two contracts, one item | ITM-1009 on RC-2026-013 and RC-2026-015 | Lowest rate **with enough ceiling** (4.3). |
| Values near thresholds | ₹1,97,514 · ₹1,97,743 · ₹2,01,446 · ₹2,03,000 | `Decimal` arithmetic, strict `<` vs `≤` per clause. |
| Window boundaries | Need-by gaps of exactly 8 d; created gaps of 14 and 15 d; PO gaps of 23.75 h, 24.33 h, 27.67 h | Inclusive bounds and calendar-day counting, documented. |
| Latest PO from a non-Active supplier | ITM-1014, 1017, 1020, 1049, 1050 | Valuation (3.1b) uses the latest PO regardless of supplier; the "bought from Active" test and the PO supplier use Active only. |
| Junk rows | PR-172 (qty 0), PR-173 (plant PUN2) | `NOT_PROCESSED` with reason. |
| Near-duplicates | PR-174/175: same requester, same item, 4 min apart | Clubbed per 2.1, flagged "possible duplicate" for the buyer. |
| Text noise | "- urgent", "as per sample", "(repeat)", "for maintenance", `brg`, `hyd`, `pneu`, "welding rod", `monitor 24"` | Normaliser and abbreviation map; the urgency **field** is authoritative and the word "urgent" is only a flag. |
| Same-day PO tie | ITM-1034, 2026-04-10 | Tie-break by higher PO number (matches example 11). |
| Category top-up order | Examples 10 and 12 | `on_time/100 + quality/5`, equal weight; tie → supplier_id ascending. Reproduces exactly. |
| Short suggestion pool | Example 11 RFP shows only 4 suppliers | Return fewer than requested, never pad with ineligible suppliers. |
| OEM-branded items | "(Vertex CNC)", "(Vertex)", "(Hydrax)" | **Strong hint of a future "proprietary/OEM" amendment.** The DSL supports item sets and new routes. |

### 2.2 The PO-number offset
Example PO numbers are consistently **one lower** than ours. Every difference traces to one requirement before 09:40 on 2 Nov: PR-174/175, which sit with the other trap rows at the end of the file. The most likely explanation is that the answer key was generated before the trap rows were appended. **PO IDs are our own namespace** (brief: "Your PO number"), so the grader almost certainly compares *co-membership*, not literal IDs. We don't chase the offset; we record it.

### 2.3 Sample batch profile (prototype output)
186 lines → 149 requirements → SPOT 58 · RFQ 39 · CONTRACT 30 · CAPEX 10 · EMERGENCY 6 · RFP 4 · NEW 2 · NOT_PROCESSED 2 · about 82 POs. This becomes the **snapshot regression test**.

---

<a id="3-architecture"></a>
## 3. Architecture

```
┌───────────────────────── Browser (React + TS) ─────────────────────────┐
│ Chat · Buyer Inbox · Requirement detail · Batches · Policy · Contracts │
│ Preferred suppliers · Audit                                            │
└───────────────▲────────────────────────────────────────────────────────┘
                │ same-origin JSON / CSV (FastAPI serves the built SPA)
┌───────────────┴──────────────── FastAPI (Python 3.12) ─────────────────┐
│ api/        routers, request/response schemas (Pydantic v2)            │
│ services/   orchestration: runs, approvals, amendments, chat, import   │
│ ai/         LLM gateway (Gemini → Groq fallback → deterministic path)  │
│ repo/       SQLAlchemy 2 repositories                                  │
│                                                                        │
│ ┌──────────────── procure_engine (pure, zero I/O) ───────────────────┐ │
│ │ matching → clubbing → valuation → contracts → facts → rules →      │ │
│ │ suppliers → consolidation → explain                                │ │
│ └────────────────────────────────────────────────────────────────────┘ │
└───────────────┬────────────────────────────────────────────────────────┘
                │
        PostgreSQL (Neon/Supabase free tier; Docker Postgres locally)
```

**Stack and why**

| Layer | Choice | Reason |
|---|---|---|
| Engine | Plain Python package, `Decimal`, frozen dataclasses | Prototype already proven in Python; pure functions are trivially testable; explainable in Round 2 |
| API | FastAPI + Pydantic v2 | Typed contracts, auto OpenAPI at `/docs` (free API documentation for graders) |
| DB | PostgreSQL + SQLAlchemy 2 + Alembic | JSONB for policy bodies and decision traces; real migrations |
| Frontend | React 18 + Vite + TypeScript + Tailwind + shadcn/ui + TanStack Query/Table | Fast to build dense enterprise tables; good-looking defaults |
| LLM | Gemini Flash (structured JSON output), Groq as fallback | Free tiers; schema-constrained output |
| Hosting | One Docker image on Render (web service) + external free Postgres | One URL, no CORS; the DB survives redeploys |
| CI | GitHub Actions: ruff, mypy, pytest, tsc, eslint, docker build | Green badge in README |

**Hard architectural rules**
1. `procure_engine` imports nothing from `api`, `services` or the DB. It receives a `MasterData` snapshot and a `PolicyResolver` and returns `RunResult`.
2. The UI never computes a decision. It renders `Decision.trace`.
3. Every money value is `Decimal`; thresholds compare unrounded values; rounding happens only at serialisation (2 dp).
4. Every state change writes an `audit_event` (who, when, what, before, after).
5. The app works **with no LLM key**: chat falls back to the deterministic parser, amendments fall back to the structured rule editor.

---

<a id="4-policy-dsl"></a>
## 4. Policy-as-data: the DSL

### 4.1 Design goals
- Every number in the policy is a **named parameter**, so diffs read in business language ("Spot PO limit ₹2,00,000 → ₹3,00,000").
- Rules are an **ordered list**; first match wins (§5 of the policy).
- Conditions are a small typed expression language over a **fact registry**: `all` / `any` / `not` plus `{fact, op, value | param}`.
- Outcomes are data: `decision`, `route` (**any string**, so new routes need no code), supplier strategy, price strategy, suggestion count, flags.
- **Item sets** (named lists or description patterns) and **scopes** (plant, category, department) make plant-only and category rules natural.
- Versions are immutable once approved and resolve by **effective date**.

### 4.2 v5.0 encoded (abridged, the real file is `policies/v5.0.json`)
```json
{
  "policy_id": "CORVO-PROC-POL-04",
  "version": "5.0",
  "effective_from": "2026-04-01",
  "params": {
    "club_created_within_days": { "value": 14,      "unit": "days", "label": "Clubbing window (creation)",  "clause": "2.2" },
    "club_need_by_within_days": { "value": 7,       "unit": "days", "label": "Clubbing window (need-by)",   "clause": "2.2" },
    "last_po_lookback_days":    { "value": 365,     "unit": "days", "label": "Valuation PO lookback",       "clause": "3.1" },
    "bought_lookback_days":     { "value": 365,     "unit": "days", "label": "Purchase-history lookback",   "clause": "5.3" },
    "emergency_limit":          { "value": 500000,  "unit": "INR",  "label": "Emergency PO limit",          "clause": "5.3" },
    "spot_limit":               { "value": 200000,  "unit": "INR",  "label": "Spot PO limit",               "clause": "5.4" },
    "rfq_limit":                { "value": 1000000, "unit": "INR",  "label": "RFQ / RFP boundary",          "clause": "5.5" },
    "preferred_lookback_days":  { "value": 548,     "unit": "days", "label": "Preferred-list lookback",     "clause": "6.1" },
    "po_consolidation_hours":   { "value": 24,      "unit": "hours","label": "PO consolidation window",     "clause": "7.1" },
    "contract_ceiling_tolerance_pct": { "value": 0, "unit": "%",    "label": "Contract ceiling tolerance",  "clause": "4.2" }
  },
  "supplier_eligibility": { "allowed_statuses": ["Active"], "overrides": [] },
  "item_sets": {},
  "clubbing":   { "enabled": true, "key": ["item_code", "plant"], "anchor": "first_line",
                  "never_club_when": { "fact": "item.is_new", "op": "eq", "value": true } },
  "valuation":  { "sources": ["contract_rate", "last_po_price", "standard_price"], "new_item": "requester_estimate" },
  "contracts":  { "selection": "lowest_rate_with_ceiling", "consume_order": "requirement_date" },
  "preferred_suppliers": {
    "include_contract_holders": true,
    "weights": { "frequency": 0.30, "recency": 0.25, "contract": 0.20, "on_time": 0.15, "quality": 0.10 },
    "recency_bands": [ { "within_days": 90, "score": 1.0 }, { "within_days": 365, "score": 0.5 } ],
    "tie_breakers": ["last_po_date_desc", "supplier_id_asc"],
    "reference_price": ["latest_po_in_window", "latest_contract_rate"]
  },
  "suggestions": { "topup": "category_by_delivery_quality", "new_item": "none" },
  "consolidation": { "enabled": true, "key": ["supplier_id", "plant", "route"], "anchor": "first_requirement",
                     "window_param": "po_consolidation_hours" },
  "rules": [
    { "id": "R-1.2", "clause": "1.2", "name": "New item → sourcing",
      "when": { "fact": "item.is_new", "op": "eq", "value": true },
      "then": { "decision": "SOURCING_REQUEST", "route": "NEW_ITEM_SOURCING", "suggest": 0 } },
    { "id": "R-5.1", "clause": "5.1", "name": "Capex → sourcing",
      "when": { "fact": "item.type", "op": "eq", "value": "Capex" },
      "then": { "decision": "SOURCING_REQUEST", "route": "CAPEX_SOURCING", "suggest": 5, "flags": ["CAPEX_APPROVAL"] } },
    { "id": "R-5.2", "clause": "5.2", "name": "Rate contract",
      "when": { "fact": "contract.usable", "op": "eq", "value": true },
      "then": { "decision": "PO", "route": "CONTRACT_PO", "supplier": "contract", "price": "contract_rate" } },
    { "id": "R-5.3", "clause": "5.3", "name": "Emergency PO",
      "when": { "all": [ { "fact": "req.emergency", "op": "eq", "value": true },
                         { "fact": "req.value", "op": "lte", "param": "emergency_limit" },
                         { "fact": "history.bought_from_active", "op": "eq", "value": true } ] },
      "then": { "decision": "PO", "route": "EMERGENCY_PO", "supplier": "preferred:1", "price": "reference_price" } },
    { "id": "R-5.4", "clause": "5.4", "name": "Spot PO",
      "when": { "all": [ { "fact": "req.value", "op": "lt", "param": "spot_limit" },
                         { "fact": "history.bought_from_active", "op": "eq", "value": true } ] },
      "then": { "decision": "PO", "route": "SPOT_PO", "supplier": "preferred:1", "price": "reference_price" } },
    { "id": "R-5.5", "clause": "5.5", "name": "RFQ",
      "when": { "fact": "req.value", "op": "lt", "param": "rfq_limit" },
      "then": { "decision": "SOURCING_REQUEST", "route": "RFQ", "suggest": 3 } },
    { "id": "R-5.6", "clause": "5.6", "name": "RFP",
      "when": { "always": true },
      "then": { "decision": "SOURCING_REQUEST", "route": "RFP", "suggest": 5 } }
  ]
}
```

### 4.3 Fact registry (the extension boundary)
New **conditions over existing facts** need no code. New **facts** are a one-function addition, and we ship a deliberately wide set so amendments almost never need one.

| Namespace | Facts |
|---|---|
| `item.*` | `code`, `description`, `category`, `type` (Material/Service/Capex), `uom`, `standard_price`, `is_new`, `in_set(<name>)` |
| `req.*` | `plant`, `value`, `quantity`, `unit_price`, `emergency`, `line_count`, `date`, `need_by`, `lead_time_days`, `departments`, `requesters`, `any_desc_contains` |
| `contract.*` | `applicable`, `usable`, `count_applicable`, `best_rate`, `remaining_ceiling`, `supplier_id` |
| `history.*` | `bought_from_active` (uses `bought_lookback_days`), `po_count_365`, `days_since_last_po`, `last_po_supplier_status` |
| `preferred.*` | `count`, `first.supplier_id`, `first.on_time_pct`, `first.quality`, `first.reference_price` |
| `supplier.*` | (outcome-time) `status`, `categories`, `on_time_pct`, `quality` |

**Operators:** `eq ne in not_in lt lte gt gte between contains matches exists` · combinators `all any not always`.
**Outcome strategies:** supplier `contract | preferred:N | fixed:<id> | none`; price `contract_rate | reference_price | last_po_price | standard_price`; `suggest: N`; `flags: [...]`; `requires_approval: [role]`.

### 4.4 Amendments the DSL must express with zero code (our drill set)
| # | Amendment | Expressed as |
|---|---|---|
| A1 | Spot limit ₹2 L → ₹3 L from 1 Dec | `set_param spot_limit`, new version effective 2026-12-01 |
| A2 | CHK1-only emergency limit ₹7.5 L | `add_rule` before R-5.3 with `req.plant eq CHK1` |
| A3 | Office & IT always RFQ regardless of value | `add_rule` after R-5.2: `item.category eq "Office & IT"` → RFQ |
| A4 | Proprietary OEM items (Vertex, Hydrax) → `PROPRIETARY_PO` to the OEM | `add_item_set` + `add_rule` with a new route and `supplier: preferred:1` |
| A5 | Clubbing window 14 → 30 days | `set_param` |
| A6 | Services above ₹5 L need an RFP | `add_rule` on `item.type eq Service` |
| A7 | Supplier S013 blocked from 20 Nov | `supplier_eligibility.overrides` |
| A8 | Contracts usable to 110% of ceiling | `set_param contract_ceiling_tolerance_pct` |
| A9 | Emergency POs are not consolidated | `consolidation.exclude_routes` |
| A10 | Need-by within 3 days counts as emergency | `add_rule` with `req.lead_time_days lte 3` (or a derived-fact alias) |
| A11 | RFQ suggests 4 suppliers instead of 3 | `modify_rule R-5.5 then.suggest` |
| A12 | Ranking adds more weight to quality | `set ranking.weights` |

---

<a id="5-engine"></a>
## 5. Decision engine design

### 5.1 Pipeline
```
parse_and_validate(lines)        → ValidLine[] + NotProcessed[] (reasons)
match_items(lines)               → resolved item_code | NEW, match score, candidates
sort by (created_at, pr_no, pr_line)
club(lines, policy@line_date)    → Requirement[] (anchor = first line; earliest joinable)
for req in sorted(reqs, key=requirement_datetime):           # §4.2 consume order
    policy  = resolver.for_date(req.date)                     # version per requirement
    ctx     = facts(req, policy, master, ledger)              # lazy, memoised
    value   = valuation(req, ctx)                             # 3.1
    rule    = first_matching(policy.rules, ctx)               # 5.x
    outcome = apply(rule.then, ctx)                           # supplier, price, suggestions
    ledger.consume(contract, value) if outcome uses contract  # 4.2
    trace   = [RuleEval(rule_id, matched, evaluated_facts)...]
consolidate(PO outcomes, policy)                              # 7.1/7.2
explain(decisions) → reason strings + structured trace
```

### 5.2 Algorithms (the exact semantics)
- **Clubbing (2.2):** iterate lines in order; candidates are open requirements with the same `(item, plant)` where `0 ≤ line.date − first.date ≤ 14` calendar days and `|line.need_by − first.need_by| ≤ 7`; join the **earliest**. NEW items never club. The window is anchored on the first line, not chained.
- **Valuation (3.1):** price = (a) rate of the contract that will be used; if every applicable contract is out of ceiling, the **lowest applicable** rate; (b) the latest PO for the item in `[date−365, date)` (tie → higher PO number); (c) standard price. NEW = qty × estimate.
- **Contracts (4.1–4.3):** applicable = covers item ∧ `start ≤ req.date ≤ end` ∧ supplier Active (after policy overrides). Usable = `consumed + qty × rate ≤ cap × (1 + tolerance)`. Pick the lowest rate among usable. Ceiling consumption runs over a run-scoped **ledger** seeded from the register plus PDF-only contracts at zero.
- **Consolidation (7):** iterate PO requirements by creation time; join the earliest open PO with the same `(supplier, plant, route)` whose first requirement is ≤ 24 h earlier; otherwise open a new PO.
- **Determinism:** shuffling input rows yields byte-identical output (property-tested).

### 5.3 Trace object (powers the UI and `reason`)
```json
{ "requirement_id": "REQ-0007", "policy_version": "5.0",
  "value": { "qty": 4610, "price": "7.06", "source": "contract_rate", "ref": "RC-2026-013", "total": "32546.60" },
  "ladder": [
    { "rule": "R-1.2", "matched": false, "facts": { "item.is_new": false } },
    { "rule": "R-5.1", "matched": false, "facts": { "item.type": "Material" } },
    { "rule": "R-5.2", "matched": true,  "facts": { "contract.usable": true,
        "contracts": [ { "id": "RC-2026-015", "rate": "6.45", "remaining": "12000", "usable": false },
                       { "id": "RC-2026-013", "rate": "7.06", "remaining": "550000", "usable": true } ] } } ],
  "outcome": { "decision": "PO", "route": "CONTRACT_PO", "supplier": "S007", "unit_price": "7.06" },
  "flags": [] }
```
`reason` (CSV): `v5.0 §5.2 CONTRACT_PO via RC-2026-013 @₹7.06 (RC-2026-015 lower rate but ceiling insufficient; §4.3)`.

---

<a id="6-data-model"></a>
## 6. Data model (PostgreSQL)

```
users(id, name, role[REQUESTER|BUYER|PROCUREMENT_ADMIN])
plants(code, name)
items(code, description, uom, category, item_type, standard_price, search_vector)
suppliers(id, name, city, categories[], status, on_time_pct, quality_rating)
po_history(po_number, po_date, supplier_id, item_code, qty, uom, unit_price, plant, delivered_on_time)

contracts(id, supplier_id, start_date, end_date, value_cap, consumed_at_register, source[REGISTER|PDF],
          pdf_object, register_as_of, created_by)
contract_lines(contract_id, item_code, uom, rate)
contract_ledger(id, contract_id, requirement_id, amount, kind[COMMIT|REVERSAL], at)    -- live mode only

policy_versions(id, policy_id, version, effective_from, status[DRAFT|PENDING|ACTIVE|SUPERSEDED|REJECTED],
                body jsonb, body_hash, parent_id, created_by, approved_by, approved_at)
policy_amendments(id, source_kind[DOC|CHAT|EDITOR], source_text, source_file, ops jsonb, questions jsonb,
                  summary jsonb, impact jsonb, proposed_version_id, status, created_by, decided_by, decided_at)

pr_headers(pr_no, created_at, requester, department, source[CHAT|CSV|API], chat_session_id)
pr_lines(pr_no, line, plant, item_code_input, description, qty, uom, est_unit_price, need_by, urgency,
         resolved_item_code, match_score, flags[])

runs(id, kind[BATCH|LIVE], input_file, input_hash, policy_pin, created_by, created_at, summary jsonb)
requirements(id, run_id, group_code, item_code, plant, req_date, emergency, value, policy_version_id)
requirement_lines(requirement_id, pr_no, line)
decisions(id, requirement_id, decision, route, supplier_id, unit_price, suggested[], rule_id, clause,
          trace jsonb, reason, status[PROPOSED|APPROVED|OVERRIDDEN], created_at)        -- immutable
overrides(id, decision_id, new_route, new_supplier_id, new_price, comment NOT NULL, by, at)
purchase_orders(id, po_code, run_id, supplier_id, plant, route, status, created_by, created_at)
po_lines(po_id, requirement_id, item_code, qty, unit_price, amount)
sourcing_events(id, code, requirement_id, kind[RFQ|RFP|CAPEX|NEW_ITEM], suggested[], status)

chat_sessions(id, user_id, state jsonb), chat_messages(id, session_id, role, content, meta jsonb, at)
audit_events(id, actor, action, entity, entity_id, before jsonb, after jsonb, at)          -- append-only
```
Key choices: decisions are **append-only** (an override is a new row linked to the original, per 8.1); batch runs are **isolated** (their own requirement and PO namespace, ledger from baseline); approved live POs write to `contract_ledger`.

---

<a id="7-api"></a>
## 7. API (OpenAPI served at `/docs`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/process-batch` | Multipart `file` **or** raw `text/csv`. Query: `policy_version` (pin), `format=json|csv`. Returns `{run_id, policy_versions_used, summary, decisions[]}` or the CSV. **Stateless w.r.t. contract ceilings.** |
| GET | `/api/runs` · `/api/runs/{id}` · `/api/runs/{id}/export.csv` | Run history and exports |
| GET | `/api/preferred-suppliers/export.csv?as_of=YYYY-MM-DD&top=3` | `item_code,rank,supplier_id,reference_price` |
| GET | `/api/preferred-suppliers/{item}?as_of=` | Ranked list with score breakdown |
| GET/POST | `/api/policy/versions` · `/api/policy/versions/{v}` · `/diff?from=&to=` | Versions, diffs |
| POST | `/api/policy/amendments` (doc upload or `{text}`) | Returns proposed ops, plain-language summary, questions, impact |
| POST | `/api/policy/amendments/{id}/approve` · `/reject` | Activate from effective date / reject |
| POST | `/api/chat/sessions` · `/api/chat/sessions/{id}/messages` | Chat intake |
| GET | `/api/items/match?q=` | Top-k candidates with scores |
| GET | `/api/requirements?status=&route=` · `/api/requirements/{id}` | Buyer inbox and detail (with trace) |
| POST | `/api/requirements/{id}/approve` · `/override` (comment required) | Create PO/RFQ/RFP, or override |
| GET/POST | `/api/contracts` · `/api/contracts/import-pdf` · `/api/contracts/reconcile` | Register, PDF extraction, reconciliation |
| GET | `/api/audit?entity=&id=` | Who/when/what |
| GET | `/healthz` · `/readyz` | Liveness / DB readiness |

Export CSV columns, in input row order: `pr_no, pr_line, resolved_item_code, group_id, po_id, decision, route, supplier_id, unit_price, group_value_inr, suggested_supplier_ids, policy_version, reason`.

---

<a id="8-amendments"></a>
## 8. Policy amendment pipeline

```
Upload (PDF/DOCX/TXT/MD) or chat text
   │ extract text (pdfplumber / python-docx)
   ▼
LLM (temperature 0, JSON schema): input = amendment text + current policy JSON + fact registry + op schema
   → { effective_from, ops[], questions[], each op has source_quote }
   ▼
Validate: schema · param/rule/fact references · types · op legality
   → on error: one repair round with the validator's messages
   ▼
Apply ops to a copy → candidate version (DRAFT)
   ▼
Lint: unreachable rules · missing catch-all · overlapping rules · new routes listed
   ▼
Plain-language diff (deterministic templates, NOT LLM prose)
   "Rule 5.4 Spot PO: value limit below ₹2,00,000 → below ₹3,00,000   ← 'raise the spot purchase limit to ₹3 lakh'"
   ▼
Impact preview: re-run the latest batch under old vs candidate → table of changed decisions
   ▼
Procurement approves → ACTIVE from effective_from (version 5.1); audit event; previous stays for earlier dates
```
**Op vocabulary:** `set_param`, `add_param`, `add_rule{position: before|after <rule_id> | index}`, `modify_rule`, `remove_rule`, `reorder_rules`, `add_item_set`, `set_supplier_override`, `set_ranking`, `set_consolidation`, `set_clubbing`, `set_effective_from`.

**Safeguards:** a manual **structured rule editor** (form plus a JSON view with schema validation) produces the same ops, so if the LLM misreads during the blind test we fix it *in the app*. Duplicate upload detection by `body_hash` ("already active as v5.1"). A retroactive effective date is allowed with a warning; it never mutates already-approved POs.

**Version resolution:** each requirement uses the version in force on its **requirement date**. Clubbing uses the version in force on the candidate requirement's first-line date; consolidation uses the version of the PO's first requirement. Batch runs can be **pinned** (`policy_version=5.0`) so graders can reproduce Run 1 after the amendment is active.

---

<a id="9-chat"></a>
## 9. Chat intake

**Slot state machine:** `item → quantity(+uom) → plant → need_by → urgency → [est_price if NEW] → confirm → created`.

| Concern | Behaviour |
|---|---|
| Extraction | LLM structured output into slots (multi-item messages produce a multi-line PR); deterministic parser fallback (regex for qty/uom, plant aliases Chakan→CHK1, Bhosari/Pune→PUN1, `dateparser` relative to IST "now"). |
| Item resolution | Deterministic matcher returns top-k with scores. High score with clear margin → "I matched **ITM-1048 Nitrile coated gloves (PAIR)**, right?" Ambiguous → clickable chips. No match → "I can't find this in the item master. Is it a new item? Give a short spec and an estimated unit price." **The LLM never proposes item codes**; it can only pick from matcher candidates. |
| Ask for missing | One question at a time, with chips for plants and urgency; dates echo back resolved ("next Friday = **Fri 27 Nov**"). |
| Sanity checks | UoM mismatch ("the item master buys this in PAIR, so 200 gloves = 100 pairs or 200 pairs?"), qty ≤ 0, past need-by, "urgent" in text → "mark as Emergency?" |
| Confirm card | Summary plus a **live decision preview**: "This joins REQ-0042 with 2 earlier PRs for the same item; combined ₹2.3 L → RFQ (policy 2.1 no-splitting)." |
| After create | PR number, expected route, next step and owner. |
| Guardrails | Off-topic → polite redirect; prompt injection in descriptions is treated as data; PR always created via typed API. |

**Chat eval set:** 20 scripted conversations (vague, abbreviation-heavy, unknown item, multi-item, wrong UoM, relative dates, Hindi-English mix like "Chakan ke liye 200 gloves chahiye") with expected slot outcomes, run in CI with the deterministic path and nightly with the LLM.

---

<a id="10-ui"></a>
## 10. Buyer workspace & screens

Every screen has **one primary button**. Indian number formatting everywhere (₹1,37,531; lakh/crore).

| Screen | Content | Primary action |
|---|---|---|
| **Inbox** (buyer home) | Queues: *POs ready to place* (grouped by consolidated PO) · *Sourcing to launch* · *Needs review* (flags) · *Done*. Counts, value totals, filters by route, plant, flag. | "Review next" |
| **Requirement detail** | PR lines; value maths ("1,140 + 2,150 = 3,290 × ₹7.06 (RC-2026-013) = ₹23,227"); the **rule ladder**; clause and version chip; contract ceiling bar; supplier card with ranking breakdown; suggested suppliers with "why"; flags. | Approve → creates PO / RFQ / RFP · secondary: Override (comment required, blocked suppliers not selectable) |
| **PO view** | Consolidated lines, supplier, plant, totals, source decisions; printable. | "Mark issued" |
| **Batches** | Upload → validation report (row errors, flags) → run (pin version optional) → summary chips + table → download CSV. | "Download decisions CSV" |
| **Policy** | Active version, timeline of versions with effective dates, readable rule table ("If item type is Capex → Sourcing (CAPEX_SOURCING), suggest 5"), version diff. | "Propose amendment" |
| **Amendment review** | Source text with highlighted quotes ↔ ops ↔ plain-language changes; questions; impact preview table. | "Approve & activate from {date}" |
| **Contracts** | Register with ceiling burn-down bars, validity, status, source (Register/PDF), reconciliation report. | "Add contract from PDF" |
| **Preferred suppliers** | Item picker, as-of date, ranked list with score components. | "Export CSV" |
| **Run comparison** | Pick two runs (e.g. Run 1 vs Run 2); summary of changed routes/suppliers/values; changed rows highlighted with old → new and the rule that caused it. Doubles as the blind-test sanity check. | "Export diff CSV" |
| **Welcome / tour** | First-visit panel: "1. Raise a PR in chat · 2. Review the inbox · 3. Try a policy amendment". The hosted app ships with the sample batch already processed. | "Start tour" |
| **Audit** | Filterable timeline. | — |

Roles via a seeded user switcher (Requester, Buyer, Procurement Admin). Real authentication is out of scope and documented as such.

---

<a id="11-contracts"></a>
## 11. Contracts & PDF import

- **Seed** the register and lines from CSV, with `register_as_of = 2026-10-31`.
- **PDF import**: pdfplumber text → deterministic parser for this template (contract no., supplier ID, term, ceiling in Indian format "60,00,000", Schedule A rows) → LLM fallback for unfamiliar layouts → **pre-filled form for buyer review** → save with `source=PDF`, consumed 0.
- **Reconcile**: import every PDF; for those in the register, verify supplier, term, ceiling and rates match (report mismatches); for those absent, add as PDF-only. RC-2026-031 and RC-2026-033 get loaded *through this feature* on the hosted app before freeze.
- Validation: an unknown supplier or item blocks saving; a Blocked supplier gives a warning ("contract will not be applicable under §4.1").

---

<a id="12-ranking"></a>
## 12. Preferred supplier ranking (§6)

**Eligibility (6.1):** Active (after overrides) ∧ (≥1 PO for the item in the 548 days before the date ∨ holds a contract for the item that started on or before the date).

**Score (weights live in the policy, so they are versioned and amendable):**
```
score = 0.30·freq + 0.25·recency + 0.20·contract + 0.15·on_time + 0.10·quality
freq     = POs(548d) / max POs(548d) among eligible suppliers for this item   (relative, 0..1)
recency  = 1.0 if last PO ≤ 90 d · 0.5 if ≤ 365 d · 0 otherwise               (matches the worked examples)
contract = 1 if it has held a contract for the item (started ≤ date), else 0
on_time  = on_time_pct / 100
quality  = quality_rating / 5
ties     → most recent PO date, then supplier_id
```
**Why this weighting:** demonstrated buying behaviour (frequency + recency = 55%) predicts a smooth direct PO best; a contract is a negotiated commitment (20%); delivery and quality (25%) separate otherwise similar suppliers without overturning proven history. It reproduces all three worked tables. **Sensitivity check** in DECISIONS.md: ±0.05 perturbations of each weight, with the share of items whose #1 changes reported.

**Reference price (6.3):** latest PO in 548 d; else the rate in its most recent contract for the item.
**Top-up (6.4):** other Active suppliers listing the item's category, ordered by `on_time/100 + quality/5`, then supplier_id. NEW items get no suggestions.
**UI:** each supplier row shows the component bars and a sentence: "Ranked #1: 7 POs in 18 months (most of any supplier), last bought 12 days ago, holds RC-2026-007."

---

<a id="13-testing"></a>
## 13. Testing strategy

| Layer | Tests | Gate |
|---|---|---|
| Golden | 14 worked examples + 3 ranking tables as YAML fixtures | Must pass, in CI |
| Snapshot | Full sample batch → committed expected CSV; diffs require review | CI |
| Boundaries | 14 d / 15 d, 7 d / 8 d, 24 h / 24 h+1 min, ₹2 L exactly, ₹5 L exactly, ₹10 L exactly, ceiling exactly met | CI |
| Invariants (Hypothesis) | No non-Active supplier in PO/suggestions · clubbed lines share item+plant · ceilings never exceeded · PO routes have supplier and price · sourcing has no po_id · NEW never clubbed · shuffle-invariance · idempotence | CI |
| Policy-as-data | Each A1–A12 fixture: ops → expected policy JSON → expected decision delta on the sample batch; version resolution across an effective date mid-batch | CI |
| Matcher | All 39 free-text lines + negatives (`ball bearing 6206` ≠ 6205, `water purifier` → NEW, `monitor 27"` ≠ 24") | CI |
| API contract | process-batch CSV/JSON schema, column order, row count = input rows | CI |
| LLM evals | 20 chat scripts, 12 amendment texts (paraphrased, messy) → scored | Manual/nightly |
| E2E | Playwright: chat → PR → approve; batch → export; amendment → approve → re-run | Pre-freeze |

Target: engine coverage ≥ 90%. Every DECISIONS.md entry links to the test that pins it.

---

<a id="14-prod"></a>
## 14. Production readiness

- **Config:** 12-factor env vars (`DATABASE_URL`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `APP_TZ=Asia/Kolkata`); `.env.example`; no secrets in git.
- **Run:** `docker compose up` → Postgres + app; entrypoint runs Alembic migrations, then an idempotent seed (master data, register, PDF reconcile, policy v5.0).
- **Hosting:** Render free web service (sleeps after 15 min idle, about 1 min wake; filesystem is ephemeral), so: an **external** Postgres (Neon/Supabase; avoid Render's free Postgres, which expires after 30 days), a keep-alive ping every 10 min (UptimeRobot / cron-job.org) on `/healthz`, and nothing stored on local disk (uploads go to DB bytea). Backup host plan: the same image on Railway/Fly, ready to deploy.
- **Freeze-safe deploys:** after the freeze, **disable auto-deploy** (or set a build filter ignoring `submission/**`) so pushing the CSVs at 11:xx does not redeploy the app mid-review.
- **Observability:** structured JSON logs with request IDs; run timings; LLM call logging (latency, tokens, fallback used); `/readyz` checks the DB.
- **Robustness:** upload size and type limits; CSV validation with row-level errors; LLM timeouts (20 s) + retry + provider fallback + deterministic fallback; CSV formula-injection escaping on free-text export fields; DB transactions around approve/override; optimistic concurrency on approvals.
- **Quality gates:** ruff, mypy (strict on the engine), pytest, tsc, eslint, docker build; pre-commit hooks.
- **Docs:** README (one-command run, hosted link, demo users, 3-minute tour, API examples with curl), DECISIONS.md, APPROACH.md (AI tools used, architecture, trade-offs, what we'd do next), `docs/policy-dsl.md`.

---

<a id="15-repo"></a>
## 15. Repository layout

```
corvo-procure/
├─ README.md  DECISIONS.md  APPROACH.md  PLAN.md  docker-compose.yml  Dockerfile  .env.example
├─ backend/
│  ├─ pyproject.toml  alembic/  
│  ├─ procure_engine/            # pure, no I/O
│  │  ├─ models.py  money.py  masterdata.py
│  │  ├─ matching.py  clubbing.py  valuation.py  contracts.py
│  │  ├─ facts.py  conditions.py  rules.py  policy_schema.py  policy_ops.py
│  │  ├─ suppliers.py  consolidation.py  explain.py  pipeline.py
│  ├─ app/
│  │  ├─ main.py  config.py  db.py
│  │  ├─ api/  (batch, runs, policy, amendments, chat, requirements, contracts, suppliers, audit)
│  │  ├─ services/  (run_service, approval_service, amendment_service, chat_service, contract_import)
│  │  ├─ ai/  (gateway.py, prompts/, schemas/)
│  │  ├─ repo/  models.py
│  │  └─ seed/  (loader.py)
│  └─ tests/  (golden/, snapshot/, boundaries/, properties/, policy/, matcher/, api/)
├─ frontend/  (src/routes, src/components, src/lib/format.ts …)
├─ policies/  v5.0.json  schema.json
├─ data/      (kit CSVs + contract PDFs, seeded at startup)
├─ fixtures/  amendments/A1..A12.{md,expected.json}  chats/*.yaml
├─ e2e/       playwright specs
├─ .github/workflows/ci.yml
└─ submission/   (created at blind test)
```

---

<a id="16-timeline"></a>
## 16. Build timeline (Tue 23:00 → Thu 09:30 IST)

Priority tags: **P0** = blind-test critical · **P1** = scored heavily · **P2** = polish. If behind schedule, cut from the bottom of each phase, never P0.

**Revision 1.1 ordering principle:** the complete blind-test path (batch → amendment via the structured editor → re-run → three exports) must work **on the hosted app by Wed 15:00**, before any AI parsing, chat or UI polish. Everything after that milestone is score-raising, not score-protecting.

| Window | Phase | Deliverables | Exit check |
|---|---|---|---|
| **Tue 23:00–02:30** | **0 · Foundation + engine port** (P0) | Repo, Docker Compose, CI skeleton; port the prototype into `procure_engine` with Decimal; golden + snapshot tests; deploy hello-world to Render + Neon | 14/14 golden, 3/3 ranking, hosted `/healthz` green |
| Tue 02:30–08:00 | Sleep | | |
| **Wed 08:00–11:30** | **1 · Policy DSL** (P0) | `policy_schema` (Pydantic), conditions evaluator, fact registry, params, rules-driven pipeline, version resolver, **op applier** (`policy_ops.py`); v5.0.json; boundary + invariant tests; A1–A12 expressed as op fixtures | Engine has **no hard-coded policy numbers** (grep check); all A1–A12 fixtures apply and change decisions as expected |
| **Wed 11:30–15:00** | **2 · Persistence + blind-test path** (P0) | DB models, migrations, seed, PDF import + reconcile, `POST /api/process-batch` (+ version pin), runs, decisions CSV, preferred CSV; amendment endpoints accepting **structured ops** (no LLM yet) + approve/activate; minimal Batches + Policy-editor pages; **demo seed** (sample batch processed so the inbox is populated) | **MILESTONE:** on the hosted URL, Run 1 → apply A1 via editor → Run 2 → preferred export, end to end |
| **Wed 15:00–18:00** | **3 · AI amendment reading** (P1) | LLM gateway (Gemini → Groq), amendment text/doc → ops with source quotes, validator + one repair round, deterministic plain-language diff, impact preview, duplicate detection | ≥ 11/12 drills parsed correctly from prose; the rest fixable in the editor |
| **Wed 18:00–22:30** | **4 · Buyer UI** (P1) | Shell + role switcher; Inbox; Requirement detail with rule ladder; approve/override + audit; Policy timeline + diff; Contracts with ceiling bars; Preferred suppliers; **Run comparison screen** (Run A vs Run B, changed rows highlighted) | Buyer goes from upload to approved PO in < 60 s |
| **Wed 22:30–02:00** | **5 · Chat intake** (P1) | Slot machine, deterministic parser first, LLM extraction second, matcher chips, NEW-item path, confirm card with live decision preview | 20 chat scripts pass on the deterministic path |
| Thu 02:00–06:00 | Sleep (non-negotiable; tired blind tests fail) | | |
| **Thu 06:00–08:15** | **6 · Docs + hardening** (P1) | DECISIONS.md, APPROACH.md, README with screenshots and a 2-minute demo video/GIF; ranking robustness note; interpretation stress-test note; error/empty states | Fresh clone → `docker compose up` works |
| **Thu 08:15–09:30** | **7 · Dress rehearsal + freeze** (P0) | Full Run 1 / amendment / Run 2 / preferred export **on the hosted app** using a fixture amendment written in prose; tag `v1.0`; disable auto-deploy; submit the form | Three CSVs produced in < 15 min |
| Thu 09:30–10:00 | Buffer | | |

**Cut list (in order) if behind:** Playwright → LLM PDF fallback → chat multi-item → demo video → amendment impact preview UI (keep API) → audit screen (keep table). **Never cut** anything in the Wed 15:00 milestone.

### 16.1 Two checks added in revision 1.1
- **Ranking robustness (before freezing weights):** compute top-3 lists for all 73 items under the chosen weights and under ±0.05 perturbations of each weight (and an equal-weights variant). Report the share of items whose top-3 *set* and #1 change. Choose the weighting that reproduces the three worked tables **and** is most stable; record the numbers in DECISIONS.md.
- **Interpretation stress test (D6, D10, D23, D8):** for each, implement the alternative behind a policy/config flag, run the sample batch both ways, count affected rows, and record in DECISIONS.md why the chosen reading is the better business decision. Only the chosen reading is the default.

---

<a id="17-decisions"></a>
## 17. DECISIONS.md register (where the policy is silent)

Format per entry: **Noticed → Decided → Why → Code/Test**.

| # | Noticed | Decision |
|---|---|---|
| D1 | Plant `PUN2` not in plants master | `NOT_PROCESSED`, reason "unknown plant"; the chat only offers valid plants |
| D2 | Quantity 0 / negative / non-numeric | `NOT_PROCESSED` |
| D3 | "- urgent" in the description, urgency field Normal | Urgency field is authoritative (policy says "marked Emergency"); flagged for the buyer; chat asks |
| D4 | Item code given but description disagrees | Code wins (1.1); flag when similarity is low |
| D5 | Fuzzy matching risk | Normalise + abbreviation map + **numeric-token guard** (6205 ≠ 6206); below threshold → NEW (safe: sourcing, never a wrong PO) |
| D6 | PR-174/175 look like duplicates | Clubbed per 2.1 (the anti-split rule already neutralises them); flagged "possible duplicate"; not silently dropped |
| D7 | "Within 14 calendar days" / "within 7 days" | Calendar dates, inclusive, anchored to the requirement's first line (no chaining) |
| D8 | "Last 365 / 548 days" boundaries | Window `[date − N, date)` on PO date |
| D9 | Two POs on the same latest date | Higher PO number is the most recent |
| D10 | Latest PO is from a Blocked/Inactive supplier | 3.1(b) has no supplier condition → used for valuation; "bought from Active" and the PO supplier use Active only |
| D11 | Supplier status history unavailable | Current master status applies to all dates |
| D12 | Contract with a Blocked supplier | Not applicable at all, so excluded from "lowest applicable rate" too |
| D13 | Expired contract holders | Stay on the preferred list (6.1b); reference price from that contract if no PO in 548 d |
| D14 | Ceilings in batch vs live | Batch runs start from the register baseline and are isolated (Run 1 ≠ Run 2 only because of the policy); live approvals commit to a ledger |
| D15 | PDF-only contracts | Consumed starts at 0 (4.2); valid for both plants (PDF clause 3) |
| D16 | Emergency above ₹5 L or without history | Falls through to RFQ/RFP as the ladder dictates |
| D17 | Fewer eligible suppliers than 3/5 | Return fewer; flag "short list"; never pad with ineligible ones |
| D18 | NEW item without an estimate | Value 0, flag "estimate required"; chat insists on an estimate |
| D19 | Capex | Sourcing with a `CAPEX_APPROVAL` flag; never consolidated |
| D20 | Policy version boundaries | Version per requirement date; clubbing by the first line's date; consolidation by the PO's first requirement |
| D21 | Consolidation "within 24 hours" | Inclusive, measured from the PO's first requirement |
| D22 | Money & rounding | Decimal; compare unrounded; output 2 dp |
| D23 | NOT_PROCESSED columns | `decision` blank, `route=NOT_PROCESSED`, reason filled |
| D24 | Need-by before creation date | Process, flag "need-by in the past" |
| D25 | UoM differs from the item master | Known conversions applied; otherwise process with a "UoM mismatch" flag and buyer review |
| D26 | New PR would join an already-approved requirement (live mode) | New requirement, but limits evaluated on the combined value (anti-split), flagged |
| D27 | Override safety | Comment mandatory; Blocked/Inactive suppliers cannot be selected; the original is preserved |
| D28 | Retroactive amendment | Allowed with a warning; affects new runs only; approved POs untouched |
| D29 | Re-running Run 1 after the amendment | `policy_version` pin on process-batch |
| D30 | Example PO numbers offset by 1 | Our PO IDs are our own namespace; grouping matches; see §2.2 |
| D31 | Ranking method | §12, with the sensitivity analysis |

---

<a id="18-runbook"></a>
## 18. Blind-test runbook (Thu 10:00–12:00)

**09:45** Open the hosted app (wake it), check `/readyz`, active policy = v5.0, contracts include RC-2026-031/033. Local `docker compose up` on the **same tag** as a warm fallback.

| Time | Step | Check |
|---|---|---|
| 10:00 | Download the batch + amendment + date | Commit nothing to the app code |
| 10:05 | Batches → upload → validation report | Row count matches; note NOT_PROCESSED rows |
| 10:10 | **Run 1** (pin v5.0) → export `submission/run1_decisions.csv` | No non-Active suppliers (built-in check panel); routes plausible |
| 10:20 | Policy → Propose amendment → upload | Read every op against its source quote; answer questions; **check the effective date** |
| 10:35 | Review the impact preview | The changes match the amendment's intent; fix via the rule editor if not |
| 10:45 | Approve → v5.1 active | Version timeline shows both |
| 10:50 | **Run 2** (no pin, effective-dated) → `submission/run2_decisions.csv` | Diff vs Run 1 = only what the amendment implies |
| 11:00 | Preferred suppliers → as-of date → `submission/preferred_suppliers_<date>.csv` | 3 per item max, no blocked suppliers |
| 11:10 | Spot-check 10 rows by hand against the trace | |
| 11:20 | `git add submission && git commit && git push` | Auto-deploy is off; app untouched |
| 11:30 | Verify files on GitHub | **30 min buffer before 12:00** |

---

<a id="19-risks"></a>
## 19. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM misreads the amendment | Med | High | Ops cite source quotes; impact preview; structured editor fallback; 12 rehearsed drills |
| LLM quota / outage at 10:00 | Med | High | Provider fallback; deterministic chat; the editor needs no LLM |
| Amendment needs a fact we don't have | Low–Med | High | Wide fact registry; `item_sets` + `matches` regex cover most; drill A1–A12 |
| Hosted app sleeps / cold start | High | Low | Keep-alive ping; warm it at 09:45 |
| Redeploy on submission push | Med | High | Auto-deploy off after freeze; DB external |
| Free DB limits | Low | High | Neon/Supabase; nightly `pg_dump` to the repo artifact |
| Over-scoping chat/UI | High | Med | Strict P0 order; cut list |
| Float threshold flips | Low | Med | Decimal everywhere |
| Similar-repo detection | — | High | Our own design, commit history shows incremental work, write-ups in our own words |
| Fatigue errors | High | High | Two sleep blocks; runbook; dress rehearsal |

---

<a id="20-dod"></a>
## 20. Definition of done (freeze checklist)

- [ ] 14/14 worked examples, 3/3 ranking tables, snapshot, boundary, invariant and policy-drill tests green in CI
- [ ] `grep` finds no policy constants in `procure_engine` (only in `policies/*.json`)
- [ ] `POST /api/process-batch` on the **hosted** URL returns the spec CSV
- [ ] Amendment upload → diff → impact → approve → re-run works on hosted, with and without an LLM key
- [ ] Preferred-supplier CSV export for any as-of date
- [ ] Chat: known item, abbreviation, ambiguous, unknown/new, multi-item, relative date all handled
- [ ] Buyer: approve creates a PO/RFQ/RFP; override requires a comment; audit shows who/when
- [ ] Contracts: register loaded; PDF import + reconcile done for 031/033 on hosted
- [ ] README one-command run verified from a fresh clone; hosted link in README
- [ ] DECISIONS.md (D1–D31), APPROACH.md (AI use stated), `docs/policy-dsl.md`
- [ ] Tag `v1.0` before 10:00; auto-deploy disabled; submission form sent
