import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import useTorontoTheme from './hooks/useTorontoTheme'
import TorontoSkyline from './components/background/TorontoSkyline'
import AnimatedElements from './components/background/AnimatedElements'
import AuthScreen from './components/auth/AuthScreen'
import AppShell from './components/layout/AppShell'
import Sidebar from './components/layout/Sidebar'
import { getToken, logout as apiLogout } from './api/client'

// Mock trip — still used for the post-login view until Step 11 wires the store.
const MOCK_TRIP = {
  id: 'mock', status: 'in_progress',
  current_stage: 'activities', current_stop_index: 0, multi_city: true,
  trip_stage_commits: [
    { stage: 'setup', commit_type: 'chosen', completed: true },
    { stage: 'destination', commit_type: 'chosen', completed: true },
    { stage: 'reconciliation', commit_type: 'unvisited', completed: false },
    { stage: 'final', commit_type: 'unvisited', completed: false },
  ],
  stops: [
    { id: 's0', stop_index: 0, city: 'Paris', country: 'France', stage_commits: [
      { stage: 'flights', commit_type: 'chosen', completed: true },
      { stage: 'accommodation', commit_type: 'skipped', completed: true },
      { stage: 'activities', commit_type: 'unvisited', completed: false },
      { stage: 'daily_plan', commit_type: 'unvisited', completed: false },
    ]},
    { id: 's1', stop_index: 1, city: 'Rome', country: 'Italy', stage_commits: [
      { stage: 'flights', commit_type: 'unvisited', completed: false },
      { stage: 'accommodation', commit_type: 'unvisited', completed: false },
      { stage: 'activities', commit_type: 'unvisited', completed: false },
      { stage: 'daily_plan', commit_type: 'unvisited', completed: false },
    ]},
  ],
}

export default function App() {
  const { t } = useTranslation()
  const { mode, toggleMode, isAuto } = useTorontoTheme()
  const [burstKey, setBurstKey] = useState(0)
  // Authenticated if a token already exists (persisted from a prior session)
  const [authed, setAuthed] = useState(() => !!getToken())

  function handleLogout() {
    apiLogout()
    setAuthed(false)
  }

  // The background is shared across both auth and main views
  const background = (
    <>
      <TorontoSkyline mode={mode} onTowerClick={() => setBurstKey(k => k + 1)} />
      <AnimatedElements mode={mode} burstKey={burstKey} />
    </>
  )

  if (!authed) {
    return (
      <div style={{ position: 'relative', minHeight: '100vh' }}>
        {background}
        <AuthScreen
          mode={mode}
          toggleMode={toggleMode}
          isAuto={isAuto}
          onAuthenticated={() => setAuthed(true)}
        />
      </div>
    )
  }

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
          onNavigateBack={(stage, stopIndex) => console.log('BACK to', stage, stopIndex)}
        />
      }
    >
      <div className="glass-card p-8 max-w-lg">
        <h1 className="text-2xl font-semibold text-white text-glow">
          {t('stages.activities')}
        </h1>
        <p className="text-white/60 text-sm mt-2">
          Signed in. Main app placeholder — wizard arrives in Steps 11–12.
        </p>
        <button
          onClick={handleLogout}
          className="mt-5 px-4 py-2 rounded-lg text-sm font-medium text-white/70 hover:text-white"
          style={{ background: 'rgba(255,255,255,0.08)' }}
        >
          {t('auth.logout')}
        </button>
      </div>
    </AppShell>
  )
}