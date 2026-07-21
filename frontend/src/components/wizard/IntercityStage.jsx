import React, { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, OptionCard, StageActions } from './primitives'
import { getStageOptions } from '../../api/client'
import useTripStore from '../../store/tripStore'

// ─────────────────────────────────────────────────────────────────────────────
// IntercityStage — how to reach each spoke, and when
// ─────────────────────────────────────────────────────────────────────────────
// Only in the sequence for multi-city trips. Commit validates against
// IntercityCommitData:
//   { segments: [ { stop_index, city, travel_date, return_date, selected } ] }
//   one segment per SPOKE (stop_index >= 1); the hub (0) is never a segment.
//
// This renders ONCE and handles every spoke: for each, it fetches that spoke's
// transport options (a per-spoke IntercityAgent call) and offers a mode pick
// plus two date fields. Commit sends all segments at once.
//
// Date window — the fiddly, load-bearing part. Each day trip must fall STRICTLY
// inside the trip window: you can't leave before you've landed (depart+1
// earliest) and you can't still be away the morning your flight home leaves
// (return-1 latest). _apply_intercity_commit / _validate_segments enforce this
// server-side; the pickers enforce it here so the user can't build an invalid
// segment in the first place. min/max on the date inputs do the clamping.
//
// travel_date and return_date may be the same day (a true day trip). return may
// not precede travel.

function isoAddDays(iso, n) {
  const d = new Date(iso + 'T00:00:00')
  d.setDate(d.getDate() + n)
  return d.toISOString().slice(0, 10)
}

const MODE_ICON = {
  train: '🚆', bus: '🚌', flight: '✈️', ferry: '⛴️', car: '🚗',
}

function SpokeBlock({ spoke, tripId, windowMin, windowMax, value, onChange, t }) {
  const [options, setOptions] = useState([])
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setFailed(false)
    getStageOptions(tripId, 'intercity', spoke.stop_index, { force: reloadKey > 0 })
      .then((opts) => { if (!cancelled) setOptions(opts) })
      .catch(() => { if (!cancelled) { setOptions([]); setFailed(true) } })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [tripId, spoke.stop_index, reloadKey])

  const sel = value || {}

  function pickOption(opt) {
    onChange({ ...sel, selected: opt })
  }
  function setTravel(date) {
    // Keep return >= travel: if return is now before travel, pull it up.
    const nextReturn = sel.return_date && sel.return_date < date ? date : sel.return_date
    onChange({ ...sel, travel_date: date, return_date: nextReturn })
  }
  function setReturn(date) {
    onChange({ ...sel, return_date: date })
  }

  return (
    <div className="rounded-xl px-4 py-4 mb-4"
      style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.10)' }}>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-white/40 text-xs uppercase tracking-widest">{t('intercity.dayTripTo')}</span>
        <span className="text-white font-semibold">{spoke.city}</span>
      </div>

      {loading ? (
        <div className="py-6 text-center text-white/50 text-sm">{t('common.loading')}</div>
      ) : failed || options.length === 0 ? (
        <div className="py-4 text-center">
          <p className="text-white/60 text-sm mb-2">{t('errors.optionsFailed')}</p>
          <button onClick={() => setReloadKey((k) => k + 1)}
            className="text-sm hover:underline" style={{ color: '#2dd4bf' }}>
            {t('common.retry')}
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-2 mb-4">
          {options.map((o, i) => {
            const chosen = sel.selected && sel.selected.mode === o.mode &&
              sel.selected.description === o.description
            return (
              <OptionCard key={i} selected={chosen} onClick={() => pickOption(o)}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span>{MODE_ICON[o.mode] ?? '•'}</span>
                      <span className="text-white text-sm font-medium capitalize">{o.mode}</span>
                    </div>
                    <p className="text-white/60 text-xs leading-relaxed">{o.description}</p>
                    {/* sources are empty in this version (no web search yet); when
                        they arrive, Anthropic's terms require rendering them here. */}
                    {o.sources && o.sources.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {o.sources.map((s, si) => (
                          <a key={si} href={s.url} target="_blank" rel="noreferrer"
                            className="text-[10px] underline" style={{ color: '#2dd4bf' }}>
                            {s.title || t('intercity.source')}
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="text-right flex-shrink-0">
                    <div className="text-white/80 text-sm font-semibold">${o.cost_usd}</div>
                    <div className="text-white/40 text-xs">{o.duration_hours}h {t('intercity.eachWay')}</div>
                  </div>
                </div>
              </OptionCard>
            )
          })}
        </div>
      )}

      {/* Date window — strictly inside the trip */}
      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="text-white/50 text-xs mb-1 block">{t('intercity.travelDate')}</span>
          <input type="date" value={sel.travel_date || ''} min={windowMin} max={windowMax}
            onChange={(e) => setTravel(e.target.value)}
            className="w-full rounded-lg px-3 py-2 text-sm text-white"
            style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.15)' }} />
        </label>
        <label className="block">
          <span className="text-white/50 text-xs mb-1 block">{t('intercity.returnDate')}</span>
          <input type="date" value={sel.return_date || ''}
            min={sel.travel_date || windowMin} max={windowMax}
            onChange={(e) => setReturn(e.target.value)}
            className="w-full rounded-lg px-3 py-2 text-sm text-white"
            style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.15)' }} />
        </label>
      </div>
    </div>
  )
}

