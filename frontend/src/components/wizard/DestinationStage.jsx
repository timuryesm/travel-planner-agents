import React, { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, OptionCard, Badge, StageActions } from './primitives'
import { getStageOptions } from '../../api/client'
import useTripStore from '../../store/tripStore'

// ─────────────────────────────────────────────────────────────────────────────
// DestinationStage — pick one city, or several when multi_city is on
// ─────────────────────────────────────────────────────────────────────────────
// Commit payload must validate against DestinationCommitData (Phase B):
//   { destinations: [ { city, country, why_chosen_summary,
//                       season_note, safety_note }, ... ] }   min_length=1
//
// This is the stage that RESTRUCTURES navigation: committing N destinations
// causes the backend to create N Stop rows, each with four unvisited
// StopStageCommit rows. The sidebar's per-city groups appear immediately
// after this commit lands.
//
// Selection mode is driven by setupData.multi_city:
//   false → radio behaviour, exactly one city
//   true  → multi-select, ordered by pick order (index i → stop_index i)
//
// Options now come from the DestinationAgent via
// POST /trips/{id}/stages/destination/options (no stop_index — there are no
// stops yet; creating them is what this stage's commit does).
//
// handleConfirm re-picks the five DestinationCommitData fields explicitly
// rather than committing whole option objects: the agent's model_dump may
// carry extra keys (advisory level, scores) that the commit schema rejects.

export default function DestinationStage({ commit, commitData, setupData, transitioning }) {
  const { t } = useTranslation()
  const trip = useTripStore((s) => s.trip)

  const multiCity = setupData?.multi_city ?? false

  const [destinations, setDestinations] = useState([])
  const [loading, setLoading] = useState(true)

  // Prefill from an existing commit when revisiting this stage.
  // Safe to initialise synchronously: we store city *names*, not indices into
  // the fetched list, so this doesn't depend on options having arrived.
  const [selected, setSelected] = useState(() => {
    const prior = commitData?.destinations
    if (!prior?.length) return []
    return prior.map((d) => d.city)
  })

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getStageOptions(trip.id, 'destination')
      .then((opts) => { if (!cancelled) setDestinations(opts) })
      .catch(() => { if (!cancelled) setDestinations([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [trip.id])

  function toggle(city) {
    if (multiCity) {
      // Multi-select: append or remove; pick order becomes stop order
      setSelected((cur) =>
        cur.includes(city) ? cur.filter((c) => c !== city) : [...cur, city]
      )
    } else {
      // Single-select: replace
      setSelected([city])
    }
  }

  function handleConfirm() {
    // Preserve pick order — destinations[i] maps to stop_index i
    const chosen = selected
      .map((city) => destinations.find((d) => d.city === city))
      .filter(Boolean)
      .map(({ city, country, why_chosen_summary, season_note, safety_note }) => ({
        city, country, why_chosen_summary, season_note, safety_note,
      }))

    commit({ destinations: chosen })
  }

  const valid = selected.length >= 1

  if (loading) {
    return (
      <StageCard title={t('destination.title')} subtitle={t('destination.subtitle')}>
        <div className="py-10 text-center text-white/50 text-sm">
          {t('common.loading')}
        </div>
      </StageCard>
    )
  }

  return (
    <StageCard title={t('destination.title')} subtitle={t('destination.subtitle')}>
      <div className="flex flex-col gap-3">
        {destinations.map((d) => {
          const isSelected = selected.includes(d.city)
          const order = selected.indexOf(d.city) + 1

          return (
            <OptionCard key={d.city} selected={isSelected} onClick={() => toggle(d.city)}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2.5 mb-1">
                    <h3 className="text-white font-semibold text-base">{d.city}</h3>
                    <span className="text-white/40 text-sm">{d.country}</span>
                    {/* In multi-city mode show the visit order on selected cards */}
                    {isSelected && multiCity && (
                      <Badge>#{order}</Badge>
                    )}
                  </div>

                  <p className="text-white/65 text-sm leading-relaxed">
                    {d.why_chosen_summary}
                  </p>

                  <div className="mt-3 flex flex-col gap-1.5">
                    <div className="flex gap-2 text-xs">
                      <span className="text-white/35 flex-shrink-0 w-28">
                        {t('destination.seasonNote')}
                      </span>
                      <span className="text-white/55">{d.season_note}</span>
                    </div>
                    <div className="flex gap-2 text-xs">
                      <span className="text-white/35 flex-shrink-0 w-28">
                        {t('destination.safetyNote')}
                      </span>
                      <span className="text-white/55">{d.safety_note}</span>
                    </div>
                  </div>
                </div>

                {/* Selection indicator */}
                <div
                  style={{
                    flexShrink: 0, width: 22, height: 22, borderRadius: '50%',
                    border: `2px solid ${isSelected ? '#2dd4bf' : 'rgba(255,255,255,0.25)'}`,
                    background: isSelected ? '#2dd4bf' : 'transparent',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    marginTop: 2,
                  }}
                >
                  {isSelected && (
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                      <path d="M2 6 L5 9 L10 3" stroke="#0a0e1a" strokeWidth="2"
                        strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </div>
              </div>
            </OptionCard>
          )
        })}
      </div>

      {/* Multi-city hint */}
      {multiCity && (
        <p className="text-white/40 text-xs mt-4">
          {selected.length === 0
            ? t('destination.subtitle')
            : `${selected.length} ${selected.length === 1 ? 'city' : 'cities'} — ${selected.join(' → ')}`}
        </p>
      )}

      {/* Destination cannot be skipped — the stop block depends on it */}
      <StageActions
        onConfirm={handleConfirm}
        confirmDisabled={!valid}
        showSkip={false}
        showForward={false}
        transitioning={transitioning}
      />
    </StageCard>
  )
}