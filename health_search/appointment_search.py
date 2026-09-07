"""HTTP service for reranking appointment search results."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .infrai_rerank import InfraiError, InfraiReranker


class AppointmentCandidate(BaseModel):
    appointment_id: str
    provider_name: str
    specialty: str
    visit_mode: Literal["in_person", "video"]
    next_available: str
    accepts_new_patients: bool
    booking_status: Literal["open", "referral_required", "closed"]
    patient_note: str | None = None

    def rerank_text(self) -> str:
        note = self.patient_note or "No additional scheduling note."
        return (
            f"{self.provider_name}; specialty: {self.specialty}; mode: {self.visit_mode}; "
            f"next available: {self.next_available}; booking: {self.booking_status}; {note}"
        )


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    candidates: list[AppointmentCandidate] = Field(min_length=1, max_length=100)
    top_k: int = Field(default=5, ge=1, le=20)


class RankedAppointment(BaseModel):
    rank: int
    relevance_score: float
    appointment: AppointmentCandidate
    action: Literal["book", "contact_care_team", "unavailable"]
    notification: str | None


class SearchResponse(BaseModel):
    results: list[RankedAppointment]


def appointment_action(candidate: AppointmentCandidate) -> tuple[str, str | None]:
    """Keep ranking relevance separate from the permitted scheduling action."""
    if not candidate.accepts_new_patients or candidate.booking_status == "closed":
        return "unavailable", "This appointment cannot be booked for a new patient."
    if candidate.booking_status == "referral_required":
        return "contact_care_team", "A referral must be confirmed before booking."
    return "book", None


def build_ranked_results(
    candidates: list[AppointmentCandidate], rerank_data: dict[str, Any]
) -> list[RankedAppointment]:
    raw_results = rerank_data.get("results")
    if not isinstance(raw_results, list):
        raise ValueError("Rerank data must contain a results list")

    ranked: list[RankedAppointment] = []
    for rank, item in enumerate(raw_results, start=1):
        if not isinstance(item, dict):
            raise ValueError("Each rerank result must be an object")
        index = item.get("index")
        score = item.get("relevance_score")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(candidates):
            raise ValueError("Rerank result index is outside the candidate list")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            raise ValueError("Rerank result score must be numeric")
        candidate = candidates[index]
        action, notification = appointment_action(candidate)
        ranked.append(
            RankedAppointment(
                rank=rank,
                relevance_score=float(score),
                appointment=candidate,
                action=action,
                notification=notification,
            )
        )
    return ranked


def get_reranker() -> Iterator[InfraiReranker]:
    api_key = os.environ.get("INFRAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set INFRAI_API_KEY before starting the service")
    client = InfraiReranker(api_key)
    try:
        yield client
    finally:
        client.close()


app = FastAPI(title="Appointment search reranker")


@app.post("/search/rerank", response_model=SearchResponse)
def rerank_appointments(
    request: SearchRequest,
    reranker: Annotated[InfraiReranker, Depends(get_reranker)],
) -> SearchResponse:
    try:
        data = reranker.rerank(
            request.query,
            [candidate.rerank_text() for candidate in request.candidates],
            min(request.top_k, len(request.candidates)),
        )
        return SearchResponse(results=build_ranked_results(request.candidates, data))
    except InfraiError as exc:
        client_status = exc.status_code if 400 <= exc.status_code < 500 else 502
        raise HTTPException(
            status_code=client_status,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
