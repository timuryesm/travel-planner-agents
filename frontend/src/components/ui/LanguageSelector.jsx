import React, { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { SUPPORTED_LANGUAGES } from '../../i18n'

// ─────────────────────────────────────────────────────────────────────────────
// LanguageSelector — dropdown showing 🇨🇦 English / 🇫🇷 Français / 🇷🇺 Русский
// ─────────────────────────────────────────────────────────────────────────────
// Reads the language list from SUPPORTED_LANGUAGES (defined in i18n/index.js)
// so this component stays in sync with the config automatically. Changing the
// language calls i18n.changeLanguage, which the LanguageDetector persists to
// localStorage under 'tp-language' for next visit.

export default function LanguageSelector() {
  const { i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  const current =
    SUPPORTED_LANGUAGES.find((l) => l.code === i18n.language) ||
    SUPPORTED_LANGUAGES.find((l) => i18n.language?.startsWith(l.code)) ||
    SUPPORTED_LANGUAGES[0]

  // Close the dropdown on any outside click
  useEffect(() => {
    function onClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  function selectLanguage(code) {
    i18n.changeLanguage(code)
    setOpen(false)
  }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      {/* Trigger button — current flag + native name */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="glass-card flex items-center gap-2 px-3 py-2 text-sm font-medium text-white/90 hover:text-white"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="text-base leading-none">{current.flag}</span>
        <span className="hidden sm:inline">{current.label}</span>
        <svg
          width="12" height="12" viewBox="0 0 12 12" fill="none"
          style={{
            transform: open ? 'rotate(180deg)' : 'none',
            transition: 'transform 0.2s ease',
          }}
        >
          <path d="M2 4 L6 8 L10 4" stroke="currentColor" strokeWidth="1.5"
            strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {/* Dropdown */}
      {open && (
        <div
          role="listbox"
          className="glass-card"
          style={{
            position: 'absolute',
            top: 'calc(100% + 8px)',
            right: 0,
            minWidth: '160px',
            padding: '6px',
            zIndex: 60,
          }}
        >
          {SUPPORTED_LANGUAGES.map((lang) => {
            const active = lang.code === current.code
            return (
              <button
                key={lang.code}
                role="option"
                aria-selected={active}
                onClick={() => selectLanguage(lang.code)}
                className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-left text-white/85 hover:bg-white/10 transition-colors"
                style={{
                  background: active ? 'rgba(45,212,191,0.14)' : 'transparent',
                }}
              >
                <span className="text-base leading-none">{lang.flag}</span>
                <span className="flex-1">{lang.label}</span>
                {active && (
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                    <path d="M2 7 L6 11 L12 3" stroke="#2dd4bf" strokeWidth="2"
                      strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}