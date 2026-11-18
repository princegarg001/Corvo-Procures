"""The engine's only filesystem module: load the kit CSVs, contract PDFs and policy files.

Tests, the CLI and the app's seed call this; every other engine module is pure.
Contracts present only as signed PDFs are added with consumed = 0 (policy 4.2, 4.4).
"""

from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from .contract_pdf import ParsedContract, ReconcileReport, parse_contract_pdf, reconcile
from .masterdata import MasterData, build_master_data

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KIT = REPO_ROOT / "data" / "kit"
DEFAULT_POLICY_DIR = REPO_ROOT / "policies"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def read_csv_text(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


def parse_contract_pdfs(pdf_dir: Path) -> list[ParsedContract]:
    return [parse_contract_pdf(p.read_bytes()) for p in sorted(pdf_dir.glob("*.pdf"))]


def load_kit(kit_dir: Path = DEFAULT_KIT, *, include_pdfs: bool = True) -> tuple[MasterData, ReconcileReport | None]:
    """Load master data and contracts; add PDF-only contracts at zero consumption."""
    md = build_master_data(
        items=read_csv_rows(kit_dir / "master_data" / "item_master.csv"),
        suppliers=read_csv_rows(kit_dir / "master_data" / "supplier_master.csv"),
        plants=read_csv_rows(kit_dir / "master_data" / "plants.csv"),
        po_history=read_csv_rows(kit_dir / "master_data" / "po_history.csv"),
        register=read_csv_rows(kit_dir / "contracts" / "contract_register.csv"),
        contract_lines=read_csv_rows(kit_dir / "contracts" / "contract_lines.csv"),
    )
    if not include_pdfs:
        return md, None
    parsed = parse_contract_pdfs(kit_dir / "contracts" / "pdf")
    report = reconcile(dict(md.contracts), parsed)
    extra = [p.to_contract() for p in parsed if p.contract_id in report.pdf_only]
    return md.with_contracts(extra), report


def load_json(path: Path) -> Any:
    """Read JSON with every non-integer number parsed as Decimal (never float)."""
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def load_policy_dict(path: Path) -> dict[str, Any]:
    data = load_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a policy object")
    return data


def policy_files(policy_dir: Path = DEFAULT_POLICY_DIR) -> list[Path]:
    return sorted(p for p in policy_dir.glob("v*.json"))

