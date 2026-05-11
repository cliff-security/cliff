/**
 * AI provider onboarding client (ADR-0036, IMPL-0011).
 *
 * Mirrors the backend routes under /api/integrations/ai.
 */

import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from './client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AIProvider = 'openrouter' | 'anthropic' | 'openai' | 'custom'
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
  override_model: string | null
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
  disconnect: async (): Promise<void> => {
    const resp = await fetch('/api/integrations/ai/disconnect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
    if (!resp.ok) {
      const text = await resp.text()
      throw new Error(`${resp.status}: ${text}`)
    }
  },
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

const STATUS_KEY = ['ai-provider', 'status'] as const

/** Read-only status hook — drives every agent-button gate via useAIRequired. */
export function useAIProviderStatus() {
  return useQuery({
    queryKey: STATUS_KEY,
    queryFn: aiProviderApi.status,
    // Background poll keeps "configured" state fresh after a successful
    // OAuth handshake without forcing a hard reload.
    refetchInterval: false,
    staleTime: 30_000,
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
      qc.invalidateQueries({ queryKey: ['ai-provider'] })
    },
  })
}

export function useByok() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: aiProviderApi.byok,
    onSuccess: (data) => {
      qc.setQueryData(STATUS_KEY, data)
      qc.invalidateQueries({ queryKey: ['ai-provider'] })
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

/**
 * Poll the OAuth status endpoint every 1s while *sessionId* is set and the
 * status is non-terminal. Calls *onTerminal* once with the final status.
 * Hard 5-min timeout matches the backend listener TTL.
 */
export function useOpenRouterPolling(
  sessionId: string | null,
  onTerminal: (status: OpenRouterStatusResponse) => void,
) {
  const startedAt = useRef<number | null>(null)
  const TIMEOUT_MS = 5 * 60 * 1000
  const qc = useQueryClient()

  const query = useQuery({
    queryKey: ['ai-provider', 'openrouter', sessionId],
    queryFn: () => aiProviderApi.openrouterStatus(sessionId as string),
    enabled: !!sessionId,
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
    }
  }, [sessionId])

  useEffect(() => {
    if (!query.data) return
    if (query.data.status !== 'waiting') {
      onTerminal(query.data)
      qc.invalidateQueries({ queryKey: STATUS_KEY })
    }
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
