import React, { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { motion } from 'framer-motion'
import useTripStore from '../../store/tripStore'

// ─────────────────────────────────────────────────────────────────────────────
// TripListScreen — "your plans", shown when no trip is open
// ─────────────────────────────────────────────────────────────────────────────
// Replaces the auto-create placeholder: the app used to mint a trip the moment
// you authenticated, which meant effectively one ephemeral trip and no way back
// to an earlier one. Now authentication lands here, and a trip is created only
// when you ask for one.
//
// Each card is built from TripSummaryResponse, which now carries the
// destination derived from the trip's Stop rows (country, cities, and the hub's
// date window). Without those a card could only show a UUID and a timestamp —
// see the note on _trip_summary.
//
// A trip with no stops yet (still on setup/country) has no destination to show,
// so it falls back to "Untitled trip" plus where the wizard left off.

function fmtDate(iso) {
  if (!iso) return null
  // Short, locale-agnostic: "Oct 1". Intl would localise but the trip list is
  // scanned, not read, and a stable short form is easier to compare down a list.
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function fmtWhen(startISO, endISO) {
  const a = fmtDate(startISO)
  const b = fmtDate(endISO)
  if (a && b) return `${a} – ${b}`
  return a || b || null
}

function TripCard({ trip, onOpen, t }) {
  const cities = trip.cities || []
  const title = cities.length
    ? cities.join(' · ')
    : t('plans.untitled')
  const when = fmtWhen(trip.start_date, trip.end_date)
  const isComplete = trip.status === 'complete'

  return (
    <motion.button
      whileHover={{ y: -2 }}
      onClick={() => onOpen(trip.id)}
      className="w-full text-left rounded-xl px-5 py-4 transition-colors"
      style={{
        background: 'rgba(255,255,255,0.05)',
        border: '1px solid rgba(255,255,255,0.10)',
      }}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <h3 className="text-white font-semibold text-base">{title}</h3>
            {trip.country && (
              <span className="text-white/40 text-sm">{trip.country}</span>
            )}
            {trip.multi_city && (
              <span className="text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded"
                style={{ background: 'rgba(56,189,248,0.15)', color: '#38bdf8' }}>
                {t('plans.multiCity')}
              </span>
            )}
          </div>

          {when && <p className="text-white/50 text-sm">{when}</p>}

          <p className="text-white/35 text-xs mt-2">
            {isComplete
              ? t('plans.complete')
              : `${t('plans.at')}: ${t(`stages.${trip.current_stage}`)}`}
          </p>
        </div>

        <div className="flex-shrink-0 flex flex-col items-end gap-2">
          <span
            className="text-[10px] uppercase tracking-widest px-2 py-1 rounded"
            style={{
              background: isComplete ? 'rgba(45,212,191,0.15)' : 'rgba(255,255,255,0.08)',
              color: isComplete ? '#2dd4bf' : 'rgba(255,255,255,0.55)',
            }}
          >
            {isComplete ? t('plans.complete') : t('plans.inProgress')}
          </span>
          <span className="text-xs" style={{ color: '#2dd4bf' }}>
            {isComplete ? t('plans.view') : t('plans.resume')} →
          </span>
        </div>
      </div>
    </motion.button>
  )
}

export default function TripListScreen() {
  const { t } = useTranslation()
  const trips = useTripStore((s) => s.trips)
  const tripsLoading = useTripStore((s) => s.tripsLoading)
  const fetchTrips = useTripStore((s) => s.fetchTrips)
  const loadTrip = useTripStore((s) => s.loadTrip)
  const startTrip = useTripStore((s) => s.startTrip)

  useEffect(() => {
    fetchTrips().catch(() => { /* surfaces via store.error */ })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function openTrip(id) {
    loadTrip(id).catch(() => {})
  }

  function newTrip() {
    // Creating a trip loads it into the store, which switches App to the wizard.
    startTrip().catch(() => {})
  }

  return (
    <div className="glass-card p-6 md:p-8" style={{ maxWidth: 720, width: '100%' }}>
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <h2 className="text-white font-semibold text-xl tracking-tight">
            {t('plans.title')}
          </h2>
          <p className="text-white/50 text-sm mt-1">{t('plans.subtitle')}</p>
        </div>
        <button
          onClick={newTrip}
          className="px-4 py-2 rounded-lg text-sm font-semibold flex-shrink-0"
          style={{ color: '#0a0e1a', background: 'linear-gradient(135deg, #2dd4bf, #38bdf8)' }}
        >
          + {t('sidebar.newTrip')}
        </button>
      </div>

      {tripsLoading ? (
        <div className="py-12 text-center text-white/50 text-sm">
          {t('common.loading')}
        </div>
      ) : trips.length === 0 ? (
        <div className="py-12 text-center">
          <p className="text-white/70 text-sm mb-1">{t('plans.empty')}</p>
          <p className="text-white/40 text-xs mb-5">{t('plans.emptyHint')}</p>
          <button
            onClick={newTrip}
            className="px-5 py-2.5 rounded-lg text-sm font-semibold"
            style={{ color: '#0a0e1a', background: 'linear-gradient(135deg, #2dd4bf, #38bdf8)' }}
          >
            + {t('sidebar.newTrip')}
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {trips.map((tr) => (
            <TripCard key={tr.id} trip={tr} onOpen={openTrip} t={t} />
          ))}
        </div>
      )}
    </div>
  )
}