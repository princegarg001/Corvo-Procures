"""Builds the engine's MasterData snapshot from the database (cached until data changes)."""

from __future__ import annotations

import threading

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from procure_engine.masterdata import MasterData
from procure_engine.models import Contract, ContractLine, Item, Plant, PORecord, Supplier

from ..repo.models import ContractRow, ItemRow, PlantRow, POHistoryRow, SupplierRow

_lock = threading.Lock()
_cache: MasterData | None = None


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def contract_from_row(c: ContractRow) -> Contract:
    return Contract(
        id=c.id, supplier_id=c.supplier_id, supplier_name=c.supplier_name, start=c.start_date, end=c.end_date,
        value_cap=c.value_cap, consumed=c.consumed_at_register, source=c.source,
        lines=tuple(ContractLine(ln.item_code, ln.description, ln.uom, ln.rate) for ln in c.lines),
        plants=tuple(c.plants or ()),
    )


def load_master(session: Session) -> MasterData:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
    items = {r.code: Item(r.code, r.description, r.uom, r.category, r.item_type, r.standard_price)
             for r in session.scalars(select(ItemRow).order_by(ItemRow.code))}
    suppliers = {r.id: Supplier(r.id, r.name, r.city, tuple(r.categories or ()), r.status, r.on_time_pct, r.quality_rating)
                 for r in session.scalars(select(SupplierRow).order_by(SupplierRow.id))}
    plants = {r.code: Plant(r.code, r.name) for r in session.scalars(select(PlantRow).order_by(PlantRow.code))}
    pos = tuple(
        PORecord(r.po_number, r.po_date, r.supplier_id, r.item_code, r.qty, r.uom, r.unit_price, r.plant, r.delivered_on_time)
        for r in session.scalars(select(POHistoryRow).order_by(POHistoryRow.po_date, POHistoryRow.po_number))
    )
    contracts = {c.id: contract_from_row(c)
                 for c in session.scalars(select(ContractRow).options(selectinload(ContractRow.lines)).order_by(ContractRow.id))}
    md = MasterData(items=items, suppliers=suppliers, plants=plants, po_history=pos, contracts=contracts)
    with _lock:
        _cache = md
    return md
