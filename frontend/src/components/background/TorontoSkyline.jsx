import React from 'react'
import { motion } from 'framer-motion'

import dayImg from '../../assets/toronto-day.png'
import nightImg from '../../assets/toronto-night.png'

// ─────────────────────────────────────────────────────────────────────────────
// TorontoSkyline — photographic background with day/night crossfade
// ─────────────────────────────────────────────────────────────────────────────
// Both source images are 1376x768 (ratio 1.792) and frame the CN Tower in the
// same position, so a simple opacity crossfade between them looks seamless.
//
// The images are the fixed backdrop; animated elements (stars, boats, plane,
// fireworks) are layered on TOP by AnimatedElements in Step 3. The CN Tower
// click zone for fireworks is positioned as a percentage of the viewport so it
// tracks the tower regardless of screen size.
//
// Tower position in both images (measured):
//   center X ~55%, spans vertically from ~3% (antenna tip) to ~68% (base)

const CLICK_ZONE = {
  left: '52%',
  width: '8%',
  top: '3%',
  height: '65%',
}

export default function TorontoSkyline({ mode = 'night', onTowerClick }) {
  const isNight = mode === 'night'

  return (
    <div style={{ position: 'fixed', inset: 0, overflow: 'hidden' }}>
      {/* Night image */}
      <motion.div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage: `url(${nightImg})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center bottom',
        }}
        animate={{ opacity: isNight ? 1 : 0 }}
        transition={{ duration: 2.5, ease: 'easeInOut' }}
      />

      {/* Day image */}
      <motion.div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage: `url(${dayImg})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center bottom',
        }}
        animate={{ opacity: isNight ? 0 : 1 }}
        transition={{ duration: 2.5, ease: 'easeInOut' }}
      />

      {/* Readability scrim — a subtle darkening so glass panels and text stay
          legible over the bright day image. Heavier at the top-left where the
          sidebar and content sit, lighter over the tower. */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: isNight
            ? 'linear-gradient(105deg, rgba(3,6,14,0.55) 0%, rgba(3,6,14,0.15) 45%, rgba(3,6,14,0) 70%)'
            : 'linear-gradient(105deg, rgba(8,20,40,0.42) 0%, rgba(8,20,40,0.10) 45%, rgba(8,20,40,0) 70%)',
          transition: 'background 2.5s ease-in-out',
          pointerEvents: 'none',
        }}
      />

      {/* CN Tower click zone — transparent, triggers fireworks.
          Positioned as a percentage so it tracks the tower at any screen size. */}
      <div
        onClick={onTowerClick}
        title="Click the CN Tower"
        style={{
          position: 'absolute',
          left: CLICK_ZONE.left,
          width: CLICK_ZONE.width,
          top: CLICK_ZONE.top,
          height: CLICK_ZONE.height,
          cursor: 'pointer',
          zIndex: 5,
        }}
      />
    </div>
  )
}