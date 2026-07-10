import React from 'react'
import { useTranslation } from 'react-i18next'

// ─────────────────────────────────────────────────────────────────────────────
// Shared UI primitives for wizard stages
// ─────────────────────────────────────────────────────────────────────────────
// Extracted here so all eight stages share one visual language and one set of
// focus/hover behaviours. Every stage imports from this file rather than
// re-styling inputs and buttons locally.

const INPUT_BG = 'rgba(0,0,0,0.25)'
const INPUT_BORDER = 'rgba(255,255,255,0.12)'
const FOCUS_BORDER = 'rgba(45,212,191,0.5)'

// ── Stage frame ───────────────────────────────────────────────────────────────
// The glass card + title + subtitle every stage sits inside.

export function StageCard({ title, subtitle, children, maxWidth = 720 }) {
  return (
    <div className="glass-card p-8" style={{ maxWidth, width: '100%' }}>
      <h2 className="text-2xl font-semibold text-white text-glow tracking-tight">
        {title}
      </h2>
      {subtitle && (
        <p className="text-white/50 text-sm mt-1.5">{subtitle}</p>
      )}
      <div className="mt-7">{children}</div>
    </div>
  )
}

// ── Labelled field wrapper ────────────────────────────────────────────────────

export function Field({ label, hint, children }) {
  return (
    <div>
      <label className="block text-white/70 text-xs font-medium mb-1.5">
        {label}
        {hint && <span className="text-white/35 font-normal ml-1.5">{hint}</span>}
      </label>
      {children}
    </div>
  )
}

// ── Text / number / date input ────────────────────────────────────────────────

export function Input({ type = 'text', value, onChange, placeholder, min, ...rest }) {
  return (
    <input
      type={type}
      value={value ?? ''}
      min={min}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded-lg px-3.5 py-2.5 text-sm text-white placeholder-white/30 outline-none transition-colors"
      style={{
        background: INPUT_BG,
        border: `1px solid ${INPUT_BORDER}`,
        colorScheme: 'dark',   // makes native date pickers dark
      }}
      onFocus={(e) => (e.target.style.borderColor = FOCUS_BORDER)}
      onBlur={(e) => (e.target.style.borderColor = INPUT_BORDER)}
      {...rest}
    />
  )
}

// ── Textarea ──────────────────────────────────────────────────────────────────

export function Textarea({ value, onChange, placeholder, rows = 3 }) {
  return (
    <textarea
      value={value ?? ''}
      rows={rows}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded-lg px-3.5 py-2.5 text-sm text-white placeholder-white/30 outline-none transition-colors resize-none"
      style={{ background: INPUT_BG, border: `1px solid ${INPUT_BORDER}` }}
      onFocus={(e) => (e.target.style.borderColor = FOCUS_BORDER)}
      onBlur={(e) => (e.target.style.borderColor = INPUT_BORDER)}
    />
  )
}

// ── Select ────────────────────────────────────────────────────────────────────

export function Select({ value, onChange, options }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-lg px-3.5 py-2.5 text-sm text-white outline-none transition-colors"
      style={{
        background: INPUT_BG,
        border: `1px solid ${INPUT_BORDER}`,
        colorScheme: 'dark',
      }}
      onFocus={(e) => (e.target.style.borderColor = FOCUS_BORDER)}
      onBlur={(e) => (e.target.style.borderColor = INPUT_BORDER)}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value} style={{ background: '#0d1b32' }}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

// ── Segmented control (for travel_type) ───────────────────────────────────────

