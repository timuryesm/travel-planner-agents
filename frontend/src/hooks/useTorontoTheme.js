import { useEffect, useState, useCallback, useRef } from 'react'

// ─────────────────────────────────────────────────────────────────────────────
// useTorontoTheme — drives day/night from Toronto's actual clock
// ─────────────────────────────────────────────────────────────────────────────
// The background represents Toronto, so the sky should match Toronto's time,
// not the visitor's local time. A user in Paris at 3am still sees the CN Tower
// at night the way it actually looks in Toronto right then.
//
// Behaviour:
//   - On mount, reads the current hour in America/Toronto and picks day/night.
//   - Schedules a timer that fires exactly at the next transition boundary
//     (06:00 or 20:00 Toronto time) so the switch happens automatically
//     mid-session without polling.
//   - A manual toggle overrides auto-detection and persists to localStorage.
//     While overridden, the auto-timer is paused; clearing the override
//     resumes automatic behaviour.
//
// Returns: { mode, toggleMode, isAuto, resetToAuto }
//   mode        — 'day' | 'night'
//   toggleMode  — flip day<->night, switches to manual and persists
//   isAuto      — true when mode is following Toronto's clock
//   resetToAuto — clear the manual override, snap back to Toronto time

const DAY_START_HOUR = 6     // 06:00 Toronto → day begins
const NIGHT_START_HOUR = 20  // 20:00 Toronto → night begins

const STORAGE_KEY = 'tp-theme-override'   // 'day' | 'night' | absent

// ── Get the current hour (0–23) in Toronto, regardless of the user's timezone ──
function getTorontoHour() {
  // Intl gives us Toronto's wall-clock hour directly, handling DST for us.
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Toronto',
    hour: 'numeric',
    hour12: false,
  }).formatToParts(new Date())

  const hourPart = parts.find((p) => p.type === 'hour')
  let hour = hourPart ? parseInt(hourPart.value, 10) : 0
  // Intl can return "24" for midnight in hour12:false — normalise to 0.
  if (hour === 24) hour = 0
  return hour
}

// ── Full minute+hour in Toronto, used to compute ms until next transition ──
function getTorontoNow() {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Toronto',
    hour: 'numeric',
    minute: 'numeric',
    second: 'numeric',
    hour12: false,
  }).formatToParts(new Date())

  const get = (t) => {
    const p = parts.find((x) => x.type === t)
    return p ? parseInt(p.value, 10) : 0
  }
  let hour = get('hour')
  if (hour === 24) hour = 0
  return { hour, minute: get('minute'), second: get('second') }
}

function modeForHour(hour) {
  return hour >= DAY_START_HOUR && hour < NIGHT_START_HOUR ? 'day' : 'night'
}

// ── Milliseconds from "now in Toronto" until the next 06:00 or 20:00 boundary ──
function msUntilNextTransition() {
  const { hour, minute, second } = getTorontoNow()
  const secondsNow = hour * 3600 + minute * 60 + second

  const dayStart = DAY_START_HOUR * 3600
  const nightStart = NIGHT_START_HOUR * 3600
  const fullDay = 24 * 3600

  let nextBoundary
  if (secondsNow < dayStart) {
    nextBoundary = dayStart
  } else if (secondsNow < nightStart) {
    nextBoundary = nightStart
  } else {
    nextBoundary = fullDay + dayStart   // tomorrow's 06:00
  }

  // +1s cushion so we're safely past the boundary when the timer fires
  return (nextBoundary - secondsNow + 1) * 1000
}

function readOverride() {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return v === 'day' || v === 'night' ? v : null
  } catch {
    return null
  }
}

export function useTorontoTheme() {
  // Manual override ('day'|'night') or null when following Toronto's clock
  const [override, setOverride] = useState(readOverride)
  // The auto-computed mode from Toronto time
  const [autoMode, setAutoMode] = useState(() => modeForHour(getTorontoHour()))

  const timerRef = useRef(null)

  // ── Schedule the next automatic transition ──
  // Reschedules itself each time it fires. Runs only while not overridden.
  useEffect(() => {
    if (override !== null) {
      // Manual override active — no auto-timer.
      if (timerRef.current) clearTimeout(timerRef.current)
      return
    }

    function scheduleNext() {
      const delay = msUntilNextTransition()
      timerRef.current = setTimeout(() => {
        setAutoMode(modeForHour(getTorontoHour()))
        scheduleNext()   // chain the next transition
      }, delay)
    }

    // Sync immediately in case time passed since mount, then schedule.
    setAutoMode(modeForHour(getTorontoHour()))
    scheduleNext()

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [override])

  // ── Re-sync when the tab regains focus ──
  // A backgrounded tab may have its timers throttled; on return, recompute.
  useEffect(() => {
    function onVisible() {
      if (document.visibilityState === 'visible' && override === null) {
        setAutoMode(modeForHour(getTorontoHour()))
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [override])

  const mode = override ?? autoMode
  const isAuto = override === null

  // ── Manual toggle: flip current mode, persist, switch to manual ──
  const toggleMode = useCallback(() => {
    const next = mode === 'night' ? 'day' : 'night'
    setOverride(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* localStorage unavailable (private mode) — override still works in-memory */
    }
  }, [mode])

  // ── Clear override, snap back to Toronto's clock ──
  const resetToAuto = useCallback(() => {
    setOverride(null)
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch {
      /* ignore */
    }
    setAutoMode(modeForHour(getTorontoHour()))
  }, [])

  return { mode, toggleMode, isAuto, resetToAuto }
}

export default useTorontoTheme