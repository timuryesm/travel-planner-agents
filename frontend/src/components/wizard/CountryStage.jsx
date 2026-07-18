import React, { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, OptionCard, StageActions } from './primitives'
import { getStageOptions } from '../../api/client'
import useTripStore from '../../store/tripStore'

// ─────────────────────────────────────────────────────────────────────────────
// CountryStage — pick exactly one country
// ─────────────────────────────────────────────────────────────────────────────
// Commit payload validates against CountryCommitData:
//   { country: { name, why_chosen_summary, climate_note, safety_note } }
//
// One country per trip, always. A second country is a different plan, not a
// longer one — it needs its own flights, its own advisory, its own hub.
//
// safety_note comes from the live State Dept advisory feed, never from the
// model. Rendered plainly, never editorialised.
//
// Options come from CountryAgent via POST /trips/{id}/stages/country/options.
// The fetcher raises rather than serving an empty list, so a failure arrives as
// a 502 and gets the retry path below. An empty country list is a dead wizard,
// not an answer.

export default function CountryStage({ commit, commitData, transitioning }) {
  const { t } = useTranslation()
  const trip = useTripStore((s) => s.trip)

  const [countries, setCountries] = useState([])
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  // Restoring by NAME, not by index, so this is safe in an initialiser: it
  // doesn't depend on the fetched list having arrived. (AccommodationStage has
  // to restore inside the effect because it matches against fetched objects.)
  const [selected, setSelected] = useState(() => commitData?.country?.name ?? null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setFailed(false)
    getStageOptions(trip.id, 'country', null, { force: reloadKey > 0 })
      .then((opts) => { if (!cancelled) setCountries(opts) })
      .catch(() => { if (!cancelled) { setCountries([]); setFailed(true) } })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [trip.id, reloadKey])

  function handleConfirm() {
    const chosen = countries.find((c) => c.name === selected)
    if (!chosen) return
    // Re-pick the four fields explicitly: the agent's model_dump may carry keys
    // CountryCommitData doesn't accept, and the backend validates on write now.
    const { name, why_chosen_summary, climate_note, safety_note } = chosen
    commit({ country: { name, why_chosen_summary, climate_note, safety_note } })
  }

  if (loading) {
    return (
      <StageCard title={t('country.title')} subtitle={t('country.subtitle')}>
        <div className="py-10 text-center text-white/50 text-sm">
          {t('common.loading')}
        </div>
      </StageCard>
    )
  }

  if (failed || countries.length === 0) {
    return (
      <StageCard title={t('country.title')} subtitle={t('country.subtitle')}>
        <div className="py-10 text-center">
          <p className="text-white/60 text-sm mb-4">{t('errors.optionsFailed')}</p>
          <button
            onClick={() => setReloadKey((k) => k + 1)}
            className="text-sm hover:underline"
            style={{ color: '#2dd4bf' }}
          >
            {t('common.retry')}
          </button>
        </div>
      </StageCard>
    )
  }

  return (
    <StageCard title={t('country.title')} subtitle={t('country.subtitle')}>
      <div className="flex flex-col gap-3">
        {countries.map((c) => {
          const isSelected = selected === c.name
          return (
            <OptionCard
              key={c.name}
              selected={isSelected}
              onClick={() => setSelected(c.name)}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <h3 className="text-white font-semibold text-base mb-1">{c.name}</h3>

                  <p className="text-white/65 text-sm leading-relaxed">
                    {c.why_chosen_summary}
                  </p>

                  <div className="mt-3 flex flex-col gap-1.5">
                    <div className="flex gap-2 text-xs">
                      <span className="text-white/35 flex-shrink-0 w-28">
                        {t('country.climateNote')}
                      </span>
                      <span className="text-white/55">{c.climate_note}</span>
                    </div>
                    <div className="flex gap-2 text-xs">
                      <span className="text-white/35 flex-shrink-0 w-28">
                        {t('country.safetyNote')}
                      </span>
                      <span className="text-white/55">{c.safety_note}</span>
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

      <p className="text-white/30 text-xs mt-4">{t('country.advisorySource')}</p>

      {/* Country cannot be skipped — the city stage and the stops depend on it */}
      <StageActions
        onConfirm={handleConfirm}
        confirmDisabled={!selected}
        showSkip={false}
        showForward={false}
        transitioning={transitioning}
      />
    </StageCard>
  )
}