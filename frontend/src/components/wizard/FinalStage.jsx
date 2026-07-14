import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, Textarea } from './primitives'
import useTripStore from '../../store/tripStore'

// ─────────────────────────────────────────────────────────────────────────────
// ReconciliationStage — the pre-final gate
// ─────────────────────────────────────────────────────────────────────────────
// Scans all stop-level stages for ones needing attention (NAG_BOTH policy:
// skipped OR unvisited) and offers three doors per stage:
//   1. Add it now   → BACK to that stage (jump back to fill it in)
//   2. Write my own → free-text capture → self_provided commit on that stage
//   3. Leave it out → no change; it stays out of the plan
//
// When nothing needs attention, shows an "all good" state and the assemble
// button. Committing this stage (FORWARD via confirm) advances to final,
// which triggers plan assembly on the backend.
//
// This stage reaches into the store directly (rather than only using the
// passed props) because its actions target OTHER stages' commits, not its own:
//   - "Add it now" is a BACK transition to a stop-level stage
//   - "Write my own" needs to commit to a specific stop stage, then return
// The store exposes back() and a helper to commit to an arbitrary position is
// not available, so "write my own" uses BACK then the target stage handles it.
// For v1 simplicity, "write my own" here jumps back to the stage (same as
// "add it now") where the user can use that stage's own self-provided path.

const STOP_STAGES = ['flights', 'accommodation', 'activities', 'daily_plan']

// Collect all stop-level stages that are skipped or unvisited (NAG_BOTH)
function findIncompleteStages(trip) {
  if (!trip) return []
  const out = []
  const stops = [...trip.stops].sort((a, b) => a.stop_index - b.stop_index)
  for (const stop of stops) {
    for (const stageName of STOP_STAGES) {
      const commit = stop.stage_commits.find((c) => c.stage === stageName)
      if (!commit) continue
      const type = commit.commit_type
      if (type === 'skipped' || type === 'unvisited') {
        out.push({
          stage: stageName,
          stopIndex: stop.stop_index,
          city: stop.city,
          type,
        })
      }
    }
  }
  return out
}

export default function ReconciliationStage({ commit, transitioning }) {
  const { t } = useTranslation()
  const trip = useTripStore((s) => s.trip)
  const back = useTripStore((s) => s.back)

  const incomplete = findIncompleteStages(trip)

  // Track which stage the user is writing their own text for
  const [writingFor, setWritingFor] = useState(null)  // {stage, stopIndex} | null
  const [ownText, setOwnText] = useState('')

  // "Add it now" — jump back to the stage to fill it in properly
  function addNow(stage, stopIndex) {
    back(stage, stopIndex)
  }

  // "Write my own" — for v1, jump back to the stage where the user can use
  // that stage's built-in self-provided path. (A future refinement could
  // commit self_provided text directly from here.)
  function writeOwn(stage, stopIndex) {
    setWritingFor({ stage, stopIndex })
    setOwnText('')
  }

  function submitOwn() {
    if (writingFor) {
      // Jump to the stage so the user completes it with their own text there
      back(writingFor.stage, writingFor.stopIndex)
      setWritingFor(null)
    }
  }

  // "Assemble" — commit reconciliation (advances to final → assembly)
  function handleAssemble() {
    commit({})
  }

  const stageLabel = (stage, city) => `${t(`stages.${stage}`)} · ${city}`

  return (
    <StageCard
      title={t('reconciliation.title')}
      subtitle={
        incomplete.length > 0
          ? t('reconciliation.subtitle')
          : t('reconciliation.allComplete')
      }
    >
      {incomplete.length === 0 ? (
        // ── All complete ──
        <div className="flex flex-col items-center py-8 text-center">
          <div
            style={{
              width: 56, height: 56, borderRadius: '50%',
              background: 'rgba(45,212,191,0.15)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              marginBottom: 16,
            }}
          >
            <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
              <path d="M7 14 L12 19 L21 9" stroke="#2dd4bf" strokeWidth="2.5"
                strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <p className="text-white/70 text-sm mb-6">{t('reconciliation.allComplete')}</p>
          <button
            onClick={handleAssemble}
            disabled={transitioning}
            className="px-6 py-3 rounded-lg text-sm font-semibold text-white"
            style={{
              background: transitioning
                ? 'rgba(45,212,191,0.4)'
                : 'linear-gradient(135deg, #2dd4bf, #38bdf8)',
              opacity: transitioning ? 0.7 : 1,
            }}
          >
            {transitioning ? t('common.loading') : t('reconciliation.assemblePlan')}
          </button>
        </div>
      ) : (
        // ── Stages needing attention ──
        <div className="flex flex-col gap-3">
          {incomplete.map(({ stage, stopIndex, city, type }) => {
            const isWriting =
              writingFor?.stage === stage && writingFor?.stopIndex === stopIndex
            return (
              <div
                key={`${stage}-${stopIndex}`}
                className="rounded-xl p-4"
                style={{
                  background: 'rgba(255,255,255,0.05)',
                  border: '1px solid rgba(251,191,36,0.25)',
                }}
              >
                <div className="flex items-center gap-2 mb-3">
                  <span className="dot-skipped" />
                  <span className="text-white font-medium text-sm">
                    {stageLabel(stage, city)}
                  </span>
                  <span className="text-white/35 text-xs ml-auto">
                    {t(`stageStatus.${type === 'skipped' ? 'skipped' : 'unvisited'}`)}
                  </span>
                </div>

                {!isWriting ? (
                  <div className="flex gap-2 flex-wrap">
                    <button
                      onClick={() => addNow(stage, stopIndex)}
                      disabled={transitioning}
                      className="px-3 py-1.5 rounded-lg text-xs font-medium text-white"
                      style={{ background: 'rgba(45,212,191,0.2)' }}
                    >
                      {t('reconciliation.addNow')}
                    </button>
                    <button
                      onClick={() => writeOwn(stage, stopIndex)}
                      disabled={transitioning}
                      className="px-3 py-1.5 rounded-lg text-xs font-medium text-white/70 hover:text-white"
                      style={{ background: 'rgba(255,255,255,0.08)' }}
                    >
                      {t('reconciliation.writeOwn')}
                    </button>
                    <span className="px-3 py-1.5 text-xs text-white/40">
                      {t('reconciliation.skipForGood')}
                    </span>
                  </div>
                ) : (
                  <div className="flex flex-col gap-2">
                    <Textarea
                      value={ownText}
                      onChange={setOwnText}
                      placeholder={t('reconciliation.writeOwnPlaceholder')}
                      rows={2}
                    />
                    <div className="flex gap-2">
                      <button
                        onClick={submitOwn}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium text-white"
                        style={{ background: 'rgba(45,212,191,0.25)' }}
                      >
                        {t('common.continue')}
                      </button>
                      <button
                        onClick={() => setWritingFor(null)}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium text-white/60"
                      >
                        {t('common.cancel')}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}

          {/* Assemble anyway — leave the remaining stages out */}
          <button
            onClick={handleAssemble}
            disabled={transitioning}
            className="mt-3 px-6 py-3 rounded-lg text-sm font-semibold text-white self-start"
            style={{
              background: transitioning
                ? 'rgba(45,212,191,0.4)'
                : 'linear-gradient(135deg, #2dd4bf, #38bdf8)',
              opacity: transitioning ? 0.7 : 1,
            }}
          >
            {transitioning ? t('common.loading') : t('reconciliation.assemblePlan')}
          </button>
        </div>
      )}
    </StageCard>
  )
}