import type { Config } from 'tailwindcss'
import typography from '@tailwindcss/typography'
import forms from '@tailwindcss/forms'
import containerQueries from '@tailwindcss/container-queries'

/**
 * Cliff Cyberdeck design tokens (replaces Serene Sentinel / Material 3 palette).
 *
 * Dark navy operator console with a single sage-mint accent. The existing
 * component tree refers to Material 3 names (bg-primary, text-on-surface, etc.);
 * we keep those identifiers but remap them to Cyberdeck values so most
 * components inherit the new look without per-file edits.
 *
 * Canonical token source: design_handoff_cliff_cyberdeck/design-system/colors_and_type.css
 */

// Cyberdeck palette — surfaces, ink, accents
const cd = {
  bg: '#0B101B',         // app body
  bg1: '#0E1422',        // nav, topbar
  bg2: '#0D1322',        // recessed wells
  card: '#131A2A',       // default card
  cardHov: '#161E32',    // row hover
  cardHi: '#1B2438',     // focused / active row
  rule: '#27324E',       // default hairline
  rule2: '#34405E',      // emphasised hairline / hover

  fg1: '#F2F6FE',        // hi-emphasis
  fg2: '#D6E0F4',        // body
  fg3: '#9BACCC',        // secondary
  fg4: '#6473A0',        // tertiary / meta
  fg5: '#44507A',        // disabled / hint

  neon: '#6FE3B5',       // sage — primary accent
  neonHi: '#9FECC9',
  cyan: '#7FC8DC',       // paths, agent identity, links
  magenta: '#E78AC4',    // secrets / identity
  amber: '#F0BF7E',      // attention / high severity
  red: '#E97A8E',        // critical only
}

const config: Config = {
  // Cyberdeck has no light variant — keep the `class` strategy but the app
  // always renders dark. Existing `dark:` modifiers in the tree become no-ops
  // unless we toggle the class; we leave the option open for the future.
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // --- Material 3 → Cyberdeck mapping -----------------------------
        // Surfaces (the ladder)
        'background': cd.bg,
        'surface': cd.bg,
        'surface-bright': cd.bg1,
        'surface-dim': cd.bg2,
        'surface-container-lowest': cd.bg,
        'surface-container-low': cd.bg1,
        'surface-container': cd.card,
        'surface-container-high': cd.cardHov,
        'surface-container-highest': cd.cardHi,
        'surface-variant': cd.cardHov,
        'inverse-surface': cd.fg1,
        'inverse-on-surface': cd.bg,

        // Ink
        'on-background': cd.fg2,
        'on-surface': cd.fg2,
        'on-surface-variant': cd.fg3,
        'outline': cd.fg4,
        'outline-variant': cd.rule,

        // Primary (sage)
        'primary': cd.neon,
        'primary-dim': cd.neonHi,
        'primary-fixed': cd.neon,
        'primary-fixed-dim': cd.neonHi,
        'primary-container': 'rgba(111,227,181,0.10)',
        'on-primary': cd.bg,
        'on-primary-fixed': cd.bg,
        'on-primary-fixed-variant': cd.neonHi,
        'on-primary-container': cd.neonHi,
        'surface-tint': cd.neon,
        'inverse-primary': cd.neonHi,

        // Secondary / Tertiary (cyan — agent identity, links)
        'secondary': cd.cyan,
        'secondary-dim': cd.cyan,
        'secondary-container': 'rgba(127,200,220,0.10)',
        'secondary-fixed': cd.cyan,
        'secondary-fixed-dim': cd.cyan,
        'on-secondary': cd.bg,
        'on-secondary-container': cd.cyan,
        'on-secondary-fixed': cd.cyan,
        'on-secondary-fixed-variant': cd.cyan,

        'tertiary': cd.cyan,
        'tertiary-dim': cd.cyan,
        'tertiary-container': 'rgba(127,200,220,0.10)',
        'tertiary-fixed': cd.cyan,
        'tertiary-fixed-dim': cd.cyan,
        'on-tertiary': cd.bg,
        'on-tertiary-container': cd.cyan,
        'on-tertiary-fixed': cd.cyan,
        'on-tertiary-fixed-variant': cd.cyan,

        // Error (rose)
        'error': cd.red,
        'error-dim': cd.red,
        'error-container': 'rgba(233,122,142,0.14)',
        'on-error': cd.bg,
        'on-error-container': cd.red,

        // Warning (amber) — ADR-0029 still in the codebase
        'warning': cd.amber,
        'warning-dim': cd.amber,
        'warning-container': 'rgba(240,191,126,0.14)',
        'on-warning-container': cd.amber,

        // --- Cyberdeck-native names (cd-*) for new code ----------------
        'cd-bg': cd.bg,
        'cd-bg-1': cd.bg1,
        'cd-bg-2': cd.bg2,
        'cd-card': cd.card,
        'cd-card-hov': cd.cardHov,
        'cd-card-hi': cd.cardHi,
        'cd-rule': cd.rule,
        'cd-rule-2': cd.rule2,
        'cd-fg-1': cd.fg1,
        'cd-fg-2': cd.fg2,
        'cd-fg-3': cd.fg3,
        'cd-fg-4': cd.fg4,
        'cd-fg-5': cd.fg5,
        'cd-neon': cd.neon,
        'cd-neon-hi': cd.neonHi,
        'cd-cyan': cd.cyan,
        'cd-magenta': cd.magenta,
        'cd-amber': cd.amber,
        'cd-red': cd.red,
      },
      fontFamily: {
        headline: ['Manrope', 'sans-serif'],
        display: ['Manrope', 'sans-serif'],
        body: ['Inter', 'sans-serif'],
        label: ['JetBrains Mono', 'monospace'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      borderRadius: {
        // Cyberdeck is almost square — clamp all radii to <=6px except `full`.
        DEFAULT: '2px',
        none: '0',
        sm: '2px',
        md: '4px',
        lg: '4px',
        xl: '6px',
        '2xl': '6px',
        '3xl': '6px',
        full: '9999px',
      },
      letterSpacing: {
        tightest: '-0.045em',
        tighter: '-0.03em',
        tactical: '0.22em',
      },
      boxShadow: {
        'neon': '0 0 12px rgba(111,227,181,0.40)',
        'neon-soft': '0 0 8px rgba(111,227,181,0.30)',
        'neon-strong': '0 0 22px rgba(111,227,181,0.40)',
        'red-glow': '0 0 12px rgba(233,122,142,0.45)',
      },
    },
  },
  plugins: [typography, forms, containerQueries],
}

export default config
