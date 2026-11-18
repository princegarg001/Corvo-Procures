"""Write the policy and amendment-op JSON Schemas (policies/schema.json, policies/ops.schema.json)."""

from __future__ import annotations

import json
from pathlib import Path

from procure_engine.policy_ops import ops_json_schema
from procure_engine.policy_schema import json_schema

ROOT = Path(__file__).resolve().parents[1] / "policies"

if __name__ == "__main__":
    (ROOT / "schema.json").write_text(json.dumps(json_schema(), indent=2) + "\n", encoding="utf-8")
    (ROOT / "ops.schema.json").write_text(json.dumps(ops_json_schema(), indent=2) + "\n", encoding="utf-8")
    print("wrote", ROOT / "schema.json", "and", ROOT / "ops.schema.json")
