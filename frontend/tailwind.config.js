/** @type {import('tailwindcss').Config} */
export default {
    content: [
      './index.html',
      './src/**/*.{js,jsx,ts,tsx}',
    ],
  
    // Dark mode is toggled by adding the "dark" class to <html>.
    // useTorontoTheme.js manages this based on Toronto time + manual override.
    darkMode: 'class',
  
    theme: {
      extend: {
        fontFamily: {
          sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        },
        colors: {
          // Night sky palette
          night: {
            950: '#050810',
            900: '#0a0e1a',
            800: '#111827',
            700: '#1a2540',
          },
          // Day sky palette
          day: {
            50:  '#f0f9ff',
            100: '#e0f4ff',
            200: '#bae6fd',
            300: '#87ceeb',
          },
          // Iridescent accent ramp — used for glow effects, stage status dots,
          // and the aurora layer
          iris: {
            teal:   '#2dd4bf',
            violet: '#a78bfa',
            rose:   '#fb7185',
            gold:   '#fbbf24',
          },
        },
        backdropBlur: {
          xs: '2px',
          glass: '20px',
        },
        animation: {
          'aurora':    'aurora 12s ease-in-out infinite',
          'twinkle':   'twinkle 3s ease-in-out infinite',
          'drift':     'drift 60s linear infinite',
          'pulse-dot': 'pulseDot 2s ease-in-out infinite',
          'firework':  'firework 2s ease-out forwards',
        },
        keyframes: {
          aurora: {
            '0%, 100%': { filter: 'hue-rotate(0deg) brightness(1)' },
            '33%':      { filter: 'hue-rotate(60deg) brightness(1.1)' },
            '66%':      { filter: 'hue-rotate(120deg) brightness(0.95)' },
          },
          twinkle: {
            '0%, 100%': { opacity: '1' },
            '50%':      { opacity: '0.3' },
          },
          drift: {
            '0%':   { transform: 'translateX(-120px)' },
            '100%': { transform: 'translateX(calc(100vw + 120px))' },
          },
          pulseDot: {
            '0%, 100%': { boxShadow: '0 0 0 0 rgba(45, 212, 191, 0.4)' },
            '50%':      { boxShadow: '0 0 0 8px rgba(45, 212, 191, 0)' },
          },
        },
      },
    },
  
    plugins: [],
  }