import React, { useState, useMemo, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, StageActions } from './primitives'
import { getWeather } from '../../api/client'
import useTripStore from '../../store/tripStore'

// ─────────────────────────────────────────────────────────────────────────────
// DailyPlanStage — the day-by-day itinerary for the trip
// ─────────────────────────────────────────────────────────────────────────────
// Commit payload validates against DailyPlanCommitData:
//   { day_by_day: [ DayPlan ] }
//   DayPlan: { date, city, weather_line, activity_names: [str] }
//
// TRIP-LEVEL under hub-and-spoke: one plan for the whole trip, so it reads the
// hub from hubStop() rather than currentStop() (which is null here — the same
// trap that white-screened flights). The plan is built from the hub stop's
// committed activities + the trip dates.
//
// MULTI-CITY (step 19): each day's city is decided by the spoke date ranges.
// A spoke stop carries start_date/end_date (its day-trip dates, mirrored from
// the intercity commit onto the row and now exposed by the API). For each day
// of the trip, if the date falls inside a spoke's range, that day is a day trip
// to that spoke — its city, its activities. Otherwise it's a hub day — hub city,
// hub activities. Single-city trips have no spokes, so every day is the hub,
// exactly as before.
//
// The free-text edit box is captured but not yet AI-applied; real editing lands
// in Phase D. What's committed is the current day_by_day list.
//
// activity_names reference Activity.name from the hub's activities commit — a
// loose string reference, since everything lives in JSONB.
//
// Weather is real now (step 12): GET /trips/{id}/weather returns a per-day
// forecast for the hub, live when the trip is within ~15 days, otherwise a
// seasonal proxy from last year's same dates (is_seasonal=true, lines tagged
// "(typical)"). The plan is built client-side, then each day's weather_line is
// filled from that lookup by DATE. A day with no matching forecast entry (the
// window can exceed the archive's coverage) gets a neutral dash — never a
// fabricated line.

function addDays(iso, n) {
  const d = new Date(iso)
  d.setDate(d.getDate() + n)
  return d.toISOString().slice(0, 10)
}

// Read the chosen activities for one stop from the trip object.
function activitiesForStop(stop) {
  if (!stop) return []
  const commit = stop.stage_commits?.find((c) => c.stage === 'activities')
  const chosen = commit?.commit_data?.chosen
  return Array.isArray(chosen) ? chosen : []
}

// Which stop is a given ISO date in? A spoke if the date falls inside its
// [start_date, end_date] (its day-trip window); otherwise the hub. Spokes are
// checked first so a day trip wins over the hub's default coverage.
function stopForDate(iso, hub, spokes) {
  for (const sp of spokes) {
    if (sp.start_date && sp.end_date && iso >= sp.start_date && iso <= sp.end_date) {
      return sp
    }
  }
  return hub
}

// Build the day-by-day plan. For each day: resolve the day's stop (hub or a
// spoke whose date-range covers it), label the day with that stop's city, and
// draw from that stop's activities. Activities are consumed per city with a
// cursor, so a city's chosen list is distributed across only the days spent
// there — a spoke's activities land on the spoke day(s), the hub's on hub days.
function generatePlan(startDate, numDays, hub, spokes, forecastByDay) {
  const days = []

  // Per-stop activity pool + a cursor, so each city's activities are handed out
  // in order across its own days without repeating across cities.
  const pool = {}
  const cursor = {}
  const allStops = [hub, ...spokes].filter(Boolean)
  for (const st of allStops) {
    pool[st.stop_index] = activitiesForStop(st)
    cursor[st.stop_index] = 0
  }

  // Count how many days each stop gets, to size the per-day slice sensibly.
  const dayStops = []
  for (let d = 0; d < numDays; d++) {
    const iso = startDate ? addDays(startDate, d) : null
    dayStops.push(iso ? stopForDate(iso, hub, spokes) : hub)
  }
  const daysPerStop = {}
  for (const st of dayStops) daysPerStop[st.stop_index] = (daysPerStop[st.stop_index] || 0) + 1

  for (let d = 0; d < numDays; d++) {
    const iso = startDate ? addDays(startDate, d) : null
    const st = dayStops[d]
    const idx = st.stop_index
    const acts = pool[idx] || []
    const perDay = Math.max(1, Math.ceil(acts.length / Math.max(1, daysPerStop[idx] || 1)))
    const slice = acts.slice(cursor[idx], cursor[idx] + perDay)
    cursor[idx] += perDay

    days.push({
      date: iso ?? `Day ${d + 1}`,
      city: st.city,
      weather_line: (iso && forecastByDay[iso]) || '',
      activity_names: slice.map((a) => a.name),
    })
  }
  return days
}

