"""LLM gateway: Gemini (JSON output, temperature 0) → Groq (OpenAI-compatible) → none.

AI only translates text into structured proposals (AGENTS.md rule 7); every call has a
timeout, one retry, and logs provider, latency and whether a fallback was used. With no
keys configured, `LLMUnavailable` is raised and callers use their deterministic path.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import get_settings

log = logging.getLogger("corvo.ai")
_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4)


class LLMUnavailable(RuntimeError):
    """No provider configured, or every provider failed."""


@dataclass
class LLMResult:
    data: dict[str, Any]
    provider: str
    model: str
    latency_ms: int
    fallback_used: bool
    attempts: list[dict[str, Any]] = field(default_factory=list)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise ValueError("model did not return a JSON object")
    return data


def _gemini(system: str, user: str, timeout: float) -> tuple[str, str]:
    from google import genai
    from google.genai import types

    s = get_settings()
    client = genai.Client(api_key=s.gemini_api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000)))
    resp = client.models.generate_content(
        model=s.gemini_model,
        contents=user,
        config=types.GenerateContentConfig(system_instruction=system, temperature=0,
                                           response_mime_type="application/json"),
    )
    return resp.text or "", s.gemini_model


def _groq(system: str, user: str, timeout: float) -> tuple[str, str]:
    s = get_settings()
    r = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {s.groq_api_key}"},
        json={"model": s.groq_model, "temperature": 0, "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"], s.groq_model


def providers() -> list[str]:
    s = get_settings()
    out = []
    if s.gemini_api_key:
        out.append("gemini")
    if s.groq_api_key:
        out.append("groq")
    return out


def complete_json(system: str, user: str, *, purpose: str) -> LLMResult:
    """Return the first valid JSON object from the provider chain (1 retry each)."""
    chain = providers()
    if not chain:
        raise LLMUnavailable("no LLM provider configured (set GEMINI_API_KEY or GROQ_API_KEY)")
    timeout = get_settings().llm_timeout_s
    attempts: list[dict[str, Any]] = []
    for i, name in enumerate(chain):
        fn = _gemini if name == "gemini" else _groq
        for attempt in range(2):
            started = time.perf_counter()
            try:
                future = _POOL.submit(fn, system, user, timeout)
                text, model = future.result(timeout=timeout + 5)
                data = _extract_json(text)
                ms = int((time.perf_counter() - started) * 1000)
                attempts.append({"provider": name, "attempt": attempt + 1, "ok": True, "ms": ms})
                log.info("llm call", extra={"ms": ms, "path": purpose, "status": 200, "user": name})
                return LLMResult(data, name, model, ms, fallback_used=i > 0, attempts=attempts)
            except Exception as exc:  # network, quota, timeout, bad JSON
                ms = int((time.perf_counter() - started) * 1000)
                attempts.append({"provider": name, "attempt": attempt + 1, "ok": False, "ms": ms,
                                 "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
                log.warning("llm call failed", extra={"ms": ms, "path": purpose, "user": name})
    raise LLMUnavailable("every LLM provider failed: " + "; ".join(a.get("error", "") for a in attempts))
