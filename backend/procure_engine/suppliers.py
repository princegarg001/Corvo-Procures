"""Supplier eligibility (§4.1, §5.7), preferred list and ranking (§6.1-6.2),
reference price (§6.3) and sourcing suggestions with category top-up (§6.4).

Score (weights, bands and scales from the policy — PLAN §12):
    score = w_f·freq + w_r·recency + w_c·contract + w_o·on_time/scale + w_q·quality/scale
freq is POs in the lookback window relative to the most-bought eligible supplier,
recency is banded on days since the last PO, contract is 1 if the supplier has held
a contract for the item that started on or before the date.
Blocked/Inactive suppliers (after policy overrides) never appear anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from .masterdata import MasterData
from .models import PORecord
from .money import ONE, ZERO
from .policy_schema import Policy


class Eligibility:
    """Supplier status as seen by one policy version (master status + overrides)."""

    def __init__(self, policy: Policy, master: MasterData):
        self.policy = policy
        self.master = master
        self.allowed = frozenset(policy.supplier_eligibility.allowed_statuses)
        self.overrides = policy.supplier_eligibility.overrides

    def status(self, supplier_id: str, on: date) -> str:
        status = self.master.suppliers[supplier_id].status if supplier_id in self.master.suppliers else "Unknown"
        for ov in self.overrides:
            if ov.supplier_id != supplier_id:
                continue
            if ov.effective_from and on < ov.effective_from:
                continue
            if ov.effective_to and on > ov.effective_to:
                continue
            status = ov.status
        return status

    def eligible(self, supplier_id: str, on: date) -> bool:
        return supplier_id in self.master.suppliers and self.status(supplier_id, on) in self.allowed


@dataclass(frozen=True)
class RankedSupplier:
    supplier_id: str
    rank: int
    score: Decimal
    components: dict[str, Decimal]
    raw: dict[str, Any]
    po_count: int
    last_po_date: date | None
    has_contract: bool
    contract_ids: tuple[str, ...]
    reference_price: Decimal | None
    reference_source: str
    reference_ref: str

    def explanation(self, max_count: int) -> str:
        parts = [f"{self.po_count} PO(s) in the lookback window" + (" (most of any supplier)" if self.po_count and self.po_count == max_count else "")]
        if self.last_po_date:
            parts.append(f"last bought {self.raw['days_since_last_po']} days before the date")
        else:
            parts.append("no PO in the window")
        if self.has_contract:
            parts.append("holds " + ", ".join(self.contract_ids))
        parts.append(f"on-time {self.raw['on_time_pct']}%, quality {self.raw['quality_rating']}")
        return f"Ranked #{self.rank}: " + "; ".join(parts) + "."


@dataclass(frozen=True)
class Suggestion:
    supplier_id: str
    source: str  # "preferred" | "category"
    why: str


@dataclass
class SupplierBook:
    """Memoised §6 computations for one policy version and master snapshot."""

    policy: Policy
    master: MasterData
    eligibility: Eligibility = field(init=False)
    _cache: dict[tuple[str, date], list[RankedSupplier]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.eligibility = Eligibility(self.policy, self.master)

    # -- §6.1 / §6.2 ---------------------------------------------------------------------------
    def preferred(self, item_code: str, as_of: date) -> list[RankedSupplier]:
        key = (item_code, as_of)
        if key not in self._cache:
            self._cache[key] = self._rank(item_code, as_of)
        return self._cache[key]

    def _window_pos(self, item_code: str, as_of: date) -> list[PORecord]:
        days = self.policy.param_int(self.policy.preferred_suppliers.lookback_param)
        lo = as_of - timedelta(days=days)
        return [p for p in self.master.pos_for_item(item_code) if lo <= p.po_date < as_of]

    def _held_contracts(self, item_code: str, as_of: date) -> dict[str, list[tuple[date, str, Decimal]]]:
        held: dict[str, list[tuple[date, str, Decimal]]] = {}
        for c in self.master.contracts_for_item(item_code):
            rate = c.rate_for(item_code)
            if rate is None or c.start > as_of:
                continue
            held.setdefault(c.supplier_id, []).append((c.start, c.id, rate))
        return held

    def _recency(self, days: int | None) -> Decimal:
        if days is None:
            return ZERO
        for band in sorted(self.policy.preferred_suppliers.recency_bands, key=lambda b: b.within_days):
            if days <= band.within_days:
                return band.score
        return ZERO

    def _rank(self, item_code: str, as_of: date) -> list[RankedSupplier]:
        cfg = self.policy.preferred_suppliers
        w = cfg.weights
        elig = self.eligibility
        by_supplier: dict[str, list[PORecord]] = {}
        for p in self._window_pos(item_code, as_of):
            if elig.eligible(p.supplier_id, as_of):
                by_supplier.setdefault(p.supplier_id, []).append(p)
        held = self._held_contracts(item_code, as_of) if cfg.include_contract_holders else {}
        held = {s: v for s, v in held.items() if elig.eligible(s, as_of)}
        members = sorted(set(by_supplier) | set(held))
        if not members:
            return []
        max_count = max((len(v) for v in by_supplier.values()), default=0)
        rows: list[tuple[tuple[Any, ...], RankedSupplier]] = []
        for sid in members:
            pos = sorted(by_supplier.get(sid, []), key=lambda p: p.recency_key)
            sup = self.master.suppliers[sid]
            count = len(pos)
            last = pos[-1] if pos else None
            days = (as_of - last.po_date).days if last else None
            freq = Decimal(count) / Decimal(max_count) if max_count else ZERO
            recency = self._recency(days)
            has_contract = sid in held
            on_time = sup.on_time_pct / cfg.rating_scales.on_time_pct
            quality = sup.quality_rating / cfg.rating_scales.quality_rating
            comps = {
                "frequency": w.frequency * freq,
                "recency": w.recency * recency,
                "contract": w.contract * (ONE if has_contract else ZERO),
                "on_time": w.on_time * on_time,
                "quality": w.quality * quality,
            }
            score = sum(comps.values(), ZERO)
            ref_price, ref_source, ref_ref = self._reference(sid, pos, held.get(sid, []))
            contracts = tuple(sorted(cid for _, cid, _ in held.get(sid, [])))
            ranked = RankedSupplier(
                supplier_id=sid, rank=0, score=score, components=comps,
                raw={
                    "frequency": freq, "recency": recency, "contract": has_contract,
                    "on_time_pct": sup.on_time_pct, "quality_rating": sup.quality_rating,
                    "days_since_last_po": days, "max_po_count": max_count,
                },
                po_count=count, last_po_date=last.po_date if last else None,
                has_contract=has_contract, contract_ids=contracts,
                reference_price=ref_price, reference_source=ref_source, reference_ref=ref_ref,
            )
            rows.append((self._sort_key(ranked), ranked))
        rows.sort(key=lambda r: r[0])
        out = []
        for i, (_, r) in enumerate(rows, start=1):
            out.append(RankedSupplier(**{**r.__dict__, "rank": i}))
        return out

    def _sort_key(self, r: RankedSupplier) -> tuple[Any, ...]:
        key: list[Any] = [-r.score]
        for tb in self.policy.preferred_suppliers.tie_breakers:
            if tb == "last_po_date_desc":
                key.append(-(r.last_po_date.toordinal() if r.last_po_date else 0))
            elif tb == "po_count_desc":
                key.append(-r.po_count)
            elif tb == "supplier_id_asc":
                key.append(r.supplier_id)
        key.append(r.supplier_id)
        return tuple(key)

    # -- §6.3 ----------------------------------------------------------------------------------
    def _reference(
        self, supplier_id: str, pos: list[PORecord], held: list[tuple[date, str, Decimal]]
    ) -> tuple[Decimal | None, str, str]:
        for source in self.policy.preferred_suppliers.reference_price:
            if source == "latest_po_in_window" and pos:
                last = max(pos, key=lambda p: p.recency_key)
                return last.unit_price, "latest_po_in_window", f"PO {last.po_number}"
            if source == "latest_contract_rate" and held:
                _start, cid, rate = max(held, key=lambda h: (h[0], h[1]))
                return rate, "latest_contract_rate", f"contract {cid}"
        return None, "none", ""

    def reference_for(self, supplier_id: str, item_code: str, as_of: date) -> tuple[Decimal | None, str, str]:
        """Reference price of any supplier (used by fixed:<id> strategies)."""
        for r in self.preferred(item_code, as_of):
            if r.supplier_id == supplier_id:
                return r.reference_price, r.reference_source, r.reference_ref
        pos = [p for p in self._window_pos(item_code, as_of) if p.supplier_id == supplier_id]
        held = self._held_contracts(item_code, as_of).get(supplier_id, [])
        return self._reference(supplier_id, pos, held)

    # -- §6.4 ----------------------------------------------------------------------------------
    def topup_score(self, supplier_id: str) -> Decimal:
        s = self.master.suppliers[supplier_id]
        w = self.policy.suggestions.topup_weights
        sc = self.policy.preferred_suppliers.rating_scales
        return w.on_time * s.on_time_pct / sc.on_time_pct + w.quality * s.quality_rating / sc.quality_rating

    def suggest(self, item_code: str, as_of: date, n: int) -> list[Suggestion]:
        if n <= 0:
            return []
        out: list[Suggestion] = []
        for r in self.preferred(item_code, as_of)[:n]:
            out.append(Suggestion(r.supplier_id, "preferred", f"preferred #{r.rank} (score {r.score:.3f})"))
        if len(out) >= n or self.policy.suggestions.topup == "none":
            return out
        item = self.master.items.get(item_code)
        if item is None:
            return out
        taken = {s.supplier_id for s in out}
        pool = [
            sid for sid, sup in self.master.suppliers.items()
            if sid not in taken and item.category in sup.categories and self.eligibility.eligible(sid, as_of)
        ]
        pool.sort(key=lambda sid: (-self.topup_score(sid), sid))
        for sid in pool[: n - len(out)]:
            sup = self.master.suppliers[sid]
            out.append(Suggestion(
                sid, "category",
                f"lists category '{item.category}'; on-time {sup.on_time_pct}%, quality {sup.quality_rating}",
            ))
        return out
