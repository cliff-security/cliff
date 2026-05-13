/**
 * IssueRow — Cliff Cyberdeck issue list row.
 *
 * Grid layout mirrors `ui-kit/issues.jsx` exactly:
 *   [60px severity] [22px type-icon] [1fr title+meta] [150px stage] [130px action]
 *
 * - cd-row hover (sage left border) + hairline top border between rows
 * - title 13.5px in fg-2, mono meta line with cyan file path, amber CVSS,
 *   fg-4 timestamp
 * - action: cd-btn primary (Review plan / Review PR) or outline (Start)
 *
 * Click semantics:
 * - Click the row body → `onInspect(finding)` opens the side panel for
 *   read-only inspection. No workspace is created, no repo guard fires.
 * - Click the action button → `onActivate(finding)` runs the existing
 *   handler that creates a workspace + opens the panel, gated by the
 *   GitHub-integration check on the parent page.
 *
 * That split (inspect-vs-activate) is the ui-kit's intent: clicking a row
 * always reveals the finding; the explicit CTA is what "starts" work.
 */
import { memo, useState, type KeyboardEvent, type MouseEvent, type ReactElement } from 'react'
import type { Finding, IssueStage } from '../../api/client'
import {
  IssuePostureBadge,
  IssueSeverityBadge,
  type IssueSeverityKind,
} from './IssueSeverityBadge'
import { IssueStageChip } from './IssueStageChip'

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
  dim?: boolean
  focused?: boolean
  /** Row-body click — open the side panel for inspection only. */
  onInspect?: (finding: Finding) => void
  /** Action-button click — run the workspace/start flow (may show guards). */
  onActivate?: (finding: Finding) => void
}

function IssueRowImpl({
  finding,
  dim = false,
  focused = false,
  onInspect,
  onActivate,
}: IssueRowProps): ReactElement {
  const [hover, setHover] = useState(false)

  const stage: IssueStage = finding.derived?.stage ?? 'todo'
  const action = actionForStage(stage)
  const isPosture = finding.type === 'posture'
  const sev = severityKind(finding.raw_severity)
  const typeIcon = TYPE_ICON[finding.type ?? 'dependency'] ?? 'bug_report'

  const inspect = (): void => {
    if (onInspect) onInspect(finding)
    else onActivate?.(finding)
  }

  const activate = (e: MouseEvent): void => {
    e.stopPropagation()
    onActivate?.(finding)
  }

  const handleKey = (e: KeyboardEvent<HTMLDivElement>): void => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      inspect()
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
      onClick={inspect}
      onKeyDown={handleKey}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className={`cd-row ${focused ? 'cd-row--focus' : ''} ${dim ? 'opacity-70' : ''}`}
      style={{
        display: 'grid',
        gridTemplateColumns: '60px 22px minmax(0,1fr) 150px 130px',
        gap: 16,
        alignItems: 'center',
        padding: '12px 16px',
        borderTop: '1px solid var(--cd-rule)',
        cursor: 'pointer',
      }}
    >
      {/* 1. Severity / category chip (60px col) */}
      <div style={{ display: 'flex', alignItems: 'center' }}>
        {isPosture ? (
          <IssuePostureBadge category={finding.category ?? undefined} size="sm" />
        ) : (
          <IssueSeverityBadge kind={sev} size="sm" />
        )}
      </div>

      {/* 2. Type icon (22px col, stroke-only) */}
      <span
        aria-hidden="true"
        style={{ color: 'var(--cd-fg-4)', display: 'inline-flex', alignItems: 'center' }}
      >
        <span
          className="material-symbols-outlined"
          style={{ fontSize: 14, fontVariationSettings: "'FILL' 0, 'wght' 400" }}
        >
          {typeIcon}
        </span>
      </span>

      {/* 3. Title + meta */}
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontSize: 13.5,
            fontWeight: 500,
            color: hover ? 'var(--cd-fg-1)' : 'var(--cd-fg-2)',
            lineHeight: 1.3,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {finding.title}
        </div>
        <div
          className="font-mono"
          style={{
            fontSize: 12,
            color: 'var(--cd-fg-3)',
            marginTop: 3,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {!isPosture && file && (
            <span style={{ color: 'var(--cd-cyan)' }}>
              {file}
              {line != null ? `:${line}` : ''}
            </span>
          )}
          {!isPosture && cwe && (
            <>
              <span style={{ margin: '0 6px', color: 'var(--cd-fg-5)' }}>·</span>
              <span>{cwe}</span>
            </>
          )}
          {!isPosture && cvss != null && (
            <>
              <span style={{ margin: '0 6px', color: 'var(--cd-fg-5)' }}>·</span>
              <span style={{ color: 'var(--cd-amber)' }}>{cvss}</span>
            </>
          )}
          {!isPosture && (
            <>
              <span style={{ margin: '0 6px', color: 'var(--cd-fg-5)' }}>·</span>
              <span>{finding.source_id}</span>
            </>
          )}
          {found && (
            <span style={{ marginLeft: 8, color: 'var(--cd-fg-5)' }}>
              {found}
            </span>
          )}
        </div>
      </div>

      {/* 4. Stage chip */}
      <div>
        <IssueStageChip kind={stage} size="sm" />
      </div>

      {/* 5. Action */}
      <div style={{ textAlign: 'right', display: 'flex', justifyContent: 'flex-end' }}>
        {action === 'review_plan' && (
          <button onClick={activate} className="cd-btn cd-btn--primary cd-btn--sm">
            <span className="material-symbols-outlined" style={{ fontSize: 13 }} aria-hidden>
              rate_review
            </span>
            Review plan
          </button>
        )}
        {action === 'review_pr' && (
          <button onClick={activate} className="cd-btn cd-btn--primary cd-btn--sm">
            <span className="material-symbols-outlined" style={{ fontSize: 13 }} aria-hidden>
              merge_type
            </span>
            Review PR
          </button>
        )}
        {action === 'start' && (
          <button onClick={activate} className="cd-btn cd-btn--outline cd-btn--sm">
            <span className="material-symbols-outlined" style={{ fontSize: 13 }} aria-hidden>
              play_arrow
            </span>
            Start
          </button>
        )}
        {action === 'view' && (
          <span
            aria-hidden
            style={{
              color: hover ? 'var(--cd-fg-2)' : 'var(--cd-fg-4)',
              display: 'inline-flex',
              alignItems: 'center',
            }}
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

export const IssueRow = memo(IssueRowImpl)
