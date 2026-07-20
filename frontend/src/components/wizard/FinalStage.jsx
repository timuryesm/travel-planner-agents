import React, { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, StageActions } from './primitives'
import { assembleTrip } from '../../api/client'
import useTripStore from '../../store/tripStore'

// ─────────────────────────────────────────────────────────────────────────────
// FinalStage — assemble and confirm the itinerary
// ─────────────────────────────────────────────────────────────────────────────
// Two-step by design (see the assemble route): POST /assemble GENERATES the
// itinerary + budget and returns them; committing this stage PERSISTS them as
// FinalCommitData. Keeping the itinerary in the commit means transition()'s
// cascade-invalidate handles staleness — go BACK and change the hotel, and the
// final commit is invalidated like any other downstream stage.
//
// So this component:
//   - on mount (fresh), calls /assemble and shows the result unsaved
//   - on revisit, renders the SAVED commit without paying to regenerate
//   - Regenerate re-runs /assemble (an explicit, paid choice)
//   - Confirm commits the currently-shown result as FinalCommitData
//
// Replaces the old ReconciliationStage, which the redesign dropped: with only
// activities skippable per stop, there was nothing left to reconcile.
//
// Minimal markdown rendering, no dependency: the itinerary is Claude-authored
// markdown, rendered by a small formatter below. A real markdown lib is a
// deployment-time nicety (Track 4), not needed to prove the flow.

