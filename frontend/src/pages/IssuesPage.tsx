/**
 * IssuesPage — PRD-0006 Phase 2 (IMPL-0007 PR-A).
 *
 * Phase 2 ships:
 *   1. Side panel (F1+F3+F4+F5+F6) opened via ``?open=<findingId>`` URL state
 *      — replaces the standalone /workspace/:id depth surface.
 *   2. Plans-waiting / PRs-ready sub-headers inside Review (F7) — only when
 *      both subgroups are non-empty.
 *   3. Done collapsed by default with single-word verdict chips and a
 *      ``[`` / ``]`` keyboard toggle (F8). Collapse state persists per
 *      session.
 *   4. MigrationBanner removed (F10) — Phase 2 is the redesign it announced.
 *
 * Phase 1's pinned Review section, In progress collapsed-by-default, sidenav
 * trim, and ``derived`` server contract all carry over unchanged.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import type { Finding } from '../api/client'
import { api } from '../api/client'
import { useDashboard } from '../api/dashboard'
import { useFindings, useIntegrations, useAllIntegrationsHealth } from '../api/hooks'
import EmptyState from '../components/EmptyState'
import ErrorBoundary from '../components/ErrorBoundary'
import ErrorState from '../components/ErrorState'
import ImportDialog from '../components/ImportDialog'
import { IssueRow } from '../components/issues/IssueRow'
import { IssueSidePanel } from '../components/issues/IssueSidePanel'
import { IssuesHeader, type SeverityFilter, type TypeFilter } from '../components/issues/IssuesHeader'

const IN_PROGRESS_OPEN_KEY = 'opensec.issues.inProgressOpen'
const DONE_OPEN_KEY = 'opensec.issues.doneOpen'
const OPEN_PARAM = 'open'

export default function IssuesPage() {
  return (
    <ErrorBoundary
      fallbackTitle="Issues error"
      fallbackSubtitle="Something went wrong loading issues."
    >
      <IssuesPageContent />
    </ErrorBoundary>
  )
}

function IssuesPageContent() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const openId = searchParams.get(OPEN_PARAM)

  const [solving, setSolving] = useState<string | null>(null)
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all')
  /** Type filter — narrows the list to one of the four type buckets the
   *  backend emits. `dependency` + `code` both roll up under
   *  "vulnerability" in the UI per the dropdown's user-facing labelling. */
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [importOpen, setImportOpen] = useState(false)
  const [showRepoGuard, setShowRepoGuard] = useState(false)
  const [pendingFinding, setPendingFinding] = useState<Finding | null>(null)
  const [inProgressOpen, setInProgressOpen] = useState(
    () => sessionStorage.getItem(IN_PROGRESS_OPEN_KEY) === '1',
  )
  // Done is collapsed by default in Phase 2 (matches In progress).
  const [doneOpen, setDoneOpen] = useState(
    () => sessionStorage.getItem(DONE_OPEN_KEY) === '1',
  )

  const { data: integrations } = useIntegrations()
  const { data: healthStatuses } = useAllIntegrationsHealth(
    (integrations?.length ?? 0) > 0,
  )
  const githubInt = integrations?.find((i) => i.provider_name === 'GitHub')
  const githubHealth = healthStatuses?.find((h) => h.integration_id === githubInt?.id)
  const repoConfigured =
    !!githubInt?.config?.repo_url && githubHealth?.credential_status === 'ok'

  const { data: dashboard } = useDashboard()
  const grade = dashboard?.grade ?? null

  const {
    data: findings,
    isLoading,
    isError,
    refetch,
  } = useFindings({ scope: 'current', refetchIntervalMs: 5000 })

  const { sections, inProgressBreakdown, totalIssues } = useMemo(() => {
    const review: Finding[] = []
    const inProgress: Finding[] = []
    const todo: Finding[] = []
    const done: Finding[] = []
    const breakdown = { planning: 0, generating: 0, opening_pr: 0, validating: 0 }
    let total = 0
    for (const f of findings ?? []) {
      if (
        severityFilter !== 'all' &&
        (f.raw_severity ?? '').toLowerCase() !== severityFilter
      ) {
        continue
      }
      // Type filter — collapse backend `dependency` + `code` into the UI's
      // single "vulnerability" bucket. Posture / secret / license map 1:1.
      if (typeFilter !== 'all') {
        const rawType = (f.type ?? 'vulnerability').toLowerCase()
        const uiType =
          rawType === 'posture' || rawType === 'secret' || rawType === 'license'
            ? rawType
            : 'vulnerability'
        if (uiType !== typeFilter) continue
      }
      total += 1
      const section = f.derived?.section ?? 'todo'
      if (section === 'review') review.push(f)
      else if (section === 'in_progress') {
        inProgress.push(f)
        const stage = f.derived?.stage
        if (stage && stage in breakdown) {
          breakdown[stage as keyof typeof breakdown] += 1
        }
      } else if (section === 'done') done.push(f)
      else todo.push(f)
    }
    return {
      sections: { review, inProgress, todo, done },
      inProgressBreakdown: breakdown,
      totalIssues: total,
    }
  }, [findings, severityFilter, typeFilter])

  // F7 — split Review into Plans-waiting + PRs-ready buckets when both are
  // non-empty. Single-bucket Review renders flat (no sub-headers) so the
  // typical case stays uncluttered.
  const reviewSplit = useMemo(() => {
    const plans: Finding[] = []
    const prs: Finding[] = []
    for (const f of sections.review) {
      const stage = f.derived?.stage
      if (stage === 'plan_ready') plans.push(f)
      else if (stage === 'pr_ready' || stage === 'pr_awaiting_val') prs.push(f)
    }
    return { plans, prs, useSubheaders: plans.length > 0 && prs.length > 0 }
  }, [sections.review])

  const openPanel = useCallback(
    (findingId: string) => {
      const next = new URLSearchParams(searchParams)
      next.set(OPEN_PARAM, findingId)
      setSearchParams(next, { replace: false })
    },
    [searchParams, setSearchParams],
  )

  const closePanel = useCallback(() => {
    const next = new URLSearchParams(searchParams)
    next.delete(OPEN_PARAM)
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  const startWorkspaceAndOpen = useCallback(
    async (finding: Finding) => {
      // Workspace already exists? Just open the panel — no backend round-trip.
      if (finding.derived?.workspace_id) {
        openPanel(finding.id)
        return
      }
      setSolving(finding.id)
      try {
        await api.createWorkspace({ finding_id: finding.id })
        openPanel(finding.id)
      } catch (err) {
        console.error('Failed to create workspace:', err)
      } finally {
        setSolving(null)
      }
    },
    [openPanel],
  )

  const handleActivate = useCallback(
    (finding: Finding) => {
      // If a workspace already exists, open the panel directly — the user
      // already cleared the GitHub-integration guard the first time.
      if (finding.derived?.workspace_id) {
        openPanel(finding.id)
        return
      }
      if (!repoConfigured) {
        setPendingFinding(finding)
        setShowRepoGuard(true)
        return
      }
      void startWorkspaceAndOpen(finding)
    },
    [openPanel, repoConfigured, startWorkspaceAndOpen],
  )

  /** Read-only inspection — opens the side panel for any finding without
   *  touching the workspace flow. The Start / Review CTA inside the row
   *  still routes through ``handleActivate`` (which is the gated path). */
  const openInspect = useCallback(
    (finding: Finding) => {
      openPanel(finding.id)
    },
    [openPanel],
  )

  const toggleInProgress = useCallback(() => {
    setInProgressOpen((prev) => {
      const next = !prev
      sessionStorage.setItem(IN_PROGRESS_OPEN_KEY, next ? '1' : '0')
      return next
    })
  }, [])

  const toggleDone = useCallback(() => {
    setDoneOpen((prev) => {
      const next = !prev
      sessionStorage.setItem(DONE_OPEN_KEY, next ? '1' : '0')
      return next
    })
  }, [])

  // F8 — global ``[`` / ``]`` keyboard shortcut for the Done section. Skips
  // any keystroke originating from a text input so the user can still type.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const target = e.target as HTMLElement | null
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      ) {
        return
      }
      if (e.key === '[' && doneOpen) {
        e.preventDefault()
        toggleDone()
      } else if (e.key === ']' && !doneOpen) {
        e.preventDefault()
        toggleDone()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [doneOpen, toggleDone])

  if (isError) {
    return (
      <div className="bg-background min-h-screen">
        <ErrorState
          title="Couldn't load issues"
          subtitle="There was a problem fetching your issues. Please try again."
          onRetry={() => refetch()}
        />
      </div>
    )
  }

  const allFindings = findings ?? []
  const showEmptyReviewCard =
    sections.review.length === 0 &&
    sections.inProgress.length + sections.todo.length + sections.done.length > 0
  const allRepoEmpty = !isLoading && allFindings.length === 0

  // Resolve the side-panel target. If the URL points at a finding the list
  // doesn't contain (e.g. a stale bookmark or a finding that's been deleted)
  // we silently ignore the param rather than rendering an empty panel.
  const openFinding = openId
    ? (allFindings.find((f) => f.id === openId) ?? null)
    : null

  return (
    <div className="bg-background min-h-screen">
      <IssuesHeader
        findings={allFindings}
        grade={grade}
        severityFilter={severityFilter}
        onSeverityFilterChange={setSeverityFilter}
        typeFilter={typeFilter}
        onTypeFilterChange={setTypeFilter}
      />

      {importOpen && (
        <ImportDialog
          onComplete={() => {
            void refetch()
            setImportOpen(false)
          }}
          onClose={() => setImportOpen(false)}
        />
      )}

      {isLoading ? (
        <div className="flex justify-center py-24">
          <div className="w-8 h-8 border-3 border-primary/30 border-t-primary rounded-full animate-spin" />
        </div>
      ) : allRepoEmpty ? (
        <EmptyState
          icon="assignment_late"
          title="No issues yet"
          subtitle="Import findings from your scanner to get started."
          action={{
            label: 'Import',
            icon: 'upload_file',
            onClick: () => setImportOpen(true),
          }}
          footer="Supports Snyk, Wiz, and other JSON exports"
        />
      ) : (
        /* Generous top padding so the first card breathes away from the
           sticky filter sub-bar. 28px lateral matches the topbar's
           horizontal rhythm; 24px gap between sections is the canonical
           "section gap" from the design system. */
        <div
          style={{
            padding: '28px 28px 80px',
            display: 'flex',
            flexDirection: 'column',
            gap: 24,
          }}
        >
          {/* ── REVIEW — wrapped in the tactical corner-bracket frame ── */}
          {sections.review.length > 0 ? (
            <div className="cd-frame" aria-label="Review section">
              <div className="cd-frame-br" />
              {/* Sage gradient header */}
              <div
                style={{
                  padding: '14px 18px',
                  background:
                    'linear-gradient(180deg, rgba(111,227,181,0.06), rgba(111,227,181,0.01))',
                  borderBottom: '1px solid var(--cd-green-line)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 14,
                  flexWrap: 'wrap',
                }}
              >
                <span className="cd-section-label" style={{ color: 'var(--cd-green)' }}>
                  Needs you
                </span>
                <span
                  className="font-mono"
                  style={{ fontSize: 12, color: 'var(--cd-fg-4)' }}
                >
                  {sections.review.length}
                </span>
                <span style={{ fontSize: 14, color: 'var(--cd-fg-3)' }}>
                  Approve, refine, or reject before the agent ships.
                </span>
              </div>

              <div style={{ paddingTop: 10 }}>
                {reviewSplit.useSubheaders ? (
                  <>
                    <div className="cd-hairline" style={{ padding: '8px 18px' }}>
                      Plans waiting · {reviewSplit.plans.length}
                    </div>
                    {reviewSplit.plans.map((f) => (
                      <IssueRow
                        key={f.id}
                        finding={f}
                        onInspect={openInspect}
                        onActivate={handleActivate}
                      />
                    ))}
                    <div className="cd-hairline" style={{ padding: '14px 18px 8px' }}>
                      PRs ready · {reviewSplit.prs.length}
                    </div>
                    {reviewSplit.prs.map((f) => (
                      <IssueRow
                        key={f.id}
                        finding={f}
                        onInspect={openInspect}
                        onActivate={handleActivate}
                      />
                    ))}
                  </>
                ) : (
                  sections.review.map((f) => (
                    <IssueRow
                      key={f.id}
                      finding={f}
                      onInspect={openInspect}
                      onActivate={handleActivate}
                    />
                  ))
                )}
              </div>
            </div>
          ) : (
            showEmptyReviewCard && (
              <section
                aria-label="Review section"
                className="cd-card"
                style={{ padding: '32px 36px' }}
              >
                <h2
                  className="font-display font-extrabold"
                  style={{ fontSize: 22, color: 'var(--cd-fg-1)', letterSpacing: '-0.02em', marginBottom: 6 }}
                >
                  Review is clear.
                </h2>
                <p style={{ fontSize: 14, color: 'var(--cd-fg-3)', lineHeight: 1.55, maxWidth: 560 }}>
                  All open issues are either in progress or in the Todo queue.
                  The next thing that needs you will land here.
                </p>
              </section>
            )
          )}

          {/* ── IN PROGRESS — single collapsed line per the ui-kit ── */}
          {(sections.inProgress.length > 0 || !showEmptyReviewCard) && (
            <section aria-label="In progress section">
              <button
                type="button"
                onClick={toggleInProgress}
                aria-expanded={inProgressOpen}
                style={{
                  width: '100%',
                  padding: '14px 18px',
                  background: 'var(--cd-card)',
                  border: '1px solid var(--cd-rule)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 14,
                  flexWrap: 'wrap',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                <span
                  className="cd-pulse"
                  style={{
                    width: 7,
                    height: 7,
                    background: 'var(--cd-cyan)',
                    boxShadow: '0 0 6px var(--cd-cyan)',
                  }}
                  aria-hidden
                />
                <span
                  style={{
                    fontFamily: 'var(--cd-sans)',
                    fontSize: 14,
                    fontWeight: 600,
                    color: 'var(--cd-cyan)',
                  }}
                >
                  In progress
                </span>
                <span
                  className="font-mono"
                  style={{ fontSize: 12, color: 'var(--cd-fg-4)' }}
                >
                  {sections.inProgress.length}
                </span>
                <span
                  style={{ fontSize: 13, color: 'var(--cd-fg-3)' }}
                >
                  {inProgressBreakdown.planning} planning ·{' '}
                  {inProgressBreakdown.generating} generating ·{' '}
                  {inProgressBreakdown.opening_pr} opening PR ·{' '}
                  {inProgressBreakdown.validating} validating
                </span>
                <span
                  className="cd-btn cd-btn--ghost cd-btn--sm"
                  style={{ marginLeft: 'auto', pointerEvents: 'none' }}
                  aria-hidden
                >
                  <span
                    className="material-symbols-outlined"
                    style={{ fontSize: 13 }}
                  >
                    {inProgressOpen ? 'expand_less' : 'expand_more'}
                  </span>
                  {inProgressOpen ? 'Collapse' : 'Expand'}
                </span>
              </button>
              {inProgressOpen && (
                <div
                  style={{
                    background: 'var(--cd-card)',
                    border: '1px solid var(--cd-rule)',
                    borderTop: 'none',
                  }}
                >
                  {sections.inProgress.map((f) => (
                    <IssueRow
                      key={f.id}
                      finding={f}
                      onInspect={openInspect}
                      onActivate={handleActivate}
                    />
                  ))}
                </div>
              )}
            </section>
          )}

          {/* ── TODO — flat list per ui-kit ── */}
          <section aria-label="Todo section">
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '10px 0 12px',
              }}
            >
              <span
                className="material-symbols-outlined"
                aria-hidden="true"
                style={{ fontSize: 16, color: 'var(--cd-fg-2)' }}
              >
                inbox
              </span>
              <span
                style={{
                  fontFamily: 'var(--cd-sans)',
                  fontSize: 14,
                  fontWeight: 600,
                  color: 'var(--cd-fg-1)',
                }}
              >
                Todo
              </span>
              <span
                className="font-mono"
                style={{ fontSize: 11, color: 'var(--cd-fg-4)' }}
              >
                {sections.todo.length}
              </span>
              <span style={{ fontSize: 14, color: 'var(--cd-fg-3)' }}>
                Triaged but not yet picked up. Start one, or let the agent
                batch them tonight.
              </span>
            </div>
            <div
              style={{
                background: 'var(--cd-card)',
                border: '1px solid var(--cd-rule)',
              }}
            >
              {sections.todo.map((f) => (
                <IssueRow
                  key={f.id}
                  finding={f}
                  onInspect={openInspect}
                  onActivate={handleActivate}
                />
              ))}
              {sections.todo.length === 0 && (
                <p
                  style={{
                    fontSize: 12,
                    color: 'var(--cd-fg-4)',
                    padding: '14px 18px',
                  }}
                >
                  Inbox clean
                </p>
              )}
            </div>
            {solving && (
              <p
                style={{
                  fontSize: 13,
                  color: 'var(--cd-cyan)',
                  marginTop: 10,
                }}
              >
                Cliff is opening the workspace…
              </p>
            )}
          </section>

          {/* ── DONE — collapsed single line per ui-kit ── */}
          <section aria-label="Done section">
            <button
              type="button"
              onClick={toggleDone}
              aria-expanded={doneOpen}
              style={{
                width: '100%',
                padding: '12px 18px',
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                background: 'transparent',
                border: 'none',
                cursor: 'pointer',
                textAlign: 'left',
              }}
            >
              <span
                className="material-symbols-outlined"
                aria-hidden="true"
                style={{ fontSize: 16, color: 'var(--cd-fg-4)' }}
              >
                {doneOpen ? 'expand_more' : 'chevron_right'}
              </span>
              <span
                style={{
                  fontFamily: 'var(--cd-sans)',
                  fontSize: 14,
                  fontWeight: 600,
                  color: 'var(--cd-fg-2)',
                }}
              >
                Done
              </span>
              <span
                className="font-mono"
                style={{ fontSize: 12, color: 'var(--cd-fg-4)' }}
              >
                {sections.done.length}
              </span>
              <span style={{ fontSize: 13, color: 'var(--cd-fg-4)' }}>
                {doneOpen ? 'Hide closed' : 'Closed in the last 7 days'}
              </span>
              <span
                className="font-mono ml-auto"
                style={{ fontSize: 10, color: 'var(--cd-fg-4)' }}
              >
                <kbd
                  className="cd-key"
                  aria-hidden
                  style={{ marginLeft: 'auto' }}
                >
                  {doneOpen ? '[' : ']'}
                </kbd>
              </span>
            </button>
            {doneOpen && (
              <div
                style={{
                  background: 'var(--cd-card)',
                  border: '1px solid var(--cd-rule)',
                  marginTop: 6,
                }}
              >
                {sections.done.map((f) => (
                  <IssueRow
                    key={f.id}
                    finding={f}
                    onInspect={openInspect}
                    onActivate={handleActivate}
                    dim
                  />
                ))}
                {sections.done.length === 0 && (
                  <p
                    style={{
                      fontSize: 12,
                      color: 'var(--cd-fg-4)',
                      padding: '14px 18px',
                    }}
                  >
                    Nothing closed yet.
                  </p>
                )}
              </div>
            )}
          </section>

          {totalIssues === 0 && (
            <p
              style={{
                fontSize: 13,
                color: 'var(--cd-fg-4)',
                textAlign: 'center',
                marginTop: 16,
              }}
            >
              No issues match this filter.
            </p>
          )}
        </div>
      )}

      {/* Side panel — F1+F2+F3+F4+F5+F6. */}
      {openFinding && <IssueSidePanel finding={openFinding} onClose={closePanel} />}

      {/* Repo guard dialog (carried over from Phase 1) — Cyberdeck dress. */}
      {showRepoGuard && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(11,16,27,0.72)', backdropFilter: 'blur(4px)' }}
        >
          <div
            className="cd-frame mx-4"
            style={{
              background: 'var(--cd-card)',
              border: '1px solid var(--cd-rule)',
              width: '100%',
              maxWidth: 440,
              padding: '28px 28px 24px',
            }}
          >
            <div className="cd-frame-br" />
            <h3
              className="font-display font-extrabold"
              style={{
                fontSize: 20,
                color: 'var(--cd-fg-1)',
                letterSpacing: '-0.02em',
                textAlign: 'center',
                marginBottom: 8,
              }}
            >
              Connect GitHub first
            </h3>
            <p
              style={{
                fontSize: 14,
                color: 'var(--cd-fg-3)',
                lineHeight: 1.55,
                textAlign: 'center',
                marginBottom: 22,
              }}
            >
              Cliff needs a GitHub repo to clone code and open pull requests.
              You can still inspect findings without one.
            </p>
            <div className="flex flex-col gap-2.5">
              <button
                type="button"
                onClick={() => {
                  setShowRepoGuard(false)
                  navigate('/settings#integrations')
                }}
                className="cd-btn cd-btn--primary"
                style={{ width: '100%', justifyContent: 'center', padding: '10px 14px' }}
              >
                <span
                  className="material-symbols-outlined"
                  style={{ fontSize: 13 }}
                  aria-hidden
                >
                  settings
                </span>
                Configure integration
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowRepoGuard(false)
                  if (pendingFinding) openPanel(pendingFinding.id)
                  setPendingFinding(null)
                }}
                className="cd-btn cd-btn--ghost"
                style={{ width: '100%', justifyContent: 'center', padding: '10px 14px' }}
              >
                Continue without repo
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

