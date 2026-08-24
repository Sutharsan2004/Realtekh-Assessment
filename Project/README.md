# AI Resume Decision Pipeline & Disagreement Auditor

## Stack
- Backend: FastAPI (Python) + Groq LLM
- Frontend: React (Vite)

## Run backend
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # add your GROQ_API_KEY
uvicorn main:app --reload --port 8000
```

## Run frontend
```bash
cd frontend
npm install
npm run dev
```
Frontend runs at http://localhost:5173 and proxies /api to http://localhost:8000.

## Design notes
- `pipeline.py` — deterministic Recruiter→Manager→Client→Final logic. Never touched by the LLM.
- `scoring.py` — deterministic final score + recommendation, computed only from the LLM's structured per-requirement JSON. The LLM never states a score/recommendation directly.
- `comparison.py` — generic agreement/disagreement/review_required engine for any AI/human combination, with fixed-list causes and non-reversing review actions.
- `llm_client.py` — Groq call + strict JSON parsing with a safe manual_review fallback on any parse/network failure.
- Decision history is append-only (`superseded` flag), so editing an earlier stage recalculates downstream stages without destroying history.
- `/api/candidates/{id}/audit` returns the full exportable JSON audit report (candidate, ai_evaluation, pipeline decisions, audit/disagreements, disclaimer).
