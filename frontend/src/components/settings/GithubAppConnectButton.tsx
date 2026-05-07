import { useEffect, useState } from 'react'
import {
  useGithubAppConnect,
  useGithubAppDisconnect,
  type DeviceFlowConnectResponse,
} from '@/api/githubApp'
import { GithubAppDeviceFlowModal } from './GithubAppDeviceFlowModal'

/**
 * Single-button entry point for the GitHub App + Device Flow onboarding.
 *
 * Single-tab UX (deliberate — multi-tab is confusing):
 * 1. Click button → POST /connect → navigate this tab to the GitHub
 *    install URL.
 * 2. User picks repos on github.com and clicks Install.
 * 3. GitHub redirects to /api/integrations/github/setup, which 302s
 *    back to /settings?github_setup=complete#integrations.
 * 4. This component re-mounts, the useEffect detects the query param,
 *    re-fetches the in-flight state via /connect (idempotent), and
 *    opens the modal with the user code + a prominent "Authorize on
 *    GitHub" CTA.
 * 5. Modal polls /status; on 'connected' it auto-dismisses.
 */
export function GithubAppConnectButton({
  className = '',
  label = 'Connect GitHub',
}: {
  className?: string
  label?: string
}) {
  const connect = useGithubAppConnect()
  const disconnect = useGithubAppDisconnect()
  const [response, setResponse] = useState<DeviceFlowConnectResponse | null>(
    null,
  )

  // Re-open the device-flow modal automatically when GitHub redirects
  // back with ?github_setup=complete. This is what makes the single-tab
  // UX feel seamless: the user lands back on Settings and the next
  // step (authorize on GitHub) immediately appears.
  useEffect(() => {
    if (typeof window === 'undefined') return
    const url = new URL(window.location.href)
    if (url.searchParams.get('github_setup') !== 'complete') return
    if (connect.isPending || response) return
    void (async () => {
      try {
        const r = await connect.mutateAsync()
        setResponse(r)
      } finally {
        url.searchParams.delete('github_setup')
        url.searchParams.delete('integration_id')
        window.history.replaceState({}, '', url.toString())
      }
    })()
    // We deliberately fire this once on mount; the connect mutation hook is
    // stable so the lint exception is intentional.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleClick = async () => {
    const r = await connect.mutateAsync()
    if (typeof window !== 'undefined') {
      // Same-tab navigation. After the user installs on github.com,
      // GitHub will redirect back to our setup endpoint, which 302s
      // back here with ?github_setup=complete; the useEffect picks it
      // up and opens the modal automatically.
      window.location.href = r.install_url
    }
  }

  const handleTryAgain = async () => {
    await disconnect.mutateAsync().catch(() => undefined)
    setResponse(null)
    await handleClick()
  }

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        disabled={connect.isPending}
        className={
          className ||
          'inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-primary hover:bg-primary/90 transition-colors disabled:opacity-60'
        }
      >
        <span className="material-symbols-outlined text-base">
          rocket_launch
        </span>
        {connect.isPending ? 'Starting...' : label}
      </button>
      {response && (
        <GithubAppDeviceFlowModal
          connect={response}
          onDismiss={() => setResponse(null)}
          onTryAgain={handleTryAgain}
        />
      )}
    </>
  )
}
