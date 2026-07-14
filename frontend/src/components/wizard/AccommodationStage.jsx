import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, OptionCard, Badge, StageActions, Field, Input } from './primitives'

// ─────────────────────────────────────────────────────────────────────────────
// AccommodationStage — pick one stay, or provide your own
// ─────────────────────────────────────────────────────────────────────────────
// Commit payload validates against AccommodationCommitData:
//   { selected: HotelOption }
//   HotelOption: { name, location, stars?, price_per_night_usd,
//                  total_price_usd, booking_url?, property_type, provider }
//
// MOCK DATA — swapped for a real Booking.com / Airbnb agent call later.

function nightsBetween(depart, ret) {
  if (!depart || !ret) return 7
  const d = new Date(depart), r = new Date(ret)
  const n = Math.round((r - d) / 86400000)
  return n > 0 ? n : 7
}

function mockHotels(city, nights) {
  return [
    {
      name: `${city} Grand Central Hotel`,
      location: `Downtown ${city}`,
      stars: 4,
      price_per_night_usd: 142,
      total_price_usd: 142 * nights,
      booking_url: null,
      property_type: 'hotel',
      provider: 'booking.com',
    },
    {
      name: `Cozy Loft in Old Town`,
      location: `Historic District, ${city}`,
      stars: 4.8,
      price_per_night_usd: 96,
      total_price_usd: 96 * nights,
      booking_url: null,
      property_type: 'apartment',
      provider: 'airbnb',
    },
    {
      name: `${city} Riverside Suites`,
      location: `Waterfront, ${city}`,
      stars: 4.5,
      price_per_night_usd: 178,
      total_price_usd: 178 * nights,
      booking_url: null,
      property_type: 'hotel',
      provider: 'booking.com',
    },
  ]
}

const PROVIDER_COLOR = { 'booking.com': '#38bdf8', airbnb: '#fb7185' }

function Stars({ value }) {
  return (
    <span className="text-xs" style={{ color: '#fbbf24' }}>
      {'★'.repeat(Math.floor(value))}
      <span className="text-white/30">{value % 1 >= 0.5 ? '½' : ''}</span>
    </span>
  )
}

export default function AccommodationStage({ commit, skip, forward, commitData, stop, setupData, transitioning }) {
  const { t } = useTranslation()

  const city = stop?.city ?? ''
  const nights = nightsBetween(setupData?.departure_date, setupData?.return_date)
  const hotels = mockHotels(city, nights)

  const [selectedIdx, setSelectedIdx] = useState(() => {
    const prior = commitData?.selected
    if (!prior) return null
    const match = hotels.findIndex((h) => h.name === prior.name)
    return match >= 0 ? match : null
  })

  const [ownMode, setOwnMode] = useState(false)
  const [ownText, setOwnText] = useState('')

  function handleConfirm() {
    if (ownMode) {
      commit(
        {
          selected: {
            name: ownText.trim() || 'Self-booked stay',
            location: city,
            stars: null,
            price_per_night_usd: 0,
            total_price_usd: 0,
            booking_url: null,
            property_type: 'hotel',
            provider: 'self',
          },
        },
        ownText.trim()
      )
      return
    }
    if (selectedIdx === null) return
    commit({ selected: hotels[selectedIdx] })
  }

  const valid = ownMode ? ownText.trim().length > 0 : selectedIdx !== null

  return (
    <StageCard
      title={t('accommodation.title')}
      subtitle={t('accommodation.subtitle', { city })}
    >
      {!ownMode ? (
        <div className="flex flex-col gap-3">
          {hotels.map((h, i) => (
            <OptionCard key={i} selected={selectedIdx === i} onClick={() => setSelectedIdx(i)}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2.5 mb-1">
                    <h3 className="text-white font-semibold text-base">{h.name}</h3>
                    {h.stars && <Stars value={h.stars} />}
                  </div>
                  <p className="text-white/45 text-sm">{h.location}</p>
                  <div className="mt-2">
                    <Badge color={PROVIDER_COLOR[h.provider] ?? '#94a3b8'}>
                      {h.provider}
                    </Badge>
                  </div>
                </div>
                <div className="text-right flex-shrink-0">
                  <div className="text-white font-semibold text-lg">
                    ${h.price_per_night_usd}
                    <span className="text-white/40 text-xs font-normal">
                      {' '}{t('accommodation.perNight')}
                    </span>
                  </div>
                  <div className="text-white/45 text-xs mt-0.5">
                    {t('accommodation.total')} ${h.total_price_usd} ·{' '}
                    {t('accommodation.nights', { count: nights })}
                  </div>
                </div>
              </div>
            </OptionCard>
          ))}
        </div>
      ) : (
        <Field label={t('accommodation.provideOwn')}>
          <Input
            value={ownText}
            onChange={setOwnText}
            placeholder={t('accommodation.provideOwnPlaceholder')}
          />
        </Field>
      )}

      <button
        onClick={() => setOwnMode((m) => !m)}
        className="mt-4 text-sm hover:underline"
        style={{ color: '#2dd4bf' }}
      >
        {ownMode ? `← ${t('accommodation.title')}` : t('accommodation.provideOwn')}
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