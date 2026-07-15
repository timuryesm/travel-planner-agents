import React, { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, OptionCard, Badge, StageActions, Field, Input } from './primitives'
import { getStageOptions } from '../../api/client'
import useTripStore from '../../store/tripStore'

// ─────────────────────────────────────────────────────────────────────────────
// FlightsStage — now fetches real options from the agent endpoint
// ─────────────────────────────────────────────────────────────────────────────
// Change from the mock version: instead of mockFlights(), we fetch on mount
// from POST /trips/{id}/stages/flights/options?stop_index=N. The agent returns
// FlightOption[] (currently mock data, since SKYSCANNER_ENABLED is False — but
// the frontend no longer knows or cares; it just renders what comes back).
//
// Everything downstream (selection, self-provided path, commit payload) is
// unchanged from the mock version.

function fmtTime(iso) {
  return iso?.split('T')[1] ?? iso ?? ''
}

// Derive a cheapest/fastest label set from the returned options
function labelFor(flights, idx) {
  if (!flights.length) return null
  const prices = flights.map((f) => f.price_usd)
  const durations = flights.map((f) =>
    (f.legs || []).reduce((s, l) => s + (l.duration_hours || 0), 0)
  )
  const minPrice = Math.min(...prices)
  const minDur = Math.min(...durations)
  if (flights[idx].price_usd === minPrice) return 'cheapest'
  if (durations[idx] === minDur) return 'fastest'
  return 'comfortable'
}

function LegRow({ leg, label, t }) {
  if (!leg) return null
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-white/35 w-16 flex-shrink-0 text-xs uppercase tracking-wide">
        {label}
      </span>
      <span className="text-white/85 font-medium">{leg.airline}</span>
      <span className="text-white/45">
        {leg.origin} {fmtTime(leg.departure_time)} → {leg.destination} {fmtTime(leg.arrival_time)}
      </span>
      <span className="text-white/40 ml-auto text-xs">
        {t('flights.duration', { hours: leg.duration_hours })}
      </span>
    </div>
  )
}

const LABEL_COLOR = { cheapest: '#2dd4bf', fastest: '#a78bfa', comfortable: '#fbbf24' }

export default function FlightsStage({ commit, skip, forward, commitData, stop, transitioning }) {
  const { t } = useTranslation()
  const trip = useTripStore((s) => s.trip)
  const city = stop?.city ?? ''

  const [flights, setFlights] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedIdx, setSelectedIdx] = useState(null)
  const [ownMode, setOwnMode] = useState(false)
  const [ownText, setOwnText] = useState('')

  // Fetch options on mount (and whenever the stop changes)
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getStageOptions(trip.id, 'flights', stop.stop_index)
      .then((opts) => {
        if (cancelled) return
        setFlights(opts)
        // Restore prior selection by matching price
        const prior = commitData?.selected
        if (prior) {
          const match = opts.findIndex((f) => f.price_usd === prior.price_usd)
          if (match >= 0) setSelectedIdx(match)
        }
      })
      .catch(() => { if (!cancelled) setFlights([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trip.id, stop.stop_index])

  function handleConfirm() {
    if (ownMode) {
      commit(
        { selected: { trip_type: 'roundtrip', legs: [], price_usd: 0, booking_url: null } },
        ownText.trim()
      )
      return
    }
    if (selectedIdx === null) return
    commit({ selected: flights[selectedIdx] })
  }

  const valid = ownMode ? ownText.trim().length > 0 : selectedIdx !== null

  return (
    <StageCard title={t('flights.title')} subtitle={t('flights.subtitle', { city })}>
      {loading ? (
        <div className="py-10 text-center text-white/50 text-sm">
          {t('common.loading')}
        </div>
      ) : ownMode ? (
        <Field label={t('flights.provideOwn')}>
          <Input value={ownText} onChange={setOwnText}
            placeholder={t('flights.provideOwnPlaceholder')} />
        </Field>
      ) : (
        <div className="flex flex-col gap-3">
          {flights.map((f, i) => {
            const label = labelFor(flights, i)
            const stops = Math.max(0, (f.legs?.length || 1) - 1)
            return (
              <OptionCard key={i} selected={selectedIdx === i} onClick={() => setSelectedIdx(i)}>
                <div className="flex items-center justify-between mb-3">
                  {label && <Badge color={LABEL_COLOR[label]}>{t(`flights.${label}`)}</Badge>}
                  <div className="flex items-center gap-3">
                    <span className="text-white/40 text-xs">
                      {stops === 0 ? t('flights.nonstop') : t('flights.stops', { count: stops })}
                    </span>
                    <span className="text-white font-semibold text-lg">${f.price_usd}</span>
                  </div>
                </div>
                <div className="flex flex-col gap-1.5">
                  <LegRow leg={f.legs?.[0]} label={t('flights.outbound')} t={t} />
                  <LegRow leg={f.legs?.[1]} label={t('flights.return')} t={t} />
                </div>
              </OptionCard>
            )
          })}
        </div>
      )}

      {!loading && (
        <button
          onClick={() => setOwnMode((m) => !m)}
          className="mt-4 text-sm hover:underline"
          style={{ color: '#2dd4bf' }}
        >
          {ownMode ? `← ${t('flights.title')}` : t('flights.provideOwn')}
        </button>
      )}

      <StageActions
        onConfirm={handleConfirm}
        confirmDisabled={!valid}
        onSkip={skip}
        onForward={forward}
        transitioning={transitioning}
      />
    </StageCard>
  )
}