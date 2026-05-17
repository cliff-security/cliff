/**
 * PostureCheckItem — checklist-style posture row (PRD-0004 Story 3 /
 * IMPL-0004 T10).
 *
 * Four states, four icons, four row tints, four action-slot variants:
 *
 *   ┌────────┬───────────────────────────────────────────────┐
 *   │ STATUS │ Title                                          │
 *   │  icon  │ Explanation                                    │
 *   │  label │ [action slot: button / chip / link / hint]     │
 *   └────────┴───────────────────────────────────────────────┘
 *
 * Three reinforcing signals (icon shape, text label, row tint) so
 * colorblind users and screen readers lose nothing.
 */

import type { ReactNode } from 'react'

export type PostureCheckState = 'to_do' | 'running' | 'succeeded' | 'failed'

export type PostureCheckName =
  | 'security_md'
  | 'dependabot_config'
  | (string & {})

export interface PostureCheckItemProps {
  checkName: PostureCheckName
  /** 4-state machine; drives icon, label, tint and action slot. */
  state: PostureCheckState
  /** Primary title — e.g. "SECURITY.md is missing". */
  label: string
  /** Short explanation rendered under the title. Keep to 1–2 lines. */
  description?: string
  /** Pending first click — disables the "Let Cliff open a PR" button. */
  pending?: boolean
  /** Fired by the state="to_do" primary button. */
  onStart?: (checkName: PostureCheckName) => void
  /** PR URL when state="succeeded". Rendered as the link-chip action. */
  prUrl?: string | null
  /** Error text when state="failed". Used for the a11y description only. */
  error?: string | null
  /**
   * Optional node rendered inside the "details" rail — used for the
   * security_md contact-email input. Renders only when state="to_do".
   */
  detailsSlot?: ReactNode
}

const STATUS_META: Record<
  PostureCheckState,
  {
    icon: string
    iconFilled: boolean
    iconColor: string
    label: string
    rowTint: string
    labelColor: string
  }
> = {
  to_do: {
    icon: 'radio_button_unchecked',
    iconFilled: false,
    iconColor: 'text-outline-variant',
    label: 'To do',
    rowTint: 'bg-surface-container-lowest',
    labelColor: 'text-on-surface-variant',
  },
  running: {
    // Spinner handled via a CSS spinner, not a material glyph.
    icon: 'progress_activity',
    iconFilled: false,
    iconColor: 'text-primary',
    label: 'Running',
    rowTint: 'bg-primary-container/25',
    labelColor: 'text-primary',
  },
  succeeded: {
    icon: 'check_circle',
    iconFilled: true,
    iconColor: 'text-tertiary',
    label: 'Done',
    rowTint: 'bg-tertiary-container/20',
    labelColor: 'text-tertiary',
  },
  failed: {
    icon: 'cancel',
    iconFilled: true,
    iconColor: 'text-error',
    label: 'Failed',
    rowTint: 'bg-error-container/15',
    labelColor: 'text-error',
  },
}

export default function PostureCheckItem({
  checkName,
  state,
  label,
  description,
  pending = false,
  onStart,
  prUrl,
  error,
  detailsSlot,
}: PostureCheckItemProps) {
  const meta = STATUS_META[state]

  return (
    <li
      data-testid="posture-check-item"
      data-state={state}
      data-check-name={checkName}
      className={`flex flex-col gap-3 rounded-2xl p-4 transition-colors sm:flex-row sm:items-start ${meta.rowTint}`}
    >
      <div
        className="flex w-14 flex-shrink-0 flex-col items-center gap-1 pt-0.5"
        aria-label={`Status: ${meta.label}`}
      >
        {state === 'running' ? (
          <span
            role="status"
            aria-live="polite"
            className="inline-block h-7 w-7 animate-spin rounded-full border-2 border-primary/30 border-t-primary"
          />
        ) : (
          <span
            className={`material-symbols-outlined ${meta.iconColor}`}
            style={{
              fontSize: '30px',
              ...(meta.iconFilled
                ? { fontVariationSettings: "'FILL' 1" }
                : undefined),
            }}
            aria-hidden
          >
            {meta.icon}
          </span>
        )}
        <span
          className={`text-[10px] font-semibold uppercase tracking-wider ${meta.labelColor}`}
        >
          {meta.label}
        </span>
      </div>

      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-on-surface">{label}</p>
        {description && (
          <p className="mt-1 text-sm text-on-surface-variant">{description}</p>
        )}
        {state === 'to_do' && detailsSlot && (
          <div className="mt-3">{detailsSlot}</div>
        )}
        {state === 'failed' && (
          <p className="mt-2 inline-flex items-center gap-1 text-xs text-on-surface-variant">
            <span
              className="material-symbols-outlined text-sm"
              aria-hidden
            >
              refresh
            </span>
            Re-run the assessment to retry this check.
          </p>
        )}
        {state === 'failed' && error && (
          <p className="sr-only" aria-live="polite">
            {error}
          </p>
        )}
      </div>

      <div className="flex-shrink-0 self-start">
        {state === 'to_do' && onStart && (
          <button
            type="button"
            data-testid="posture-check-primary-action"
            disabled={pending}
            onClick={() => onStart(checkName)}
            className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-primary px-4 py-2 text-sm font-semibold text-on-primary shadow-sm transition hover:bg-primary/90 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
          >
            <span className="material-symbols-outlined text-sm" aria-hidden>
              play_arrow
            </span>
            {pending ? 'Starting…' : 'Let Cliff open a PR'}
          </button>
        )}
        {state === 'running' && (
          <span
            role="status"
            aria-live="polite"
            data-testid="posture-check-running-chip"
            tabIndex={-1}
            className="inline-flex cursor-default items-center gap-1.5 whitespace-nowrap rounded-full bg-surface-container-high px-4 py-2 text-sm font-medium text-on-surface-variant"
          >
            <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
            Agent is drafting a PR…
          </span>
        )}
        {state === 'succeeded' && prUrl && (
          <a
            data-testid="posture-check-done-link"
            href={prUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-tertiary-container/40 px-4 py-2 text-sm font-semibold text-on-tertiary-container hover:bg-tertiary-container/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-tertiary/60"
          >
            <span
              className="material-symbols-outlined text-sm"
              aria-hidden
            >
              open_in_new
            </span>
            View draft PR
          </a>
        )}
      </div>
    </li>
  )
}
