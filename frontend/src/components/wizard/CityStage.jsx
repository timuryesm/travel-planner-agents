import React, { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, OptionCard, StageActions, Field, Input } from './primitives'
import { getStageOptions } from '../../api/client'
import useTripStore from '../../store/tripStore'

// ─────────────────────────────────────────────────────────────────────────────
// CityStage — pick the hub city
// ─────────────────────────────────────────────────────────────────────────────
// Commit payload validates against CityCommitData:
//   { cities: [ { city, why_chosen_summary, climate_note } ] }   min_length=1
//
// cities[0] is the HUB: the city you fly into, where the hotel is, and where
// every day-trip starts and ends. Track 1 commits exactly one. "Add another
// city" (step 16) appends spokes to this same list — the payload is already
// the right shape for it, which is why it's a list of one rather than a single
// object.
//
// This commit is STRUCTURAL: it creates the Stop rows, sets multi_city, and
// decides whether the intercity stage exists. The sidebar's per-city groups
// appear the moment it lands.
//
// The preference box is a stage-scoped hint — "somewhere coastal", "not a
// megacity". It is separate from the setup preferences, which describe the
// whole trip; the agent receives them as two labelled lines and treats them as
// different questions. Applying it forces a refetch (getStageOptions never
// serves a cached answer to a hinted request).
//
// No safety_note here: advisories are published per country, and the note on
// the committed country covers every city in it.

export default function CityStage({ commit, commitData, transitioning }) {
  const { t } = useTranslation()
  const trip = useTripStore((s) => s.trip)
  const countryData = useTripStore((s) => s.countryData)
  const country = countryData()?.country?.name ?? ''

  const [cities, setCities] = useState([])
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  // What's in the box vs. what was last sent. Typing shouldn't refetch; only
  // pressing Apply should — each fetch is a Claude call.
  const [preference, setPreference] = useState('')
  const [appliedPreference, setAppliedPreference] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)

  // By name, so it survives a list that hasn't arrived yet. cities[0] is the
  // hub and Track 1 has only that one.
  const [selected, setSelected] = useState(() => commitData?.cities?.[0]?.city ?? null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setFailed(false)
    getStageOptions(trip.id, 'city', null, {
      preferenceText: appliedPreference,
      force: reloadKey > 0,
    })
      .then((opts) => { if (!cancelled) setCities(opts) })
      .catch(() => { if (!cancelled) { setCities([]); setFailed(true) } })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [trip.id, appliedPreference, reloadKey])

  function applyPreference() {
    const text = preference.trim()
    setAppliedPreference(text || null)
    // A cleared box with no prior hint would leave the effect deps unchanged
    // and refetch nothing; bump the key so Apply always means "ask again".
    setReloadKey((k) => k + 1)
  }

  function handleConfirm() {
    const chosen = cities.find((c) => c.city === selected)
    if (!chosen) return
    // Explicit field pick: the agent's model_dump may carry keys CityCommitData
    // doesn't accept, and the backend validates on write now.
    const { city, why_chosen_summary, climate_note } = chosen
    commit({ cities: [{ city, why_chosen_summary, climate_note }] })
  }

  const preferenceBox = (
    <div className="mb-4">
      <Field label={t('city.preferenceLabel')} hint={`(${t('common.optional')})`}>
        <div className="flex gap-2">
          <div className="flex-1">
            <Input
              value={preference}
              onChange={setPreference}
              placeholder={t('city.preferencePlaceholder')}
            />
          </div>
          <button
            onClick={applyPreference}
            disabled={loading}
            className="px-4 text-sm rounded-lg flex-shrink-0"
            style={{
              color: '#0a0e1a',
              background: '#2dd4bf',
              opacity: loading ? 0.5 : 1,
            }}
          >
            {t('city.applyPreference')}
          </button>
        </div>
      </Field>
    </div>
  )

  return (
    <StageCard title={t('city.title')} subtitle={t('city.subtitle', { country })}>
      {preferenceBox}

      {loading ? (
        <div className="py-10 text-center text-white/50 text-sm">
          {t('common.loading')}
        </div>
      ) : failed || cities.length === 0 ? (
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
      ) : (
        <div className="flex flex-col gap-3">
          {cities.map((c) => {
            const isSelected = selected === c.city
            return (
              <OptionCard key={c.city} selected={isSelected} onClick={() => setSelected(c.city)}>
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <h3 className="text-white font-semibold text-base mb-1">{c.city}</h3>

                    <p className="text-white/65 text-sm leading-relaxed">
                      {c.why_chosen_summary}
                    </p>

                    <div className="mt-3 flex gap-2 text-xs">
                      <span className="text-white/35 flex-shrink-0 w-28">
                        {t('city.climateNote')}
                      </span>
                      <span className="text-white/55">{c.climate_note}</span>
                    </div>
                  </div>

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
      )}

      <p className="text-white/40 text-xs mt-4">{t('city.hubHint')}</p>

      {/* City cannot be skipped — the stops, the flight and the hotel need it */}
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