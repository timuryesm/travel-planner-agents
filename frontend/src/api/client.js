// ─────────────────────────────────────────────────────────────────────────────
// API client — the single gateway to the FastAPI backend
// ─────────────────────────────────────────────────────────────────────────────
// Every network call to the backend goes through here. Responsibilities:
//   - Read the base URL from VITE_API_BASE_URL (.env), default localhost:8000
//   - Inject the JWT as `Authorization: Bearer` on authenticated requests
//   - Store / retrieve / clear the token in localStorage
//   - Normalise errors into a typed ApiError the UI can map to i18n messages
//   - Surface 401 by clearing the token and tagging the error 'sessionExpired'
//     so the app can redirect to the auth screen
//
// The endpoint functions mirror the Phase B routes 1:1:
//   register, login            → /auth/*
//   createTrip, listTrips,
//   getTrip, transition        → /trips/*

const BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') || 'http://localhost:8000'

const TOKEN_KEY = 'tp-token'

// ── Token storage ─────────────────────────────────────────────────────────────

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token) {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    /* private mode — token lives only in memory for this session */
  }
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* ignore */
  }
}

// ── Error type ────────────────────────────────────────────────────────────────
// `code` is a stable string the UI maps to an i18n key; `detail` is the raw
// server message (useful for debugging, not shown to users directly).

export class ApiError extends Error {
  constructor(code, status, detail) {
    super(detail || code)
    this.name = 'ApiError'
    this.code = code       // 'invalidCredentials' | 'emailTaken' | 'sessionExpired' | ...
    this.status = status   // HTTP status, or 0 for network failure
    this.detail = detail
  }
}

// Map an HTTP response to a stable error code the UI can translate.
function codeForResponse(status, detail) {
  if (status === 401) return 'sessionExpired'
  if (status === 409) return 'emailTaken'
  if (status === 400 || status === 422) return 'validation'
  if (status >= 500) return 'serverError'
  // Some auth failures come back as 401 with a specific detail; the login
  // route returns 401 for bad credentials, which we treat distinctly only
  // in the login function below (see there).
  return 'generic'
}

// ── Core request helper ───────────────────────────────────────────────────────

async function request(path, { method = 'GET', body, auth = true, form = false } = {}) {
  const headers = {}
  const opts = { method, headers }

  if (auth) {
    const token = getToken()
    if (token) headers['Authorization'] = `Bearer ${token}`
  }

  if (body !== undefined) {
    if (form) {
      // OAuth2 login expects application/x-www-form-urlencoded
      headers['Content-Type'] = 'application/x-www-form-urlencoded'
      opts.body = new URLSearchParams(body).toString()
    } else {
      headers['Content-Type'] = 'application/json'
      opts.body = JSON.stringify(body)
    }
  }

  let res
  try {
    res = await fetch(`${BASE_URL}${path}`, opts)
  } catch {
    // Network-level failure (server down, no connection, CORS block)
    throw new ApiError('networkError', 0, 'Network request failed')
  }

  // 401 → token is stale/invalid; clear it so the app redirects to auth
  if (res.status === 401) {
    clearToken()
  }

  // Parse body — may be empty for some responses
  let data = null
  const text = await res.text()
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { detail: text }
    }
  }

  if (!res.ok) {
    const detail = data?.detail
    // FastAPI validation errors come back as an array under `detail`
    const detailStr = Array.isArray(detail)
      ? detail.map((d) => d.msg).join('; ')
      : detail
    throw new ApiError(codeForResponse(res.status, detailStr), res.status, detailStr)
  }

  return data
}

// ── Auth endpoints ────────────────────────────────────────────────────────────

// POST /auth/register  → { access_token, token_type, user_id, email }
export async function register(email, password) {
  const data = await request('/auth/register', {
    method: 'POST',
    body: { email, password },
    auth: false,
  })
  if (data?.access_token) setToken(data.access_token)
  return data
}

// POST /auth/login  (form-encoded: username=email, password)
// The backend returns 401 for bad credentials — remap that specific case to
// 'invalidCredentials' rather than the generic 'sessionExpired'.
export async function login(email, password) {
  try {
    const data = await request('/auth/login', {
      method: 'POST',
      body: { username: email, password },
      auth: false,
      form: true,
    })
    if (data?.access_token) setToken(data.access_token)
    return data
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      throw new ApiError('invalidCredentials', 401, err.detail)
    }
    throw err
  }
}

export function logout() {
  clearToken()
}

// ── Trip endpoints ────────────────────────────────────────────────────────────

