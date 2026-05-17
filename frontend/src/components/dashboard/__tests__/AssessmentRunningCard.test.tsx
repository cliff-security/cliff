import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import AssessmentRunningCard from '../AssessmentRunningCard'

describe('<AssessmentRunningCard />', () => {
  const baseProps = {
    repoUrl: 'https://github.com/acme/fast-markdown',
    startedAt: new Date(Date.now() - 84 * 1000).toISOString(),
    progressPct: 24,
    tools: [
      {
        id: 'trivy',
        label: 'Trivy 0.52.2',
        icon: 'bug_report',
        state: 'done' as const,
      },
      {
        id: 'semgrep',
        label: 'Semgrep 1.70.0',
        icon: 'code',
        state: 'active' as const,
      },
      {
        id: 'posture',
        label: '15 posture checks',
        icon: 'rule',
        state: 'pending' as const,
      },
    ],
    steps: [
      {
        key: 'detect',
        label: 'Detecting project type',
        state: 'done',
        result_summary: 'npm + Python',
      },
      {
        key: 'trivy_vuln',
        label: 'Building software bill of materials',
        state: 'running',
        progress_pct: 42,
        detail: 'Resolving 312 dependencies across npm and pip…',
      },
      {
        key: 'semgrep',
        label: 'Scanning code with Semgrep',
        state: 'pending',
        hint: '~120s',
      },
    ],
  }

  it('renders all three step states (done / running / pending)', () => {
    render(<AssessmentRunningCard {...baseProps} />)
    expect(screen.getByTestId('step-row-detect')).toHaveAttribute(
      'data-state',
      'done',
    )
    expect(screen.getByTestId('step-row-trivy_vuln')).toHaveAttribute(
      'data-state',
      'running',
    )
    expect(screen.getByTestId('step-row-semgrep')).toHaveAttribute(
      'data-state',
      'pending',
    )
  })

  it('renders the running step with its percent and per-step bar', () => {
    render(<AssessmentRunningCard {...baseProps} />)
    expect(screen.getByTestId('step-row-trivy_vuln')).toHaveTextContent('42%')
  })

  it('shows scanner pills with state-specific tones (active = pulse-dot)', () => {
    render(<AssessmentRunningCard {...baseProps} />)
    const active = screen.getByTestId('scanner-pill-semgrep')
    expect(active).toHaveAttribute('data-state', 'active')
    // The active pill embeds a span with the cliff-pulse-dot class.
    expect(active.querySelector('.cliff-pulse-dot')).not.toBeNull()
  })

  it('renders the elapsed timer formatted as MM:SS', () => {
    render(<AssessmentRunningCard {...baseProps} />)
    expect(screen.getByTestId('assessment-running-elapsed')).toHaveTextContent(
      /^0\d:\d{2}$/,
    )
  })

  it('overall progress bar reflects the prop', () => {
    render(<AssessmentRunningCard {...baseProps} />)
    const bar = screen.getByTestId('assessment-running-overall-bar')
    expect(bar.getAttribute('style')).toMatch(/width:\s*24%/)
  })
})
