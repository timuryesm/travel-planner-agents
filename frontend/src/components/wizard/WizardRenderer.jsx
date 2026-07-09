import React, { useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { motion, AnimatePresence } from 'framer-motion'
import useTripStore from '../../store/tripStore'

// Stage components — implemented in Step 12.
// Until then a shared placeholder stands in for each, so the renderer, the
// store, and the transition wiring can be tested end-to-end first.
import {
  SetupStage,
  DestinationStage,
  FlightsStage,
  AccommodationStage,
  ActivitiesStage,
  DailyPlanStage,
  ReconciliationStage,
  FinalStage,
} from './stages'

// ─────────────────────────────────────────────────────────────────────────────
// WizardRenderer — the stage dispatcher
// ─────────────────────────────────────────────────────────────────────────────
// Reads current_stage from the store and renders the matching component.
// Every stage component receives the same prop contract:
//
//   commit(data, selfProvidedText?) — commit as 'chosen' (or 'self_provided'
//                                     if text is passed), then advance
//   skip()                          — mark skipped, advance
//   forward()                       — advance without committing
//   commitData                      — the existing commit_data for this stage,
//                                     if the user is revisiting it (else null)
//   stop                            — the Stop object for stop-level stages
//   setupData                       — the committed setup payload (dates,
//                                     travelers, budget) that later stages need
//   transitioning                   — true while a transition is in flight
//
// Direction: advancing slides left, going back slides right. We track the
// previous position index to know which way we moved.

const STAGE_COMPONENTS = {
  setup: SetupStage,
  destination: DestinationStage,
  flights: FlightsStage,
  accommodation: AccommodationStage,
  activities: ActivitiesStage,
  daily_plan: DailyPlanStage,
  reconciliation: ReconciliationStage,
  final: FinalStage,
}

// Mirrors the backend's flattened_sequence() so we can compare positions
const PRE = ['setup', 'destination']
const STOP_STAGES = ['flights', 'accommodation', 'activities', 'daily_plan']
const POST = ['reconciliation', 'final']

function sequenceIndex(stage, stopIndex, numStops) {
  if (stopIndex === null) {
    const pre = PRE.indexOf(stage)
    if (pre >= 0) return pre
    const post = POST.indexOf(stage)
    if (post >= 0) return PRE.length + numStops * STOP_STAGES.length + post
    return -1
  }
  const s = STOP_STAGES.indexOf(stage)
  if (s < 0) return -1
  return PRE.length + stopIndex * STOP_STAGES.length + s
}

export default function WizardRenderer() {
  const { t } = useTranslation()
  const trip = useTripStore((s) => s.trip)
  const transitioning = useTripStore((s) => s.transitioning)
  const error = useTripStore((s) => s.error)

  const commitFn = useTripStore((s) => s.commit)
  const skipFn = useTripStore((s) => s.skip)
  const forwardFn = useTripStore((s) => s.forward)

  const currentCommit = useTripStore((s) => s.currentCommit)
  const currentStop = useTripStore((s) => s.currentStop)
  const setupData = useTripStore((s) => s.setupData)

  // Track movement direction for the slide animation
  const prevIdxRef = useRef(0)
  const numStops = trip?.stops?.length ?? 0
  const idx = trip
    ? sequenceIndex(trip.current_stage, trip.current_stop_index, numStops)
    : 0
  const direction = idx >= prevIdxRef.current ? 1 : -1

  useEffect(() => {
    prevIdxRef.current = idx
  }, [idx])

  if (!trip) {
    return (
      <div className="glass-card p-8 max-w-md">
        <p className="text-white/60 text-sm">{t('common.loading')}</p>
      </div>
    )
  }

  const StageComponent = STAGE_COMPONENTS[trip.current_stage]

  if (!StageComponent) {
    return (
      <div className="glass-card p-8 max-w-md">
        <p className="text-white/60 text-sm">
          {t('errors.generic')} (unknown stage: {trip.current_stage})
        </p>
      </div>
    )
  }

  // `commit` accepts an optional free-text second arg. When present the commit
  // type flips to 'self_provided' — this is how the "I booked my own" path and
  // the reconciliation "write my own" door are expressed.
  const commit = (data, selfProvidedText = null) =>
    commitFn(
      selfProvidedText ? 'self_provided' : 'chosen',
      data ?? {},
      selfProvidedText
    )

  // A stable key so AnimatePresence knows when the position actually changed
  const stageKey =
    trip.current_stop_index === null
      ? trip.current_stage
      : `${trip.current_stage}-${trip.current_stop_index}`

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      {/* Error banner */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="glass-card mb-4 px-4 py-3"
            style={{ borderColor: 'rgba(251,113,133,0.4)' }}
          >
            <p className="text-sm" style={{ color: '#fb7185' }}>
              {t(error)}
            </p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Stage content — slides left on advance, right on back */}
      <AnimatePresence mode="wait" custom={direction}>
        <motion.div
          key={stageKey}
          custom={direction}
          initial={{ opacity: 0, x: direction * 40 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: direction * -40 }}
          transition={{ duration: 0.28, ease: 'easeOut' }}
        >
          <StageComponent
            commit={commit}
            skip={skipFn}
            forward={forwardFn}
            commitData={currentCommit()?.commit_data ?? null}
            stop={currentStop()}
            setupData={setupData()}
            transitioning={transitioning}
          />
        </motion.div>
      </AnimatePresence>
    </div>
  )
}