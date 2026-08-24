"""
Deterministic scoring & recommendation logic.

CRITICAL RULE: the LLM never states a final score or recommendation directly.
This module computes both from the structured per-requirement output only.
"""
from __future__ import annotations

from typing import List

from models import (
    RequirementEvaluation,
    RequirementCategory,
    RecencyStatus,
    ResumeStatus,
    AIRecommendation,
    EvaluationWeights,
    EvaluationThresholds,
    MatchSummary,
)

# resume_status -> per-requirement score contribution (0-100)
STATUS_SCORE = {
    ResumeStatus.supported: 100.0,
    # A keyword/skills-list mention is partial evidence, not proof of hands-on
    # experience. Keep this deliberately below a passing score.
    ResumeStatus.partially_supported: 35.0,
    ResumeStatus.unclear: 15.0,
    ResumeStatus.not_found: 0.0,
    # not_applicable requirements are excluded from scoring entirely
}

RECENCY_SCORE = {
    RecencyStatus.recent: 100.0,
    RecencyStatus.older: 35.0,
    RecencyStatus.unclear: 50.0,
    RecencyStatus.not_found: 0.0,
}


def category_average(requirements: List[RequirementEvaluation], category: RequirementCategory) -> float:
    relevant = [
        r for r in requirements
        if r.category == category and r.resume_status != ResumeStatus.not_applicable
    ]
    if not relevant:
        # Empty JD categories are excluded when weights are normalised below.
        return 0.0
    total = 0.0
    for r in relevant:
        # The status is the deterministic source of truth. A model-supplied
        # numeric estimate must never inflate a keyword-only match.
        base = STATUS_SCORE.get(r.resume_status, 0.0)
        total += base
    return total / len(relevant)


def recency_average(requirements: List[RequirementEvaluation]) -> float:
    """Score whether JD requirements are evidenced in recent work experience."""
    relevant = [r for r in requirements if r.recency_status != RecencyStatus.not_applicable]
    if not relevant:
        return 0.0
    return sum(RECENCY_SCORE.get(r.recency_status, 0.0) for r in relevant) / len(relevant)


def compute_score_breakdown(requirements: List[RequirementEvaluation], weights: EvaluationWeights) -> dict[str, float]:
    scores = {
        RequirementCategory.mandatory: category_average(requirements, RequirementCategory.mandatory),
        RequirementCategory.experience: category_average(requirements, RequirementCategory.experience),
        RequirementCategory.projects: category_average(requirements, RequirementCategory.projects),
        RequirementCategory.preferred: category_average(requirements, RequirementCategory.preferred),
        RequirementCategory.education: category_average(requirements, RequirementCategory.education),
    }
    category_weights = {
        RequirementCategory.mandatory: weights.mandatory,
        RequirementCategory.experience: weights.experience,
        RequirementCategory.projects: weights.projects,
        RequirementCategory.preferred: weights.preferred,
        RequirementCategory.education: weights.education,
    }
    applicable_categories = {
        category for category in RequirementCategory
        if any(
            r.category == category and r.resume_status != ResumeStatus.not_applicable
            for r in requirements
        )
    }
    has_recency = any(r.recency_status != RecencyStatus.not_applicable for r in requirements)
    recency = recency_average(requirements)
    weighted = {
        "mandatory": scores[RequirementCategory.mandatory] * weights.mandatory,
        "experience": scores[RequirementCategory.experience] * weights.experience,
        "projects": scores[RequirementCategory.projects] * weights.projects,
        "preferred": scores[RequirementCategory.preferred] * weights.preferred,
        "education": scores[RequirementCategory.education] * weights.education,
        "recency": recency * weights.recency,
    }
    applicable_weight_total = sum(
        category_weights[category] for category in applicable_categories
    ) + (weights.recency if has_recency else 0.0)
    final = sum(
        weighted[category.value] for category in applicable_categories
    ) + (weighted["recency"] if has_recency else 0.0)
    final = (final / applicable_weight_total) if applicable_weight_total else 0.0
    recency_points = (
        (weighted["recency"] / applicable_weight_total) if has_recency and applicable_weight_total else 0.0
    )
    return {
        "mandatory": round(scores[RequirementCategory.mandatory], 2),
        "experience": round(scores[RequirementCategory.experience], 2),
        "projects": round(scores[RequirementCategory.projects], 2),
        "preferred": round(scores[RequirementCategory.preferred], 2),
        "education": round(scores[RequirementCategory.education], 2),
        "recency": round(recency, 2),
        "recency_weighted_points": round(recency_points, 2),
        "applicable_weight_total": round(applicable_weight_total, 2),
        "final_score": round(final, 2),
    }


