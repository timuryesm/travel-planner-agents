import React, { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, OptionCard, Badge, StageActions, Field, Input } from './primitives'
import { getStageOptions } from '../../api/client'
import useTripStore from '../../store/tripStore'

// ─────────────────────────────────────────────────────────────────────────────
// ActivitiesStage — pick several activities, in an order the user controls
// ─────────────────────────────────────────────────────────────────────────────
// Commit payload validates against ActivitiesCommitData:
//   { chosen: [Activity], preference_text?: str }
//   chosen is ORDERED (min_length 0) — the order feeds the daily plan, so it
//   is a list the user arranges, not a set. That's the core change from the
//   old version, which stored selection as a Set and lost order on commit.
//
// Still stop-level: activities is the one stage that repeats per city, so it
// keeps `stop` and stop_index (unlike flights/accommodation/daily_plan, which
// went trip-level). No hub-stop change here.
//
// Three hints reach the agent (POST .../stages/activities/options):
//   preference_text — what the user wants from activities here; its own line,
//                     separate from the setup preferences.
//   exclude         — names already on screen. Powers two buttons:
//                       Regenerate → replace the suggestion list
//                       Show more  → append to it
//   (limit is left at the agent default of 10.)
//
// Selection is kept as an ORDERED ARRAY of names. Restore-from-commit keeps the
// committed order; matching by name means it's safe in a useState initialiser,
// before the fetched list arrives.

const CATEGORY_COLOR = {
  culture: '#a78bfa',
  food: '#fb7185',
  outdoor: '#2dd4bf',
  nightlife: '#f472b6',
  shopping: '#38bdf8',
  relaxation: '#34d399',
}

function ActivityMeta({ a, t }) {
  return (
    <div className="flex items-center gap-2">
      <Badge color={CATEGORY_COLOR[a.category] ?? '#94a3b8'}>{a.category}</Badge>
      <span className="text-white/40 text-xs">
        {t('activities.duration', { hours: a.duration_hours })}
      </span>
      <span className="text-white/70 text-xs ml-auto font-medium">
        ${a.estimated_cost_usd}
      </span>
    </div>
  )
}

