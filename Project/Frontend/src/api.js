const BASE = '/api'

async function handle(res) {
  let body
  try {
    body = await res.json()
  } catch {
    body = null
  }
  if (!res.ok) {
    const detail = body?.detail || res.statusText || 'Request failed'
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return body
}

export async function evaluateResume(formData) {
  const res = await fetch(`${BASE}/evaluate`, {
    method: 'POST',
    body: formData,
  })
  return handle(res)
}

export async function listCandidates() {
  const res = await fetch(`${BASE}/candidates`)
  return handle(res)
}

export async function getCandidate(id) {
  const res = await fetch(`${BASE}/candidates/${id}`)
  return handle(res)
}

export async function submitDecision(id, stage, decision, reason) {
  const res = await fetch(`${BASE}/candidates/${id}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stage, decision, reason }),
  })
  return handle(res)
}

export async function getAudit(id) {
  const res = await fetch(`${BASE}/candidates/${id}/audit`)
  return handle(res)
}
