"""
Deterministic pipeline logic: Recruiter -> Manager -> Client -> Final outcome.

This is plain application code -- the LLM has no say in pipeline transitions.
"""
from __future__ import annotations

from typing import List, Optional

from models import (
    Stage,
    HumanDecision,
    DecisionRecord,
    StageState,
    PipelineState,
    now,
)


class InvalidTransitionError(Exception):
    pass


def empty_pipeline() -> PipelineState:
    return PipelineState(
        recruiter=StageState(stage=Stage.recruiter),
        manager=StageState(stage=Stage.manager),
        client=StageState(stage=Stage.client),
        final_outcome=HumanDecision.pending,
    )


def validate_transition(pipeline: PipelineState, stage: Stage) -> None:
    """Raise InvalidTransitionError if `stage` cannot currently be decided."""
    if stage == Stage.recruiter:
        return  # recruiter can always be (re)decided; it's the first stage

    if stage == Stage.manager:
        if pipeline.recruiter.decision != HumanDecision.approved:
            raise InvalidTransitionError(
                "Manager cannot decide until Recruiter has approved."
            )
        return

    if stage == Stage.client:
        if not (
            pipeline.recruiter.decision == HumanDecision.approved
            and pipeline.manager.decision == HumanDecision.approved
        ):
            raise InvalidTransitionError(
                "Client can only decide after Recruiter AND Manager approve."
            )
        return


def recompute_pipeline(history: List[DecisionRecord]) -> PipelineState:
    """
    Rebuild the current pipeline state from the full decision history.
    History is append-only and never overwritten; this derives the *current*
    state deterministically, always taking the latest non-superseded record
    per stage as authoritative, then applying stop / not_reached rules.
    """
    latest: dict[Stage, DecisionRecord] = {}
    for record in history:
        if not record.superseded:
            latest[record.stage] = record  # last write wins among non-superseded

    def stage_state(stage: Stage) -> StageState:
        rec = latest.get(stage)
        if rec is None:
            return StageState(stage=stage)
        return StageState(
            stage=stage,
            decision=rec.decision,
            reason=rec.reason,
            reason_provided=rec.reason_provided,
            decided_at=rec.created_at,
        )

    recruiter = stage_state(Stage.recruiter)
    manager = stage_state(Stage.manager)
    client = stage_state(Stage.client)

    # Enforce downstream stop rules regardless of what's stored (e.g. if an
    # earlier decision was just changed, later stages recalculate here).
    if recruiter.decision in (HumanDecision.pending,):
        manager = StageState(stage=Stage.manager, decision=HumanDecision.not_reached)
        client = StageState(stage=Stage.client, decision=HumanDecision.not_reached)
    elif recruiter.decision == HumanDecision.rejected:
        manager = StageState(stage=Stage.manager, decision=HumanDecision.not_reached)
        client = StageState(stage=Stage.client, decision=HumanDecision.not_reached)
    elif recruiter.decision == HumanDecision.approved:
        if manager.decision in (HumanDecision.pending,):
            client = StageState(stage=Stage.client, decision=HumanDecision.not_reached)
        elif manager.decision == HumanDecision.rejected:
            client = StageState(stage=Stage.client, decision=HumanDecision.not_reached)
        elif manager.decision == HumanDecision.approved:
            pass  # client keeps whatever it currently is (pending/approved/rejected)

    # Final outcome
    if recruiter.decision == HumanDecision.rejected:
        final = HumanDecision.rejected
    elif recruiter.decision == HumanDecision.pending:
        final = HumanDecision.pending
    elif manager.decision == HumanDecision.rejected:
        final = HumanDecision.rejected
    elif manager.decision == HumanDecision.pending:
        final = HumanDecision.pending
    elif client.decision == HumanDecision.rejected:
        final = HumanDecision.rejected
    elif client.decision == HumanDecision.pending:
        final = HumanDecision.pending
    elif client.decision == HumanDecision.approved:
        final = HumanDecision.approved
    else:
        final = HumanDecision.pending

    return PipelineState(
        recruiter=recruiter, manager=manager, client=client, final_outcome=final
    )


def apply_decision(
    history: List[DecisionRecord],
    stage: Stage,
    decision: HumanDecision,
    reason: Optional[str],
) -> List[DecisionRecord]:
    """
    Append a new decision record for `stage`. Marks any prior non-superseded
    record for the same stage as superseded (history is preserved, never
    deleted or overwritten in place). Downstream recalculation happens in
    recompute_pipeline().
    """
    current_pipeline = recompute_pipeline(history)
    validate_transition(current_pipeline, stage)

    new_history = list(history)
    for rec in new_history:
        if rec.stage == stage and not rec.superseded:
            rec.superseded = True

    record = DecisionRecord(
        stage=stage,
        decision=decision,
        reason=reason,
        reason_provided=bool(reason and reason.strip()),
        created_at=now(),
    )
    new_history.append(record)
    return new_history
