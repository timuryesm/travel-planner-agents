import React, { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import useTorontoTheme from './hooks/useTorontoTheme'
import useTripStore from './store/tripStore'
import TorontoSkyline from './components/background/TorontoSkyline'
import AnimatedElements from './components/background/AnimatedElements'
import AuthScreen from './components/auth/AuthScreen'
import AppShell from './components/layout/AppShell'
import Sidebar from './components/layout/Sidebar'
import WizardRenderer from './components/wizard/WizardRenderer'
import { getToken, logout as apiLogout } from './api/client'

export default function App() {
  const { t } = useTranslation()
  const { mode, toggleMode, isAuto } = useTorontoTheme()
  const [burstKey, setBurstKey] = useState(0)
  const [authed, setAuthed] = useState(() => !!getToken())

  const trip = useTripStore((s) => s.trip)
  const startTrip = useTripStore((s) => s.startTrip)
  const back = useTripStore((s) => s.back)
  const clearTrip = useTripStore((s) => s.clearTrip)

  // Start a trip as soon as we're authenticated and none is loaded.
  // Step 12 / Phase D can add a trip list + resume flow here instead.
  useEffect(() => {
    if (authed && !trip) {
      startTrip().catch(() => { /* error surfaces via store.error */ })
    }
  }, [authed, trip, startTrip])

  function handleLogout() {
    apiLogout()
    clearTrip()
    setAuthed(false)
  }

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
        <div className="flex flex-col h-full">
          <div className="flex-1 min-h-0">
            <Sidebar
              trip={trip}
              onNavigateBack={(stage, stopIndex) => back(stage, stopIndex)}
            />
          </div>
          <button
            onClick={handleLogout}
            className="mt-3 px-2 py-2 rounded-lg text-sm font-medium text-white/50 hover:text-white/80 text-left"
          >
            {t('auth.logout')}
          </button>
        </div>
      }
    >
      <WizardRenderer />
    </AppShell>
  )
}