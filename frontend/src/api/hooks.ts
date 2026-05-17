import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type {
  AgentRunCreate,
  AgentRunUpdate,
  Finding,
  IngestRequest,
  IntegrationConfigCreate,
  IntegrationConfigUpdate,
  MessageCreate,
  RejectFindingPayload,
  WorkspaceCreate,
} from './client'

// ---------------------------------------------------------------------------
// Health (Phase 1)
// ---------------------------------------------------------------------------

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => api.health(),
    refetchInterval: 30_000,
  })
}

// ---------------------------------------------------------------------------
// OpenCode sessions (Phase 1)
// ---------------------------------------------------------------------------

export function useSessions() {
  return useQuery({
    queryKey: ['sessions'],
    queryFn: () => api.listSessions(),
  })
}

export function useSession(id: string | undefined) {
  return useQuery({
    queryKey: ['session', id],
    queryFn: () => api.getSession(id!),
    enabled: !!id,
  })
}

// ---------------------------------------------------------------------------
// Findings (Phase 4)
// ---------------------------------------------------------------------------

export function useFindings(params?: {
  status?: string
  has_workspace?: boolean
  scope?: 'current'
  /**
   * Optional poll interval in milliseconds. The Issues page (PRD-0006)
   * passes 5000 so rows visibly transition between sections (Todo → In
   * progress → Review → Done) as the agent pipeline progresses, without
   * the user needing to refresh. Other consumers (e.g. tests, single-row
   * lookups) leave it unset for the default no-polling behaviour.
   */
  refetchIntervalMs?: number
}) {
  return useQuery({
    queryKey: ['findings', params],
    queryFn: () => api.listFindings(params),
    refetchInterval: params?.refetchIntervalMs ?? false,
  })
}

export function useFinding(id: string | undefined) {
  return useQuery({
    queryKey: ['finding', id],
    queryFn: () => api.getFinding(id!),
    enabled: !!id,
  })
}

// PRD-0006 / IMPL-0008 — Issues count badge for SideNav. Shares the cache key
// with IssuesPage's `useFindings({ scope: 'current', refetchIntervalMs: 5000 })`
// call so mounting both components triggers a single network request.
export function useOpenIssuesCount(): number {
  const { data } = useFindings({ scope: 'current', refetchIntervalMs: 5000 })
  return useMemo(() => {
    if (!data) return 0
    return data.filter((f) =>
      ['review', 'in_progress', 'todo'].includes(f.derived?.section ?? ''),
    ).length
  }, [data])
}

// PRD-0006 Phase 2 — partial PATCH for the side panel's Reopen flow (clear
// status + exception_reason + exception_note). Invalidates the findings
// list + the single-finding query so the row visually returns to its
// pre-reject section/stage.
export function useUpdateFinding() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Finding> }) =>
      api.updateFinding(id, data),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['findings'] })
      qc.invalidateQueries({ queryKey: ['finding', variables.id] })
    },
  })
}

// PRD-0006 Phase 2 — Reject reason picker submit (POST /findings/{id}/reject).
export function useRejectFinding() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: RejectFindingPayload }) =>
      api.rejectFinding(id, payload),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['findings'] })
      qc.invalidateQueries({ queryKey: ['finding', variables.id] })
    },
  })
}

// PRD-0006 Phase 2 — generic agent-execute mutation. The Refine inline state
// in the side panel passes ``{ agentType: 'remediation_planner', user_note }``;
// other callers can omit ``user_note`` and behave like Phase 1.
export function useExecuteAgent(workspaceId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      agentType,
      user_note,
    }: {
      agentType: string
      user_note?: string
    }) => api.executeAgent(workspaceId!, agentType, user_note ? { user_note } : undefined),
    onSuccess: () => {
      if (workspaceId) {
        qc.invalidateQueries({ queryKey: ['agent-runs', workspaceId] })
        qc.invalidateQueries({ queryKey: ['sidebar', workspaceId] })
      }
      qc.invalidateQueries({ queryKey: ['findings'] })
    },
  })
}

// Cancel the currently-running agent run for a workspace. The backend
// flips the agent_run to status='cancelled'; the issue-derivation then
// surfaces the finding as 'failed' (recoverable via Retry) rather than
// spinning on "Thinking" forever.
export function useCancelAgentRun(workspaceId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (runId: string) => api.cancelAgentRun(workspaceId!, runId),
    onSuccess: () => {
      if (workspaceId) {
        qc.invalidateQueries({ queryKey: ['agent-runs', workspaceId] })
        qc.invalidateQueries({ queryKey: ['sidebar', workspaceId] })
      }
      qc.invalidateQueries({ queryKey: ['findings'] })
    },
  })
}