export default function IntercityStage({ commit, commitData, transitioning }) {
  const { t } = useTranslation()
  const trip = useTripStore((s) => s.trip)
  const setupData = useTripStore((s) => s.setupData)

  // Spokes are stops 1..N. The hub (0) is never a day-trip target.
  const spokes = (trip?.stops ?? [])
    .filter((s) => s.stop_index >= 1)
    .sort((a, b) => a.stop_index - b.stop_index)

  // Trip window, strictly inside: [depart+1 .. return-1]. A day trip can't be
  // the arrival day or the departure-home day.
  const setup = setupData()
  const windowMin = setup ? isoAddDays(setup.departure_date, 1) : undefined
  const windowMax = setup ? isoAddDays(setup.return_date, -1) : undefined

  // segments keyed by stop_index, so each SpokeBlock edits its own.
  const [segments, setSegments] = useState(() => {
    const prior = {}
    for (const seg of commitData?.segments ?? []) prior[seg.stop_index] = seg
    return prior
  })

  function updateSegment(stopIndex, city, partial) {
    setSegments((cur) => ({
      ...cur,
      [stopIndex]: { stop_index: stopIndex, city, ...cur[stopIndex], ...partial },
    }))
  }

  // Complete = every spoke has an option and both dates.
  const allComplete = spokes.every((s) => {
    const seg = segments[s.stop_index]
    return seg && seg.selected && seg.travel_date && seg.return_date
  })

  function handleConfirm() {
    if (!allComplete) return
    const list = spokes.map((s) => {
      const seg = segments[s.stop_index]
      return {
        stop_index: s.stop_index,
        city: s.city,
        travel_date: seg.travel_date,
        return_date: seg.return_date,
        selected: seg.selected,
      }
    })
    commit({ segments: list })
  }

  return (
    <StageCard title={t('intercity.title')} subtitle={t('intercity.subtitle')}>
      <p className="text-white/50 text-xs mb-4">{t('intercity.windowHint')}</p>

      {spokes.map((s) => (
        <SpokeBlock
          key={s.stop_index}
          spoke={s}
          tripId={trip.id}
          windowMin={windowMin}
          windowMax={windowMax}
          value={segments[s.stop_index]}
          onChange={(partial) => updateSegment(s.stop_index, s.city, partial)}
          t={t}
        />
      ))}

      <StageActions
        onConfirm={handleConfirm}
        confirmDisabled={!allComplete}
        showSkip={false}
        showForward={false}
        transitioning={transitioning}
      />
    </StageCard>
  )
}