import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import LastAssessmentPanel, {
  type LastAssessmentInfo,
} from '../LastAssessmentPanel'
import { formatDurationMs } from '../durationFormat'

const FIXTURE: LastAssessmentInfo = {
  repo_url: 'https://github.com/acme/fast-markdown',
  finished_at: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
  duration_ms: 257_000,
  commit_sha: 'a3f81c2',
  branch: 'main',
  scanned_files: 4128,
  scanned_deps: 312,
  scanners: [
    {
      id: 'trivy',
      label: 'Trivy 0.52.2',
      icon: 'bug_report',
      version: '0.52.2',
      ran: 'Dependency + secret scan',
      scope: '312 deps · npm + pip · git history',
      duration_ms: 38_400,
      result: { kind: 'findings_count', value: 7, text: '7 findings' },
    },
    {
      id: 'semgrep',
      label: 'Semgrep 1.70.0',
      icon: 'code',
      version: '1.70.0',
      ran: 'Static analysis (p/security-audit)',
      scope: '4128 files · p/security-audit',
      duration_ms: 71_200,
      result: { kind: 'findings_count', value: 3, text: '3 findings' },
    },
    {
      id: 'posture',
      label: '15 posture checks',
      icon: 'rule',
      version: '1.0.0',
      ran: '15 repo + cloud configuration checks',
      scope: '15 repo + cloud configuration checks',
      duration_ms: 9_600,
      result: { kind: 'pass_count', value: 12, text: '12 pass' },
    },
  ],
}

describe('<LastAssessmentPanel />', () => {
  it('renders one ScannerRow per scanner (Trivy + Semgrep + Posture)', () => {
    render(<LastAssessmentPanel data={FIXTURE} />)
    expect(screen.getByTestId('scanner-row-trivy')).toBeInTheDocument()
    expect(screen.getByTestId('scanner-row-semgrep')).toBeInTheDocument()
    expect(screen.getByTestId('scanner-row-posture')).toBeInTheDocument()
  })

  it("Trivy's row uses combined ran + scope copy (CEO call: one invocation)", () => {
    render(<LastAssessmentPanel data={FIXTURE} />)
    const row = screen.getByTestId('scanner-row-trivy')
    expect(row).toHaveTextContent('Dependency + secret scan')
    expect(row).toHaveTextContent('git history')
  })

  it('reassess fires onReassess and disables while in flight', () => {
    const onReassess = vi.fn()
    const { rerender } = render(
      <LastAssessmentPanel data={FIXTURE} onReassess={onReassess} />,
    )
    fireEvent.click(screen.getByTestId('last-assessment-reassess'))
    expect(onReassess).toHaveBeenCalledTimes(1)

    rerender(
      <LastAssessmentPanel
        data={FIXTURE}
        onReassess={onReassess}
        reassessing
      />,
    )
    const btn = screen.getByTestId(
      'last-assessment-reassess',
    ) as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn).toHaveTextContent(/Re-assessing/)
  })

  it('renders a friendly "no prior assessment" subtitle when fields are empty', () => {
    render(
      <LastAssessmentPanel
        data={{ repo_url: 'https://github.com/acme/x', scanners: [] }}
      />,
    )
    expect(
      screen.getByText(/No scanner output captured/i),
    ).toBeInTheDocument()
  })
})

describe('formatDurationMs', () => {
  it.each([
    [0, '0.0s'],
    [9_900, '9.9s'],
    [60_000, '1m 0s'],
    [240_000, '4m 0s'],
    [257_000, '4m 17s'],
  ])('formats %i ms as %s', (ms, expected) => {
    expect(formatDurationMs(ms)).toBe(expected)
  })

  it('returns dash for null / undefined', () => {
    expect(formatDurationMs(null)).toBe('—')
    expect(formatDurationMs(undefined)).toBe('—')
  })
})
