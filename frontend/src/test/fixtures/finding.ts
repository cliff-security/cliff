/**
 * Test fixture factory for `Finding` records, used by the IMPL-0006 Issues
 * page tests (IssueRow, IssuesHeader, IssuesPage). Single source of truth so
 * each test file doesn't re-derive `derived.section` from `stage` differently.
 *
 * Mirrors the section-from-stage mapping in
 * `backend/opensec/models/issue_derivation.py` so fixtures match what the
 * server would actually return.
 */
import type { Finding, IssueSection, IssueStage } from '../../api/client'

const REVIEW_STAGES: ReadonlySet<IssueStage> = new Set([
  'plan_ready',
  'pr_ready',
  'pr_awaiting_val',
])

const DONE_STAGES: ReadonlySet<IssueStage> = new Set([
  'fixed',
  'false_positive',
  'wont_fix',
  'accepted',
  'deferred',
])

function sectionForStage(stage: IssueStage): IssueSection {
  if (REVIEW_STAGES.has(stage)) return 'review'
  if (DONE_STAGES.has(stage)) return 'done'
  if (stage === 'todo') return 'todo'
  return 'in_progress'
}

export interface MakeFindingOptions {
  id?: string
  stage?: IssueStage
  severity?: 'critical' | 'high' | 'medium' | 'low'
  workspaceId?: string | null
  prUrl?: string | null
  updated_at?: string
  title?: string
}

export function makeFinding(opts: MakeFindingOptions = {}): Finding {
  const stage: IssueStage = opts.stage ?? 'todo'
  const id = opts.id ?? 'f-1'
  return {
    id,
    source_type: 'trivy',
    source_id: id,
    title: opts.title ?? `Issue ${id}`,
    description: null,
    raw_severity: opts.severity ?? 'high',
    // Mirror the input severity. The legacy P1/P2/P3 convention was retired
    // in favor of critical/high/medium/low (matches IssueSeverityBadge,
    // OpenBySeverityCard, and the IssuesPage severity filter all reading
    // the canonical critical/high/medium/low values).
    normalized_priority: opts.severity ?? 'high',
    asset_id: null,
    asset_label: null,
    status: 'new',
    likely_owner: null,
    why_this_matters: null,
    raw_payload: null,
    plain_description: null,
    created_at: '2026-04-29T00:00:00Z',
    updated_at: opts.updated_at ?? '2026-04-29T00:00:00Z',
    type: 'dependency',
    derived: {
      section: sectionForStage(stage),
      stage,
      workspace_id: opts.workspaceId ?? null,
      pr_url: opts.prUrl ?? null,
    },
  }
}
