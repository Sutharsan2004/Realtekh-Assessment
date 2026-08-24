import React, { useEffect, useState } from 'react'
import { getAudit } from '../api.js'

function download(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export default function AuditReport({ candidateId, onError }) {
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getAudit(candidateId)
      .then((r) => !cancelled && setReport(r))
      .catch((err) => onError(err.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [candidateId])

  if (loading) return <div className="card">Loading audit report…</div>
  if (!report) return <div className="card">No audit report available.</div>

  return (
    <div className="card">
      <div className="audit-header">
        <h2>Audit Report — {report.job_title}</h2>
        <button onClick={() => download(`audit_${report.candidate_id}.json`, report)}>
          Export as JSON
        </button>
      </div>

      <p className="disclaimer">{report.disclaimer}</p>

      {report.ai_evaluation.match_summary?.paragraph && (
        <section className="match-summary">
          <h3>Resume–JD Match Summary</h3>
          <p>{report.ai_evaluation.match_summary.paragraph}</p>
          <div className="summary-columns">
            <SummaryList title="Key strengths" items={report.ai_evaluation.match_summary.strengths} />
            <SummaryList title="Gaps to review" items={report.ai_evaluation.match_summary.gaps} />
            <SummaryList title="Recent-experience findings" items={report.ai_evaluation.match_summary.recency_findings} />
          </div>
          {report.ai_evaluation.score_breakdown && (
            <p className="score-breakdown">
              <strong>Score breakdown:</strong> Recency {report.ai_evaluation.score_breakdown.recency ?? 'N/A'} / 100
              {' '}× {Math.round((report.ai_evaluation.weights_used.recency || 0) * 100)}% =
              {' '}{report.ai_evaluation.score_breakdown.recency_weighted_points ?? 'N/A'} final-score points.
              {' '}Only categories present in the JD are included in the normalised score.
            </p>
          )}
        </section>
      )}

      <h3>Requirement-by-Requirement AI Evaluation</h3>
      <table className="req-table">
        <thead>
          <tr>
            <th>Requirement</th>
            <th>Type</th>
            <th>Category</th>
            <th>Status</th>
            <th>Resume Evidence</th>
            <th>JD Evidence</th>
            <th>Recency</th>
            <th>Recency Insight</th>
            <th>Score</th>
          </tr>
        </thead>
        <tbody>
          {report.ai_evaluation.requirements.map((r, i) => (
            <tr key={i}>
              <td>{r.requirement_text}</td>
              <td>{r.requirement_type}</td>
              <td>{r.category}</td>
              <td><span className={`badge badge-${r.resume_status}`}>{r.resume_status}</span></td>
              <td>{r.resume_evidence || '—'}</td>
              <td>{r.jd_evidence || '—'}</td>
              <td>{r.recency_status ? <span className={`badge badge-${r.recency_status}`}>{r.recency_status.replace('_', ' ')}</span> : 'N/A'}</td>
              <td>{r.recency_insight || r.recency_evidence || 'N/A'}</td>
              <td>{r.score}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p>
        <strong>Final Score:</strong> {report.ai_evaluation.final_score} &nbsp;|&nbsp;
        <strong>AI Recommendation:</strong> {report.ai_evaluation.recommendation}
      </p>

      <h3>Stage-by-Stage Comparison</h3>
      {report.stage_comparisons.length === 0 && <p>No reached decisions yet to compare.</p>}
      {report.stage_comparisons.map((c) => (
        <div key={c.stage} className={`comparison-card result-${c.result}`}>
          <h4>
            {c.stage.toUpperCase()} — <span className="result-label">{c.result.replace('_', ' ')}</span>
          </h4>
          <p>
            AI: <strong>{c.ai_recommendation}</strong> vs Human: <strong>{c.human_decision}</strong>{' '}
            (reason: {c.human_reason})
          </p>
          {c.human_decision_reason_summary && (
            <p className="human-insight">{c.human_decision_reason_summary}</p>
          )}
          <p className="justification">{c.ai_justification}</p>
          {c.causes.length > 0 && (
            <p>
              <strong>Possible cause(s):</strong> {c.causes.join(', ')}
            </p>
          )}
          <p>
            <strong>Recommended review action:</strong> {c.recommended_review_action}
          </p>
        </div>
      ))}
    </div>
  )
}

function SummaryList({ title, items = [] }) {
  return (
    <div>
      <strong>{title}</strong>
      {items.length > 0 ? <ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p>None identified.</p>}
    </div>
  )
}
