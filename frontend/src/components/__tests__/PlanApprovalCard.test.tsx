import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import PlanApprovalCard from '../PlanApprovalCard'
import type { PlanOutput } from '@/api/client'

const basePlan: PlanOutput = {
  plan_steps: [
    'Upgrade lodash from 4.17.20 to 4.17.21',
    'Run npm install to update lockfile',
    'Run test suite to verify no regressions',
  ],
  definition_of_done: [
    'lodash >= 4.17.21 in package.json',
    'Tests pass',
  ],
  interim_mitigation: null,
  dependencies: [],
  estimated_effort: null,
  suggested_due_date: null,
  validation_method: null,
}

describe('PlanApprovalCard', () => {
  it('renders plan steps', () => {
    render(<PlanApprovalCard plan={basePlan} onApprove={vi.fn()} onModify={vi.fn()} />)
    expect(screen.getByText('Plan approval')).toBeInTheDocument()
    expect(screen.getByText(/Upgrade lodash/)).toBeInTheDocument()
    expect(screen.getByText('1.')).toBeInTheDocument()
    expect(screen.getByText('2.')).toBeInTheDocument()
    expect(screen.getByText('3.')).toBeInTheDocument()
  })

  it('renders branch name when provided', () => {
    render(
      <PlanApprovalCard
        plan={basePlan}
        branchName="cliff/fix/cve-2026-1234"
        onApprove={vi.fn()}
        onModify={vi.fn()}
      />
    )
    expect(screen.getByText('cliff/fix/cve-2026-1234')).toBeInTheDocument()
  })

  it('renders definition of done', () => {
    render(<PlanApprovalCard plan={basePlan} onApprove={vi.fn()} onModify={vi.fn()} />)
    expect(screen.getByText(/lodash >= 4.17.21/)).toBeInTheDocument()
    expect(screen.getByText('Tests pass')).toBeInTheDocument()
  })

  it('calls onApprove when approve button clicked', async () => {
    const user = userEvent.setup()
    const onApprove = vi.fn()
    render(<PlanApprovalCard plan={basePlan} onApprove={onApprove} onModify={vi.fn()} />)

    await user.click(screen.getByText('Approve and start'))
    expect(onApprove).toHaveBeenCalledOnce()
  })

  it('shows loading state after approve', async () => {
    const user = userEvent.setup()
    render(<PlanApprovalCard plan={basePlan} onApprove={vi.fn()} onModify={vi.fn()} />)

    await user.click(screen.getByText('Approve and start'))
    expect(screen.getByText('Starting...')).toBeInTheDocument()
  })

  it('calls onModify when modify button clicked', async () => {
    const user = userEvent.setup()
    const onModify = vi.fn()
    render(<PlanApprovalCard plan={basePlan} onApprove={vi.fn()} onModify={onModify} />)

    await user.click(screen.getByText('Modify plan'))
    expect(onModify).toHaveBeenCalledOnce()
  })
})
