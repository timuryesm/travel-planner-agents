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
// SINGLE-CITY SCOPE. Track 1 has one city, the hub, so every day is in the hub
// and activities come from the hub's activities commit. Multi-city — days that
// move between hub and spokes, activities pulled from each spoke's commit — is
// step 19. This version names the hub city on every DayPlan (the schema now
// requires `city`), which is exactly right for one city and the honest floor
// for more.
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

// Read the chosen activities for this stop from the trip object
function activitiesForStop(stop) {
  if (!stop) return []
  const commit = stop.stage_commits?.find((c) => c.stage === 'activities')
  const chosen = commit?.commit_data?.chosen
  return Array.isArray(chosen) ? chosen : []
}

// Distribute activities across the available days (round-robin, ~2 per day).
// Each DayPlan carries the city (schema requires it) and a weather_line looked
// up by date from the forecast map — empty string when the date isn't covered,
// which the render turns into a neutral dash rather than inventing a line.
function generatePlan(activities, startDate, numDays, city, forecastByDay) {
  const days = []
  const perDay = Math.max(1, Math.ceil(activities.length / Math.max(1, numDays)))

  for (let d = 0; d < numDays; d++) {
    const slice = activities.slice(d * perDay, (d + 1) * perDay)
    const iso = startDate ? addDays(startDate, d) : null
    days.push({
      date: iso ?? `Day ${d + 1}`,
      city,
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

  const activities = useMemo(() => activitiesForStop(stop), [stop])
  const numDays = nightsBetween(setupData?.departure_date, setupData?.return_date)

  const trip = useTripStore((s) => s.trip)

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
        setPlan(generatePlan(activities, setupData?.departure_date, numDays, city, w.forecast_by_day || {}))
        setWeatherState(w.is_seasonal ? 'seasonal' : 'ready')
      })
      .catch(() => {
        if (cancelled) return
        // No forecast — build the plan anyway with blank weather lines. The
        // stage still works; the days just don't show a forecast.
        setPlan(generatePlan(activities, setupData?.departure_date, numDays, city, {}))
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