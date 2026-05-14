/** API client for the OpenSec FastAPI backend. */

const BASE = '';  // Uses Vite proxy in dev

// ---------------------------------------------------------------------------
// OpenCode session types (Phase 1)
// ---------------------------------------------------------------------------

export interface SessionSummary {
  id: string;
  created_at?: string;
}

export interface SessionDetail extends SessionSummary {
  messages: MessageInfo[];
  model?: string;
}

export interface MessageInfo {
  id: string;
  role: string;
  content: string;
  created_at?: string;
}

export interface HealthStatus {
  opensec: string;
  opencode: string;
  opencode_version: string;
  model: string;
}

// ---------------------------------------------------------------------------
// Domain types (Phase 3+)
// ---------------------------------------------------------------------------

export type FindingStatus =
  | 'new' | 'triaged' | 'in_progress' | 'remediated'
  | 'validated' | 'closed' | 'exception' | 'passed';

export type FindingType = 'dependency' | 'code' | 'secret' | 'posture';
export type FindingGradeImpact = 'counts' | 'advisory';

// PRD-0006 Phase 2 — values accepted by POST /findings/{id}/reject. The
// server enforces this set via a CHECK constraint (migration 012) and a
// Pydantic Literal — keep them in lockstep.
export type ExceptionReason =
  | 'false_positive'
  | 'accepted_risk'
  | 'wont_fix'
  | 'deferred';

// PRD-0006 / IMPL-0006 — server-derived UI section + stage. Computed in
// repo_finding from workspace + sidebar + agent-run state. Never persisted.
export type IssueSection = 'review' | 'in_progress' | 'todo' | 'done';

export type IssueStage =
  | 'todo'
  | 'planning' | 'generating' | 'pushing' | 'opening_pr' | 'validating'
  | 'plan_ready' | 'pr_ready' | 'pr_awaiting_val'
  | 'failed'
  | 'fixed' | 'false_positive' | 'wont_fix' | 'accepted' | 'deferred';

export interface IssueDerived {
  section: IssueSection;
  stage: IssueStage;
  workspace_id: string | null;
  pr_url: string | null;
}

export interface Finding {
  id: string;
  source_type: string;
  source_id: string;
  title: string;
  description: string | null;
  /** Plain-language description written for a non-security reader (IMPL-0002 Milestone A). */
  plain_description?: string | null;
  raw_severity: string | null;
  normalized_priority: string | null;
  asset_id: string | null;
  asset_label: string | null;
  status: FindingStatus;
  likely_owner: string | null;
  why_this_matters: string | null;
  raw_payload: Record<string, unknown> | null;
  // ADR-0027 v0.2 columns. Optional in the TS contract because older fixtures
  // and seed payloads in tests may omit them; backend always returns them.
  type?: FindingType;
  grade_impact?: FindingGradeImpact;
  category?: string | null;
  assessment_id?: string | null;
  pr_url?: string | null;
  created_at: string;
  updated_at: string;
  // PRD-0006 / IMPL-0006 — populated on list/get responses.
  derived?: IssueDerived | null;
  // PRD-0006 Phase 2 — reject metadata, set by POST /findings/{id}/reject.
  exception_reason?: ExceptionReason | null;
  exception_note?: string | null;
}

// PRD-0006 Phase 2 — body of POST /findings/{id}/reject.
export interface RejectFindingPayload {
  reason: ExceptionReason;
  note?: string | null;
}

export type WorkspaceState =
  | 'open' | 'waiting' | 'ready_to_close' | 'closed' | 'reopened';

