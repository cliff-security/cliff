import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { IssueSeverityBadge } from '../IssueSeverityBadge'

describe('IssueSeverityBadge', () => {
  const kinds = ['critical', 'high', 'medium', 'low'] as const

  it.each(kinds)('renders %s with the matching label and accessible name', (kind) => {
    render(<IssueSeverityBadge kind={kind} />)
    const badge = screen.getByLabelText(new RegExp(`severity ${kind}`, 'i'))
    expect(badge).toBeInTheDocument()
    expect(badge.textContent?.toLowerCase()).toContain(kind)
  })

  // Cyberdeck severity chips render in Inter 12px (cd-chip base) for both
  // `md` and `sm` sizes — only padding tightens at `sm`. The test below
  // exercises the padding contract instead of the font size.
  it.each(kinds)('renders %s in sm size with tighter paddings', (kind) => {
    render(<IssueSeverityBadge kind={kind} size="sm" />)
    const badge = screen.getByLabelText(new RegExp(`severity ${kind}`, 'i'))
    expect(badge).toBeInTheDocument()
    expect(badge.style.padding).toMatch(/2px\s*7px/)
  })

  it('uses the rose cd-chip variant for critical', () => {
    render(<IssueSeverityBadge kind="critical" />)
    const badge = screen.getByLabelText(/severity critical/i)
    expect(badge.className).toMatch(/cd-chip(\s|--).*red/)
  })

  it('uses the amber cd-chip variant for high', () => {
    render(<IssueSeverityBadge kind="high" />)
    const badge = screen.getByLabelText(/severity high/i)
    expect(badge.className).toMatch(/cd-chip(\s|--).*amber/)
  })

  it('uses the cyan cd-chip variant for medium', () => {
    render(<IssueSeverityBadge kind="medium" />)
    const badge = screen.getByLabelText(/severity medium/i)
    expect(badge.className).toMatch(/cd-chip(\s|--).*cyan/)
  })

  it('uses the ink cd-chip variant for low', () => {
    render(<IssueSeverityBadge kind="low" />)
    const badge = screen.getByLabelText(/severity low/i)
    expect(badge.className).toMatch(/cd-chip(\s|--).*ink/)
  })

  it('renders the severity icon as a Material Symbols span', () => {
    render(<IssueSeverityBadge kind="critical" />)
    const badge = screen.getByLabelText(/severity critical/i)
    const icon = badge.querySelector('span.material-symbols-outlined')
    expect(icon).not.toBeNull()
    expect(icon?.textContent).toBe('crisis_alert')
  })
})
