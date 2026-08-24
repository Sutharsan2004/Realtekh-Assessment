from __future__ import annotations

import io
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import store
from models import (
    Candidate,
    AIEvaluation,
    EvaluationWeights,
    EvaluationThresholds,
    DecisionRequest,
    HumanDecision,
    Stage,
    AuditReport,
)
from pipeline import empty_pipeline, apply_decision, recompute_pipeline, InvalidTransitionError
from scoring import (
    build_ai_comment,
    build_match_summary,
    compute_final_score,
    compute_recommendation,
    compute_score_breakdown,
)
from comparison import compare_all_stages
from llm_client import evaluate_resume

app = FastAPI(title="AI Resume Decision Pipeline & Disagreement Auditor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_resume_text(resume_text: Optional[str], file: Optional[UploadFile]) -> str:
    if file is not None and file.filename:
        try:
            content = file.file.read()
            if file.filename.lower().endswith(".pdf"):
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(content))
                text = "\n".join((page.extract_text() or "") for page in reader.pages)
                if not text.strip():
                    raise HTTPException(
                        status_code=400,
                        detail="PDF extraction failed or produced no text (scanned/image-only PDF?).",
                    )
                return text
            else:
                return content.decode("utf-8", errors="ignore")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Resume file extraction failed: {e}")
    if resume_text and resume_text.strip():
        return resume_text
    raise HTTPException(status_code=400, detail="No resume text or file provided.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/evaluate")
async def evaluate(
    job_title: str = Form(...),
    job_description: str = Form(...),
    resume_text: Optional[str] = Form(None),
    resume_file: Optional[UploadFile] = File(None),
    mandatory_weight: float = Form(0.30),
    experience_weight: float = Form(0.20),
    projects_weight: float = Form(0.15),
    preferred_weight: float = Form(0.10),
    education_weight: float = Form(0.10),
    recency_weight: float = Form(0.15),
    recommended_min: float = Form(75),
):
    if not job_title or not job_title.strip():
        raise HTTPException(status_code=400, detail="Job title cannot be empty.")
    if not job_description or not job_description.strip():
        raise HTTPException(status_code=400, detail="Job description cannot be empty.")

    resume = extract_resume_text(resume_text, resume_file)

    weights = EvaluationWeights(
        mandatory=mandatory_weight,
        experience=experience_weight,
        projects=projects_weight,
        preferred=preferred_weight,
        education=education_weight,
        recency=recency_weight,
    )
    thresholds = EvaluationThresholds(recommended_min=recommended_min)

    requirements, error = evaluate_resume(job_title, job_description, resume)
    final_score = compute_final_score(requirements, weights)
    recommendation = compute_recommendation(final_score, requirements, thresholds)
    comment = build_ai_comment(recommendation, requirements)
    score_breakdown = compute_score_breakdown(requirements, weights)
    match_summary = build_match_summary(requirements)

    notes = []
    if error:
        notes.append(f"AI evaluation used fallback data due to an error: {error}")

    ai_eval = AIEvaluation(
        requirements=requirements,
        final_score=final_score,
        recommendation=recommendation,
        comment=comment,
        weights_used=weights,
        thresholds_used=thresholds,
        score_breakdown=score_breakdown,
        match_summary=match_summary,
        notes=notes,
        raw_ai_error=error,
    )

    candidate = Candidate(
        job_title=job_title,
        job_description=job_description,
        resume_text=resume,
        ai_evaluation=ai_eval,
        pipeline=empty_pipeline(),
        decision_history=[],
    )
    store.save(candidate)
    return candidate


@app.get("/api/candidates")
def list_candidates():
    return [
        {
            "id": c.id,
            "job_title": c.job_title,
            "created_at": c.created_at,
            "ai_recommendation": c.ai_evaluation.recommendation,
            "final_score": c.ai_evaluation.final_score,
            "final_outcome": c.pipeline.final_outcome,
        }
        for c in store.list_all()
    ]


@app.get("/api/candidates/{candidate_id}")
def get_candidate(candidate_id: str):
    candidate = store.get(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    return candidate


class DecisionPayload(BaseModel):
    stage: Stage
    decision: str
    reason: Optional[str] = None


@app.post("/api/candidates/{candidate_id}/decision")
def submit_decision(candidate_id: str, payload: DecisionPayload):
    candidate = store.get(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    if payload.decision not in ("approved", "rejected"):
        raise HTTPException(
            status_code=400, detail="decision must be 'approved' or 'rejected'."
        )

    human_decision = HumanDecision(payload.decision)

    # duplicate detection: same stage, same decision, same reason as the
    # current authoritative record -> accept gracefully but flag it
    current_stage_state = getattr(candidate.pipeline, payload.stage.value)
    duplicate = (
        current_stage_state.decision == human_decision
        and (current_stage_state.reason or "") == (payload.reason or "")
    )

    try:
        new_history = apply_decision(
            candidate.decision_history, payload.stage, human_decision, payload.reason
        )
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))

    candidate.decision_history = new_history
    candidate.pipeline = recompute_pipeline(new_history)
    store.save(candidate)

    return {"candidate": candidate, "duplicate_decision_detected": duplicate}


@app.get("/api/candidates/{candidate_id}/audit", response_model=AuditReport)
def get_audit(candidate_id: str):
    candidate = store.get(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    comparisons = compare_all_stages(
        candidate.pipeline,
        candidate.ai_evaluation.requirements,
        candidate.ai_evaluation.recommendation,
    )

    report = AuditReport(
        candidate_id=candidate.id,
        job_title=candidate.job_title,
        ai_evaluation=candidate.ai_evaluation,
        pipeline=candidate.pipeline,
        decision_history=candidate.decision_history,
        stage_comparisons=comparisons,
    )
    return report


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
