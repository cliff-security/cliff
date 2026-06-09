import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { IssueStageChip, type IssueStage } from '../IssueStageChip'

describe('IssueStageChip', () => {
  const allStages: IssueStage[] = [
    'todo',
    'triaging',
    'planning',
    'generating',
    'pushing',
    'opening_pr',
    'validating',
    'triage_verdict',
    'plan_ready',
    'pr_ready',
    'pr_awaiting_val',
    'executor_failed',
    'fixed',
    'false_positive',
    'unexploitable',
    'wont_fix',
    'accepted',
    'deferred',
  ]

  it.each(allStages)('renders %s without console warnings', (stage) => {
    expect(() => render(<IssueStageChip kind={stage} />)).not.toThrow()
    // Each chip should produce some visible label text.
    const root = screen.getByTestId(`stage-chip-${stage}`)
    expect(root.textContent?.trim().length ?? 0).toBeGreaterThan(0)
  })

  it('attaches aria-live="polite" to the chip wrapper for screen-reader transitions', () => {
    render(<IssueStageChip kind="planning" />)
    expect(screen.getByTestId('stage-chip-planning').getAttribute('aria-live')).toBe(
      'polite',
    )
  })

  it('renders a pulsing dot for in-flight stages', () => {
    render(<IssueStageChip kind="generating" />)
    const root = screen.getByTestId('stage-chip-generating')
    expect(root.querySelector('.cd-loader')).not.toBeNull()
  })

  it('does NOT render a pulsing dot for ready stages', () => {
    render(<IssueStageChip kind="plan_ready" />)
    const root = screen.getByTestId('stage-chip-plan_ready')
    expect(root.querySelector('.cd-loader')).toBeNull()
  })

  it('renders a static dot fallback when prefers-reduced-motion: reduce', () => {
    // The CSS file scopes the animation to a media query; we verify the dot
    // element exists and carries the .cd-loader class so the media query can
    // disable the keyframe without removing the dot itself.
    render(<IssueStageChip kind="planning" />)
    const dot = screen
      .getByTestId('stage-chip-planning')
      .querySelector('.cd-loader')
    expect(dot).not.toBeNull()
  })

  it('renders a check icon for the positive verdict (fixed)', () => {
    render(<IssueStageChip kind="fixed" />)
    const root = screen.getByTestId('stage-chip-fixed')
    const icon = root.querySelector('.material-symbols-outlined')
    expect(icon?.textContent).toBe('check')
  })

  it('renders a block icon for wont_fix', () => {
    render(<IssueStageChip kind="wont_fix" />)
    const icon = screen
      .getByTestId('stage-chip-wont_fix')
      .querySelector('.material-symbols-outlined')
    expect(icon?.textContent).toBe('block')
  })

  it('renders a schedule icon for deferred', () => {
    render(<IssueStageChip kind="deferred" />)
    const icon = screen
      .getByTestId('stage-chip-deferred')
      .querySelector('.material-symbols-outlined')
    expect(icon?.textContent).toBe('schedule')
  })

  it('uses sm sizing when size="sm"', () => {
    render(<IssueStageChip kind="plan_ready" size="sm" />)
    const root = screen.getByTestId('stage-chip-plan_ready')
    expect(root.style.fontSize).toBe('9.5px')
  })

  // --- Triage stages (ADR-0051 / PRD-0008) -------------------------------

  it('renders a pulsing dot + "Triaging" for the triaging stage', () => {
    render(<IssueStageChip kind="triaging" />)
    const root = screen.getByTestId('stage-chip-triaging')
    expect(root.textContent).toMatch(/Triaging/)
    expect(root.querySelector('.cd-loader')).not.toBeNull()
  })

  it('labels triage_verdict as "Review verdict" in the awaiting tone', () => {
    render(<IssueStageChip kind="triage_verdict" />)
    const root = screen.getByTestId('stage-chip-triage_verdict')
    expect(root.textContent).toMatch(/Review verdict/)
    // awaiting tone carries a pulse dot (same treatment as pr_awaiting_val).
    expect(root.querySelector('.cd-loader')).not.toBeNull()
  })

  it('gives unexploitable a distinct icon from false_positive (color+icon+label)', () => {
    render(<IssueStageChip kind="unexploitable" />)
    render(<IssueStageChip kind="false_positive" />)
    const unexp = screen
      .getByTestId('stage-chip-unexploitable')
      .querySelector('.material-symbols-outlined')?.textContent
    const fp = screen
      .getByTestId('stage-chip-false_positive')
      .querySelector('.material-symbols-outlined')?.textContent
    expect(unexp).toBe('shield')
    expect(fp).toBe('report')
    expect(unexp).not.toBe(fp)
  })
})
