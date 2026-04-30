import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { api, type Finding } from '@/api/client'
import { useQueryClient } from '@tanstack/react-query'
import { useAgentRuns, useFinding, useSidebar, useSuggestedNext, useWorkspace, useWorkspaces } from '@/api/hooks'
import ActionButton from '@/components/ActionButton'
import ActionChips from '@/components/ActionChips'
import EmptyState from '@/components/EmptyState'
import EnricherResultCard from '@/components/EnricherResultCard'
import ErrorBoundary from '@/components/ErrorBoundary'
import ExposureResultCard from '@/components/ExposureResultCard'
import ListCard from '@/components/ListCard'
import Markdown from '@/components/Markdown'
import PageShell from '@/components/PageShell'
import PermissionApprovalCard from '@/components/PermissionApprovalCard'
import PlanApprovalCard from '@/components/PlanApprovalCard'
import PlannerResultCard from '@/components/PlannerResultCard'
import RemediationResultCard from '@/components/RemediationResultCard'
import SeverityBadge from '@/components/SeverityBadge'
import WorkspaceSidebar from '@/components/WorkspaceSidebar'

// ---------------------------------------------------------------------------
// Agent type → result card component map
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const RESULT_CARDS: Record<string, React.ComponentType<{ data: any; confidence?: number | null; markdown?: string }>> = {
  finding_enricher: EnricherResultCard,
  exposure_analyzer: ExposureResultCard,
  remediation_planner: PlannerResultCard,
  remediation_executor: RemediationResultCard,
}

// ---------------------------------------------------------------------------
// Chat message type (local state for streaming)
// ---------------------------------------------------------------------------

interface ChatMessage {
  role: 'user' | 'assistant' | 'error'
  content: string
  agentType?: string
  structuredOutput?: Record<string, unknown>
  confidence?: number | null
}

// ---------------------------------------------------------------------------
// Landing: list open workspaces with finding context
// ---------------------------------------------------------------------------

function WorkspaceCard({ ws, onClick }: { ws: { id: string; finding_id: string; state: string; current_focus: string | null }; onClick: () => void }) {
  const { data: finding } = useFinding(ws.finding_id)

  return (
    <ListCard>
      <div className="p-2 bg-primary-container rounded-lg flex-shrink-0">
        <span className="material-symbols-outlined text-primary text-sm">terminal</span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-base font-bold truncate">
          {finding?.title ?? 'Loading...'}
        </p>
        <div className="flex items-center gap-2 mt-1">
          {finding?.raw_severity && (
            <SeverityBadge severity={finding.raw_severity} />
          )}
          {finding?.asset_label && (
            <span className="text-xs text-on-surface-variant">{finding.asset_label}</span>
          )}
          {finding?.likely_owner && (
            <span className="text-xs text-on-surface-variant">
              &bull; {finding.likely_owner}
            </span>
          )}
        </div>
      </div>
      <ActionButton label="Continue" icon="login" onClick={onClick} />
    </ListCard>
  )
}

function WorkspaceLanding() {
  const navigate = useNavigate()
  const { data: workspaces, isLoading } = useWorkspaces({ state: 'open' })

  if (isLoading) {
    return (
      <PageShell title="Workspaces" subtitle="Active remediation sessions.">
        <div className="flex justify-center py-24">
          <div className="w-8 h-8 border-3 border-primary/30 border-t-primary rounded-full animate-spin" />
        </div>
      </PageShell>
    )
  }

  if (!workspaces || workspaces.length === 0) {
    return (
      <PageShell title="Workspaces" subtitle="Active remediation sessions.">
        <EmptyState
          icon="terminal"
          title="No active workspaces"
          subtitle="Open a finding from Findings to start a remediation session."
          action={{ label: 'Go to findings', onClick: () => navigate('/findings') }}
        />
      </PageShell>
    )
  }

  return (
    <PageShell title="Workspaces" subtitle="Pick up where you left off.">
      <div className="space-y-3">
        {workspaces.map((ws) => (
          <WorkspaceCard
            key={ws.id}
            ws={ws}
            onClick={() => navigate(`/workspace/${ws.id}`)}
          />
        ))}
      </div>
    </PageShell>
  )
}

