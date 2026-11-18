"""The 3 preferred-supplier tables from Worked_Examples.pdf page 5."""

from __future__ import annotations

from datetime import date

import pytest
import yaml

from procure_engine.masterdata import MasterData
from procure_engine.policy_schema import Policy
from procure_engine.suppliers import SupplierBook
from tests.conftest import GOLDEN

SPEC = yaml.safe_load((GOLDEN / "rankings.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("item", sorted(SPEC["rankings"]))
def test_ranking(item: str, master: MasterData, policy_v5: Policy) -> None:
    book = SupplierBook(policy_v5, master)
    ranked = book.preferred(item, date.fromisoformat(SPEC["as_of"]))
    assert [r.supplier_id for r in ranked] == SPEC["rankings"][item]


def test_inactive_supplier_excluded(master: MasterData, policy_v5: Policy) -> None:
    book = SupplierBook(policy_v5, master)
    ranked = book.preferred("ITM-1048", date.fromisoformat(SPEC["as_of"]))
    assert all(master.suppliers[r.supplier_id].status == "Active" for r in ranked)
