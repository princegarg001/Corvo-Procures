"""API contract tests (PLAN §13) and the blind-test milestone flow, over HTTP against a
fresh database: Run 1 → amendment via structured ops → approve → Run 2 → pinned re-run →
preferred export; plus approve / override / audit and contract import."""

from __future__ import annotations

import csv
import io
import os
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from procure_engine.export import DECISION_COLUMNS
from tests.conftest import KIT, SAMPLE

FIX = Path(__file__).resolve().parents[3] / "fixtures" / "amendments"
BUYER = {"X-User": "Rahul"}
ADMIN = {"X-User": "Meera"}


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    db = tmp_path_factory.mktemp("db") / "api.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db.as_posix()}"
    os.environ["LOG_JSON"] = "0"
    os.environ["GEMINI_API_KEY"] = ""  # these tests exercise the no-AI path; never call a real provider
    os.environ["GROQ_API_KEY"] = ""
    os.environ["STATIC_DIR"] = str(tmp_path_factory.mktemp("nostatic"))
    from app import config
    from app import db as dbmod
    from app.services import masterdata_service, policy_service

    config.reset_settings()
    dbmod.reset_engine()
    masterdata_service.invalidate()
    policy_service._parsed.clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
    dbmod.reset_engine()


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_health(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    r = client.get("/readyz").json()
    assert r["status"] == "ready" and r["active_policy"] == "5.0"


def test_seeded_state(client: TestClient) -> None:
    contracts = {c["id"]: c for c in client.get("/api/contracts").json()}
    assert contracts["RC-2026-031"]["source"] == "PDF" and contracts["RC-2026-031"]["consumed_at_register"] in ("0", "0.000000")
    assert contracts["RC-2026-033"]["source"] == "PDF"
    runs = client.get("/api/runs").json()
    assert any(r["name"] == "Sample batch (Nov 2026)" for r in runs)
    assert [u["name"] for u in client.get("/api/users").json()] == ["Asha", "Rahul", "Meera"]
    rec = client.get("/api/contracts/reconcile").json()
    assert rec["pdf_only"] == ["RC-2026-031", "RC-2026-033"] and rec["mismatches"] == []


def test_process_batch_multipart_json(client: TestClient) -> None:
    with SAMPLE.open("rb") as fh:
        r = client.post("/api/process-batch", files={"file": ("sample.csv", fh, "text/csv")}, headers=BUYER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["policy_versions_used"] == ["5.0"]
    assert len(body["decisions"]) == 186
    assert list(body["decisions"][0].keys()) == list(DECISION_COLUMNS)
    src = _rows(SAMPLE.read_text(encoding="utf-8"))
    assert [(d["pr_no"], d["pr_line"]) for d in body["decisions"]] == [(s["pr_no"], s["pr_line"]) for s in src]


def test_process_batch_raw_csv_body(client: TestClient) -> None:
    r = client.post("/api/process-batch?format=csv", content=SAMPLE.read_bytes(), headers={"Content-Type": "text/csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.splitlines()
    assert lines[0] == ",".join(DECISION_COLUMNS) and len(lines) == 187


def test_bad_batch_is_rejected(client: TestClient) -> None:
    r = client.post("/api/process-batch", content=b"a,b\n1,2\n", headers={"Content-Type": "text/csv"})
    assert r.status_code == 422 and "missing column" in r.json()["detail"]


def test_milestone_flow(client: TestClient) -> None:
    run1 = client.post("/api/process-batch?format=csv&policy_version=5.0&name=Run%201", content=SAMPLE.read_bytes(),
                       headers={"Content-Type": "text/csv", **BUYER}).text
    ops = [{"op": "set_param", "name": "spot_limit", "value": 300000}]
    created = client.post("/api/policy/amendments", json={"ops": ops, "title": "A1", "effective_from": "2026-11-10"},
                          headers=ADMIN).json()
    assert created["status"] == "PROPOSED", created
    assert created["proposed_version"] == "5.1" and created["effective_from"] == "2026-11-10"
    assert "₹2,00,000 → ₹3,00,000" in created["summary"][0]["text"]
    assert created["impact"]["available"] and created["impact"]["summary"]["route_moves"]["RFQ → SPOT_PO"] > 0
    approved = client.post(f"/api/policy/amendments/{created['id']}/approve", json={"comment": "ok"}, headers=ADMIN).json()
    assert approved["status"] == "APPROVED"
    versions = {v["version"]: v for v in client.get("/api/policy/versions").json()}
    assert versions["5.1"]["status"] == "ACTIVE" and versions["5.0"]["status"] == "SUPERSEDED"

    run2 = _rows(client.post("/api/process-batch?format=csv&name=Run%202", content=SAMPLE.read_bytes(),
                             headers={"Content-Type": "text/csv", **BUYER}).text)
    assert {r["policy_version"] for r in run2} == {"5.0", "5.1"}
    moves = Counter((a["route"], b["route"]) for a, b in zip(_rows(run1), run2, strict=True) if a["route"] != b["route"])
    assert set(moves) == {("RFQ", "SPOT_PO")}

    pinned = client.post("/api/process-batch?format=csv&policy_version=5.0", content=SAMPLE.read_bytes(),
                         headers={"Content-Type": "text/csv"}).text
    assert pinned == run1, "a run pinned to 5.0 reproduces Run 1 byte for byte"

    diff = client.get("/api/policy/diff", params={"from": "5.0", "to": "5.1"}).json()
    assert [c["op"] for c in diff["changes"]] == ["set_param", "set_effective_from"]

    runs = client.get("/api/runs").json()
    a, b = next(r["id"] for r in runs if r["name"] == "Run 1"), next(r["id"] for r in runs if r["name"] == "Run 2")
    cmp = client.get("/api/runs/compare", params={"a": a, "b": b}).json()
    assert cmp["summary"]["route_moves"] == {"RFQ → SPOT_PO": sum(moves.values())}
    assert all(set(c["changes"]) - {"policy_version"} for c in cmp["changed"]), "version-only lines are not changes"
    assert cmp["summary"]["lines_changed"] < sum(1 for r in run2 if r["policy_version"] == "5.1")

    # duplicate upload of the same amendment is flagged
    dup = client.post("/api/policy/amendments", json={"ops": ops, "effective_from": "2026-11-10"}, headers=ADMIN).json()
    assert any("identical to approved version 5.1" in w for w in dup["lint"])
    assert client.post(f"/api/policy/amendments/{dup['id']}/approve", headers=ADMIN).status_code == 409
    client.post(f"/api/policy/amendments/{dup['id']}/reject", json={"comment": "duplicate"}, headers=ADMIN)


def test_invalid_amendment_reports_errors(client: TestClient) -> None:
    bad = client.post("/api/policy/amendments", json={"ops": [{"op": "set_param", "name": "nope", "value": 1}]},
                      headers=ADMIN).json()
    assert bad["status"] == "INVALID" and "unknown param" in bad["errors"][0]
    fixed = client.put(f"/api/policy/amendments/{bad['id']}",
                       json={"ops": [{"op": "modify_rule", "rule_id": "R-5.5", "changes": {"then": {"suggest": 4}}}]},
                       headers=ADMIN).json()
    assert fixed["status"] == "PROPOSED" and not fixed["errors"]
    client.post(f"/api/policy/amendments/{bad['id']}/reject", json={"comment": "test"}, headers=ADMIN)


def test_preferred_export(client: TestClient) -> None:
    r = client.get("/api/preferred-suppliers/export.csv", params={"as_of": "2026-11-01"})
    rows = _rows(r.text)
    assert list(rows[0].keys()) == ["item_code", "rank", "supplier_id", "reference_price"]
    per_item = Counter(r["item_code"] for r in rows)
    assert max(per_item.values()) <= 3
    statuses = {s["id"]: s["status"] for s in client.get("/api/suppliers").json()}
    assert all(statuses[r["supplier_id"]] == "Active" for r in rows)
    assert [r["supplier_id"] for r in rows if r["item_code"] == "ITM-1036"] == ["S023", "S022", "S024"]
    detail = client.get("/api/preferred-suppliers/ITM-1048", params={"as_of": "2026-11-01"}).json()
    assert [x["supplier_id"] for x in detail["ranked"]] == ["S029", "S030"]
    assert detail["excluded"][0]["supplier_id"] == "S031"


def test_buyer_actions_and_audit(client: TestClient) -> None:
    inbox = client.get("/api/inbox").json()
    po = inbox["queues"]["pos"]["items"][0]
    res = client.post(f"/api/purchase-orders/{po['po_id']}/approve", headers=BUYER).json()
    assert res["status"] == "APPROVED"
    assert client.post(f"/api/purchase-orders/{po['po_id']}/issue", headers=BUYER).json()["status"] == "ISSUED"

    src = inbox["queues"]["sourcing"]["items"][0]
    ev = client.post(f"/api/requirements/{src['id']}/approve", headers=BUYER).json()
    assert ev["sourcing_event"]["code"]

    target = next(r for r in client.get("/api/requirements", params={"route": "SPOT_PO", "status": "OPEN"}).json())
    no_comment = client.post(f"/api/requirements/{target['id']}/override",
                             json={"route": "SPOT_PO", "supplier_id": "S013", "unit_price": "10", "comment": " "}, headers=BUYER)
    assert no_comment.status_code == 422 and "reason" in no_comment.json()["detail"]
    blocked = client.post(f"/api/requirements/{target['id']}/override",
                          json={"route": "SPOT_PO", "supplier_id": "S004", "unit_price": "10", "comment": "test"}, headers=BUYER)
    assert blocked.status_code == 422 and "Blocked" in blocked.json()["detail"]
    ok = client.post(f"/api/requirements/{target['id']}/override",
                     json={"route": "RFQ", "comment": "price looks stale, get quotes"}, headers=BUYER)
    assert ok.status_code == 200, ok.text
    detail = client.get(f"/api/requirements/{target['id']}").json()
    assert detail["route"] == "RFQ" and detail["overridden"] and len(detail["history"]) == 2
    assert detail["overrides"][0]["comment"] == "price looks stale, get quotes"
    actions = {a["action"] for a in client.get("/api/audit", params={"entity": "requirement", "id": str(target["id"])}).json()}
    assert "requirement.override" in actions


def test_contract_pdf_import(client: TestClient) -> None:
    pdf = (KIT / "contracts" / "pdf" / "RC-2026-031.pdf").read_bytes()
    r = client.post("/api/contracts/import-pdf", files={"file": ("RC-2026-031.pdf", pdf, "application/pdf")}).json()
    assert r["form"]["contract_id"] == "RC-2026-031" and r["form"]["value_cap"] == "2000000"
    assert r["exists"] and not r["errors"]
    assert client.post("/api/contracts/import-pdf", content=b"not a pdf", headers={"Content-Type": "application/pdf"}).status_code == 415


def test_item_match(client: TestClient) -> None:
    r = client.get("/api/items/match", params={"q": "brg 6308 zz"}).json()
    assert r["resolved"] == "ITM-1022"
    assert client.get("/api/items/match", params={"q": "ball bearing 6206"}).json()["resolved"] == "NEW"


def test_amendment_from_text_without_llm(client: TestClient) -> None:
    text = (FIX / "A11.md").read_text(encoding="utf-8")
    r = client.post("/api/policy/amendments", json={"text": text}, headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ai_meta"]["provider"] == "deterministic"
    assert body["ops"][0]["op"] == "modify_rule" and body["ops"][0]["source_quote"] in text
    assert body["effective_from"] == "2026-11-01" and body["status"] == "PROPOSED"
    client.post(f"/api/policy/amendments/{body['id']}/reject", json={"comment": "test"}, headers=ADMIN)


def test_amendment_document_upload_without_llm(client: TestClient) -> None:
    data = (FIX / "A3.md").read_bytes()
    body = client.post("/api/policy/amendments", files={"file": ("A3.md", data, "text/markdown")}, headers=ADMIN).json()
    assert body["source_kind"] == "DOC" and body["source_text"].startswith("Amendment to the Procurement Policy")
    assert [o for o in body["ops"] if o["op"] != "set_effective_from"] == [] and body["questions"]
    client.post(f"/api/policy/amendments/{body['id']}/reject", json={"comment": "test"}, headers=ADMIN)
