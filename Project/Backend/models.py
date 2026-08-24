"""
Domain models for the AI Resume Decision Pipeline & Disagreement Auditor.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def new_id() -> str:
    return str(uuid4())


def now() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RequirementType(str, Enum):
    mandatory = "mandatory"
    preferred = "preferred"


class RequirementCategory(str, Enum):
    mandatory = "mandatory"          # core mandatory requirements bucket (35%)
    experience = "experience"        # 25%
    projects = "projects"            # 20%
    preferred = "preferred"          # 10%
    education = "education"          # education / eligibility (10%)


class ResumeStatus(str, Enum):
    supported = "supported"
    partially_supported = "partially_supported"
    not_found = "not_found"
    unclear = "unclear"
    not_applicable = "not_applicable"


class RecencyStatus(str, Enum):
    recent = "recent"                # evidenced in the most recent role(s)
    older = "older"                  # evidenced only in earlier role(s)
    not_found = "not_found"          # not evidenced in work experience
    unclear = "unclear"              # employment chronology/evidence is unclear
    not_applicable = "not_applicable"  # e.g. education-only requirement


class AIRecommendation(str, Enum):
    recommended = "recommended"
    not_recommended = "not_recommended"


class HumanDecision(str, Enum):
    approved = "approved"
    rejected = "rejected"
    pending = "pending"
    not_reached = "not_reached"


class Stage(str, Enum):
    recruiter = "recruiter"
    manager = "manager"
    client = "client"


class ComparisonResult(str, Enum):
    agreement = "agreement"
    disagreement = "disagreement"
    review_required = "review_required"


class DisagreementCause(str, Enum):
    resume_evidence_missing = "resume_evidence_missing"
    resume_evidence_unclear = "resume_evidence_unclear"
    ai_extraction_error_possible = "ai_extraction_error_possible"
    requirement_interpretation_difference = "requirement_interpretation_difference"
    threshold_or_weight_difference = "threshold_or_weight_difference"
    human_criterion_not_in_jd = "human_criterion_not_in_jd"
    human_feedback_missing = "human_feedback_missing"
    insufficient_evidence = "insufficient_evidence"
    manual_review_required = "manual_review_required"
    human_reason_not_evidence_based = "human_reason_not_evidence_based"


# ---------------------------------------------------------------------------
# AI evaluation structures
# ---------------------------------------------------------------------------

class RequirementEvaluation(BaseModel):
    requirement_text: str
    requirement_type: RequirementType
    category: RequirementCategory
    resume_status: ResumeStatus
    resume_evidence: str = ""   # quoted (or paraphrased) from resume; "" if none found
    jd_evidence: str = ""       # quoted (or paraphrased) from JD
    score: float = Field(ge=0, le=100)
    recency_status: RecencyStatus = RecencyStatus.not_applicable
    recency_evidence: str = ""  # roles/dates showing whether evidence is recent
    recency_insight: str = ""   # concise, evidence-based explanation


class EvaluationWeights(BaseModel):
    mandatory: float = 0.30
    experience: float = 0.20
    projects: float = 0.15
    preferred: float = 0.10
    education: float = 0.10
    recency: float = 0.15


class EvaluationThresholds(BaseModel):
    recommended_min: float = 75


class MatchSummary(BaseModel):
    paragraph: str = ""
    strengths: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    recency_findings: List[str] = Field(default_factory=list)


class AIEvaluation(BaseModel):
    id: str = Field(default_factory=new_id)
    created_at: str = Field(default_factory=now)
    requirements: List[RequirementEvaluation]
    final_score: float
    recommendation: AIRecommendation
    comment: str
    weights_used: EvaluationWeights
    thresholds_used: EvaluationThresholds
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    match_summary: MatchSummary = Field(default_factory=MatchSummary)
    notes: List[str] = Field(default_factory=list)   # e.g. degraded-mode notices
    raw_ai_error: Optional[str] = None                # populated on LLM/parse failure


# ---------------------------------------------------------------------------
# Pipeline / decisions
# ---------------------------------------------------------------------------

class DecisionRecord(BaseModel):
    id: str = Field(default_factory=new_id)
    stage: Stage
    decision: HumanDecision
    reason: Optional[str] = None
    reason_provided: bool = False
    created_at: str = Field(default_factory=now)
    superseded: bool = False   # true once a later decision at same stage replaces it


class StageState(BaseModel):
    stage: Stage
    decision: HumanDecision = HumanDecision.pending
    reason: Optional[str] = None
    reason_provided: bool = False
    decided_at: Optional[str] = None


class PipelineState(BaseModel):
    recruiter: StageState
    manager: StageState
    client: StageState
    final_outcome: HumanDecision = HumanDecision.pending


class DecisionRequest(BaseModel):
    stage: Stage
    decision: Literal["approved", "rejected"]
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Comparison / audit
# ---------------------------------------------------------------------------

class StageComparison(BaseModel):
    stage: Stage
    ai_recommendation: AIRecommendation
    human_decision: HumanDecision
    human_reason: str = "reason_not_provided"
    human_decision_reason_summary: str = ""
    result: ComparisonResult
    causes: List[DisagreementCause] = Field(default_factory=list)
    ai_justification: str = ""
    recommended_review_action: str = ""
    ai_evidence: List[str] = Field(default_factory=list)
    jd_criteria: List[str] = Field(default_factory=list)
    resume_evidence: List[str] = Field(default_factory=list)
    agreement_points: List[str] = Field(default_factory=list)
    disagreement_points: List[str] = Field(default_factory=list)


class AuditReport(BaseModel):
    generated_at: str = Field(default_factory=now)
    candidate_id: str
    job_title: str
    ai_evaluation: AIEvaluation
    pipeline: PipelineState
    decision_history: List[DecisionRecord]
    stage_comparisons: List[StageComparison]
    disclaimer: str = (
        "The AI evaluation is advisory only. It never overrides a human decision. "
        "Final hiring decisions rest entirely with human reviewers."
    )


class Candidate(BaseModel):
    id: str = Field(default_factory=new_id)
    created_at: str = Field(default_factory=now)
    job_title: str
    job_description: str
    resume_text: str
    ai_evaluation: AIEvaluation
    pipeline: PipelineState
    decision_history: List[DecisionRecord] = Field(default_factory=list)
