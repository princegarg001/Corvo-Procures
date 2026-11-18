"""Interpretation stress test (PLAN §16.1) for decisions D6, D8, D10, D23.

Runs the sample batch under the chosen reading and under the alternative reading (switched on
here, in the script, by flag — the engine defaults never change) and counts affected PR lines.

  D6  near-duplicate PRs: club + flag (chosen) vs drop the later duplicate
  D8  lookback windows: [date - N, date) (chosen) vs [date - N, date] (PO on the date counts)
  D10 latest PO from a non-Active supplier: used for valuation (chosen) vs ignored
  D23 NOT_PROCESSED rows: decision blank (chosen) vs decision "NOT_PROCESSED"

    python scripts/interpretation_stress.py
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from procure_engine import facts, suppliers, valuation  # noqa: E402
from procure_engine.loader import DEFAULT_KIT, DEFAULT_POLICY_DIR, load_kit, load_policy_dict, read_csv_rows  # noqa: E402
from procure_engine.pipeline import RunResult, run_batch  # noqa: E402
from procure_engine.policy_schema import load_policy  # noqa: E402
from procure_engine.versions import PolicyResolver  # noqa: E402


def diff(a: RunResult, b: RunResult) -> tuple[int, dict[str, int]]:
    kb = {(r.pr_no, r.pr_line): r for r in b.rows}
    changed = 0
    fields: dict[str, int] = {}
    for r in a.rows:
        o = kb.get((r.pr_no, r.pr_line))
        if o is None:
            changed += 1
            fields["dropped"] = fields.get("dropped", 0) + 1
            continue
        diffs = [f for f in ("route", "supplier_id", "unit_price", "group_value_inr", "suggested_supplier_ids", "decision")
                 if getattr(r, f) != getattr(o, f)]
        if diffs:
            changed += 1
            for f in diffs:
                fields[f] = fields.get(f, 0) + 1
    return changed, fields


@contextmanager
def inclusive_windows() -> Iterator[None]:
    """D8 alternative: a PO dated on the requirement date counts as history."""
    orig_latest = valuation.latest_po

    def latest_po(master, item_code, on, lookback_days):  # type: ignore[no-untyped-def]
        return orig_latest(master, item_code, on + timedelta(days=1), lookback_days + 1)

    orig_hist = facts._history

    def history(ctx):  # type: ignore[no-untyped-def]
        days = ctx.policy.param_int("bought_lookback_days")
        on = ctx.req_date
        return [p for p in ctx.master.pos_for_item(ctx.item_code) if on - timedelta(days=days) <= p.po_date <= on] if ctx.item else []

    orig_window = suppliers.SupplierBook._window_pos

    def window(self, item_code, as_of):  # type: ignore[no-untyped-def]
        days = self.policy.param_int(self.policy.preferred_suppliers.lookback_param)
        return [p for p in self.master.pos_for_item(item_code) if as_of - timedelta(days=days) <= p.po_date <= as_of]

    valuation.latest_po, facts._history, suppliers.SupplierBook._window_pos = latest_po, history, window
    import procure_engine.valuation as v
    v.latest_po = latest_po
    try:
        yield
    finally:
        valuation.latest_po, facts._history, suppliers.SupplierBook._window_pos = orig_latest, orig_hist, orig_window


@contextmanager
def ignore_non_active_valuation() -> Iterator[None]:
    """D10 alternative: valuation ignores POs from Blocked/Inactive suppliers."""
    orig = valuation.latest_po

    def latest_po(master, item_code, on, lookback_days):  # type: ignore[no-untyped-def]
        lo = on - timedelta(days=lookback_days)
        window = [p for p in master.pos_for_item(item_code) if lo <= p.po_date < on
                  and master.suppliers.get(p.supplier_id) is not None and master.suppliers[p.supplier_id].status == "Active"]
        return max(window, key=lambda p: p.recency_key) if window else None

    valuation.latest_po = latest_po
    try:
        yield
    finally:
        valuation.latest_po = orig


def main() -> int:
    md, _ = load_kit(DEFAULT_KIT)
    res = PolicyResolver([load_policy(load_policy_dict(DEFAULT_POLICY_DIR / "v5.0.json"))])
    rows = read_csv_rows(DEFAULT_KIT / "pr_batches" / "sample_pr_batch.csv")
    base = run_batch(rows, md, res)
    print(f"{'decision':<6} {'alternative':<58} {'lines affected':>15}  detail")

    dup_reqs = [r for r in base.requirements if "POSSIBLE_DUPLICATE" in base.decisions[r.id].flags]
    drop = {(rl.line.pr_no, str(rl.line.pr_line)) for r in dup_reqs for rl in r.lines[1:]}
    alt = run_batch([r for r in rows if (r["pr_no"], r["pr_line"]) not in drop], md, res)
    n, f = diff(base, alt)
    print(f"{'D6':<6} {'drop the later of two near-duplicate PRs':<58} {n:>15}  {f} dropped={sorted(drop)}")

    with inclusive_windows():
        alt = run_batch(rows, md, res)
    n, f = diff(base, alt)
    print(f"{'D8':<6} {'windows include the requirement date [d-N, d]':<58} {n:>15}  {f}")

    with ignore_non_active_valuation():
        alt = run_batch(rows, md, res)
    n, f = diff(base, alt)
    print(f"{'D10':<6} {'valuation ignores POs from non-Active suppliers':<58} {n:>15}  {f}")

    np_rows = [r for r in base.rows if r.route == "NOT_PROCESSED"]
    print(f"{'D23':<6} {'NOT_PROCESSED rows carry decision=NOT_PROCESSED':<58} {len(np_rows):>15}  "
          f"{[f'{r.pr_no}/{r.pr_line}' for r in np_rows]} (format only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
