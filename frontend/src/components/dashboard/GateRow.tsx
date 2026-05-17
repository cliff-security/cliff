/**
 * GateRow — one gate inside the Level-up panel (IMPL-0009 / F6).
 *
 * Composes LevelUpProgressPuck (F2) on the left, label + status chip + detail
 * + metric line in the body, and an action button on the right that either
 * navigates (most statuses) or fans out posture-fix calls (auto_fixable).
 */
import { useState } from 'react'
import LevelUpProgressPuck from './LevelUpProgressPuck'
import GateStatusChip, { type GateStatus } from './GateStatusChip'
import { formatAutoFixError } from './formatAutoFixError'

export type GateRowData = {
  id: string
  label: string
  detail: string
  current: number
  target: number
  unit: string
  status: GateStatus
  action_label: string
  action_href: string
  auto_fixable_check_names?: string[]
  /** B27 — first matching finding for non-posture gates, so the Start
   *  card can deep-link the Issues side panel via ``?open=<id>``. The
   *  ``action_href`` already includes this query param when populated;
   *  the field is exposed so consumers can also key on it directly. */
  first_finding_id?: string | null
}

export default function GateRow({
  gate,
  onNavigate,
  onAutoFix,
  onAutoFixError,
  error,
  pending,
}: {
  gate: GateRowData
  /** Called for navigate-style actions. */
  onNavigate?: (href: string) => void
  /** Called for the auto-fixable action. */
  onAutoFix?: (checkNames: string[]) => Promise<void> | void
  /**
   * Q01R B24 — invoked with a human-readable message when ``onAutoFix``
   * rejects. The parent decides where to render the message (typically
   * by passing the same string back as the ``error`` prop so it shows
   * inline on the same card). Without this, a 4xx from
   * ``POST /api/posture/fix/{check_name}`` was silently swallowed and
   * the user saw nothing happen.
   */
  onAutoFixError?: (message: string) => void
  /** Q01R B24 — inline error text rendered on the card. */
  error?: string | null
  /** External "in flight" flag used by the parent to disable the button. */
  pending?: boolean
}) {
  const [localPending, setLocalPending] = useState(false)
  const busy = pending || localPending
  const isPosture = gate.target > 0
  const metricText = isPosture
    ? `${gate.current} / ${gate.target} passing · ${gate.unit}`
    : `${gate.current} → ${gate.target} · ${gate.unit}`

  const onClickAction = async () => {
    if (busy) return
    if (gate.status === 'auto_fixable') {
      const names = gate.auto_fixable_check_names ?? []
      if (names.length === 0) return
      try {
        setLocalPending(true)
        await onAutoFix?.(names)
      } catch (err) {
        // Q01R B24 — never swallow a 4xx; surface a parsed message to the
        // parent so it can render it (inline + wherever else makes sense)
        // instead of leaving the user staring at a dead button.
        onAutoFixError?.(formatAutoFixError(err))
      } finally {
        setLocalPending(false)
      }
      return
    }
    onNavigate?.(gate.action_href)
  }

  return (
    <li>
      <div
        data-testid={`gate-row-${gate.id}`}
        data-status={gate.status}
        className="rounded-2xl p-4 flex items-start gap-4"
        style={{ background: 'var(--surface-container-low, #f1f4f6)' }}
      >
        <LevelUpProgressPuck
          current={gate.current}
          target={gate.target}
          met={
            gate.target === 0
              ? gate.current <= 0
              : gate.current >= gate.target
          }
        />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="font-semibold"
              style={{
                fontSize: 13.5,
                color: 'var(--on-surface, #2b3437)',
              }}
            >
              {gate.label}
            </span>
            <GateStatusChip status={gate.status} />
          </div>
          <div
            className="mt-1"
            style={{
              fontSize: 12.5,
              color: 'var(--on-surface-variant, #586064)',
              textWrap: 'pretty' as never,
            }}
          >
            {gate.detail}
          </div>
          <div
            className="mt-2 font-mono"
            style={{ fontSize: 11, color: 'var(--on-surface-variant, #586064)' }}
          >
            <span
              className="font-semibold"
              style={{ color: 'var(--on-surface, #2b3437)' }}
            >
              {isPosture
                ? `${gate.current} / ${gate.target} passing`
                : `${gate.current} → ${gate.target}`}
            </span>
            <span aria-hidden> · </span>
            <span>{gate.unit}</span>
            <span className="sr-only">{metricText}</span>
          </div>
          {error ? (
            <div
              role="alert"
              data-testid={`gate-row-${gate.id}-error`}
              className="mt-2"
              style={{
                fontSize: 12,
                color: 'var(--error, #b3261e)',
                textWrap: 'pretty' as never,
              }}
            >
              {error}
            </div>
          ) : null}
        </div>

        <button
          type="button"
          data-testid={`gate-row-${gate.id}-action`}
          disabled={busy}
          onClick={onClickAction}
          className="self-center flex-shrink-0 inline-flex items-center gap-1.5 rounded-md bg-primary px-3.5 py-2 text-on-primary hover:bg-primary/90 disabled:opacity-50 transition-colors"
          style={{ fontSize: 13, fontWeight: 600 }}
        >
          {busy ? 'Working…' : gate.action_label}
          {!busy && (
            <span
              className="material-symbols-outlined"
              style={{ fontSize: 16 }}
              aria-hidden
            >
              arrow_forward
            </span>
          )}
        </button>
      </div>
    </li>
  )
}

