# DECISIONS.md

Where the policy, the brief or the data is silent or ambiguous, this file records **what we noticed → what we
decided → why → where it lives in code → which test pins it**. Paths are relative to `backend/`.
Policy clause numbers refer to Corvo Procurement Policy v5.0.

All numbers quoted below were produced by the scripts in `scripts/` on the kit's sample batch.

## Register

| # | Noticed | Decided | Why | Code | Test |
|---|---|---|---|---|---|
| D1 | Plant `PUN2` (PR-26-00173) is not in the plants master. | `NOT_PROCESSED`, reason "unknown plant PUN2". Chat only offers valid plants. | A PO or sourcing event for a plant that does not exist cannot be fulfilled; guessing would be worse than flagging. | `procure_engine/intake.py:validate_line` | `tests/golden/test_matching.py::test_not_processed` |
| D2 | Quantity 0 (PR-26-00172), negative or non-numeric. | `NOT_PROCESSED` with a reason. | A requirement of zero has no value, so no limit can apply. | `intake.py:validate_line`, `intake.parse_rows` | same; `tests/properties/test_invariants.py` |
| D3 | Descriptions end in "- urgent" while the urgency field says Normal. | The **urgency field is authoritative** (policy 2.3 says "marked Emergency"). The word raises a `URGENT_IN_TEXT` flag for the buyer. Chat asks, never auto-sets. | Auto-promoting on text would let any requester bypass the quote rules by typing a word. | `matching.py` noise phrases (policy JSON), `facts.py:req.emergency` | `fixtures/chats/10_urgent_word_asks.yaml` |
| D4 | Item code given but the description disagrees. | The code wins (policy 1.1); a `DESCRIPTION_MISMATCH` flag is raised when similarity is low. | 1.1 says "if the requester gave an item code, use it". | `matching.py:ItemMatcher.resolve` | `tests/golden/test_matching.py` |
| D5 | Fuzzy matching can confuse `6205` and `6206`, or a 24" and a 27" monitor. | Normalise (noise phrases, abbreviations, `"` → inch), token Jaccard ≥ 0.6, and a **numeric-token guard**: every number in the query must exist in the candidate. Below threshold → NEW. | A wrong item silently becomes a wrong PO; NEW is safe, it goes to sourcing and a buyer. | `matching.py`, policy `matching` section | `test_matching.py` (39 positives, 4 negatives), chat script 16 |
| D6 | PR-26-00174/175: same requester, same item, 4 minutes apart. | Clubbed per 2.1 (the anti-split rule already neutralises it) and flagged `POSSIBLE_DUPLICATE`. Never dropped. | Dropping a line loses a real requirement if it is not a duplicate; clubbing is policy. | `clubbing.py:_flag_duplicates` | snapshot; stress test below |
| D7 | "Within 14 calendar days" / "7 days either side". | Calendar dates, inclusive, anchored on the requirement's first line (no chaining). | Policy 2.2 says "of the requirement's first line". | `clubbing.py:_fits` | `tests/boundaries/test_boundaries.py` (14 d vs 15 d, ±7 d vs ±8 d, no chaining) |
| D8 | "In the 365 / 548 days before the date". | Window `[date − N, date)` on PO date: a PO dated on the requirement date is not history. | "Before the requirement date". | `valuation.py:latest_po`, `suppliers.py:_window_pos` | boundaries (`test_valuation_lookback_window`, `test_po_on_requirement_date_is_not_history`) |
| D9 | Two POs on the same latest date (ITM-1034, 2026-04-10). | Higher PO number is more recent. | Reproduces worked example 11. | `models.py:PORecord.recency_key` | `test_worked_example[11]` |
| D10 | The latest PO for ITM-1014, 1017, 1020, 1049, 1050 is from a Blocked/Inactive supplier. | Valuation 3.1(b) has no supplier condition, so the latest PO prices the requirement. "Bought from an Active supplier" and the PO supplier use Active suppliers only. A `VALUED_ON_NON_ACTIVE_SUPPLIER_PO` flag is raised. | Reads 3.1(b) literally; the supplier rules apply where the policy states them (5.3/5.4/5.7). | `valuation.py`, `facts.py:history.bought_from_active` | worked example 6; stress test below |
| D11 | Supplier status history is not available. | Current master status applies to all dates, with dated policy overrides for known changes. | The data has no status history. | `suppliers.py:Eligibility` | `test_a7_supplier_blocked_from_date` |
| D12 | RC-2026-005 is with a Blocked supplier. | Not applicable at all (4.1), so it is also excluded from "lowest applicable rate" in valuation. | Applicability is defined once, in 4.1. | `contracts.py:assess` | snapshot |
| D13 | RC-2025-020 expired 30 Sep. | Not usable, but its supplier stays on the preferred list (6.1b says "even if it has since expired"). Reference price from the contract if no PO in 548 days. | Literal reading of 6.1b and 6.3. | `suppliers.py:_held_contracts` | worked ranking tables |
| D14 | Contract ceilings in a batch vs live use. | A batch run starts from the register baseline and is isolated; Run 1 and Run 2 differ only by policy. Live approvals commit to a ledger. | The blind test re-runs the same batch; it must not depend on earlier runs. | `contracts.py:Ledger`, `app/services/live_service.py:ledger_baseline` | `test_milestone_flow` (pinned re-run is byte-identical) |
| D15 | RC-2026-031 and RC-2026-033 exist only as PDFs. | Loaded through the contract-import feature with consumed = 0; valid for both plants (PDF clause 3). | Policy 4.2 and 4.4. | `contract_pdf.py`, `app/seed/loader.py:seed_pdfs` | `test_seeded_state`, worked example 2 |
| D16 | Emergency above ₹5 L or without purchase history. | Falls through to RFQ/RFP as the ladder dictates. | First matching rule decides. | policy JSON R-5.3 | boundaries (`test_emergency_limit_is_inclusive`) |
| D17 | Fewer eligible suppliers than 3 or 5. | Return fewer, flag `SHORT_LIST`, never pad with ineligible suppliers. | 5.7; matches worked example 11 (4 suggestions). | `rules.py:realise`, `suppliers.py:suggest` | `test_worked_example[11]` |
| D18 | NEW item without an estimate. | Value 0, flag `ESTIMATE_REQUIRED`; chat insists on an estimate. | Valuation needs a price (1.2). | `valuation.py:value_new_item`, `chat_service` | chat script 21 |
| D19 | Capex. | Sourcing with a `CAPEX_APPROVAL` flag; never consolidated (no PO). | Policy 5.1 "needs capex approval". | policy JSON R-5.1 | `test_worked_example[12]` |
| D20 | A policy version can start mid-batch. | Version per requirement date; clubbing by the candidate group's first-line date; consolidation by the PO's first requirement. | Each stage has its own natural date. | `versions.py`, `clubbing.py`, `consolidation.py` | `test_a1_spot_limit_split_by_effective_date` |
| D21 | "Within 24 hours of the first requirement". | Inclusive, measured from the PO's first requirement. | The policy says "of the first requirement on that PO". | `consolidation.py` | boundaries (24 h vs 24 h + 1 min) |
| D22 | Money and rounding. | `Decimal` everywhere; thresholds compare unrounded values; 2 dp only when serialising. | ₹1,97,514 / ₹2,01,446 sit near limits. | `money.py` | boundaries, `test_values_are_exact_decimals` |
| D23 | Columns for NOT_PROCESSED rows. | `decision` blank, `route=NOT_PROCESSED`, reason filled, policy version of the line's date. | The brief gives `NOT_PROCESSED` as a route. | `pipeline.py:_rows` | snapshot, `test_not_processed` |
| D24 | Need-by before the creation date. | Processed, flagged `NEED_BY_IN_PAST`. Chat rejects past dates. | A data-entry error should not block a real need. | `pipeline.py:_flags` | chat script 11 |
| D25 | Unit differs from the item master. | Process with a `UOM_MISMATCH` flag. Chat asks. | The data has no conversion table. | `pipeline.py:_flags`, `chat_service` | chat script 7 |
| D26 | A new live PR would join an already approved requirement. | Approved requirements are frozen; the new line is a new requirement. | Approved POs are never rewritten (D28). | `live_service.py:_frozen_ids` | — |
| D27 | Override safety. | Comment mandatory; Blocked/Inactive suppliers are not selectable; the original decision is kept as an earlier row. | Policy 8.1 and 5.7. | `approval_service.py:override` | `test_buyer_actions_and_audit` |
| D28 | Retroactive effective date. | Allowed with a warning in the impact preview; affects new runs only. | Approved POs are never changed. | `amendment_service.py:impact` | — |
| D29 | Re-running Run 1 after the amendment. | `policy_version` pin on `process-batch`. | The graders may repeat Run 1. | `versions.py:PolicyResolver(pin=)` | `test_milestone_flow` |
| D30 | Example PO numbers are one lower than ours. | PO IDs are our own namespace; PO **co-membership** matches the examples. See below. | The brief says "Your PO number". | `consolidation.py` | `test_po_numbers_are_our_namespace` |
| D31 | Ranking method. | See below. | — | `suppliers.py` | `tests/golden/test_rankings.py` |

