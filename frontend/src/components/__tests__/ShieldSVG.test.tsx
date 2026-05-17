import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ShieldSVG from '../completion/ShieldSVG'

describe('ShieldSVG', () => {
  it('renders at the default celebration size (150×180)', () => {
    const { container } = render(<ShieldSVG completedDate="2026-04-14" />)
    const svg = container.querySelector('svg')!
    expect(svg).not.toBeNull()
    expect(svg.getAttribute('width')).toBe('150')
    expect(svg.getAttribute('height')).toBe('180')
    expect(svg.getAttribute('viewBox')).toBe('0 0 160 190')
  })

  it.each([
    [56, 64],
    [80, 96],
    [150, 180],
  ])('accepts width=%i height=%i from props (three sanctioned sizes)', (w, h) => {
    const { container } = render(
      <ShieldSVG completedDate="2026-04-14" width={w} height={h} />,
    )
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('width')).toBe(String(w))
    expect(svg.getAttribute('height')).toBe(String(h))
  })

  it('renders the COMPLETED {date} caption verbatim', () => {
    const { container } = render(
      <ShieldSVG completedDate="2026-04-14" />,
    )
    expect(container.textContent).toMatch(/COMPLETED\s+2026-04-14/)
  })

  it('announces itself as an image with a descriptive aria-label by default', () => {
    const { container } = render(
      <ShieldSVG completedDate="2026-04-14" />,
    )
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('role')).toBe('img')
    expect(svg.getAttribute('aria-label')).toMatch(/Cliff/i)
  })

  it('allows callers to mark it decorative via aria-hidden', () => {
    const { container } = render(
      <ShieldSVG completedDate="2026-04-14" ariaHidden />,
    )
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('aria-hidden')).toBe('true')
    // When decorative, no role/label should pollute the a11y tree.
    expect(svg.getAttribute('role')).toBeNull()
  })
})
