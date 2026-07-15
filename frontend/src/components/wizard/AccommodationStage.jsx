import React, { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, OptionCard, Badge, StageActions, Field, Input } from './primitives'
import { getStageOptions } from '../../api/client'
import useTripStore from '../../store/tripStore'

// ─────────────────────────────────────────────────────────────────────────────
// AccommodationStage — pick one stay, or provide your own
// ─────────────────────────────────────────────────────────────────────────────
// Commit payload validates against AccommodationCommitData:
//   { selected: HotelOption }
//   HotelOption: { name, location, stars?, price_per_night_usd,
//                  total_price_usd, booking_url?, property_type, provider }
//
// Options come from the HotelAgent via
// POST /trips/{id}/stages/accommodation/options?stop_index=N.
// With AIRBNB_ENABLED False the agent returns mock data through the real path —
// the frontend neither knows nor cares.
//
// `nights` is display-only. total_price_usd comes from the agent, which does
// its own night arithmetic; we don't recompute it or the committed total could
// disagree with what the user was shown.

function nightsBetween(depart, ret) {
  if (!depart || !ret) return 7
  const d = new Date(depart), r = new Date(ret)
  const n = Math.round((r - d) / 86400000)
  return n > 0 ? n : 7
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
  const trip = useTripStore((s) => s.trip)

  const city = stop?.city ?? ''
  const nights = nightsBetween(setupData?.departure_date, setupData?.return_date)

  const [hotels, setHotels] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedIdx, setSelectedIdx] = useState(null)
  const [ownMode, setOwnMode] = useState(false)
  const [ownText, setOwnText] = useState('')

  // Fetch on mount (and whenever the stop changes).
  // The prior-selection restore lives HERE, not in a useState initialiser:
  // options arrive asynchronously, so an initialiser would search an empty
  // array and silently drop the restore when revisiting a committed stage.
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getStageOptions(trip.id, 'accommodation', stop.stop_index)
      .then((opts) => {
        if (cancelled) return
        setHotels(opts)
        const prior = commitData?.selected
        if (prior) {
          const match = opts.findIndex((h) => h.name === prior.name)
          if (match >= 0) setSelectedIdx(match)
        }
      })
      .catch(() => { if (!cancelled) setHotels([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trip.id, stop.stop_index])

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
      {loading ? (
        <div className="py-10 text-center text-white/50 text-sm">
          {t('common.loading')}
        </div>
      ) : !ownMode ? (
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

      {!loading && (
        <button
          onClick={() => setOwnMode((m) => !m)}
          className="mt-4 text-sm hover:underline"
          style={{ color: '#2dd4bf' }}
        >
          {ownMode ? `← ${t('accommodation.title')}` : t('accommodation.provideOwn')}
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