def compute_final_score(requirements: List[RequirementEvaluation], weights: EvaluationWeights) -> float:
    return compute_score_breakdown(requirements, weights)["final_score"]


def build_match_summary(requirements: List[RequirementEvaluation]) -> MatchSummary:
    supported = [r for r in requirements if r.resume_status == ResumeStatus.supported]
    partial = [r for r in requirements if r.resume_status == ResumeStatus.partially_supported]
    gaps = [
        r for r in requirements
        if r.requirement_type.value == "mandatory"
        and r.resume_status in (ResumeStatus.not_found, ResumeStatus.unclear)
    ]
    recency_issues = [
        r for r in requirements
        if r.recency_status in (RecencyStatus.older, RecencyStatus.not_found, RecencyStatus.unclear)
    ]
    strengths = [
        f"{r.requirement_text}: {r.resume_evidence or 'supported by the resume'}"
        for r in (supported + partial)[:3]
    ]
    gap_points = [
        f"{r.requirement_text}: {r.resume_evidence or 'no clear resume evidence found'}"
        for r in gaps[:3]
    ]
    recency_points = [
        r.recency_insight or f"{r.requirement_text}: {r.recency_status.value} work evidence."
        for r in recency_issues[:3]
    ]
    coverage = f"{len(supported)} supported and {len(partial)} partially supported requirement(s)"
    gap_text = f" {len(gaps)} mandatory gap(s) need review." if gaps else " No mandatory evidence gaps were identified."
    recency_text = (
        f" Recent-work evidence needs attention for {len(recency_issues)} requirement(s)."
        if recency_issues else " Required skills are evidenced in the most recent role where recency applies."
    )
    return MatchSummary(
        paragraph=f"The resume-JD match shows {coverage}.{gap_text}{recency_text}",
        strengths=strengths,
        gaps=gap_points,
        recency_findings=recency_points,
    )


def compute_recommendation(
    final_score: float,
    requirements: List[RequirementEvaluation],
    thresholds: EvaluationThresholds,
) -> AIRecommendation:
    if final_score >= thresholds.recommended_min:
        return AIRecommendation.recommended
    return AIRecommendation.not_recommended


def build_ai_comment(
    recommendation: AIRecommendation,
    requirements: List[RequirementEvaluation],
) -> str:
    """Create the read-only, evidence-based explanation shown on the pipeline board."""
    if recommendation == AIRecommendation.recommended:
        matches = [
            r.requirement_text for r in requirements
            if r.resume_status in (ResumeStatus.supported, ResumeStatus.partially_supported)
        ]
        evidence = ", ".join(matches[:3]) or "the evaluated job requirements"
        older_only = [r.requirement_text for r in requirements if r.recency_status == RecencyStatus.older]
        recency_note = (
            f" Note: {', '.join(older_only[:2])} is evidenced only in earlier roles."
            if older_only else ""
        )
        return f"Recommended: the resume provides supporting evidence for {evidence}.{recency_note}"

    gaps = [
        r.requirement_text for r in requirements
        if r.requirement_type.value == "mandatory"
        and r.resume_status in (ResumeStatus.not_found, ResumeStatus.unclear)
    ]
    evidence = ", ".join(gaps[:3]) or "enough of the evaluated job requirements"
    stale = [r.requirement_text for r in requirements if r.recency_status in (RecencyStatus.older, RecencyStatus.not_found)]
    recency_note = f" Recent-work evidence is also limited for {', '.join(stale[:2])}." if stale else ""
    return f"Rejected: the resume does not provide clear evidence for {evidence}.{recency_note}"
