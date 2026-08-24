import React, { useState } from 'react'
import { submitDecision, getCandidate } from '../api.js'

const STAGES = ['recruiter', 'manager', 'client']

function stageLabel(stage) {
  return stage[0].toUpperCase() + stage.slice(1)
}

function topResumeGaps(requirements) {
  return [...requirements]
    .filter((r) => ['not_found', 'unclear', 'partially_supported'].includes(r.resume_status))
    .sort((a, b) => {
      const statusRank = { not_found: 0, unclear: 1, partially_supported: 2 }
      const typeRank = { mandatory: 0, preferred: 1 }
      return (
        (statusRank[a.resume_status] ?? 3) - (statusRank[b.resume_status] ?? 3) ||
        (typeRank[a.requirement_type] ?? 2) - (typeRank[b.requirement_type] ?? 2) ||
        a.score - b.score
      )
    })
    .slice(0, 3)
    .map((r) => r.requirement_text)
}

function importantTerms(text) {
  const stopWords = new Set([
    'about', 'because', 'candidate', 'experience', 'mentioned', 'more',
    'need', 'needs', 'preferred', 'rejected', 'required', 'should',
    'skill', 'skills', 'skillset', 'their', 'with',
  ])
  return new Set(
    (text.toLowerCase().match(/[a-z][a-z0-9+#.-]*/g) || [])
      .filter((word) => word.length >= 4 && !stopWords.has(word))
  )
}

function relatedRequirements(reason, requirements) {
  const terms = importantTerms(reason)
  const lowerReason = reason.toLowerCase()
  const experienceOrSkillFocus = ['experience', 'experienced', 'skill', 'skills', 'skillset', 'hands-on', 'hands on']
    .some((term) => lowerReason.includes(term))

  function matchScore(req) {
    const haystack = [
      req.requirement_text,
      req.jd_evidence,
      req.resume_evidence,
      req.category,
    ].join(' ').toLowerCase()
    let score = [...terms].filter((term) => haystack.includes(term)).length
    if (experienceOrSkillFocus && ['experience', 'preferred'].includes(req.category)) score += 2
    if (['not_found', 'unclear'].includes(req.resume_status)) score += 2
    if (req.resume_status === 'partially_supported') score += 1
    if (req.requirement_type === 'mandatory') score += 1
    return score
  }

  return [...requirements]
    .filter((req) => matchScore(req) > 0)
    .sort((a, b) => matchScore(b) - matchScore(a) || a.score - b.score)
    .slice(0, 3)
}

function reasonFocus(reason, related) {
  const lowerReason = reason.toLowerCase()
  if (['experience', 'hands-on', 'hands on'].some((term) => lowerReason.includes(term))) {
    return related.length > 0
      ? `the depth of experience for ${related[0].requirement_text}`
      : 'the depth of experience requested by the role'
  }
  if (['skill', 'skills', 'skillset'].some((term) => lowerReason.includes(term))) {
    return related.length > 0
      ? `fit against the expected skill set, especially ${related[0].requirement_text}`
      : 'fit against the expected skill set'
  }
  return related.length > 0 ? related[0].requirement_text : 'the recorded reviewer concern'
}

function evidenceNote(requirement) {
  if (requirement.resume_evidence) {
    return `The resume evidence found by AI was: ${requirement.resume_evidence}.`
  }
  if (requirement.resume_status === 'not_found') {
    return 'The AI did not find clear resume evidence for this requirement.'
  }
  return 'The AI found limited or unclear resume evidence for this requirement.'
}

function rejectionReasonInterpretation(label, reason, requirements) {
  const related = relatedRequirements(reason, requirements)
  const focus = reasonFocus(reason, related)

  if (related.length > 0) {
    const primary = related[0]
    return `AI interpretation: ${label}'s rejection appears to focus on ${focus}. The closest JD/resume signal is "${primary.requirement_text}" (${primary.resume_status}). ${evidenceNote(primary)} The reviewer may be applying a stricter bar for practical depth, recency, or role ownership than the AI score captures. This explains the recorded rejection reason without overriding or blaming the reviewer.`
  }

  const gaps = topResumeGaps(requirements)
  if (gaps.length > 0) {
    return `AI interpretation: ${label}'s rejection note says "${reason}". No exact JD item matched that wording, but the strongest possible concern is limited resume evidence for ${gaps.join(', ')}. Treat this as a suggested explanation and ask the reviewer to confirm the exact criterion.`
  }

  return `AI interpretation: ${label}'s rejection note says "${reason}". The AI could not tie it to a specific extracted JD requirement, so the safest action is to ask the reviewer to clarify the exact rejection criterion.`
}

function approvalReasonInterpretation(label, reason, requirements) {
  const related = relatedRequirements(reason, requirements)
  const supporting = related.filter((req) => ['supported', 'partially_supported'].includes(req.resume_status))
  const fallback = [...requirements]
    .filter((req) => ['supported', 'partially_supported'].includes(req.resume_status))
    .sort((a, b) =>
      (a.requirement_type === 'mandatory' ? 0 : 1) - (b.requirement_type === 'mandatory' ? 0 : 1) ||
      (a.resume_status === 'supported' ? 0 : 1) - (b.resume_status === 'supported' ? 0 : 1)
    )
  const evidence = (supporting.length > 0 ? supporting : fallback).slice(0, 2)
  const gaps = topResumeGaps(requirements).slice(0, 2)

  if (evidence.length > 0) {
    const matches = evidence.map((req) => req.requirement_text).join(' and ')
    const proof = evidence.map((req) => req.resume_evidence).filter(Boolean).join(' ')
    const gapNote = gaps.length > 0
      ? ` This approval is supported by those positive signals, but the resume still has gaps for ${gaps.join(' and ')}.`
      : ''
    return `AI interpretation: ${label}'s approval is broadly consistent with the resume evidence for ${matches}.${proof ? ` Evidence noted: ${proof}.` : ''}${gapNote}`
  }

  return `AI interpretation: ${label}'s approval reason says "${reason}", but the AI did not find clear supporting JD-to-resume evidence. Ask the reviewer to record the job-related strengths that informed the approval.`
}

function humanDecisionReasonSummary(stage, state, requirements) {
  const label = stageLabel(stage)
  const reason = state.reason?.trim()

  if (reason) {
    if (state.decision === 'rejected') {
      return rejectionReasonInterpretation(label, reason, requirements)
    }
    return approvalReasonInterpretation(label, reason, requirements)
  }

  if (state.decision === 'rejected') {
    const gaps = topResumeGaps(requirements)
    if (gaps.length > 0) {
      return `Suggested reason: ${label} may have rejected the candidate because the resume has limited evidence for ${gaps.join(', ')}.`
    }
    return `Suggested reason: ${label} rejected the candidate, but no reviewer reason was recorded. Ask the reviewer to document the rejection reason.`
  }

  if (state.decision === 'approved') {
    return `${label} approved the candidate, but no reviewer reason was recorded.`
  }

  return ''
}

function StatusBadge({ status }) {
  return <span className={`badge badge-${status}`}>{status.replace('_', ' ')}</span>
}

function AIStatusBadge({ recommendation }) {
  const rejected = recommendation === 'not_recommended'
  return <span className={`badge badge-${rejected ? 'rejected' : 'approved'}`}>{rejected ? 'Rejected' : 'Recommended'}</span>
}

export default function PipelineBoard({ candidate, setCandidate, onError, onViewAudit }) {
  const [reasons, setReasons] = useState({ recruiter: '', manager: '', client: '' })
  const [busyStage, setBusyStage] = useState(null)

  async function refresh() {
    const fresh = await getCandidate(candidate.id)
    setCandidate(fresh)
  }

  async function decide(stage, decision) {
    onError(null)
    setBusyStage(stage)
    try {
      const result = await submitDecision(candidate.id, stage, decision, reasons[stage])
      setCandidate(result.candidate)
      if (result.duplicate_decision_detected) {
        onError(`Note: this looks like a duplicate of the current ${stage} decision — recorded anyway as a new history entry.`)
      }
    } catch (err) {
      onError(err.message)
    } finally {
      setBusyStage(null)
    }
  }

  const { ai_evaluation, pipeline, decision_history } = candidate

  return (
    <div className="card">
      <h2>{candidate.job_title} — Pipeline Decision Board</h2>

      <div className="ai-summary">
        <strong>AI Result:</strong> <AIStatusBadge recommendation={ai_evaluation.recommendation} />{' '}
        <span>Score: {ai_evaluation.final_score}</span>
        {ai_evaluation.notes.length > 0 && (
          <div className="notes">{ai_evaluation.notes.map((n, i) => <div key={i}>⚠ {n}</div>)}</div>
        )}
      </div>

      {ai_evaluation.match_summary?.paragraph && (
        <section className="match-summary pipeline-reasoning">
          <h3>AI reasoning</h3>
          <p>{ai_evaluation.match_summary.paragraph}</p>
          {ai_evaluation.match_summary.gaps?.length > 0 && (
            <p><strong>Evidence gaps:</strong> {ai_evaluation.match_summary.gaps.join(' | ')}</p>
          )}
          {ai_evaluation.match_summary.recency_findings?.length > 0 && (
            <p><strong>Recency:</strong> {ai_evaluation.match_summary.recency_findings.join(' | ')}</p>
          )}
          {ai_evaluation.score_breakdown && (
            <p className="score-breakdown">
              <strong>Recency score:</strong> {ai_evaluation.score_breakdown.recency}/100,
              {' '}contributing {ai_evaluation.score_breakdown.recency_weighted_points} final-score points after normalising to applicable JD categories.
            </p>
          )}
        </section>
      )}

      <div className="stage-columns">
        {STAGES.map((stage) => {
          const state = pipeline[stage]
          const blocked = state.decision === 'not_reached'
          const humanReasonSummary = humanDecisionReasonSummary(stage, state, ai_evaluation.requirements)
          return (
            <div key={stage} className={`stage-col ${blocked ? 'blocked' : ''}`}>
              <h3>{stageLabel(stage)}</h3>
              <StatusBadge status={state.decision} />
              {state.reason && <p className="reason">Reason: {state.reason}</p>}
              {humanReasonSummary && <p className="reason insight">AI reason insight: {humanReasonSummary}</p>}
              {!state.reason_provided && state.decision !== 'pending' && state.decision !== 'not_reached' && (
                <p className="reason-missing">reason_not_provided</p>
              )}

              {!blocked && (
                <div className="decision-controls">
                  <textarea
                    placeholder="Optional reason..."
                    value={reasons[stage]}
                    onChange={(e) => setReasons({ ...reasons, [stage]: e.target.value })}
                    rows={2}
                  />
                  <div className="btn-row">
                    <button
                      className="approve"
                      disabled={busyStage === stage}
                      onClick={() => decide(stage, 'approved')}
                    >
                      Approve
                    </button>
                    <button
                      className="reject"
                      disabled={busyStage === stage}
                      onClick={() => decide(stage, 'rejected')}
                    >
                      Reject
                    </button>
                  </div>
                </div>
              )}
            </div>
          )
        })}
        <div className="stage-col ai-stage">
          <h3>AI</h3>
          <AIStatusBadge recommendation={ai_evaluation.recommendation} />
          <p className="reason">Reason: {ai_evaluation.comment || 'AI evaluation comment unavailable.'}</p>
        </div>
      </div>

      <div className="final-outcome">
        <strong>Final Outcome:</strong> <StatusBadge status={pipeline.final_outcome} />
      </div>

      <details>
        <summary>Decision History ({decision_history.length})</summary>
        <ul className="history-list">
          {decision_history.map((d) => (
            <li key={d.id} className={d.superseded ? 'superseded' : ''}>
              [{d.created_at}] {d.stage} → {d.decision}
              {d.reason ? ` ("${d.reason}")` : ' (no reason)'}
              {d.superseded ? ' — superseded' : ''}
            </li>
          ))}
        </ul>
      </details>

      <button className="secondary" onClick={onViewAudit}>
        View Audit Report →
      </button>
    </div>
  )
}
