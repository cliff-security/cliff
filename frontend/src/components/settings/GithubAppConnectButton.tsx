import { useState } from 'react'
import {
  useGithubAppConnect,
  useGithubAppDisconnect,
  type DeviceFlowConnectResponse,
} from '@/api/githubApp'
import { GithubAppDeviceFlowModal } from './GithubAppDeviceFlowModal'

/**
 * Single-button entry point for the GitHub App + Device Flow onboarding.
 *
 * Single-modal UX (ADR-0048):
 * 1. Click button → POST /connect → mount the GithubAppDeviceFlowModal.
 * 2. The modal walks the user through authorizing the device code.
 * 3. The moment the backend's poller catches the user access token the
 *    integration is connected and the modal dismisses — the token IS
 *    the connection.
 *
 * The device flow has no inbound callback, so onboarding works on any
 * self-host port or behind a reverse proxy (B02). Installing the Cliff
 * GitHub App on a repo is a separate, always-available affordance on the
 * Integrations page — not a step in this flow.
 */
export function GithubAppConnectButton({
  className = '',
  label = 'Connect GitHub',
  returnTo,
}: {
  className?: string
  label?: string
  /**
   * SPA path to land on after the install + authorize round-trip
   * completes. Used by the onboarding flow to keep the user on
   * /onboarding/connect instead of bouncing through Settings.
   * Defaults to /settings (server-side).
   */
  returnTo?: string
}) {
  const connect = useGithubAppConnect()
  const disconnect = useGithubAppDisconnect()
  const [response, setResponse] = useState<DeviceFlowConnectResponse | null>(
    null,
  )

  // Note: detection of ``?github_setup=complete`` (the post-install
  // resume) lives at the page level in IntegrationSettings via
  // useGithubAppResumeOnReturn — the button isn't guaranteed to be
  // mounted at that point (catalog tile unmounts once an integration
  // row exists), so the page is the only safe owner of that effect.

  const handleClick = async () => {
    // ADR-0048 — go straight to the device-flow modal. Installing the
    // App on a repo is a separate, always-available affordance on the
    // Integrations page, not a step in this flow.
    const r = await connect.mutateAsync({ returnTo })
    setResponse(r)
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

