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
  | 'planning'
  | 'generating'
  | 'pushing'
  | 'opening_pr'
  | 'validating'
  | 'plan_ready'
  | 'pr_ready'
  | 'pr_awaiting_val'
  | 'awaiting_permission'
  | 'failed'
  | 'fixed'
  | 'false_positive'
  | 'wont_fix'
  | 'accepted'
  | 'deferred'

type Tone = 'in_flight' | 'ready' | 'awaiting' | 'positive' | 'neutral' | 'error'

interface StageVisual {
  label: string
  tone: Tone
  icon?: 'check' | 'block' | 'schedule'
}

const STAGE_VISUALS: Record<IssueStage, StageVisual> = {
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
  fixed:           { label: 'Fixed',               tone: 'positive', icon: 'check' },
  false_positive:  { label: 'False positive',      tone: 'positive', icon: 'check' },
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
}

const TONE_DOT_COLOR: Record<Tone, string> = {
  in_flight: 'var(--cd-cyan)',
  ready:     'var(--cd-green)',
  awaiting:  'var(--cd-cyan)',
  positive:  'var(--cd-green)',
  neutral:   'var(--cd-fg-4)',
  error:     'var(--cd-red, #ef6464)',
}

const HAS_PULSE_DOT: Record<Tone, boolean> = {
  in_flight: true,
  ready: false,
  awaiting: true,
  positive: false,
  neutral: false,
  error: false,
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
