# Policy DSL

The engine does not contain the procurement policy. It reads it from a versioned JSON
document (`policies/v5.0.json`, schema in `policies/schema.json`). Procurement changes
the policy by approving **amendment ops**, never by changing code.

## 1. Document shape

| Section | What it controls | Policy clause |
|---|---|---|
| `params` | Every number, with `value`, `unit`, `label` and `clause`. Diffs read as "Spot PO limit ₹2,00,000 → ₹3,00,000". | all |
| `requirement.emergency_urgencies` | Which urgency values make a requirement an emergency. | 2.3 |
| `matching` | Threshold, numeric-token guard, noise phrases (with flags), replacements, abbreviations. | 1.1 |
| `supplier_eligibility` | Statuses allowed to receive POs / suggestions, plus dated per-supplier overrides. | 4.1, 5.7 |
| `item_sets` | Named groups of items by code, category or description regex. | (amendments) |
| `clubbing` | Key, windows (by param name), anchor, `never_club_when` condition. | 2.1–2.3 |
| `valuation` | Ordered price sources and the PO lookback param. | 3.1 |
| `contracts` | Selection strategy and the ceiling tolerance param. | 4.1–4.3 |
| `preferred_suppliers` | Lookback, weights, recency bands, rating scales, tie-breakers, reference price, export size. | 6.1–6.3 |
| `suggestions` | Category top-up and its weights. | 6.4 |
| `consolidation` | Key, window param, routes never consolidated. | 7.1–7.2 |
| `review_flags` | Buyer-review heuristics (possible-duplicate window, description mismatch). | 8.1 |
| `routes` | Labels for routes; a rule may introduce a new route without code. | 5 |
| `rules` | **Ordered** list. The first rule whose `when` matches and whose outcome can be realised decides. | 5 |

## 2. Rules

```json
{ "id": "R-5.4", "clause": "5.4", "name": "Spot PO",
  "when": { "all": [ { "fact": "req.value", "op": "lt", "param": "spot_limit" },
                     { "fact": "history.bought_from_active", "op": "eq", "value": true } ] },
  "then": { "decision": "PO", "route": "SPOT_PO", "supplier": "preferred:1", "price": "reference_price" } }
```

* **Conditions**: a leaf `{fact, op, value | param}` or `all` / `any` / `not` / `always`.
  `param` reads a named parameter, so a limit change is a one-number amendment.
* **Operators**: `eq ne in not_in lt lte gt gte between contains matches exists`.
  Each fact type accepts only the operators that make sense (a `lt` on a boolean is rejected at load time).
  Strings compare case-insensitively; money compares as exact `Decimal`.
* **Outcome (`then`)**
  * `decision`: `PO` or `SOURCING_REQUEST`; `route`: any `UPPER_SNAKE` string (new routes need no code).
  * `supplier`: `contract` · `preferred:N` · `fixed:<supplier id>` · `none`.
  * `price`: `contract_rate` · `reference_price` · `last_po_price` · `standard_price`.
  * `suggest`: N suppliers (preferred list, then category top-up; never ineligible suppliers).
  * `flags`, `requires_approval`: shown to the buyer.
* If a matching PO rule cannot be fulfilled (for example, no eligible preferred supplier),
  the trace records "conditions met but outcome unavailable" and the next rule is tried.
* Load-time validation rejects unknown facts, operators, params, item sets, bad regexes and
  duplicate rule ids. Lint warns about unreachable rules, a missing catch-all and new routes.

## 3. Facts

Facts are computed lazily per requirement and recorded in the decision trace ("rule ladder").
Facts marked *line* are also usable in `clubbing.never_club_when`.

| Fact | Type | Meaning |
|---|---|---|
| `item.code` | string | Resolved item master code (`NEW` for new items). *line* |
| `item.description` | string | Item master description (requester text for new items). *line* |
| `item.category` | string | Item master category, e.g. "Office & IT". *line* |
| `item.type` | string | Material, Service or Capex. *line* |
| `item.uom` | string | Item master unit. *line* |
| `item.standard_price` | money | Standard unit price. *line* |
| `item.is_new` | bool | No item master match (1.2). *line* |
| `item.sets` | list | Item sets the item belongs to. *line* |
| `item.in_set(<set>)` | bool | Membership of one item set. *line* |
| `req.plant` | string | Plant code. *line* |
| `req.value` | money | Quantity × unit price (3.1), unrounded. |
| `req.unit_price` | money | Valuation unit price. |
| `req.price_source` | string | `contract_rate`, `contract_rate_out_of_ceiling`, `last_po_price`, `standard_price`, `requester_estimate`. |
| `req.quantity` | number | Total quantity of the clubbed lines. *line* |
| `req.emergency` | bool | Any line has an emergency urgency (2.3). *line* |
| `req.urgencies` | list | Distinct urgencies. *line* |
| `req.line_count` | number | PR lines in the requirement. *line* |
| `req.date` | date | First line's creation date (2.3). *line* |
| `req.need_by` | date | Earliest need-by date. *line* |
| `req.lead_time_days` | number | Need-by minus requirement date, in days. *line* |
| `req.departments` / `req.requesters` / `req.uoms` | list | From the lines. *line* |
| `req.descriptions` | string | All descriptions joined (use `contains` / `matches`). *line* |
| `contract.applicable` / `contract.usable` | bool | 4.1 / 4.2–4.3. |
| `contract.count_applicable` | number | Applicable contracts. |
| `contract.best_rate` / `contract.remaining_ceiling` | money | Of the contract that would be used (or the lowest applicable). |
| `contract.supplier_id` / `contract.id` | string | Of that contract. |
| `history.bought_from_active` | bool | A PO from an eligible supplier in `bought_lookback_days` (5.3/5.4). *line* |
| `history.po_count` / `history.days_since_last_po` | number | Purchase history in the lookback. *line* |
| `history.last_po_supplier_id` / `history.last_po_supplier_status` | string | Latest PO's supplier. *line* |
| `history.last_po_price` | money | Latest PO price. *line* |
| `preferred.count` | number | Suppliers on the preferred list (6.1). |
| `preferred.supplier_ids` | list | Preferred list in rank order. |
| `preferred.first.supplier_id` / `.on_time_pct` / `.quality` / `.reference_price` / `.score` | mixed | The 1st preferred supplier. |