### D30: the PO-number offset
The examples number POs consistently one lower than we do. Every difference traces to one requirement before
09:40 on 2 Nov: PR-174/175, which sit with the other trap rows at the end of the file. The likeliest explanation is
that the answer key was produced before those rows were appended. We checked that our PO groupings equal the
reference prototype's exactly (82 POs, identical membership) and kept our own numbering.

### D31: ranking method
```
score = 0.30·frequency + 0.25·recency + 0.20·contract + 0.15·on_time/100 + 0.10·quality/5
frequency = POs in 548 d / the most POs among eligible suppliers for the item   (relative, 0..1)
recency   = 1.0 if last PO ≤ 90 d, 0.5 if ≤ 365 d, else 0
contract  = 1 if the supplier has held a contract for the item that started on or before the date
ties      = most recent PO date, then supplier ID
```
*Rationale.* Demonstrated buying behaviour (frequency plus recency, 55%) predicts a smooth direct PO best; a
contract is a negotiated commitment (20%); delivery and quality (25%) separate otherwise similar suppliers without
overturning proven history. Frequency is relative so a three-PO item and a thirty-PO item are comparable.
The weights live in the policy, so they are versioned and amendable (drill A12). Buyers see each component as a
bar and a sentence ("Ranked #1: 7 POs … holds RC-2026-007").
The method reproduces all three worked tables, including the Inactive supplier excluded from ITM-1048.

