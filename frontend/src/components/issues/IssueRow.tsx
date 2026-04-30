/**
 * IssueRow — Phase 1 (PRD-0006) component.
 *
 * Six-slot CSS grid row matching IPIssueRow in
 * `frontend/mockups/claude-design/PRD-0006/issues-page/table.jsx`.
 *
 *   [hairline] [type icon] [title block] [severity] [stage] [action]
 *      4px        22px       1fr           auto      auto      auto
 *
 * Action variant infers from `derived.stage`:
 *   - plan_ready                         → "Review plan" primary button
 *   - pr_ready / pr_awaiting_val         → "Review PR" primary button
 *   - todo                               → "Start" primary button
 *   - any in-flight or done stage        → chevron-right view-only icon
 *
 * Click anywhere on the row (or on the action) calls `onActivate`. In Phase 1
 * the parent IssuesPage wires this to the existing Solve flow:
 * `createWorkspace(finding) → navigate(/workspace/:id)`. Phase 2 swaps in the
 * side-panel.
 */
import { memo, useState, type KeyboardEvent, type ReactElement } from 'react'
import type { Finding, IssueStage } from '../../api/client'
import {
  IssuePostureBadge,
  IssueSeverityBadge,
  type IssueSeverityKind,
} from './IssueSeverityBadge'
import { IssueStageChip } from './IssueStageChip'

const SEVERITY_HAIRLINE: Record<IssueSeverityKind, string> = {
  critical: 'bg-error',
  high: 'bg-warning-dim',
  medium: 'bg-secondary',
  low: 'bg-tertiary',
}

/** Hairline color for non-CVE finding types. Posture rows use a neutral
 *  outline so the eye doesn't read them as "high severity bug". */
const POSTURE_HAIRLINE = 'bg-outline-variant'

const TYPE_ICON: Record<string, string> = {
  dependency: 'bug_report',
  code: 'bug_report',
  secret: 'key',
  posture: 'verified_user',
}

type ActionKind = 'review_plan' | 'review_pr' | 'start' | 'view'

function actionForStage(stage: IssueStage): ActionKind {
  if (stage === 'plan_ready') return 'review_plan'
  if (stage === 'pr_ready' || stage === 'pr_awaiting_val') return 'review_pr'
  if (stage === 'todo') return 'start'
  return 'view'
}

function severityKind(raw: string | null): IssueSeverityKind {
  const key = (raw ?? 'medium').toLowerCase()
  if (key === 'critical' || key === 'high' || key === 'low') return key
  return 'medium'
}

interface IssueRowProps {
  finding: Finding
  /** Render the row as visually muted (Done section). */
  dim?: boolean
  /** Render with the focus-visible ring (e.g. for keyboard navigation). */
  focused?: boolean
  /** Click / Enter handler — fires for both row click and action button. */
  onActivate?: (finding: Finding) => void
}

