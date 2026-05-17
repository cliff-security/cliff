import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import RemediationResultCard from '../RemediationResultCard'
import type { RemediationExecutorOutput } from '@/api/client'

const prCreatedData: RemediationExecutorOutput = {
  status: 'pr_created',
  pr_url: 'https://github.com/acme/repo/pull/42',
  branch_name: 'cliff/fix/cve-2026-1234',
  changes_summary: 'Updated lodash from 4.17.20 to 4.17.21 in package.json',
  test_results: 'All 50 tests passed',
  error_details: null,
}

const failedData: RemediationExecutorOutput = {
  status: 'failed',
  pr_url: null,
  branch_name: 'cliff/fix/cve-2026-1234',
  changes_summary: 'Updated lodash in package.json',
  test_results: '3 of 50 tests failed',
  error_details: 'TypeError: merge is not a function in src/utils.test.js',
}

describe('RemediationResultCard', () => {
  it('renders agent label', () => {
    render(<RemediationResultCard data={prCreatedData} />)
    expect(screen.getByText('Remediation result')).toBeInTheDocument()
  })

  it('renders pr_created status', () => {
    render(<RemediationResultCard data={prCreatedData} />)
    expect(screen.getByText('PR created')).toBeInTheDocument()
  })

  it('renders branch name', () => {
    render(<RemediationResultCard data={prCreatedData} />)
    expect(screen.getByText('cliff/fix/cve-2026-1234')).toBeInTheDocument()
  })

  it('renders changes summary', () => {
    render(<RemediationResultCard data={prCreatedData} />)
    expect(screen.getByText(/Updated lodash/)).toBeInTheDocument()
  })

  it('renders test results', () => {
    render(<RemediationResultCard data={prCreatedData} />)
    expect(screen.getByText('All 50 tests passed')).toBeInTheDocument()
  })

  it('renders PR link that opens in new tab', () => {
    render(<RemediationResultCard data={prCreatedData} />)
    const link = screen.getByText('View pull request')
    expect(link).toBeInTheDocument()
    expect(link.closest('a')).toHaveAttribute('href', 'https://github.com/acme/repo/pull/42')
    expect(link.closest('a')).toHaveAttribute('target', '_blank')
  })

  it('renders failed status', () => {
    render(<RemediationResultCard data={failedData} />)
    expect(screen.getByText('Failed')).toBeInTheDocument()
  })

  it('does not render PR link when pr_url is null', () => {
    render(<RemediationResultCard data={failedData} />)
    expect(screen.queryByText('View pull request')).not.toBeInTheDocument()
  })

  it('renders confidence badge', () => {
    render(<RemediationResultCard data={prCreatedData} confidence={0.85} />)
    expect(screen.getByText('High')).toBeInTheDocument()
  })

  it('handles minimal data gracefully', () => {
    const minimalData: RemediationExecutorOutput = {
      status: 'changes_made',
      pr_url: null,
      branch_name: null,
      changes_summary: null,
      test_results: null,
      error_details: null,
    }
    render(<RemediationResultCard data={minimalData} />)
    expect(screen.getByText('Remediation result')).toBeInTheDocument()
    expect(screen.getByText('Changes made')).toBeInTheDocument()
  })
})
