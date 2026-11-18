"""Command line: run a PR batch (or export preferred suppliers) without the web app.

    python -m procure_engine.cli data/kit/pr_batches/sample_pr_batch.csv -o out.csv
    python -m procure_engine.cli --preferred 2026-11-19 -o preferred.csv
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .export import decisions_csv, preferred_csv
from .loader import DEFAULT_KIT, DEFAULT_POLICY_DIR, load_kit, load_policy_dict, policy_files, read_csv_rows
from .pipeline import run_batch
from .policy_schema import load_policy
from .versions import PolicyResolver


def build_resolver(policy_dir: Path, pin: str | None) -> PolicyResolver:
    versions = [load_policy(load_policy_dict(p)) for p in policy_files(policy_dir)]
    return PolicyResolver(versions, pin=pin)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="procure_engine")
    ap.add_argument("batch", nargs="?", help="PR batch CSV")
    ap.add_argument("-o", "--out", help="output CSV path (default: stdout)")
    ap.add_argument("--kit", default=str(DEFAULT_KIT), help="kit directory with master_data/ and contracts/")
    ap.add_argument("--policies", default=str(DEFAULT_POLICY_DIR), help="directory of policy versions v*.json")
    ap.add_argument("--pin", help="pin a policy version, e.g. 5.0")
    ap.add_argument("--preferred", metavar="AS_OF", help="export preferred suppliers as of YYYY-MM-DD instead")
    args = ap.parse_args(argv)

    master, _ = load_kit(Path(args.kit))
    resolver = build_resolver(Path(args.policies), args.pin)
    if args.preferred:
        text = preferred_csv(master, resolver, date.fromisoformat(args.preferred))
    elif args.batch:
        result = run_batch(read_csv_rows(Path(args.batch)), master, resolver)
        text = decisions_csv(result.rows)
        s = result.summary
        print(f"rows={s['input_rows']} requirements={s['requirements']} POs={s['purchase_orders']} "
              f"not_processed={s['not_processed']} versions={','.join(s['policy_versions_used'])}", file=sys.stderr)
        for route, n in s["routes_by_requirement"].items():
            print(f"  {route:<20} {n}", file=sys.stderr)
    else:
        ap.error("give a batch CSV or --preferred AS_OF")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
