"""Scripted chat-intake conversations (fixtures/chats/*.yaml) on the deterministic path
(no LLM), through the HTTP API, with today pinned to Wed 18 Nov 2026 (PLAN §9, Phase 5)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

CHATS = Path(__file__).resolve().parents[3] / "fixtures" / "chats"
SCRIPTS = sorted(CHATS.glob("*.yaml"))


@pytest.fixture(scope="module")
def chat_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    db = tmp_path_factory.mktemp("chatdb") / "chat.db"
    saved = {k: os.environ.get(k) for k in ("DATABASE_URL", "APP_TODAY", "GEMINI_API_KEY", "GROQ_API_KEY",
                                             "SEED_DEMO_RUN", "LOG_JSON", "STATIC_DIR")}
    os.environ.update(DATABASE_URL=f"sqlite:///{db.as_posix()}", APP_TODAY="2026-11-18", GEMINI_API_KEY="",
                      GROQ_API_KEY="", SEED_DEMO_RUN="0", LOG_JSON="0",
                      STATIC_DIR=str(tmp_path_factory.mktemp("nostatic")))
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
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    config.reset_settings()
    masterdata_service.invalidate()
    policy_service._parsed.clear()


def _check(step: int, view: dict[str, Any], expect: dict[str, Any]) -> None:
    state = view["state"]
    new = [m for m in view["messages"] if m["id"] in view.get("new_message_ids", [])]
    reply = "\n".join(m["content"] for m in new)
    chips = [c.get("value", "") + " " + c.get("label", "") for m in new for c in (m["meta"] or {}).get("chips", [])]
    card = next((m["meta"]["card"] for m in new if (m["meta"] or {}).get("card")), None)
    where = f"turn {step}: reply was {reply!r}"
    if "pending" in expect:
        assert (state.get("pending") or {}).get("type") == expect["pending"], where
    if "stage" in expect:
        assert state.get("stage") == expect["stage"], where
    for s in expect.get("reply_contains", []):
        assert s in reply, where
    for s in expect.get("reply_not_contains", []):
        assert s not in reply, where
    for s in expect.get("chips_include", []):
        assert any(s in c for c in chips), f"{where}; chips {chips}"
    for s in expect.get("chips_exclude", []):
        assert not any(s in c for c in chips), f"{where}; chips {chips}"
    if "lines" in expect:
        assert len(state["lines"]) == expect["lines"], where
    if "card_items" in expect:
        assert card is not None, where
        assert [ln["item_code"] for ln in card["lines"]] == expect["card_items"], where
    if "card_routes" in expect:
        assert card is not None, where
        assert [ln["preview"].get("route") for ln in card["lines"]] == expect["card_routes"], where


@pytest.mark.parametrize("path", SCRIPTS, ids=[p.stem for p in SCRIPTS])
def test_chat_script(path: Path, chat_client: TestClient) -> None:
    script = yaml.safe_load(path.read_text(encoding="utf-8"))
    headers = {"X-User": "Asha"}
    sid = chat_client.post("/api/chat/sessions", headers=headers).json()["id"]
    view: dict[str, Any] = {}
    for i, turn in enumerate(script["turns"], start=1):
        body = {"text": turn.get("say", ""), "value": turn.get("value")}
        r = chat_client.post(f"/api/chat/sessions/{sid}/messages", json=body, headers=headers)
        assert r.status_code == 200, r.text
        view = r.json()
        _check(i, view, turn.get("expect", {}))
    if "max_turns" in script:
        assert len(script["turns"]) <= script["max_turns"]
    final = script.get("final")
    if final:
        state = view["state"]
        lines = state["lines"]
        assert len(lines) == len(final["lines"])
        for got, want in zip(lines, final["lines"], strict=True):
            for k, v in want.items():
                assert str(got.get(k)) == str(v) or (k == "est_price" and float(got[k]) == float(v)), (k, got, want)
        for k in ("plant", "need_by", "urgency"):
            if k in final:
                assert state.get(k) == final[k], (k, state.get(k))
        if state.get("stage") == "created":
            pr = state["pr_no"]
            rows = chat_client.get("/api/requirements", params={"q": pr}).json()
            assert rows, f"{pr} should be in the buyer inbox"
