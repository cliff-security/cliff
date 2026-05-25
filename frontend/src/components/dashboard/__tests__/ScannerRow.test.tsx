import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ScannerRow, { type ScannerRowData } from '../ScannerRow'

const DONE: ScannerRowData = {
  id: 'trivy',
  label: 'Trivy',
  state: 'done',
  icon: 'bug_report',
  result: { kind: 'findings_count', value: 0, text: '0 findings' },
}

const SKIPPED_TIMEOUT: ScannerRowData = {
  id: 'semgrep',
  label: 'Semgrep',
  state: 'skipped',
  error: 'timeout',
  icon: 'code',
  result: null,
}

describe('<ScannerRow />', () => {
  it('done state renders the success check and the findings count', () => {
    render(<ScannerRow tool={DONE} />)
    const row = screen.getByTestId('scanner-row-trivy')
    expect(row).toHaveAttribute('data-state', 'done')
    expect(screen.getByTestId('scanner-row-status-done')).toBeInTheDocument()
    expect(screen.getByTestId('scanner-row-findings-chip')).toHaveTextContent(
      '0 findings',
    )
  })

  it('skipped+timeout renders a warning status, NOT a green check', () => {
    render(<ScannerRow tool={SKIPPED_TIMEOUT} />)
    const row = screen.getByTestId('scanner-row-semgrep')
    expect(row).toHaveAttribute('data-state', 'skipped')
    expect(
      screen.getByTestId('scanner-row-status-skipped'),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId('scanner-row-status-done'),
    ).not.toBeInTheDocument()
  })

  it('skipped scanner does not show a misleading "0 findings" chip', () => {
    render(<ScannerRow tool={SKIPPED_TIMEOUT} />)
    expect(
      screen.queryByTestId('scanner-row-findings-chip'),
    ).not.toBeInTheDocument()
    // it shows a skipped chip that names the reason instead
    const chip = screen.getByTestId('scanner-row-skipped-chip')
    expect(chip).toHaveTextContent(/timed out/i)
  })

  it('skipped chip reflects the error reason', () => {
    render(
      <ScannerRow
        tool={{ ...SKIPPED_TIMEOUT, error: 'binary_missing' }}
      />,
    )
    expect(screen.getByTestId('scanner-row-skipped-chip')).toHaveTextContent(
      /unavailable/i,
    )
  })

  it('skipped status carries a title explaining what happened', () => {
    render(<ScannerRow tool={SKIPPED_TIMEOUT} />)
    const status = screen.getByTestId('scanner-row-status-skipped')
    expect(status.getAttribute('title') ?? '').toMatch(/timed out|configure/i)
  })
})
