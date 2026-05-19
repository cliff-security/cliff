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
import { useQueryClient } from '@tanstack/react-query'
import type { Finding } from '../api/client'
import { api } from '../api/client'
import { useDashboard } from '../api/dashboard'
import { useFindings, useIntegrations, useAllIntegrationsHealth } from '../api/hooks'
import EmptyState from '../components/EmptyState'
import ErrorBoundary from '../components/ErrorBoundary'
import ErrorState from '../components/ErrorState'
import ImportDialog from '../components/ImportDialog'
import { FirstScanBanner } from '../components/issues/FirstScanBanner'
import { IssueRow } from '../components/issues/IssueRow'
import { IssueSidePanel } from '../components/issues/IssueSidePanel'
import { IssuesHeader, type SeverityFilter, type TypeFilter } from '../components/issues/IssuesHeader'

const IN_PROGRESS_OPEN_KEY = 'cliff.issues.inProgressOpen'
const DONE_OPEN_KEY = 'cliff.issues.doneOpen'
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
  const queryClient = useQueryClient()

  const [solving, setSolving] = useState<string | null>(null)
  // B25 — hydrate the filter dropdowns from the URL on first render so
  // deep links like /issues?severity=critical&type=posture actually
  // narrow the visible list without the user re-selecting the chips.
  const initialSeverity = (
    searchParams.get('severity') ?? 'all'
  ) as SeverityFilter
  const initialType = (searchParams.get('type') ?? 'all') as TypeFilter
  const [severityFilter, setSeverityFilter] =
    useState<SeverityFilter>(initialSeverity)
  /** Type filter — narrows the list to one of the four type buckets the
   *  backend emits. `dependency` + `code` both roll up under
   *  "vulnerability" in the UI per the dropdown's user-facing labelling. */
  const [typeFilter, setTypeFilter] = useState<TypeFilter>(initialType)

  // Mirror the filter state back into the URL so deep-linkable state
  // survives reloads and the back button. Compare-before-set so the
  // effect doesn't fight itself or push duplicate history entries.
  const syncFilterParam = useCallback(
    (key: 'severity' | 'type', value: string) => {
      const next = new URLSearchParams(searchParams)
      if (value === 'all') {
        if (!next.has(key)) return
        next.delete(key)
      } else {
        if (next.get(key) === value) return
        next.set(key, value)
      }
      setSearchParams(next, { replace: true })
    },
    [searchParams, setSearchParams],
  )

  const handleSeverityFilterChange = useCallback(
    (value: SeverityFilter) => {
      setSeverityFilter(value)
      syncFilterParam('severity', value)
    },
    [syncFilterParam],
  )

  const handleTypeFilterChange = useCallback(
    (value: TypeFilter) => {
      setTypeFilter(value)
      syncFilterParam('type', value)
    },
    [syncFilterParam],
  )
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

  const { sections, totalIssues } = useMemo(() => {
    const review: Finding[] = []
    const inProgress: Finding[] = []
    const todo: Finding[] = []
    const done: Finding[] = []
    let total = 0
    for (const f of findings ?? []) {
      // Canonical severity = ``normalized_priority`` (server-mapped to
      // critical/high/medium/low). The IssuesHeader chip count uses the same
      // field, so the filter and the chip always agree. ``raw_severity`` is
      // scanner-native (e.g. ``WARNING``/``HIGH``) and would mis-bucket here.
      if (
        severityFilter !== 'all' &&
        (f.normalized_priority ?? '').toLowerCase() !== severityFilter
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
      else if (section === 'in_progress') inProgress.push(f)
      else if (section === 'done') done.push(f)
      else todo.push(f)
    }
    return {
      sections: { review, inProgress, todo, done },
      totalIssues: total,
    }
  }, [findings, severityFilter, typeFilter])

  // F7 — split Review into Errors / Plans-waiting / PRs-ready buckets.
  // Sub-headers render whenever more than one bucket is populated so the
  // user can tell ``errors needing retry`` apart from the rest. Single-
  // bucket Review renders flat (no sub-headers) so the typical case stays
  // uncluttered.
  const reviewSplit = useMemo(() => {
    const approvals: Finding[] = []
    const plans: Finding[] = []
    const prs: Finding[] = []
    const errors: Finding[] = []
    for (const f of sections.review) {
      const stage = f.derived?.stage
      // Approval requests come first — the agent is literally paused
      // waiting for the user, which is more urgent than a finished plan
      // or a ready PR.
      if (stage === 'awaiting_permission') approvals.push(f)
      else if (stage === 'failed') errors.push(f)
      else if (stage === 'plan_ready') plans.push(f)
      else if (stage === 'pr_ready' || stage === 'pr_awaiting_val') prs.push(f)
    }
    const nonEmpty = [approvals, errors, plans, prs].filter(
      (b) => b.length > 0,
    ).length
    return { approvals, plans, prs, errors, useSubheaders: nonEmpty > 1 }
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
      setSolving(finding.id)
      let workspaceId = finding.derived?.workspace_id ?? null
      try {
        // POST /workspaces is idempotent server-side (one workspace per
        // finding, forever — preserves KB + sidebar + agent runs), so the
        // first-time path and "second click" path converge cleanly.
        if (!workspaceId) {
          const workspace = await api.createWorkspace({ finding_id: finding.id })
          workspaceId = workspace.id
        }
        openPanel(finding.id)
        // Optimistically rewrite this finding's row in every cached
        // findings query so the IssueRow moves out of "Todo" stage *this
        // render*. Without this, ``solving`` clears as soon as the POST
        // resolves but the cached row still carries ``derived.stage='todo'``
        // until the next 5-second refetch — the user sees a flash back to
        // "Start" before "Thinking" lands.
        const optimisticWorkspaceId = workspaceId
        queryClient.setQueriesData<Finding[]>(
          { queryKey: ['findings'] },
          (rows) =>
            rows?.map((r) =>
              r.id === finding.id
                ? {
                    ...r,
                    status: 'in_progress',
                    derived: {
                      ...(r.derived ?? {
                        section: 'in_progress',
                        stage: 'planning',
                        workspace_id: optimisticWorkspaceId,
                        pr_url: null,
                      }),
                      section: 'in_progress',
                      stage: 'planning',
                      workspace_id: optimisticWorkspaceId,
                    },
                  }
                : r,
            ) ?? rows,
        )
        // Always fire the pipeline. If an agent is already running for this
        // workspace the backend rejects with 409 (the AgentBusy guard) and
        // we silently swallow it — that's exactly the state we wanted. If
        // the workspace existed but never had agents fire (e.g. a
        // re-assessed finding), this is what gets it unstuck.
        if (workspaceId) {
          api.runAllPipeline(workspaceId).catch((err) => {
            if (err?.status !== 409) {
              console.error('Failed to start remediation pipeline:', err)
            }
          })
        }
      } catch (err) {
        console.error('Failed to start finding:', err)
      } finally {
        setSolving(null)
      }
    },
    [openPanel, queryClient],
  )

  const handleActivate = useCallback(
    (finding: Finding) => {
      // The GitHub-integration guard only matters when we'd actually have
      // to create the workspace (and therefore call GitHub). If a workspace
      // already exists we skip the guard — the user has cleared it before —
      // but still route through startWorkspaceAndOpen so the pipeline gets
      // (re-)triggered on findings whose workspace never had agents fire.
      if (finding.derived?.workspace_id) {
        void startWorkspaceAndOpen(finding)
        return
      }
      if (!repoConfigured) {
        setPendingFinding(finding)
        setShowRepoGuard(true)
        return
      }
      void startWorkspaceAndOpen(finding)
    },
    [repoConfigured, startWorkspaceAndOpen],
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
  // B26 — only surface the "manual review queue is clear" reassurance
  // when there is genuinely no Todo waiting either. Previously the card
  // rendered alongside 45 queued Todo items, which read as a false
  // all-clear. Empty queue must mean both Review AND Todo are empty.
  const showEmptyReviewCard =
    sections.review.length === 0 &&
    sections.todo.length === 0 &&
    sections.inProgress.length + sections.done.length > 0
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
        onSeverityFilterChange={handleSeverityFilterChange}
        typeFilter={typeFilter}
        onTypeFilterChange={handleTypeFilterChange}
      />

      <FirstScanBanner
        totalFindings={allFindings.length}
        closedCount={sections.done.length}
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
                    {reviewSplit.approvals.length > 0 && (
                      <>
                        <div
                          className="cd-hairline"
                          style={{ padding: '8px 18px' }}
                          data-testid="review-bucket-approvals"
                        >
                          Awaiting approval · {reviewSplit.approvals.length}
                        </div>
                        {reviewSplit.approvals.map((f) => (
                          <IssueRow
                            key={f.id}
                            finding={f}
                            onInspect={openInspect}
                            onActivate={handleActivate}
                            starting={solving === f.id}
                          />
                        ))}
                      </>
                    )}
                    {reviewSplit.errors.length > 0 && (
                      <>
                        <div className="cd-hairline" style={{ padding: '8px 18px' }}>
                          Errors · {reviewSplit.errors.length}
                        </div>
                        {reviewSplit.errors.map((f) => (
                          <IssueRow
                            key={f.id}
                            finding={f}
                            onInspect={openInspect}
                            onActivate={handleActivate}
                            starting={solving === f.id}
                          />
                        ))}
                      </>
                    )}
                    {reviewSplit.plans.length > 0 && (
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
                            starting={solving === f.id}
                          />
                        ))}
                      </>
                    )}
                    {reviewSplit.prs.length > 0 && (
                      <>
                        <div className="cd-hairline" style={{ padding: '14px 18px 8px' }}>
                          PRs ready · {reviewSplit.prs.length}
                        </div>
                        {reviewSplit.prs.map((f) => (
                          <IssueRow
                            key={f.id}
                            finding={f}
                            onInspect={openInspect}
                            onActivate={handleActivate}
                            starting={solving === f.id}
                          />
                        ))}
                      </>
                    )}
                  </>
                ) : (
                  sections.review.map((f) => (
                    <IssueRow
                      key={f.id}
                      finding={f}
                      onInspect={openInspect}
                      onActivate={handleActivate}
                      starting={solving === f.id}
                    />
                  ))
                )}
              </div>
            </div>
          ) : (
            showEmptyReviewCard && (
              /* Empty NEEDS YOU — tactical corner-bracket frame + a
               * sage check-stroke that draws on mount. Inverts the
               * "this is loaded, pay attention" gesture to mean "the
               * console framed the answer for you, and it's good." */
              <section
                aria-label="Review section"
                className="cd-frame"
                style={{ padding: 0 }}
              >
                <div className="cd-frame-br" />
                <div
                  style={{
                    padding: '36px 36px 36px 32px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 24,
                  }}
                >
                  <svg
                    width="56"
                    height="56"
                    viewBox="0 0 56 56"
                    aria-hidden
                    style={{ flexShrink: 0 }}
                  >
                    <circle
                      cx="28"
                      cy="28"
                      r="26"
                      fill="none"
                      stroke="var(--cd-green)"
                      strokeWidth="1.4"
                      opacity="0.35"
                    />
                    <path
                      d="M16 29 L24 37 L40 19"
                      fill="none"
                      stroke="var(--cd-green)"
                      strokeWidth="2.2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className="cd-stroke-on-mount"
                      style={
                        {
                          ['--cd-stroke-length']: '52',
                          filter: 'drop-shadow(0 0 6px var(--cd-green-glow))',
                        } as React.CSSProperties &
                          Record<`--${string}`, string>
                      }
                    />
                  </svg>
                  <div>
                    <h2
                      className="font-display font-extrabold"
                      style={{
                        fontSize: 24,
                        color: 'var(--cd-fg-1)',
                        letterSpacing: '-0.02em',
                        marginBottom: 6,
                      }}
                    >
                      Manual review queue is clear.
                    </h2>
                    <p
                      style={{
                        fontSize: 14,
                        color: 'var(--cd-fg-3)',
                        lineHeight: 1.55,
                        maxWidth: 560,
                      }}
                    >
                      All open issues are either in progress or in the Todo
                      queue. The next thing that needs you will land here.
                    </p>
                  </div>
                </div>
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
                  {/* The per-substage breakdown ("0 planning · 2 generating
                       · …") was misleading: substages were derived
                       optimistically from finding.status and don't reliably
                       reflect what the executor is actually doing. Until we
                       wire real progress events we just surface the
                       aggregate count, which is always correct. */}
                  Agents working — no action needed
                </span>
                {/* Hint chip, not a button — the outer <button> is the
                 *  toggle. Styled as a quiet caption + chevron rather
                 *  than wearing cd-btn chrome so it can't be confused
                 *  for an interactive element. */}
                <span
                  aria-hidden
                  style={{
                    marginLeft: 'auto',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    fontSize: 13,
                    color: 'var(--cd-fg-3)',
                  }}
                >
                  <span
                    className="material-symbols-outlined"
                    style={{ fontSize: 14 }}
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
                      starting={solving === f.id}
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
                  starting={solving === f.id}
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
      {openFinding && (
        <IssueSidePanel
          finding={openFinding}
          onClose={closePanel}
          onStart={() => handleActivate(openFinding)}
          starting={solving === openFinding.id}
        />
      )}

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

