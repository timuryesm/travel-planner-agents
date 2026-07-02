import React, { useEffect, useRef, useState, useCallback } from 'react'

// ─────────────────────────────────────────────────────────────────────────────
// AnimatedElements — the moving layers over the photographic skyline
// ─────────────────────────────────────────────────────────────────────────────
// Sits ABOVE TorontoSkyline, BELOW the app content. All layers are
// pointer-events: none so clicks pass through to the tower click zone and the
// UI panels — except nothing here needs clicks anyway.
//
//   Night: twinkling stars scattered across the upper sky
//   Day:   sailboats drifting across the lake + a plane crossing on a diagonal
//   Both:  fireworks canvas, triggered imperatively via the `fireworksAt` prop
//
// The parent (App / AppShell) passes a `burstKey` that increments on each tower
// click; when it changes, a fresh firework show plays for ~2.5s.

// ── Deterministic PRNG so star/boat placement is stable across renders ──
function mulberry32(seed) {
  return function () {
    seed |= 0
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Stars (night)
// ─────────────────────────────────────────────────────────────────────────────
const STARS = (() => {
  const rand = mulberry32(20260702)
  const arr = []
  for (let i = 0; i < 110; i++) {
    arr.push({
      // Upper ~62% of the sky only — below that is skyline/water in the photo
      left: rand() * 100,
      top: rand() * 58,
      size: rand() < 0.15 ? 2.4 : rand() < 0.5 ? 1.6 : 1.1,
      delay: rand() * 4,
      dur: 2.5 + rand() * 3,
      baseOpacity: 0.4 + rand() * 0.5,
    })
  }
  return arr
})()

function Stars({ visible }) {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        pointerEvents: 'none',
        opacity: visible ? 1 : 0,
        transition: 'opacity 2.5s ease-in-out',
        zIndex: 2,
      }}
      aria-hidden="true"
    >
      {STARS.map((s, i) => (
        <div
          key={i}
          style={{
            position: 'absolute',
            left: `${s.left}%`,
            top: `${s.top}%`,
            width: `${s.size}px`,
            height: `${s.size}px`,
            borderRadius: '50%',
            background: '#ffffff',
            opacity: s.baseOpacity,
            boxShadow: `0 0 ${s.size * 2}px rgba(255,255,255,0.8)`,
            animation: `twinkle ${s.dur}s ease-in-out ${s.delay}s infinite`,
          }}
        />
      ))}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Sailboats (day) — drift slowly across the lake
// ─────────────────────────────────────────────────────────────────────────────
// Positioned in the lower ~28% of the viewport (the water region of the photo).
const BOATS = [
  { top: 74, scale: 1.0,  dur: 58, delay: 0,   dir: 1  },
  { top: 80, scale: 0.72, dur: 74, delay: 12,  dir: 1  },
  { top: 77, scale: 0.86, dur: 66, delay: 30,  dir: -1 },
]

function Sailboat({ scale }) {
  // Simple sloop silhouette: hull + mainsail + jib
  return (
    <svg width={54 * scale} height={46 * scale} viewBox="0 0 54 46" fill="none">
      {/* sails */}
      <path d="M26 4 L26 32 L10 32 Z" fill="rgba(255,255,255,0.92)" />
      <path d="M28 10 L28 32 L40 32 Z" fill="rgba(255,255,255,0.78)" />
      {/* mast */}
      <rect x="25.4" y="4" width="1.2" height="28" fill="rgba(255,255,255,0.6)" />
      {/* hull */}
      <path d="M6 33 L48 33 L42 41 L12 41 Z" fill="#f1f5f9" />
      <path d="M6 33 L48 33 L46 35 L8 35 Z" fill="rgba(0,0,0,0.12)" />
      {/* reflection hint */}
      <ellipse cx="27" cy="44" rx="20" ry="2" fill="rgba(255,255,255,0.15)" />
    </svg>
  )
}

function Sailboats({ visible }) {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        pointerEvents: 'none',
        opacity: visible ? 1 : 0,
        transition: 'opacity 2.5s ease-in-out',
        zIndex: 2,
        overflow: 'hidden',
      }}
      aria-hidden="true"
    >
      {BOATS.map((b, i) => (
        // Outer div owns the drift animation (translateX). Inner div owns the
        // horizontal flip (scaleX). Separating them prevents the animation's
        // transform from overwriting the flip — a single element can only have
        // one transform, and the keyframe would win.
        <div
          key={i}
          style={{
            position: 'absolute',
            top: `${b.top}%`,
            left: 0,
            animation: `drift ${b.dur}s linear ${b.delay}s infinite`,
          }}
        >
          <div style={{ transform: b.dir === -1 ? 'scaleX(-1)' : 'none' }}>
            <Sailboat scale={b.scale} />
          </div>
        </div>
      ))}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Plane (day) — crosses the upper sky on a gentle diagonal, with a contrail