// ---------------------------------------------------------------------------
// Active workspace
// ---------------------------------------------------------------------------

export default function WorkspacePage() {
  const { id: workspaceId } = useParams<{ id: string }>()

  return (
    <ErrorBoundary fallbackTitle="Workspace error" fallbackSubtitle="Something went wrong loading this workspace.">
      {workspaceId ? <ActiveWorkspace workspaceId={workspaceId} /> : <WorkspaceLanding />}
    </ErrorBoundary>
  )
}

function ActiveWorkspace({ workspaceId }: { workspaceId: string }) {
  const { data: workspace } = useWorkspace(workspaceId)
  const { data: finding } = useFinding(workspace?.finding_id)
  const { data: sidebar } = useSidebar(workspaceId)

  const { data: agentRuns } = useAgentRuns(workspaceId)
  const { data: suggestedNext } = useSuggestedNext(workspaceId)
  const queryClient = useQueryClient()
  const processedRunIds = useRef<Set<string>>(new Set())
  const activeRun = agentRuns?.find(r => r.status === 'running')
  const completedAgentTypes = agentRuns
    ?.filter(r => r.status === 'completed')
    .map(r => r.agent_type) ?? []

  // Chat state
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessionModel, setSessionModel] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [chatSending, setChatSending] = useState(false)
  const sending = chatSending || !!activeRun
  const [streaming, setStreaming] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)
  const lastUserMessageRef = useRef('')
  const streamingRef = useRef('')

  // Permission approval state
  // The executor serializes permission requests (blocks on each one),
  // so a single pendingPermission state is sufficient.
  const [pendingPermission, setPendingPermission] = useState<{
    id: string; tool: string; patterns: string[]; runId: string; sessionId: string
  } | null>(null)
  const [permissionLoading, setPermissionLoading] = useState(false)
  const [permissionError, setPermissionError] = useState<string | null>(null)

  // Plan-approval gate (PRD-0006 Story 3). The pipeline pauses after the
  // planner finishes; we render PlanApprovalCard until the user clicks
  // approve, then resume the run-all loop.
  const [approvingPlan, setApprovingPlan] = useState(false)
  const planFromSidebar = sidebar?.plan as
    | { plan_steps?: string[]; definition_of_done?: string[]; approved?: boolean; branch_name?: string }
    | undefined
  const executorCompleted = (agentRuns ?? []).some(
    r => r.agent_type === 'remediation_executor' && r.status === 'completed',
  )
  const planAwaitingApproval = !!(
    planFromSidebar?.plan_steps?.length &&
    !planFromSidebar.approved &&
    !executorCompleted &&
    !activeRun
  )

  const handleApprovePlan = useCallback(async () => {
    if (approvingPlan) return
    setApprovingPlan(true)
    try {
      await api.approvePlan(workspaceId)
      // Re-fetch sidebar so the gate flips locally even before the next poll.
      await queryClient.invalidateQueries({ queryKey: ['sidebar', workspaceId] })
      await api.runAllPipeline(workspaceId)
      queryClient.invalidateQueries({ queryKey: ['agent-runs', workspaceId] })
    } catch (err) {
      setMessages(prev => [...prev, { role: 'error', content: `Failed to approve plan: ${err}` }])
    } finally {
      setApprovingPlan(false)
    }
  }, [approvingPlan, workspaceId, queryClient])

  // Auto-scroll (includes pendingPermission to scroll to approval card)
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streaming, pendingPermission])

  // Restore or create OpenCode session, load existing chat history.
  useEffect(() => {
    if (!workspace) return
    let cancelled = false

    async function initSession() {
      const storedSessionId = workspace!.current_focus

      if (storedSessionId) {
        // Try to restore existing session and load its messages.
        try {
          const detail = await api.getSession(storedSessionId)
          if (!cancelled) {
            setSessionId(detail.id)
            // Use model from session messages if available, otherwise fall back to runtime.
            if (detail.model) {
              setSessionModel(detail.model)
            } else {
              try {
                const mc = await api.getModelConfig()
                if (mc.model_full_id) setSessionModel(mc.model_full_id)
              } catch { /* non-critical */ }
            }
            // Load existing chat history from OpenCode.
            const history: ChatMessage[] = detail.messages
              .filter((m) => m.content.trim())
              .map((m) => ({
                role: m.role === 'user' ? 'user' as const : 'assistant' as const,
                content: m.content,
              }))
            setMessages(history)
          }
          return
        } catch {
          // Session no longer exists — create a new one.
        }
      }

      // Create a new session on this workspace's isolated OpenCode process.
      const session = await api.createWorkspaceSession(workspaceId)
      if (!cancelled) {
        setSessionId(session.session_id)
        // Capture the runtime model at session creation time.
        try {
          const mc = await api.getModelConfig()
          if (mc.model_full_id) setSessionModel(mc.model_full_id)
        } catch { /* non-critical */ }
        // Store the session ID on the workspace for future reconnection.
        api.updateWorkspace(workspaceId, { current_focus: session.session_id } as Parameters<typeof api.updateWorkspace>[1]).catch(console.error)
      }
    }

    initSession().then(async () => {
      // Restore completed agent runs as structured cards in the timeline.
      // Running agents are detected automatically via useAgentRuns polling.
      if (cancelled) return
      try {
        const runs = await api.listAgentRuns(workspaceId)
        if (cancelled) return

        // Seed processedRunIds so the completion useEffect doesn't re-add them
        for (const r of runs) {
          if (r.status !== 'running' && r.status !== 'queued') {
            processedRunIds.current.add(r.id)
          }
        }

        // Restore completed agent runs as structured cards in the timeline.
        // ``api.listAgentRuns`` returns rows ``ORDER BY started_at DESC``
        // (newest-first); we want oldest-first so the cards land in chrono
        // order at the bottom of the chat — newest at the bottom, matching
        // every other chat UI on the planet.
        const completedRuns: ChatMessage[] = [...runs]
          .reverse()
          .filter((r) => r.status === 'completed' && r.structured_output)
          .map((r) => ({
            role: 'assistant' as const,
            content: r.summary_markdown ?? '',
            agentType: r.agent_type,
            structuredOutput: r.structured_output ?? undefined,
            confidence: r.confidence,
          }))
        if (completedRuns.length > 0 && !cancelled) {
          setMessages((prev) => [...prev, ...completedRuns])
        }
      } catch { /* non-critical */ }
    }).catch(console.error)
    return () => { cancelled = true }
  }, [workspace, workspaceId])

  // SSE connection
  useEffect(() => {
    if (!sessionId) return
    let active = true

    const es = api.streamWorkspaceEvents(workspaceId, sessionId)
    eventSourceRef.current = es

    es.addEventListener('text', (event) => {
      if (!active) return
      const text = event.data
      if (text.trim() === lastUserMessageRef.current.trim()) return
      streamingRef.current = text
      setStreaming(text)
      setChatSending(true)
    })

    es.addEventListener('error', (event: Event) => {
      if (!active) return
      try {
        const data = JSON.parse((event as MessageEvent).data)
        streamingRef.current = ''
        setStreaming('')
        setMessages((msgs) => [...msgs, { role: 'error', content: data.message || 'Unknown error' }])
      } catch { /* SSE connection error */ }
      setChatSending(false)
    })

    es.addEventListener('done', () => {
      if (!active) return
      const text = streamingRef.current
      if (text) {
        setMessages((msgs) => [...msgs, { role: 'assistant', content: text }])
      }
      streamingRef.current = ''
      setStreaming('')
      setChatSending(false)
      setPendingPermission(null)
    })

    // Listen for permission_request events on the chat SSE stream.
    // This handles the chat path (action chips like "Enrich finding")
    // where OpenCode emits permission.asked directly.
    es.addEventListener('permission_request', (event) => {
      if (!active) return
      try {
        const data = JSON.parse((event as MessageEvent).data)
        setPendingPermission({
          id: data.id,
          tool: data.tool,
          patterns: data.patterns || [],
          runId: '', // chat path has no agent run ID
          sessionId: data.session_id || '',
        })
        setPermissionError(null)
      } catch { /* parse error */ }
    })

    return () => {
      active = false
      es.close()
      eventSourceRef.current = null
    }
  }, [sessionId, workspaceId])

  // Agent completion detection — polls instead of SSE to avoid useEffect closure races.
  useEffect(() => {
    if (!agentRuns) return
    for (const run of agentRuns) {
      if (processedRunIds.current.has(run.id)) continue
      if (run.status === 'completed') {
        processedRunIds.current.add(run.id)
        setMessages((prev) => [...prev, {
          role: 'assistant' as const,
          content: run.summary_markdown ?? 'Agent completed.',
          agentType: run.agent_type,
          structuredOutput: run.structured_output ?? undefined,
          confidence: run.confidence,
        }])
      } else if (run.status === 'failed' || run.status === 'cancelled') {
        processedRunIds.current.add(run.id)
        setMessages((prev) => [...prev, {
          role: 'error' as const,
          content: run.summary_markdown ?? 'Agent execution failed. Try again or ask a question in the chat.',
        }])
      } else {
        continue
      }
      setPendingPermission(null)
      setPermissionLoading(false)
      setPermissionError(null)
      // Refresh suggestion after agent state changes.
      queryClient.invalidateQueries({ queryKey: ['suggested-next', workspaceId] })
      queryClient.invalidateQueries({ queryKey: ['sidebar', workspaceId] })
    }
  }, [agentRuns, queryClient, workspaceId])

  // Permission SSE — lightweight connection only for permission_request events.
  // Completion is detected via polling above, so done/error events are ignored.
  useEffect(() => {
    if (!activeRun) return
    const es = api.streamAgentExecution(workspaceId)

    es.addEventListener('permission_request', (event) => {
      try {
        const data = JSON.parse((event as MessageEvent).data)
        setPendingPermission({
          id: data.id,
          tool: data.tool,
          patterns: data.patterns || [],
          runId: data.run_id || activeRun.id,
          sessionId: data.session_id || '',
        })
        setPermissionError(null)
      } catch { /* parse error */ }
    })

    // Ignore done — completion detected via polling
    es.addEventListener('done', () => { /* no-op */ })
    es.addEventListener('error', () => { es.close() })

    return () => { es.close() }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- activeRun?.id is intentional; using the full object would reconnect on every poll cycle
  }, [activeRun?.id, workspaceId])

  // Permission approve/deny handler.
  // Uses the chat-path endpoint when runId is empty (action chips),
  // or the executor endpoint when runId is set (programmatic execute).
  // After approval, sending stays true — the SSE `done` event handles
  // clearing it. After deny, the agent won't produce more output, so
  // we reset sending immediately.
  const handlePermissionResponse = useCallback(async (approved: boolean) => {
    if (!pendingPermission) return
    setPermissionLoading(true)
    setPermissionError(null)
    try {
      if (pendingPermission.runId) {
        await api.respondToPermission(workspaceId, pendingPermission.runId, approved)
      } else {
        await api.respondToChatPermission(workspaceId, pendingPermission.id, pendingPermission.sessionId, approved)
      }
      setPendingPermission(null)
      if (!approved) {
        setChatSending(false)
      }
    } catch (err) {
      setPermissionError(`Failed to ${approved ? 'approve' : 'deny'}: ${err}`)
    } finally {
      setPermissionLoading(false)
    }
  }, [workspaceId, pendingPermission])

  // Send a chat message (used by text input).
  const sendChatMessage = useCallback(async (content: string) => {
    if (!sessionId || sending) return
    lastUserMessageRef.current = content
    setMessages((prev) => [...prev, { role: 'user', content }])
    setChatSending(true)
    setStreaming('')
    streamingRef.current = ''

    try {
      await api.sendWorkspaceMessage(workspaceId, sessionId, content)
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'error', content: `Failed to send: ${err}` }])
      setChatSending(false)
    }
  }, [workspaceId, sessionId, sending])

  // Handle text input submit.
  const handleSubmit = useCallback(() => {
    if (!input.trim()) return
    const content = input.trim()
    setInput('')
    sendChatMessage(content)
  }, [input, sendChatMessage])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  // Action chips trigger programmatic agent execution (not chat).
  // No manual state management — useAgentRuns polling detects the running agent.
  const handleAgentAction = useCallback(async (agentType: string) => {
    if (sending) return
    try {
      await api.executeAgent(workspaceId, agentType)
      // Immediate re-fetch so useAgentRuns picks up the running agent fast
      queryClient.invalidateQueries({ queryKey: ['agent-runs', workspaceId] })
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'error', content: `Failed to start agent: ${err}` }])
    }
  }, [workspaceId, sending, queryClient])

  const [pipelineRunning, setPipelineRunning] = useState(false)

  const handleRunAll = useCallback(async () => {
    if (sending || pipelineRunning) return
    try {
      setPipelineRunning(true)
      await api.runAllPipeline(workspaceId)
      queryClient.invalidateQueries({ queryKey: ['agent-runs', workspaceId] })
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'error', content: `Pipeline failed: ${err}` }])
      setPipelineRunning(false)
    }
  }, [workspaceId, sending, pipelineRunning, queryClient])

  // Reset pipelineRunning when no agent is active and pipeline is "done"
  useEffect(() => {
    if (pipelineRunning && !activeRun && suggestedNext?.action_type !== 'run_agent') {
      setPipelineRunning(false)
    }
  }, [pipelineRunning, activeRun, suggestedNext])

  const isResolved = workspace?.state === 'closed'

  return (
    <div className={`flex flex-col h-[calc(100vh-4rem)] ${isResolved ? 'opacity-80' : ''}`}>
      {/* Top bar with finding context */}
      <FindingHeader finding={finding} workspaceId={workspaceId} workspaceState={workspace?.state} sessionModel={sessionModel} />

      {/* Resolved banner */}
      {isResolved && (
        <div className="bg-green-50 border-b border-green-200 px-8 py-2 flex items-center gap-2">
          <span className="material-symbols-outlined text-green-600 text-sm">check_circle</span>
          <span className="text-xs font-medium text-green-700">
            This workspace has been resolved. Chat and actions are read-only.
          </span>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* Center: chat */}
        <section className="flex-1 overflow-y-auto px-8 py-8 bg-surface-container-low flex flex-col gap-6 scroll-smooth">
          {/* Finding summary card.
              Sources, in order of preference:
                1. sidebar.summary.description — enricher's prose narrative
                   (populated for every finding type once the enricher runs).
                2. finding.plain_description — plain-language gloss, written
                   on ingest for vulnerability rows.
                3. finding.description — raw scanner-emitted description,
                   typically populated for CVE rows but null for posture.
              When all three are missing we still render the card with the
              finding title so the workspace isn't blank while the enricher
              is in flight. */}
          {finding && (() => {
            const sidebarSummary = sidebar?.summary as
              | { title?: string; description?: string; cve_ids?: string[] | null; cvss_score?: number | null }
              | undefined
            const headline =
              sidebarSummary?.title || finding.title || 'Finding'
            const body =
              sidebarSummary?.description
              || finding.plain_description
              || finding.description
              || null
            const cves = sidebarSummary?.cve_ids ?? []
            const cvss = sidebarSummary?.cvss_score ?? null

            // Posture detail extraction. Each posture check writes its own
            // shape under raw_payload.detail; we surface whichever finding-
            // list key is present so users can see the exact rows to fix.
            const isPosture = finding.type === 'posture'
            const postureDetail = isPosture
              ? ((finding.raw_payload?.detail as Record<string, unknown> | undefined) ?? {})
              : {}
            type PostureItem = Record<string, string | number | null | undefined>
            const postureItems: PostureItem[] = (() => {
              for (const k of ['untrusted', 'unpinned', 'flagged', 'stale', 'matches', 'items']) {
                const v = postureDetail[k]
                if (Array.isArray(v) && v.length > 0) {
                  return v.filter((x): x is PostureItem => x !== null && typeof x === 'object') as PostureItem[]
                }
              }
              return []
            })()

            return (
              <div className="max-w-3xl">
                <div className="bg-white rounded-2xl p-6 shadow-md border border-surface-container/80">
                  <div className="flex items-start gap-4">
                    <div className="w-10 h-10 rounded-full bg-primary-container flex items-center justify-center flex-shrink-0">
                      <span className="material-symbols-outlined text-primary">auto_awesome</span>
                    </div>
                    <div className="min-w-0 w-full">
                      <h3 className="text-lg font-bold mb-1">{headline}</h3>
                      {(cves.length > 0 || cvss != null) && (
                        <div className="flex items-center gap-2 mb-3 text-xs text-on-surface-variant">
                          {cves.map(id => (
                            <span key={id} className="font-mono">{id}</span>
                          ))}
                          {cvss != null && <span>CVSS {cvss}</span>}
                        </div>
                      )}
                      {body ? (
                        <p className="text-on-surface-variant text-sm leading-relaxed mb-4">
                          {body}
                        </p>
                      ) : (
                        <p className="text-on-surface-variant text-sm italic mb-4">
                          Enriching this finding — the AI summary will appear here in a few seconds.
                        </p>
                      )}
                      {finding.why_this_matters && (
                        <div className="p-3 bg-surface-container-low rounded-lg mb-4">
                          <p className="text-[10px] text-on-surface-variant uppercase font-bold tracking-widest mb-1">
                            Why this matters
                          </p>
                          <p className="text-sm font-medium">{finding.why_this_matters}</p>
                        </div>
                      )}

                      {isPosture && postureItems.length > 0 && (
                        <div className="mt-4">
                          <p className="text-[10px] text-on-surface-variant uppercase font-bold tracking-widest mb-2">
                            What the scanner flagged ({postureItems.length})
                          </p>
                          <ul className="space-y-1.5 text-xs font-mono bg-surface-container-low rounded-lg p-3">
                            {postureItems.slice(0, 12).map((it, i) => {
                              const file = it.file as string | undefined
                              const line = it.line as string | number | undefined
                              const action = it.action as string | undefined
                              const version = it.version as string | undefined
                              const owner = it.owner as string | undefined
                              const login = it.login as string | undefined
                              const reason = it.reason as string | undefined
                              const left = file
                                ? `${file}${line != null ? `:${line}` : ''}`
                                : login || owner || reason || ''
                              const right = action
                                ? `${action}${version ? `@${version}` : ''}`
                                : owner && file ? owner : ''
                              return (
                                <li key={i} className="flex items-center gap-2 text-on-surface-variant">
                                  <span className="text-outline">·</span>
                                  <span className="truncate">{left}</span>
                                  {right && (
                                    <>
                                      <span className="text-outline">→</span>
                                      <span className="truncate">{right}</span>
                                    </>
                                  )}
                                </li>
                              )
                            })}
                            {postureItems.length > 12 && (
                              <li className="text-outline italic">…and {postureItems.length - 12} more</li>
                            )}
                          </ul>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )
          })()}

          {/* Action chips */}
          {!isResolved && (
            <ActionChips
              onAction={handleAgentAction}
              onRunAll={handleRunAll}
              disabled={!sessionId || sending}
              suggestedAgentType={suggestedNext?.agent_type}
              runningAgentType={activeRun?.agent_type}
              completedAgentTypes={completedAgentTypes}
              pipelineRunning={pipelineRunning}
            />
          )}

          {/* Chat messages */}
          {messages.map((msg, i) => (
            <div key={i} className={`max-w-3xl ${msg.role === 'user' ? 'self-end' : 'self-start'}`}>
              {msg.role === 'user' ? (
                <div className="bg-primary text-white rounded-2xl rounded-br-md px-5 py-3 shadow-sm">
                  <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                </div>
              ) : msg.role === 'error' ? (
                <div className="bg-error-container/20 border border-error/20 rounded-2xl rounded-bl-md px-5 py-3">
                  <p className="text-sm text-error leading-relaxed">{msg.content}</p>
                </div>
              ) : (() => {
                const CardComponent = msg.agentType && msg.structuredOutput ? RESULT_CARDS[msg.agentType] : undefined
                return CardComponent ? (
                  <CardComponent
                    data={msg.structuredOutput}
                    confidence={msg.confidence}
                    markdown={msg.content}
                  />
                ) : (
                  <div className="bg-white rounded-2xl rounded-bl-md px-5 py-4 shadow-sm border border-surface-container/80">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="material-symbols-outlined text-primary text-sm">auto_awesome</span>
                      <span className="text-xs font-bold text-on-surface-variant uppercase tracking-wider">OpenSec</span>
                    </div>
                    <Markdown content={msg.content} />
                  </div>
                )
              })()}
            </div>
          ))}

          {/* Plan-approval gate (PRD-0006 Story 3) — render the existing
              PlanApprovalCard inline once the planner has written a plan but
              the user hasn't approved it. The pipeline run-all loop is
              already paused server-side at this point; clicking Approve
              flips ``sidebar.plan.approved`` and resumes the loop. */}
          {planAwaitingApproval && !isResolved && (
            <div className="max-w-3xl self-start w-full">
              <PlanApprovalCard
                plan={{
                  plan_steps: planFromSidebar?.plan_steps ?? [],
                  definition_of_done:
                    (sidebar?.definition_of_done as { items?: string[] } | undefined)?.items
                    ?? planFromSidebar?.definition_of_done
                    ?? [],
                  interim_mitigation: null,
                  dependencies: [],
                  estimated_effort: null,
                  suggested_due_date: null,
                  validation_method: null,
                }}
                branchName={planFromSidebar?.branch_name}
                onApprove={() => { void handleApprovePlan() }}
                onModify={() => {
                  setMessages(prev => [...prev, {
                    role: 'assistant',
                    content: 'Modifying the plan inline is coming in a future release. For now, send refinements via chat.',
                  }])
                }}
              />
            </div>
          )}

          {/* Streaming indicator */}
          {streaming && (
            <div className="max-w-3xl self-start">
              <div className="bg-white rounded-2xl rounded-bl-md px-5 py-4 shadow-sm border border-surface-container/80">
                <div className="flex items-center gap-2 mb-2">
                  <span className="material-symbols-outlined text-primary text-sm">auto_awesome</span>
                  <span className="text-xs font-bold text-on-surface-variant uppercase tracking-wider">OpenSec</span>
                </div>
                <Markdown content={streaming} />
                <span className="inline-block w-2 h-4 bg-primary/40 rounded-sm animate-pulse ml-0.5" />
              </div>
            </div>
          )}

          {/* Thinking / running indicator */}
          {sending && !streaming && !pendingPermission && (
            <div className="max-w-3xl self-start">
              <div className="bg-indigo-50/80 border border-indigo-100 rounded-xl px-4 py-3 flex items-center gap-3 shadow-sm">
                <div className="flex gap-1">
                  <div className="w-1.5 h-1.5 rounded-full bg-primary/40 animate-bounce" style={{ animationDelay: '0ms' }} />
                  <div className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: '150ms' }} />
                  <div className="w-1.5 h-1.5 rounded-full bg-primary/80 animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
                <p className="text-sm text-on-primary-fixed-variant font-medium">
                  {activeRun ? 'Running agent...' : 'Thinking...'}
                </p>
              </div>
            </div>
          )}

          {/* Permission approval card */}
          {pendingPermission && (
            <PermissionApprovalCard
              tool={pendingPermission.tool}
              patterns={pendingPermission.patterns}
              onApprove={() => handlePermissionResponse(true)}
              onDeny={() => handlePermissionResponse(false)}
              loading={permissionLoading}
              error={permissionError}
            />
          )}

          <div ref={messagesEndRef} />
        </section>

        {/* Right sidebar */}
        <WorkspaceSidebar sidebar={sidebar} />
      </div>

      {/* Chat input */}
      {isResolved ? (
        <div className="px-8 py-4 bg-surface-container-low border-t border-surface-container">
          <div className="max-w-3xl mx-auto text-center text-xs text-on-surface-variant py-2">
            This workspace is resolved. Reopen it from the History page to continue.
          </div>
        </div>
      ) : (
        <div className="px-8 py-4 bg-surface-container-lowest border-t border-surface-container">
          <div className="max-w-3xl mx-auto flex items-end gap-3">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={pendingPermission ? "Approve or deny the tool request to continue..." : "Type a message or use action chips above..."}
              disabled={sending || !sessionId || !!pendingPermission}
              rows={1}
              className="flex-1 bg-surface-container-low border-none rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-primary/20 transition-all resize-none"
            />
            <button
              onClick={handleSubmit}
              disabled={!input.trim() || sending || !sessionId}
              className="bg-primary text-white p-3 rounded-xl hover:bg-primary-dim disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-lg shadow-primary/20 active:scale-95"
            >
              <span className="material-symbols-outlined">send</span>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Finding header bar
// ---------------------------------------------------------------------------

function FindingHeader({
  finding,
  workspaceId,
  workspaceState,
  sessionModel,
}: {
  finding: Finding | undefined
  workspaceId: string
  workspaceState: string | undefined
  sessionModel: string | null
}) {
  const navigate = useNavigate()
  const [resolving, setResolving] = useState(false)

  const isClosed = workspaceState === 'closed'

  const handleResolve = useCallback(async () => {
    setResolving(true)
    try {
      await api.updateWorkspace(workspaceId, { state: 'closed' } as Parameters<typeof api.updateWorkspace>[1])
      navigate('/findings')
    } catch (err) {
      console.error('Failed to resolve workspace:', err)
      setResolving(false)
    }
  }, [workspaceId, navigate])

  return (
    <section className="bg-surface-container-lowest px-8 py-4 flex items-center justify-between border-b border-surface-container">
      <div className="flex items-center gap-4">
        {finding?.raw_severity && (
          <div className="p-2 bg-error-container/20 rounded-lg">
            <span className="material-symbols-outlined text-error">warning</span>
          </div>
        )}
        <div>
          <h1 className="text-xl font-bold tracking-tight">
            {finding?.title ?? 'Loading...'}
          </h1>
          <div className="flex gap-3 mt-1 items-center">
            {finding?.raw_severity && <SeverityBadge severity={finding.raw_severity} size="md" />}
            {finding?.asset_label && (
              <span className="text-xs text-on-surface-variant">
                Asset: <span className="text-on-surface font-medium">{finding.asset_label}</span>
              </span>
            )}
            {finding?.likely_owner && (
              <span className="text-xs text-on-surface-variant">
                Owner: <span className="text-on-surface font-medium">{finding.likely_owner}</span>
              </span>
            )}
            {sessionModel && (
              <span className="text-xs text-on-surface-variant flex items-center gap-1">
                <span className="material-symbols-outlined text-[13px]">neurology</span>
                <span className="font-mono text-on-surface">{sessionModel}</span>
              </span>
            )}
          </div>
        </div>
      </div>
      <div className="flex gap-2">
        {isClosed ? (
          <span className="flex items-center gap-2 px-4 py-2 rounded-lg bg-green-100 text-green-700 text-sm font-bold">
            <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
            Resolved
          </span>
        ) : (
          <button
            onClick={handleResolve}
            disabled={resolving}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-tertiary hover:bg-tertiary-dim text-on-tertiary text-sm font-bold transition-all shadow-sm disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-sm">done_all</span>
            {resolving ? 'Resolving...' : 'Resolve'}
          </button>
        )}
      </div>
    </section>
  )
}
