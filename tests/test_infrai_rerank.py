import json

import httpx

from health_search.infrai_rerank import InfraiReranker


def test_retries_rate_limit_and_sends_exact_rerank_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0"},
                json={"ok": False, "data": None, "error": {"code": "RATE_LIMITED"}, "metadata": {}},
            )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {"results": [{"index": 0, "relevance_score": 0.9}]},
                "error": None,
                "metadata": {"vendor": "selected-provider"},
            },
        )

    client = InfraiReranker(
        "test-key",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    try:
        result = client.rerank("cardiology", ["Dr. Rivera; cardiology"], 1)
    finally:
        client.close()

    assert result["results"][0]["index"] == 0
    assert len(requests) == 2
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/v1/ai/rerank"
    assert json.loads(requests[0].content) == {
        "query": "cardiology",
        "candidates": ["Dr. Rivera; cardiology"],
        "top_k": 1,
        "model": "auto",
        "vendor": "auto",
    }

