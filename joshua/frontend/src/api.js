// Every call goes to the app's own origin. In the container nginx proxies
// /api to joshua-backend, so there is no CORS handling anywhere on either side.

export class ApiError extends Error {
  constructor(message, { status = 0, errors = [] } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    // The backend returns a flat `errors` array alongside `error` on a 400,
    // one entry per failed field. Kept so forms can put them next to fields.
    this.errors = errors
  }

  // 503 from /api/insights and /api/drift-review means Ollama is unreachable
  // or the model tag was never pulled -- worth telling the user apart from a
  // generic failure, because only one of them is their problem to fix.
  get isLlmUnavailable() {
    return this.status === 503
  }
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(path, options)
  } catch (cause) {
    throw new ApiError(
      'Could not reach the API. The backend may be starting up or down.',
      { status: 0 },
    )
  }

  if (response.status === 204) return null

  const text = await response.text()
  let body = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      // A proxy error page rather than the API: fall through to the status.
    }
  }

  if (!response.ok) {
    throw new ApiError(
      (body && body.error) || `The API returned HTTP ${response.status}.`,
      { status: response.status, errors: (body && body.errors) || [] },
    )
  }

  return body
}

function jsonBody(payload) {
  return {
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }
}

export const getHoldings = () => request('/api/holdings')
export const getHolding = (id) => request(`/api/holdings/${id}`)
export const createHolding = (payload) =>
  request('/api/holdings', { method: 'POST', ...jsonBody(payload) })
export const updateHolding = (id, payload) =>
  request(`/api/holdings/${id}`, { method: 'PUT', ...jsonBody(payload) })
export const deleteHolding = (id) =>
  request(`/api/holdings/${id}`, { method: 'DELETE' })

export const getAllocation = () => request('/api/allocation')
export const getTargets = () => request('/api/targets')
export const putTargets = (targets) =>
  request('/api/targets', { method: 'PUT', ...jsonBody({ targets }) })

export const createInsight = () => request('/api/insights', { method: 'POST' })
export const runDriftReview = () => request('/api/drift-review', { method: 'POST' })
