/**
 * AI provider onboarding client (ADR-0036, IMPL-0011).
 *
 * Mirrors the backend routes under /api/integrations/ai.
 */

import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request, requestVoid } from './client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AIProvider =
  | 'openrouter'
  | 'anthropic'
  | 'openai'
  | 'google'
  | 'ollama'
  | 'custom'
export type AISource = 'autodetect' | 'openrouter-oauth' | 'byok'
export type AIState = 'unconfigured' | 'connected'
export type OAuthStatus =
  | 'waiting'
  | 'connected'
  | 'denied'
  | 'error'
  | 'timeout'

export type ByokErrorCode =
  | 'auth_failed'
  | 'no_access'
  | 'network'
  | 'rate_limited'
  | 'model_not_found'

export interface AIStatusResponse {
  state: AIState
  provider: AIProvider | null
  source: AISource | null
  connected_at: string | null
  metadata: Record<string, unknown> | null
  /** Canonical active model — written via the picker, used by workspace spawn. */
  model: string | null
}

export interface ProviderModelOption {
  id: string
  label: string
  description: string | null
}

export interface ProviderModelsResponse {
  provider: AIProvider
  default_model: string | null
  models: ProviderModelOption[]
  /** ``'live'`` for Ollama (probes /api/tags); ``'catalog'`` for cloud providers. */
  source: 'catalog' | 'live'
}

export interface AutodetectResponse {
  found: boolean
  provider: AIProvider | null
  source: string | null
}

export interface OpenRouterStartResponse {
  auth_url: string
  session_id: string
}

export interface OpenRouterStatusResponse {
  status: OAuthStatus
  detail: string | null
}

export interface BYOKErrorBody {
  error_code: ByokErrorCode
  error_message: string
}

// ---------------------------------------------------------------------------
// Raw API
// ---------------------------------------------------------------------------

export const aiProviderApi = {
  status: () => request<AIStatusResponse>('/api/integrations/ai/status'),
  autodetect: () =>
    request<AutodetectResponse>('/api/integrations/ai/autodetect'),
  adopt: () =>
    request<AIStatusResponse>('/api/integrations/ai/autodetect/adopt', {
      method: 'POST',
      body: '{}',
    }),
  byok: (body: {
    provider: AIProvider
    api_key: string
    base_url?: string
    model?: string
  }) =>
    request<AIStatusResponse>('/api/integrations/ai/byok', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  openrouterStart: () =>
    request<OpenRouterStartResponse>(
      '/api/integrations/ai/openrouter/start',
      { method: 'POST', body: '{}' },
    ),
  openrouterStatus: (sessionId: string) =>
    request<OpenRouterStatusResponse>(
      `/api/integrations/ai/openrouter/status?session_id=${encodeURIComponent(
        sessionId,
      )}`,
    ),
  setModel: (model: string) =>
    request<AIStatusResponse>('/api/integrations/ai/model', {
      method: 'PUT',
      body: JSON.stringify({ model }),
    }),
  listProviderModels: (provider: AIProvider) =>
    request<ProviderModelsResponse>(
      `/api/integrations/ai/models?provider=${encodeURIComponent(provider)}`,
    ),
  disconnect: () =>
    requestVoid('/api/integrations/ai/disconnect', {
      method: 'POST',
      body: '{}',
    }),
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

const STATUS_KEY = ['ai-provider', 'status'] as const

/**
 * Invalidate every ``ai-provider`` cache key EXCEPT the status query.
 * Mutations that return the new status payload call ``setQueryData`` to
 * seed it directly — invalidating the status key on top of that would
 * trigger an immediate refetch that throws away the fresh data we just
 * stored (round-trip race + UI flash).
 */
function invalidateAINonStatus(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({
    predicate: (q) =>
      q.queryKey[0] === 'ai-provider' && q.queryKey[1] !== 'status',
  })
}

/** Read-only status hook — drives every agent-button gate via useAIRequired.
 *
 * Refetches every 15s so the Settings card reflects upstream change
 * quickly. The drift banner that the 15s cadence used to feed was
 * removed in M9 (architect health-check): on_key_change restarts the
 * singleton synchronously, so canonical state and the loaded model
 * can't disagree by more than one event loop tick.
 */
export function useAIProviderStatus() {
  return useQuery({
    queryKey: STATUS_KEY,
    queryFn: aiProviderApi.status,
    refetchInterval: 15_000,
    staleTime: 5_000,
  })
}

/** Auto-detect a key in the user's environment. Read-only — never persists. */
export function useAutodetect(enabled: boolean = true) {
  return useQuery({
    queryKey: ['ai-provider', 'autodetect'],
    queryFn: aiProviderApi.autodetect,
    enabled,
    staleTime: 60_000,
  })
}

export function useAdopt() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: aiProviderApi.adopt,
    onSuccess: (data) => {
      qc.setQueryData(STATUS_KEY, data)
      invalidateAINonStatus(qc)
    },
  })
}

export function useByok() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: aiProviderApi.byok,
    onSuccess: (data) => {
      qc.setQueryData(STATUS_KEY, data)
      invalidateAINonStatus(qc)
    },
  })
}

export function useDisconnect() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: aiProviderApi.disconnect,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ai-provider'] })
    },
  })
}

export function useOpenRouterStart() {
  return useMutation({
    mutationFn: aiProviderApi.openrouterStart,
  })
}

/** Change the canonical active model. */
export function useSetModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (model: string) => aiProviderApi.setModel(model),
    onSuccess: (data) => {
      qc.setQueryData(STATUS_KEY, data)
      invalidateAINonStatus(qc)
    },
  })
}

