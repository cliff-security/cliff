import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { makeFinding } from '../../../test/fixtures/finding'
import { IssuesHeader, type SeverityFilter } from '../IssuesHeader'

describe('IssuesHeader', () => {
  it('renders the page title "Issues"', () => {
    render(
      <IssuesHeader
        findings={[]}
        grade={null}
        severityFilter="all"
        onSeverityFilterChange={() => {}}
      />,
    )
    expect(screen.getByRole('heading', { name: /^Issues$/ })).toBeInTheDocument()
  })

  it('renders open count + closed-last-7d + grade caption', () => {
    const now = new Date('2026-04-29T12:00:00Z')
    vi.useFakeTimers()
    vi.setSystemTime(now)
    const sixDaysAgo = '2026-04-23T12:00:00Z'
    const tenDaysAgo = '2026-04-19T12:00:00Z'
    const findings = [
      makeFinding({ id: 'a', stage: 'todo', severity: 'high' }),
      makeFinding({ id: 'b', stage: 'plan_ready', severity: 'critical' }),
      makeFinding({ id: 'c', stage: 'generating', severity: 'medium' }),
      makeFinding({
        id: 'd',
        stage: 'fixed',
        severity: 'low',
        updated_at: sixDaysAgo,
      }),
      makeFinding({
        id: 'e',
        stage: 'fixed',
        severity: 'low',
        updated_at: tenDaysAgo,
      }),
    ]
    render(
      <IssuesHeader
        findings={findings}
        grade="B"
        severityFilter="all"
        onSeverityFilterChange={() => {}}
      />,
    )
    expect(screen.getByTestId('issues-caption').textContent).toContain('3 open')
    expect(screen.getByTestId('issues-caption').textContent).toContain(
      '1 closed in the last 7 days',
    )
    expect(screen.getByTestId('issues-caption').textContent).toContain('grade B')
    vi.useRealTimers()
  })

  it('renders pre-assessment when grade is missing', () => {
    render(
      <IssuesHeader
        findings={[]}
        grade={null}
        severityFilter="all"
        onSeverityFilterChange={() => {}}
      />,
    )
    expect(screen.getByTestId('issues-caption').textContent).toContain('pre-assessment')
  })

  it('renders Type chip group with [All issues, Vulnerability, Posture]', () => {
    render(
      <IssuesHeader
        findings={[]}
        grade={null}
        severityFilter="all"
        onSeverityFilterChange={() => {}}
      />,
    )
    expect(screen.getByRole('button', { name: /All issues/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Vulnerability/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Posture/i })).toBeInTheDocument()
  })

  it('emits severity-filter changes when a severity chip is clicked', () => {
    const onChange = vi.fn<(filter: SeverityFilter) => void>()
    render(
      <IssuesHeader
        findings={[]}
        grade={null}
        severityFilter="all"
        onSeverityFilterChange={onChange}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /^Critical/i }))
    expect(onChange).toHaveBeenCalledWith('critical')
  })

  it('marks the active severity chip with aria-pressed', () => {
    render(
      <IssuesHeader
        findings={[]}
        grade={null}
        severityFilter="high"
        onSeverityFilterChange={() => {}}
      />,
    )
    expect(
      screen.getByRole('button', { name: /^High/i }).getAttribute('aria-pressed'),
    ).toBe('true')
  })

  it('renders severity counts in the chips', () => {
    const findings = [
      makeFinding({ id: 'a', stage: 'todo', severity: 'critical' }),
      makeFinding({ id: 'b', stage: 'todo', severity: 'high' }),
      makeFinding({ id: 'c', stage: 'todo', severity: 'high' }),
    ]
    render(
      <IssuesHeader
        findings={findings}
        grade={null}
        severityFilter="all"
        onSeverityFilterChange={() => {}}
      />,
    )
    // Critical chip count = 1
    const critical = screen.getByRole('button', { name: /^Critical/i })
    expect(critical.textContent).toContain('1')
    // High chip count = 2
    const high = screen.getByRole('button', { name: /^High/i })
    expect(high.textContent).toContain('2')
  })
})
