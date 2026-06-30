import React from 'react'

// Stub — replaced step by step as Phase C progresses.
// Step 2 adds TorontoSkyline beneath this.
// Step 4 adds useTorontoTheme (dark/light switching).
// Step 7 adds AppShell (sidebar + main content).
// Step 10 adds AuthScreen.
// Step 11 adds the full wizard.

export default function App() {
  return (
    <div className="min-h-screen bg-night-900 flex flex-col items-center justify-center gap-6">

      {/* Scaffold confirmation card */}
      <div className="glass-card px-10 py-8 text-center max-w-sm">
        <div className="text-3xl mb-3">✈️</div>
        <h1 className="text-2xl font-semibold text-white tracking-tight">
          Travel Planner
        </h1>
        <p className="text-white/50 text-sm mt-2">
          Phase C scaffold — Vite + React + Tailwind ready
        </p>
      </div>

      {/* Dependency checklist — visible during development only */}
      <div className="glass-card px-8 py-5 max-w-xs w-full">
        <p className="text-white/40 text-xs font-medium uppercase tracking-widest mb-3">
          Dependencies
        </p>
        {[
          'React 18',
          'Tailwind CSS 3',
          'Framer Motion 11',
          'react-i18next 15',
          'Zustand 5',
        ].map((dep) => (
          <div key={dep} className="flex items-center gap-2 py-1">
            <span className="w-1.5 h-1.5 rounded-full bg-iris-teal" />
            <span className="text-white/70 text-sm">{dep}</span>
          </div>
        ))}
      </div>

    </div>
  )
}