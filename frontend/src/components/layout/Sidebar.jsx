import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { motion, AnimatePresence } from 'framer-motion'

// ─────────────────────────────────────────────────────────────────────────────
// Sidebar — wizard navigation
// ─────────────────────────────────────────────────────────────────────────────
// Renders the flattened stage sequence as grouped, status-marked nav items:
//
//   Trip setup      → setup, destination            (trip-level)
//   <City name>     → flights, accommodation,        (one group per stop)
//                     activities, daily_plan
//   Finishing up    → reconciliation, final          (trip-level)
//
// Each stage shows a status dot derived from its commit_type:
//   unvisited  → hollow grey
//   current    → pulsing teal ring (the trip's current position)
//   completed  → filled teal (chosen / self_provided / skipped, completed=true)
//   skipped    → amber dash
//
// Clicking a *completed* stage that is BEFORE the current position triggers the
// blast-radius modal: it lists every downstream stage that would be reset, and
// only on confirm calls onNavigateBack (which the parent wires to a BACK
// transition). Forward stages and the current stage are not clickable.
//
// Props:
//   trip            — TripDetailResponse (current_stage, current_stop_index,
//                     multi_city, trip_stage_commits[], stops[])
//   onNavigateBack  — (targetStage, targetStopIndex) => void
//
// If trip is null (no trip loaded yet), renders just the section skeleton.

const STOP_STAGES = ['flights', 'accommodation', 'activities', 'daily_plan']
const PRE_STAGES = ['setup', 'destination']
const POST_STAGES = ['reconciliation', 'final']

// Build the full ordered position list so we can compute "before/after current"
// and the blast radius. Mirrors the backend's flattened_sequence().
function buildSequence(numStops) {
  const seq = []
  PRE_STAGES.forEach((s) => seq.push({ stage: s, stopIndex: null }))
  for (let i = 0; i < numStops; i++) {
    STOP_STAGES.forEach((s) => seq.push({ stage: s, stopIndex: i }))
  }
  POST_STAGES.forEach((s) => seq.push({ stage: s, stopIndex: null }))
  return seq
}

function positionIndex(seq, stage, stopIndex) {
  return seq.findIndex(
    (p) => p.stage === stage && p.stopIndex === stopIndex
  )
}

// Look up a commit's status for a given position from the trip object
function getCommit(trip, stage, stopIndex) {
  if (stopIndex === null) {
    return trip.trip_stage_commits.find((c) => c.stage === stage) || null
  }
  const stop = trip.stops.find((s) => s.stop_index === stopIndex)
  if (!stop) return null
  return stop.stage_commits.find((c) => c.stage === stage) || null
}

// ─────────────────────────────────────────────────────────────────────────────
// Status dot
// ─────────────────────────────────────────────────────────────────────────────
function StatusDot({ status }) {
  const cls =
    status === 'current'   ? 'dot-current'   :
    status === 'completed' ? 'dot-complete'  :
    status === 'skipped'   ? 'dot-skipped'   :
                             'dot-unvisited'
  return <span className={cls} />
}

