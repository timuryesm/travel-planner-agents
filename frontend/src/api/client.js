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
  // 409 is NOT emailTaken any more. _build_context returns it for wizard
  // ordering ("Setup must be completed", "A country must be chosen"), so a
  // blanket mapping told users their email was taken when they'd skipped a
  // step. register() remaps its own 409 — the only place it means that.
  if (status === 409) return 'conflict'
  // 502 = a discovery agent failed upstream. Distinct from serverError so the
  // stage can offer Retry rather than implying the app itself is broken.
  if (status === 502) return 'agentFailed'
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
// 409 here means the email is taken — the one route where that's true.
export async function register(email, password) {
  try {
    const data = await request('/auth/register', {
      method: 'POST',
      body: { email, password },
      auth: false,
    })
    if (data?.access_token) setToken(data.access_token)
    return data
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      throw new ApiError('emailTaken', 409, err.detail)
    }
    throw err
  }
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

// ── Weather endpoint ──────────────────────────────────────────────────────────
// GET /trips/{id}/weather → { city, forecast_by_day, packing_tips, is_seasonal }
// forecast_by_day maps "YYYY-MM-DD" → a human line. is_seasonal is true when the
// trip is too far out for a live forecast and the lines are last year's proxy.
export function getWeather(tripId) {
  return request(`/trips/${tripId}/weather`, { method: 'GET' })
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
//   getStageOptions(tripId, 'country')                        → [Country]
//   getStageOptions(tripId, 'city', null, { preferenceText }) → [City]
//   getStageOptions(tripId, 'flights')                        → [FlightOption]
//   getStageOptions(tripId, 'accommodation')                  → [HotelOption]
//   getStageOptions(tripId, 'activities', 1)                  → [Activity]
//
// stopIndex is required for activities and omitted everywhere else — under
// hub-and-spoke, flights and accommodation are trip-level (one roundtrip, one
// hotel), so activities is the only stage that repeats per city.
//
// EVERYTHING GOES IN THE BODY, including stop_index. This used to be a query
// param (`?stop_index=N`) while StageOptionsRequest read it from the body, so
// it silently never arrived. Invisible today because only activities uses it;
// it would have surfaced at step 11 as "400 stop_index is required" looking
// like a component bug.
//
// Caching, and why it isn't optional:
//   React 18 StrictMode double-invokes effects in dev, so every stage mount
//   fires this twice. Each call runs a real agent — and with SKYSCANNER_ENABLED
//   / AIRBNB_ENABLED on, each agent run costs quota. We cache the in-flight
//   *promise* per (trip, stage, stop): the second caller joins the first
//   request instead of starting a new one. Once resolved, the cache also means
//   re-visiting a stage doesn't re-run the agent.
//
//   Hints are NOT part of the key. A regenerate or a preference change is a
//   deliberate "ask again", so it forces instead — the new answer replaces the
//   cached one under the same key, which is what a user pressing the button
//   expects. Keying on hints would leave stale results parked under every
//   phrasing the user ever tried.
//
//   Failures are evicted so a transient error isn't cached forever.

const _optionsCache = new Map() // key → Promise<options[]>

function _optionsKey(tripId, stage, stopIndex) {
  return `${tripId}:${stage}:${stopIndex ?? '-'}`
}

export function getStageOptions(
  tripId,
  stage,
  stopIndex = null,
  { force = false, exclude = [], preferenceText = null, limit = null } = {}
) {
  const key = _optionsKey(tripId, stage, stopIndex)

  // Any hint means the caller is asking a new question — never serve a cached
  // answer to it.
  const hasHints = exclude.length > 0 || !!preferenceText || limit !== null
  if (!force && !hasHints && _optionsCache.has(key)) {
    return _optionsCache.get(key)
  }

  const body = {}
  if (stopIndex !== null) body.stop_index = stopIndex
  if (exclude.length) body.exclude = exclude
  if (preferenceText) body.preference_text = preferenceText
  if (limit !== null) body.limit = limit

  const pending = request(`/trips/${tripId}/stages/${stage}/options`, {
    method: 'POST',
    body,
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