export default function ActivitiesStage({ commit, skip, forward, commitData, stop, transitioning }) {
  const { t } = useTranslation()
  const trip = useTripStore((s) => s.trip)
  const city = stop?.city ?? ''

  const [activities, setActivities] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false) // regenerate / show-more in flight

  // Ordered list of chosen NAMES. Order is the committed order on revisit.
  const [chosenNames, setChosenNames] = useState(() => {
    const prior = commitData?.chosen
    return prior?.length ? prior.map((a) => a.name) : []
  })

  // Preference box: typed vs. applied (only Apply refetches — each is a call).
  const [preference, setPreference] = useState(commitData?.preference_text ?? '')
  const [appliedPreference, setAppliedPreference] = useState(
    commitData?.preference_text ?? null
  )
  const [reloadKey, setReloadKey] = useState(0)

  // Initial load + preference-driven reloads. Replaces the list wholesale.
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getStageOptions(trip.id, 'activities', stop.stop_index, {
      preferenceText: appliedPreference,
      force: reloadKey > 0,
    })
      .then((opts) => { if (!cancelled) setActivities(opts) })
      .catch(() => { if (!cancelled) setActivities([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trip.id, stop.stop_index, appliedPreference, reloadKey])

  // A lookup so the ordered picks list can render full cards from names, and so
  // a chosen activity survives even if a regenerate drops it from suggestions.
  const [byName, setByName] = useState({})
  useEffect(() => {
    setByName((prev) => {
      const next = { ...prev }
      for (const a of activities) next[a.name] = a
      return next
    })
  }, [activities])
  // Seed from a prior commit so restored picks have their full objects on mount.
  useEffect(() => {
    if (commitData?.chosen?.length) {
      setByName((prev) => {
        const next = { ...prev }
        for (const a of commitData.chosen) next[a.name] = a
        return next
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function applyPreference() {
    const text = preference.trim()
    setAppliedPreference(text || null)
    setReloadKey((k) => k + 1)
  }

  // Regenerate (replace) and Show more (append) both exclude what's on screen.
  const fetchMore = useCallback(
    (mode) => {
      setBusy(true)
      const exclude = activities.map((a) => a.name)
      getStageOptions(trip.id, 'activities', stop.stop_index, {
        preferenceText: appliedPreference,
        exclude,
        force: true,
      })
        .then((opts) => {
          if (mode === 'replace') {
            setActivities(opts)
          } else {
            // Append, de-duped by name — the agent excludes shown names, but
            // guard anyway so a repeat can never create two cards with the same
            // key or let a name appear twice.
            setActivities((cur) => {
              const seen = new Set(cur.map((a) => a.name))
              return [...cur, ...opts.filter((a) => !seen.has(a.name))]
            })
          }
        })
        .catch(() => { /* keep what's on screen; a failed refresh isn't fatal */ })
        .finally(() => setBusy(false))
    },
    [activities, appliedPreference, trip.id, stop.stop_index]
  )

  // ── Selection ──
  function toggle(name) {
    setChosenNames((cur) =>
      cur.includes(name) ? cur.filter((n) => n !== name) : [...cur, name]
    )
  }

  function move(name, dir) {
    setChosenNames((cur) => {
      const i = cur.indexOf(name)
      const j = i + dir
      if (i < 0 || j < 0 || j >= cur.length) return cur
      const next = [...cur]
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })
  }

  function handleConfirm() {
    // Emit in the user's order, full Activity objects, from the name lookup.
    const chosen = chosenNames.map((n) => byName[n]).filter(Boolean)
    commit({
      chosen,
      preference_text: appliedPreference || null,
    })
  }

  const chosenSet = new Set(chosenNames)
  const totalCost = chosenNames.reduce(
    (sum, n) => sum + (byName[n]?.estimated_cost_usd ?? 0),
    0
  )

  const preferenceBox = (
    <div className="mb-4">
      <Field label={t('activities.preferenceLabel')} hint={`(${t('common.optional')})`}>
        <div className="flex gap-2">
          <div className="flex-1">
            <Input
              value={preference}
              onChange={setPreference}
              placeholder={t('activities.preferencePlaceholder')}
            />
          </div>
          <button
            onClick={applyPreference}
            disabled={loading || busy}
            className="px-4 text-sm rounded-lg flex-shrink-0"
            style={{ color: '#0a0e1a', background: '#2dd4bf', opacity: (loading || busy) ? 0.5 : 1 }}
          >
            {t('activities.applyPreference')}
          </button>
        </div>
      </Field>
    </div>
  )

  return (
    <StageCard
      title={t('activities.title')}
      subtitle={t('activities.subtitle', { city })}
    >
      {preferenceBox}

      {loading ? (
        <div className="py-10 text-center text-white/50 text-sm">
          {t('common.loading')}
        </div>
      ) : (
        <>
          {/* Suggestions */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {activities.map((a) => {
              const isSelected = chosenSet.has(a.name)
              return (
                <OptionCard key={a.name} selected={isSelected} onClick={() => toggle(a.name)}>
                  <div className="flex items-start justify-between gap-2 mb-1.5">
                    <h3 className="text-white font-medium text-sm leading-snug">{a.name}</h3>
                    <div
                      style={{
                        flexShrink: 0, width: 20, height: 20, borderRadius: 6,
                        border: `2px solid ${isSelected ? '#2dd4bf' : 'rgba(255,255,255,0.25)'}`,
                        background: isSelected ? '#2dd4bf' : 'transparent',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}
                    >
                      {isSelected && (
                        <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
                          <path d="M2 6 L5 9 L10 3" stroke="#0a0e1a" strokeWidth="2"
                            strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                    </div>
                  </div>
                  <p className="text-white/55 text-xs leading-relaxed mb-3">{a.description}</p>
                  <ActivityMeta a={a} t={t} />
                </OptionCard>
              )
            })}
          </div>

          {activities.length === 0 && (
            <p className="text-white/40 text-sm text-center py-6">
              {t('activities.noneFound')}
            </p>
          )}

          {/* Regenerate / show more */}
          <div className="flex gap-4 mt-4">
            <button
              onClick={() => fetchMore('replace')}
              disabled={busy}
              className="text-sm hover:underline"
              style={{ color: '#2dd4bf', opacity: busy ? 0.5 : 1 }}
            >
              {t('activities.regenerate')}
            </button>
            <button
              onClick={() => fetchMore('append')}
              disabled={busy}
              className="text-sm hover:underline"
              style={{ color: '#2dd4bf', opacity: busy ? 0.5 : 1 }}
            >
              {t('activities.showMore')}
            </button>
            {busy && <span className="text-white/40 text-xs self-center">{t('common.loading')}</span>}
          </div>

          {/* Chosen, in order, with up/down */}
          {chosenNames.length > 0 && (
            <div className="mt-6">
              <p className="text-white/70 text-xs font-semibold uppercase tracking-widest mb-2">
                {t('activities.yourPicks')}
              </p>
              <div className="flex flex-col gap-2">
                {chosenNames.map((name, i) => {
                  const a = byName[name]
                  if (!a) return null
                  return (
                    <div
                      key={name}
                      className="flex items-center gap-3 rounded-lg px-3 py-2"
                      style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.10)' }}
                    >
                      <span className="text-white/40 text-xs w-5 flex-shrink-0">{i + 1}</span>
                      <div className="flex-1 min-w-0">
                        <span className="text-white/85 text-sm">{a.name}</span>
                      </div>
                      <div className="flex items-center gap-1 flex-shrink-0">
                        <ArrowButton dir={-1} disabled={i === 0} onClick={() => move(name, -1)} label={t('activities.moveUp')} />
                        <ArrowButton dir={1} disabled={i === chosenNames.length - 1} onClick={() => move(name, 1)} label={t('activities.moveDown')} />
                        <button
                          onClick={() => toggle(name)}
                          aria-label={t('activities.removeActivity')}
                          className="ml-1 text-white/40 hover:text-white/80 text-lg leading-none px-1"
                        >
                          ×
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Summary */}
          <div className="flex items-center justify-between mt-4 text-sm">
            <span className="text-white/55">
              {t('activities.selected', { count: chosenNames.length })}
            </span>
            {chosenNames.length > 0 && (
              <span className="text-white/70">
                {t('activities.estimatedCost')}: <span className="font-semibold">${totalCost}</span>
              </span>
            )}
          </div>
        </>
      )}

      {/* Activities may be skipped or left empty (min_length 0), so no disable */}
      <StageActions
        onConfirm={handleConfirm}
        confirmLabel={t('activities.confirmSelection')}
        onSkip={skip}
        onForward={forward}
        transitioning={transitioning}
      />
    </StageCard>
  )
}

// Small square arrow button for reordering a pick.
function ArrowButton({ dir, disabled, onClick, label }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className="flex items-center justify-center rounded"
      style={{
        width: 24, height: 24,
        background: disabled ? 'transparent' : 'rgba(255,255,255,0.08)',
        opacity: disabled ? 0.25 : 1,
        cursor: disabled ? 'default' : 'pointer',
      }}
    >
      <svg width="10" height="10" viewBox="0 0 10 10" fill="none"
        style={{ transform: dir === 1 ? 'rotate(180deg)' : 'none' }}>
        <path d="M5 2 L5 8 M2 5 L5 2 L8 5" stroke="#fff" strokeWidth="1.4"
          strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  )
}