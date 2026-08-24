"""
Comparison / Disagreement engine.

Computes agreement / disagreement / review_required in application code for
ANY valid combination of AI recommendation and reached human decision -- not
hardcoded to the five demo scenarios (those are just the minimum required
cases the engine must correctly cover).
"""
from __future__ import annotations

import re
from typing import List, Optional

from models import (
    AIRecommendation,
    HumanDecision,
    ComparisonResult,
    DisagreementCause,
    RequirementEvaluation,
    ResumeStatus,
    Stage,
    StageComparison,
)


def _mandatory_evidence_quality(requirements: List[RequirementEvaluation]) -> List[DisagreementCause]:
    causes: List[DisagreementCause] = []
    statuses = [r.resume_status for r in requirements if r.requirement_type.value == "mandatory"]
    if any(s == ResumeStatus.not_found for s in statuses):
        causes.append(DisagreementCause.resume_evidence_missing)
    if any(s == ResumeStatus.unclear for s in statuses):
        causes.append(DisagreementCause.resume_evidence_unclear)
    return causes


def compare_stage(
    stage: Stage,
    ai_recommendation: AIRecommendation,
    human_decision: HumanDecision,
    human_reason: Optional[str],
    requirements: List[RequirementEvaluation],
) -> Optional[StageComparison]:
    """
    Returns None for not_reached stages -- excluded from agreement stats
    entirely, per spec.
    """
    if human_decision == HumanDecision.not_reached:
        return None

    reason_provided = bool(human_reason and human_reason.strip())
    reason_text = human_reason.strip() if reason_provided else "reason_not_provided"

    causes: List[DisagreementCause] = []
    result: ComparisonResult

    # --- Review-required triggers (checked first; they can override an
    # otherwise clean agreement/disagreement classification) -------------
    review_trigger = False
    if human_decision == HumanDecision.pending:
        review_trigger = True
    if not reason_provided and human_decision == HumanDecision.rejected:
        # A rejection with no reason is exactly the "missing reason" case
        causes.append(DisagreementCause.human_feedback_missing)
        review_trigger = True
    elif human_decision == HumanDecision.rejected and not _related_requirements(reason_text, requirements):
        # A reason is only auditable when it can be related to a JD criterion
        # or resume evidence. The reviewer remains the final decision-maker.
        causes.extend([
            DisagreementCause.human_reason_not_evidence_based,
            DisagreementCause.human_criterion_not_in_jd,
        ])
        review_trigger = True

    insufficient_evidence = len(_mandatory_evidence_quality(requirements)) > 0

    if review_trigger:
        result = ComparisonResult.review_required
        if insufficient_evidence:
            causes.extend(_mandatory_evidence_quality(requirements))
            causes.append(DisagreementCause.insufficient_evidence)
    else:
        # --- Clean agreement / disagreement classification ---------------
        ai_positive = ai_recommendation == AIRecommendation.recommended
        ai_negative = ai_recommendation == AIRecommendation.not_recommended
        human_positive = human_decision == HumanDecision.approved
        human_negative = human_decision == HumanDecision.rejected

        if (ai_positive and human_positive) or (ai_negative and human_negative):
            result = ComparisonResult.agreement
        elif (ai_positive and human_negative) or (ai_negative and human_positive):
            result = ComparisonResult.disagreement
            causes.extend(_mandatory_evidence_quality(requirements))
            if not causes:
                causes.append(DisagreementCause.requirement_interpretation_difference)
            causes.append(DisagreementCause.threshold_or_weight_difference)
        else:
            result = ComparisonResult.review_required
            causes.append(DisagreementCause.insufficient_evidence)

    # de-duplicate causes while preserving order
    seen = set()
    deduped = []
    for c in causes:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    causes = deduped

    ai_evidence = [
        f"[{r.category.value}/{r.requirement_type.value}] {r.requirement_text}: "
        f"{r.resume_status.value} — {r.resume_evidence or 'no evidence found'}"
        for r in requirements
    ]
    jd_criteria = [r.jd_evidence for r in requirements if r.jd_evidence]
    resume_evidence = [r.resume_evidence for r in requirements if r.resume_evidence]

    agreement_points: List[str] = []
    disagreement_points: List[str] = []
    if result == ComparisonResult.agreement:
        agreement_points.append(
            f"AI recommendation ({ai_recommendation.value}) matches the {stage.value}'s "
            f"decision ({human_decision.value})."
        )
    elif result == ComparisonResult.disagreement:
        disagreement_points.append(
            f"AI recommendation ({ai_recommendation.value}) conflicts with the {stage.value}'s "
            f"decision ({human_decision.value})."
        )
        if reason_provided:
            disagreement_points.append(f"{stage.value} reason on record: {reason_text}")

    justification = _build_justification(
        stage, ai_recommendation, human_decision, result, causes, requirements
    )
    human_decision_reason_summary = _build_human_decision_reason_summary(
        stage, human_decision, reason_text, reason_provided, requirements
    )
    action = _recommended_action(result, causes)

    return StageComparison(
        stage=stage,
        ai_recommendation=ai_recommendation,
        human_decision=human_decision,
        human_reason=reason_text,
        human_decision_reason_summary=human_decision_reason_summary,
        result=result,
        causes=causes,
        ai_justification=justification,
        recommended_review_action=action,
        ai_evidence=ai_evidence,
        jd_criteria=jd_criteria,
        resume_evidence=resume_evidence,
        agreement_points=agreement_points,
        disagreement_points=disagreement_points,
    )


