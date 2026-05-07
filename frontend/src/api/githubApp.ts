/**
 * GitHub App + Device Flow client (ADR-0035, IMPL-0010).
 *
 * Mirrors the four backend endpoints under /api/integrations/github.
 * The frontend never talks to GitHub directly — it polls our backend's
 * /status endpoint while our backend polls GitHub's token endpoint.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from './client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type DeviceFlowPollingStatus =
  | 'installation_pending'
  | 'device_pending'
  | 'connected'
  | 'expired'
  | 'denied'
  | 'rate_limited'
  | 'error'

export interface DeviceFlowConnectResponse {
  user_code: string
  verification_uri: string
  expires_in: number
  interval: number
  install_url: string
}

export interface DeviceFlowStatusResponse {
  status: DeviceFlowPollingStatus
  user_code: string | null
  expires_at: string | null
  installation_id: number | null
  github_login: string | null
  error: string | null
}

export interface DeviceFlowDisconnectResponse {
  status: 'disconnected'
  manual_revoke_url: string
}

// ---------------------------------------------------------------------------
// Raw API
// ---------------------------------------------------------------------------

export const githubAppApi = {
  connect: () =>
    request<DeviceFlowConnectResponse>('/api/integrations/github/connect', {
      method: 'POST',
      body: '{}',
    }),
  status: () =>
    request<DeviceFlowStatusResponse>('/api/integrations/github/status'),
  disconnect: () =>
    request<DeviceFlowDisconnectResponse>(
      '/api/integrations/github/disconnect',
      { method: 'POST', body: '{}' },
    ),
}

// ---------------------------------------------------------------------------
// React Query hooks
// ---------------------------------------------------------------------------

export function useGithubAppConnect() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => githubAppApi.connect(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['github-app', 'status'] })
    },
  })
}

/**
 * Polls /status while *enabled* is true. The backend reports terminal
 * states ('connected' | 'expired' | 'denied' | 'error') — the caller
 * disables polling once one of those arrives.
 *
 * 404 means no flow has ever been started; we surface that as
 * ``status: null`` so the UI renders the "Connect GitHub" button.
 */
export function useGithubAppStatus(opts: {
  enabled?: boolean
  intervalMs?: number
}) {
  const { enabled = false, intervalMs = 2000 } = opts
  return useQuery({
    queryKey: ['github-app', 'status'],
    queryFn: async (): Promise<DeviceFlowStatusResponse | null> => {
      try {
        return await githubAppApi.status()
      } catch (err) {
        if (err instanceof Error && err.message.startsWith('404:')) {
          return null
        }
        throw err
      }
    },
    enabled,
    refetchInterval: (query) => {
      const data = query.state.data as DeviceFlowStatusResponse | null
      if (!data) return false
      const terminal: DeviceFlowPollingStatus[] = [
        'connected',
        'expired',
        'denied',
        'error',
      ]
      return terminal.includes(data.status) ? false : intervalMs
    },
  })
}

export function useGithubAppDisconnect() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => githubAppApi.disconnect(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['github-app', 'status'] })
      qc.invalidateQueries({ queryKey: ['integrations'] })
    },
  })
}
