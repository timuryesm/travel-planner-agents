import React from 'react'
import { motion } from 'framer-motion'
import TorontoSkyline from '../background/TorontoSkyline'
import AnimatedElements from '../background/AnimatedElements'
import LanguageSelector from '../ui/LanguageSelector'
import ThemeToggle from '../ui/ThemeToggle'

// ─────────────────────────────────────────────────────────────────────────────
// AppShell — the master layout every authenticated screen sits inside
// ─────────────────────────────────────────────────────────────────────────────
// Layout structure (z-order from back to front):
//   0. TorontoSkyline        — fixed photographic background
//   2. AnimatedElements      — stars / boats / plane
//   6. Fireworks canvas      — (inside AnimatedElements)
//  10. Sidebar + main        — the app content, in glass panels
//  50. Top bar controls      — language + theme
//
// The sidebar is a fixed-width column (260px) that the parent fills via the
// `sidebar` prop. The main content area fills the rest and scrolls
// independently. On narrow screens the sidebar collapses to a slimmer width.
//
// Props:
//   mode, toggleMode, isAuto — from useTorontoTheme (instantiated once in the
//                              top-level App and threaded down)
//   onTowerClick             — fireworks trigger
//   burstKey                 — increments per tower click
//   sidebar                  — the sidebar content (Sidebar component, Step 8)
//   children                 — the main content (wizard, auth, etc.)

const SIDEBAR_WIDTH = 264

export default function AppShell({
  mode,
  toggleMode,
  isAuto,
  onTowerClick,
  burstKey,
  sidebar,
  children,
}) {
  return (
    <div style={{ position: 'relative', minHeight: '100vh' }}>
      {/* ── Background layers ── */}
      <TorontoSkyline mode={mode} onTowerClick={onTowerClick} />
      <AnimatedElements mode={mode} burstKey={burstKey} />

      {/* ── Top bar controls ── */}
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

      {/* ── Main layout grid ── */}
      <div
        style={{
          position: 'relative',
          zIndex: 10,
          display: 'flex',
          minHeight: '100vh',
        }}
      >
        {/* Sidebar column */}
        {sidebar && (
          <motion.aside
            initial={{ x: -30, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
            style={{
              width: SIDEBAR_WIDTH,
              flexShrink: 0,
              padding: '20px 16px',
              height: '100vh',
              position: 'sticky',
              top: 0,
              overflowY: 'auto',
            }}
            className="hidden md:block"
          >
            <div className="glass-card h-full p-4 flex flex-col">
              {sidebar}
            </div>
          </motion.aside>
        )}

        {/* Main content area */}
        <motion.main
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.5, ease: 'easeOut', delay: 0.1 }}
          style={{
            flex: 1,
            minWidth: 0,
            padding: '32px clamp(20px, 4vw, 64px)',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {children}
        </motion.main>
      </div>
    </div>
  )
}