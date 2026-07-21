import React, { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, OptionCard, StageActions, Field, Input } from './primitives'
import { getStageOptions } from '../../api/client'
import useTripStore from '../../store/tripStore'

// ─────────────────────────────────────────────────────────────────────────────
// CityStage — pick the hub, then optional day-trip spokes
// ─────────────────────────────────────────────────────────────────────────────
// Commit payload validates against CityCommitData:
//   { cities: [ { city, why_chosen_summary, climate_note } ] }   min_length 1
//
// cities[0] is the HUB: flown into, hotel is here, every day-trip starts and
// ends here. cities[1..N] are SPOKES — day-trips out and back, no overnight.
// The backend already does everything from this list: one Stop per city,
// multi_city from len > 1, intercity commit created/deleted to match. So
// multi-city is entirely a matter of this component building a longer list.
//
// Flow (hub-then-spokes, each spoke a fresh search):
//   1. First search suggests cities. Pick one → it's the hub, confirmed.
//   2. An "add a day-trip city" section appears. Each add runs a NEW city
//      search with every already-chosen city excluded, so spokes come from
//      fresh suggestions rather than a fixed six.
//   3. Add as many spokes as wanted, remove any, then continue.
//
// Each search is a Claude call, so a search only runs when the user asks for
// one (confirming the hub, or pressing "find day-trip cities") — never on every
// render.
//
// No safety_note here: advisories are country-level, and the committed
// country's note covers every city in it.

