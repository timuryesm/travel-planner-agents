import React from 'react'
import { useTranslation } from 'react-i18next'

// ─────────────────────────────────────────────────────────────────────────────
// Stage components — barrel file
// ─────────────────────────────────────────────────────────────────────────────
// Real implementations are imported and re-exported here. Stages not yet built
// fall back to PlaceholderStage.
//
//   12a  SetupStage, DestinationStage                          ← done
//   12b  FlightsStage, AccommodationStage, ActivitiesStage      ← done
//   12c  DailyPlanStage, ReconciliationStage, FinalStage        ← next

import SetupStageImpl from './SetupStage'
import DestinationStageImpl from './DestinationStage'
import FlightsStageImpl from './FlightsStage'
import AccommodationStageImpl from './AccommodationStage'
import ActivitiesStageImpl from './ActivitiesStage'

// ── Placeholder for stages not yet implemented ────────────────────────────────

function PlaceholderStage({ stageKey, commit, skip, forward, commitData, stop, transitioning }) {
  const { t } = useTranslation()

  return (
    <div className="glass-card p-8" style={{ maxWidth: 720, width: '100%' }}>
      <h2 className="text-2xl font-semibold text-white text-glow">
        {t(`stages.${stageKey}`)}
        {stop && <span className="text-white/50 font-normal"> · {stop.city}</span>}
      </h2>

      <p className="text-white/50 text-sm mt-2">
        Placeholder — real UI arrives in the next sub-step.
      </p>

      {commitData && (
        <pre
          className="mt-4 text-xs text-white/60 overflow-x-auto rounded-lg p-3"
          style={{ background: 'rgba(0,0,0,0.25)' }}
        >
          {JSON.stringify(commitData, null, 2)}
        </pre>
      )}

      <div className="flex items-center gap-3 mt-8 pt-6"
        style={{ borderTop: '1px solid rgba(255,255,255,0.08)' }}>
        <button
          onClick={() => commit({ placeholder: true, stage: stageKey })}
          disabled={transitioning}
          className="px-5 py-2.5 rounded-lg text-sm font-semibold text-white"
          style={{
            background: transitioning
              ? 'rgba(45,212,191,0.4)'
              : 'linear-gradient(135deg, #2dd4bf, #38bdf8)',
            opacity: transitioning ? 0.7 : 1,
          }}
        >
          {transitioning ? t('common.loading') : t('common.confirm')}
        </button>

        <button
          onClick={skip}
          disabled={transitioning}
          className="px-4 py-2.5 rounded-lg text-sm font-medium text-white/65 hover:text-white"
          style={{ background: 'rgba(255,255,255,0.07)' }}
        >
          {t('common.skip')}
        </button>

        <button
          onClick={forward}
          disabled={transitioning}
          className="ml-auto px-3 py-2.5 rounded-lg text-sm font-medium text-white/40 hover:text-white/70"
        >
          {t('common.next')} →
        </button>
      </div>
    </div>
  )
}

// ── Exports ───────────────────────────────────────────────────────────────────

export const SetupStage         = SetupStageImpl
export const DestinationStage   = DestinationStageImpl
export const FlightsStage       = FlightsStageImpl
export const AccommodationStage = AccommodationStageImpl
export const ActivitiesStage    = ActivitiesStageImpl

// Still placeholders — replaced in 12c
export const DailyPlanStage      = (p) => <PlaceholderStage {...p} stageKey="daily_plan" />
export const ReconciliationStage = (p) => <PlaceholderStage {...p} stageKey="reconciliation" />
export const FinalStage          = (p) => <PlaceholderStage {...p} stageKey="final" />