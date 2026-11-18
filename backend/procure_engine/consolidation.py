"""PO consolidation — policy 7.1 (same supplier, plant, route; within N hours of the
PO's first requirement, measured on first-line creation times) and 7.2 (take
requirements in creation order; join the earliest open PO; sourcing never combined);
decisions D19, D21.

Key, window and excluded routes come from the policy version in force on the PO's
first requirement date. The window is inclusive.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .models import PurchaseOrder
from .policy_schema import Policy

SECONDS_PER_HOUR = 3600


@dataclass(frozen=True)
class PORequest:
    requirement_id: str
    created_at: datetime
    sort_key: tuple[datetime, str, int]
    supplier_id: str
    plant: str
    route: str


def _key(req: PORequest, attrs: list[str]) -> tuple[str, ...]:
    return tuple(getattr(req, a) for a in attrs)


def consolidate(
    requests: list[PORequest],
    policy_for: Callable[[date], Policy],
    *,
    id_prefix: str = "PO-",
) -> list[PurchaseOrder]:
    pos: list[PurchaseOrder] = []
    open_meta: list[tuple[PurchaseOrder, PORequest, Policy, bool]] = []  # po, first req, policy, joinable
    for req in sorted(requests, key=lambda r: r.sort_key):
        own = policy_for(req.created_at.date())
        target: PurchaseOrder | None = None
        excluded = not own.consolidation.enabled or req.route in own.consolidation.exclude_routes
        if not excluded:
            for po, first, pol, joinable in open_meta:
                if not joinable:
                    continue
                if _key(first, list(pol.consolidation.key)) != _key(req, list(pol.consolidation.key)):
                    continue
                window = timedelta(seconds=int(pol.param(pol.consolidation.window_param) * SECONDS_PER_HOUR))
                gap = req.created_at - first.created_at
                if timedelta(0) <= gap <= window:
                    target = po
                    break
        if target is None:
            target = PurchaseOrder(
                id=f"{id_prefix}{len(pos) + 1:04d}", supplier_id=req.supplier_id, plant=req.plant,
                route=req.route, first_created_at=req.created_at, policy_version=own.version,
                requirement_ids=[],
            )
            pos.append(target)
            open_meta.append((target, req, own, not excluded))
        target.requirement_ids.append(req.requirement_id)
    return pos
