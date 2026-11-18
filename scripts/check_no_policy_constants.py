"""CI guard for AGENTS.md rules 1 and 2.

Fails if backend/procure_engine contains, outside comments and docstrings:
  * policy literals (limits, windows, weights, bands, thresholds), or
  * specific PR numbers, item codes, supplier IDs or contract IDs.
Policy values belong in policies/*.json; IDs belong in tests, fixtures and data.

    python scripts/check_no_policy_constants.py
"""

from __future__ import annotations

import io
import re
import sys
import tokenize
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "backend" / "procure_engine"

FORBIDDEN_NUMBERS = {
    "14", "7", "365", "548", "24", "90", "200000", "500000", "1000000", "750000", "300000",
    "2e5", "5e5", "1e6", "0.30", "0.3", "0.25", "0.20", "0.2", "0.15", "0.10", "0.1", "0.6", "0.5", "1.0",
}
ID_PATTERNS = [
    (re.compile(r"PR-\d{2}-\d{3,}"), "PR number"),
    (re.compile(r"\bITM-\d{3,}"), "item code"),
    (re.compile(r"\bS\d{3}\b"), "supplier ID"),
    (re.compile(r"\bRC-\d{4}-\d{2,}"), "contract ID"),
    (re.compile(r"\b(PUN1|CHK1|PUN2)\b"), "plant code"),
    (re.compile(r"\b(CONTRACT_PO|EMERGENCY_PO|SPOT_PO|RFQ|RFP|CAPEX_SOURCING|NEW_ITEM_SOURCING)\b"), "route name"),
]


def _docstring_lines(source: str) -> set[int]:
    """Line numbers covered by string statements (docstrings)."""
    import ast

    lines: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return lines


def scan(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    doc_lines = _docstring_lines(source)
    problems: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT or tok.start[0] in doc_lines:
            continue
        where = f"{path.relative_to(ENGINE.parents[1])}:{tok.start[0]}"
        if tok.type == tokenize.NUMBER and tok.string.lower().replace("_", "") in FORBIDDEN_NUMBERS:
            problems.append(f"{where}: policy-like literal {tok.string}")
        if tok.type in (tokenize.STRING, tokenize.NAME) or getattr(tokenize, "FSTRING_MIDDLE", -1) == tok.type:
            for pattern, what in ID_PATTERNS:
                if pattern.search(tok.string):
                    problems.append(f"{where}: hard-coded {what} {tok.string!r}")
    return problems


def main() -> int:
    problems = [p for f in sorted(ENGINE.rglob("*.py")) for p in scan(f)]
    for p in problems:
        print(p)
    print(f"checked {len(list(ENGINE.rglob('*.py')))} files: {'FAIL' if problems else 'OK'} ({len(problems)} problem(s))")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