def _build_human_decision_reason_summary(
    stage: Stage,
    human_decision: HumanDecision,
    reason_text: str,
    reason_provided: bool,
    requirements: List[RequirementEvaluation],
) -> str:
    stage_label = stage.value.capitalize()

    if reason_provided:
        if human_decision == HumanDecision.rejected:
            return _interpret_rejection_reason(stage_label, reason_text, requirements)
        return _interpret_approval_reason(stage_label, reason_text, requirements)

    if human_decision == HumanDecision.rejected:
        suggested_gaps = _top_resume_gaps(requirements)
        if suggested_gaps:
            return (
                f"Suggested reason: {stage_label} may have rejected the candidate because "
                f"the resume has limited evidence for {', '.join(suggested_gaps)}."
            )
        return (
            f"Suggested reason: {stage_label} rejected the candidate, but no reviewer "
            f"reason was recorded. Ask the reviewer to document the rejection reason."
        )

    if human_decision == HumanDecision.approved:
        return (
            f"{stage_label} approved the candidate, but no reviewer reason was recorded."
        )

    return (
        f"{stage_label} decision is {human_decision.value}; no reviewer reason was recorded."
    )


def _interpret_rejection_reason(
    stage_label: str,
    reason_text: str,
    requirements: List[RequirementEvaluation],
) -> str:
    related = _related_requirements(reason_text, requirements)
    focus = _reason_focus(reason_text, related)

    if related:
        primary = related[0]
        evidence_note = _evidence_note(primary)
        return (
            f"AI interpretation: {stage_label}'s rejection appears to focus on {focus}. "
            f"The closest JD/resume signal is '{primary.requirement_text}' "
            f"({primary.resume_status.value}). {evidence_note} The reviewer may be applying "
            f"a stricter bar for practical depth, recency, or role ownership than the AI score "
            f"captures. This explains the recorded rejection reason without overriding or blaming "
            f"the reviewer."
        )

    suggested_gaps = _top_resume_gaps(requirements)
    if suggested_gaps:
        return (
            f"AI interpretation: {stage_label}'s rejection note says '{reason_text}'. "
            f"No exact JD item matched that wording, but the strongest possible concern is limited "
            f"resume evidence for {', '.join(suggested_gaps)}. Treat this as a suggested explanation "
            f"and ask the reviewer to confirm the exact criterion."
        )

    return (
        f"AI interpretation: {stage_label}'s rejection note says '{reason_text}'. "
        f"The AI could not tie it to a specific extracted JD requirement or resume evidence. "
        f"This does not establish that the rejection is invalid, but it is unsupported by the "
        f"recorded evaluation and requires a job-related criterion from the reviewer."
    )


