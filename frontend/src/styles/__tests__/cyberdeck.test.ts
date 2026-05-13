import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const cssPath = resolve(here, '..', 'cyberdeck.css')
const mainPath = resolve(here, '..', '..', 'main.tsx')
const tailwindConfigPath = resolve(here, '..', '..', '..', 'tailwind.config.ts')

const css = readFileSync(cssPath, 'utf8')
const mainTsx = readFileSync(mainPath, 'utf8')
const tailwindConfigSource = readFileSync(tailwindConfigPath, 'utf8')

describe('cyberdeck CSS utilities (Epic 0)', () => {
  it('test_cyberdeck_css_imports: main.tsx imports the stylesheet', () => {
    expect(mainTsx).toMatch(/['"][./@a-zA-Z-]*styles\/cyberdeck\.css['"]/)
  })

  it('test_spinner_animation_applied: defines .spinner with spin keyframes and reduced-motion override', () => {
    expect(css).toMatch(/\.spinner\b/)
    expect(css).toMatch(/\.spinner-lg\b/)
    expect(css).toMatch(/@keyframes\s+spin\b/)
  })

  it('test_animate_pulse_subtle_animation_applied: defines .animate-pulse-subtle and keyframes', () => {
    expect(css).toMatch(/\.animate-pulse-subtle\b/)
    expect(css).toMatch(/@keyframes\s+pulse-subtle\b/)
  })

  it('test_grade_ring_conic_gradient: .grade-ring uses conic-gradient', () => {
    expect(css).toMatch(/\.grade-ring\b/)
    expect(css).toMatch(/conic-gradient/)
  })

  it('respects prefers-reduced-motion for spinner and pulse animations', () => {
    expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/)
  })

  it('defines .msym-filled as a stroke-only Material Symbol shim', () => {
    // Cyberdeck rule is stroke-only icons everywhere; the legacy
    // `.msym-filled` utility is kept for back-compat but now renders
    // with FILL 0 so it doesn't introduce filled blobs on the dark UI.
    expect(css).toMatch(/\.msym-filled\b/)
    expect(css).toMatch(/'FILL'\s*0/)
  })

  it('tailwind config exposes JetBrains Mono in fontFamily.mono', () => {
    expect(tailwindConfigSource).toMatch(/mono:\s*\[\s*['"]JetBrains Mono['"]/)
  })
})
