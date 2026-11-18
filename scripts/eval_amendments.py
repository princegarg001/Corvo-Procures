"""Evaluate amendment reading on fixtures/amendments/A1..A12.md (PLAN §8, Phase 3).

For each drill, read the prose (live LLM by default; --mode heuristic for the no-AI reader),
apply the ops to v5.0 and compare with the expected policy from Phase 1:
  * structural: equal after normalising names, ids, labels and clause numbers
  * behavioural: identical decisions on the sample batch and on targeted edge-case batches,
    and identical preferred-supplier lists.
A drill passes when both hold. Prints a score table.

    python scripts/eval_amendments.py                 # LLM (needs GEMINI_API_KEY or GROQ_API_KEY)
    python scripts/eval_amendments.py --mode heuristic
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from procure_engine.export import preferred_csv  # noqa: E402
from procure_engine.loader import DEFAULT_KIT, DEFAULT_POLICY_DIR, load_kit, load_policy_dict, read_csv_rows  # noqa: E402
from procure_engine.pipeline import run_batch  # noqa: E402
from procure_engine.policy_ops import apply_ops  # noqa: E402
from procure_engine.policy_schema import Policy, PolicyError, load_policy  # noqa: E402
from procure_engine.versions import PolicyResolver  # noqa: E402

FIX = ROOT / "fixtures" / "amendments"
TODAY = date(2026, 11, 18)


def normalise(policy: Policy, base: Policy) -> Any:
    doc = policy.to_json_dict()
    base_params, base_rules = set(base.params), {r.id for r in base.rules}
    pmap = {n: f"P{i}" for i, n in enumerate([n for n in doc["params"] if n not in base_params])}
    rmap = {r["id"]: f"R{i}" for i, r in enumerate([r for r in doc["rules"] if r["id"] not in base_rules])}
    smap = {n: f"S{i}" for i, n in enumerate(sorted(doc["item_sets"]))}
    text = json.dumps(doc, sort_keys=True)
    for mapping in (pmap, rmap):
        for old, new in mapping.items():
            text = text.replace(f'"{old}"', f'"{new}"')
    for old, new in smap.items():
        text = text.replace(f'"{old}"', f'"{new}"').replace(f"({old})", f"({new})")
    out = json.loads(text)
    for p in out["params"].values():
        p.pop("label", None)
        p.pop("clause", None)
    for r in out["rules"]:
        for k in ("name", "clause", "description"):
            r.pop(k, None)
    for s in out["item_sets"].values():
        s.pop("label", None)
    for o in out["supplier_eligibility"]["overrides"]:
        o.pop("reason", None)
    out.pop("title", None)
    out.pop("version", None)
    return out


def variants(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    def edit(pr: str, **kw: str) -> list[dict[str, str]]:
        out = copy.deepcopy(rows)
        for r in out:
            if r["pr_no"] == pr:
                r.update(kw)
        return out

    twin = dict(next(r for r in rows if r["pr_no"] == "PR-26-00058"))
    twin.update(pr_no="PR-26-90058", created_at="2026-11-12 13:15", need_by_date="2026-12-20", quantity="100")
    return {
        "sample": rows,
        "chk1_emergency_6L": edit("PR-26-00058", quantity="3000"),
        "emergency_twin": [*rows, twin],
        "short_lead_time": edit("PR-26-00089", need_by_date="2026-11-07"),
    }


def behaviour(policy: Policy, base: Policy, md: Any, batches: dict[str, list[dict[str, str]]]) -> str:
    parts = []
    for name, rows in batches.items():
        res = run_batch(rows, md, PolicyResolver([base, policy]))
        groups: dict[str, list[str]] = {}
        pos: dict[str, list[str]] = {}
        for r in res.rows:
            groups.setdefault(r.group_id, []).append(f"{r.pr_no}/{r.pr_line}")
            if r.po_id:
                pos.setdefault(r.po_id, []).append(f"{r.pr_no}/{r.pr_line}")
        parts.append(json.dumps([name, [(r.pr_no, r.pr_line, r.route, r.supplier_id, r.unit_price, r.group_value_inr,
                                         r.suggested_supplier_ids) for r in res.rows],
                                 sorted(sorted(g) for g in groups.values()), sorted(sorted(p) for p in pos.values())]))
    res2 = PolicyResolver([base, policy])
    parts.append(preferred_csv(md, res2, date(2026, 11, 15)))
    return "\n".join(parts)


def read_ops(mode: str, text: str, base: Policy, md: Any) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
    if mode == "heuristic":
        from app.ai import heuristics

        h = heuristics.read(text, base, md, TODAY)
        return h["ops"], h["effective_from"], {"provider": "deterministic"}
    from app.ai.amendment_reader import llm_read

    r = llm_read(text, base, md)
    eff = r["effective_from"].isoformat() if r["effective_from"] else None
    return r["ops"], eff, r["meta"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["llm", "heuristic"], default="llm")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    md, _ = load_kit(DEFAULT_KIT)
    base = load_policy(load_policy_dict(DEFAULT_POLICY_DIR / "v5.0.json"))
    rows = read_csv_rows(DEFAULT_KIT / "pr_batches" / "sample_pr_batch.csv")
    batches = variants(rows)
    ids = args.only or [f"A{i}" for i in range(1, 13)]
    results = []
    for aid in ids:
        expected = load_policy(json.loads((FIX / f"{aid}.expected.json").read_text(encoding="utf-8"), parse_float=__import__("decimal").Decimal))
        text = (FIX / f"{aid}.md").read_text(encoding="utf-8")
        status, note, ms = "FAIL", "", ""
        try:
            ops, eff, meta = read_ops(args.mode, text, base, md)
            ms = str(meta.get("latency_ms", ""))
            full = [*ops, *([{"op": "set_effective_from", "date": eff}] if eff else [])]
            got = apply_ops(base, full, new_version="5.1")
            structural = normalise(got, base) == normalise(expected, base)
            behavioural = behaviour(got, base, md, batches) == behaviour(expected, base, md, batches)
            status = "PASS" if (structural or behavioural) and got.effective_from == expected.effective_from else "FAIL"
            note = (f"structural={'yes' if structural else 'no'} behavioural={'yes' if behavioural else 'no'} "
                    f"eff={got.effective_from} ops={[o.get('op') for o in ops]}")
        except PolicyError as exc:
            note = "invalid: " + "; ".join(exc.messages)[:160]
        except Exception as exc:  # LLM unavailable, etc.
            note = f"{type(exc).__name__}: {str(exc)[:160]}"
        results.append((aid, status, ms, note))
        print(f"{aid:<4} {status:<5} {ms:>6} {note}", flush=True)
    passed = sum(1 for r in results if r[1] == "PASS")
    print(f"\nscore ({args.mode}): {passed}/{len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
