"""In-memory master-data snapshot with the indexes the engine needs.

Holds the item master (§1), supplier master (§4.1, §5.7, §6), PO history (§3.1b,
§5.3/5.4, §6), plants, and the contract register plus PDF-only contracts (§4.2, §4.4).
Built from plain row dicts, so it is pure: files are read by `loader.py`, DB rows by the app.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from .models import Contract, ContractLine, Item, Plant, PORecord, Supplier
from .money import ZERO, to_decimal


class MasterDataError(ValueError):
    """Raised when master data rows are malformed."""


@dataclass(frozen=True)
class MasterData:
    items: Mapping[str, Item]
    suppliers: Mapping[str, Supplier]
    plants: Mapping[str, Plant]
    po_history: tuple[PORecord, ...]
    contracts: Mapping[str, Contract]
    register_as_of: date | None = None
    _po_by_item: dict[str, tuple[PORecord, ...]] = field(default_factory=dict, repr=False)
    _contracts_by_item: dict[str, tuple[Contract, ...]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        by_item: dict[str, list[PORecord]] = {}
        for po in self.po_history:
            by_item.setdefault(po.item_code, []).append(po)
        for code, pos in by_item.items():
            pos.sort(key=lambda p: p.recency_key)
            self._po_by_item[code] = tuple(pos)
        c_by_item: dict[str, list[Contract]] = {}
        for contract in self.contracts.values():
            for line in contract.lines:
                c_by_item.setdefault(line.item_code, []).append(contract)
        for code, cs in c_by_item.items():
            cs.sort(key=lambda c: c.id)
            self._contracts_by_item[code] = tuple(cs)

    def pos_for_item(self, item_code: str) -> tuple[PORecord, ...]:
        """PO history for an item, oldest first by (date, po_number)."""
        return self._po_by_item.get(item_code, ())

    def contracts_for_item(self, item_code: str) -> tuple[Contract, ...]:
        return self._contracts_by_item.get(item_code, ())

    def with_contracts(self, extra: Iterable[Contract]) -> MasterData:
        """Return a copy with contracts added or replaced (e.g. PDF-only contracts)."""
        merged = dict(self.contracts)
        for contract in extra:
            merged[contract.id] = contract
        return MasterData(
            items=self.items,
            suppliers=self.suppliers,
            plants=self.plants,
            po_history=self.po_history,
            contracts=dict(sorted(merged.items())),
            register_as_of=self.register_as_of,
        )


def _req(row: Mapping[str, str], key: str) -> str:
    if key not in row:
        raise MasterDataError(f"missing column {key!r}")
    return (row[key] or "").strip()


def _bool(text: str) -> bool:
    return text.strip().lower() in {"true", "1", "yes", "y"}


def build_items(rows: Iterable[Mapping[str, str]]) -> dict[str, Item]:
    items: dict[str, Item] = {}
    for row in rows:
        code = _req(row, "item_code")
        items[code] = Item(
            code=code,
            description=_req(row, "description"),
            uom=_req(row, "uom"),
            category=_req(row, "category"),
            item_type=_req(row, "item_type"),
            standard_price=to_decimal(_req(row, "standard_price")),
        )
    return dict(sorted(items.items()))


def build_suppliers(rows: Iterable[Mapping[str, str]]) -> dict[str, Supplier]:
    suppliers: dict[str, Supplier] = {}
    for row in rows:
        sid = _req(row, "supplier_id")
        cats = tuple(c.strip() for c in _req(row, "categories").split(";") if c.strip())
        suppliers[sid] = Supplier(
            id=sid,
            name=_req(row, "name"),
            city=(row.get("city") or "").strip(),
            categories=cats,
            status=_req(row, "status"),
            on_time_pct=to_decimal(_req(row, "on_time_pct")),
            quality_rating=to_decimal(_req(row, "quality_rating")),
        )
    return dict(sorted(suppliers.items()))


def build_plants(rows: Iterable[Mapping[str, str]]) -> dict[str, Plant]:
    plants = {_req(r, "plant"): Plant(code=_req(r, "plant"), name=_req(r, "name")) for r in rows}
    return dict(sorted(plants.items()))


def build_po_history(rows: Iterable[Mapping[str, str]]) -> tuple[PORecord, ...]:
    out: list[PORecord] = []
    for row in rows:
        out.append(
            PORecord(
                po_number=_req(row, "po_number"),
                po_date=date.fromisoformat(_req(row, "po_date")),
                supplier_id=_req(row, "supplier_id"),
                item_code=_req(row, "item_code"),
                quantity=to_decimal(_req(row, "quantity")),
                uom=_req(row, "uom"),
                unit_price=to_decimal(_req(row, "unit_price")),
                plant=_req(row, "plant"),
                delivered_on_time=_bool(_req(row, "delivered_on_time")),
            )
        )
    out.sort(key=lambda p: (p.recency_key, p.item_code, p.supplier_id))
    return tuple(out)


def build_contracts(
    register_rows: Iterable[Mapping[str, str]],
    line_rows: Iterable[Mapping[str, str]],
    *,
    source: str = "REGISTER",
) -> dict[str, Contract]:
    lines_by_contract: dict[str, list[ContractLine]] = {}
    for row in line_rows:
        lines_by_contract.setdefault(_req(row, "contract_id"), []).append(
            ContractLine(
                item_code=_req(row, "item_code"),
                description=(row.get("description") or "").strip(),
                uom=(row.get("uom") or "").strip(),
                rate=to_decimal(_req(row, "rate")),
            )
        )
    contracts: dict[str, Contract] = {}
    for row in register_rows:
        cid = _req(row, "contract_id")
        consumed_text = (row.get("consumed_value") or "").strip()
        contracts[cid] = Contract(
            id=cid,
            supplier_id=_req(row, "supplier_id"),
            supplier_name=(row.get("supplier_name") or "").strip(),
            start=date.fromisoformat(_req(row, "start_date")),
            end=date.fromisoformat(_req(row, "end_date")),
            value_cap=to_decimal(_req(row, "value_cap")),
            consumed=to_decimal(consumed_text) if consumed_text else ZERO,
            source=source,
            lines=tuple(sorted(lines_by_contract.get(cid, []), key=lambda ln: ln.item_code)),
        )
    return dict(sorted(contracts.items()))


def build_master_data(
    *,
    items: Iterable[Mapping[str, str]],
    suppliers: Iterable[Mapping[str, str]],
    plants: Iterable[Mapping[str, str]],
    po_history: Iterable[Mapping[str, str]],
    register: Iterable[Mapping[str, str]],
    contract_lines: Iterable[Mapping[str, str]],
    extra_contracts: Sequence[Contract] = (),
    register_as_of: date | None = None,
) -> MasterData:
    contracts = build_contracts(register, contract_lines)
    for c in extra_contracts:
        contracts.setdefault(c.id, c)
    return MasterData(
        items=build_items(items),
        suppliers=build_suppliers(suppliers),
        plants=build_plants(plants),
        po_history=build_po_history(po_history),
        contracts=dict(sorted(contracts.items())),
        register_as_of=register_as_of,
    )