// ─────────────────────────────────────────────────────────────────────────────
// One stage row
// ─────────────────────────────────────────────────────────────────────────────
function StageRow({ label, status, clickable, onClick }) {
  return (
    <button
      onClick={clickable ? onClick : undefined}
      disabled={!clickable}
      className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors"
      style={{
        cursor: clickable ? 'pointer' : 'default',
        background: status === 'current' ? 'rgba(45,212,191,0.10)' : 'transparent',
      }}
      onMouseEnter={(e) => {
        if (clickable) e.currentTarget.style.background = 'rgba(255,255,255,0.06)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background =
          status === 'current' ? 'rgba(45,212,191,0.10)' : 'transparent'
      }}
    >
      <StatusDot status={status} />
      <span
        className="flex-1 text-sm"
        style={{
          color:
            status === 'current'    ? '#ffffff' :
            status === 'unvisited'  ? 'rgba(255,255,255,0.45)' :
                                      'rgba(255,255,255,0.78)',
          fontWeight: status === 'current' ? 600 : 400,
        }}
      >
        {label}
      </span>
    </button>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Blast-radius modal
// ─────────────────────────────────────────────────────────────────────────────
function BlastRadiusModal({ affectedLabels, onConfirm, onCancel }) {
  const { t } = useTranslation()
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(0,0,0,0.5)',
        backdropFilter: 'blur(4px)',
      }}
      onClick={onCancel}
    >
      <motion.div
        initial={{ scale: 0.94, y: 10 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.94, y: 10 }}
        transition={{ duration: 0.2 }}
        onClick={(e) => e.stopPropagation()}
        className="glass-card"
        style={{ maxWidth: 420, width: '90%', padding: 28 }}
      >
        <div className="flex items-start gap-3 mb-4">
          {/* Warning icon */}
          <div
            style={{
              flexShrink: 0,
              width: 36, height: 36, borderRadius: 10,
              background: 'rgba(251,191,36,0.16)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path d="M10 2 L18 17 L2 17 Z" stroke="#fbbf24" strokeWidth="1.6"
                strokeLinejoin="round" />
              <path d="M10 8 L10 12" stroke="#fbbf24" strokeWidth="1.6"
                strokeLinecap="round" />
              <circle cx="10" cy="14.5" r="0.9" fill="#fbbf24" />
            </svg>
          </div>
          <div>
            <h3 className="text-white font-semibold text-base leading-snug">
              {t('blastRadius.title')}
            </h3>
          </div>
        </div>

        <p className="text-white/65 text-sm mb-3">
          {t('blastRadius.description')}
        </p>

        {/* Affected stages list */}
        <div
          style={{
            background: 'rgba(0,0,0,0.2)',
            borderRadius: 10,
            padding: '10px 14px',
            marginBottom: 22,
            maxHeight: 160,
            overflowY: 'auto',
          }}
        >
          {affectedLabels.map((label, i) => (
            <div key={i} className="flex items-center gap-2 py-1">
              <span
                style={{
                  width: 5, height: 5, borderRadius: '50%',
                  background: '#fb7185', flexShrink: 0,
                }}
              />
              <span className="text-white/75 text-sm">{label}</span>
            </div>
          ))}
        </div>

        <div className="flex gap-3 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white/70 hover:text-white transition-colors"
          >
            {t('blastRadius.keepEditing')}
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors"
            style={{ background: 'rgba(251,113,133,0.9)' }}
          >
            {t('blastRadius.confirmBack')}
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Sidebar
// ─────────────────────────────────────────────────────────────────────────────
export default function Sidebar({ trip, onNavigateBack }) {
  const { t } = useTranslation()
  const [pendingTarget, setPendingTarget] = useState(null)

  const numStops = trip?.stops?.length ?? 0
  const seq = buildSequence(numStops)
  const currentIdx = trip
    ? positionIndex(seq, trip.current_stage, trip.current_stop_index)
    : -1

  // Resolve the display status for a position
  function statusFor(stage, stopIndex) {
    if (
      trip &&
      trip.current_stage === stage &&
      trip.current_stop_index === stopIndex
    ) {
      return 'current'
    }
    const commit = trip ? getCommit(trip, stage, stopIndex) : null
    if (!commit) return 'unvisited'
    if (commit.commit_type === 'skipped') return 'skipped'
    if (commit.completed) return 'completed'
    return 'unvisited'
  }

  // A stage is clickable if it's completed/skipped AND strictly before current
  function isClickable(stage, stopIndex) {
    if (!trip) return false
    const idx = positionIndex(seq, stage, stopIndex)
    if (idx < 0 || idx >= currentIdx) return false
    const status = statusFor(stage, stopIndex)
    return status === 'completed' || status === 'skipped'
  }

  // When a completed past stage is clicked, compute the blast radius and open
  // the modal instead of navigating immediately.
  function requestNavigate(stage, stopIndex) {
    const targetIdx = positionIndex(seq, stage, stopIndex)
    const affected = seq
      .slice(targetIdx + 1)
      .filter((p) => {
        // Only warn about stages that actually hold data / are completed
        const s = statusFor(p.stage, p.stopIndex)
        return s === 'completed' || s === 'skipped' || s === 'current'
      })
      .map((p) => stageLabel(p.stage, p.stopIndex))
    setPendingTarget({ stage, stopIndex, affected })
  }

  function confirmNavigate() {
    if (pendingTarget) {
      onNavigateBack(pendingTarget.stage, pendingTarget.stopIndex)
      setPendingTarget(null)
    }
  }

  // Human label for a stage, with city name for stop-level stages
  function stageLabel(stage, stopIndex) {
    const base = t(`stages.${stage}`)
    if (stopIndex === null) return base
    const stop = trip?.stops?.find((s) => s.stop_index === stopIndex)
    const city = stop?.city
    return city ? `${base} · ${city}` : base
  }

  // ── Render a group of stage rows ──
  function renderGroup(positions) {
    return positions.map(({ stage, stopIndex }) => {
      const key = stopIndex === null ? stage : `${stage}-${stopIndex}`
      const status = statusFor(stage, stopIndex)
      const clickable = isClickable(stage, stopIndex)
      return (
        <StageRow
          key={key}
          label={t(`stages.${stage}`)}
          status={status}
          clickable={clickable}
          onClick={() => requestNavigate(stage, stopIndex)}
        />
      )
    })
  }

  return (
    <div className="flex flex-col h-full">
      {/* App name */}
      <div className="px-2 mb-5">
        <h1 className="text-white font-semibold text-lg tracking-tight">
          {t('app.name')}
        </h1>
      </div>

      <nav className="flex-1 flex flex-col gap-5 overflow-y-auto">
        {/* Trip setup */}
        <div>
          <p className="text-white/35 text-[11px] font-semibold uppercase tracking-widest px-2 mb-1.5">
            {t('sidebar.tripSetup')}
          </p>
          {renderGroup(PRE_STAGES.map((s) => ({ stage: s, stopIndex: null })))}
        </div>

        {/* One group per stop */}
        {trip?.stops
          ?.slice()
          .sort((a, b) => a.stop_index - b.stop_index)
          .map((stop) => (
            <div key={stop.id ?? stop.stop_index}>
              <p className="text-white/35 text-[11px] font-semibold uppercase tracking-widest px-2 mb-1.5">
                {stop.city || `${t('sidebar.stop')} ${stop.stop_index + 1}`}
              </p>
              {renderGroup(
                STOP_STAGES.map((s) => ({ stage: s, stopIndex: stop.stop_index }))
              )}
            </div>
          ))}

        {/* Finishing up */}
        <div>
          <p className="text-white/35 text-[11px] font-semibold uppercase tracking-widest px-2 mb-1.5">
            {t('sidebar.finishingUp')}
          </p>
          {renderGroup(POST_STAGES.map((s) => ({ stage: s, stopIndex: null })))}
        </div>
      </nav>

      {/* Blast-radius modal */}
      <AnimatePresence>
        {pendingTarget && (
          <BlastRadiusModal
            affectedLabels={pendingTarget.affected}
            onConfirm={confirmNavigate}
            onCancel={() => setPendingTarget(null)}
          />
        )}
      </AnimatePresence>
    </div>
  )
}