function nightsBetween(depart, ret) {
  if (!depart || !ret) return 3
  const n = Math.round((new Date(ret) - new Date(depart)) / 86400000)
  return n > 0 ? n : 3
}

export default function DailyPlanStage({ commit, skip, forward, commitData, setupData, transitioning }) {
  const { t } = useTranslation()
  const hubStop = useTripStore((s) => s.hubStop)

  // Trip-level: the plan spans the trip, based in the hub. Not currentStop() —
  // null while a trip-level stage renders.
  const stop = hubStop()
  const city = stop?.city ?? ''

  const trip = useTripStore((s) => s.trip)

  // Hub (index 0) + spokes (1..N), sorted. Spokes carry their day-trip dates on
  // start_date/end_date; the plan builder uses them to place each day.
  const spokes = useMemo(
    () => (trip?.stops ?? [])
      .filter((s) => s.stop_index >= 1)
      .sort((a, b) => a.stop_index - b.stop_index),
    [trip]
  )
  const numDays = nightsBetween(setupData?.departure_date, setupData?.return_date)

  // Revisiting a committed plan keeps it verbatim — the user may have edited it,
  // and its weather lines were real when generated. A fresh plan waits for the
  // forecast before it's built, so weather lands on it from the first render.
  const revisiting = !!commitData?.day_by_day?.length
  const [plan, setPlan] = useState(() =>
    revisiting ? commitData.day_by_day : null
  )
  const [weatherState, setWeatherState] = useState('loading') // loading|ready|seasonal|failed

  useEffect(() => {
    if (revisiting) { setWeatherState('ready'); return }
    let cancelled = false
    getWeather(trip.id)
      .then((w) => {
        if (cancelled) return
        setPlan(generatePlan(setupData?.departure_date, numDays, stop, spokes, w.forecast_by_day || {}))
        setWeatherState(w.is_seasonal ? 'seasonal' : 'ready')
      })
      .catch(() => {
        if (cancelled) return
        // No forecast — build the plan anyway with blank weather lines. The
        // stage still works; the days just don't show a forecast.
        setPlan(generatePlan(setupData?.departure_date, numDays, stop, spokes, {}))
        setWeatherState('failed')
      })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trip.id])

  function handleConfirm() {
    // Committed as generated, or as previously committed on revisit. Free-text
    // editing (Phase D) will rewrite the plan before this point later.
    if (!plan) return
    commit({ day_by_day: plan })
  }

  if (!plan) {
    return (
      <StageCard title={t('dailyPlan.title')} subtitle={t('dailyPlan.subtitle', { city })}>
        <div className="py-10 text-center text-white/50 text-sm">
          {t('common.loading')}
        </div>
      </StageCard>
    )
  }

  return (
    <StageCard
      title={t('dailyPlan.title')}
      subtitle={t('dailyPlan.subtitle', { city })}
    >
      {(weatherState === 'seasonal' || weatherState === 'failed') && (
        <p className="text-white/40 text-xs mb-3">
          {weatherState === 'seasonal'
            ? t('dailyPlan.seasonalNote')
            : t('dailyPlan.weatherUnavailable')}
        </p>
      )}
      <div className="flex flex-col gap-3">
        {plan.map((day, i) => (
          <div
            key={i}
            className="rounded-xl p-4"
            style={{
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.10)',
            }}
          >
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-white font-semibold text-sm">
                {t('dailyPlan.day', { number: i + 1 })}
                <span className="text-white/40 font-normal ml-2">{day.date}</span>
              </h3>
              <span className="text-white/45 text-xs">
                {t('dailyPlan.weatherLabel')}: {day.weather_line || '—'}
              </span>
            </div>

            {day.activity_names.length > 0 ? (
              <div className="flex flex-col gap-1.5">
                {day.activity_names.map((name, j) => (
                  <div key={j} className="flex items-center gap-2.5">
                    <span
                      style={{
                        width: 5, height: 5, borderRadius: '50%',
                        background: '#2dd4bf', flexShrink: 0,
                      }}
                    />
                    <span className="text-white/75 text-sm">{name}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-white/35 text-sm italic">—</p>
            )}
          </div>
        ))}
      </div>

      {/* Free-text plan editing (send a note, agent rewrites the plan) is
          Track 3 / Phase D. Omitted here rather than shown as a box that
          discards what you type. */}

      <StageActions
        onConfirm={handleConfirm}
        onSkip={skip}
        onForward={forward}
        transitioning={transitioning}
      />
    </StageCard>
  )
}