function CityCard({ c, selected, onClick, t }) {
  return (
    <OptionCard selected={selected} onClick={onClick}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <h3 className="text-white font-semibold text-base mb-1">{c.city}</h3>
          <p className="text-white/65 text-sm leading-relaxed">{c.why_chosen_summary}</p>
          <div className="mt-3 flex gap-2 text-xs">
            <span className="text-white/35 flex-shrink-0 w-28">{t('city.climateNote')}</span>
            <span className="text-white/55">{c.climate_note}</span>
          </div>
        </div>
        <div
          style={{
            flexShrink: 0, width: 22, height: 22, borderRadius: '50%',
            border: `2px solid ${selected ? '#2dd4bf' : 'rgba(255,255,255,0.25)'}`,
            background: selected ? '#2dd4bf' : 'transparent',
            display: 'flex', alignItems: 'center', justifyContent: 'center', marginTop: 2,
          }}
        >
          {selected && (
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path d="M2 6 L5 9 L10 3" stroke="#0a0e1a" strokeWidth="2"
                strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </div>
      </div>
    </OptionCard>
  )
}

function pick(c) {
  // Only the three fields CityCommitData accepts — the agent's dump may carry more.
  const { city, why_chosen_summary, climate_note } = c
  return { city, why_chosen_summary, climate_note }
}

export default function CityStage({ commit, commitData, transitioning }) {
  const { t } = useTranslation()
  const trip = useTripStore((s) => s.trip)
  const countryData = useTripStore((s) => s.countryData)
  const country = countryData()?.country?.name ?? ''

  // The committed list, if revisiting: [hub, ...spokes]. Chosen full objects.
  const priorCities = commitData?.cities ?? []
  const [hub, setHub] = useState(() => (priorCities.length ? pick(priorCities[0]) : null))
  const [spokes, setSpokes] = useState(() => priorCities.slice(1).map(pick))

  // The current suggestion list (for whichever search is active) + its state.
  const [suggestions, setSuggestions] = useState([])
  const [selected, setSelected] = useState(null) // name highlighted in the current list
  const [loading, setLoading] = useState(!hub)   // load hub suggestions on mount only if no hub yet
  const [failed, setFailed] = useState(false)

  // Are we currently searching for a spoke (vs. the initial hub search)?
  const [addingSpoke, setAddingSpoke] = useState(false)

  // Preference box (kept from step 9). Applies to the CURRENT search.
  const [preference, setPreference] = useState('')
  const [appliedPreference, setAppliedPreference] = useState(null)
  const [searchKey, setSearchKey] = useState(0) // bump to force a fresh search

  const chosenNames = [hub?.city, ...spokes.map((s) => s.city)].filter(Boolean)

  // Run a city search. exclude = everything already chosen, so a spoke search
  // never re-suggests the hub or an existing spoke.
  const search = useCallback(() => {
    let cancelled = false
    setLoading(true)
    setFailed(false)
    setSelected(null)
    getStageOptions(trip.id, 'city', null, {
      preferenceText: appliedPreference,
      exclude: chosenNames,
      force: true, // every search here is a deliberate "ask again"
    })
      .then((opts) => { if (!cancelled) setSuggestions(opts) })
      .catch(() => { if (!cancelled) { setSuggestions([]); setFailed(true) } })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trip.id, appliedPreference, searchKey])

  // Initial hub search — only if we don't already have a committed hub.
  useEffect(() => {
    if (hub) { setLoading(false); return }
    const cleanup = search()
    return cleanup
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchKey])

  function applyPreference() {
    setAppliedPreference(preference.trim() || null)
    setSearchKey((k) => k + 1) // re-run the current search with the new hint
  }

  // Confirm the highlighted suggestion as either the hub or a new spoke.
  function confirmSelection() {
    const chosen = suggestions.find((c) => c.city === selected)
    if (!chosen) return
    if (!hub) {
      setHub(pick(chosen))
      setAddingSpoke(false)
    } else {
      setSpokes((cur) => [...cur, pick(chosen)])
      setAddingSpoke(false)
    }
    setSuggestions([])
    setSelected(null)
    setPreference('')
    setAppliedPreference(null)
  }

  // Begin a spoke search: reveal the list and fetch fresh suggestions.
  function startAddSpoke() {
    setAddingSpoke(true)
    setSuggestions([])
    setSelected(null)
    setPreference('')
    setAppliedPreference(null)
    setSearchKey((k) => k + 1) // triggers search() via the effect below
  }

  // A spoke search runs when addingSpoke flips on (searchKey bumped).
  useEffect(() => {
    if (!addingSpoke) return
    const cleanup = search()
    return cleanup
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addingSpoke, searchKey])

  function removeSpoke(name) {
    setSpokes((cur) => cur.filter((s) => s.city !== name))
  }

  function changeHub() {
    // Re-pick the hub: clear everything and start over. Spokes were chosen
    // relative to this hub (day-trip distance), so they don't survive a hub swap.
    setHub(null)
    setSpokes([])
    setAddingSpoke(false)
    setSuggestions([])
    setSelected(null)
    setSearchKey((k) => k + 1)
  }

  function handleConfirm() {
    if (!hub) return
    commit({ cities: [hub, ...spokes] })
  }

  // ── Render ──
  const showingSearch = !hub || addingSpoke
  const searchTitle = !hub ? t('city.pickHub') : t('city.pickSpoke')

  const preferenceBox = showingSearch && (
    <div className="mb-4">
      <Field label={t('city.preferenceLabel')} hint={`(${t('common.optional')})`}>
        <div className="flex gap-2">
          <div className="flex-1">
            <Input value={preference} onChange={setPreference}
              placeholder={t('city.preferencePlaceholder')} />
          </div>
          <button onClick={applyPreference} disabled={loading}
            className="px-4 text-sm rounded-lg flex-shrink-0"
            style={{ color: '#0a0e1a', background: '#2dd4bf', opacity: loading ? 0.5 : 1 }}>
            {t('city.applyPreference')}
          </button>
        </div>
      </Field>
    </div>
  )

  return (
    <StageCard title={t('city.title')} subtitle={t('city.subtitle', { country })}>
      {/* Chosen so far: hub + spokes */}
      {hub && (
        <div className="mb-5">
          <div className="flex items-center justify-between rounded-lg px-3 py-2 mb-2"
            style={{ background: 'rgba(45,212,191,0.10)', border: '1px solid rgba(45,212,191,0.3)' }}>
            <div className="min-w-0">
              <span className="text-white/40 text-xs uppercase tracking-widest mr-2">{t('city.hub')}</span>
              <span className="text-white text-sm font-medium">{hub.city}</span>
            </div>
            <button onClick={changeHub} disabled={transitioning}
              className="text-white/50 hover:text-white/80 text-xs">
              {t('city.changeHub')}
            </button>
          </div>

          {spokes.map((s) => (
            <div key={s.city}
              className="flex items-center justify-between rounded-lg px-3 py-2 mb-2"
              style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.10)' }}>
              <div className="min-w-0">
                <span className="text-white/40 text-xs uppercase tracking-widest mr-2">{t('city.dayTrip')}</span>
                <span className="text-white/85 text-sm">{s.city}</span>
              </div>
              <button onClick={() => removeSpoke(s.city)} aria-label={t('city.removeSpoke')}
                className="text-white/40 hover:text-white/80 text-lg leading-none px-1">×</button>
            </div>
          ))}

          {/* Add-spoke trigger, shown when not already searching for one */}
          {!addingSpoke && (
            <button onClick={startAddSpoke} disabled={transitioning}
              className="text-sm mt-1 hover:underline" style={{ color: '#2dd4bf' }}>
              + {t('city.addCity')}
            </button>
          )}
        </div>
      )}

      {/* Search + suggestions, shown for hub pick or an in-progress spoke add */}
      {showingSearch && (
        <>
          <p className="text-white/70 text-xs font-semibold uppercase tracking-widest mb-2">
            {searchTitle}
          </p>
          {preferenceBox}

          {loading ? (
            <div className="py-10 text-center text-white/50 text-sm">{t('common.loading')}</div>
          ) : failed || suggestions.length === 0 ? (
            <div className="py-8 text-center">
              <p className="text-white/60 text-sm mb-3">{t('errors.optionsFailed')}</p>
              <button onClick={() => setSearchKey((k) => k + 1)}
                className="text-sm hover:underline" style={{ color: '#2dd4bf' }}>
                {t('common.retry')}
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {suggestions.map((c) => (
                <CityCard key={c.city} c={c} selected={selected === c.city}
                  onClick={() => setSelected(c.city)} t={t} />
              ))}
            </div>
          )}

          {/* Confirm the current pick as hub or spoke */}
          {suggestions.length > 0 && (
            <div className="flex gap-3 mt-4">
              <button onClick={confirmSelection} disabled={!selected}
                className="px-4 py-2 text-sm rounded-lg"
                style={{ color: '#0a0e1a', background: '#2dd4bf', opacity: selected ? 1 : 0.4 }}>
                {!hub ? t('city.confirmHub') : t('city.confirmSpoke')}
              </button>
              {hub && addingSpoke && (
                <button onClick={() => { setAddingSpoke(false); setSuggestions([]); setSelected(null) }}
                  className="px-4 py-2 text-sm text-white/60 hover:text-white/90">
                  {t('common.cancel')}
                </button>
              )}
              <button onClick={() => setSearchKey((k) => k + 1)}
                className="ml-auto text-sm self-center hover:underline" style={{ color: '#2dd4bf' }}>
                {t('city.regenerate')}
              </button>
            </div>
          )}
        </>
      )}

      <p className="text-white/40 text-xs mt-5">{t('city.hubHint')}</p>

      {/* Continue is enabled once a hub exists; spokes are optional */}
      <StageActions
        onConfirm={handleConfirm}
        confirmDisabled={!hub}
        showSkip={false}
        showForward={false}
        transitioning={transitioning}
      />
    </StageCard>
  )
}