def _interpret_approval_reason(
    stage_label: str,
    reason_text: str,
    requirements: List[RequirementEvaluation],
) -> str:
    related = _related_requirements(reason_text, requirements)
    supporting = [
        req for req in related
        if req.resume_status in (ResumeStatus.supported, ResumeStatus.partially_supported)
    ]
    if not supporting:
        supporting = sorted(
            [
                req for req in requirements
                if req.resume_status in (ResumeStatus.supported, ResumeStatus.partially_supported)
            ],
            key=lambda req: (
                req.requirement_type.value != "mandatory",
                req.resume_status != ResumeStatus.supported,
            ),
        )

    if supporting:
        evidence = supporting[:2]
        match_text = " and ".join(req.requirement_text for req in evidence)
        proof = " ".join(req.resume_evidence for req in evidence if req.resume_evidence)
        gaps = _top_resume_gaps(requirements)[:2]
        gap_note = (
            f" This supports the approval, while evidence gaps remain for {', '.join(gaps)}."
            if gaps else ""
        )
        proof_note = f" Evidence noted: {proof}." if proof else ""
        return (
            f"AI interpretation: {stage_label}'s approval is broadly consistent with "
            f"resume evidence for {match_text}.{proof_note}{gap_note}"
        )

    return (
        f"AI interpretation: {stage_label}'s approval note says '{reason_text}', but the AI "
        f"did not find clear supporting JD-to-resume evidence. Ask the reviewer to record "
        f"the job-related strengths that informed the approval."
    )


def _related_requirements(
    reason_text: str, requirements: List[RequirementEvaluation]
) -> List[RequirementEvaluation]:
    reason_terms = _important_terms(reason_text)
    lower_reason = reason_text.lower()
    experience_or_skill_focus = any(
        term in lower_reason
        for term in ("experience", "experienced", "skill", "skills", "skillset", "hands-on", "hands on")
    )

    def match_score(req: RequirementEvaluation) -> int:
        haystack = " ".join(
            [
                req.requirement_text,
                req.jd_evidence,
                req.resume_evidence,
                req.recency_evidence,
                req.recency_insight,
                req.category.value,
            ]
        ).lower()
        score = sum(1 for term in reason_terms if term in haystack)
        if experience_or_skill_focus and req.category.value in ("experience", "preferred"):
            score += 2
        if req.resume_status in (ResumeStatus.not_found, ResumeStatus.unclear):
            score += 2
        elif req.resume_status == ResumeStatus.partially_supported:
            score += 1
        if req.requirement_type.value == "mandatory":
            score += 1
        return score

    matches = [r for r in requirements if match_score(r) > 0]
    return sorted(matches, key=lambda r: (-match_score(r), r.score))[:3]


def _important_terms(text: str) -> set[str]:
    stop_words = {
        "about", "because", "candidate", "experience", "mentioned", "more",
        "need", "needs", "preferred", "rejected", "required", "should",
        "skill", "skills", "skillset", "their", "with",
    }
    return {
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]*", text.lower())
        if len(word) >= 4 and word not in stop_words
    }


def _reason_focus(reason_text: str, related: List[RequirementEvaluation]) -> str:
    lower_reason = reason_text.lower()
    if any(term in lower_reason for term in ("recency", "recent", "current", "latest")):
        if related:
            return f"recent work evidence for {related[0].requirement_text}"
        return "recent work evidence requested by the role"
    if any(term in lower_reason for term in ("experience", "hands-on", "hands on")):
        if related:
            return f"the depth of experience for {related[0].requirement_text}"
        return "the depth of experience requested by the role"
    if any(term in lower_reason for term in ("skill", "skills", "skillset")):
        if related:
            return f"fit against the expected skill set, especially {related[0].requirement_text}"
        return "fit against the expected skill set"
    if related:
        return related[0].requirement_text
    return "the recorded reviewer concern"


def _evidence_note(requirement: RequirementEvaluation) -> str:
    if requirement.recency_status.value == "older":
        return requirement.recency_insight or "The skill is evidenced only in earlier roles."
    if requirement.recency_status.value == "not_found":
        return requirement.recency_insight or "The skill is not evidenced in work experience."
    if requirement.resume_evidence:
        return f"The resume evidence found by AI was: {requirement.resume_evidence}."
    if requirement.resume_status == ResumeStatus.not_found:
        return "The AI did not find clear resume evidence for this requirement."
    return "The AI found limited or unclear resume evidence for this requirement."


