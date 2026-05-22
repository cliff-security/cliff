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

export interface PushAccessDiagnoseResponse {
  can_push: boolean
  reason: string
  repo_url: string
  /** ISO 8601 UTC. Backend echoes the *probe* time, not the response
   *  time — so a cached result still shows "checked 2 min ago". */
  checked_at: string
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
  /** Probe push access against the currently-configured GitHub repo.
   *  Backend caches for 5 minutes; pass ``refresh: true`` to force a
   *  fresh GitHub call after the user fixes the App on github.com. */
  diagnose: (opts?: { refresh?: boolean }) => {
    const qs = opts?.refresh ? '?refresh=1' : ''
    return request<PushAccessDiagnoseResponse>(
      `/api/integrations/github/diagnose${qs}`,
    )
  },
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


/**
 * Probe push access for the configured GitHub repo (IMPL-0018 / B35c).
 *
 * Returns ``data: null`` on 404 so the badge can render nothing without
 * a thrown error bubbling through React Query's ``isError`` state. Every
 * other failure mode bubbles as a normal query error so the operator
 * gets a visible signal instead of a phantom "everything looks fine".
 *
 * Stale window matches the backend cache (5 minutes) so the SPA and the
 * server agree on what "fresh" means. Background refetch on focus is
 * disabled — the user comes back to the Settings page after fixing the
 * App on github.com, and the explicit Refresh button is the natural
 * way to re-probe.
 */
export function useGitHubPushDiagnose() {
  return useQuery({
    queryKey: ['github-app', 'diagnose'],
    queryFn: async (): Promise<PushAccessDiagnoseResponse | null> => {
      try {
        return await githubAppApi.diagnose()
      } catch (err) {
        // 404 = GitHub not configured. The badge renders nothing in
        // this state — don't surface a query error to the caller, since
        // the absence of a GitHub integration is normal pre-onboarding.
        if (err instanceof Error && err.message.startsWith('404:')) {
          return null
        }
        throw err
      }
    },
    // 5 min — matches the server-side cache so we don't re-fetch faster
    // than the backend is willing to re-probe.
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
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
 * Triggers ONLY on the ``?github_setup=complete`` or
 * ``?github_setup=updated`` query parameter — i.e. the user just came
 * back from the backend's /setup callback after a successful install
 * or configure-save on github.com. In both cases the modal opens so
 * the user can finish authorising the device.
 *
 * We deliberately do NOT auto-open the modal whenever the backend
 * has an in-flight row, because that fires PRE-install too (immediately
 * after the user clicks Install but before they've actually done
 * anything on GitHub). The "App already installed → GitHub diverts to
 * Configure → setup_url never fires" recovery case is handled by an
 * explicit "Resume install" affordance on the page rather than a
 * surprise modal — see ``manualResume`` in ConnectRepo / IntegrationSettings.
 *
 * Lives at this layer (not inside the connect button) so the post-
 * install resume flow works regardless of whether any specific CTA is
 * currently mounted - once the install creates an integration row the
 * catalog button unmounts, but the page still renders.
 */
export function useGithubAppResumeOnReturn(): {
  response: DeviceFlowConnectResponse | null
  clear: () => void
  /** Manually open the modal (e.g. from a "Resume install" button).
   *  Calls the idempotent /connect to fetch the in-flight code and
   *  mounts the modal in the same way the URL-driven path does. */
  resume: () => Promise<void>
} {
  const connect = useGithubAppConnect()
  const [response, setResponse] = useState<DeviceFlowConnectResponse | null>(
    null,
  )
  const triggered = useRef(false)

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (triggered.current) return
    if (connect.isPending || response) return

    const url = new URL(window.location.href)
    const setupStatus = url.searchParams.get('github_setup')
    if (setupStatus !== 'complete' && setupStatus !== 'updated') return

    triggered.current = true

    const cleanUrl = () => {
      url.searchParams.delete('github_setup')
      url.searchParams.delete('integration_id')
      url.searchParams.delete('reason')
      // ``url.toString()`` already serialises the hash from the original
      // URL — appending ``window.location.hash`` would double it
      // (#integrations#integrations).
      window.history.replaceState({}, '', url.toString())
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

  const resume = async () => {
    if (connect.isPending || response) return
    const r = await connect.mutateAsync({})
    setResponse(r)
  }

  return {
    response,
    clear: () => {
      setResponse(null)
      // Allow a fresh trigger if the user starts a new flow later.
      triggered.current = false
    },
    resume,
  }
}
