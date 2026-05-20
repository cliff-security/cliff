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
 * Collapsed single-modal UX (ADR-0048):
 * 1. Click button → POST /connect → mount the GithubAppDeviceFlowModal
 *    directly. No install tab is opened up front — the device flow
 *    comes first.
 * 2. The modal walks the user through authorizing the device code.
 * 3. Once authorized, the backend discovers the GitHub App installation
 *    from the user access token (``GET /user/installations``). The
 *    modal then either connects automatically (one installation),
 *    shows an "Install the Cliff GitHub App" affordance (none), or a
 *    picker (several) — all in the same modal.
 *
 * Discovery removes the dependency on the App's redirect callback, so
 * onboarding works on any self-host port (B02).
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
    // ADR-0048 — go straight to the device-flow modal. The App-install
    // step (when needed) is a secondary affordance the modal surfaces
    // after the device is authorized, not a tab opened up front.
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

