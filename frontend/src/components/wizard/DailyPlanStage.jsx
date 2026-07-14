import React, { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, StageActions, Textarea } from './primitives'

// ─────────────────────────────────────────────────────────────────────────────
// DailyPlanStage — the day-by-day itinerary for one stop
// ─────────────────────────────────────────────────────────────────────────────
// Commit payload validates against DailyPlanCommitData:
//   { day_by_day: [ DayPlan ] }
//   DayPlan: { date, weather_line, activity_names: [str] }
//
// The plan is generated locally from the stop's committed activities + the
// trip dates, distributing activities across days. A free-text box lets the
// user request changes — in this mock version the box is captured but not
// AI-applied; the real free-text editing (Phase D) will send the note to an
// agent and replace day_by_day with the edited result. What's committed is the
// current (possibly edited) day_by_day list.
//
// activity_names reference Activity.name from the same stop's activities
// commit — a loose string reference, since everything lives in JSONB.

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

// Distribute activities across the available days (round-robin, ~2 per day)
function generatePlan(activities, startDate, numDays) {
  const days = []
  const perDay = Math.max(1, Math.ceil(activities.length / Math.max(1, numDays)))

  for (let d = 0; d < numDays; d++) {
    const slice = activities.slice(d * perDay, (d + 1) * perDay)
    days.push({
      date: startDate ? addDays(startDate, d) : `Day ${d + 1}`,
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

export default function DailyPlanStage({ commit, skip, forward, commitData, stop, setupData, transitioning }) {
  const { t } = useTranslation()
  const city = stop?.city ?? ''

  const activities = useMemo(() => activitiesForStop(stop), [stop])
  const numDays = nightsBetween(setupData?.departure_date, setupData?.return_date)

  // Use the prior committed plan if revisiting, else generate a fresh one
  const [plan] = useState(() => {
    if (commitData?.day_by_day?.length) return commitData.day_by_day
    return generatePlan(activities, setupData?.departure_date, numDays)
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