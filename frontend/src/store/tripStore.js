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
//   fetchTrips()      — GET /trips/  (summaries for the plan list)
//   closeTrip()       — close the open trip, return to the list
//
// Derived selectors (computed, not stored):
//   currentCommit()   — the commit row for the current position
//   currentStop()     — the Stop object for current_stop_index, or null
//   setupData()       — the committed setup payload, or null
//   countryData()     — the committed country payload, or null
//   cityData()        — the committed city list, or null

// ── Trip-creation in-flight guard ────────────────────────────────────────────
// App.jsx auto-creates a trip from an effect guarded by `!trip`. That guard
// reads state which only updates AFTER POST /trips/ returns, so anything that
// re-renders during the request re-fires the effect and mints a second trip —
// a real orphan row in Postgres, not just a wasted call. React 18 StrictMode
// makes this fire every time in dev, but it's a genuine check-then-act race
// that would survive to production; StrictMode only makes it honest.
//
// Holding the in-flight promise here means concurrent callers join the
// existing request instead of starting a new one. Module scope, not store
// state, because a `set()` wouldn't be visible to a caller that's already
// mid-effect in the same synchronous pass.
let _startInFlight = null

export const useTripStore = create((set, get) => ({
  // ── State ──────────────────────────────────────────────────────────────────
  trip: null,
  loading: false,
  transitioning: false,   // true while a transition request is in flight
  error: null,            // i18n key under errors.* or auth.errors.*
  trips: [],              // TripSummaryResponse[] for the plan list
  tripsLoading: false,

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

  // Idempotent while a create is in flight: concurrent callers get the same
  // promise and the same trip. Once it settles the guard clears, so an
  // explicit "new trip" action later still works normally.
  startTrip: async () => {
    if (_startInFlight) return _startInFlight

    _startInFlight = get()
      ._run(() => api.createTrip())
      .finally(() => { _startInFlight = null })

    return _startInFlight
  },

  loadTrip: async (tripId) => {
    return get()._run(() => api.getTrip(tripId))
  },

  // Load the user's trip summaries for the plan list. Kept separate from
  // `trip`: the list is summaries (id, destination, status), the open trip is
  // the full state. Fetching the list must never clobber an open trip.
  fetchTrips: async () => {
    set({ tripsLoading: true, error: null })
    try {
      const trips = await api.listTrips()
      set({ trips, tripsLoading: false })
      return trips
    } catch (err) {
      const code =
        err?.code === 'sessionExpired' ? 'errors.sessionExpired' :
        err?.code === 'networkError'   ? 'auth.errors.networkError' :
                                         'errors.generic'
      set({ error: code, tripsLoading: false })
      throw err
    }
  },

  // Delete one or several trips, then refresh the list. Parallel per-id calls
  // rather than a bulk endpoint — N is small and the semantics stay standard.
  // allSettled, not all: one failed delete (e.g. already gone) shouldn't stop
  // the rest, and the refetch shows the true remaining state either way.
  deleteTrips: async (ids) => {
    set({ tripsLoading: true, error: null })
    try {
      await Promise.allSettled(ids.map((id) => api.deleteTrip(id)))
      // If the open trip was among them, close it — it no longer exists.
      const open = get().trip
      if (open && ids.includes(open.id)) set({ trip: null })
    } finally {
      await get().fetchTrips().catch(() => {})
    }
  },
 
  // Close the open trip and return to the plan list. NOT a wizard action: it
  // touches no commit and no position, it just stops showing the wizard. The
  // trip is untouched on the server and resumes exactly where it was.
  //
  // Distinct from clearTrip(), which is for logout — that also drops the trips
  // list, because the next user must not see the previous one's plans.
  closeTrip: () => set({ trip: null, error: null }),

  clearTrip: () => {
    _startInFlight = null
    set({ trip: null, trips: [], error: null })
  },

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

  // The hub stop — stops[0], the city you fly into and stay in. Distinct from
  // currentStop(): the hub is fixed for the whole trip, while currentStop()
  // follows the wizard's position and is null on trip-level stages. Flights and
  // accommodation are trip-level now (one roundtrip, one hotel), so they can't
  // read the hub from currentStop() — it's null while they're on screen. They
  // read it here instead.
  //
  // Null until the city stage commits and creates the stops. The components
  // guard on it: no hub yet means the wizard shouldn't be on those stages, but
  // a guarded null renders a safe empty state instead of throwing.
  hubStop: () => {
    const { trip } = get()
    if (!trip) return null
    return trip.stops.find((s) => s.stop_index === 0) ?? null
  },

  hubCity: () => {
    return get().hubStop()?.city ?? null
  },

  // The committed setup payload — needed by later stages (dates, travelers, budget)
  setupData: () => {
    const { trip } = get()
    if (!trip) return null
    const c = trip.trip_stage_commits.find((s) => s.stage === 'setup')
    return c?.commit_data ?? null
  },

  // The committed country — { country: { name, why_chosen_summary,
  // climate_note, safety_note } }. CityStage needs the name for its subtitle.
  countryData: () => {
    const { trip } = get()
    if (!trip) return null
    const c = trip.trip_stage_commits.find((s) => s.stage === 'country')
    return c?.commit_data ?? null
  },

  // The committed city list — { cities: [City] }, cities[0] is the hub.
  // Replaces destinationData(), which read the 'destination' stage: that stage
  // no longer exists, so it had been returning null for every trip.
  cityData: () => {
    const { trip } = get()
    if (!trip) return null
    const c = trip.trip_stage_commits.find((s) => s.stage === 'city')
    return c?.commit_data ?? null
  },
}))

export default useTripStore