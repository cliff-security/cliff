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
 * Flow:
 * 1. Click "Connect GitHub" → POST /connect.
 * 2. Open the App install URL in a new tab so the user can pick repos.
 * 3. Open the device-flow modal so the user can also enter the user_code.
 * 4. Modal polls /status; on 'connected' it auto-dismisses.
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
  // back with ?github_setup=complete.
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
    setResponse(r)
    if (typeof window !== 'undefined') {
      window.open(r.install_url, '_blank', 'noopener,noreferrer')
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
