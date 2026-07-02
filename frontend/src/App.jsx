import React, { useState } from 'react'
import TorontoSkyline from './components/background/TorontoSkyline'
import AnimatedElements from './components/background/AnimatedElements'

export default function App() {
  const [mode, setMode] = useState('night')
  const [burstKey, setBurstKey] = useState(0)

  return (
    <div className="min-h-screen">
      <TorontoSkyline
        mode={mode}
        onTowerClick={() => setBurstKey(k => k + 1)}
      />
      <AnimatedElements mode={mode} burstKey={burstKey} />

      {/* Temporary toggle — replaced by useTorontoTheme in Step 4 */}
      <div style={{ position: 'fixed', top: 20, right: 20, zIndex: 50 }}>
        <button
          onClick={() => setMode(m => m === 'night' ? 'day' : 'night')}
          className="glass-card px-4 py-2 text-white text-sm font-medium"
        >
          {mode === 'night' ? '☀️ Day' : '🌙 Night'}
        </button>
      </div>
    </div>
  )
}