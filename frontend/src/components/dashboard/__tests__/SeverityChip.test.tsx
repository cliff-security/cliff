import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { SeverityChip } from '@/components/dashboard/SeverityChip'

describe('SeverityChip', () => {
  it('renders the label and count for each kind', () => {
    render(
      <>
        <SeverityChip kind="critical" count={3} />
        <SeverityChip kind="high" count={2} />
        <SeverityChip kind="medium" count={5} />
        <SeverityChip kind="low" count={1} />
        <SeverityChip kind="code" count={4} />
      </>,
    )
    expect(screen.getByTestId('severity-chip-critical')).toHaveTextContent('Critical')
    expect(screen.getByTestId('severity-chip-critical')).toHaveTextContent('3')
    expect(screen.getByTestId('severity-chip-medium')).toHaveTextContent('Medium')
    expect(screen.getByTestId('severity-chip-medium')).toHaveTextContent('5')
    expect(screen.getByTestId('severity-chip-code')).toHaveTextContent('Code')
  })

  it('test_severity_chip_medium_uses_warning_token', () => {
    /**
     * Architect-mandated regression guard (ADR-0029).
     *
     * The Claude design's reference JSX defaults medium severity to the
     * tertiary token family. That is wrong for the Cliff codebase: PRD-0004
     * landed the warning token specifically for medium severity, stale data,
     * and degraded service. Medium chips MUST use:
     *
     *   bg-warning-container/40 text-on-warning-container
     *
     * Do not loosen this assertion.
     */
    render(<SeverityChip kind="medium" count={5} />)
    const chip = screen.getByTestId('severity-chip-medium')
    const className = chip.className
    expect(className).toContain('bg-warning-container/40')
    expect(className).toContain('text-on-warning-container')
    // And critically, NOT the tertiary token the Claude design uses.
    expect(className).not.toContain('tertiary')
  })

  it('uses the error family for critical and high severity', () => {
    render(
      <>
        <SeverityChip kind="critical" count={1} />
        <SeverityChip kind="high" count={1} />
      </>,
    )
    expect(screen.getByTestId('severity-chip-critical').className).toContain(
      'text-error',
    )
    expect(screen.getByTestId('severity-chip-high').className).toContain(
      'text-error',
    )
  })

  it('exposes a screen-reader-friendly count label', () => {
    render(<SeverityChip kind="critical" count={3} />)
    expect(screen.getByLabelText('3 critical')).toBeInTheDocument()
  })
})