*Robustness* (`scripts/ranking_robustness.py`, 68 of 73 items have an eligible supplier; the other 5 have none):

| Variant (as of 2026-11-01) | #1 changes | top-3 set changes |
|---|---|---|
| frequency ±0.05 | 1.5% / 0% | 0% / 0% |
| recency ±0.05 | 0% / 0% | 0% / 1.5% |
| contract ±0.05 | 0% / 1.5% | 0% / 0% |
| on-time ±0.05 | 0% / 0% | 0% / 0% |
| quality ±0.05 | 0% / 0% | 0% / 1.5% |
| equal weights | 2.9% | 0% |

Every variant still reproduces the three worked tables. Moving any single weight by 0.05 changes the top
supplier for at most 1.5% of items (4.4% for the 2026-11-19 date), and the top-3 *set* for at most 1.5%
(one item). The chosen weights are therefore stable, and we kept them.

## Interpretation stress test
`scripts/interpretation_stress.py` runs the sample batch under the chosen reading and the alternative, and
counts the PR lines affected.

| # | Alternative | Lines affected | What changes |
|---|---|---|---|
| D6 | Drop the later of two near-duplicate PRs | 2 | The ITM-1033 requirement value falls by one unit; PR-26-00175 disappears from the output |
| D8 | Windows include the requirement date | 0 | Nothing in this batch; the choice only matters for a PO dated on a requirement date |
| D10 | Valuation ignores POs from non-Active suppliers | 6 | Six requirement values change (they would be priced on an older PO) |
| D23 | `decision` = "NOT_PROCESSED" instead of blank | 2 (format only) | Cosmetic |

*Why we keep the chosen readings.* D6: dropping a row breaks "one row per input line" and loses a real need if it
is not a duplicate. D10: policy 3.1(b) names no supplier condition while 5.3/5.4 do, so the difference looks
deliberate. D8 is a no-op here, so the literal "before" reading stays. D23 follows the brief's wording.

## Anything else we noticed
* **OEM-branded items** ("(Vertex CNC)", "(Hydrax)") look like the seed for a future "proprietary" rule. The DSL
  expresses it without code (drill A4: an item set plus a new route).
* **Short-pool suggestions** return fewer than requested rather than padding (D17).
* **Chat "urgent"** never sets Emergency on its own (D3).

## Blind test (19 Nov 2026): how Amendment No. 1 was applied
Run 1 was processed pinned to v5.0. The amendment PDF was uploaded through the app's Policy feature and read by the
LLM, then reviewed against its plain-language diff and impact preview before approval (v5.1, effective 1 Dec 2026).
* **A2 (RFP threshold ₹8 L)** and **A3 (Chakan electrical, new rule 5.2A after 5.2)** were read correctly.
* **A1 (Packaging spot limit ₹1 L)** was misread: the generated rule only kept Packaging below ₹1 L as a spot PO, so
  ₹1–2 L Packaging requirements would still have matched the normal spot rule. The impact preview showed no Packaging
  changes, which exposed it. It was corrected in the app's structured editor (new rule 5.4A before 5.4: Packaging,
  value at or above ₹1,00,000 and below the RFP threshold → RFQ), then approved. No code was changed.
* Run 2 reprocessed the same batch with no pin, so each requirement uses the version in force on its date
  (92 lines on v5.0, 98 on v5.1). A pinned v5.0 re-run is byte-identical to Run 1.