/** List the picker's suggested models for *provider*. */
export function useProviderModels(provider: AIProvider | null) {
  return useQuery({
    queryKey: ['ai-provider', 'models', provider],
    queryFn: () => aiProviderApi.listProviderModels(provider as AIProvider),
    enabled: !!provider,
    staleTime: provider === 'ollama' ? 5_000 : 60_000,
  })
}

/**
 * Poll the OAuth status endpoint every 1s while *sessionId* is set and the
 * status is non-terminal. Calls *onTerminal* once with the final status.
 * Hard 5-min timeout matches the backend listener TTL.
 *
 * After this much elapsed `waiting`, the hook also consults the canonical
 * `/ai/status` and promotes to terminal-connected if the DB-backed status
 * says so — guards against any race where the per-session state flag lags
 * behind the persisted integration.
 */
const openRouterAiStatusFallbackAfterMs = 5_000
/** Throttle: at most one extra `/ai/status` call per this window while waiting. */
const openRouterAiStatusFallbackThrottleMs = 5_000

export function useOpenRouterPolling(
  sessionId: string | null,
  onTerminal: (status: OpenRouterStatusResponse) => void,
) {
  const startedAt = useRef<number | null>(null)
  // Guards against the terminal-status effect re-firing every time the
  // parent re-renders with a fresh `onTerminal` callback identity.
  const lastHandled = useRef<OAuthStatus | null>(null)
  const lastAiStatusCheckAt = useRef<number>(0)
  const TIMEOUT_MS = 5 * 60 * 1000
  const qc = useQueryClient()

  const query = useQuery({
    queryKey: ['ai-provider', 'openrouter', sessionId],
    queryFn: async () => {
      // When the backend's listener TTL (5 min) elapses or the singleton was
      // restarted, /openrouter/status returns 404 even though the callback
      // may have already persisted the key. Fall back to /ai/status (which
      // reads from the DB) and treat a connected OpenRouter row as the
      // terminal result. ``request<T>`` throws Error("404: <body>").
      let resp: OpenRouterStatusResponse
      try {
        resp = await aiProviderApi.openrouterStatus(sessionId as string)
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err ?? '')
        const httpStatus = Number.parseInt(msg.split(':', 1)[0] ?? '', 10)
        if (httpStatus === 404) {
          try {
            const ai = await aiProviderApi.status()
            if (ai.state === 'connected' && ai.provider === 'openrouter') {
              return {
                status: 'connected' as const,
                detail: null,
              } satisfies OpenRouterStatusResponse
            }
          } catch {
            // Surface the original 404 path instead.
          }
        }
        throw err
      }

      // Same canonical-status promotion for the "still alive, just stuck on
      // waiting" case. Throttled so a 5-minute hang doesn't issue ~300
      // redundant /ai/status calls — at most one per 5 s.
      if (
        resp.status === 'waiting' &&
        startedAt.current !== null &&
        Date.now() - startedAt.current >
          openRouterAiStatusFallbackAfterMs &&
        Date.now() - lastAiStatusCheckAt.current >
          openRouterAiStatusFallbackThrottleMs
      ) {
        lastAiStatusCheckAt.current = Date.now()
        try {
          const ai = await aiProviderApi.status()
          if (ai.state === 'connected' && ai.provider === 'openrouter') {
            return {
              status: 'connected' as const,
              detail: null,
            } satisfies OpenRouterStatusResponse
          }
        } catch {
          // Keep returning the waiting response.
        }
      }

      return resp
    },
    enabled: !!sessionId,
    // Refetch when the tab regains focus so a user who tabs back from
    // the OpenRouter consent screen sees the terminal status without
    // waiting for the next 1-second tick (Chrome aggressively throttles
    // background-tab timers). This is in addition to the 1 s poll.
    refetchOnWindowFocus: true,
    refetchInterval: (q) => {
      if (!q.state.data) return 1000
      if (q.state.data.status !== 'waiting') return false
      if (
        startedAt.current !== null &&
        Date.now() - startedAt.current > TIMEOUT_MS
      ) {
        return false
      }
      return 1000
    },
  })

  useEffect(() => {
    if (sessionId && startedAt.current === null) {
      startedAt.current = Date.now()
    } else if (!sessionId) {
      startedAt.current = null
      lastHandled.current = null
      lastAiStatusCheckAt.current = 0
    }
  }, [sessionId])

  useEffect(() => {
    if (!query.data) return
    if (query.data.status === 'waiting') return
    if (lastHandled.current === query.data.status) return
    lastHandled.current = query.data.status
    onTerminal(query.data)
    qc.invalidateQueries({ queryKey: STATUS_KEY })
  }, [query.data, onTerminal, qc])

  return query
}

// ---------------------------------------------------------------------------
// Gate hook — drives every agent-action button
// ---------------------------------------------------------------------------

export interface AIRequiredState {
  enabled: boolean
  tooltip: string | null
  loading: boolean
  /** True when a configured provider is OpenAI / custom — UI shows a
   *  "tuned for Claude" toast on the first agent click of the session. */
  isOpenAIClass: boolean
}

export function useAIRequired(): AIRequiredState {
  const { data, isLoading } = useAIProviderStatus()
  if (isLoading) {
    return { enabled: false, tooltip: null, loading: true, isOpenAIClass: false }
  }
  if (!data || data.state !== 'connected') {
    return {
      enabled: false,
      tooltip: 'Configure AI provider first.',
      loading: false,
      isOpenAIClass: false,
    }
  }
  return {
    enabled: true,
    tooltip: null,
    loading: false,
    isOpenAIClass: data.provider === 'openai' || data.provider === 'custom',
  }
}
