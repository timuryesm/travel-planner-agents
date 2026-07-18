import React, { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, StageActions, Textarea } from './primitives'
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
// loose string reference, since everything lives in JSONB. Real weather
// replaces MOCK_WEATHER in step 12; this stays mock for the prop-shift fix.

function addDays(iso, n) {
  const d = new Date(iso)
  d.setDate(d.getDate() + n)
  return d.toISOString().slice(0, 10)
}

const MOCK_WEATHER = [
  'Sunny, 24 °C', 'Partly cloudy, 22 °C', 'Clear, 26 °C',
  'Light breeze, 23 °C', 'Sunny, 25 °C', 'Scattered clouds, 21 °C',
  'Warm, 27 °C', 'Mild, 20 °C',
]

// Read the chosen activities for this stop from the trip object
function activitiesForStop(stop) {
  if (!stop) return []
  const commit = stop.stage_commits?.find((c) => c.stage === 'activities')
  const chosen = commit?.commit_data?.chosen
  return Array.isArray(chosen) ? chosen : []
}

// Distribute activities across the available days (round-robin, ~2 per day).
// Each DayPlan carries the city — the schema requires it now that a plan can in
// principle move between hub and spokes. Single-city: it's the hub every day.
function generatePlan(activities, startDate, numDays, city) {
  const days = []
  const perDay = Math.max(1, Math.ceil(activities.length / Math.max(1, numDays)))

  for (let d = 0; d < numDays; d++) {
    const slice = activities.slice(d * perDay, (d + 1) * perDay)
    days.push({
      date: startDate ? addDays(startDate, d) : `Day ${d + 1}`,
      city,
      weather_line: MOCK_WEATHER[d % MOCK_WEATHER.length],
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

  // Use the prior committed plan if revisiting, else generate a fresh one
  const [plan] = useState(() => {
    if (commitData?.day_by_day?.length) return commitData.day_by_day
    return generatePlan(activities, setupData?.departure_date, numDays, city)
  })

  const [editNote, setEditNote] = useState('')

  function handleConfirm() {
    // In this mock the plan is committed as-is. Phase D applies editNote via an
    // agent before committing; for now the note is simply ignored on commit.
    commit({ day_by_day: plan })
  }

  return (
    <StageCard
      title={t('dailyPlan.title')}
      subtitle={t('dailyPlan.subtitle', { city })}
    >
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
                {t('dailyPlan.weatherLabel')}: {day.weather_line}
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

      {/* Free-text edit box (captured; AI-applied in Phase D) */}
      <div className="mt-5">
        <label className="block text-white/70 text-xs font-medium mb-1.5">
          {t('dailyPlan.editPlan')}
        </label>
        <Textarea
          value={editNote}
          onChange={setEditNote}
          placeholder={t('dailyPlan.editPlaceholder')}
          rows={2}
        />
      </div>

      <StageActions
        onConfirm={handleConfirm}
        onSkip={skip}
        onForward={forward}
        transitioning={transitioning}
      />
    </StageCard>
  )
}