def _top_resume_gaps(requirements: List[RequirementEvaluation]) -> List[str]:
    gap_statuses = {ResumeStatus.not_found, ResumeStatus.unclear, ResumeStatus.partially_supported}
    ranked = sorted(
        [r for r in requirements if r.resume_status in gap_statuses],
        key=lambda r: (
            r.resume_status != ResumeStatus.not_found,
            r.requirement_type.value != "mandatory",
            r.score,
        ),
    )
    return [r.requirement_text for r in ranked[:3]]


def _build_justification(
    stage: Stage,
    ai_recommendation: AIRecommendation,
    human_decision: HumanDecision,
    result: ComparisonResult,
    causes: List[DisagreementCause],
    requirements: List[RequirementEvaluation],
) -> str:
    """
    Evidence-based explanation of the AI's OWN result. Never asserts the
    human reviewer was wrong -- only explains what the AI's structured
    evaluation found and why its output differs (or aligns).
    """
    supporting = [
        r for r in requirements
        if r.resume_status in (ResumeStatus.supported, ResumeStatus.partially_supported)
    ]
    gaps = [
        r for r in requirements
        if r.resume_status in (ResumeStatus.not_found, ResumeStatus.unclear)
        and r.requirement_type.value == "mandatory"
    ]

    if result == ComparisonResult.agreement:
        return (
            f"The AI's {ai_recommendation.value} result is based on {len(supporting)} "
            f"supported/partially-supported requirement(s) against the JD, which aligns "
            f"with the {stage.value}'s {human_decision.value} decision. Agreement between "
            f"the AI and this reviewer is not, by itself, proof of correctness."
        )

    if result == ComparisonResult.disagreement:
        if ai_recommendation == AIRecommendation.recommended:
            basis = (
                f"the resume showed supported or partially-supported evidence for the "
                f"mandatory and weighted requirements evaluated"
            )
        else:
            gap_txt = "; ".join(
                f"'{g.requirement_text}' ({g.resume_status.value})" for g in gaps[:3]
            ) or "one or more mandatory requirements lacking clear resume evidence"
            basis = f"the following mandatory requirement(s) were not clearly met: {gap_txt}"
        cause_txt = ", ".join(c.value for c in causes) if causes else "no specific cause flagged"
        return (
            f"Based on its structured requirement analysis, the AI reached {ai_recommendation.value} "
            f"because {basis}. This differs from the {stage.value}'s {human_decision.value} decision. "
            f"Possible cause(s): {cause_txt}. This is a difference in evaluation, not a claim that the "
            f"{stage.value} was wrong -- both results are presented for human review."
        )

    # review_required
    cause_txt = ", ".join(c.value for c in causes) if causes else "insufficient signal to classify"
    return (
        f"This stage requires manual review rather than an automated agreement/disagreement "
        f"classification. Reason(s): {cause_txt}."
    )


def _recommended_action(result: ComparisonResult, causes: List[DisagreementCause]) -> str:
    if result == ComparisonResult.agreement:
        return "No action required; log for audit trail only."
    if DisagreementCause.human_feedback_missing in causes:
        return "Request the reviewer to record a reason for their decision before closing this stage."
    if DisagreementCause.human_reason_not_evidence_based in causes:
        return "Request a specific job-related rejection reason and supporting JD/resume evidence; route to a senior reviewer before closing this stage."
    if DisagreementCause.human_criterion_not_in_jd in causes:
        return "Ask the reviewer to confirm whether the criterion used should be added to the JD for future evaluations."
    if result == ComparisonResult.review_required:
        return "Route to a senior reviewer for manual adjudication; do not auto-reverse the human decision."
    return "Escalate to a senior reviewer to reconcile the AI/human divergence; do not auto-reverse the human decision."


def compare_all_stages(
    pipeline_states, requirements: List[RequirementEvaluation], ai_recommendation: AIRecommendation
) -> List[StageComparison]:
    results = []
    for stage_state in (pipeline_states.recruiter, pipeline_states.manager, pipeline_states.client):
        cmp = compare_stage(
            stage=stage_state.stage,
            ai_recommendation=ai_recommendation,
            human_decision=stage_state.decision,
            human_reason=stage_state.reason,
            requirements=requirements,
        )
        if cmp is not None:
            results.append(cmp)
    return results