// Approve or deny a parked agent-permission request. Approve → the
// executor resumes; deny → the run ends and ``derive()`` routes the
// finding to ``review/failed`` with the existing Retry CTA. Invalidating
// agent-runs is the load-bearing call — it bumps the row out of the
// "Needs you" bucket as soon as the marker clears server-side. Sidebar +
// findings are belt-and-suspenders for the rare race where the executor
// races ahead to plan_ready / pr_ready before our refetch fires.
export function useRespondToPermission(workspaceId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ runId, approved }: { runId: string; approved: boolean }) =>
      api.respondToPermission(workspaceId!, runId, approved),
    onSuccess: () => {
      if (workspaceId) {
        qc.invalidateQueries({ queryKey: ['agent-runs', workspaceId] })
        qc.invalidateQueries({ queryKey: ['sidebar', workspaceId] })
      }
      qc.invalidateQueries({ queryKey: ['findings'] })
    },
  })
}

// ---------------------------------------------------------------------------
// Workspaces (Phase 5)
// ---------------------------------------------------------------------------

export function useWorkspaces(params?: { state?: string; finding_id?: string }) {
  return useQuery({
    queryKey: ['workspaces', params],
    queryFn: () => api.listWorkspaces(params),
  })
}

export function useWorkspace(id: string | undefined) {
  return useQuery({
    queryKey: ['workspace', id],
    queryFn: () => api.getWorkspace(id!),
    enabled: !!id,
  })
}

export function useCreateWorkspace() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: WorkspaceCreate) => api.createWorkspace(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workspaces'] })
    },
  })
}

// ---------------------------------------------------------------------------
// Messages (Phase 5)
// ---------------------------------------------------------------------------

export function useMessages(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ['messages', workspaceId],
    queryFn: () => api.listMessages(workspaceId!),
    enabled: !!workspaceId,
  })
}

export function useCreateMessage(workspaceId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: MessageCreate) => api.createMessage(workspaceId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['messages', workspaceId] })
    },
  })
}

// ---------------------------------------------------------------------------
// Agent chips (UI metadata)
// ---------------------------------------------------------------------------

export function useAgentChips() {
  return useQuery({
    queryKey: ['agent-chips'],
    queryFn: () => api.listAgentChips(),
    staleTime: Infinity,
  })
}

// ---------------------------------------------------------------------------
// Pipeline suggestion (which agent to run next)
// ---------------------------------------------------------------------------

export function useSuggestedNext(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ['suggested-next', workspaceId],
    queryFn: () => api.getSuggestedNext(workspaceId!),
    enabled: !!workspaceId,
    staleTime: 5_000,
  })
}

// ---------------------------------------------------------------------------
// Agent runs (Phase 5)
// ---------------------------------------------------------------------------

export function useAgentRuns(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ['agent-runs', workspaceId],
    queryFn: () => api.listAgentRuns(workspaceId!),
    enabled: !!workspaceId,
    // Always keep a background poll going while a workspace panel is
    // open: when an agent IS running we tick fast (2 s) so the
    // "Thinking…" widget updates promptly; when nothing is running we
    // still tick at 5 s so the panel observes the freshly-completed
    // planner flipping derived.stage → ``plan_ready`` (which is what
    // makes the footer's "Approve & generate fix" button appear). The
    // previous behaviour (``false`` between runs) stalled the UI on the
    // stale "Thinking…" widget and blocked plan approval — B28/B29.
    refetchInterval: (query) => {
      const runs = query.state.data
      const hasActive = runs?.some(
        (r) => r.status === 'running' || r.status === 'queued',
      )
      return hasActive ? 2_000 : 5_000
    },
  })
}

export function useCreateAgentRun(workspaceId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: AgentRunCreate) => api.createAgentRun(workspaceId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-runs', workspaceId] })
    },
  })
}

export function useUpdateAgentRun(workspaceId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ runId, data }: { runId: string; data: AgentRunUpdate }) =>
      api.updateAgentRun(workspaceId, runId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-runs', workspaceId] })
    },
  })
}

// ---------------------------------------------------------------------------
// Sidebar state (Phase 5)
// ---------------------------------------------------------------------------

export function useSidebar(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ['sidebar', workspaceId],
    queryFn: () => api.getSidebar(workspaceId!),
    enabled: !!workspaceId,
    retry: false,
  })
}

// ---------------------------------------------------------------------------
// Settings — Model (Settings overhaul)
// ---------------------------------------------------------------------------

