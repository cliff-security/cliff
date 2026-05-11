/**
 * GitHub App + Device Flow client (ADR-0035, IMPL-0010).
 *
 * Mirrors the four backend endpoints under /api/integrations/github.
 * The frontend never talks to GitHub directly — it polls our backend's
 * /status endpoint while our backend polls GitHub's token endpoint.
 */

import { useEffect, useRef, useState } from 'react'
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
  /** Force an immediate poll tick on the backend and return the
   * resulting status. Used after the user clicks Authorize on
   * github.com so we don't wait for the next scheduled poll
   * (which can be 5-60s out depending on GitHub's slow_down). */
  pollNow: () =>
    request<DeviceFlowStatusResponse>(
      '/api/integrations/github/poll-now',
      { method: 'POST', body: '{}' },
    ),
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

export function useGithubAppPollNow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => githubAppApi.pollNow(),
    onSuccess: (data) => {
      // Push the poll result straight into the cache so the modal's
      // useGithubAppStatus picks it up without waiting for its next
      // refetch interval.
      qc.setQueryData(['github-app', 'status'], data)
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
 * Decides whether to open the device-flow modal on page mount.
 *
 * Two triggers, both treated as "resume the in-flight flow":
 *
 * 1. ``?github_setup=complete`` on the URL — the backend's /setup
 *    callback fired after a successful App install on GitHub.
 * 2. ``/status`` reports an in-flight state (``installation_pending``
 *    or ``device_pending``) regardless of URL — covers the
 *    "App was already installed on this user's account, GitHub
 *    skipped /setup and dropped them on the Configure page" path. If
 *    the user navigates back to OpenSec without our query param, we
 *    still know the backend has an open device flow and we should
 *    show the modal so they can finish authorizing.
 *
 * ``?github_setup=updated`` cleans the URL silently (the user
 * reconfigured an already-connected install — no modal needed).
 *
 * Lives at this layer (not inside the connect button) so the post-
 * install resume flow works regardless of whether any specific CTA is
 * currently mounted - once the install creates an integration row the
 * catalog button unmounts, but the page still renders.
 */
export function useGithubAppResumeOnReturn(): {
  response: DeviceFlowConnectResponse | null
  clear: () => void
} {
  const connect = useGithubAppConnect()
  const [response, setResponse] = useState<DeviceFlowConnectResponse | null>(
    null,
  )
  const triggered = useRef(false)

  // Probe the backend for an in-flight state. Enabled unconditionally —
  // if there's no flow in progress we get a 404 (mapped to ``null``)
  // and skip. The status polling continues at 2s after the modal
  // opens, since the same query key is shared with the modal's hook.
  const { data: status } = useGithubAppStatus({ enabled: true })

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (triggered.current) return
    if (connect.isPending || response) return

    const url = new URL(window.location.href)
    const setupStatus = url.searchParams.get('github_setup')

    const cleanUrl = () => {
      url.searchParams.delete('github_setup')
      url.searchParams.delete('integration_id')
      url.searchParams.delete('reason')
      // ``url.toString()`` already serialises the hash from the original
      // URL — appending ``window.location.hash`` would double it
      // (#integrations#integrations).
      window.history.replaceState({}, '', url.toString())
    }

    // 'updated' — silent URL cleanup, no modal.
    if (setupStatus === 'updated') {
      triggered.current = true
      cleanUrl()
      return
    }

    // Trigger the modal if EITHER the URL says we just came back from
    // a successful install OR the backend already has an in-flight
    // flow we should resume.
    const inflight =
      status?.status === 'installation_pending' ||
      status?.status === 'device_pending'
    if (setupStatus !== 'complete' && !inflight) return

    triggered.current = true
    void (async () => {
      try {
        const r = await connect.mutateAsync({})
        setResponse(r)
      } finally {
        cleanUrl()
      }
    })()
    // We deliberately retrigger when ``status?.status`` arrives so the
    // backend-only resume case (no query param) still fires once /status
    // resolves. The ``triggered`` ref guards against double-firing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.status])

  return {
    response,
    clear: () => {
      setResponse(null)
      // Allow a fresh trigger if the user starts a new flow later.
      triggered.current = false
    },
  }
}
