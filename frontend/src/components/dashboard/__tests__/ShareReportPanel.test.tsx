import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ShareReportPanel from '../ShareReportPanel'

const CRITERIA = [
  { key: 'no_critical_vulns', label: 'No critical vulns', met: true },
  { key: 'no_high_vulns', label: 'No high vulns', met: false },
  { key: 'security_md_present', label: 'SECURITY.md present', met: true },
  { key: 'code_owners_exists', label: 'Code owners file exists', met: false },
]

describe('<ShareReportPanel />', () => {
  it('renders nothing interactive when closed', () => {
    render(
      <ShareReportPanel
        open={false}
        onClose={() => {}}
        grade="D"
        repoName="cliff-security/litellm"
        criteria={CRITERIA}
      />,
    )
    const panel = screen.getByTestId('share-report-panel')
    // dialog without the open attribute is not shown
    expect(panel).not.toHaveAttribute('open')
  })

  it('preview state (non-A grade): lists criteria and shows the remaining count', () => {
    render(
      <ShareReportPanel
        open
        onClose={() => {}}
        grade="D"
        repoName="cliff-security/litellm"
        criteria={CRITERIA}
      />,
    )
    const panel = screen.getByTestId('share-report-panel')
    expect(panel).toHaveAttribute('open')
    // criteria checklist — one row per criterion
    expect(screen.getByTestId('share-report-panel')).toHaveTextContent(
      'No high vulns',
    )
    expect(screen.getByTestId('share-report-panel')).toHaveTextContent(
      'SECURITY.md present',
    )
    // 2 of 4 met → "2 of 4 criteria met"
    expect(panel).toHaveTextContent('2 of 4 criteria met')
    // motivating preview line names the remaining count
    expect(screen.getByTestId('share-report-preview-line')).toHaveTextContent(
      '2',
    )
  })

  it('earned state (grade A): shows the badge-earned message, not the preview line', () => {
    const allMet = CRITERIA.map((c) => ({ ...c, met: true }))
    render(
      <ShareReportPanel
        open
        onClose={() => {}}
        grade="A"
        repoName="cliff-security/litellm"
        criteria={allMet}
      />,
    )
    expect(screen.getByTestId('share-report-earned-line')).toBeInTheDocument()
    expect(
      screen.queryByTestId('share-report-preview-line'),
    ).not.toBeInTheDocument()
    expect(screen.getByTestId('share-report-panel')).toHaveTextContent(
      '4 of 4 criteria met',
    )
  })

  it('close button calls onClose', () => {
    const onClose = vi.fn()
    render(
      <ShareReportPanel
        open
        onClose={onClose}
        grade="D"
        repoName="cliff-security/litellm"
        criteria={CRITERIA}
      />,
    )
    fireEvent.click(screen.getByTestId('share-report-close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('each criterion row marks met vs unmet distinctly', () => {
    render(
      <ShareReportPanel
        open
        onClose={() => {}}
        grade="D"
        repoName="cliff-security/litellm"
        criteria={CRITERIA}
      />,
    )
    expect(
      screen.getByTestId('share-report-criterion-no_critical_vulns'),
    ).toHaveAttribute('data-met', 'true')
    expect(
      screen.getByTestId('share-report-criterion-no_high_vulns'),
    ).toHaveAttribute('data-met', 'false')
  })
})
