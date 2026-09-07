// The single place this app talks to the network.
//
// Nothing else in src/ calls fetch. Every request goes to the app's own
// origin: nginx proxies /api to the backend in the container, and the Vite
// dev server proxies it on a laptop, so there is no base URL to configure and
// no CORS preflight in the normal path.

export class ApiError extends Error {
  constructor(message, { status = 0, details = [] } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    // The backend returns `details` alongside `error` on a 400 -- one entry
    // per problem -- so a form can show all of them at once.
    this.details = details
  }

  // 503 from a plan or replan means Ollama is unreachable or the configured
  // model was never pulled. Worth telling apart from a generic failure: it is
  // an infrastructure problem with a known fix, not a bug in the request.
  get isModelUnavailable() {
    return this.status === 503
  }

  get isNotFound() {
    return this.status === 404
  }
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(path, options)
  } catch {
    throw new ApiError('Could not reach the API. The backend may be starting up or down.', {
      status: 0,
    })
  }

  if (response.status === 204) return null

  const text = await response.text()
  let body = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      // An nginx error page rather than the API: fall through to the status.
    }
  }

  if (!response.ok) {
    throw new ApiError(body?.error || `The API returned HTTP ${response.status}.`, {
      status: response.status,
      details: body?.details || [],
    })
  }

  return body
}

const jsonBody = (payload) => ({
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
})

const query = (params) => {
  const search = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null),
  ).toString()
  return search ? `?${search}` : ''
}

// --- Health -----------------------------------------------------------------
export const getHealth = () => request('/health')

// --- Goals ------------------------------------------------------------------
export const listGoals = (filters = {}) => request(`/api/goals${query(filters)}`)
export const getGoal = (id) => request(`/api/goals/${id}`)
export const createGoal = (payload) => request('/api/goals', { method: 'POST', ...jsonBody(payload) })
export const updateGoal = (id, payload) =>
  request(`/api/goals/${id}`, { method: 'PUT', ...jsonBody(payload) })
export const deleteGoal = (id) => request(`/api/goals/${id}`, { method: 'DELETE' })

// --- Steps ------------------------------------------------------------------
export const listSteps = (goalId) => request(`/api/goals/${goalId}/steps`)
export const updateStep = (goalId, stepId, payload) =>
  request(`/api/goals/${goalId}/steps/${stepId}`, { method: 'PUT', ...jsonBody(payload) })
export const deleteStep = (goalId, stepId) =>
  request(`/api/goals/${goalId}/steps/${stepId}`, { method: 'DELETE' })

// --- Contributions ----------------------------------------------------------
export const listContributions = (goalId) => request(`/api/goals/${goalId}/contributions`)
export const createContribution = (goalId, payload) =>
  request(`/api/goals/${goalId}/contributions`, { method: 'POST', ...jsonBody(payload) })

// --- Budget -----------------------------------------------------------------
export const getBudgetSummary = (userId) => request(`/api/budget/summary${query({ user_id: userId })}`)
export const getBudgetSettings = (userId) => request(`/api/budget/settings${query({ user_id: userId })}`)
export const putBudgetSettings = (payload) =>
  request('/api/budget/settings', { method: 'PUT', ...jsonBody(payload) })

// --- The agentic loop -------------------------------------------------------
export const generatePlan = (goalId) => request(`/api/goals/${goalId}/plan`, { method: 'POST' })
export const getProgress = (goalId) => request(`/api/goals/${goalId}/progress`)
export const regeneratePlan = (goalId) => request(`/api/goals/${goalId}/replan`, { method: 'POST' })
export const getAiLog = (goalId) => request(`/api/goals/${goalId}/ai-log`)