export interface Workspace {
  id: string;
  finding_id: string;
  state: WorkspaceState;
  current_focus: string | null;
  active_plan_version: number | null;
  linked_ticket_id: string | null;
  validation_state: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceCreate {
  finding_id: string;
  state?: WorkspaceState;
  current_focus?: string;
}

export type MessageRole = 'user' | 'assistant' | 'system' | 'agent';

export interface Message {
  id: string;
  workspace_id: string;
  role: MessageRole;
  content_markdown: string | null;
  linked_agent_run_id: string | null;
  created_at: string;
}

export interface MessageCreate {
  role: MessageRole;
  content_markdown?: string;
  linked_agent_run_id?: string;
}

export type AgentRunStatus =
  | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface AgentRun {
  id: string;
  workspace_id: string;
  agent_type: string;
  status: AgentRunStatus;
  input_json: Record<string, unknown> | null;
  summary_markdown: string | null;
  confidence: number | null;
  evidence_json: Record<string, unknown> | null;
  structured_output: Record<string, unknown> | null;
  next_action_hint: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface AgentRunCreate {
  agent_type: string;
  status?: AgentRunStatus;
  input_json?: Record<string, unknown>;
}

export interface AgentRunUpdate {
  status?: AgentRunStatus;
  summary_markdown?: string;
  confidence?: number;
  evidence_json?: Record<string, unknown>;
  structured_output?: Record<string, unknown>;
  next_action_hint?: string;
}

// ---------------------------------------------------------------------------
// Structured output types (mirror backend agents/schemas.py)
// ---------------------------------------------------------------------------

export interface EnrichmentOutput {
  normalized_title: string;
  cve_ids: string[];
  cvss_score: number | null;
  cvss_vector: string | null;
  description: string | null;
  affected_versions: string | null;
  fixed_version: string | null;
  known_exploits: boolean;
  exploit_details: string | null;
  references: string[];
}

export interface ExposureOutput {
  recommended_urgency: string;
  environment: string | null;
  internet_facing: boolean | null;
  reachable: string | null;
  reachability_evidence: string | null;
  business_criticality: string | null;
  blast_radius: string | null;
}

export interface PlanOutput {
  plan_steps: string[];
  definition_of_done: string[];
  interim_mitigation: string | null;
  dependencies: string[];
  estimated_effort: string | null;
  suggested_due_date: string | null;
  validation_method: string | null;
}

export interface RemediationExecutorOutput {
  status: string;
  pr_url: string | null;
  branch_name: string | null;
  changes_summary: string | null;
  test_results: string | null;
  error_details: string | null;
}

export interface AgentChipConfig {
  agent_type: string;
  label: string;
  icon: string;
}

export interface SuggestedNext {
  agent_type: string | null;
  reason: string | null;
  priority: string | null;
  action_type: string | null;
}

export interface SidebarState {
  workspace_id: string;
  summary: Record<string, unknown> | null;
  evidence: Record<string, unknown> | null;
  owner: Record<string, unknown> | null;
  plan: Record<string, unknown> | null;
  definition_of_done: Record<string, unknown> | null;
  linked_ticket: Record<string, unknown> | null;
  validation: Record<string, unknown> | null;
  similar_cases: Record<string, unknown> | null;
  pull_request: Record<string, unknown> | null;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Settings types
// ---------------------------------------------------------------------------

export interface ModelConfig {
  model_full_id: string;
  provider: string;
  model_id: string;
}

export interface ProviderInfo {
  id: string;
  name: string;
  env: string[];
  models: Record<string, {
    id: string;
    name: string;
    release_date?: string;
    reasoning?: boolean;
    tool_call?: boolean;
    temperature?: boolean;
    attachment?: boolean;
  }>;
}

export interface ApiKeyInfo {
  provider: string;
  key_masked: string;
  has_credentials: boolean;
  updated_at: string | null;
}

export interface IntegrationConfigItem {
  id: string;
  adapter_type: string;
  provider_name: string;
  enabled: boolean;
  config: Record<string, unknown> | null;
  last_test_result: Record<string, unknown> | null;
  updated_at: string;
  /** ADR-0035 / IMPL-0010 — populated only on the github row.
   * 'github_app' = device-flow path; 'pat' = legacy PAT onboarding. */
  auth_method?: 'github_app' | 'pat' | null;
  /** GitHub login the user authorized as. Populated only for
   *  auth_method='github_app' rows. */
  github_login?: string | null;
}

export interface IntegrationConfigCreate {
  adapter_type: string;
  provider_name: string;
  enabled?: boolean;
  config?: Record<string, unknown>;
}

export interface IntegrationConfigUpdate {
  enabled?: boolean;
  config?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Integration registry & credential types (Phase I-0)
// ---------------------------------------------------------------------------

export interface CredentialField {
  key_name: string;
  label: string;
  type: 'password' | 'text' | 'url';
  required: boolean;
  help_text: string | null;
  placeholder: string | null;
}

export interface RegistryEntry {
  id: string;
  name: string;
  adapter_type: string;
  description: string;
  icon: string;
  status: 'available' | 'coming_soon' | 'community';
  setup_guide_md: string;
  credentials_schema: CredentialField[];
  config_fields?: CredentialField[];
  capabilities: string[];
  docs_url: string | null;
  mcp_config: Record<string, unknown> | null;
  /** ADR-0035 / IMPL-0010 — true on the github entry when the
   * shared GitHub App + Device Flow onboarding surface is configured
   * on this instance. Stays false for every other entry. */
  github_app_available?: boolean;
}

export interface CredentialInfo {
  key_name: string;
  created_at: string;
  rotated_at: string | null;
}

export interface TestConnectionResult {
  success: boolean;
  message: string;
  details: Record<string, unknown> | null;
}

export interface IntegrationHealthStatus {
  integration_id: string;
  registry_id: string;
  provider_name: string;
  credential_status: string;
  connection_status: string;
  last_checked: string | null;
  error_message: string | null;
}

// ---------------------------------------------------------------------------
// Ingest types (ADR-0023)
// ---------------------------------------------------------------------------

export type IngestJobStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';

export interface IngestRequest {
  source: string;
  raw_data: Record<string, unknown>[];
  model?: string;
  chunk_size?: number;
  dry_run?: boolean;
}

export interface IngestJobResponse {
  job_id: string;
  status: string;
  total_items: number;
  chunk_size: number;
  total_chunks: number;
  estimated_tokens: number | null;
  poll_url: string;
}

export interface IngestJobProgress {
  job_id: string;
  status: IngestJobStatus;
  total_items: number;
  total_chunks: number;
  completed_chunks: number;
  failed_chunks: number;
  findings_created: number;
  errors: string[];
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

export async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
  return resp.json();
}

export async function requestVoid(
  path: string,
  init?: RequestInit,
): Promise<void> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
}

// ---------------------------------------------------------------------------
// API methods
// ---------------------------------------------------------------------------

export const api = {
  // Health
  health: () => request<HealthStatus>('/health'),

  // OpenCode sessions (legacy — shared singleton process)
  createSession: () =>
    request<SessionSummary>('/api/sessions', { method: 'POST' }),
  listSessions: () => request<SessionSummary[]>('/api/sessions'),
  getSession: (id: string) =>
    request<SessionDetail>(`/api/sessions/${id}`),

  // Chat — legacy (shared singleton process)
  sendMessage: (sessionId: string, content: string) =>
    request<{ session_id: string; status: string }>(
      `/api/chat/${sessionId}/send`,
      { method: 'POST', body: JSON.stringify({ content }) },
    ),
  streamEvents: (sessionId: string): EventSource =>
    new EventSource(`/api/chat/${sessionId}/stream`),

  // Workspace-scoped sessions (isolated per-workspace OpenCode process)
  createWorkspaceSession: (workspaceId: string) =>
    request<{ session_id: string; workspace_id: string }>(
      `/api/workspaces/${workspaceId}/sessions`,
      { method: 'POST' },
    ),

  // Workspace-scoped chat (isolated per-workspace OpenCode process)
  sendWorkspaceMessage: (workspaceId: string, sessionId: string, content: string) =>
    request<{ session_id: string; status: string }>(
      `/api/workspaces/${workspaceId}/chat/send`,
      { method: 'POST', body: JSON.stringify({ session_id: sessionId, content }) },
    ),
  streamWorkspaceEvents: (workspaceId: string, sessionId: string): EventSource =>
    new EventSource(`/api/workspaces/${workspaceId}/chat/stream?session_id=${sessionId}`),

  // Findings
  listFindings: (params?: {
    status?: string;
    has_workspace?: boolean;
    scope?: 'current';
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.has_workspace != null) qs.set('has_workspace', String(params.has_workspace));
    if (params?.scope) qs.set('scope', params.scope);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.offset) qs.set('offset', String(params.offset));
    const q = qs.toString();
    return request<Finding[]>(`/api/findings${q ? `?${q}` : ''}`);
  },
  getFinding: (id: string) => request<Finding>(`/api/findings/${id}`),

  // PRD-0006 Phase 2 — partial update (used by the side panel's Reopen flow
  // to clear ``status`` + ``exception_reason`` + ``exception_note`` back to
  // null after a reject). Backend route is PATCH /findings/{id}.
  updateFinding: (id: string, data: Partial<Finding>) =>
    request<Finding>(`/api/findings/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  // PRD-0006 Phase 2 — reject endpoint (POST /findings/{id}/reject).
  rejectFinding: (id: string, payload: RejectFindingPayload) =>
    request<Finding>(`/api/findings/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // Workspaces
  createWorkspace: (data: WorkspaceCreate) =>
    request<Workspace>('/api/workspaces', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  listWorkspaces: (params?: { state?: string; finding_id?: string }) => {
    const qs = new URLSearchParams();
    if (params?.state) qs.set('state', params.state);
    if (params?.finding_id) qs.set('finding_id', params.finding_id);
    const q = qs.toString();
    return request<Workspace[]>(`/api/workspaces${q ? `?${q}` : ''}`);
  },
  getWorkspace: (id: string) =>
    request<Workspace>(`/api/workspaces/${id}`),
  updateWorkspace: (id: string, data: Partial<Workspace>) =>
    request<Workspace>(`/api/workspaces/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  // Messages (nested under workspaces)
  createMessage: (workspaceId: string, data: MessageCreate) =>
    request<Message>(`/api/workspaces/${workspaceId}/messages`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  listMessages: (workspaceId: string) =>
    request<Message[]>(`/api/workspaces/${workspaceId}/messages`),

  // Agent runs (nested under workspaces)
  createAgentRun: (workspaceId: string, data: AgentRunCreate) =>
    request<AgentRun>(
      `/api/workspaces/${workspaceId}/agent-runs`,
      { method: 'POST', body: JSON.stringify(data) },
    ),
  listAgentRuns: (workspaceId: string) =>
    request<AgentRun[]>(`/api/workspaces/${workspaceId}/agent-runs`),
  getAgentRun: (workspaceId: string, runId: string) =>
    request<AgentRun>(
      `/api/workspaces/${workspaceId}/agent-runs/${runId}`,
    ),
  updateAgentRun: (
    workspaceId: string,
    runId: string,
    data: AgentRunUpdate,
  ) =>
    request<AgentRun>(
      `/api/workspaces/${workspaceId}/agent-runs/${runId}`,
      { method: 'PATCH', body: JSON.stringify(data) },
    ),

  // Sidebar state (nested under workspaces)
  getSidebar: (workspaceId: string) =>
    request<SidebarState>(`/api/workspaces/${workspaceId}/sidebar`),
  upsertSidebar: (
    workspaceId: string,
    data: Partial<SidebarState>,
  ) =>
    request<SidebarState>(`/api/workspaces/${workspaceId}/sidebar`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  // Seed
  seed: () => request<Finding[]>('/api/seed', { method: 'POST' }),

  // Delete (for cleanup)
  deleteFinding: (id: string) =>
    requestVoid(`/api/findings/${id}`, { method: 'DELETE' }),

  // Settings — Model
  getModelConfig: () => request<ModelConfig>('/api/settings/model'),
  updateModel: (model_full_id: string) =>
    request<ModelConfig>('/api/settings/model', {
      method: 'PUT',
      body: JSON.stringify({ model_full_id }),
    }),

  // Settings — Providers
  listProviders: () => request<ProviderInfo[]>('/api/settings/providers'),
  getConfiguredProviders: () =>
    request<{ providers: unknown; auth: Record<string, unknown[]> }>(
      '/api/settings/providers/configured',
    ),

  // Settings — API Keys
  listApiKeys: () => request<ApiKeyInfo[]>('/api/settings/api-keys'),
  setApiKey: (provider: string, key: string) =>
    request<ApiKeyInfo>(`/api/settings/api-keys/${provider}`, {
      method: 'PUT',
      body: JSON.stringify({ provider, key }),
    }),
  deleteApiKey: (provider: string) =>
    requestVoid(`/api/settings/api-keys/${provider}`, { method: 'DELETE' }),

  // Settings — Integrations
  listIntegrations: () =>
    request<IntegrationConfigItem[]>('/api/settings/integrations'),
  createIntegration: (data: IntegrationConfigCreate) =>
    request<IntegrationConfigItem>('/api/settings/integrations', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateIntegration: (id: string, data: IntegrationConfigUpdate) =>
    request<IntegrationConfigItem>(`/api/settings/integrations/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteIntegration: (id: string) =>
    requestVoid(`/api/settings/integrations/${id}`, { method: 'DELETE' }),

  // Settings — Integration Registry
  getRegistry: () =>
    request<RegistryEntry[]>('/api/settings/integrations/registry'),
  getRegistryEntry: (id: string) =>
    request<RegistryEntry>(`/api/settings/integrations/registry/${id}`),

  // Settings — Credentials (per integration)
  listCredentials: (integrationId: string) =>
    request<CredentialInfo[]>(
      `/api/settings/integrations/${integrationId}/credentials`,
    ),
  storeCredential: (integrationId: string, keyName: string, value: string) =>
    request<CredentialInfo>(
      `/api/settings/integrations/${integrationId}/credentials`,
      { method: 'POST', body: JSON.stringify({ key_name: keyName, value }) },
    ),
  deleteCredential: (integrationId: string, keyName: string) =>
    requestVoid(
      `/api/settings/integrations/${integrationId}/credentials/${keyName}`,
      { method: 'DELETE' },
    ),

  // Settings — Test Connection
  testIntegration: (integrationId: string) =>
    request<TestConnectionResult>(
      `/api/settings/integrations/${integrationId}/test`,
      { method: 'POST' },
    ),

  // Settings — Integration Health
  getAllIntegrationsHealth: () =>
    request<IntegrationHealthStatus[]>('/api/settings/integrations/health'),

  // Finding ingest (ADR-0023)
  startIngest: (data: IngestRequest) =>
    request<IngestJobResponse>('/api/findings/ingest', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getIngestProgress: (jobId: string) =>
    request<IngestJobProgress>(`/api/findings/ingest/${jobId}`),
  cancelIngest: (jobId: string) =>
    request<{ job_id: string; status: string }>(
      `/api/findings/ingest/${jobId}/cancel`,
      { method: 'POST' },
    ),

  // Agent chips (UI metadata from backend registry)
  listAgentChips: () =>
    request<AgentChipConfig[]>('/api/agents/chips'),

  // Pipeline suggestion
  getSuggestedNext: (workspaceId: string) =>
    request<SuggestedNext>(`/api/workspaces/${workspaceId}/pipeline/suggest-next`),

  // Agent execution. PRD-0006 Phase 2 — optional ``user_note`` is forwarded
  // to the planner's prompt for the Refine flow; other agents ignore it.
  executeAgent: (
    workspaceId: string,
    agentType: string,
    body?: { user_note?: string },
  ) =>
    request<{ agent_run_id: string; agent_type: string; status: string }>(
      `/api/workspaces/${workspaceId}/agents/${agentType}/execute`,
      {
        method: 'POST',
        body: body ? JSON.stringify(body) : undefined,
      },
    ),

  // Run all remaining pipeline agents sequentially
  runAllPipeline: (workspaceId: string) =>
    request<{ status: string; message: string }>(
      `/api/workspaces/${workspaceId}/pipeline/run-all`,
      { method: 'POST' },
    ),

  // Approve the planner's output and release the run-all loop's gate
  // so the executor can run (PRD-0006 Story 3).
  approvePlan: (workspaceId: string) =>
    request<SidebarState>(
      `/api/workspaces/${workspaceId}/plan/approve`,
      { method: 'POST' },
    ),

  // Agent execution SSE stream (connect when agent starts, disconnect on completion)
  streamAgentExecution: (workspaceId: string): EventSource =>
    new EventSource(`/api/workspaces/${workspaceId}/agent-execution/stream`),

  // Permission approval (programmatic execute path)
  respondToPermission: (workspaceId: string, runId: string, approved: boolean) =>
    request<{ status: string; agent_run_id: string }>(
      `/api/workspaces/${workspaceId}/agent-runs/${runId}/permission`,
      { method: 'POST', body: JSON.stringify({ approved }) },
    ),

  // Permission approval (chat path — calls OpenCode directly)
  respondToChatPermission: (workspaceId: string, permissionId: string, sessionId: string, approved: boolean) =>
    request<{ status: string; permission_id: string }>(
      `/api/workspaces/${workspaceId}/chat/permission`,
      { method: 'POST', body: JSON.stringify({ permission_id: permissionId, session_id: sessionId, approved }) },
    ),

  // Completion share-action recording (EXEC-0002 / IMPL-0002 H5).
  // Frozen contract: POST /api/completion/{id}/share-action returns HTTP 200
  // with { completion_id, share_actions_used }. Frontend treats it as
  // fire-and-forget (the response body is ignored).
  recordShareAction: (
    completionId: string,
    action: 'download' | 'copy_text' | 'copy_markdown',
  ) =>
    requestVoid(`/api/completion/${completionId}/share-action`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    }),
};
