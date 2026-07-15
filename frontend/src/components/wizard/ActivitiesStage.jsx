import React, { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, OptionCard, Badge, StageActions } from './primitives'
import { getStageOptions } from '../../api/client'
import useTripStore from '../../store/tripStore'

// ─────────────────────────────────────────────────────────────────────────────
// ActivitiesStage — pick several activities (a LIST, unlike flights/hotels)
// ─────────────────────────────────────────────────────────────────────────────
// Commit payload validates against ActivitiesCommitData:
//   { chosen: [Activity] }   min_length 0 (an empty list is allowed)
//   Activity: { name, description, estimated_cost_usd, duration_hours,
//               category, booking_url? }
//
// Options come from the Claude-backed ActivitiesAgent via
// POST /trips/{id}/stages/activities/options?stop_index=N.
//
// Selection is stored as a Set of activity NAMES, not indices — which is why
// the restore can stay in a useState initialiser here (unlike the other
// stages): it doesn't need the fetched list to exist.

const CATEGORY_COLOR = {
  culture: '#a78bfa',
  food: '#fb7185',
  outdoor: '#2dd4bf',
  leisure: '#38bdf8',
}

export default function ActivitiesStage({ commit, skip, forward, commitData, stop, transitioning }) {
  const { t } = useTranslation()
  const trip = useTripStore((s) => s.trip)

  const city = stop?.city ?? ''

  const [activities, setActivities] = useState([])
  const [loading, setLoading] = useState(true)

  // Restore prior selection by matching activity names
  const [selected, setSelected] = useState(() => {
    const prior = commitData?.chosen
    if (!prior?.length) return new Set()
    return new Set(prior.map((a) => a.name))
  })

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getStageOptions(trip.id, 'activities', stop.stop_index)
      .then((opts) => { if (!cancelled) setActivities(opts) })
      .catch(() => { if (!cancelled) setActivities([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [trip.id, stop.stop_index])

  function toggle(name) {
    setSelected((cur) => {
      const next = new Set(cur)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  function handleConfirm() {
    const chosen = activities.filter((a) => selected.has(a.name))
    commit({ chosen })
  }

  const totalCost = activities
    .filter((a) => selected.has(a.name))
    .reduce((sum, a) => sum + a.estimated_cost_usd, 0)

  if (loading) {
    return (
      <StageCard
        title={t('activities.title')}
        subtitle={t('activities.subtitle', { city })}
      >
        <div className="py-10 text-center text-white/50 text-sm">
          {t('common.loading')}
        </div>
      </StageCard>
    )
  }

  return (
    <StageCard
      title={t('activities.title')}
      subtitle={t('activities.subtitle', { city })}
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {activities.map((a) => {
          const isSelected = selected.has(a.name)
          return (
            <OptionCard key={a.name} selected={isSelected} onClick={() => toggle(a.name)}>
              <div className="flex items-start justify-between gap-2 mb-1.5">
                <h3 className="text-white font-medium text-sm leading-snug">{a.name}</h3>
                <div
                  style={{
                    flexShrink: 0, width: 20, height: 20, borderRadius: 6,
                    border: `2px solid ${isSelected ? '#2dd4bf' : 'rgba(255,255,255,0.25)'}`,
                    background: isSelected ? '#2dd4bf' : 'transparent',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  {isSelected && (
                    <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
                      <path d="M2 6 L5 9 L10 3" stroke="#0a0e1a" strokeWidth="2"
                        strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </div>
              </div>
              <p className="text-white/55 text-xs leading-relaxed mb-3">{a.description}</p>
              <div className="flex items-center gap-2">
                <Badge color={CATEGORY_COLOR[a.category] ?? '#94a3b8'}>{a.category}</Badge>
                <span className="text-white/40 text-xs">
                  {t('activities.duration', { hours: a.duration_hours })}
                </span>
                <span className="text-white/70 text-xs ml-auto font-medium">
                  ${a.estimated_cost_usd}
                </span>
              </div>
            </OptionCard>
          )
        })}
      </div>

      {/* Selection summary */}
      <div className="flex items-center justify-between mt-4 text-sm">
        <span className="text-white/55">
          {t('activities.selected', { count: selected.size })}
        </span>
        {selected.size > 0 && (
          <span className="text-white/70">
            {t('activities.estimatedCost')}: <span className="font-semibold">${totalCost}</span>
          </span>
        )}
      </div>

      <StageActions
        onConfirm={handleConfirm}
        confirmLabel={t('activities.confirmSelection')}
        confirmDisabled={selected.size === 0}
        onSkip={skip}
        onForward={forward}
        transitioning={transitioning}
      />
    </StageCard>
  )
}