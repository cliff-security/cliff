/**
 * GitHub App + Device Flow client (ADR-0035, IMPL-0010).
 *
 * Mirrors the four backend endpoints under /api/integrations/github.
 * The frontend never talks to GitHub directly — it polls our backend's
 * /status endpoint while our backend polls GitHub's token endpoint.
 */

import { useEffect, useState } from 'react'
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
  /**
   * Initiate (or resume) the device flow.
   * Pass *returnTo* to make the post-install redirect target a specific
   * SPA path (e.g. '/onboarding/connect'). Defaults to /settings.
   */
  connect: (opts?: { returnTo?: string }) => {
    const qs = opts?.returnTo
      ? `?return_to=${encodeURIComponent(opts.returnTo)}`
      : ''
    return request<DeviceFlowConnectResponse>(
      `/api/integrations/github/connect${qs}`,
      { method: 'POST', body: '{}' },
    )
  },
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
    mutationFn: (opts?: { returnTo?: string }) => githubAppApi.connect(opts),
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

/**
 * Detects ``?github_setup=complete`` on the current URL (set by the
 * backend's /setup callback after a successful App install on GitHub),
 * fires the idempotent /connect once to fetch the in-flight state, and
 * returns the device-flow response so the page can mount the modal.
 *
 * Lives at this layer (not inside the connect button) so the post-
 * install resume flow works regardless of whether any specific CTA is
 * currently mounted - e.g. once the install creates an integration row
 * the catalog button unmounts, but the page still renders, so a
 * page-level effect is the only safe place.
 */
export function useGithubAppResumeOnReturn(): {
  response: DeviceFlowConnectResponse | null
  clear: () => void
} {
  const connect = useGithubAppConnect()
  const [response, setResponse] = useState<DeviceFlowConnectResponse | null>(
    null,
  )
  useEffect(() => {
    if (typeof window === 'undefined') return
    const url = new URL(window.location.href)
    const setupStatus = url.searchParams.get('github_setup')
    // 'complete' = first install, open the device-flow modal.
    // 'updated' = user reconfigured an existing install, no modal needed
    //             (already authorized). Just clean the URL silently.
    // Anything else = ignore.
    if (setupStatus !== 'complete' && setupStatus !== 'updated') return
    if (connect.isPending || response) return

    const cleanUrl = () => {
      url.searchParams.delete('github_setup')
      url.searchParams.delete('integration_id')
      url.searchParams.delete('reason')
      // ``url.toString()`` already serialises the hash from the original
      // URL — appending ``window.location.hash`` would double it
      // (#integrations#integrations).
      window.history.replaceState({}, '', url.toString())
    }

    if (setupStatus === 'updated') {
      cleanUrl()
      return
    }

    void (async () => {
      try {
        const r = await connect.mutateAsync({})
        setResponse(r)
      } finally {
        cleanUrl()
      }
    })()
    // Fire once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return { response, clear: () => setResponse(null) }
}
