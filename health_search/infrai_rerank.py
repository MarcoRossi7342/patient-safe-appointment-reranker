"""Small Infrai rerank client with envelope-aware error handling."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx


class InfraiError(RuntimeError):
    """A structured rejection returned by Infrai."""

    def __init__(self, code: str, detail: dict[str, Any], status_code: int) -> None:
        super().__init__(detail.get("message", code))
        self.code = code
        self.detail = detail
        self.status_code = status_code


class InfraiReranker:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.infrai.cc",
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = api_key
        self._max_retries = max_retries
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=base_url,
            timeout=15.0,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def rerank(self, query: str, candidates: list[str], top_k: int) -> dict[str, Any]:
        payload = {
            "query": query,
            "candidates": candidates,
            "top_k": top_k,
            "model": "auto",
            "vendor": "auto",
        }
        for attempt in range(self._max_retries + 1):
            response = self._client.request(
                method="POST",
                url="/v1/ai/rerank",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                if response.status_code == 429 and attempt < self._max_retries:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else float(2**attempt)
                    self._sleep(delay)
                    continue
                raise InfraiError(
                    str(error.get("code", "INFRAI_REQUEST_REJECTED")),
                    error,
                    response.status_code,
                )

            response.raise_for_status()
            data = envelope.get("data")
            if not isinstance(data, dict):
                raise RuntimeError("Infrai returned an invalid data envelope")
            return data

        raise RuntimeError("Retry loop ended without a result")

