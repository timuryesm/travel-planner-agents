import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import useTorontoTheme from './hooks/useTorontoTheme'
import AppShell from './components/layout/AppShell'
import Sidebar from './components/layout/Sidebar'

// Mock trip for build-testing the sidebar — a 2-city trip mid-wizard.
// Replaced by real trip state from the store in Step 11.
const MOCK_TRIP = {
  id: 'mock',
  status: 'in_progress',
  current_stage: 'activities',
  current_stop_index: 0,
  multi_city: true,
  trip_stage_commits: [
    { stage: 'setup', commit_type: 'chosen', completed: true },
    { stage: 'destination', commit_type: 'chosen', completed: true },
    { stage: 'reconciliation', commit_type: 'unvisited', completed: false },
    { stage: 'final', commit_type: 'unvisited', completed: false },
  ],
  stops: [
    {
      id: 's0', stop_index: 0, city: 'Paris', country: 'France',
      stage_commits: [
        { stage: 'flights', commit_type: 'chosen', completed: true },
        { stage: 'accommodation', commit_type: 'skipped', completed: true },
        { stage: 'activities', commit_type: 'unvisited', completed: false },
        { stage: 'daily_plan', commit_type: 'unvisited', completed: false },
      ],
    },
    {
      id: 's1', stop_index: 1, city: 'Rome', country: 'Italy',
      stage_commits: [
        { stage: 'flights', commit_type: 'unvisited', completed: false },
        { stage: 'accommodation', commit_type: 'unvisited', completed: false },
        { stage: 'activities', commit_type: 'unvisited', completed: false },
        { stage: 'daily_plan', commit_type: 'unvisited', completed: false },
      ],
    },
  ],
}

export default function App() {
  const { t } = useTranslation()
  const { mode, toggleMode, isAuto } = useTorontoTheme()
  const [burstKey, setBurstKey] = useState(0)

  return (
    <AppShell
      mode={mode}
      toggleMode={toggleMode}
      isAuto={isAuto}
      onTowerClick={() => setBurstKey(k => k + 1)}
      burstKey={burstKey}
      sidebar={
        <Sidebar
          trip={MOCK_TRIP}
          onNavigateBack={(stage, stopIndex) =>
            console.log('BACK to', stage, stopIndex)
          }
        />
      }
    >
      <div className="glass-card p-8 max-w-lg">
        <h1 className="text-2xl font-semibold text-white text-glow">
          {t('stages.activities')}
        </h1>
        <p className="text-white/60 text-sm mt-2">
          Sidebar test — Paris, mid-wizard. Click a completed past stage
          (e.g. Flights) to see the blast-radius warning.
        </p>
      </div>
    </AppShell>
  )
}