# AGENTS.md: Non-negotiable rules for any coding agent in this repo

## 0. Sources of truth, in priority order
1. data/kit/Cantill_FullStack_Task_Brief.pdf  (what to build, output format)
2. data/kit/Corvo_Procurement_Policy.pdf      (policy v5.0 semantics)
3. data/kit/Worked_Examples.pdf               (14 decisions + 3 rankings = acceptance tests)
4. PLAN.md (revision 1.1)                     (architecture, DSL, data model, API, decisions D1–D31)
5. reference/prototype_engine.py              (validated reference logic; reproduces all 14 examples)
If two sources disagree, the higher one wins. If you think PLAN.md is wrong, STOP and ask; do not "improve" it.

## 1. Deviation protocol
- Do not change scope, stack, folder layout, API paths, CSV columns, DSL shape or decisions D1–D31.
- If something is impossible, ambiguous or missing: STOP, append it to docs/OPEN_QUESTIONS.md
  (context, options, your recommendation) and ask the human. Never guess silently.
- Do not add a dependency that is not listed in PLAN.md §3 / this file without asking.
- Work only on the current phase. Do not start the next phase until the human says so.

## 2. Hard rules (violating any of these = the phase is not done)
1. NO HARD-CODED ANSWERS. Engine code must never reference specific PR numbers, item codes,
   supplier IDs, contract IDs or the worked-example values. Those appear ONLY in tests/fixtures
   and data files. Never special-case code to make a test pass.
2. NO POLICY CONSTANTS IN CODE. Every limit, window, count, weight, route name and rule order
   lives in policies/*.json. backend/procure_engine must not contain 14, 7, 365, 548, 24, 200000,
   500000, 1000000, 0.30 etc. as policy values (CI grep check enforces this).
3. ENGINE IS PURE. backend/procure_engine imports nothing from app/, no DB, no HTTP, no LLM,
   no filesystem (except an explicit loader module that tests and the app call).
4. MONEY IS Decimal. Compare thresholds on unrounded Decimals; round to 2 dp only when serialising.
5. DETERMINISTIC. Same inputs → byte-identical outputs. Input row order must not change results.
6. NO NON-ACTIVE SUPPLIERS. A Blocked/Inactive supplier must never receive a PO, be a contract
   supplier used, or appear in suggestions or preferred lists.
7. AI ONLY AT THE EDGES. LLMs may translate chat → slots, amendment text → policy ops,
   PDF → contract fields. LLMs never decide routes, prices or suppliers, and never invent item codes.
   Everything must work with no LLM key (deterministic fallbacks).
8. AUDIT EVERYTHING. Every state change writes audit_events (actor, action, entity, before, after, at).
   Decisions are append-only; overrides are new rows that require a comment.
9. OUTPUT FORMAT IS EXACT. Decisions CSV columns, in this order:
   pr_no,pr_line,resolved_item_code,group_id,po_id,decision,route,supplier_id,unit_price,
   group_value_inr,suggested_supplier_ids,policy_version,reason
   One row per input PR line, in input order. suggested_supplier_ids joined with ';'.
   Preferred CSV: item_code,rank,supplier_id,reference_price (top 3 per item).
10. SECRETS never committed. Use env vars and .env.example.

## 3. Stack (fixed)
Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg, pdfplumber, python-docx,
dateparser, rapidfuzz, httpx, google-genai (Gemini), pytest, hypothesis, ruff, mypy.
Frontend: React 18, Vite, TypeScript, Tailwind, shadcn/ui, TanStack Query, TanStack Table,
react-router. Playwright for E2E.
Infra: one Dockerfile (builds frontend, FastAPI serves it), docker-compose.yml (app + postgres),
GitHub Actions CI. Timezone Asia/Kolkata. Indian number formatting in the UI (₹1,37,531).

## 4. Working style
- Small modules, each explainable in one sentence; docstring at the top of every engine module
  citing the policy clause(s) it implements.
- Tests first for engine work. Run the full test suite before declaring anything done.
- Commit after each completed sub-step using Conventional Commits, e.g.
  "feat(engine): clubbing per policy 2.2". Never squash history.
- End every phase with a REPORT: files changed, commands run with their output (tests, lint),
  acceptance checklist with ✅/❌, open questions. Never claim a check passed without running it.