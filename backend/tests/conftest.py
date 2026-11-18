"""Shared fixtures: the kit master data, policy v5.0 and the sample-batch run."""

from __future__ import annotations

from pathlib import Path

import pytest

from procure_engine.loader import DEFAULT_KIT, DEFAULT_POLICY_DIR, load_kit, load_policy_dict, read_csv_rows
from procure_engine.masterdata import MasterData
from procure_engine.pipeline import RunResult, run_batch
from procure_engine.policy_schema import Policy, load_policy
from procure_engine.versions import PolicyResolver

KIT = DEFAULT_KIT
SAMPLE = KIT / "pr_batches" / "sample_pr_batch.csv"
GOLDEN = Path(__file__).parent / "golden"


@pytest.fixture(scope="session")
def master() -> MasterData:
    md, _ = load_kit(KIT)
    return md


@pytest.fixture(scope="session")
def policy_v5() -> Policy:
    return load_policy(load_policy_dict(DEFAULT_POLICY_DIR / "v5.0.json"))


@pytest.fixture(scope="session")
def resolver(policy_v5: Policy) -> PolicyResolver:
    return PolicyResolver([policy_v5])


@pytest.fixture(scope="session")
def sample_rows() -> list[dict[str, str]]:
    return read_csv_rows(SAMPLE)


@pytest.fixture(scope="session")
def sample_run(sample_rows: list[dict[str, str]], master: MasterData, resolver: PolicyResolver) -> RunResult:
    return run_batch(sample_rows, master, resolver)
