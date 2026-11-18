"""Ranking robustness (PLAN §16.1): how stable are preferred-supplier lists under weight changes?

For every item, compute the top-3 under the v5.0 weights and under each ±0.05 perturbation of one
weight (renormalised to sum 1), and under equal weights. Report the share of items whose #1 and
whose top-3 set change, and whether the three worked-example tables still reproduce.
Weights are never changed by this script.

    python scripts/ranking_robustness.py [--as-of 2026-11-01 2026-11-19]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from procure_engine.loader import DEFAULT_KIT, DEFAULT_POLICY_DIR, load_kit, load_policy_dict  # noqa: E402
from procure_engine.policy_ops import apply_ops  # noqa: E402
from procure_engine.policy_schema import Policy, load_policy  # noqa: E402
from procure_engine.suppliers import SupplierBook  # noqa: E402

WORKED = {"ITM-1048": ["S029", "S030"], "ITM-1036": ["S023", "S022", "S024"], "ITM-1016": ["S009", "S010"]}
KEYS = ["frequency", "recency", "contract", "on_time", "quality"]


def variants(base: Policy) -> list[tuple[str, dict[str, Decimal]]]:
    w = base.preferred_suppliers.weights.model_dump()
    out = [("v5.0 weights", dict(w))]
    for k in KEYS:
        for delta in (Decimal("0.05"), Decimal("-0.05")):
            v = dict(w)
            v[k] = max(Decimal(0), v[k] + delta)
            total = sum(v.values())
            out.append((f"{k} {'+' if delta > 0 else '-'}0.05", {kk: vv / total for kk, vv in v.items()}))
    out.append(("equal weights", {k: Decimal("0.2") for k in KEYS}))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", nargs="*", default=["2026-11-01", "2026-11-19"])
    args = ap.parse_args()
    md, _ = load_kit(DEFAULT_KIT)
    base = load_policy(load_policy_dict(DEFAULT_POLICY_DIR / "v5.0.json"))
    for as_of in args.as_of:
        on = date.fromisoformat(as_of)
        ref = SupplierBook(base, md)
        ranked_items = [c for c in md.items if ref.preferred(c, on)]
        base_top = {c: [r.supplier_id for r in ref.preferred(c, on)[:3]] for c in ranked_items}
        print(f"\nAs of {as_of}: {len(ranked_items)} of {len(md.items)} items have at least one eligible supplier")
        print(f"{'variant':<20} {'#1 changes':>12} {'top-3 set changes':>18} {'order changes':>14} {'worked tables':>14}")
        for name, w in variants(base):
            pol = apply_ops(base, [{"op": "set_ranking", "changes": {"weights": {k: str(v) for k, v in w.items()}}}])
            book = SupplierBook(pol, md)
            first = top_set = order = 0
            for c in ranked_items:
                top = [r.supplier_id for r in book.preferred(c, on)[:3]]
                first += top[0] != base_top[c][0]
                top_set += set(top) != set(base_top[c])
                order += top != base_top[c]
            worked = sum([r.supplier_id for r in book.preferred(i, date(2026, 11, 1))] == exp for i, exp in WORKED.items())
            n = len(ranked_items)
            print(f"{name:<20} {first:>4} ({first / n:>5.1%}) {top_set:>8} ({top_set / n:>5.1%}) {order:>6} ({order / n:>5.1%}) {worked:>10}/3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
