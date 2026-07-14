import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, OptionCard, Badge, StageActions } from './primitives'

// ─────────────────────────────────────────────────────────────────────────────
// ActivitiesStage — pick several activities (a LIST, unlike flights/hotels)
// ─────────────────────────────────────────────────────────────────────────────
// Commit payload validates against ActivitiesCommitData:
//   { chosen: [Activity] }   min_length 0 (an empty list is allowed)
//   Activity: { name, description, estimated_cost_usd, duration_hours,
//               category, booking_url? }
//
// MOCK DATA — swapped for a real Claude activities-agent call later.

function mockActivities(city) {
  return [
    { name: `${city} Old Town Walking Tour`, description: 'A guided 2.5-hour stroll through the historic core with a local storyteller.', estimated_cost_usd: 35, duration_hours: 2.5, category: 'culture', booking_url: null },
    { name: 'Rooftop Food Market', description: 'Sample regional dishes from a dozen stalls with skyline views at sunset.', estimated_cost_usd: 40, duration_hours: 2, category: 'food', booking_url: null },
    { name: 'Sunrise Hike & Viewpoint', description: 'An early trek to the best panorama over the city and coastline.', estimated_cost_usd: 20, duration_hours: 4, category: 'outdoor', booking_url: null },
    { name: 'Museum of Modern Art', description: 'Rotating contemporary exhibitions plus a permanent collection of local masters.', estimated_cost_usd: 18, duration_hours: 2, category: 'culture', booking_url: null },
    { name: 'Evening River Cruise', description: 'A relaxed 90-minute boat ride past the illuminated waterfront landmarks.', estimated_cost_usd: 55, duration_hours: 1.5, category: 'leisure', booking_url: null },
    { name: 'Cooking Class with a Local Chef', description: 'Hands-on preparation of three traditional dishes, then sit down to eat.', estimated_cost_usd: 75, duration_hours: 3, category: 'food', booking_url: null },
  ]
}

const CATEGORY_COLOR = {
  culture: '#a78bfa',
  food: '#fb7185',
  outdoor: '#2dd4bf',
  leisure: '#38bdf8',
}

export default function ActivitiesStage({ commit, skip, forward, commitData, stop, transitioning }) {
  const { t } = useTranslation()

  const city = stop?.city ?? ''
  const activities = mockActivities(city)

  // Restore prior selection by matching activity names
  const [selected, setSelected] = useState(() => {
    const prior = commitData?.chosen
    if (!prior?.length) return new Set()
    return new Set(prior.map((a) => a.name))
  })

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