export function Segmented({ value, onChange, options }) {
  return (
    <div
      className="flex gap-1 p-1 rounded-lg"
      style={{ background: INPUT_BG, border: `1px solid ${INPUT_BORDER}` }}
    >
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            onClick={() => onChange(o.value)}
            className="flex-1 rounded-md py-2 text-sm font-medium transition-all"
            style={{
              background: active ? 'rgba(45,212,191,0.18)' : 'transparent',
              color: active ? '#ffffff' : 'rgba(255,255,255,0.55)',
            }}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

// ── Toggle switch ─────────────────────────────────────────────────────────────

export function Toggle({ checked, onChange, label }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className="flex items-center gap-3 w-full text-left"
    >
      <div
        style={{
          width: 40, height: 22, borderRadius: 11, flexShrink: 0,
          background: checked ? 'rgba(45,212,191,0.85)' : 'rgba(255,255,255,0.15)',
          transition: 'background 0.2s ease',
          position: 'relative',
        }}
      >
        <div
          style={{
            width: 18, height: 18, borderRadius: '50%', background: '#fff',
            position: 'absolute', top: 2,
            left: checked ? 20 : 2,
            transition: 'left 0.2s ease',
          }}
        />
      </div>
      <span className="text-white/75 text-sm">{label}</span>
    </button>
  )
}

// ── Selectable option card (flights, hotels, destinations, activities) ────────

export function OptionCard({ selected, onClick, children, disabled }) {
  return (
    <button
      onClick={disabled ? undefined : onClick}
      className="w-full text-left rounded-xl p-4 transition-all"
      style={{
        background: selected ? 'rgba(45,212,191,0.10)' : 'rgba(255,255,255,0.05)',
        border: `1px solid ${selected ? 'rgba(45,212,191,0.55)' : 'rgba(255,255,255,0.10)'}`,
        cursor: disabled ? 'default' : 'pointer',
      }}
      onMouseEnter={(e) => {
        if (!selected && !disabled)
          e.currentTarget.style.borderColor = 'rgba(255,255,255,0.28)'
      }}
      onMouseLeave={(e) => {
        if (!selected)
          e.currentTarget.style.borderColor = 'rgba(255,255,255,0.10)'
      }}
    >
      {children}
    </button>
  )
}

// ── Badge (cheapest / fastest / provider labels) ──────────────────────────────

export function Badge({ children, color = '#2dd4bf' }) {
  return (
    <span
      className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full"
      style={{ background: `${color}22`, color }}
    >
      {children}
    </span>
  )
}

// ── Stage action bar — primary / skip / forward ───────────────────────────────
// The three forward paths every stop-level stage offers. Trip-level stages
// (setup, destination) pass showSkip={false} since they can't be skipped.

export function StageActions({
  onConfirm,
  confirmLabel,
  confirmDisabled,
  onSkip,
  onForward,
  showSkip = true,
  showForward = true,
  transitioning,
}) {
  const { t } = useTranslation()
  const disabled = transitioning || confirmDisabled

  return (
    <div className="flex items-center gap-3 mt-8 pt-6"
      style={{ borderTop: '1px solid rgba(255,255,255,0.08)' }}>
      <button
        onClick={onConfirm}
        disabled={disabled}
        className="px-5 py-2.5 rounded-lg text-sm font-semibold text-white transition-all"
        style={{
          background: disabled
            ? 'rgba(45,212,191,0.3)'
            : 'linear-gradient(135deg, #2dd4bf, #38bdf8)',
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.6 : 1,
        }}
      >
        {transitioning ? t('common.loading') : confirmLabel ?? t('common.continue')}
      </button>

      {showSkip && (
        <button
          onClick={onSkip}
          disabled={transitioning}
          className="px-4 py-2.5 rounded-lg text-sm font-medium text-white/65 hover:text-white transition-colors"
          style={{ background: 'rgba(255,255,255,0.07)' }}
        >
          {t('common.skip')}
        </button>
      )}

      {showForward && (
        <button
          onClick={onForward}
          disabled={transitioning}
          className="ml-auto px-3 py-2.5 rounded-lg text-sm font-medium text-white/40 hover:text-white/70 transition-colors"
        >
          {t('common.next')} →
        </button>
      )}
    </div>
  )
}