export default function FinalStage({ commit, commitData, transitioning }) {
  const { t } = useTranslation()
  const trip = useTripStore((s) => s.trip)

  // Saved commit on revisit, else null until /assemble returns.
  const saved = commitData?.itinerary_markdown ? commitData : null

  const [result, setResult] = useState(saved) // { itinerary_markdown, budget, generated_at }
  const [loading, setLoading] = useState(!saved)
  const [failed, setFailed] = useState(false)

  const runAssemble = useCallback((force = false) => {
    let cancelled = false
    setLoading(true)
    setFailed(false)
    assembleTrip(trip.id, { force })
      .then((r) => { if (!cancelled) setResult(r) })
      .catch(() => { if (!cancelled) setFailed(true) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [trip.id])

  // Assemble on first mount only when there's no saved plan to show.
  useEffect(() => {
    if (saved) return
    const cleanup = runAssemble()
    return cleanup
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleConfirm() {
    if (!result) return
    // Commit exactly what's shown. Shape already matches FinalCommitData.
    commit({
      itinerary_markdown: result.itinerary_markdown,
      budget: result.budget,
      generated_at: result.generated_at,
    })
  }

  if (loading) {
    return (
      <StageCard title={t('final.title')} subtitle={t('final.assembling')}>
        <div className="py-12 text-center text-white/50 text-sm">
          {t('final.assemblingDetail')}
        </div>
      </StageCard>
    )
  }

  if (failed || !result) {
    return (
      <StageCard title={t('final.title')} subtitle={t('final.subtitle')}>
        <div className="py-12 text-center">
          <p className="text-white/60 text-sm mb-4">{t('final.assembleFailed')}</p>
          <button
            onClick={() => runAssemble(true)}
            className="text-sm hover:underline"
            style={{ color: '#2dd4bf' }}
          >
            {t('common.retry')}
          </button>
        </div>
      </StageCard>
    )
  }

  const b = result.budget
  const overBudget = b && b.within_budget === false

  return (
    <StageCard title={t('final.title')} subtitle={t('final.subtitle')}>
      {/* Budget banner */}
      {b && (
        <div
          className="rounded-xl px-4 py-3 mb-4 flex items-center justify-between"
          style={{
            background: overBudget ? 'rgba(251,113,133,0.12)' : 'rgba(45,212,191,0.12)',
            border: `1px solid ${overBudget ? 'rgba(251,113,133,0.3)' : 'rgba(45,212,191,0.3)'}`,
          }}
        >
          <span className="text-white/80 text-sm font-medium">
            {t('final.total')}: ${b.total_usd?.toLocaleString()}
          </span>
          <span
            className="text-xs font-semibold"
            style={{ color: overBudget ? '#fb7185' : '#2dd4bf' }}
          >
            {overBudget ? t('final.overBudget') : t('final.withinBudget')}
          </span>
        </div>
      )}

      {/* Itinerary */}
      <div
        className="rounded-xl px-5 py-4 mb-4 overflow-y-auto"
        style={{
          background: 'rgba(255,255,255,0.04)',
          border: '1px solid rgba(255,255,255,0.10)',
          maxHeight: '52vh',
        }}
      >
        <Markdown text={result.itinerary_markdown} />
      </div>

      <div className="flex items-center gap-4 mb-2">
        <button
          onClick={() => runAssemble(true)}
          disabled={transitioning}
          className="text-sm hover:underline"
          style={{ color: '#2dd4bf', opacity: transitioning ? 0.5 : 1 }}
        >
          {t('final.regenerate')}
        </button>
        {result.generated_at && (
          <span className="text-white/30 text-xs">
            {t('final.generatedAt')}: {new Date(result.generated_at).toLocaleString()}
          </span>
        )}
      </div>

      <StageActions
        onConfirm={handleConfirm}
        confirmLabel={t('final.confirmPlan')}
        showSkip={false}
        showForward={false}
        transitioning={transitioning}
      />
    </StageCard>
  )
}

// ── Tiny markdown renderer ────────────────────────────────────────────────────
// Handles the subset Claude emits for the itinerary: #/##/### headings, bold,
// bullet lists, tables (pipe syntax), and paragraphs. Intentionally small — a
// full markdown dependency is a Track-4 polish, not a correctness need.
function Markdown({ text }) {
  const blocks = []
  const lines = (text || '').split('\n')
  let i = 0
  let key = 0

  const inline = (s) =>
    s.split(/(\*\*[^*]+\*\*)/g).map((part, k) =>
      part.startsWith('**') && part.endsWith('**') ? (
        <strong key={k} className="text-white">{part.slice(2, -2)}</strong>
      ) : (
        <React.Fragment key={k}>{part}</React.Fragment>
      )
    )

  while (i < lines.length) {
    const line = lines[i]

    if (/^#{1,3}\s/.test(line)) {
      const level = line.match(/^#+/)[0].length
      const content = line.replace(/^#+\s/, '')
      const size = level === 1 ? 'text-lg' : level === 2 ? 'text-base' : 'text-sm'
      blocks.push(
        <h3 key={key++} className={`${size} font-semibold text-white mt-4 mb-2 first:mt-0`}>
          {inline(content)}
        </h3>
      )
      i++
      continue
    }

    // Table: a header row followed by a |---| separator
    if (line.includes('|') && lines[i + 1] && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1])) {
      const rows = []
      const header = line
      i += 2 // skip header + separator
      while (i < lines.length && lines[i].includes('|')) {
        rows.push(lines[i]); i++
      }
      const cells = (r) => r.split('|').map((c) => c.trim()).filter((c, idx, arr) => !(idx === 0 && c === '') && !(idx === arr.length - 1 && c === ''))
      blocks.push(
        <table key={key++} className="w-full text-xs my-3 border-collapse">
          <thead>
            <tr>{cells(header).map((c, k) => (
              <th key={k} className="text-left text-white/70 font-semibold py-1 pr-4 border-b border-white/15">{inline(c)}</th>
            ))}</tr>
          </thead>
          <tbody>{rows.map((r, k) => (
            <tr key={k}>{cells(r).map((c, ck) => (
              <td key={ck} className="text-white/60 py-1 pr-4 border-b border-white/5">{inline(c)}</td>
            ))}</tr>
          ))}</tbody>
        </table>
      )
      continue
    }

    if (/^\s*[-*]\s/.test(line)) {
      const items = []
      while (i < lines.length && /^\s*[-*]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s/, '')); i++
      }
      blocks.push(
        <ul key={key++} className="list-disc list-inside space-y-1 my-2">
          {items.map((it, k) => (
            <li key={k} className="text-white/65 text-sm">{inline(it)}</li>
          ))}
        </ul>
      )
      continue
    }

    if (line.trim() === '') { i++; continue }

    blocks.push(
      <p key={key++} className="text-white/65 text-sm leading-relaxed my-2">{inline(line)}</p>
    )
    i++
  }

  return <div>{blocks}</div>
}