import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import useTorontoTheme from './hooks/useTorontoTheme'
import useTripStore from './store/tripStore'
import TorontoSkyline from './components/background/TorontoSkyline'
import AnimatedElements from './components/background/AnimatedElements'
import AuthScreen from './components/auth/AuthScreen'
import AppShell from './components/layout/AppShell'
import Sidebar from './components/layout/Sidebar'
import WizardRenderer from './components/wizard/WizardRenderer'
import TripListScreen from './components/plans/TripListScreen'
import { getToken, logout as apiLogout } from './api/client'

export default function App() {
  const { t } = useTranslation()
  const { mode, toggleMode, isAuto } = useTorontoTheme()
  const [burstKey, setBurstKey] = useState(0)
  const [authed, setAuthed] = useState(() => !!getToken())

  const trip = useTripStore((s) => s.trip)
  const back = useTripStore((s) => s.back)
  const clearTrip = useTripStore((s) => s.clearTrip)
  const closeTrip = useTripStore((s) => s.closeTrip)

  // No auto-create. Authenticating lands on the trip list; a trip is created
  // only when the user asks for one. The old effect minted a trip on every
  // login, which meant one ephemeral trip and no way back to an earlier plan.

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
            {trip ? (
              <Sidebar
                trip={trip}
                onNavigateBack={(stage, stopIndex) => back(stage, stopIndex)}
                onCloseTrip={closeTrip}
              />
            ) : (
              // No trip open: the stage list would be an empty skeleton, so the
              // sidebar is just the app name until one is selected.
              <div className="px-2">
                <h1 className="text-white font-semibold text-lg tracking-tight">
                  {t('app.name')}
                </h1>
              </div>
            )}
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
      {trip ? <WizardRenderer /> : <TripListScreen />}
    </AppShell>
  )
}