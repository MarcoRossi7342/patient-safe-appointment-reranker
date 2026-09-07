from fastapi.testclient import TestClient

from health_search.appointment_search import app, get_reranker


class FixedReranker:
    def rerank(self, query: str, candidates: list[str], top_k: int) -> dict:
        assert query == "cardiologist accepting new patients"
        assert top_k == 2
        assert "cardiology" in candidates[0]
        return {
            "results": [
                {"index": 1, "relevance_score": 0.96},
                {"index": 0, "relevance_score": 0.81},
            ]
        }


def override_reranker():
    yield FixedReranker()


def test_rerank_preserves_referral_safety_action() -> None:
    app.dependency_overrides[get_reranker] = override_reranker
    try:
        response = TestClient(app).post(
            "/search/rerank",
            json={
                "query": "cardiologist accepting new patients",
                "top_k": 2,
                "candidates": [
                    {
                        "appointment_id": "apt-open",
                        "provider_name": "Dr. Rivera",
                        "specialty": "cardiology",
                        "visit_mode": "video",
                        "next_available": "2026-09-08T09:00:00Z",
                        "accepts_new_patients": True,
                        "booking_status": "open",
                    },
                    {
                        "appointment_id": "apt-referral",
                        "provider_name": "Dr. Chen",
                        "specialty": "cardiology",
                        "visit_mode": "in_person",
                        "next_available": "2026-09-05T14:30:00Z",
                        "accepts_new_patients": True,
                        "booking_status": "referral_required",
                    },
                ],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["appointment"]["appointment_id"] == "apt-referral"
    assert body["results"][0]["action"] == "contact_care_team"
    assert body["results"][0]["notification"] == "A referral must be confirmed before booking."
    assert body["results"][1]["action"] == "book"
    assert body["results"][1]["notification"] is None

