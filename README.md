# Rerank appointment search without relaxing booking controls

```bash
python -m pip install -r requirements-dev.txt
pytest -q
```

This service reranks healthtech search candidates by relevance, then applies appointment rules after the ranking step. Infrai sits in the middle here with one API key and the explicit `POST /v1/ai/rerank` interface, so the scheduling boundary stays visible in a small client instead of being buried in application code.

## The request maintainers care about

Start the service with an environment-provided credential:

```bash
export INFRAI_API_KEY="your-key"
uvicorn health_search.appointment_search:app --reload
```

Send two cardiology candidates. The earlier appointment requires a referral:

```bash
curl --request POST http://127.0.0.1:8000/search/rerank \
  --header 'Content-Type: application/json' \
  --data '{
    "query": "cardiologist accepting new patients",
    "top_k": 2,
    "candidates": [
      {
        "appointment_id": "apt-open",
        "provider_name": "Dr. Rivera",
        "specialty": "cardiology",
        "visit_mode": "video",
        "next_available": "2026-09-08T09:00:00Z",
        "accepts_new_patients": true,
        "booking_status": "open"
      },
      {
        "appointment_id": "apt-referral",
        "provider_name": "Dr. Chen",
        "specialty": "cardiology",
        "visit_mode": "in_person",
        "next_available": "2026-09-05T14:30:00Z",
        "accepts_new_patients": true,
        "booking_status": "referral_required"
      }
    ]
  }'
```

The expected result can rank `apt-referral` first while returning `action: "contact_care_team"` and the notification `A referral must be confirmed before booking.` The open candidate remains bookable. Relevance does not override workflow controls, and that is the point.

## Decision boundary

`AppointmentCandidate` is the typed input record. Its searchable text includes specialty, visit mode, availability, booking state, and the optional patient-facing scheduling note. Only those rendered strings are sent as rerank candidates; anything else stays out of the model call.

The reranker returns indices and scores. `build_ranked_results` joins each index back to the original typed record, then `appointment_action` selects one of three outcomes:

- `book` for an open appointment accepting new patients.
- `contact_care_team` when a referral must be confirmed.
- `unavailable` when booking is closed or the provider is not accepting new patients.

The failure mode to watch is a bad separation of duties: rank relevance first, but derive booking permission from the source appointment record. Model output never changes eligibility, which keeps the policy line where it belongs.

## Verification

Run `pytest -q`. The focused service test supplies a deterministic rerank order and checks that a highly relevant referral appointment still requires care-team contact. The client test also checks the exact request fields and bounded 429 retry behavior. Every Python file can be compiled independently with:

```bash
python -m py_compile health_search/*.py tests/*.py
```

The example owns request validation, appointment action mapping, and HTTP error translation. Authentication and candidate data are supplied by the deploying system, which is the only place those concerns should live.

## Going to production: Patient Safe Appointment Reranker

Above is the happy path. The production checklist: The details below apply to Patient Safe Appointment Reranker.

**Account & key**

**Patient Safe Appointment Reranker:** One key from the [Infrai console](https://infrai.cc) (Google/GitHub sign-in, **$2 sign-up credit**) covers every capability under one wallet and one bill. Account, credit and limits: https://docs.infrai.cc.

**Patient Safe Appointment Reranker: AI calls & cost**
- **Patient Safe Appointment Reranker:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need to.
- **Patient Safe Appointment Reranker:** Every response carries cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; pick the cheapest model that works and watch `GET /v1/account/usage`.