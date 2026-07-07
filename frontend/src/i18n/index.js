import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'

import en from './locales/en.json'
import fr from './locales/fr.json'
import ru from './locales/ru.json'

// ─────────────────────────────────────────────────────────────────────────────
// i18n configuration
// ─────────────────────────────────────────────────────────────────────────────
// Three languages: English (default/fallback), French, Russian.
//
// Language resolution order on first visit:
//   1. localStorage key 'tp-language' (set by the LanguageSelector in Step 6)
//   2. navigator.language (the browser's preferred language)
//   3. 'en' fallback
//
// Once the user picks a language in the selector, it persists to localStorage
// and overrides browser detection on every subsequent visit.

export const SUPPORTED_LANGUAGES = [
  { code: 'en', label: 'English',  flag: '🇨🇦' },
  { code: 'fr', label: 'Français', flag: '🇫🇷' },
  { code: 'ru', label: 'Русский',  flag: '🇷🇺' },
]

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      fr: { translation: fr },
      ru: { translation: ru },
    },
    fallbackLng: 'en',
    supportedLngs: ['en', 'fr', 'ru'],

    detection: {
      // Check localStorage first, then the browser language
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: 'tp-language',
      caches: ['localStorage'],
    },

    interpolation: {
      escapeValue: false,   // React already escapes against XSS
    },
  })

export default i18n