// ─────────────────────────────────────────────────────────────────────────────
function Plane({ visible }) {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        pointerEvents: 'none',
        opacity: visible ? 1 : 0,
        transition: 'opacity 2.5s ease-in-out',
        zIndex: 2,
        overflow: 'hidden',
      }}
      aria-hidden="true"
    >
      <div
        style={{
          position: 'absolute',
          top: '14%',
          left: 0,
          animation: 'planeCross 26s linear infinite',
        }}
      >
        {/* contrail */}
        <div
          style={{
            position: 'absolute',
            right: '100%',
            top: '50%',
            width: '140px',
            height: '2px',
            background: 'linear-gradient(to left, rgba(255,255,255,0.5), transparent)',
            transform: 'translateY(-50%)',
          }}
        />
        <svg width="40" height="40" viewBox="0 0 40 40" fill="none"
          style={{ transform: 'rotate(8deg)' }}>
          <path
            d="M38 20 L16 23 L6 14 L3 15 L9 23 L4 28 L1 27 L2 31 L8 31 L20 26 L38 22 Z"
            fill="rgba(255,255,255,0.95)"
          />
        </svg>
      </div>

      {/* keyframes for the plane crossing (defined inline so this component is
          self-contained; the drift/twinkle keyframes live in Tailwind config) */}
      <style>{`
        @keyframes planeCross {
          0%   { transform: translate(-160px, 0); }
          100% { transform: translate(calc(100vw + 160px), 40px); }
        }
      `}</style>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Fireworks (both modes) — canvas particle burst on tower click
// ─────────────────────────────────────────────────────────────────────────────
const IRIS_COLORS = ['#2dd4bf', '#a78bfa', '#fb7185', '#fbbf24', '#38bdf8', '#f472b6']

function Fireworks({ burstKey }) {
  const canvasRef = useRef(null)
  const particlesRef = useRef([])
  const rafRef = useRef(null)
  const runningRef = useRef(false)

  const spawnBurst = useCallback((cx, cy) => {
    const count = 26 + Math.floor(Math.random() * 10)
    const color = IRIS_COLORS[Math.floor(Math.random() * IRIS_COLORS.length)]
    for (let i = 0; i < count; i++) {
      const angle = (Math.PI * 2 * i) / count + Math.random() * 0.3
      const speed = 2 + Math.random() * 4
      particlesRef.current.push({
        x: cx, y: cy,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: 1,
        decay: 0.012 + Math.random() * 0.012,
        color,
        size: 1.5 + Math.random() * 2,
      })
    }
  }, [])

  const tick = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    const ps = particlesRef.current
    for (let i = ps.length - 1; i >= 0; i--) {
      const p = ps[i]
      p.vx *= 0.985           // air drag
      p.vy *= 0.985
      p.vy += 0.06            // gravity
      p.x += p.vx
      p.y += p.vy
      p.life -= p.decay

      if (p.life <= 0) { ps.splice(i, 1); continue }

      ctx.globalAlpha = Math.max(0, p.life)
      ctx.fillStyle = p.color
      ctx.shadowBlur = 8
      ctx.shadowColor = p.color
      ctx.beginPath()
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2)
      ctx.fill()
    }
    ctx.globalAlpha = 1
    ctx.shadowBlur = 0

    if (ps.length > 0) {
      rafRef.current = requestAnimationFrame(tick)
    } else {
      runningRef.current = false
    }
  }, [])

  // Trigger a show whenever burstKey changes (and is > 0)
  useEffect(() => {
    if (!burstKey) return
    const canvas = canvasRef.current
    if (!canvas) return

    canvas.width = window.innerWidth
    canvas.height = window.innerHeight

    // Tower tip is ~55% across, ~8% down. Launch several bursts around there,
    // staggered over ~1.2s, at varied positions for a mini-show.
    const towerX = window.innerWidth * 0.55
    const towerTopY = window.innerHeight * 0.10

    const positions = [
      [towerX,                     towerTopY],
      [towerX - 90,                towerTopY + 60],
      [towerX + 100,               towerTopY + 40],
      [towerX - 40,                towerTopY - 20],
      [towerX + 50,                towerTopY + 90],
      [towerX,                     towerTopY + 130],
    ]

    positions.forEach(([x, y], idx) => {
      setTimeout(() => spawnBurst(x, y), idx * 200)
    })

    if (!runningRef.current) {
      runningRef.current = true
      rafRef.current = requestAnimationFrame(tick)
    }

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [burstKey, spawnBurst, tick])

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 6,
      }}
      aria-hidden="true"
    />
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main export
// ─────────────────────────────────────────────────────────────────────────────
export default function AnimatedElements({ mode = 'night', burstKey = 0 }) {
  const isNight = mode === 'night'
  return (
    <>
      <Stars visible={isNight} />
      <Sailboats visible={!isNight} />
      <Plane visible={!isNight} />
      <Fireworks burstKey={burstKey} />
    </>
  )
}