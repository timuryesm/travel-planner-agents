import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, OptionCard, Badge, StageActions, Field, Input } from './primitives'

// ─────────────────────────────────────────────────────────────────────────────
// FlightsStage — pick one flight, or provide your own
// ─────────────────────────────────────────────────────────────────────────────
// Commit payload validates against FlightsCommitData: { selected: FlightOption }
//   FlightOption: { trip_type, legs: [FlightLeg], price_usd, booking_url? }
//   FlightLeg:    { airline, origin, destination, departure_time,
//                   arrival_time, duration_hours }
//
// Self-provided path: commit(data, text) sends commit_type 'self_provided'
// with the free-text note; data carries a minimal FlightOption so the shape
// stays valid.
//
// MOCK DATA — swapped for a real Skyscanner agent call in the agent-endpoints
// step. Shape matches FlightOption exactly.

function mockFlights(origin, city) {
  const o = origin || 'YYZ'
  return [
    {
      trip_type: 'roundtrip',
      price_usd: 842,
      booking_url: null,
      legs: [
        { airline: 'Air Canada', origin: o, destination: city, departure_time: '2026-08-01T18:30', arrival_time: '2026-08-02T09:15', duration_hours: 8.75 },
        { airline: 'Air Canada', origin: city, destination: o, departure_time: '2026-08-10T11:00', arrival_time: '2026-08-10T14:30', duration_hours: 9.5 },
      ],
      _label: 'cheapest',
      _stops: 0,
    },
    {
      trip_type: 'roundtrip',
      price_usd: 1180,
      booking_url: null,
      legs: [
        { airline: 'Lufthansa', origin: o, destination: city, departure_time: '2026-08-01T21:00', arrival_time: '2026-08-02T10:05', duration_hours: 7.1 },
        { airline: 'Lufthansa', origin: city, destination: o, departure_time: '2026-08-10T13:20', arrival_time: '2026-08-10T16:00', duration_hours: 8.7 },
      ],
      _label: 'fastest',
      _stops: 0,
    },
    {
      trip_type: 'roundtrip',
      price_usd: 968,
      booking_url: null,
      legs: [
        { airline: 'KLM', origin: o, destination: city, departure_time: '2026-08-01T16:45', arrival_time: '2026-08-02T12:30', duration_hours: 11.75 },
        { airline: 'KLM', origin: city, destination: o, departure_time: '2026-08-10T09:10', arrival_time: '2026-08-10T15:40', duration_hours: 12.5 },
      ],
      _label: 'comfortable',
      _stops: 1,
    },
  ]
}

function fmtTime(iso) {
  // "2026-08-01T18:30" → "18:30"
  return iso.split('T')[1] ?? iso
}

function LegRow({ leg, label, t }) {
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

export default function FlightsStage({ commit, skip, forward, commitData, stop, setupData, transitioning }) {
  const { t } = useTranslation()

  const city = stop?.city ?? ''
  const flights = mockFlights(setupData?.origin, city)

  // Restore prior selection when revisiting
  const [selectedIdx, setSelectedIdx] = useState(() => {
    const prior = commitData?.selected
    if (!prior) return null
    const match = flights.findIndex((f) => f.price_usd === prior.price_usd)
    return match >= 0 ? match : null
  })

  const [ownMode, setOwnMode] = useState(false)
  const [ownText, setOwnText] = useState(commitData?.__self_text ?? '')

  const labelColor = {
    cheapest: '#2dd4bf',
    fastest: '#a78bfa',
    comfortable: '#fbbf24',
  }

  function handleConfirm() {
    if (ownMode) {
      // self_provided: minimal valid FlightOption + free text
      commit(
        { selected: { trip_type: 'roundtrip', legs: [], price_usd: 0, booking_url: null } },
        ownText.trim()
      )
      return
    }
    if (selectedIdx === null) return
    const f = flights[selectedIdx]
    // Strip the private _label / _stops fields before committing
    const { _label, _stops, ...clean } = f
    commit({ selected: clean })
  }

  const valid = ownMode ? ownText.trim().length > 0 : selectedIdx !== null

  return (
    <StageCard
      title={t('flights.title')}
      subtitle={t('flights.subtitle', { city })}
    >
      {!ownMode ? (
        <div className="flex flex-col gap-3">
          {flights.map((f, i) => (
            <OptionCard key={i} selected={selectedIdx === i} onClick={() => setSelectedIdx(i)}>
              <div className="flex items-center justify-between mb-3">
                <Badge color={labelColor[f._label]}>{t(`flights.${f._label}`)}</Badge>
                <div className="flex items-center gap-3">
                  <span className="text-white/40 text-xs">
                    {f._stops === 0 ? t('flights.nonstop') : t('flights.stops', { count: f._stops })}
                  </span>
                  <span className="text-white font-semibold text-lg">${f.price_usd}</span>
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <LegRow leg={f.legs[0]} label={t('flights.outbound')} t={t} />
                <LegRow leg={f.legs[1]} label={t('flights.return')} t={t} />
              </div>
            </OptionCard>
          ))}
        </div>
      ) : (
        <Field label={t('flights.provideOwn')}>
          <Input
            value={ownText}
            onChange={setOwnText}
            placeholder={t('flights.provideOwnPlaceholder')}
          />
        </Field>
      )}

      {/* Toggle between choosing and providing your own */}
      <button
        onClick={() => setOwnMode((m) => !m)}
        className="mt-4 text-sm text-iris-teal hover:underline"
        style={{ color: '#2dd4bf' }}
      >
        {ownMode ? `← ${t('flights.title')}` : t('flights.provideOwn')}
      </button>

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