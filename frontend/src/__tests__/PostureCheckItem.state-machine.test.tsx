import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import PostureCheckItem from '@/components/dashboard/PostureCheckItem'

/**
 * PRD-0004 Story 3 / IMPL-0004 T10 — four-state checklist matrix.
 *
 * Each state must surface three reinforcing signals (icon shape, text label,
 * row tint) and the correct action-slot variant.
 */

describe('<PostureCheckItem /> state machine', () => {
  it('to_do: empty circle + "To do" label + primary button action slot', async () => {
    const onStart = vi.fn()
    render(
      <ul>
        <PostureCheckItem
          checkName="security_md"
          state="to_do"
          label="SECURITY.md is missing"
          description="Tells researchers where to report vulnerabilities."
          onStart={onStart}
        />
      </ul>,
    )
    const item = screen.getByTestId('posture-check-item')
    expect(item.dataset.state).toBe('to_do')
    expect(item.className).toContain('bg-surface-container-lowest')
    expect(
      item.querySelector('[aria-label="Status: To do"]'),
    ).not.toBeNull()
    expect(screen.getByText('To do')).toBeInTheDocument()
    // Icon glyph content.
    const icon = item.querySelector('.material-symbols-outlined')
    expect(icon).toHaveTextContent('radio_button_unchecked')

    const button = screen.getByRole('button', {
      name: /let cliff open a pr/i,
    })
    await userEvent.click(button)
    expect(onStart).toHaveBeenCalledWith('security_md')
  })

  it('running: spinner + "Running" label + non-interactive chip action slot', () => {
    render(
      <ul>
        <PostureCheckItem
          checkName="security_md"
          state="running"
          label="SECURITY.md is missing"
        />
      </ul>,
    )
    const item = screen.getByTestId('posture-check-item')
    expect(item.dataset.state).toBe('running')
    expect(item.className).toContain('bg-primary-container/25')
    expect(screen.getByText('Running')).toBeInTheDocument()
    const chip = screen.getByTestId('posture-check-running-chip')
    expect(chip).toHaveTextContent(/agent is drafting a pr/i)
    // Chip is non-interactive — not a button, cursor default.
    expect(chip.tagName).toBe('SPAN')
    expect(chip.className).toContain('cursor-default')
  })

  it('succeeded: filled check + "Done" label + external PR link action slot', () => {
    render(
      <ul>
        <PostureCheckItem
          checkName="security_md"
          state="succeeded"
          label="SECURITY.md is missing"
          prUrl="https://github.com/acme/widget/pull/42"
        />
      </ul>,
    )
    const item = screen.getByTestId('posture-check-item')
    expect(item.dataset.state).toBe('succeeded')
    expect(item.className).toContain('bg-tertiary-container/20')
    expect(screen.getByText('Done')).toBeInTheDocument()
    const link = screen.getByTestId('posture-check-done-link')
    expect(link).toHaveAttribute('href', 'https://github.com/acme/widget/pull/42')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(link).toHaveTextContent(/view draft pr/i)
  })

  it('failed: filled cancel + "Failed" label + no action (muted retry hint)', () => {
    render(
      <ul>
        <PostureCheckItem
          checkName="security_md"
          state="failed"
          label="SECURITY.md is missing"
          error="OpenCode crashed mid-commit"
        />
      </ul>,
    )
    const item = screen.getByTestId('posture-check-item')
    expect(item.dataset.state).toBe('failed')
    expect(item.className).toContain('bg-error-container/15')
    expect(screen.getByText('Failed')).toBeInTheDocument()
    // No primary button, no chip, no link — only the retry hint.
    expect(
      screen.queryByRole('button', { name: /let cliff open a pr/i }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('posture-check-done-link'),
    ).not.toBeInTheDocument()
    expect(
      screen.getByText(/re-run the assessment to retry this check/i),
    ).toBeInTheDocument()
    // Error text remains available for screen readers.
    expect(
      screen.getByText('OpenCode crashed mid-commit'),
    ).toHaveClass('sr-only')
  })
})
