"""HTTP client for the OpenRouter Decisions API."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
CATALOG_URL = "https://openrouter.ai/api/v1/models"
MODEL_ID = "baseten/mammoth-1"


class OpenRouterDecisionClient:
    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str = ENDPOINT,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is not set")
        self.endpoint = endpoint
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> OpenRouterDecisionClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            self._owns_client = True
        return self._client

    async def catalog_check(self) -> dict[str, Any]:
        """Fetch the decision-model catalog and return the mammoth-1 entry (or raise)."""
        resp = await self.client.get(f"{CATALOG_URL}?output_modalities=decisions")
        resp.raise_for_status()
        data = resp.json()
        models = data.get("data", [])
        entry = next((m for m in models if m.get("id") == MODEL_ID), None)
        if entry is None:
            raise ValueError(f"model {MODEL_ID} not found in decision catalog")
        arch = entry.get("architecture", {})
        if "decisions" not in (arch.get("output_modalities") or []):
            raise ValueError(f"model {MODEL_ID} does not advertise decisions output modality")
        return entry

    async def probe(
        self, state: str = "probe", question: str = "Is this a probe?"
    ) -> dict[str, Any]:
        """Minimal authenticated POST probe."""
        body = {
            "model": MODEL_ID,
            "state": state,
            "questions": {
                "probe": {
                    "type": "noul",
                    "instructions": question,
                    "criteria": {"true": "yes", "false": "no"},
                }
            },
        }
        t0 = time.perf_counter()
        resp = await self.client.post(
            self.endpoint,
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        if resp.status_code >= 400:
            raise RuntimeError(f"probe failed: HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        if "answers" not in data:
            raise ValueError("probe response missing 'answers'")
        data["_latency_ms"] = latency_ms
        data["_status_code"] = resp.status_code
        return data

    async def decide(
        self, state: str, questions: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """POST a decisions request. Returns (response_json, meta)."""
        body = {"model": MODEL_ID, "state": state, "questions": questions}
        t0 = time.perf_counter()
        resp = await self.client.post(
            self.endpoint,
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        meta = {"status_code": resp.status_code, "latency_ms": latency_ms}
        if resp.status_code >= 400:
            raise RuntimeError(
                f"decisions request failed: HTTP {resp.status_code}: {resp.text[:500]}"
            )
        data = resp.json()
        meta["request_id"] = data.get("id")
        meta["model"] = data.get("model")
        meta["provider"] = data.get("provider")
        meta["usage"] = data.get("usage", {})
        return data, meta
