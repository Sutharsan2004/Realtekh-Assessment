import React, { useState } from 'react'
import EvaluationForm, { INITIAL_FORM_VALUES } from './components/EvaluationForm.jsx'
import PipelineBoard from './components/PipelineBoard.jsx'
import AuditReport from './components/AuditReport.jsx'

export default function App() {
  const [screen, setScreen] = useState('form') // 'form' | 'board' | 'audit'
  const [candidate, setCandidate] = useState(null)
  const [error, setError] = useState(null)
  const [formValues, setFormValues] = useState(INITIAL_FORM_VALUES)

  function goToBoard(cand) {
    setCandidate(cand)
    setError(null)
    setScreen('board')
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>AI Resume Decision Pipeline &amp; Disagreement Auditor</h1>
        <nav>
          <button className={screen === 'form' ? 'active' : ''} onClick={() => setScreen('form')}>
            1. Evaluate
          </button>
          <button
            className={screen === 'board' ? 'active' : ''}
            onClick={() => candidate && setScreen('board')}
            disabled={!candidate}
          >
            2. Pipeline Board
          </button>
          <button
            className={screen === 'audit' ? 'active' : ''}
            onClick={() => candidate && setScreen('audit')}
            disabled={!candidate}
          >
            3. Audit Report
          </button>
        </nav>
      </header>

      {error && <div className="banner error">{error}</div>}

      <main>
        {screen === 'form' && (
          <EvaluationForm
            formValues={formValues}
            setFormValues={setFormValues}
            onEvaluated={goToBoard}
            onError={setError}
          />
        )}
        {screen === 'board' && candidate && (
          <PipelineBoard
            candidate={candidate}
            setCandidate={setCandidate}
            onError={setError}
            onViewAudit={() => setScreen('audit')}
          />
        )}
        {screen === 'audit' && candidate && (
          <AuditReport candidateId={candidate.id} onError={setError} />
        )}
      </main>

      <footer>
        <small>
          Advisory AI only — the AI never overrides a human decision. All final
          hiring outcomes are made by human reviewers.
        </small>
      </footer>
    </div>
  )
}