A new fact is one decorated function in `backend/procure_engine/facts.py`; nothing else changes.

## 4. Amendment ops

| Op | Fields | Example |
|---|---|---|
| `set_param` | `name, value` | Spot limit ₹2 L → ₹3 L |
| `add_param` | `name, value, unit, label, clause` | A Chakan-only emergency limit |
| `add_rule` | `rule` + one of `before` / `after` / `index` (default: before the catch-all) | A plant-only or category rule |
| `modify_rule` | `rule_id, changes{name, clause, when, then (merged), enabled}` | RFQ suggests 4 |
| `remove_rule` / `reorder_rules` | `rule_id` / `order[]` | |
| `add_item_set` | `name, set{label, codes, categories, patterns}` | OEM items |
| `set_supplier_override` | `supplier_id, status, reason, effective_from?, effective_to?` | Block S013 from 20 Nov |
| `set_ranking` / `set_consolidation` / `set_clubbing` / `set_suggestions` / `set_matching` / `set_requirement` | `changes{...}` (deep-merged) | Weights, excluded routes, windows |
| `set_effective_from` | `date` | Version effective date |

Every op may carry `source_quote` (the amendment sentence it came from) and `note`.
`apply_ops` never mutates the current version: it builds a candidate, validates it and
returns it, and `describe_ops` renders one plain-language sentence per op.

## 5. Versions

Each requirement uses the version in force on its **requirement date** (latest
`effective_from` ≤ date). Clubbing uses the version in force on the first line's date;
consolidation uses the version of the PO's first requirement. A batch run can be pinned
(`?policy_version=5.0`) to reproduce Run 1 after an amendment is active.

## 6. Three worked examples

**A. Raise the spot limit to ₹3 lakh from 1 December**
```json
[ { "op": "set_param", "name": "spot_limit", "value": 300000 },
  { "op": "set_effective_from", "date": "2026-12-01" } ]
```

**B. Chakan-only emergency limit of ₹7.5 lakh** (a plant-only rule, evaluated before 5.3)
```json
[ { "op": "add_param", "name": "chk1_emergency_limit", "value": 750000, "unit": "INR", "label": "Emergency PO limit (Chakan)", "clause": "5.3A" },
  { "op": "add_rule", "before": "R-5.3", "rule": {
      "id": "R-5.3A", "clause": "5.3A", "name": "Emergency PO (Chakan)",
      "when": { "all": [ { "fact": "req.plant", "op": "eq", "value": "CHK1" },
                         { "fact": "req.emergency", "op": "eq", "value": true },
                         { "fact": "req.value", "op": "lte", "param": "chk1_emergency_limit" },
                         { "fact": "history.bought_from_active", "op": "eq", "value": true } ] },
      "then": { "decision": "PO", "route": "EMERGENCY_PO", "supplier": "preferred:1", "price": "reference_price" } } } ]
```

**C. Proprietary OEM spares go to a new route** (a new route plus an item set, no code)
```json
[ { "op": "add_item_set", "name": "oem_proprietary", "set": { "label": "Proprietary OEM items", "patterns": ["\\(vertex", "\\(hydrax"] } },
  { "op": "add_rule", "after": "R-5.2", "rule": {
      "id": "R-5.2B", "clause": "5.2B", "name": "Proprietary OEM item → OEM",
      "when": { "all": [ { "fact": "item.in_set(oem_proprietary)", "op": "eq", "value": true },
                         { "fact": "history.bought_from_active", "op": "eq", "value": true } ] },
      "then": { "decision": "PO", "route": "PROPRIETARY_PO", "supplier": "preferred:1", "price": "reference_price" } } } ]
```

All twelve drills (A1–A12) are in `fixtures/amendments/` with their expected resulting
policies, and `backend/tests/policy/test_amendments.py` pins the decision changes each one causes.
