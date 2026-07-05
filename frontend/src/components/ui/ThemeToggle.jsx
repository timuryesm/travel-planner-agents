import React from 'react'
import { useTranslation } from 'react-i18next'

// ─────────────────────────────────────────────────────────────────────────────
// ThemeToggle — sun/moon button that flips day/night
// ─────────────────────────────────────────────────────────────────────────────
// Driven by useTorontoTheme (passed in as props from the parent, so the hook
// is instantiated once at the app level rather than here). Shows a small "auto"
// label when the current mode is still following Toronto's clock — the label
// disappears once the user manually overrides.
//
// Props:
//   mode        — 'day' | 'night'
//   toggleMode  — flip the mode (switches to manual override)
//   isAuto      — true when following Toronto time

export default function ThemeToggle({ mode, toggleMode, isAuto }) {
  const { t } = useTranslation()
  const isNight = mode === 'night'

  return (
    <button
      onClick={toggleMode}
      className="glass-card flex items-center gap-2 px-3 py-2 text-sm font-medium text-white/90 hover:text-white"
      title={isNight ? t('theme.switchToDay') : t('theme.switchToNight')}
      aria-label={isNight ? t('theme.switchToDay') : t('theme.switchToNight')}
    >
      {isNight ? (
        // Moon icon
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path
            d="M13.5 9.5 A5.5 5.5 0 1 1 6.5 2.5 A4.2 4.2 0 0 0 13.5 9.5 Z"
            fill="currentColor"
          />
        </svg>
      ) : (
        // Sun icon
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <circle cx="8" cy="8" r="3.2" fill="currentColor" />
          {[...Array(8)].map((_, i) => {
            const angle = (Math.PI * 2 * i) / 8
            const x1 = 8 + Math.cos(angle) * 5
            const y1 = 8 + Math.sin(angle) * 5
            const x2 = 8 + Math.cos(angle) * 6.8
            const y2 = 8 + Math.sin(angle) * 6.8
            return (
              <line
                key={i}
                x1={x1} y1={y1} x2={x2} y2={y2}
                stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
              />
            )
          })}
        </svg>
      )}

      <span className="hidden sm:inline">
        {isNight ? t('theme.night') : t('theme.day')}
      </span>

      {isAuto && (
        <span className="text-white/40 text-xs font-normal">
          {t('theme.auto')}
        </span>
      )}
    </button>
  )
}