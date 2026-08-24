import React, { useState } from 'react'
import { evaluateResume } from '../api.js'

const DEFAULT_WEIGHTS = {
  mandatory_weight: 0.30,
  experience_weight: 0.20,
  projects_weight: 0.15,
  preferred_weight: 0.10,
  education_weight: 0.10,
  recency_weight: 0.15,
}

const DEFAULT_THRESHOLDS = {
  recommended_min: 75,
}

export const INITIAL_FORM_VALUES = {
  jobTitle: '',
  jobDescription: '',
  resumeText: '',
  resumeFile: null,
  weights: DEFAULT_WEIGHTS,
  thresholds: DEFAULT_THRESHOLDS,
  showAdvanced: false,
}

export default function EvaluationForm({ formValues, setFormValues, onEvaluated, onError }) {
  const { jobTitle, jobDescription, resumeText, resumeFile, weights, thresholds, showAdvanced } = formValues
  const [loading, setLoading] = useState(false)

  function update(values) {
    setFormValues((current) => ({ ...current, ...values }))
  }

  const weightSum = Object.values(weights).reduce((a, b) => a + Number(b || 0), 0)

  async function handleSubmit(e) {
    e.preventDefault()
    onError(null)

    if (!jobTitle.trim() || !jobDescription.trim()) {
      onError('Job title and job description are required.')
      return
    }
    if (!resumeText.trim() && !resumeFile) {
      onError('Provide resume text or upload a resume file.')
      return
    }

    const fd = new FormData()
    fd.append('job_title', jobTitle)
    fd.append('job_description', jobDescription)
    if (resumeText.trim()) fd.append('resume_text', resumeText)
    if (resumeFile) fd.append('resume_file', resumeFile)
    Object.entries(weights).forEach(([k, v]) => fd.append(k, v))
    Object.entries(thresholds).forEach(([k, v]) => fd.append(k, v))

    setLoading(true)
    try {
      const candidate = await evaluateResume(fd)
      onEvaluated(candidate)
    } catch (err) {
      onError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>Resume Evaluation</h2>

      <label>
        Job Title
        <input value={jobTitle} onChange={(e) => update({ jobTitle: e.target.value })} placeholder="e.g. Backend Engineer" />
      </label>

      <label>
        Job Description
        <textarea
          rows={8}
          value={jobDescription}
          onChange={(e) => update({ jobDescription: e.target.value })}
          placeholder="Paste the full JD here..."
        />
      </label>

      <label>
        Resume (paste text)
        <textarea
          rows={8}
          value={resumeText}
          onChange={(e) => update({ resumeText: e.target.value })}
          placeholder="Paste resume text here, or upload a PDF below..."
        />
      </label>

      <label>
        Or upload resume (PDF / .txt)
        <input type="file" accept=".pdf,.txt" onChange={(e) => update({ resumeFile: e.target.files[0] || null })} />
        {resumeFile && <small>Selected: {resumeFile.name}</small>}
      </label>

      <button type="button" className="link-btn" onClick={() => update({ showAdvanced: !showAdvanced })}>
        {showAdvanced ? 'Hide' : 'Show'} advanced weights &amp; thresholds
      </button>

      {showAdvanced && (
        <div className="advanced-grid">
          <fieldset>
            <legend>Category Weights (sum ≈ 1.0, currently {weightSum.toFixed(2)})</legend>
            {Object.entries(weights).map(([k, v]) => (
              <label key={k} className="inline">
                {k.replace('_weight', '')}
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  max="1"
                  value={v}
                  onChange={(e) => update({ weights: { ...weights, [k]: Number(e.target.value) } })}
                />
              </label>
            ))}
          </fieldset>
          <fieldset>
            <legend>Thresholds</legend>
            <label className="inline">
              recommended min
              <input
                type="number"
                value={thresholds.recommended_min}
                onChange={(e) => update({ thresholds: { ...thresholds, recommended_min: Number(e.target.value) } })}
              />
            </label>
          </fieldset>
        </div>
      )}

      <button type="submit" disabled={loading}>
        {loading ? 'Evaluating…' : 'Run AI Evaluation'}
      </button>
    </form>
  )
}