function IssueRowImpl({
  finding,
  dim = false,
  focused = false,
  onActivate,
}: IssueRowProps): ReactElement {
  const [hover, setHover] = useState(false)

  const stage: IssueStage = finding.derived?.stage ?? 'todo'
  const action = actionForStage(stage)
  const isPosture = finding.type === 'posture'
  const sev = severityKind(finding.raw_severity)
  const typeIcon = TYPE_ICON[finding.type ?? 'dependency'] ?? 'bug_report'

  const handleActivate = (): void => {
    onActivate?.(finding)
  }

  const handleKey = (e: KeyboardEvent<HTMLDivElement>): void => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      handleActivate()
    }
  }

  const cvss = (finding.raw_payload?.cvss as number | undefined) ?? null
  const found = (finding.raw_payload?.found as string | undefined) ?? null
  const file = (finding.raw_payload?.file as string | undefined) ?? null
  const line = (finding.raw_payload?.line as number | string | undefined) ?? null
  const cwe = (finding.raw_payload?.cwe as string | undefined) ?? null

  return (
    <div
      role="row"
      tabIndex={0}
      onClick={handleActivate}
      onKeyDown={handleKey}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className={`group relative grid items-center cursor-pointer rounded-xl transition-colors ${
        hover ? 'bg-surface-container-lowest' : 'bg-transparent'
      } ${dim ? 'opacity-70' : ''}`}
      style={{
        gridTemplateColumns: '4px 22px minmax(0,1fr) auto auto auto',
        columnGap: 14,
        padding: '11px 14px 11px 12px',
        boxShadow: focused ? 'inset 0 0 0 2px var(--primary, #4d44e3)' : undefined,
      }}
    >
      {/* 1. Severity hairline (neutral for posture — they have no CVSS sev) */}
      <span
        aria-hidden="true"
        className={`rounded-full ${isPosture ? POSTURE_HAIRLINE : SEVERITY_HAIRLINE[sev]}`}
        style={{ width: 3, height: 28, alignSelf: 'center' }}
      />

      {/* 2. Type icon */}
      <span
        aria-hidden="true"
        className="flex items-center justify-center text-on-surface-variant"
      >
        <span className="material-symbols-outlined" style={{ fontSize: 17 }}>
          {typeIcon}
        </span>
      </span>

      {/* 3. Title block */}
      <div className="min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="text-[13.5px] font-semibold text-on-surface truncate"
            style={{ textWrap: 'pretty' as const }}
          >
            {finding.title}
          </span>
        </div>
        <div className="flex items-center gap-2 mt-0.5 text-[11.5px] text-on-surface-variant">
          {/* CVSS / file:line / CWE only apply to CVE-shaped rows. Posture
              rows show their category instead — surfaced via the badge. */}
          {!isPosture && file != null && (
            <span className="font-mono">
              {file}
              {line != null ? `:${line}` : ''}
            </span>
          )}
          {!isPosture && cwe && (
            <>
              <span className="text-outline">·</span>
              <span className="font-mono">{cwe}</span>
            </>
          )}
          {!isPosture && cvss != null && (
            <>
              <span className="text-outline">·</span>
              <span>CVSS {cvss}</span>
            </>
          )}
          {!isPosture && (
            <>
              <span className="text-outline">·</span>
              <span className="font-mono">{finding.source_id}</span>
            </>
          )}
          {found && (
            <>
              {!isPosture && <span className="text-outline">·</span>}
              <span>Found {found}</span>
            </>
          )}
        </div>
      </div>

      {/* 4. Severity / category badge — posture findings have no severity. */}
      {isPosture ? (
        <IssuePostureBadge category={finding.category ?? undefined} size="sm" />
      ) : (
        <IssueSeverityBadge kind={sev} size="sm" />
      )}

      {/* 5. Stage chip */}
      <IssueStageChip kind={stage} size="sm" />

      {/* 6. Action */}
      <div className="flex items-center justify-end" style={{ minWidth: 130 }}>
        {action === 'review_plan' && (
          <ActionButton
            label="Review plan"
            icon="rate_review"
            onClick={(e) => {
              e.stopPropagation()
              handleActivate()
            }}
          />
        )}
        {action === 'review_pr' && (
          <ActionButton
            label="Review PR"
            icon="merge_type"
            onClick={(e) => {
              e.stopPropagation()
              handleActivate()
            }}
          />
        )}
        {action === 'start' && (
          <ActionButton
            label="Start"
            icon="play_arrow"
            onClick={(e) => {
              e.stopPropagation()
              handleActivate()
            }}
          />
        )}
        {action === 'view' && (
          <span
            aria-hidden="true"
            className={`inline-flex items-center justify-center rounded-lg p-1 transition-colors ${
              hover ? 'text-on-surface' : 'text-outline'
            }`}
          >
            <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
              chevron_right
            </span>
          </span>
        )}
      </div>
    </div>
  )
}

// Memoize so unchanged rows don't re-render when sibling state flips (hover
// on another row, severity-filter change, doneExpanded toggle, etc.). The
// finding object is stable per query result so reference-equality is enough.
export const IssueRow = memo(IssueRowImpl)

interface ActionButtonProps {
  label: string
  icon: string
  onClick: (e: React.MouseEvent) => void
}

function ActionButton({ label, icon, onClick }: ActionButtonProps): ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center justify-center font-semibold rounded-lg transition-colors px-2.5 py-1.5 text-[12px] gap-1 bg-primary text-on-primary hover:bg-primary-dim"
      style={{ whiteSpace: 'nowrap' }}
    >
      <span
        className="material-symbols-outlined"
        style={{ fontSize: 14, fontVariationSettings: "'FILL' 1" }}
        aria-hidden="true"
      >
        {icon}
      </span>
      {label}
    </button>
  )
}
