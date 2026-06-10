/**
 * IssueStageChip — Cliff Cyberdeck stage indicator.
 *
 * In-flight stages render with a pulsing cyan dot + cyan label
 * ("Planning…", "Generating fix…", etc). Ready stages flip to sage with
 * a hairline-bright chip. Verdicts (fixed / false_positive / accepted /
 * wont_fix / deferred) render as muted-ink chips with a verdict icon.
 *
 * Mono label per the system rule; aria-live="polite" so screen readers
 * announce stage transitions.
 */
import type { ReactElement, CSSProperties } from 'react'
import './issues.css'

/** Inline-style escape hatch for CSS custom properties (`--c` etc.).
 *  TypeScript doesn't allow arbitrary keys on `CSSProperties`; this
 *  type opens it up just for our cd-loader colour override without
 *  needing a double cast at the call site. */
type CSSVar = CSSProperties & Record<`--${string}`, string | undefined>

export type IssueStage =
  | 'todo'
  // ADR-0051 / PRD-0008 — triage stages.
  | 'triaging'
  | 'planning'
  | 'generating'
  | 'pushing'
  | 'opening_pr'
  | 'validating'
  | 'triage_verdict'
  | 'plan_ready'
  | 'pr_ready'
  | 'pr_awaiting_val'
  | 'awaiting_permission'
  | 'failed'
  | 'executor_failed'
  | 'fixed'
  | 'false_positive'
  | 'unexploitable'
  | 'wont_fix'
  | 'accepted'
  | 'deferred'

type Tone =
  | 'in_flight'
  | 'ready'
  | 'awaiting'
  | 'positive'
  | 'neutral'
  | 'error'
  | 'warning'

interface StageVisual {
  label: string
  tone: Tone
  icon?: 'check' | 'block' | 'schedule' | 'shield' | 'report'
}

const STAGE_VISUALS: Record<IssueStage, StageVisual> = {
  // ADR-0051 / PRD-0008 — triage in-flight + verdict-awaiting stages. They
  // reuse the existing in_flight (cyan pulse, like planning) and awaiting
  // (cyan pulse, like pr_awaiting_val) treatments — no new visual language.
  triaging:        { label: 'Triaging',            tone: 'in_flight' },
  triage_verdict:  { label: 'Review verdict',      tone: 'awaiting' },
  planning:        { label: 'Planning',            tone: 'in_flight' },
  generating:      { label: 'Generating fix',      tone: 'in_flight' },
  pushing:         { label: 'Pushing branch',      tone: 'in_flight' },
  opening_pr:      { label: 'Opening PR',          tone: 'in_flight' },
  validating:      { label: 'Validating fix',      tone: 'in_flight' },
  plan_ready:      { label: 'Plan ready',          tone: 'ready' },
  pr_ready:        { label: 'PR ready',            tone: 'ready' },
  pr_awaiting_val: { label: 'Awaiting validation', tone: 'awaiting' },
  awaiting_permission: { label: 'Awaiting approval', tone: 'awaiting' },
  failed:          { label: 'Error',               tone: 'error',    icon: 'block' },
  // Q01R-W2 / B35b — distinct from ``failed``: the underlying run
  // returned status='completed' but its structured_output carries
  // ``error_details`` (the executor produced a local branch, then the
  // push died). Surface this as warning-tinted "Needs attention" so the
  // user lands on the retry/fix path instead of waiting on a stuck
  // "Pushing branch…" spinner. Generic enough to cover any future agent
  // that reports error_details — not push-specific.
  executor_failed: { label: 'Needs attention',     tone: 'warning',  icon: 'block' },
  fixed:           { label: 'Fixed',               tone: 'positive', icon: 'check' },
  // ADR-0051 §7 / UX-0008 §States — false_positive and unexploitable are both
  // green closes but MUST read apart: distinct icons (report vs shield) so the
  // verdict is color + icon + label, never colour alone.
  false_positive:  { label: 'False positive',      tone: 'positive', icon: 'report' },
  unexploitable:   { label: 'Not exploitable',     tone: 'positive', icon: 'shield' },
  accepted:        { label: 'Accepted',            tone: 'neutral',  icon: 'check' },
  wont_fix:        { label: "Won't fix",           tone: 'neutral',  icon: 'block' },
  deferred:        { label: 'Deferred',            tone: 'neutral',  icon: 'schedule' },
  todo:            { label: 'Todo',                tone: 'neutral' },
}

const TONE_CHIP: Record<Tone, string> = {
  in_flight: 'cd-chip cd-chip--cyan',
  ready:     'cd-chip cd-chip--green',
  awaiting:  'cd-chip cd-chip--cyan',
  positive:  'cd-chip cd-chip--green',
  neutral:   'cd-chip cd-chip--ink',
  error:     'cd-chip cd-chip--red',
  // Warning shares the amber/yellow family used elsewhere for
  // "attention-needed but not destructive" affordances. Falls back to
  // an inline color when the Cyberdeck token isn't defined so legacy
  // themes don't render unstyled.
  warning:   'cd-chip cd-chip--amber',
}

const TONE_DOT_COLOR: Record<Tone, string> = {
  in_flight: 'var(--cd-cyan)',
  ready:     'var(--cd-green)',
  awaiting:  'var(--cd-cyan)',
  positive:  'var(--cd-green)',
  neutral:   'var(--cd-fg-4)',
  error:     'var(--cd-red, #ef6464)',
  warning:   'var(--cd-amber, #f5b54a)',
}

const HAS_PULSE_DOT: Record<Tone, boolean> = {
  in_flight: true,
  ready: false,
  awaiting: true,
  positive: false,
  neutral: false,
  error: false,
  warning: false,
}

interface IssueStageChipProps {
  kind: IssueStage
  size?: 'sm' | 'md'
}

export function IssueStageChip({
  kind,
  size = 'md',
}: IssueStageChipProps): ReactElement {
  const v = STAGE_VISUALS[kind]
  const chipStyle: CSSProperties =
    size === 'sm'
      ? { padding: '2px 7px', fontSize: 9.5 }
      : { padding: '3px 9px', fontSize: 10 }

  return (
    <span
      data-testid={`stage-chip-${kind}`}
      aria-live="polite"
      className={`${TONE_CHIP[v.tone]} whitespace-nowrap`}
      style={chipStyle}
    >
      {HAS_PULSE_DOT[v.tone] && (
        <span
          aria-hidden="true"
          className="cd-loader cd-loader--sm"
          style={{ '--c': TONE_DOT_COLOR[v.tone] } as CSSVar}
        />
      )}
      {v.icon && (
        <span
          className="material-symbols-outlined"
          style={{ fontSize: 12, fontVariationSettings: "'FILL' 0, 'wght' 400" }}
          aria-hidden="true"
        >
          {v.icon}
        </span>
      )}
      {v.label}
    </span>
  )
}