// POST /trips/  → TripDetailResponse
export function createTrip() {
  return request('/trips/', { method: 'POST' })
}

// GET /trips/  → TripSummaryResponse[]
export function listTrips() {
  return request('/trips/', { method: 'GET' })
}

// GET /trips/{id}  → TripDetailResponse
export function getTrip(tripId) {
  return request(`/trips/${tripId}`, { method: 'GET' })
}

// POST /trips/{id}/transition  → TripDetailResponse
// action is one of the discriminated-union shapes the backend expects:
//   { action: 'COMMIT', commit_type, data, self_provided_text? }
//   { action: 'SKIP' }
//   { action: 'FORWARD' }
//   { action: 'BACK', target_stage, target_stop_index }
export async function transition(tripId, action) {
  const data = await request(`/trips/${tripId}/transition`, {
    method: 'POST',
    body: action,
  })
  // A BACK triggers backend cascade-invalidate of downstream stages; their
  // cached options were computed from commit state that no longer holds.
  if (action?.action === 'BACK') {
    invalidateStageOptions(tripId)
  }
  return data
}

// ── Stage options endpoint ────────────────────────────────────────────────────
// Runs the matching Phase A agent for a wizard stage and returns proposed
// options shaped for that stage's commit payload.
//
//   getStageOptions(tripId, 'destination')          → [Destination]
//   getStageOptions(tripId, 'flights', 0)           → [FlightOption]
//   getStageOptions(tripId, 'accommodation', 0)     → [HotelOption]
//   getStageOptions(tripId, 'activities', 1)        → [Activity]
//
// stopIndex is required for flights / accommodation / activities, omitted for
// destination. Returns the `options` array from the response.
//
// Caching, and why it isn't optional:
//   React 18 StrictMode double-invokes effects in dev, so every stage mount
//   fires this twice. Each call runs a real agent — and with SKYSCANNER_ENABLED
//   / AIRBNB_ENABLED on, each agent run costs quota. We cache the in-flight
//   *promise* per (trip, stage, stop): the second caller joins the first
//   request instead of starting a new one. Once resolved, the cache also means
//   re-visiting a stage doesn't re-run the agent.
//
//   Failures are evicted so a transient error isn't cached forever.
//   Pass { force: true } to deliberately re-run an agent (a "refresh options"
//   button), and call invalidateStageOptions() when commit state changes make
//   the cached options stale — see transition() below.

const _optionsCache = new Map() // key → Promise<options[]>

function _optionsKey(tripId, stage, stopIndex) {
  return `${tripId}:${stage}:${stopIndex ?? '-'}`
}

export function getStageOptions(tripId, stage, stopIndex = null, { force = false } = {}) {
  const key = _optionsKey(tripId, stage, stopIndex)

  if (!force && _optionsCache.has(key)) {
    return _optionsCache.get(key)
  }

  const qs = stopIndex !== null ? `?stop_index=${stopIndex}` : ''
  const pending = request(`/trips/${tripId}/stages/${stage}/options${qs}`, {
    method: 'POST',
  })
    .then((data) => data?.options ?? [])
    .catch((err) => {
      _optionsCache.delete(key) // don't cache failures
      throw err
    })

  _optionsCache.set(key, pending)
  return pending
}

// Drop cached options. Call with no stage to clear an entire trip — which is
// what a BACK / cascade-invalidate needs, since downstream stages' inputs
// changed and their old options no longer apply.
export function invalidateStageOptions(tripId, stage = null, stopIndex = null) {
  if (stage === null) {
    for (const key of _optionsCache.keys()) {
      if (key.startsWith(`${tripId}:`)) _optionsCache.delete(key)
    }
    return
  }
  _optionsCache.delete(_optionsKey(tripId, stage, stopIndex))
}

// ── Action builders ───────────────────────────────────────────────────────────
// Small helpers so callers don't hand-assemble action payloads. These mirror
// the CommitAction / SkipAction / ForwardAction / BackAction shapes.

export const actions = {
  commit(commitType, data, selfProvidedText = null) {
    return {
      action: 'COMMIT',
      commit_type: commitType,          // 'chosen' | 'self_provided'
      data,
      self_provided_text: selfProvidedText,
    }
  },
  skip() {
    return { action: 'SKIP' }
  },
  forward() {
    return { action: 'FORWARD' }
  },
  back(targetStage, targetStopIndex = null) {
    return {
      action: 'BACK',
      target_stage: targetStage,
      target_stop_index: targetStopIndex,
    }
  },
}