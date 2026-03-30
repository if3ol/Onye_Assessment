# EHR Clinical Data Reconciliation Engine

A full-stack application that uses AI to reconcile conflicting medication records across EHR systems and score patient record data quality.

---

## Quick Start (Local)

### 1. Clone and install
```bash
git clone <your-repo-url>
cd Onye_Assessment
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
```
Open `.env` and fill in two values:
- `APP_API_KEY` — any secret string you choose (clients must send this as `X-API-Key` header)
- `GEMINI_API_KEY` — free key from https://aistudio.google.com/app/apikey

### 3. Run
```bash
uvicorn backend.main:app --reload
```

Open http://localhost:8000 — the dashboard loads automatically.  
API docs: http://localhost:8000/docs

### 4. Run tests
```bash
pytest backend/tests/ -v
```

---



---

## API Endpoints

Both endpoints require the `X-API-Key` header.

### `POST /api/reconcile/medication`
Accepts conflicting medication records from multiple EHR sources. Returns the reconciled medication with confidence score, clinical reasoning, and recommended actions.

### `POST /api/validate/data-quality`
Accepts a patient record. Returns a data quality score (0–100) broken down by completeness, accuracy, timeliness, and clinical plausibility, plus a list of detected issues.

---

## LLM Choice: Google Gemini 1.5 Flash

**Reasons for Choosing**
- Generous free tier — no cost for an assessment project
- `gemini-1.5-flash` is fast (low latency) and handles structured JSON output reliably


**Why not OpenAI or Anthropic?**  
Both require paid API keys with no meaningful free tier at time of writing. For an assessment, Gemini's free tier removes the billing barrier entirely.

---

## Architecture & Design Decisions

### Hybrid AI approach (most important decision)
The reconciliation engine does **not** simply hand the raw data to the LLM and ask it to decide. Instead:

1. **Deterministic pre-scoring** runs first — each source is scored on recency (40%), reliability (40%), and agreement with other sources (20%). The winner is selected algorithmically.
2. **Gemini is called second** — it receives the pre-scored analysis and is asked to *explain* the decision in clinical terms, not make it.

This separation means the system degrades gracefully: if the AI API is unavailable, the endpoint still returns correct deterministic results with a fallback explanation. It also makes the AI's output more consistent because its reasoning is anchored to our pre-computed scores.

### Response caching
Identical API inputs (same prompt hash) are served from an in-memory dict without hitting Gemini again. This eliminates redundant API calls during development and testing. In production, this would be replaced with Redis.

### Layered validation
Pydantic models validate all inputs before any logic runs. This means service functions can assume clean data and focus on business logic rather than defensive checks.

### Modular service layer
Routers contain zero business logic — they only handle HTTP parsing and response serialisation. All logic lives in `services/`, which means it can be tested without spinning up the FastAPI server.

---

## What I'd Improve With More Time

- **Persistent cache** — swap the in-memory dict for Redis so cached responses survive server restarts
- **Webhook support** — emit a POST to a configured URL when a reconciliation is approved/rejected
- **Confidence calibration** — collect approve/reject feedback and use it to tune the scoring weights over time

---

## Estimated Time Spent

| Phase | Time |
|-------|------|
| Architecture planning + scaffold | 2 hrs |
| Reconciliation scoring logic + tests | 3 hrs |
| Gemini integration + caching | 2 hrs |
| Data quality service + tests | 3 hrs |
| Frontend dashboard | 2 hrs |
| README + cleanup | 1 hr |
| **Total** | **~13 hrs** |
