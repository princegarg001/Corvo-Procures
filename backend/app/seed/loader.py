"""Idempotent seed (PLAN §14): master data, contract register + lines, kit PDFs through the
contract-import feature (PDF-only contracts added with consumed 0; register contracts get
their signed copy attached), policy v5.0 as ACTIVE, demo users, and a demo batch run.
Safe to run on every container start.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from procure_engine.loader import load_policy_dict, read_csv_rows
from procure_engine.money import to_decimal
from procure_engine.policy_schema import load_policy

from ..config import Settings, get_settings
from ..repo.models import (
    ContractLineRow,
    ContractRow,
    ItemRow,
    PlantRow,
    POHistoryRow,
    PolicyVersionRow,
    RunRow,
    SupplierRow,
    User,
)
from ..services import audit, contract_import, masterdata_service, policy_service, run_service

log = logging.getLogger("corvo.seed")
DEMO_USERS = [("Asha", "REQUESTER"), ("Rahul", "BUYER"), ("Meera", "PROCUREMENT_ADMIN")]
DEMO_RUN_NAME = "Sample batch (Nov 2026)"


def _count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def seed_master(session: Session, kit: Path, settings: Settings) -> None:
    if _count(session, ItemRow):
        return
    if not (kit / "master_data" / "item_master.csv").exists():
        log.warning("seed: task kit not found at %s; master data not loaded (set KIT_DIR)", kit)
        return
    md = kit / "master_data"
    for r in read_csv_rows(md / "plants.csv"):
        session.add(PlantRow(code=r["plant"], name=r["name"]))
    for r in read_csv_rows(md / "item_master.csv"):
        session.add(ItemRow(code=r["item_code"], description=r["description"], uom=r["uom"], category=r["category"],
                            item_type=r["item_type"], standard_price=to_decimal(r["standard_price"]),
                            search_vector=r["description"].lower()))
    for r in read_csv_rows(md / "supplier_master.csv"):
        session.add(SupplierRow(id=r["supplier_id"], name=r["name"], city=r["city"],
                                categories=[c.strip() for c in r["categories"].split(";") if c.strip()],
                                status=r["status"], on_time_pct=to_decimal(r["on_time_pct"]),
                                quality_rating=to_decimal(r["quality_rating"])))
    for r in read_csv_rows(md / "po_history.csv"):
        session.add(POHistoryRow(po_number=r["po_number"], po_date=_d(r["po_date"]), supplier_id=r["supplier_id"],
                                 item_code=r["item_code"], qty=to_decimal(r["quantity"]), uom=r["uom"],
                                 unit_price=to_decimal(r["unit_price"]), plant=r["plant"],
                                 delivered_on_time=r["delivered_on_time"].strip().lower() == "true"))
    lines: dict[str, list[dict[str, str]]] = {}
    for r in read_csv_rows(kit / "contracts" / "contract_lines.csv"):
        lines.setdefault(r["contract_id"], []).append(r)
    for r in read_csv_rows(kit / "contracts" / "contract_register.csv"):
        c = ContractRow(id=r["contract_id"], supplier_id=r["supplier_id"], supplier_name=r["supplier_name"],
                        start_date=_d(r["start_date"]), end_date=_d(r["end_date"]), value_cap=to_decimal(r["value_cap"]),
                        consumed_at_register=to_decimal(r["consumed_value"] or "0"), source="REGISTER", plants=[],
                        register_as_of=settings.register_as_of, created_by="seed")
        for ln in lines.get(r["contract_id"], []):
            c.lines.append(ContractLineRow(item_code=ln["item_code"], description=ln["description"], uom=ln["uom"],
                                           rate=to_decimal(ln["rate"])))
        session.add(c)
    session.flush()
    masterdata_service.invalidate()
    audit.record(session, "seed", "seed.master_data", "kit", str(kit), None, {
        "items": _count(session, ItemRow), "suppliers": _count(session, SupplierRow),
        "po_history": _count(session, POHistoryRow), "contracts": _count(session, ContractRow)})


def seed_pdfs(session: Session, kit: Path) -> None:
    """Import every signed contract PDF through the same feature a buyer uses."""
    pdf_dir = kit / "contracts" / "pdf"
    if not pdf_dir.exists():
        return
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        data = pdf.read_bytes()
        try:
            extracted = contract_import.extract(session, data)
        except contract_import.ContractError as exc:
            log.warning("seed: %s: %s", pdf.name, exc)
            continue
        cid = extracted["form"]["contract_id"]
        existing = session.get(ContractRow, cid)
        if existing is not None and existing.pdf_object:
            continue
        if extracted["errors"]:
            log.warning("seed: %s not imported: %s", pdf.name, extracted["errors"])
            continue
        if existing is not None and extracted["mismatches"]:
            log.warning("seed: %s differs from the register: %s", cid, extracted["mismatches"])
        contract_import.save(session, extracted["form"], actor="seed", pdf_bytes=data, filename=pdf.name)


def seed_policy(session: Session, policy_dir: Path) -> None:
    if _count(session, PolicyVersionRow):
        return
    policy = load_policy(load_policy_dict(policy_dir / "v5.0.json"))
    row = policy_service.add_version(session, policy, status="ACTIVE", actor="seed")
    audit.record(session, "seed", "policy.seed", "policy_version", row.version, None,
                 {"effective_from": row.effective_from.isoformat(), "status": "ACTIVE"})


def seed_users(session: Session) -> None:
    for name, role in DEMO_USERS:
        if session.scalar(select(User).where(User.name == name)) is None:
            session.add(User(name=name, role=role))
    session.flush()


def seed_demo_run(session: Session, kit: Path) -> None:
    if session.scalar(select(RunRow).where(RunRow.name == DEMO_RUN_NAME)) is not None:
        return
    sample = kit / "pr_batches" / "sample_pr_batch.csv"
    if not sample.exists():
        return
    run_service.process_batch(session, sample.read_text(encoding="utf-8-sig"), name=DEMO_RUN_NAME,
                              filename=sample.name, pin=None, actor="seed")


def _d(text: str):  # type: ignore[no-untyped-def]
    from datetime import date

    return date.fromisoformat(text.strip())


def seed_all(session: Session, settings: Settings | None = None) -> None:
    s = settings or get_settings()
    seed_users(session)
    seed_master(session, s.kit_dir, s)
    seed_policy(session, s.policy_dir)
    seed_pdfs(session, s.kit_dir)
    session.flush()
    if s.seed_demo_run:
        seed_demo_run(session, s.kit_dir)
