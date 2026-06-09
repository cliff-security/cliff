import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { FindingStatus, IssueStage } from '../../../api/client'
import { makeFinding as baseMakeFinding } from '../../../test/fixtures/finding'
import { IssueRow } from '../IssueRow'

function makeFinding(opts: { stage: IssueStage; status?: FindingStatus }) {
  // IssueRow tests render a CVE-flavoured finding so the metadata row
  // assertions have something to look for.
  return {
    ...baseMakeFinding({
      id: 'CVE-2024-1234',
      stage: opts.stage,
      status: opts.status,
      severity: 'critical',
      workspaceId: 'w-1',
    }),
    title: 'CVE-2024-1234 in libfoo',
    description: 'Remote code execution',
    asset_id: 'srv-web-01',
    asset_label: 'Web Server 01',
    normalized_priority: 'P1',
  }
}

describe('IssueRow', () => {
  it('renders title and source-id metadata row', () => {
    render(<IssueRow finding={makeFinding({ stage: 'todo' })} />)
    expect(screen.getByText(/CVE-2024-1234 in libfoo/)).toBeInTheDocument()
    // The source_id appears in the metadata row in mono.
    const ids = screen.getAllByText('CVE-2024-1234')
    expect(ids.length).toBeGreaterThan(0)
  })

  it('renders the bug_report icon for vulnerability type', () => {
    render(<IssueRow finding={makeFinding({ stage: 'todo' })} />)
    const row = screen.getByRole('row')
    const icons = Array.from(row.querySelectorAll('.material-symbols-outlined')).map(
      (el) => el.textContent,
    )
    expect(icons).toContain('bug_report')
  })

  it('renders Review plan action for plan_ready stage', () => {
    render(<IssueRow finding={makeFinding({ stage: 'plan_ready' })} />)
    expect(screen.getByRole('button', { name: /review plan/i })).toBeInTheDocument()
  })

  it('renders Review PR action for pr_ready stage', () => {
    render(<IssueRow finding={makeFinding({ stage: 'pr_ready' })} />)
    expect(screen.getByRole('button', { name: /review pr/i })).toBeInTheDocument()
  })

  it('renders Review PR action for pr_awaiting_val stage', () => {
    render(<IssueRow finding={makeFinding({ stage: 'pr_awaiting_val' })} />)
    expect(screen.getByRole('button', { name: /review pr/i })).toBeInTheDocument()
  })

  it('renders Run triage action for an untriaged (new) todo finding', () => {
    render(<IssueRow finding={makeFinding({ stage: 'todo', status: 'new' })} />)
    expect(
      screen.getByRole('button', { name: /run triage/i }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^start/i })).toBeNull()
  })

  it('renders Start action for a confirmed-real (triaged) todo finding', () => {
    render(<IssueRow finding={makeFinding({ stage: 'todo', status: 'triaged' })} />)
    expect(screen.getByRole('button', { name: /^start/i })).toBeInTheDocument()
  })

  it('renders Review verdict action for the triage_verdict stage', () => {
    render(<IssueRow finding={makeFinding({ stage: 'triage_verdict' })} />)
    expect(
      screen.getByRole('button', { name: /review verdict/i }),
    ).toBeInTheDocument()
  })

  it('renders chevron-only action (no button) for in-flight stages', () => {
    render(<IssueRow finding={makeFinding({ stage: 'generating' })} />)
    // Should not have a "Start" / "Review plan" / "Review PR" button.
    expect(screen.queryByRole('button', { name: /start|review/i })).toBeNull()
    // The chevron-right Material symbol must be present for the view-only
    // action slot.
    const row = screen.getByRole('row')
    const symbols = Array.from(row.querySelectorAll('.material-symbols-outlined')).map(
      (el) => el.textContent,
    )
    expect(symbols).toContain('chevron_right')
  })

  it('renders chevron-only action for done stages and sets dim opacity', () => {
    render(<IssueRow finding={makeFinding({ stage: 'fixed' })} dim />)
    expect(screen.queryByRole('button', { name: /start|review/i })).toBeNull()
    const row = screen.getByRole('row')
    expect(row.className).toMatch(/opacity/)
  })

  it('fires onActivate when the row is clicked', () => {
    const onActivate = vi.fn()
    render(
      <IssueRow finding={makeFinding({ stage: 'todo' })} onActivate={onActivate} />,
    )
    fireEvent.click(screen.getByRole('row'))
    expect(onActivate).toHaveBeenCalledTimes(1)
  })

  it('fires onActivate when the action button is clicked', () => {
    const onActivate = vi.fn()
    render(
      <IssueRow
        finding={makeFinding({ stage: 'plan_ready' })}
        onActivate={onActivate}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /review plan/i }))
    expect(onActivate).toHaveBeenCalledTimes(1)
  })

  it('applies the focus-visible ring class when focused prop is set', () => {
    render(<IssueRow finding={makeFinding({ stage: 'todo' })} focused />)
    const row = screen.getByRole('row')
    // The focus ring is the Cyberdeck `cd-row--focus` class (CSS), not an
    // inline box-shadow.
    expect(row.className).toContain('cd-row--focus')
  })

  it('renders the severity hairline + badge + stage chip in the row', () => {
    render(<IssueRow finding={makeFinding({ stage: 'plan_ready' })} />)
    const row = screen.getByRole('row')
    // Stage chip uses our atom; severity badge uses our atom too.
    expect(row.querySelector('[data-testid="stage-chip-plan_ready"]')).not.toBeNull()
    expect(row.querySelector('[aria-label*="Severity"]')).not.toBeNull()
  })
})
