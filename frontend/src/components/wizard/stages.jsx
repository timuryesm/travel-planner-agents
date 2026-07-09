import React from 'react'
import { useTranslation } from 'react-i18next'

// ─────────────────────────────────────────────────────────────────────────────
// Stage components — PLACEHOLDERS
// ─────────────────────────────────────────────────────────────────────────────
// Step 12 replaces each of these with a real implementation. For now they all
// share one generic component so the store, the renderer, and the transition
// wiring can be tested end-to-end against the live backend before any
// stage-specific UI exists.
//
// Every stage receives the same prop contract (see WizardRenderer):
//   commit(data, selfProvidedText?) · skip() · forward()
//   commitData · stop · setupData · transitioning

function PlaceholderStage({ stageKey, commit, skip, forward, commitData, stop, transitioning }) {
  const { t } = useTranslation()

  return (
    <div className="glass-card p-8 max-w-2xl">
      <h2 className="text-2xl font-semibold text-white text-glow">
        {t(`stages.${stageKey}`)}
        {stop && <span className="text-white/50 font-normal"> · {stop.city}</span>}
      </h2>

      <p className="text-white/50 text-sm mt-2">
        Placeholder — real UI arrives in Step 12.
      </p>

      {/* Show existing commit data when revisiting a completed stage */}
      {commitData && (
        <pre
          className="mt-4 text-xs text-white/60 overflow-x-auto rounded-lg p-3"
          style={{ background: 'rgba(0,0,0,0.25)' }}
        >
          {JSON.stringify(commitData, null, 2)}
        </pre>
      )}

      {/* Transition controls — exercise all three forward paths */}
      <div className="flex gap-3 mt-7">
        <button
          onClick={() => commit({ placeholder: true, stage: stageKey })}
          disabled={transitioning}
          className="px-4 py-2 rounded-lg text-sm font-semibold text-white"
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
          className="px-4 py-2 rounded-lg text-sm font-medium text-white/70 hover:text-white"
          style={{ background: 'rgba(255,255,255,0.08)' }}
        >
          {t('common.skip')}
        </button>

        <button
          onClick={forward}
          disabled={transitioning}
          className="px-4 py-2 rounded-lg text-sm font-medium text-white/50 hover:text-white/80"
        >
          {t('common.next')} →
        </button>
      </div>
    </div>
  )
}

// One named export per stage, matching STAGE_COMPONENTS in WizardRenderer
export const SetupStage          = (p) => <PlaceholderStage {...p} stageKey="setup" />
export const DestinationStage    = (p) => <PlaceholderStage {...p} stageKey="destination" />
export const FlightsStage        = (p) => <PlaceholderStage {...p} stageKey="flights" />
export const AccommodationStage  = (p) => <PlaceholderStage {...p} stageKey="accommodation" />
export const ActivitiesStage     = (p) => <PlaceholderStage {...p} stageKey="activities" />
export const DailyPlanStage      = (p) => <PlaceholderStage {...p} stageKey="daily_plan" />
export const ReconciliationStage = (p) => <PlaceholderStage {...p} stageKey="reconciliation" />
export const FinalStage          = (p) => <PlaceholderStage {...p} stageKey="final" />