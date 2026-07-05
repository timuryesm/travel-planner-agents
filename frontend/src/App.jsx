import React, { useState } from 'react'
import useTorontoTheme from './hooks/useTorontoTheme'
import TorontoSkyline from './components/background/TorontoSkyline'
import AnimatedElements from './components/background/AnimatedElements'
import LanguageSelector from './components/ui/LanguageSelector'
import ThemeToggle from './components/ui/ThemeToggle'

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

      {/* Top bar — language + theme controls */}
      <div
        style={{
          position: 'fixed',
          top: 20,
          right: 20,
          zIndex: 50,
          display: 'flex',
          gap: 10,
        }}
      >
        <LanguageSelector />
        <ThemeToggle mode={mode} toggleMode={toggleMode} isAuto={isAuto} />
      </div>
    </div>
  )
}