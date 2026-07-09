import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { motion, AnimatePresence } from 'framer-motion'
import { register as apiRegister, login as apiLogin, ApiError } from '../../api/client'
import LanguageSelector from '../ui/LanguageSelector'
import ThemeToggle from '../ui/ThemeToggle'

// ─────────────────────────────────────────────────────────────────────────────
// AuthScreen — sign in / create account, floating over the Toronto background
// ─────────────────────────────────────────────────────────────────────────────
// A single component with a mode toggle between 'login' and 'register'. On
// success it calls onAuthenticated(userInfo) so the parent can store the user
// and switch to the main app. The background is rendered by the parent (App),
// so this component is just the centered glass card plus the top-bar controls
// (language + theme are available before login so users can set preferences).
//
// Errors from the API client arrive as ApiError with a stable `code`, which
// maps directly to the auth.errors.* i18n keys defined in Step 5.
//
// Props:
//   mode, toggleMode, isAuto — theme controls (threaded from useTorontoTheme)
//   onAuthenticated          — ({ user_id, email, access_token }) => void

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function AuthScreen({ mode, toggleMode, isAuto, onAuthenticated }) {
  const { t } = useTranslation()
  const [screen, setScreen] = useState('login')   // 'login' | 'register'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)         // i18n key under auth.errors
  const [submitting, setSubmitting] = useState(false)

  const isLogin = screen === 'login'

  // Map an ApiError code to a translated message.
  function messageForError(err) {
    if (err instanceof ApiError) {
      const map = {
        invalidCredentials: 'auth.errors.invalidCredentials',
        emailTaken: 'auth.errors.emailTaken',
        networkError: 'auth.errors.networkError',
        validation: 'auth.errors.emailInvalid',
        sessionExpired: 'auth.errors.invalidCredentials',
      }
      return map[err.code] || 'auth.errors.unknown'
    }
    return 'auth.errors.unknown'
  }

  // Client-side validation before hitting the network
  function validate() {
    if (!EMAIL_RE.test(email)) return 'auth.errors.emailInvalid'
    if (password.length < 8) return 'auth.errors.passwordTooShort'
    return null
  }

  async function handleSubmit() {
    setError(null)

    const validationError = validate()
    if (validationError) {
      setError(validationError)
      return
    }

    setSubmitting(true)
    try {
      const data = isLogin
        ? await apiLogin(email, password)
        : await apiRegister(email, password)
      onAuthenticated(data)
    } catch (err) {
      setError(messageForError(err))
    } finally {
      setSubmitting(false)
    }
  }

  function switchScreen() {
    setScreen(isLogin ? 'register' : 'login')
    setError(null)
  }

  return (
    <div style={{ position: 'relative', zIndex: 10, minHeight: '100vh' }}>
      {/* Top-bar controls — available before login */}
      <div
        style={{
          position: 'fixed',
          top: 20,
          right: 24,
          zIndex: 50,
          display: 'flex',
          gap: 10,
        }}
      >
        <LanguageSelector />
        <ThemeToggle mode={mode} toggleMode={toggleMode} isAuto={isAuto} />
      </div>

      {/* Centered auth card */}
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 24,
        }}
      >
        <motion.div
          initial={{ y: 24, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          className="glass-card"
          style={{ width: '100%', maxWidth: 400, padding: 36 }}
        >
          {/* Brand */}
          <div className="text-center mb-7">
            <div className="text-3xl mb-3">✈️</div>
            <h1 className="text-white font-semibold text-2xl tracking-tight text-glow">
              {t('app.name')}
            </h1>
          </div>

          {/* Title */}
          <AnimatePresence mode="wait">
            <motion.div
              key={screen}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.2 }}
              className="mb-6 text-center"
            >
              <h2 className="text-white font-medium text-lg">
                {isLogin ? t('auth.loginTitle') : t('auth.registerTitle')}
              </h2>
              <p className="text-white/50 text-sm mt-1">
                {isLogin ? t('auth.loginSubtitle') : t('auth.registerSubtitle')}
              </p>
            </motion.div>
          </AnimatePresence>

          {/* Form */}
          <div className="flex flex-col gap-4">
            {/* Email */}
            <div>
              <label className="block text-white/70 text-xs font-medium mb-1.5">
                {t('auth.email')}
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
                placeholder={t('auth.emailPlaceholder')}
                autoComplete="email"
                className="w-full rounded-lg px-3.5 py-2.5 text-sm text-white placeholder-white/30 outline-none transition-colors"
                style={{
                  background: 'rgba(0,0,0,0.25)',
                  border: '1px solid rgba(255,255,255,0.12)',
                }}
                onFocus={(e) => (e.target.style.borderColor = 'rgba(45,212,191,0.5)')}
                onBlur={(e) => (e.target.style.borderColor = 'rgba(255,255,255,0.12)')}
              />
            </div>

            {/* Password */}
            <div>
              <label className="block text-white/70 text-xs font-medium mb-1.5">
                {t('auth.password')}
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
                placeholder={t('auth.passwordPlaceholder')}
                autoComplete={isLogin ? 'current-password' : 'new-password'}
                className="w-full rounded-lg px-3.5 py-2.5 text-sm text-white placeholder-white/30 outline-none transition-colors"
                style={{
                  background: 'rgba(0,0,0,0.25)',
                  border: '1px solid rgba(255,255,255,0.12)',
                }}
                onFocus={(e) => (e.target.style.borderColor = 'rgba(45,212,191,0.5)')}
                onBlur={(e) => (e.target.style.borderColor = 'rgba(255,255,255,0.12)')}
              />
            </div>

            {/* Error message */}
            <AnimatePresence>
              {error && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="text-sm"
                  style={{ color: '#fb7185' }}
                >
                  {t(error)}
                </motion.div>
              )}
            </AnimatePresence>

            {/* Submit */}
            <button
              onClick={handleSubmit}
              disabled={submitting}
              className="w-full rounded-lg py-2.5 text-sm font-semibold text-white transition-all mt-1"
              style={{
                background: submitting
                  ? 'rgba(45,212,191,0.4)'
                  : 'linear-gradient(135deg, #2dd4bf, #38bdf8)',
                cursor: submitting ? 'default' : 'pointer',
                opacity: submitting ? 0.7 : 1,
              }}
            >
              {submitting
                ? t('common.loading')
                : isLogin
                ? t('auth.loginButton')
                : t('auth.registerButton')}
            </button>
          </div>

          {/* Switch login/register */}
          <div className="text-center mt-6 text-sm">
            <span className="text-white/50">
              {isLogin ? t('auth.noAccount') : t('auth.haveAccount')}
            </span>{' '}
            <button
              onClick={switchScreen}
              className="text-iris-teal font-medium hover:underline"
              style={{ color: '#2dd4bf' }}
            >
              {isLogin ? t('auth.signUpLink') : t('auth.signInLink')}
            </button>
          </div>
        </motion.div>
      </div>
    </div>
  )
}