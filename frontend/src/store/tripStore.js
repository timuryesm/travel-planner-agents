import { create } from 'zustand'
import * as api from '../api/client'

// ─────────────────────────────────────────────────────────────────────────────
// tripStore — the single source of truth for wizard state on the client
// ─────────────────────────────────────────────────────────────────────────────
// Mirrors the backend's TripDetailResponse shape exactly:
//   { id, status, current_stage, current_stop_index, multi_city,
//     created_at, updated_at, trip_stage_commits[], stops[] }
//
// Every action that changes wizard state calls the backend's /transition
// endpoint and replaces the whole trip object with the response. The backend
// is authoritative — we never mutate position or commits locally and hope
// they match. This mirrors the single-chokepoint discipline from the state
// model spec: one place changes state, and it's the server.
//
// Actions:
//   loadTrip(id)      — GET /trips/{id}
//   startTrip()       — POST /trips/
//   commit(type, data, text?)  — COMMIT transition
//   skip()            — SKIP transition
//   forward()         — FORWARD transition
//   back(stage, idx)  — BACK transition (cascade-invalidate)
//
// Derived selectors (computed, not stored):
//   currentCommit()   — the commit row for the current position
//   currentStop()     — the Stop object for current_stop_index, or null
//   setupData()       — the committed setup payload, or null

export const useTripStore = create((set, get) => ({
  // ── State ──────────────────────────────────────────────────────────────────
  trip: null,
  loading: false,
  transitioning: false,   // true while a transition request is in flight
  error: null,            // i18n key under errors.* or auth.errors.*

  // ── Internal: run an async op with loading + error handling ────────────────
  _run: async (fn, { flag = 'loading' } = {}) => {
    set({ [flag]: true, error: null })
    try {
      const trip = await fn()
      set({ trip, [flag]: false })
      return trip
    } catch (err) {
      const code =
        err?.code === 'sessionExpired' ? 'errors.sessionExpired' :
        err?.code === 'networkError'   ? 'auth.errors.networkError' :
                                         'errors.generic'
      set({ error: code, [flag]: false })
      throw err
    }
  },

  // ── Trip lifecycle ─────────────────────────────────────────────────────────

  startTrip: async () => {
    return get()._run(() => api.createTrip())
  },

  loadTrip: async (tripId) => {
    return get()._run(() => api.getTrip(tripId))
  },

  clearTrip: () => set({ trip: null, error: null }),

  // ── Transitions ────────────────────────────────────────────────────────────
  // All four route through the backend's transition() chokepoint. The response
  // is the full updated trip, which replaces local state wholesale.

  commit: async (commitType, data, selfProvidedText = null) => {
    const { trip } = get()
    if (!trip) return
    return get()._run(
      () => api.transition(trip.id, api.actions.commit(commitType, data, selfProvidedText)),
      { flag: 'transitioning' }
    )
  },

  skip: async () => {
    const { trip } = get()
    if (!trip) return
    return get()._run(
      () => api.transition(trip.id, api.actions.skip()),
      { flag: 'transitioning' }
    )
  },

  forward: async () => {
    const { trip } = get()
    if (!trip) return
    return get()._run(
      () => api.transition(trip.id, api.actions.forward()),
      { flag: 'transitioning' }
    )
  },

  back: async (targetStage, targetStopIndex = null) => {
    const { trip } = get()
    if (!trip) return
    return get()._run(
      () => api.transition(trip.id, api.actions.back(targetStage, targetStopIndex)),
      { flag: 'transitioning' }
    )
  },

  // ── Derived selectors ──────────────────────────────────────────────────────

  // The commit row at the trip's current position (trip-level or stop-level)
  currentCommit: () => {
    const { trip } = get()
    if (!trip) return null
    if (trip.current_stop_index === null) {
      return trip.trip_stage_commits.find((c) => c.stage === trip.current_stage) ?? null
    }
    const stop = trip.stops.find((s) => s.stop_index === trip.current_stop_index)
    return stop?.stage_commits.find((c) => c.stage === trip.current_stage) ?? null
  },

  // The Stop object for the current position, or null at trip-level stages
  currentStop: () => {
    const { trip } = get()
    if (!trip || trip.current_stop_index === null) return null
    return trip.stops.find((s) => s.stop_index === trip.current_stop_index) ?? null
  },

  // The committed setup payload — needed by later stages (dates, travelers, budget)
  setupData: () => {
    const { trip } = get()
    if (!trip) return null
    const c = trip.trip_stage_commits.find((s) => s.stage === 'setup')
    return c?.commit_data ?? null
  },

  // The committed destination list — needed to label stops
  destinationData: () => {
    const { trip } = get()
    if (!trip) return null
    const c = trip.trip_stage_commits.find((s) => s.stage === 'destination')
    return c?.commit_data ?? null
  },
}))

export default useTripStore