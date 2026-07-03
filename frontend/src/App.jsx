import React, { useState } from 'react'
import useTorontoTheme from './hooks/useTorontoTheme'
import TorontoSkyline from './components/background/TorontoSkyline'
import AnimatedElements from './components/background/AnimatedElements'

export default function App() {
  const { mode, toggleMode, isAuto } = useTorontoTheme()
  const [burstKey, setBurstKey] = useState(0)

  return (
    <div className="min-h-screen">
      <TorontoSkyline
        mode={mode}
        onTowerClick={() => setBurstKey(k => k + 1)}
      />
      <AnimatedElements mode={mode} burstKey={burstKey} />

      {/* Temporary toggle — replaced properly by AppShell in Step 7 */}
      <div style={{ position: 'fixed', top: 20, right: 20, zIndex: 50 }}>
        <button
          onClick={toggleMode}
          className="glass-card px-4 py-2 text-white text-sm font-medium"
        >
          {mode === 'night' ? '☀️ Day' : '🌙 Night'}
          {isAuto && <span className="ml-2 text-white/40 text-xs">auto</span>}
        </button>
      </div>
    </div>
  )
}