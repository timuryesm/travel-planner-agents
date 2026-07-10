import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { StageCard, OptionCard, Badge, StageActions } from './primitives'

// ─────────────────────────────────────────────────────────────────────────────
// DestinationStage — pick one city, or several when multi_city is on
// ─────────────────────────────────────────────────────────────────────────────
// Commit payload must validate against DestinationCommitData (Phase B):
//   { destinations: [ { city, country, why_chosen_summary,
//                       season_note, safety_note }, ... ] }   min_length=1
//
// This is the stage that RESTRUCTURES navigation: committing N destinations
// causes the backend to create N Stop rows, each with four unvisited
// StopStageCommit rows. The sidebar's per-city groups appear immediately
// after this commit lands.
//
// Selection mode is driven by setupData.multi_city:
//   false → radio behaviour, exactly one city
//   true  → multi-select, ordered by pick order (index i → stop_index i)
//
// MOCK DATA: replaced by a real agent call in the follow-up "agent endpoints"
// step. The shape matches the Destination schema exactly, so the swap is a
// one-line change (fetch instead of constant).

const MOCK_DESTINATIONS = [
  {
    city: 'Lisbon',
    country: 'Portugal',
    why_chosen_summary:
      'Mild weather year-round, walkable historic districts, and some of the best value dining in Western Europe.',
    season_note: 'Spring and early autumn are ideal — warm days, few crowds.',
    safety_note: 'Very safe for travellers. Standard pickpocket awareness in tourist areas.',
  },
  {
    city: 'Kyoto',
    country: 'Japan',
    why_chosen_summary:
      'Over a thousand temples, traditional machiya streets, and a food culture that rewards wandering.',
    season_note: 'Cherry blossom in early April; autumn foliage late November.',
    safety_note: 'Among the safest destinations worldwide. Minimal precautions needed.',
  },
  {
    city: 'Mexico City',
    country: 'Mexico',
    why_chosen_summary:
      'World-class museums, a defining food scene, and vibrant neighbourhoods like Roma and Condesa.',
    season_note: 'Dry season November–April brings clear skies and comfortable temperatures.',
    safety_note: 'Stick to central neighbourhoods; use registered taxis or rideshare after dark.',
  },
  {
    city: 'Reykjavík',
    country: 'Iceland',
    why_chosen_summary:
      'A compact capital that opens onto glaciers, geysers, and the northern lights within an hour of leaving town.',
    season_note: 'September–March for aurora; June–August for midnight sun and hiking.',
    safety_note: 'Extremely safe. Main risks are weather-related — check road conditions.',
  },
  {
    city: 'Porto',
    country: 'Portugal',
    why_chosen_summary:
      'Riverside cellars, tiled facades, and a slower pace than Lisbon at a lower price point.',
    season_note: 'May–October for warm, dry weather along the Douro.',
    safety_note: 'Very safe. Steep cobbled streets — sturdy shoes recommended.',
  },
  {
    city: 'Seoul',
    country: 'South Korea',
    why_chosen_summary:
      'Palaces beside skyscrapers, 24-hour markets, and the best public transit of any megacity.',
    season_note: 'April–June and September–November avoid the humid summer and cold winter.',
    safety_note: 'Exceptionally safe, including late at night. Excellent English signage on transit.',
  },
]

export default function DestinationStage({ commit, commitData, setupData, transitioning }) {
  const { t } = useTranslation()

  const multiCity = setupData?.multi_city ?? false

  // Prefill from an existing commit when revisiting this stage.
  // We match on city name since that's the stable identifier here.
  const [selected, setSelected] = useState(() => {
    const prior = commitData?.destinations
    if (!prior?.length) return []
    return prior.map((d) => d.city)
  })

  function toggle(city) {
    if (multiCity) {
      // Multi-select: append or remove; pick order becomes stop order
      setSelected((cur) =>
        cur.includes(city) ? cur.filter((c) => c !== city) : [...cur, city]
      )
    } else {
      // Single-select: replace
      setSelected([city])
    }
  }

  function handleConfirm() {
    // Preserve pick order — destinations[i] maps to stop_index i
    const destinations = selected
      .map((city) => MOCK_DESTINATIONS.find((d) => d.city === city))
      .filter(Boolean)
      .map(({ city, country, why_chosen_summary, season_note, safety_note }) => ({
        city, country, why_chosen_summary, season_note, safety_note,
      }))

    commit({ destinations })
  }

  const valid = selected.length >= 1

  return (
    <StageCard title={t('destination.title')} subtitle={t('destination.subtitle')}>
      <div className="flex flex-col gap-3">
        {MOCK_DESTINATIONS.map((d) => {
          const isSelected = selected.includes(d.city)
          const order = selected.indexOf(d.city) + 1

          return (
            <OptionCard key={d.city} selected={isSelected} onClick={() => toggle(d.city)}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2.5 mb-1">
                    <h3 className="text-white font-semibold text-base">{d.city}</h3>
                    <span className="text-white/40 text-sm">{d.country}</span>
                    {/* In multi-city mode show the visit order on selected cards */}
                    {isSelected && multiCity && (
                      <Badge>#{order}</Badge>
                    )}
                  </div>

                  <p className="text-white/65 text-sm leading-relaxed">
                    {d.why_chosen_summary}
                  </p>

                  <div className="mt-3 flex flex-col gap-1.5">
                    <div className="flex gap-2 text-xs">
                      <span className="text-white/35 flex-shrink-0 w-28">
                        {t('destination.seasonNote')}
                      </span>
                      <span className="text-white/55">{d.season_note}</span>
                    </div>
                    <div className="flex gap-2 text-xs">
                      <span className="text-white/35 flex-shrink-0 w-28">
                        {t('destination.safetyNote')}
                      </span>
                      <span className="text-white/55">{d.safety_note}</span>
                    </div>
                  </div>
                </div>

                {/* Selection indicator */}
                <div
                  style={{
                    flexShrink: 0, width: 22, height: 22, borderRadius: '50%',
                    border: `2px solid ${isSelected ? '#2dd4bf' : 'rgba(255,255,255,0.25)'}`,
                    background: isSelected ? '#2dd4bf' : 'transparent',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    marginTop: 2,
                  }}
                >
                  {isSelected && (
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                      <path d="M2 6 L5 9 L10 3" stroke="#0a0e1a" strokeWidth="2"
                        strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </div>
              </div>
            </OptionCard>
          )
        })}
      </div>

      {/* Multi-city hint */}
      {multiCity && (
        <p className="text-white/40 text-xs mt-4">
          {selected.length === 0
            ? t('destination.subtitle')
            : `${selected.length} ${selected.length === 1 ? 'city' : 'cities'} — ${selected.join(' → ')}`}
        </p>
      )}

      {/* Destination cannot be skipped — the stop block depends on it */}
      <StageActions
        onConfirm={handleConfirm}
        confirmDisabled={!valid}
        showSkip={false}
        showForward={false}
        transitioning={transitioning}
      />
    </StageCard>
  )
}