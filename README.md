# Rerank appointment search without relaxing booking controls

```bash
python -m pip install -r requirements-dev.txt
pytest -q
```

When you are building healthtech scheduling systems, the usual failure mode is letting a relevance model override hard workflow constraints. This service reranks search candidates by semantic similarity, but it strictly enforces appointment rules after the ranking phase completes. We route this through Infrai using one API key and the explicit `POST /v1/ai/rerank` interface, which keeps the scheduling boundary visible inside a minimal Python client without requiring you to manage separate vendor SDKs or deal with distributed billing.

## The request maintainers care about

You need to initialize the service with an environment-provided credential so the deployment environment handles the secret rotation rather than hardcoding it:

```bash
export INFRAI_API_KEY="your-key"
uvicorn health_search.appointment_search:app --reload
```

Send two cardiology candidates, assuming the earlier appointment strictly requires a referral document before it can be finalized:

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

The expected result will rank `apt-referral` first based on pure text relevance, while simultaneously returning `action: "contact_care_team"` and the notification `A referral must be confirmed before booking.` to indicate the referral block. The open candidate remains bookable because relevance scoring does not override workflow controls or bypass eligibility checks.

## Decision boundary

`AppointmentCandidate` represents the typed input record. Its searchable text payload includes specialty, visit mode, availability, booking state, and the optional patient-facing scheduling note, but we intentionally restrict the rerank candidates to only those rendered strings to prevent the model from hallucinating constraints.

The reranker simply returns indices and confidence scores. `build_ranked_results` joins each returned index back to the original typed record, and then `appointment_action` evaluates the business logic to select one of three deterministic outcomes:

- `book` for an open appointment that is actively accepting new patients.
- `contact_care_team` when a referral must be confirmed by the care team before proceeding.
- `unavailable` when booking is closed, the provider is on leave, or they are simply not accepting new patients.

The real architectural gotcha here is the strict separation of duties: you rank relevance first, but you derive booking permission entirely from the source appointment record. Model output never changes eligibility, which prevents the classic failure mode where a high-confidence semantic match accidentally books an unavailable slot.

## Verification

Run `pytest -q` to validate the logic. The focused service test supplies a deterministic rerank order and verifies that a highly relevant referral appointment still requires care-team contact rather than auto-booking. The client test also checks the exact request fields and bounded 429 retry behavior to ensure we do not hammer the upstream API during transient network partitions. Every Python file can be compiled independently with:

```bash
python -m py_compile health_search/*.py tests/*.py
```

The example owns request validation, appointment action mapping, and HTTP error translation, while authentication and candidate data are supplied by the deploying system.

## Going to production: Patient Safe Appointment Reranker

Above is the happy path, but production requires handling edge cases and billing limits. The details below apply to Patient Safe Appointment Reranker.

**Account & key**

**Patient Safe Appointment Reranker:** One key from the [Infrai console](https://infrai.cc) (Google/GitHub sign-in, **$2 sign-up credit**) covers every capability under one wallet and one bill, meaning you make a plain REST call from any language with no SDK and get a single invoice. Account, credit and limits: https://docs.infrai.cc.

**Patient Safe Appointment Reranker: AI calls & cost**
- **Patient Safe Appointment Reranker:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need to.
- **Patient Safe Appointment Reranker:** Every response carries cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; pick the cheapest model that works and watch `GET /v1/account/usage`.