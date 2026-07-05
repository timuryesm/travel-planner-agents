import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import useTorontoTheme from './hooks/useTorontoTheme'
import AppShell from './components/layout/AppShell'

export default function App() {
  const { t } = useTranslation()
  const { mode, toggleMode, isAuto } = useTorontoTheme()
  const [burstKey, setBurstKey] = useState(0)

  // Placeholder sidebar + main content — replaced by Sidebar (Step 8) and
  // the wizard (Steps 11-12).
  const placeholderSidebar = (
    <div className="flex flex-col gap-2">
      <p className="text-white/40 text-xs font-medium uppercase tracking-widest mb-2">
        {t('sidebar.tripSetup')}
      </p>
      {['setup', 'destination'].map((s) => (
        <div key={s} className="flex items-center gap-3 px-2 py-2">
          <span className="dot-unvisited" />
          <span className="text-white/75 text-sm">{t(`stages.${s}`)}</span>
        </div>
      ))}
    </div>
  )

  return (
    <AppShell
      mode={mode}
      toggleMode={toggleMode}
      isAuto={isAuto}
      onTowerClick={() => setBurstKey(k => k + 1)}
      burstKey={burstKey}
      sidebar={placeholderSidebar}
    >
      <div className="glass-card p-8 max-w-lg">
        <h1 className="text-2xl font-semibold text-white text-glow">
          {t('app.name')}
        </h1>
        <p className="text-white/60 text-sm mt-2">{t('app.tagline')}</p>
        <p className="text-white/40 text-xs mt-6">
          AppShell layout — sidebar + main content ready
        </p>
      </div>
    </AppShell>
  )
}