export function useModelConfig() {
  return useQuery({
    queryKey: ['model-config'],
    queryFn: () => api.getModelConfig(),
  })
}

export function useUpdateModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (model_full_id: string) => api.updateModel(model_full_id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['model-config'] })
      qc.invalidateQueries({ queryKey: ['health'] })
    },
  })
}

// ---------------------------------------------------------------------------
// Settings — Providers
// ---------------------------------------------------------------------------

export function useProviders() {
  return useQuery({
    queryKey: ['providers'],
    queryFn: () => api.listProviders(),
  })
}

export function useConfiguredProviders() {
  return useQuery({
    queryKey: ['configured-providers'],
    queryFn: () => api.getConfiguredProviders(),
  })
}

// ---------------------------------------------------------------------------
// Settings — API Keys
// ---------------------------------------------------------------------------

export function useApiKeys() {
  return useQuery({
    queryKey: ['api-keys'],
    queryFn: () => api.listApiKeys(),
  })
}

export function useSetApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ provider, key }: { provider: string; key: string }) =>
      api.setApiKey(provider, key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['api-keys'] })
      qc.invalidateQueries({ queryKey: ['configured-providers'] })
      qc.invalidateQueries({ queryKey: ['health'] })
    },
  })
}

export function useDeleteApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (provider: string) => api.deleteApiKey(provider),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['api-keys'] })
      qc.invalidateQueries({ queryKey: ['configured-providers'] })
    },
  })
}

// ---------------------------------------------------------------------------
// Settings — Integrations
// ---------------------------------------------------------------------------

export function useIntegrations() {
  return useQuery({
    queryKey: ['integrations'],
    queryFn: () => api.listIntegrations(),
  })
}

export function useCreateIntegration() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: IntegrationConfigCreate) => api.createIntegration(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['integrations'] })
    },
  })
}

export function useUpdateIntegration() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: IntegrationConfigUpdate }) =>
      api.updateIntegration(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['integrations'] })
    },
  })
}

export function useDeleteIntegration() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteIntegration(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['integrations'] })
    },
  })
}

// ---------------------------------------------------------------------------
// Integration Registry (Phase I-0)
// ---------------------------------------------------------------------------

export function useRegistry() {
  return useQuery({
    queryKey: ['registry'],
    queryFn: () => api.getRegistry(),
  })
}

export function useRegistryEntry(id: string | undefined) {
  return useQuery({
    queryKey: ['registry', id],
    queryFn: () => api.getRegistryEntry(id!),
    enabled: !!id,
  })
}

// ---------------------------------------------------------------------------
// Integration Credentials (Phase I-0)
// ---------------------------------------------------------------------------

export function useCredentials(integrationId: string | undefined) {
  return useQuery({
    queryKey: ['credentials', integrationId],
    queryFn: () => api.listCredentials(integrationId!),
    enabled: !!integrationId,
  })
}

export function useStoreCredential() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ integrationId, keyName, value }: {
      integrationId: string; keyName: string; value: string
    }) => api.storeCredential(integrationId, keyName, value),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['credentials', variables.integrationId] })
    },
  })
}

export function useDeleteCredential() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ integrationId, keyName }: {
      integrationId: string; keyName: string
    }) => api.deleteCredential(integrationId, keyName),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['credentials', variables.integrationId] })
    },
  })
}

export function useTestIntegration() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (integrationId: string) => api.testIntegration(integrationId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['integrations-health'] })
    },
  })
}

// ---------------------------------------------------------------------------
// Integration Health (Priority 3)
// ---------------------------------------------------------------------------

export function useAllIntegrationsHealth(enabled: boolean = true) {
  return useQuery({
    queryKey: ['integrations-health'],
    queryFn: () => api.getAllIntegrationsHealth(),
    enabled,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  })
}

// ---------------------------------------------------------------------------
// Finding Ingest (ADR-0023)
// ---------------------------------------------------------------------------

export function useIngestProgress(jobId: string | null) {
  return useQuery({
    queryKey: ['ingest-progress', jobId],
    queryFn: () => api.getIngestProgress(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'completed' || status === 'failed' || status === 'cancelled') return false
      return 2_000
    },
  })
}

// ---------------------------------------------------------------------------
// Finding ingest
// ---------------------------------------------------------------------------

export function useStartIngest() {
  return useMutation({
    mutationFn: (data: IngestRequest) => api.startIngest(data),
  })
}

export function useCancelIngest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => api.cancelIngest(jobId),
    onSuccess: (_, jobId) => {
      qc.invalidateQueries({ queryKey: ['ingest-progress', jobId] })
    },
  })
}
